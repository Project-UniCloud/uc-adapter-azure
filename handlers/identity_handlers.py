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
        
        Verifies that key components are initialized and available.
        Returns true/false without raising exceptions.
        """
        try:
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
            
            resp = pb2.StatusResponse()
            resp.isHealthy = True
            return resp
            
        except Exception as e:
            logger.error(f"[GetStatus] Unexpected error: {e}", exc_info=True)
            resp = pb2.StatusResponse()
            resp.isHealthy = False
            return resp
    
    def group_exists(self, request, context):
        """Checks if group with given name exists in Entra ID. Normalizes name before search."""
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
        Creates users and adds them to existing group.
        
        Adds group suffix to username (matches AWS adapter format).
        Continues despite partial user errors. Checks for duplicates before adding.
        Returns message "Users successfully added".
        """
        group_name: str = request.groupName
        users: List[str] = list(request.users)
        normalized_group_name = normalize_name(group_name)

        try:
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
            
            unique_users = list(dict.fromkeys(users))
            if len(unique_users) != len(users):
                logger.info(
                    f"[CreateUsersForGroup] Deduplicated users: {len(users)} -> {len(unique_users)}"
                )
            
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
            
            succeeded_users: List[str] = []
            failed_users: List[tuple[str, str]] = []
            already_members: List[str] = []
            
            for login in unique_users:
                username_with_suffix = build_username_with_group_suffix(login, group_name)
                user_id = None
                
                try:
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
                    
                    if user_id in existing_members:
                        already_members.append(login)
                        logger.info(
                            f"[CreateUsersForGroup] User {login} already member of group, skipping add_member"
                        )
                        succeeded_users.append(login)
                        continue
                    
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
            
            response = pb2.CreateUsersForGroupResponse()
            response.message = "Users successfully added"
            
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
        Creates group and leaders, adds leaders as group members and sets them as owners.
        
        Uses resourceTypes list to assign appropriate RBAC permissions.
        Adds group suffix to leader usernames (matches AWS adapter format).
        """
        group_name: str = request.groupName
        resource_types: List[str] = list(request.resourceTypes)
        leaders: List[str] = list(request.leaders)
        
        resource_type: str = resource_types[0] if resource_types else ""

        normalized_group_name = normalize_name(group_name)

        try:
            group_id, resource_group_name = self.group_manager.create_group(
                name=normalized_group_name,
                create_resource_group=True
            )
            created_leaders: List[tuple[str, str]] = []

            try:
                success, reason = self.rbac_manager.assign_role_to_group(
                    resource_type=resource_type,
                    group_id=group_id,
                )
                if success:
                    logger.info(
                        f"[CreateGroupWithLeaders] Assigned RBAC role for resource type '{resource_type}' "
                        f"to group '{normalized_group_name}'"
                    )
                else:
                    logger.warning(
                        f"[CreateGroupWithLeaders] RBAC role assignment for resource type '{resource_type}' "
                        f"to group '{normalized_group_name}' failed: {reason}"
                    )
            except Exception as e:
                logger.warning(
                    f"[CreateGroupWithLeaders] Exception assigning RBAC role for resource type '{resource_type}' "
                    f"to group '{normalized_group_name}': {e}",
                    exc_info=True
                )

            for leader_login in leaders:
                username_with_suffix = build_username_with_group_suffix(
                    leader_login, group_name
                )

                try:
                    leader_id = self.user_manager.create_user(
                        login=leader_login,
                        display_name=username_with_suffix,
                        group_name=group_name,
                    )
                except Exception as e:
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
        Removes group and all its members (users).
        
        Operation order:
        1. Remove Azure resources (cleanup_group_resources)
        2. Remove users
        3. Remove Entra ID group
        """
        group_name: str = request.groupName
        normalized_group_name = normalize_name(group_name)

        try:
            group = self.group_manager.get_group_by_name(normalized_group_name)
            if not group:
                response = pb2.RemoveGroupResponse()
                response.success = True
                response.message = f"Group '{normalized_group_name}' does not exist"
                return response

            group_id = group["id"]
            removed_users = []
            
            logger.info(
                f"[RemoveGroup] Step 0: Removing RBAC role assignments for group '{normalized_group_name}'..."
            )
            try:
                removed_group_assignments = self.rbac_manager.remove_role_assignments_for_group(group_id)
                logger.info(
                    f"[RemoveGroup] Removed {removed_group_assignments} role assignment(s) for group '{normalized_group_name}'"
                )
            except Exception as e:
                logger.warning(
                    f"[RemoveGroup] Error removing role assignments for group: {e}. "
                    f"Continuing with resource cleanup...",
                    exc_info=True
                )
            
            logger.info(
                f"[RemoveGroup] Step 1: Cleaning up Azure resources for group '{normalized_group_name}'..."
            )
            try:
                resources = self.resource_finder.find_resources_by_tags({"Group": normalized_group_name})
                logger.info(
                    f"[RemoveGroup] Found {len(resources)} resources with tag Group={normalized_group_name}"
                )
                
                for resource in resources:
                    try:
                        result_msg = self.resource_deleter.delete_resource(resource)
                        logger.info(f"[RemoveGroup] Deleted resource: {result_msg}")
                    except Exception as e:
                        logger.warning(
                            f"[RemoveGroup] Error deleting resource {resource.get('name', 'unknown')}: {e}",
                            exc_info=True
                        )
                
                if not resources:
                    resource_group_name = f"rg-{normalized_group_name}"
                    logger.info(
                        f"[RemoveGroup] No resources found by tags. "
                        f"Trying fallback: delete Resource Group '{resource_group_name}'"
                    )
                    try:
                        from azure_clients import get_resource_client
                        resource_client = get_resource_client()
                        try:
                            rg = resource_client.resource_groups.get(resource_group_name)
                            if rg:
                                logger.info(
                                    f"[RemoveGroup] Deleting Resource Group '{resource_group_name}' "
                                    f"(this will delete all resources in the RG)..."
                                )
                                resource_client.resource_groups.begin_delete(resource_group_name).wait()
                                logger.info(
                                    f"[RemoveGroup] Successfully deleted Resource Group '{resource_group_name}'"
                                )
                        except Exception:
                            logger.info(
                                f"[RemoveGroup] Resource Group '{resource_group_name}' does not exist"
                            )
                    except Exception as e:
                        logger.warning(
                            f"[RemoveGroup] Error during fallback Resource Group deletion: {e}",
                            exc_info=True
                        )
                
                logger.info(
                    f"[RemoveGroup] Step 1 completed: Cleaned up Azure resources for group '{normalized_group_name}'"
                )
            except Exception as e:
                logger.error(
                    f"[RemoveGroup] Error during resource cleanup: {e}. "
                    f"Continuing with user and group deletion...",
                    exc_info=True
                )
            
            logger.info(
                f"[RemoveGroup] Step 2: Removing RBAC role assignments for users in group '{normalized_group_name}'..."
            )
            
            user_members = []
            primary_endpoint_count = 0
            import time
            for attempt in range(1, 4):
                try:
                    user_members = self.group_manager.list_user_members(group_id)
                    primary_endpoint_count = len(user_members)
                    if user_members:
                        logger.info(
                            f"[RemoveGroup] Primary endpoint (list_user_members) found {primary_endpoint_count} users "
                            f"in group '{normalized_group_name}' (attempt {attempt}/3)"
                        )
                        break
                    if attempt < 3:
                        delay = 2.0 * attempt
                        logger.info(
                            f"[RemoveGroup] Primary endpoint returned 0 users (attempt {attempt}/3). "
                            f"Waiting {delay}s for Azure AD replication..."
                        )
                        time.sleep(delay)
                except Exception as e:
                    logger.warning(
                        f"[RemoveGroup] Error calling list_user_members (attempt {attempt}/3): {e}",
                        exc_info=True
                    )
                    if attempt < 3:
                        time.sleep(2.0 * attempt)
            
            logger.info(
                f"[RemoveGroup] Step 2.1: Primary endpoint found {len(user_members)} user members "
                f"in group '{normalized_group_name}' (group_id: {group_id})"
            )
            
            for idx, user in enumerate(user_members):
                logger.info(
                    f"[RemoveGroup] User {idx+1}: id={user.get('id')}, "
                    f"userPrincipalName={user.get('userPrincipalName', 'N/A')}"
                )
            
            user_ids_to_remove = []
            
            upn_search_count = 0
            if not user_members:
                logger.warning(
                    f"[RemoveGroup] Step 2.2: Primary endpoint returned 0 members (Azure AD replication delay). "
                    f"Trying fallback: search users by UPN pattern containing '{normalized_group_name}'..."
                )
                try:
                    from config.settings import AZURE_UDOMAIN
                    from azure_clients import get_graph_client
                    graph_client = get_graph_client()
                    
                    filter_pattern = f"-{normalized_group_name}@{AZURE_UDOMAIN}"
                    # Graph API wymaga URL encoding dla filtrów
                    import urllib.parse
                    filter_encoded = urllib.parse.quote(f"endswith(userPrincipalName,'{filter_pattern}')")
                    
                    resp = graph_client.get(f"/users?$filter={filter_encoded}&$select=id,userPrincipalName")
                    if resp.status_code == 200:
                        data = resp.json()
                        fallback_users = data.get("value", [])
                        logger.info(
                            f"[RemoveGroup] Step 2.2: UPN pattern search found {len(fallback_users)} users "
                            f"with pattern '{filter_pattern}'"
                        )
                        for user in fallback_users:
                            upn = user.get("userPrincipalName", "")
                            user_id = user.get("id")
                            if user_id and upn and normalized_group_name in upn:
                                user_members.append({
                                    "id": user_id,
                                    "userPrincipalName": upn
                                })
                                upn_search_count += 1
                                logger.debug(
                                    f"[RemoveGroup] UPN search: Found user '{upn}' (id: {user_id})"
                                )
                        logger.info(
                            f"[RemoveGroup] Step 2.2: UPN pattern search added {upn_search_count} users "
                            f"to removal list"
                        )
                    else:
                        logger.warning(
                            f"[RemoveGroup] Step 2.2: UPN pattern search failed: status={resp.status_code}, "
                            f"response: {resp.text[:200]}"
                        )
                except Exception as e:
                    logger.warning(
                        f"[RemoveGroup] Step 2.2: UPN pattern search error: {e}",
                        exc_info=True
                    )
            
            # Podsumowanie: loguj źródła użytkowników
            total_users_found = len(user_members)
            logger.info(
                f"[RemoveGroup] Step 2 summary: Found {total_users_found} users to remove "
                f"(primary endpoint: {primary_endpoint_count}, UPN search: {upn_search_count})"
            )
            
            if primary_endpoint_count == 0 and upn_search_count > 0:
                logger.warning(
                    f"[RemoveGroup] WARNING: Primary endpoint (list_user_members) returned 0 users, "
                    f"but UPN pattern search found {upn_search_count} users. "
                    f"This may indicate an issue with Graph API /members endpoint or Azure AD replication delays."
                )
            
            for user in user_members:
                user_id = user.get("id")
                user_principal_name = user.get("userPrincipalName", "")
                
                if not user_id:
                    logger.warning(
                        f"[RemoveGroup] User member missing 'id': {user}"
                    )
                    continue
                
                if not user_principal_name:
                    logger.warning(
                        f"[RemoveGroup] User member missing 'userPrincipalName' (id: {user_id}). "
                        f"Trying to get UPN from Graph API..."
                    )
                    try:
                        from azure_clients import get_graph_client
                        graph_client = get_graph_client()
                        user_data = graph_client.get(f"/users/{user_id}?$select=userPrincipalName")
                        if user_data.status_code == 200:
                            user_principal_name = user_data.json().get("userPrincipalName", "")
                            logger.info(
                                f"[RemoveGroup] Retrieved UPN for user {user_id}: {user_principal_name}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"[RemoveGroup] Failed to get UPN for user {user_id}: {e}"
                        )
                
                if user_id and user_principal_name:
                    try:
                        removed_user_assignments = self.rbac_manager.remove_role_assignments_for_user(user_id)
                        logger.info(
                            f"[RemoveGroup] Removed {removed_user_assignments} role assignment(s) "
                            f"for user '{user_principal_name}' (id: {user_id})"
                        )
                        user_ids_to_remove.append((user_id, user_principal_name))
                    except Exception as e:
                        logger.warning(
                            f"[RemoveGroup] Error removing role assignments for user {user_principal_name}: {e}. "
                            f"Continuing with user deletion...",
                            exc_info=True
                        )
                        user_ids_to_remove.append((user_id, user_principal_name))
                else:
                    logger.warning(
                        f"[RemoveGroup] Skipping user member: missing id or userPrincipalName. "
                        f"id={user_id}, userPrincipalName={user_principal_name}"
                    )
            
            logger.info(
                f"[RemoveGroup] Step 3: Removing users from group and deleting users for group '{normalized_group_name}'..."
            )
            for user_id, user_principal_name in user_ids_to_remove:
                try:
                    try:
                        self.group_manager.remove_member(group_id, user_id)
                    except Exception as e:
                        logger.debug(
                            f"[RemoveGroup] Error removing user {user_principal_name} from group (may already be removed): {e}"
                        )
                    
                    import time
                    user_deleted = False
                    for delete_attempt in range(1, 4):
                        try:
                            self.user_manager.delete_user(user_principal_name)
                            user_deleted = True
                            break
                        except Exception as e:
                            error_msg = str(e).lower()
                            if "404" in error_msg or "not found" in error_msg:
                                user_deleted = True
                                logger.info(
                                    f"[RemoveGroup] User '{user_principal_name}' already deleted (idempotent success)"
                                )
                                break
                            if delete_attempt < 3:
                                delay = 2.0 * delete_attempt
                                logger.warning(
                                    f"[RemoveGroup] Error deleting user {user_principal_name} (attempt {delete_attempt}/3): {e}. "
                                    f"Retrying in {delay}s..."
                                )
                                time.sleep(delay)
                            else:
                                raise
                    
                    if user_deleted:
                        removed_users.append(user_principal_name)
                        logger.info(
                            f"[RemoveGroup] Removed user '{user_principal_name}' from group and Azure AD"
                        )
                    else:
                        logger.error(
                            f"[RemoveGroup] Failed to delete user {user_principal_name} after 3 attempts"
                        )
                except Exception as e:
                    logger.warning(
                        f"[RemoveGroup] Failed to delete user {user_principal_name}: {e}",
                        exc_info=True
                    )
            
            logger.info(
                f"[RemoveGroup] Step 4: Deleting Entra ID group '{normalized_group_name}'..."
            )
            self.group_manager.delete_group(group_id)
            
            response = pb2.RemoveGroupResponse()
            response.success = True
            response.removedUsers.extend(removed_users)
            response.message = (
                f"Group '{normalized_group_name}' and its members have been removed. "
                f"Azure resources cleaned up."
            )
            logger.info(
                f"[RemoveGroup] Successfully removed group '{normalized_group_name}' "
                f"and {len(removed_users)} members. Azure resources cleaned up."
            )
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
            
            available_types = set(self.rbac_manager.RESOURCE_TYPE_ROLES.keys())
            invalid_types = [rt for rt in resource_types if rt not in available_types]
            
            if invalid_types:
                available_list = ", ".join(sorted(available_types))
                error_msg = (
                    f"Invalid resource types: {', '.join(invalid_types)}. "
                    f"Available resource types: {available_list}"
                )
                logger.error(f"[AssignPolicies] {error_msg}")
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(error_msg)
                return pb2.AssignPoliciesResponse(success=False, message=error_msg)
            
            deduplicated_types = []
            for rt in resource_types:
                if rt not in deduplicated_types:
                    deduplicated_types.append(rt)
            
            ordered_types = []
            resource_type_order = getattr(self.rbac_manager, 'RESOURCE_TYPE_ORDER', ['network', 'storage', 'vm'])
            
            for rt in resource_type_order:
                if rt in deduplicated_types:
                    ordered_types.append(rt)
            
            for rt in deduplicated_types:
                if rt not in ordered_types:
                    ordered_types.append(rt)
            
            logger.info(
                f"[AssignPolicies] Processing resource types in deterministic order: {ordered_types} "
                f"(original: {resource_types}, deduplicated: {deduplicated_types})"
            )
            
            assigned_roles = []
            failed_assignments = []
            
            for resource_type in ordered_types:
                try:
                    if group_name:
                        normalized_group_name = normalize_name(group_name)
                        group = self.group_manager.get_group_by_name(normalized_group_name)
                        if not group:
                            error_msg = f"Group '{normalized_group_name}' not found for policy assignment"
                            logger.warning(f"[AssignPolicies] {error_msg}")
                            failed_assignments.append(f"{resource_type}: {error_msg}")
                            continue
                        
                        scope = f"/subscriptions/{self.rbac_manager._subscription_id}"
                        logger.info(
                            f"[AssignPolicies] Assigning role for resource_type='{resource_type}' "
                            f"to group='{group_name}' (group_id={group['id']}, scope={scope})"
                        )
                        
                        success, reason = self.rbac_manager.assign_role_to_group(
                            resource_type=resource_type,
                            group_id=group["id"]
                        )
                        if success:
                            assigned_roles.append(f"{resource_type}->{group_name}")
                            logger.info(
                                f"[AssignPolicies] Successfully assigned RBAC role for "
                                f"resource_type='{resource_type}' to group='{group_name}'. "
                                f"group_id={group['id']}, scope={scope}"
                            )
                        else:
                            error_msg = (
                                f"Failed to assign RBAC role for resource_type='{resource_type}' "
                                f"to group='{group_name}': {reason}. "
                                f"group_id={group['id']}, scope={scope}"
                            )
                            logger.warning(f"[AssignPolicies] {error_msg}")
                            failed_assignments.append(f"{resource_type}: {reason}")
                    
                    if user_name:
                        logger.warning(f"[AssignPolicies] User-level policy assignment not yet implemented for '{user_name}'")
                        failed_assignments.append(f"{resource_type}: User-level assignment not implemented")
                
                except Exception as e:
                    error_msg = f"Exception assigning policy for resource type '{resource_type}': {str(e)}"
                    logger.error(f"[AssignPolicies] {error_msg}", exc_info=True)
                    failed_assignments.append(f"{resource_type}: {str(e)}")
                    # Continue with other resource types
            
            if assigned_roles:
                message = f"Policies assigned successfully: {', '.join(assigned_roles)}"
                if failed_assignments:
                    message += f". Some assignments failed: {', '.join(failed_assignments)}"
                response = pb2.AssignPoliciesResponse(success=True, message=message)
                return response
            else:
                # Wszystkie przypisania się nie powiodły
                error_details = "; ".join(failed_assignments) if failed_assignments else "Unknown error"
                error_msg = (
                    f"No policies were assigned. Check if group exists and resource types are valid. "
                    f"Details: {error_details}"
                )
                logger.error(f"[AssignPolicies] {error_msg}")
                response = pb2.AssignPoliciesResponse(success=False, message=error_msg)
                return response
        
        except Exception as e:
            logger.error(f"[AssignPolicies] Unexpected error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.AssignPoliciesResponse(success=False, message=f"Internal error: {str(e)}")
    
    def update_group_leaders(self, request, context):
        """
        Synchronizes leaders for existing group.
        
        Performs full sync: removes old leaders, adds new ones.
        Currently uses CreateGroupWithLeadersRequest/Response from protobuf.
        """
        group_name: str = request.groupName
        resource_types: List[str] = list(request.resourceTypes)
        new_leaders: List[str] = list(request.leaders)
        
        resource_type: str = resource_types[0] if resource_types else ""
        normalized_group_name = normalize_name(group_name)
        
        try:
            group = self.group_manager.get_group_by_name(normalized_group_name)
            if not group:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"Group '{normalized_group_name}' does not exist")
                return pb2.GroupCreatedResponse()
            
            group_id = group["id"]
            
            current_owner_ids = self.group_manager.list_owners(group_id)
            logger.info(
                f"[UpdateGroupLeaders] Current owners for group '{normalized_group_name}': {len(current_owner_ids)}"
            )
            
            current_leader_logins = set()
            owner_id_to_login = {}
            
            for owner_id in current_owner_ids:
                try:
                    from msgraph.core import GraphClient
                    from azure_clients import get_graph_client
                    graph = get_graph_client()
                    resp = graph.get(f"/users/{owner_id}")
                    if resp.status_code == 200:
                        user_data = resp.json()
                        upn = user_data.get("userPrincipalName", "")
                        login = upn.split("@")[0] if "@" in upn else upn
                        if login.endswith(f"-{normalized_group_name}"):
                            login = login[:-(len(normalized_group_name) + 1)]
                        current_leader_logins.add(login)
                        owner_id_to_login[owner_id] = login
                except Exception as e:
                    logger.warning(
                        f"[UpdateGroupLeaders] Could not get user data for owner_id {owner_id}: {e}"
                    )
                    # Użyj owner_id jako fallback
                    current_leader_logins.add(owner_id)
                    owner_id_to_login[owner_id] = owner_id
            
            # KROK 2: Oblicz diff
            new_leaders_set = set(new_leaders)
            to_add = new_leaders_set - current_leader_logins
            to_remove = current_leader_logins - new_leaders_set
            
            logger.info(
                f"[UpdateGroupLeaders] Diff for group '{normalized_group_name}': "
                f"to_add={list(to_add)}, to_remove={list(to_remove)}"
            )
            
            # KROK 3: Usuń starych liderów
            for leader_login in to_remove:
                # Znajdź owner_id dla tego loginu
                owner_id = None
                for oid, login in owner_id_to_login.items():
                    if login == leader_login:
                        owner_id = oid
                        break
                
                if owner_id:
                    try:
                        # Usuń z owners
                        self.group_manager.remove_owner(group_id, owner_id)
                        logger.info(
                            f"[UpdateGroupLeaders] Removed owner '{leader_login}' (id: {owner_id}) "
                            f"from group '{normalized_group_name}'"
                        )
                        
                        # Usuń RBAC role assignments dla tego użytkownika
                        removed_assignments = self.rbac_manager.remove_role_assignments_for_user(owner_id)
                        if removed_assignments > 0:
                            logger.info(
                                f"[UpdateGroupLeaders] Removed {removed_assignments} RBAC role assignment(s) "
                                f"for old leader '{leader_login}'"
                            )
                    except Exception as e:
                        logger.warning(
                            f"[UpdateGroupLeaders] Error removing old leader '{leader_login}': {e}",
                            exc_info=True
                        )
            
            # KROK 4: Dodaj nowych liderów
            for leader_login in to_add:
                try:
                    username_with_suffix = build_username_with_group_suffix(leader_login, group_name)
                    
                    # Sprawdź czy użytkownik już istnieje
                    user = self.user_manager.get_user(username_with_suffix)
                    if user:
                        leader_id = user.get("id")
                        logger.info(
                            f"[UpdateGroupLeaders] User '{leader_login}' already exists, using existing user"
                        )
                    else:
                        # Utwórz użytkownika
                        leader_id = self.user_manager.create_user(
                            login=leader_login,
                            display_name=username_with_suffix,
                            group_name=group_name,
                        )
                        logger.info(
                            f"[UpdateGroupLeaders] Created user '{leader_login}' for group '{normalized_group_name}'"
                        )
                    
                    # Dodaj do members (jeśli jeszcze nie jest członkiem)
                    try:
                        self.group_manager.add_member(group_id, leader_id)
                    except Exception as e:
                        # Może już być członkiem - to OK
                        if "already" not in str(e).lower():
                            logger.warning(
                                f"[UpdateGroupLeaders] Could not add '{leader_login}' to members: {e}"
                            )
                    
                    # Dodaj jako owner
                    self.group_manager.add_owner(group_id, leader_id)
                    logger.info(
                        f"[UpdateGroupLeaders] Added '{leader_login}' as owner of group '{normalized_group_name}'"
                    )
                    
                    # Przypisz RBAC role dla nowego lidera (jeśli resource_type podany)
                    if resource_type:
                        success, reason = self.rbac_manager.assign_role_to_group(
                            resource_type=resource_type,
                            group_id=group_id,
                        )
                        if success:
                            logger.info(
                                f"[UpdateGroupLeaders] Assigned RBAC role for '{resource_type}' "
                                f"to new leader '{leader_login}'"
                            )
                        else:
                            logger.warning(
                                f"[UpdateGroupLeaders] Failed to assign RBAC role for new leader '{leader_login}': {reason}"
                            )
                    
                except Exception as e:
                    logger.error(
                        f"[UpdateGroupLeaders] Error adding new leader '{leader_login}': {e}",
                        exc_info=True
                    )
                    # Kontynuuj z następnymi liderami
            
            response = pb2.GroupCreatedResponse()
            response.groupName = group_name
            logger.info(
                f"[UpdateGroupLeaders] Successfully synchronized leaders for group '{normalized_group_name}'. "
                f"Added: {len(to_add)}, Removed: {len(to_remove)}"
            )
            return response
            
        except Exception as e:
            logger.error(f"[UpdateGroupLeaders] Error: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GroupCreatedResponse()

