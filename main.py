import logging
from concurrent import futures

import grpc

from config.settings import validate_config
from identity.user_manager import AzureUserManager
from identity.group_manager import AzureGroupManager
from identity.rbac_manager import AzureRBACManager
from clean_resources.resource_finder import ResourceFinder
from clean_resources.resource_deleter import ResourceDeleter
from handlers.identity_handlers import IdentityHandlers
from handlers.cost_handlers import CostHandlers
from handlers.resource_handlers import ResourceHandlers
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class CloudAdapterServicer(pb2_grpc.CloudAdapterServicer):
    """
    Main gRPC servicer that delegates to specialized handlers.
    Handlers are organized by domain: identity, cost, and resource management.
    """
    
    def __init__(self) -> None:
        self.user_manager = AzureUserManager()
        self.group_manager = AzureGroupManager()
        self.rbac_manager = AzureRBACManager()
        self.resource_finder = ResourceFinder()
        self.resource_deleter = ResourceDeleter()
        
        self.identity_handler = IdentityHandlers(
            user_manager=self.user_manager,
            group_manager=self.group_manager,
            rbac_manager=self.rbac_manager,
            resource_finder=self.resource_finder,
            resource_deleter=self.resource_deleter,
        )
        self.cost_handler = CostHandlers()
        self.resource_handler = ResourceHandlers(
            rbac_manager=self.rbac_manager,
            resource_finder=self.resource_finder,
            resource_deleter=self.resource_deleter,
        )
    
    def GetStatus(self, request, context):
        """Health check endpoint."""
        return self.identity_handler.get_status(request, context)
    
    def GroupExists(self, request, context):
        """Check if group exists in Entra ID."""
        return self.identity_handler.group_exists(request, context)
    
    def CreateGroupWithLeaders(self, request, context):
        """Create group with leaders and assign RBAC roles."""
        return self.identity_handler.create_group_with_leaders(request, context)
    
    def CreateUsersForGroup(self, request, context):
        """Create users and add them to existing group."""
        return self.identity_handler.create_users_for_group(request, context)
    
    def RemoveGroup(self, request, context):
        """Remove group and all its members."""
        return self.identity_handler.remove_group(request, context)
    
    def GetTotalCostForGroup(self, request, context):
        """Returns total cost for a group for the specified period."""
        return self.cost_handler.get_total_cost_for_group(request, context)
    
    def GetTotalCostsForAllGroups(self, request, context):
        """Returns costs for all groups."""
        return self.cost_handler.get_total_costs_for_all_groups(request, context)
    
    def GetTotalCost(self, request, context):
        """Returns total Azure subscription cost."""
        return self.cost_handler.get_total_cost(request, context)
    
    def GetGroupCostWithServiceBreakdown(self, request, context):
        """Returns group cost with service breakdown."""
        return self.cost_handler.get_group_cost_with_service_breakdown(request, context)
    
    def GetTotalCostWithServiceBreakdown(self, request, context):
        """Returns total Azure cost with service breakdown."""
        return self.cost_handler.get_total_cost_with_service_breakdown(request, context)
    
    def GetGroupCostsLast6MonthsByService(self, request, context):
        """Returns group costs for last 6 months grouped by service."""
        return self.cost_handler.get_group_costs_last_6_months_by_service(request, context)
    
    def GetGroupMonthlyCostsLast6Months(self, request, context):
        """Returns monthly costs for last 6 months for a group."""
        return self.cost_handler.get_group_monthly_costs_last_6_months(request, context)
    
    def GetAvailableServices(self, request, context):
        """Returns list of available resource types based on configured RBAC roles."""
        return self.resource_handler.get_available_services(request, context)
    
    def GetResourceCount(self, request, context):
        """Returns count of resources with tag Group=<groupName> for specific resource type."""
        return self.resource_handler.get_resource_count(request, context)
    
    def CleanupGroupResources(self, request, context):
        """Removes all Azure resources associated with a group."""
        return self.resource_handler.cleanup_group_resources(request, context)
    
    def AssignPolicies(self, request, context):
        """Assigns RBAC policies to a group or user."""
        return self.identity_handler.assign_policies(request, context)
    
    def UpdateGroupLeaders(self, request, context):
        """Updates leaders for an existing group (synchronizes: removes old, adds new)."""
        return self.identity_handler.update_group_leaders(request, context)


def serve():
    """Starts the gRPC server."""
    validate_config()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_CloudAdapterServicer_to_server(CloudAdapterServicer(), server)
    server.add_insecure_port("[::]:50053")
    logger.info("[AzureAdapter] gRPC server started on port 50053")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
