"""
Resource management handlers.
Handles resource operations: GetAvailableServices, GetResourceCount, CleanupGroupResources.
"""

import logging

import grpc

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
            context.set_details("Pole resourceType nie może być puste (np. 'vm', 'storage').")
            return pb2.ResourceCountResponse()
        
        try:
            # Find resources by group tag
            resources = self.resource_finder.find_resources_by_tags({"Group": group_name})
            # Filter by service type
            count = sum(1 for r in resources if (r.get("service") or "").lower() == resource_type)
            return pb2.ResourceCountResponse(count=count)
        except Exception as e:
            logger.error(f"[GetResourceCount] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.ResourceCountResponse()
    
    def cleanup_group_resources(self, request, context):
        """
        Usuwa wszystkie zasoby Azure związane z grupą (VMs, storage, etc.).
        Backend expects this method (called during group cleanup).
        """
        group_name: str = request.groupName
        normalized_group_name = normalize_name(group_name)

        try:
            # Find resources tagged with group name
            resources = self.resource_finder.find_resources_by_tags({"Group": normalized_group_name})
            
            if not resources:
                response = pb2.CleanupGroupResponse()
                response.success = True
                response.message = f"No resources found for group '{normalized_group_name}'"
                logger.info(f"No resources found for group '{normalized_group_name}'")
                return response
            
            # Delete resources
            deleted_resources = []
            for resource in resources:
                try:
                    result_msg = self.resource_deleter.delete_resource(resource)
                    deleted_resources.append(result_msg)
                    logger.info(f"Deleted resource: {result_msg}")
                except Exception as e:
                    logger.error(f"Error deleting resource {resource.get('name', 'unknown')}: {e}", exc_info=True)
                    # Continue with other resources
            
            response = pb2.CleanupGroupResponse()
            response.success = True
            response.deletedResources.extend(deleted_resources)
            response.message = f"Cleanup completed for group '{normalized_group_name}'. Deleted {len(deleted_resources)} resources."
            logger.info(f"Cleaned up {len(deleted_resources)} resources for group '{normalized_group_name}'")
            return response

        except Exception as e:
            logger.error(f"[CleanupGroupResources] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            response = pb2.CleanupGroupResponse()
            response.success = False
            response.message = str(e)
            return response

