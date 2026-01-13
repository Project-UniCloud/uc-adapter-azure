"""
Resource management handlers.
Handles resource operations: GetAvailableServices, GetResourceCount, CleanupGroupResources.
"""

import logging

import grpc

from azure_clients import get_resource_client
from identity.rbac_manager import AzureRBACManager
from identity.utils import normalize_name
from clean_resources.resource_finder import ResourceFinder
from clean_resources.resource_deleter import ResourceDeleter
from protos import adapter_interface_pb2 as pb2

logger = logging.getLogger(__name__)


class ResourceHandlers:
    """Handlers for resource-related RPC methods."""
    
    def __init__(
        self,
        rbac_manager: AzureRBACManager,
        resource_finder: ResourceFinder,
        resource_deleter: ResourceDeleter,
    ):
        self.rbac_manager = rbac_manager
        self.resource_finder = resource_finder
        self.resource_deleter = resource_deleter
    
    def get_available_services(self, request, context):
        """
        Returns list of available resource types based on configured RBAC roles.
        Azure equivalent of AWS GetAvailableServices.
        """
        try:
            # Get available resource types from RBAC manager
            services_list = list(self.rbac_manager.RESOURCE_TYPE_ROLES.keys())
            response = pb2.GetAvailableServicesResponse()
            response.services.extend(services_list)
            return response
        except Exception as e:
            logger.error(f"[GetAvailableServices] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GetAvailableServicesResponse()
    
    def get_resource_count(self, request, context):
        """
        Returns count of resources with tag Group=<groupName> for specific resource type.
        """
        group_name = request.groupName
        resource_type = (request.resourceType or "").strip().lower()
        
        if not resource_type:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("resourceType cannot be empty (e.g., 'vm', 'storage')")
            return pb2.ResourceCountResponse()
        
        try:
            resources = self.resource_finder.find_resources_by_tags({"Group": group_name})
            count = sum(1 for r in resources if (r.get("service") or "").lower() == resource_type)
            return pb2.ResourceCountResponse(count=count)
        except Exception as e:
            logger.error(f"[GetResourceCount] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.ResourceCountResponse()
    
    def get_group_resources_list(self, request, context):
        """
        Returns a detailed list of resources for a given group.
        
        Maps Azure resources to ResourceDetail format matching AWS adapter.
        """
        group_name: str = request.groupName
        normalized_group_name = normalize_name(group_name)
        
        logger.info(f"[GetGroupResourcesList] Request for group '{group_name}' (normalized: '{normalized_group_name}')")
        
        try:
            # Find resources by Group tag
            resources = self.resource_finder.find_resources_by_tags({"Group": normalized_group_name})
            
            if not resources:
                logger.info(f"[GetGroupResourcesList] No resources found for group '{group_name}'")
                response = pb2.GetGroupResourcesListResponse()
                response.success = True
                response.message = "No resources found"
                return response
            
            # Map resources to ResourceDetail format
            grpc_resources = []
            for resource in resources:
                # Get additional resource details (tags, status)
                resource_id = resource.get("id", "")
                resource_name = resource.get("name", "N/A")
                resource_type = resource.get("type", "")
                service = resource.get("service", "unknown")
                
                # Try to get tags and status from Azure Resource Manager
                tags = {}
                status = "unknown"
                try:
                    from azure_clients import get_resource_client
                    resource_client = get_resource_client()
                    
                    # Parse resource ID to get resource group and provider
                    if resource_id and "/resourceGroups/" in resource_id:
                        parts = resource_id.split("/resourceGroups/")
                        if len(parts) > 1:
                            rg_parts = parts[1].split("/")
                            resource_group = rg_parts[0]
                            provider_parts = parts[0].split("/providers/")
                            if len(provider_parts) > 1:
                                provider = provider_parts[1]
                                
                                # Get resource details (tags and status)
                                try:
                                    generic_resource = resource_client.resources.get_by_id(
                                        resource_id=resource_id,
                                        api_version="2021-04-01"
                                    )
                                    tags = generic_resource.tags or {}
                                    
                                    # Try to get status from properties
                                    if hasattr(generic_resource, 'properties') and generic_resource.properties:
                                        if 'provisioningState' in generic_resource.properties:
                                            status = generic_resource.properties['provisioningState'].lower()
                                    
                                    # For VMs, try to get power state
                                    if "Microsoft.Compute/virtualMachines" in resource_type:
                                        try:
                                            from azure_clients import get_compute_client
                                            compute_client = get_compute_client()
                                            instance_view = compute_client.virtual_machines.instance_view(
                                                resource_group_name=resource_group,
                                                vm_name=resource_name
                                            )
                                            for status_obj in instance_view.statuses:
                                                if status_obj.code.startswith("PowerState/"):
                                                    status = status_obj.code.split("/")[1].lower()
                                                    break
                                        except Exception:
                                            pass  # Fallback to provisioningState if available
                                except Exception as e:
                                    logger.debug(f"[GetGroupResourcesList] Could not get detailed info for {resource_id}: {e}")
                                    # Continue with basic info
                except Exception as e:
                    logger.debug(f"[GetGroupResourcesList] Error getting resource details: {e}")
                
                # Extract resource ID (short form - just the name)
                resource_short_id = resource_name
                
                # Get name from tag or use resource name
                display_name = tags.get("Name", resource_name)
                
                # Get created_by from tag
                created_by = tags.get("CreatedBy", tags.get("User", "Unknown"))
                
                # Map resource type to human-readable format
                human_readable_type = self._map_resource_type_to_readable(resource_type)
                
                # Create ResourceDetail
                resource_detail = pb2.ResourceDetail(
                    resource_global_id=resource_id,
                    name=display_name,
                    type=human_readable_type,
                    service=service,
                    created_by=created_by,
                    resource_id=resource_short_id,
                    status=status
                )
                grpc_resources.append(resource_detail)
            
            logger.info(f"[GetGroupResourcesList] Found {len(grpc_resources)} resources for group '{group_name}'")
            
            response = pb2.GetGroupResourcesListResponse()
            response.success = True
            response.resources.extend(grpc_resources)
            response.message = f"Successfully retrieved {len(grpc_resources)} resources"
            return response
            
        except Exception as e:
            logger.error(f"[GetGroupResourcesList] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            response = pb2.GetGroupResourcesListResponse()
            response.success = False
            response.message = str(e)
            return response
    
    def _map_resource_type_to_readable(self, resource_type: str) -> str:
        """Maps Azure resource type to human-readable format."""
        if not resource_type:
            return "Unknown Resource"
        
        rtype_lower = resource_type.lower()
        
        if "virtualmachine" in rtype_lower:
            return "Virtual Machine"
        if "storageaccount" in rtype_lower:
            return "Storage Account"
        if "networkinterface" in rtype_lower:
            return "Network Interface"
        if "publicipaddress" in rtype_lower:
            return "Public IP Address"
        if "virtualnetwork" in rtype_lower or "vnet" in rtype_lower:
            return "Virtual Network"
        if "sqlserver" in rtype_lower or "sqldatabase" in rtype_lower:
            return "SQL Database"
        if "keyvault" in rtype_lower:
            return "Key Vault"
        if "appservice" in rtype_lower or "web" in rtype_lower:
            return "App Service"
        if "container" in rtype_lower or "aks" in rtype_lower:
            return "Container Service"
        
        # Extract from format: "Microsoft.Service/ResourceType"
        if "/" in resource_type:
            parts = resource_type.split("/")
            if len(parts) > 1:
                readable = parts[-1]
                # Convert camelCase to Title Case
                import re
                readable = re.sub(r'([A-Z])', r' \1', readable).strip()
                return readable or "Azure Resource"
        
        return "Azure Resource"
    
    def delete_resource(self, request, context):
        """
        Deletes a single Azure resource by its resource_global_id.
        
        Parses Azure Resource ID and calls resource_deleter.delete_resource().
        """
        resource_global_id: str = request.resource_global_id
        
        if not resource_global_id or not resource_global_id.strip():
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Resource global ID cannot be empty")
            response = pb2.DeleteResourceResponse()
            response.success = False
            response.message = "Resource global ID cannot be empty"
            return response
        
        logger.info(f"[DeleteResource] Request to delete resource: '{resource_global_id}'")
        
        try:
            # Parse Azure Resource ID
            # Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}
            if not resource_global_id.startswith("/subscriptions/"):
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(f"Invalid Azure Resource ID format: {resource_global_id}")
                response = pb2.DeleteResourceResponse()
                response.success = False
                response.message = f"Invalid Azure Resource ID format: {resource_global_id}"
                return response
            
            # Extract resource group
            if "/resourceGroups/" not in resource_global_id:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(f"Resource ID missing resource group: {resource_global_id}")
                response = pb2.DeleteResourceResponse()
                response.success = False
                response.message = f"Resource ID missing resource group: {resource_global_id}"
                return response
            
            parts = resource_global_id.split("/resourceGroups/")
            if len(parts) < 2:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(f"Could not parse resource group from ID: {resource_global_id}")
                response = pb2.DeleteResourceResponse()
                response.success = False
                response.message = f"Could not parse resource group from ID: {resource_global_id}"
                return response
            
            rg_parts = parts[1].split("/")
            resource_group = rg_parts[0]
            
            # Extract provider and resource type
            provider_parts = parts[0].split("/providers/")
            if len(provider_parts) < 2:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(f"Could not parse provider from ID: {resource_global_id}")
                response = pb2.DeleteResourceResponse()
                response.success = False
                response.message = f"Could not parse provider from ID: {resource_global_id}"
                return response
            
            # Extract resource type and name
            # Format after /providers/: Microsoft.Service/ResourceType/resourceName
            provider_path = provider_parts[1]
            provider_path_parts = provider_path.split("/")
            
            # Resource type is usually the first two parts: Microsoft.Service/ResourceType
            resource_type = "/".join(provider_path_parts[:2]) if len(provider_path_parts) >= 2 else provider_path
            
            # Resource name is the last part
            resource_name = provider_path_parts[-1] if provider_path_parts else resource_global_id.split("/")[-1]
            
            # Extract service name from resource type
            service = self.resource_finder._extract_service_name(resource_type)
            
            # Construct resource dict for deleter
            resource_dict = {
                "id": resource_global_id,
                "name": resource_name,
                "type": resource_type,
                "service": service,
                "resource_group": resource_group
            }
            
            # Call deleter
            result_msg = self.resource_deleter.delete_resource(resource_dict)
            
            # Determine success based on result message
            is_success = "Error" not in result_msg and "Skipping" not in result_msg
            
            response = pb2.DeleteResourceResponse()
            response.success = is_success
            response.message = result_msg
            
            if is_success:
                logger.info(f"[DeleteResource] Successfully deleted resource: {resource_global_id}")
            else:
                logger.warning(f"[DeleteResource] Failed to delete resource: {resource_global_id} - {result_msg}")
            
            return response
            
        except Exception as e:
            logger.error(f"[DeleteResource] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            response = pb2.DeleteResourceResponse()
            response.success = False
            response.message = str(e)
            return response
    
    def cleanup_group_resources(self, request, context):
        """
        Removes all Azure resources associated with group (VMs, storage, etc.).
        
        Strategy:
        1. Find and delete resources by Group tags
        2. Fallback: delete Resource Group rg-{group_name} if no tagged resources found
        """
        group_name: str = request.groupName
        normalized_group_name = normalize_name(group_name)

        try:
            deleted_resources = []
            
            resources = self.resource_finder.find_resources_by_tags({"Group": normalized_group_name})
            logger.info(
                f"[CleanupGroupResources] Found {len(resources)} resources with tag Group={normalized_group_name}"
            )
            
            for resource in resources:
                try:
                    result_msg = self.resource_deleter.delete_resource(resource)
                    deleted_resources.append(result_msg)
                    logger.info(f"[CleanupGroupResources] Deleted resource: {result_msg}")
                except Exception as e:
                    logger.error(
                        f"[CleanupGroupResources] Error deleting resource {resource.get('name', 'unknown')}: {e}",
                        exc_info=True
                    )
            
            if not resources:
                resource_group_name = f"rg-{normalized_group_name}"
                logger.info(
                    f"[CleanupGroupResources] No resources found by tags. "
                    f"Trying fallback: delete Resource Group '{resource_group_name}'"
                )
                
                try:
                    resource_client = get_resource_client()
                    
                    try:
                        rg = resource_client.resource_groups.get(resource_group_name)
                        if rg:
                            logger.info(
                                f"[CleanupGroupResources] Resource Group '{resource_group_name}' exists. "
                                f"Deleting it (this will delete all resources in the RG)..."
                            )
                            
                            resource_client.resource_groups.begin_delete(resource_group_name).wait()
                            
                            deleted_resources.append(f"Deleted Resource Group: {resource_group_name}")
                            logger.info(
                                f"[CleanupGroupResources] Successfully deleted Resource Group '{resource_group_name}'"
                            )
                    except Exception as e:
                        logger.info(
                            f"[CleanupGroupResources] Resource Group '{resource_group_name}' does not exist. "
                            f"Nothing to clean up."
                        )
                        
                except Exception as e:
                    logger.warning(
                        f"[CleanupGroupResources] Error during fallback Resource Group deletion: {e}",
                        exc_info=True
                    )
            
            if deleted_resources:
                response = pb2.CleanupGroupResponse()
                response.success = True
                response.deletedResources.extend(deleted_resources)
                response.message = (
                    f"Cleanup completed for group '{normalized_group_name}'. "
                    f"Deleted {len(deleted_resources)} resource(s)."
                )
                logger.info(
                    f"[CleanupGroupResources] Cleanup completed for group '{normalized_group_name}'. "
                    f"Deleted {len(deleted_resources)} resource(s)."
                )
                return response
            else:
                response = pb2.CleanupGroupResponse()
                response.success = True
                response.message = f"No resources found for group '{normalized_group_name}' (checked tags and Resource Group)"
                logger.info(
                    f"[CleanupGroupResources] No resources found for group '{normalized_group_name}' "
                    f"(checked tags and Resource Group)"
                )
                return response

        except Exception as e:
            logger.error(f"[CleanupGroupResources] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            response = pb2.CleanupGroupResponse()
            response.success = False
            response.message = str(e)
            return response

