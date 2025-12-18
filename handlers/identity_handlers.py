"""
Identity management handlers.
Handles user and group operations: GetStatus, GroupExists, CreateGroupWithLeaders, 
CreateUsersForGroup, RemoveGroup.
"""

import logging
import time
from typing import List

import grpc

from identity.user_manager import AzureUserManager
from identity.group_manager import AzureGroupManager
from identity.rbac_manager import AzureRBACManager
from identity.utils import normalize_name, build_username_with_group_suffix
from cost_monitoring import limit_manager as cost_manager
from protos import adapter_interface_pb2 as pb2

logger = logging.getLogger(__name__)


class IdentityHandlers:
    """Handlers for identity-related RPC methods."""
    
    def __init__(
        self,
        user_manager: AzureUserManager,
        group_manager: AzureGroupManager,
        rbac_manager: AzureRBACManager,
        resource_finder=None,
        resource_deleter=None,
    ):
        self.user_manager = user_manager
        self.group_manager = group_manager
        self.rbac_manager = rbac_manager
        self.resource_finder = resource_finder
        self.resource_deleter = resource_deleter
    
    def get_status(self, request, context):
        """
        Health check endpoint.
        Sprawdza czy kluczowe komponenty są zainicjalizowane i dostępne.
        Zgodnie z kontraktem Jira: zwraca true/false bez wyjątków na zewnątrz.
        """
        try:
            # Sprawdź czy komponenty są zainicjalizowane
            if not hasattr(self, 'user_manager') or self.user_manager is None:
                logger.error("[GetStatus] user_manager not initialized")
                resp = pb2.StatusResponse()
                resp.isHealthy = False
                return resp
            
            if not hasattr(self, 'group_manager') or self.group_manager is None:
                logger.error("[GetStatus] group_manager not initialized")
                resp = pb2.StatusResponse()
                resp.isHealthy = False
                return resp
            
            if not hasattr(self, 'rbac_manager') or self.rbac_manager is None:
                logger.error("[GetStatus] rbac_manager not initialized")
                resp = pb2.StatusResponse()
                resp.isHealthy = False
                return resp
            
            # Check resource_finder if it was provided (optional dependency)
            if hasattr(self, 'resource_finder'):
                if self.resource_finder is None:
                    logger.error("[GetStatus] resource_finder not initialized")
                    resp = pb2.StatusResponse()
                    resp.isHealthy = False
                    return resp
            
            # Check resource_deleter if it was provided (optional dependency)
            if hasattr(self, 'resource_deleter'):
                if self.resource_deleter is None:
                    logger.error("[GetStatus] resource_deleter not initialized")
                    resp = pb2.StatusResponse()
                    resp.isHealthy = False
                    return resp
            
            # Sprawdź czy kluczowe klienty Azure mogą być utworzone
            try:
                from azure_clients import get_credential, get_graph_client, get_cost_client
                
                credential = get_credential()
                if credential is None:
                    logger.error("[GetStatus] Failed to create credential")
                    resp = pb2.StatusResponse()
                    resp.isHealthy = False
                    return resp
                
                graph_client = get_graph_client()
                if graph_client is None:
                    logger.error("[GetStatus] Failed to create Graph client")
                    resp = pb2.StatusResponse()
                    resp.isHealthy = False
                    return resp
                
                cost_client = get_cost_client()
                if cost_client is None:
                    logger.error("[GetStatus] Failed to create Cost Management client")
                    resp = pb2.StatusResponse()
                    resp.isHealthy = False
                    return resp
                
            except Exception as e:
                logger.error(f"[GetStatus] Failed to initialize Azure clients: {e}", exc_info=True)
                resp = pb2.StatusResponse()
                resp.isHealthy = False
                return resp
            
            # Sprawdź czy cost_manager jest dostępny
            try:
                if not hasattr(cost_manager, 'get_total_cost_for_group'):
                    logger.error("[GetStatus] cost_manager.get_total_cost_for_group not available")
                    resp = pb2.StatusResponse()
                    resp.isHealthy = False
                    return resp
                
                cost_manager_instance = cost_manager.LimitManager()
                if cost_manager_instance is None:
                    logger.error("[GetStatus] Failed to create LimitManager instance")
                    resp = pb2.StatusResponse()
                    resp.isHealthy = False
                    return resp
                
            except Exception as e:
                logger.error(f"[GetStatus] Failed to initialize cost_manager: {e}", exc_info=True)
                resp = pb2.StatusResponse()
                resp.isHealthy = False
                return resp
            
            # Wszystkie checki przeszły
            resp = pb2.StatusResponse()
            resp.isHealthy = True
            return resp
            
        except Exception as e:
            logger.error(f"[GetStatus] Unexpected error: {e}", exc_info=True)
            resp = pb2.StatusResponse()
            resp.isHealthy = False
            return resp
    
    def group_exists(self, request, context):
        """
        Sprawdza, czy grupa o podanej nazwie istnieje w Entra ID.
        Normalizuje nazwę przed wyszukiwaniem (spaces → dashes).
        """
        group_name: str = request.groupName
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
    
    def create_users_for_group(self, request, context):
        """
        Tworzy użytkowników i dodaje ich do istniejącej grupy.
        Dodaje suffix grupy do username (matches AWS adapter format).
        
        Zgodnie z kontraktem Jira:
        - Kontynuuje mimo błędów części użytkowników
        - Sprawdza duplikacje przed dodaniem
        - Message: dokładnie "Users successfully added" (lub zawiera ten tekst)
        """
        group_name: str = request.groupName
        users: List[str] = list(request.users)
        normalized_group_name = normalize_name(group_name)

        try:
            # Sprawdź czy grupa istnieje (z retry logic dla replikacji Azure AD)
            max_attempts = 5
            delay_seconds = 3.0
            group = None
            
            for attempt in range(1, max_attempts + 1):
                group = self.group_manager.get_group_by_name(normalized_group_name)
                if group:
                    break
                
                if attempt < max_attempts:
                    logger.warning(
                        f"[CreateUsersForGroup] Group '{group_name}' not found "
                        f"(attempt {attempt}/{max_attempts}) – waiting {delay_seconds}s for replication..."
                    )
                    time.sleep(delay_seconds)
            
            if not group:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(
                    f"Group '{group_name}' does not exist in Azure AD (checked {max_attempts} times)"
                )
                resp = pb2.CreateUsersForGroupResponse()
                resp.message = ""
                return resp

            group_id = group["id"]
            
            # 1. Deduplikacja listy users
            unique_users = list(dict.fromkeys(users))
            if len(unique_users) != len(users):
                logger.info(
                    f"[CreateUsersForGroup] Deduplicated users: {len(users)} -> {len(unique_users)}"
                )
            
            # 2. Pobierz istniejących członków grupy
            existing_members = {}
            try:
                members = self.group_manager.list_members(group_id)
                for member in members:
                    if member.get("objectType") == "User":
                        member_id = member.get("id")
                        if member_id:
                            existing_members[member_id] = member.get("userPrincipalName", "")
            except Exception as e:
                logger.warning(
                    f"[CreateUsersForGroup] Failed to list existing members: {e}. "
                    "Continuing without duplicate check."
                )
            
            # 3. Zbieraj sukcesy i błędy per użytkownik
            succeeded_users: List[str] = []
            failed_users: List[tuple[str, str]] = []
            already_members: List[str] = []
            
            for login in unique_users:
                username_with_suffix = build_username_with_group_suffix(login, group_name)
                user_id = None
                
                try:
                    # Tworzymy użytkownika
                    try:
                        user_id = self.user_manager.create_user(
                            login=login,
                            display_name=username_with_suffix,
                            group_name=group_name,
                        )
                    except Exception as e:
                        error_msg = str(e)
                        if "already exists" in error_msg.lower() or "ObjectConflict" in error_msg:
                            logger.warning(
                                f"[CreateUsersForGroup] User {login} may already exist: {error_msg}"
                            )
                            failed_users.append((login, f"User creation failed: {error_msg}"))
                            continue
                        else:
                            failed_users.append((login, f"User creation failed: {error_msg}"))
                            logger.error(f"[CreateUsersForGroup] create_user({login}) failed: {e}")
                            continue
                    
                    # Sprawdź czy użytkownik już jest członkiem grupy
                    if user_id in existing_members:
                        already_members.append(login)
                        logger.info(
                            f"[CreateUsersForGroup] User {login} already member of group, skipping add_member"
                        )
                        succeeded_users.append(login)
                        continue
                    
                    # Dodaj do grupy
                    try:
                        self.group_manager.add_member(group_id, user_id)
                        succeeded_users.append(login)
                        logger.info(f"[CreateUsersForGroup] Successfully added user {login} to group")
                    except Exception as e:
                        error_msg = str(e)
                        if (
                            "already exists" in error_msg.lower() 
                            or "already a member" in error_msg.lower()
                            or "Request_BadRequest" in error_msg
                        ):
                            already_members.append(login)
                            succeeded_users.append(login)
                            logger.info(
                                f"[CreateUsersForGroup] User {login} already member (tolerated): {error_msg}"
                            )
                        else:
                            failed_users.append((login, f"Failed to add to group: {error_msg}"))
                            logger.error(
                                f"[CreateUsersForGroup] add_member failed for {login}: {e}"
                            )
                
                except Exception as e:
                    failed_users.append((login, f"Unexpected error: {str(e)}"))
                    logger.error(f"[CreateUsersForGroup] Unexpected error for {login}: {e}", exc_info=True)
                    continue
            
            # 4. Przygotuj response zgodnie z kontraktem
            response = pb2.CreateUsersForGroupResponse()
            response.message = "Users successfully added"
            
            # 5. Loguj detale błędów
            if failed_users:
                failed_logins = [login for login, _ in failed_users]
                fail_reasons = [reason for _, reason in failed_users]
                logger.warning(
                    f"[CreateUsersForGroup] x-failed-users: {failed_logins}, "
                    f"x-fail-reasons: {fail_reasons}"
                )
            
            if already_members:
                logger.info(
                    f"[CreateUsersForGroup] x-already-members: {already_members}"
                )
            
            logger.info(
                f"[CreateUsersForGroup] Summary: {len(succeeded_users)} succeeded, "
                f"{len(failed_users)} failed, {len(already_members)} already members"
            )
            
            return response

        except Exception as e:
            logger.error(f"[CreateUsersForGroup] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Failed to create users: {str(e)}")
            resp = pb2.CreateUsersForGroupResponse()
            resp.message = ""
            return resp
    
    def create_group_with_leaders(self, request, context):
        """
        Tworzy grupę + liderów, zapisuje ich jako członków grupy
        oraz ustawia liderów jako właścicieli (owners) tej grupy.

        Używa resourceTypes (lista) do przypisania odpowiednich uprawnień RBAC
        Dodaje suffix grupy do username liderów (matches AWS adapter format).
        """
        group_name: str = request.groupName
        resource_types: List[str] = list(request.resourceTypes)  # Changed from resourceType to resourceTypes
        leaders: List[str] = list(request.leaders)
        
        # Backend może wysłać listę, ale używamy pierwszego typu (zgodnie z AWS adapter behavior)
        resource_type: str = resource_types[0] if resource_types else ""

        normalized_group_name = normalize_name(group_name)

        try:
            # Tworzymy grupę w Entra ID
            group_id = self.group_manager.create_group(name=normalized_group_name)
            created_leaders: List[tuple[str, str]] = []

            # Assign RBAC role based on resource type
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

            for leader_login in leaders:
                username_with_suffix = build_username_with_group_suffix(
                    leader_login, group_name
                )

                # Tworzymy lidera
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

                # Dodajemy lidera jako właściciela grupy
                try:
                    self.group_manager.add_owner(group_id, leader_id)
                except Exception as e:
                    logger.warning(
                        f"[CreateGroupWithLeaders] add_owner failed for "
                        f"leader={username_with_suffix}, group_id={group_id}: {e}"
                    )

                created_leaders.append((leader_login, leader_id))

            response = pb2.GroupCreatedResponse()
            response.groupName = group_name  # Return original name, not normalized
            return response

        except Exception as e:
            logger.error(f"[CreateGroupWithLeaders] Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupCreatedResponse()
    
    def remove_group(self, request, context):
        """
        Usuwa grupę i wszystkich jej członków (użytkowników).
        Backend expects this method (called when group is deleted).
        """
        group_name: str = request.groupName
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
    
    def assign_policies(self, request, context):
        """
        Assigns RBAC policies to a group or user.
        Backend uses this to assign resource access permissions.
        """
        try:
            resource_types = list(request.resourceTypes)
            group_name = request.groupName if request.groupName else None
            user_name = request.userName if request.userName else None
            
            if not resource_types:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details("Resource types list cannot be empty")
                return pb2.AssignPoliciesResponse(success=False, message="Resource types list cannot be empty")
            
            if not group_name and not user_name:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details("Either groupName or userName must be provided")
                return pb2.AssignPoliciesResponse(success=False, message="Either groupName or userName must be provided")
            
            # Assign RBAC roles for each resource type
            assigned_roles = []
            for resource_type in resource_types:
                try:
                    if group_name:
                        normalized_group_name = normalize_name(group_name)
                        group = self.group_manager.get_group_by_name(normalized_group_name)
                        if not group:
                            logger.warning(f"Group '{normalized_group_name}' not found for policy assignment")
                            continue
                        
                        success = self.rbac_manager.assign_role_to_group(
                            resource_type=resource_type,
                            group_id=group["id"]
                        )
                        if success:
                            assigned_roles.append(f"{resource_type}->{group_name}")
                            logger.info(f"Assigned RBAC role for '{resource_type}' to group '{group_name}'")
                        else:
                            logger.warning(f"Failed to assign RBAC role for '{resource_type}' to group '{group_name}'")
                    
                    # Note: User-level policy assignment not implemented yet
                    # Azure RBAC typically uses group-based assignments
                    if user_name:
                        logger.warning(f"User-level policy assignment not yet implemented for '{user_name}'")
                
                except Exception as e:
                    logger.error(f"Error assigning policy for resource type '{resource_type}': {e}", exc_info=True)
                    # Continue with other resource types
            
            if assigned_roles:
                response = pb2.AssignPoliciesResponse(
                    success=True,
                    message=f"Policies assigned successfully: {', '.join(assigned_roles)}"
                )
                return response
            else:
                response = pb2.AssignPoliciesResponse(
                    success=False,
                    message="No policies were assigned. Check if group exists and resource types are valid."
                )
                return response
        
        except Exception as e:
            logger.error(f"[AssignPolicies] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.AssignPoliciesResponse(success=False, message=str(e))

