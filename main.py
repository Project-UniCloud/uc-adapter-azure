# main.py

import logging
from concurrent import futures
from typing import List

import grpc

from config.settings import validate_config
from config.policy_manager import PolicyManager
from identity.user_manager import AzureUserManager
from identity.group_manager import AzureGroupManager
from identity.rbac_manager import AzureRBACManager
from identity.utils import normalize_name, build_username_with_group_suffix
from clean_resources.resource_finder import ResourceFinder
from clean_resources.resource_deleter import ResourceDeleter
from cost_monitoring import limit_manager as cost_manager
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
    def __init__(self) -> None:
        self.user_manager = AzureUserManager()
        self.group_manager = AzureGroupManager()
        self.rbac_manager = AzureRBACManager()
        self.policy_manager = PolicyManager(self.rbac_manager)
        self.resource_finder = ResourceFinder()
        self.resource_deleter = ResourceDeleter()

    # ========== GetStatus ==========

    def GetStatus(self, request, context):
        resp = pb2.StatusResponse()
        resp.isHealthy = True
        return resp

    # ========== GetAvailableServices ==========

    def GetAvailableServices(self, request, context):
        """
        Returns list of available resource types based on configured RBAC roles.
        Azure equivalent of AWS GetAvailableServices.
        """
        try:
            services_list = self.policy_manager.get_available_services()
            response = pb2.GetAvailableServicesResponse()
            response.services.extend(services_list)
            return response
        except Exception as e:
            logger.error(f"[GetAvailableServices] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GetAvailableServicesResponse()

    # ========== GroupExists ==========

    def GroupExists(self, request, context):
        """
        Sprawdza, czy grupa o podanej nazwie istnieje w Entra ID.
        Normalizuje nazwę przed wyszukiwaniem (spaces → dashes).
        """
        group_name: str = request.groupName
        # Normalize group name (matches AWS adapter behavior)
        normalized_name = normalize_name(group_name)

        try:
            group = self.group_manager.get_group_by_name(normalized_name)
            resp = pb2.GroupExistsResponse()
            resp.exists = group is not None
            return resp
        except Exception as e:
            logger.error(f"[GroupExists] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupExistsResponse()

    # ========== CreateUsersForGroup ==========

    def CreateUsersForGroup(self, request, context):
        """
        Tworzy użytkowników i dodaje ich do istniejącej grupy.
        Dodaje suffix grupy do username (matches AWS adapter format).

        request:
          - groupName: nazwa grupy w Entra ID
          - users: repeated string (loginy użytkowników)
        """
        group_name: str = request.groupName
        users: List[str] = list(request.users)
        # Normalize group name (matches AWS adapter behavior)
        normalized_group_name = normalize_name(group_name)

        try:
            group = self.group_manager.get_group_by_name(normalized_group_name)
            if not group:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(
                    f"Group '{normalized_group_name}' does not exist in Azure AD"
                )
                return pb2.CreateUsersForGroupResponse()

            group_id = group["id"]
            created: List[tuple[str, str]] = []

            for login in users:
                # Build username with group suffix (matches AWS adapter format)
                username_with_suffix = build_username_with_group_suffix(login, group_name)
                
                # Tworzymy użytkownika z hasłem = group_name (matches AWS adapter behavior)
                try:
                    user_id = self.user_manager.create_user(
                        login=login,
                        display_name=username_with_suffix,
                        group_name=group_name,  # This adds suffix and sets password
                    )
                except Exception as e:
                    # rollback utworzonych do tej pory użytkowników
                    for created_login, _uid in created:
                        try:
                            # Delete using the username with suffix
                            self.user_manager.delete_user(build_username_with_group_suffix(created_login, group_name))
                        except Exception:
                            logger.warning(
                                f"[CreateUsersForGroup] rollback delete_user({created_login}) failed"
                            )
                    logger.error(f"[CreateUsersForGroup] create_user({login}) failed: {e}")
                    raise

                # Dodajemy do grupy
                try:
                    self.group_manager.add_member(group_id, user_id)
                except Exception as e:
                    # rollback bieżącego i wszystkich poprzednich
                    try:
                        self.user_manager.delete_user(username_with_suffix)
                    except Exception:
                        logger.warning(
                            f"[CreateUsersForGroup] rollback delete_user({username_with_suffix}) failed"
                        )
                    for created_login, _uid in created:
                        try:
                            self.user_manager.delete_user(build_username_with_group_suffix(created_login, group_name))
                        except Exception:
                            logger.warning(
                                f"[CreateUsersForGroup] rollback delete_user({created_login}) failed"
                            )
                    logger.error(
                        f"[CreateUsersForGroup] add_member failed for login={username_with_suffix}, group_id={group_id}: {e}"
                    )
                    raise

                created.append((login, user_id))

            response = pb2.CreateUsersForGroupResponse()
            response.message = (
                f"Created {len(users)} users in group '{normalized_group_name}' (Azure AD)."
            )
            return response

        except Exception as e:
            logger.error(f"[CreateUsersForGroup] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CreateUsersForGroupResponse()

    # ========== CreateGroupWithLeaders ==========

    def CreateGroupWithLeaders(self, request, context):
        """
        Tworzy grupę + liderów, zapisuje ich jako członków grupy
        oraz ustawia liderów jako właścicieli (owners) tej grupy.

        Używa resourceType do przypisania odpowiednich uprawnień RBAC (matches AWS adapter behavior).
        Dodaje suffix grupy do username liderów (matches AWS adapter format).
        """
        group_name: str = request.groupName
        resource_type: str = request.resourceType  # np. "vm", "storage"
        leaders: List[str] = list(request.leaders)

        # Normalize group name (matches AWS adapter behavior)
        normalized_group_name = normalize_name(group_name)

        try:
            # Tworzymy grupę w Entra ID
            group_id = self.group_manager.create_group(name=normalized_group_name)
            created_leaders: List[tuple[str, str]] = []

            # Assign RBAC role based on resource type (matches AWS adapter behavior)
            try:
                success = self.rbac_manager.assign_role_to_group(
                    resource_type=resource_type,
                    group_id=group_id,
                )
                if success:
                    logger.info(
                        f"Assigned RBAC role for resource type '{resource_type}' "
                        f"to group '{normalized_group_name}'"
                    )
                else:
                    logger.warning(
                        f"RBAC role assignment for resource type '{resource_type}' "
                        f"to group '{normalized_group_name}' failed or was skipped"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to assign RBAC role for resource type '{resource_type}' "
                    f"to group '{normalized_group_name}': {e}"
                )
                # Kontynuujemy – grupa ma działać nawet bez RBAC

            for leader_login in leaders:
                # Build username with group suffix (matches AWS adapter format)
                username_with_suffix = build_username_with_group_suffix(
                    leader_login, group_name
                )

                # Tworzymy lidera (AzureUserManager sam doda suffix i wygeneruje hasło)
                try:
                    leader_id = self.user_manager.create_user(
                        login=leader_login,
                        display_name=username_with_suffix,
                        group_name=group_name,
                    )
                except Exception as e:
                    # rollback liderów + grupy
                    for login, _uid in created_leaders:
                        try:
                            self.user_manager.delete_user(
                                build_username_with_group_suffix(login, group_name)
                            )
                        except Exception:
                            logger.warning(
                                f"[CreateGroupWithLeaders] rollback "
                                f"delete_user({login}) failed"
                            )
                    try:
                        self.group_manager.delete_group(group_id)
                    except Exception:
                        logger.warning(
                            f"[CreateGroupWithLeaders] rollback "
                            f"delete_group({group_id}) failed"
                        )
                    logger.error(
                        f"[CreateGroupWithLeaders] create_user({leader_login}) "
                        f"failed: {e}"
                    )
                    raise

                # Dodajemy lidera jako członka grupy
                try:
                    self.group_manager.add_member(group_id, leader_id)
                except Exception as e:
                    # rollback bieżącego lidera, wcześniejszych liderów i grupy
                    try:
                        self.user_manager.delete_user(username_with_suffix)
                    except Exception:
                        logger.warning(
                            f"[CreateGroupWithLeaders] rollback "
                            f"delete_user({username_with_suffix}) failed"
                        )
                    for login, _uid in created_leaders:
                        try:
                            self.user_manager.delete_user(
                                build_username_with_group_suffix(login, group_name)
                            )
                        except Exception:
                            logger.warning(
                                f"[CreateGroupWithLeaders] rollback "
                                f"delete_user({login}) failed"
                            )
                    try:
                        self.group_manager.delete_group(group_id)
                    except Exception:
                        logger.warning(
                            f"[CreateGroupWithLeaders] rollback "
                            f"delete_group({group_id}) failed"
                        )
                    logger.error(
                        f"[CreateGroupWithLeaders] add_member failed for "
                        f"leader={username_with_suffix}, group_id={group_id}: {e}"
                    )
                    raise

                # Dodajemy lidera jako właściciela grupy (owner).
                # Jeśli się nie uda – logujemy ostrzeżenie, ale nie wywalamy całej operacji.
                try:
                    self.group_manager.add_owner(group_id, leader_id)
                except Exception as e:
                    logger.warning(
                        f"[CreateGroupWithLeaders] add_owner failed for "
                        f"leader={username_with_suffix}, group_id={group_id}: {e}"
                    )

                created_leaders.append((leader_login, leader_id))

            response = pb2.GroupCreatedResponse()
            # Backend expects original group name with spaces (e.g., "AI 2024L")
            # GroupUniqueName.fromString() validates format: ".* \\d{4}[ZL]"
            response.groupName = group_name  # Return original name, not normalized
            return response

        except Exception as e:
            logger.error(f"[CreateGroupWithLeaders] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupCreatedResponse()

    # ========== GetResourceCount ==========

    def GetResourceCount(self, request, context):
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

    # ========== Cost Monitoring Methods ==========

    def GetTotalCostForGroup(self, request, context):
        """
        Returns total cost for a group for the specified period.
        Uses Azure Cost Management API.
        """
        try:
            cost = cost_manager.get_total_cost_for_group(
                group_tag_value=request.groupName,
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.CostResponse()
            resp.amount = cost
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCostForGroup] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CostResponse()

    def GetTotalCostsForAllGroups(self, request, context):
        """
        Returns costs for all groups.
        Uses Azure Cost Management API.
        
        Note: Azure Cost Management API returns normalized group names from tags.
        We need to map them back to original names (with spaces) for backend compatibility.
        Backend expects format "AI 2024L" (with spaces) for GroupUniqueName.fromString().
        """
        try:
            costs_dict = cost_manager.get_total_costs_for_all_groups(
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.AllGroupsCostResponse()
            
            # Map normalized names back to original format (with spaces)
            # Backend expects "AI 2024L" format, not "AI-2024L"
            for normalized_group, cost in costs_dict.items():
                # Try to find original group name by querying Azure AD
                # If not found, attempt to denormalize (dashes -> spaces)
                original_name = self._denormalize_group_name(normalized_group)
                
                group_cost = resp.groupCosts.add()
                group_cost.groupName = original_name
                group_cost.amount = cost
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCostsForAllGroups] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.AllGroupsCostResponse()
    
    def _denormalize_group_name(self, normalized_name: str) -> str:
        """
        Attempts to denormalize group name (dashes -> spaces) for backend compatibility.
        Backend expects format "AI 2024L" (with spaces) for GroupUniqueName.fromString().
        
        This is a best-effort approach. For exact mapping, we would need to query Azure AD
        to get the original group name, but that's expensive. Instead, we try to reverse
        the normalization by replacing dashes with spaces, which works for most cases.
        
        Note: This may not work perfectly for all group names, but should work for
        standard format like "AI-2024L" -> "AI 2024L".
        """
        # Try to find original name by querying Azure AD groups
        try:
            # Query Azure AD for groups matching the normalized name
            group = self.group_manager.get_group_by_name(normalized_name)
            if group:
                # If we find a group, we still need the original name
                # Since Azure AD stores normalized names, we need to reverse the normalization
                # The pattern is usually: "Name-YYYYZ/L" -> "Name YYYYZ/L"
                # We'll replace dashes with spaces, but be careful with the semester suffix
                display_name = group.get("displayName", normalized_name)
                
                # If display name matches normalized, try to reverse normalize
                if display_name == normalized_name:
                    # Pattern: "AI-2024L" -> "AI 2024L"
                    # Replace dashes with spaces, but keep the last part (semester) intact
                    # Semester format: YYYYZ or YYYYL (e.g., "2024L")
                    import re
                    # Match pattern: word-dash-word-dash-YYYYZ/L
                    # We want to replace dashes with spaces, but keep the semester part
                    # Example: "AI-2024L" -> "AI 2024L"
                    # Example: "Test-Group-2024L" -> "Test Group 2024L"
                    # Semester is always at the end: YYYYZ or YYYYL
                    pattern = r'^(.+)-(\d{4}[ZL])$'
                    match = re.match(pattern, normalized_name)
                    if match:
                        name_part = match.group(1)
                        semester = match.group(2)
                        # Replace remaining dashes with spaces
                        denormalized_name = name_part.replace('-', ' ') + ' ' + semester
                        return denormalized_name
                    else:
                        # Fallback: replace all dashes with spaces
                        return normalized_name.replace('-', ' ')
                else:
                    return display_name
            else:
                # Group not found, try to reverse normalize
                import re
                pattern = r'^(.+)-(\d{4}[ZL])$'
                match = re.match(pattern, normalized_name)
                if match:
                    name_part = match.group(1)
                    semester = match.group(2)
                    return name_part.replace('-', ' ') + ' ' + semester
                else:
                    return normalized_name.replace('-', ' ')
        except Exception as e:
            logger.warning(f"Failed to denormalize group name '{normalized_name}': {e}")
            # Fallback: try simple dash-to-space replacement
            import re
            pattern = r'^(.+)-(\d{4}[ZL])$'
            match = re.match(pattern, normalized_name)
            if match:
                name_part = match.group(1)
                semester = match.group(2)
                return name_part.replace('-', ' ') + ' ' + semester
            else:
                return normalized_name.replace('-', ' ')

    def GetTotalCost(self, request, context):
        """
        Returns total Azure subscription cost.
        Uses Azure Cost Management API.
        """
        try:
            cost = cost_manager.get_total_azure_cost(
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.CostResponse()
            resp.amount = cost
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCost] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CostResponse()

    def GetGroupCostWithServiceBreakdown(self, request, context):
        """
        Returns group cost with service breakdown.
        Uses Azure Cost Management API.
        """
        try:
            breakdown = cost_manager.get_group_cost_with_service_breakdown(
                group_tag_value=request.groupName,
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.GroupServiceBreakdownResponse()
            resp.total = breakdown['total']
            for service_name, amount in breakdown['by_service'].items():
                service_cost = resp.breakdown.add()
                service_cost.serviceName = service_name
                service_cost.amount = amount
            return resp
        except Exception as e:
            logger.error(f"[GetGroupCostWithServiceBreakdown] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupServiceBreakdownResponse()

    def GetTotalCostWithServiceBreakdown(self, request, context):
        """
        Returns total Azure cost with service breakdown.
        Uses Azure Cost Management API.
        """
        try:
            result = cost_manager.get_total_cost_with_service_breakdown(
                start_date=request.startDate,
                end_date=request.endDate or None
            )
            resp = pb2.GroupServiceBreakdownResponse()
            resp.total = result['total']
            for service_name, amount in result['by_service'].items():
                entry = resp.breakdown.add()
                entry.serviceName = service_name
                entry.amount = amount
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCostWithServiceBreakdown] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupServiceBreakdownResponse()

    def GetGroupCostsLast6MonthsByService(self, request, context):
        """
        Returns group costs for last 6 months grouped by service.
        Uses Azure Cost Management API.
        """
        group_name = (request.groupName or '').strip()
        if not group_name:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Pole groupName nie może być puste.")
            return pb2.GroupCostMapResponse()
        
        try:
            costs = cost_manager.get_group_cost_last_6_months_by_service(group_tag_value=group_name)
            resp = pb2.GroupCostMapResponse()
            for k, v in costs.items():
                resp.costs[k] = v
            return resp
        except Exception as e:
            logger.error(f"[GetGroupCostsLast6MonthsByService] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupCostMapResponse()

    def GetGroupMonthlyCostsLast6Months(self, request, context):
        """
        Returns monthly costs for last 6 months for a group.
        Uses Azure Cost Management API.
        """
        group_name = (request.groupName or '').strip()
        if not group_name:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Pole groupName nie może być puste.")
            return pb2.GroupMonthlyCostsResponse()
        
        try:
            costs = cost_manager.get_group_monthly_costs_last_6_months(group_tag_value=group_name)
            resp = pb2.GroupMonthlyCostsResponse()
            for month, amount in costs.items():
                resp.monthCosts[month] = amount
            return resp
        except Exception as e:
            logger.error(f"[GetGroupMonthlyCostsLast6Months] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupMonthlyCostsResponse()

    # ========== RemoveGroup ==========

    def RemoveGroup(self, request, context):
        """
        Usuwa grupę i wszystkich jej członków (użytkowników).
        Backend expects this method (called when group is deleted).
        """
        group_name: str = request.groupName
        # Normalize group name (matches AWS adapter behavior)
        normalized_group_name = normalize_name(group_name)

        try:
            group = self.group_manager.get_group_by_name(normalized_group_name)
            if not group:
                # Group doesn't exist - return success (idempotent operation)
                response = pb2.RemoveGroupResponse()
                response.success = True
                response.message = f"Group '{normalized_group_name}' does not exist"
                return response

            group_id = group["id"]
            removed_users = []
            
            # Get all members and delete them
            members = self.group_manager.list_members(group_id)
            for member in members:
                if member.get("objectType") == "User":
                    user_principal_name = member.get("userPrincipalName", "")
                    if user_principal_name:
                        try:
                            # Remove from group first
                            self.group_manager.remove_member(group_id, member.get("id"))
                            # Delete user
                            self.user_manager.delete_user(user_principal_name)
                            removed_users.append(user_principal_name)
                            logger.info(f"Removed user '{user_principal_name}' from group and Azure AD")
                        except Exception as e:
                            logger.warning(f"Failed to delete user {user_principal_name}: {e}")
                            # Continue deleting other users

            # Delete the group
            self.group_manager.delete_group(group_id)
            
            response = pb2.RemoveGroupResponse()
            response.success = True
            response.removedUsers.extend(removed_users)
            response.message = f"Group '{normalized_group_name}' and its members have been removed"
            logger.info(f"Removed group '{normalized_group_name}' and {len(removed_users)} members")
            return response

        except Exception as e:
            logger.error(f"[RemoveGroup] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            response = pb2.RemoveGroupResponse()
            response.success = False
            response.message = str(e)
            return response

    # ========== CleanupGroupResources ==========

    def CleanupGroupResources(self, request, context):
        """
        Usuwa wszystkie zasoby Azure związane z grupą (VMs, storage, etc.).
        Backend expects this method (called during group cleanup).
        """
        group_name: str = request.groupName
        # Normalize group name (matches AWS adapter behavior)
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


def serve():
    validate_config()  # sprawdzi zmienne środowiskowe

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_CloudAdapterServicer_to_server(CloudAdapterServicer(), server)
    # port możesz zostawić 50053 albo dostosować do backendu
    server.add_insecure_port("[::]:50053")
    logger.info("[AzureAdapter] gRPC server started on port 50053")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
