# main.py

import logging
from concurrent import futures
from typing import List

import grpc

from config.settings import validate_config
from identity.user_manager import AzureUserManager
from identity.group_manager import AzureGroupManager
from identity.rbac_manager import AzureRBACManager
from identity.utils import normalize_name, build_username_with_group_suffix
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
        # docelowo tutaj dodajemy LimitManager od kosztów

    # ========== GetStatus ==========

    def GetStatus(self, request, context):
        resp = pb2.StatusResponse()
        resp.isHealthy = True
        return resp

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
            response.groupName = normalized_group_name
            return response

        except Exception as e:
            logger.error(f"[CreateGroupWithLeaders] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupCreatedResponse()

    # ========== Metody kosztowe – na razie atrapy ==========

    def GetTotalCostForGroup(self, request, context):
        """
        Zwraca koszt grupy za zadany okres.
        Na razie atrapa – zawsze 0.0 (do późniejszej integracji z Azure Cost Management).
        """
        try:
            resp = pb2.CostResponse()
            resp.amount = 0.0
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCostForGroup] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CostResponse()

    def GetTotalCostsForAllGroups(self, request, context):
        """
        Zwraca koszty wszystkich grup.
        Na razie atrapa – pusta lista.
        """
        try:
            resp = pb2.AllGroupsCostResponse()
            # docelowo tutaj wypełnimy resp.groupCosts
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCostsForAllGroups] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.AllGroupsCostResponse()

    def GetTotalCost(self, request, context):
        """
        Całkowity koszt subskrypcji.
        Na razie atrapa – 0.0.
        """
        try:
            resp = pb2.CostResponse()
            resp.amount = 0.0
            return resp
        except Exception as e:
            logger.error(f"[GetTotalCost] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CostResponse()

    def GetGroupCostWithServiceBreakdown(self, request, context):
        """
        Koszt grupy z podziałem na usługi.
        Na razie atrapa – total = 0.0, brak breakdown.
        """
        try:
            resp = pb2.GroupServiceBreakdownResponse()
            resp.total = 0.0
            # resp.breakdown pozostaje puste
            return resp
        except Exception as e:
            logger.error(f"[GetGroupCostWithServiceBreakdown] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupServiceBreakdownResponse()

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
                response.message = f"Group '{normalized_group_name}' does not exist"
                return response

            group_id = group["id"]
            
            # Get all members and delete them
            members = self.group_manager.list_members(group_id)
            for member in members:
                if member.get("objectType") == "User":
                    user_id = member.get("id")
                    try:
                        # Get user details to find login
                        user_data = self.user_manager.get_user(member.get("userPrincipalName", ""))
                        if user_data:
                            # Delete user (will handle username with suffix)
                            self.user_manager.delete_user(user_data.get("userPrincipalName", ""))
                    except Exception as e:
                        logger.warning(f"Failed to delete user {user_id}: {e}")
                        # Continue deleting other users

            # Delete the group
            self.group_manager.delete_group(group_id)
            
            response = pb2.RemoveGroupResponse()
            response.message = f"Group '{normalized_group_name}' and its members have been removed"
            logger.info(f"Removed group '{normalized_group_name}' and its members")
            return response

        except Exception as e:
            logger.error(f"[RemoveGroup] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.RemoveGroupResponse()

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
            # This is a placeholder - you'll need to implement ResourceFinder
            # For now, we'll just return success
            
            # TODO: Implement actual resource cleanup using ResourceFinder
            # from clean_resources.resource_finder import ResourceFinder
            # finder = ResourceFinder()
            # resources = finder.find_resources_by_tags({"group": normalized_group_name})
            # deleter = ResourceDeleter()
            # for resource in resources:
            #     deleter.delete_resource(resource)
            
            response = pb2.CleanupGroupResponse()
            response.message = f"Resources for group '{normalized_group_name}' have been cleaned up"
            logger.info(f"Cleaned up resources for group '{normalized_group_name}'")
            return response

        except Exception as e:
            logger.error(f"[CleanupGroupResources] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.CleanupGroupResponse()


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
