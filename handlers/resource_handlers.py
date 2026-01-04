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

