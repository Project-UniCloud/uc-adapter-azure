# identity/rbac_manager.py

"""
Azure RBAC role assignment management based on resource type.
"""

import logging
from typing import Optional
import uuid
import time

from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

from azure_clients import get_credential, _validate_scope
from config.settings import AZURE_SUBSCRIPTION_ID


class AzureRBACManager:
    """Manages Azure RBAC role assignments for groups based on resource types."""

    RESOURCE_TYPE_ROLES = {
        "vm": "Virtual Machine Contributor",
        "storage": "Storage Account Contributor",
        "network": "Network Contributor",
    }
    
    RESOURCE_TYPE_ORDER = ["network", "storage", "vm"]

    def __init__(self, credential=None, subscription_id: Optional[str] = None) -> None:
        cred = credential or get_credential()
        sub_id = subscription_id or AZURE_SUBSCRIPTION_ID
        self._auth_client = AuthorizationManagementClient(cred, sub_id)
        self._subscription_id = sub_id

    def _get_role_definition_id(self, role_name: str) -> Optional[str]:
        """
        Returns role definition ID for the given role name.
        
        Searches at subscription scope. Returns None if not found or on error.
        """
        try:
            role_definitions = self._auth_client.role_definitions.list(
                scope=f"/subscriptions/{self._subscription_id}",
                filter=f"roleName eq '{role_name}'",
            )
            for role_def in role_definitions:
                return role_def.id
        except Exception as e:
            logging.warning(f"Could not find role definition for {role_name}: {e}")
        return None
    
    def _find_existing_role_assignment(
        self,
        scope: str,
        principal_id: str,
        role_definition_id: str,
    ) -> Optional[object]:
        """
        Checks if a role assignment already exists for the given principal and role.
        
        Returns RoleAssignment object if found, None otherwise.
        """
        try:
            assignments = self._auth_client.role_assignments.list_for_scope(scope=scope)
            
            for assignment in assignments:
                if (assignment.principal_id == principal_id and 
                    assignment.role_definition_id == role_definition_id):
                    logging.info(
                        f"[_find_existing_role_assignment] Found existing assignment: "
                        f"name={assignment.name}, scope={scope}, principal_id={principal_id}, "
                        f"role_definition_id={role_definition_id}"
                    )
                    return assignment
            
            return None
        except Exception as e:
            logging.warning(
                f"[_find_existing_role_assignment] Error checking for existing assignment: {e}"
            )
            return None
    
    def _verify_role_assignment_exists(
        self,
        scope: str,
        assignment_name: str,
    ) -> bool:
        """
        Verifies that a role assignment exists after creation.
        
        Returns True if found, False otherwise. Treats 404 as not found.
        """
        try:
            assignment = self._auth_client.role_assignments.get(
                scope=scope,
                role_assignment_name=assignment_name
            )
            if assignment:
                logging.info(
                    f"[_verify_role_assignment_exists] Verified assignment exists: "
                    f"name={assignment_name}, scope={scope}"
                )
                return True
            return False
        except Exception as e:
            if "404" in str(e) or "NotFound" in str(e):
                logging.warning(
                    f"[_verify_role_assignment_exists] Assignment not found after creation: "
                    f"name={assignment_name}, scope={scope}"
                )
                return False
            logging.warning(
                f"[_verify_role_assignment_exists] Error verifying assignment: {e}"
            )
            return False

    def assign_role_to_group(
        self,
        resource_type: str,
        group_id: str,
        scope: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Assigns RBAC role to a group based on resource type.
        
        Args:
            resource_type: Resource type (e.g., "vm", "storage", "network")
            group_id: Entra ID group object ID
            scope: Assignment scope (defaults to subscription level)
        
        Returns:
            Tuple (success: bool, reason: str). Returns (True, "") on success.
        """
        if resource_type not in self.RESOURCE_TYPE_ROLES:
            available_types = ", ".join(sorted(self.RESOURCE_TYPE_ROLES.keys()))
            reason = (
                f"Unknown resource type: '{resource_type}'. "
                f"Available resource types: {available_types}"
            )
            logging.warning(f"[assign_role_to_group] {reason}")
            return False, reason

        role_name = self.RESOURCE_TYPE_ROLES[resource_type]
        logging.info(
            f"[assign_role_to_group] Mapping resource_type '{resource_type}' "
            f"to role '{role_name}' for group {group_id}"
        )
        
        role_definition_id = self._get_role_definition_id(role_name)

        if not role_definition_id:
            reason = f"Role definition ID not found for role name '{role_name}'. Role may not exist in subscription."
            logging.warning(f"[assign_role_to_group] {reason}")
            return False, reason

        # Domyślny scope: poziom subskrypcji
        if scope is None:
            scope = f"/subscriptions/{self._subscription_id}"
        
        try:
            _validate_scope(scope)
        except ValueError as e:
            reason = f"Invalid scope format: {e}"
            logging.error(f"[assign_role_to_group] {reason}")
            return False, reason

        existing_assignment = self._find_existing_role_assignment(
            scope=scope,
            principal_id=group_id,
            role_definition_id=role_definition_id,
        )
        
        if existing_assignment:
            logging.info(
                f"[assign_role_to_group] Role assignment already exists (idempotent success). "
                f"scope={scope}, principal_id={group_id}, role_definition_id={role_definition_id}, "
                f"role_assignment_id={existing_assignment.name}, role_name='{role_name}'"
            )
            return True, ""
        
        role_assignment_params = RoleAssignmentCreateParameters(
            role_definition_id=role_definition_id,
            principal_id=group_id,
            principal_type="Group",
        )

        max_attempts = 5
        delay_seconds = 5.0
        assignment_name = None
        last_exception = None

        for attempt in range(1, max_attempts + 1):
            try:
                assignment_name = str(uuid.uuid4())
                
                logging.info(
                    f"[assign_role_to_group] Creating role assignment (attempt {attempt}/{max_attempts}). "
                    f"scope={scope}, principal_id={group_id}, role_definition_id={role_definition_id}, "
                    f"role_assignment_name={assignment_name}, role_name='{role_name}'"
                )

                assignment = self._auth_client.role_assignments.create(
                    scope=scope,
                    role_assignment_name=assignment_name,
                    parameters=role_assignment_params,
                )
                
                verified = self._verify_role_assignment_exists(scope, assignment_name)
                
                if verified:
                    logging.info(
                        f"[assign_role_to_group] Successfully assigned and verified role '{role_name}' "
                        f"to group {group_id} for resource type '{resource_type}' at scope '{scope}'. "
                        f"role_assignment_id={assignment_name}, role_definition_id={role_definition_id}, "
                        f"principal_id={group_id}"
                    )
                    return True, ""
                else:
                    logging.warning(
                        f"[assign_role_to_group] Assignment created but verification failed. "
                        f"This may be due to propagation delay. assignment_name={assignment_name}, scope={scope}"
                    )
                    if attempt < max_attempts:
                        time.sleep(2.0)
                        continue
                    else:
                        return True, "Assignment created but verification failed (may be propagation delay)"

            except Exception as e:
                msg = str(e)
                last_exception = e

                if ("RoleAssignmentExists" in msg or 
                    "already exists" in msg.lower() or 
                    "Conflict" in msg):
                    logging.info(
                        f"[assign_role_to_group] Assignment already exists (idempotent success). "
                        f"scope={scope}, principal_id={group_id}, role_definition_id={role_definition_id}, "
                        f"role_name='{role_name}', error_msg={msg}"
                    )
                    return True, ""

                if "PrincipalNotFound" in msg and attempt < max_attempts:
                    logging.warning(
                        f"[assign_role_to_group] PrincipalNotFound for group {group_id} "
                        f"when assigning role '{role_name}' (attempt {attempt}/{max_attempts}) – "
                        f"waiting {delay_seconds}s for replication..."
                    )
                    time.sleep(delay_seconds)
                    continue

                reason = (
                    f"Exception during role assignment (attempt {attempt}/{max_attempts}): {msg}. "
                    f"scope={scope}, principal_id={group_id}, role_definition_id={role_definition_id}, "
                    f"role_name='{role_name}'"
                )
                logging.error(f"[assign_role_to_group] {reason}")
                
                if attempt >= max_attempts:
                    return False, reason
        last_error = str(last_exception) if last_exception else "Unknown error"
        reason = (
            f"Failed to assign role '{role_name}' to group {group_id} "
            f"for resource type '{resource_type}' after {max_attempts} attempts. "
            f"scope={scope}, principal_id={group_id}, role_definition_id={role_definition_id}, "
            f"last_error={last_error}"
        )
        logging.error(f"[assign_role_to_group] {reason}")
        return False, reason
    
    def remove_role_assignments_for_group(
        self,
        group_id: str,
        scope: Optional[str] = None,
    ) -> int:
        """
        Removes all role assignments for a group.
        
        Returns count of removed assignments.
        """
        if scope is None:
            scope = f"/subscriptions/{self._subscription_id}"
        
        try:
            _validate_scope(scope)
        except ValueError as e:
            logging.error(f"[remove_role_assignments_for_group] Invalid scope: {e}")
            return 0
        
        removed_count = 0
        max_attempts = 3
        initial_delay = 2.0
        
        try:
            assignments = self._auth_client.role_assignments.list_for_scope(scope=scope)
            
            for assignment in assignments:
                if assignment.principal_id == group_id and assignment.principal_type == "Group":
                    for attempt in range(1, max_attempts + 1):
                        try:
                            self._auth_client.role_assignments.delete(
                                scope=scope,
                                role_assignment_name=assignment.name
                            )
                            removed_count += 1
                            logging.info(
                                f"[remove_role_assignments_for_group] Removed role assignment "
                                f"name={assignment.name}, role_definition_id={assignment.role_definition_id} "
                                f"for group {group_id} at scope {scope}"
                            )
                            break  # Sukces - wyjdź z retry loop
                            
                        except Exception as e:
                            msg = str(e)
                            status_code = getattr(e, 'status_code', None)
                            
                            # 404/409 jako idempotent success (assignment już nie istnieje)
                            if status_code in (404, 409) or "NotFound" in msg or "Conflict" in msg:
                                logging.info(
                                    f"[remove_role_assignments_for_group] Assignment already removed "
                                    f"(idempotent success). name={assignment.name}, group_id={group_id}"
                                )
                                removed_count += 1
                                break
                            
                            if (status_code in (429, 500, 502, 503, 504) and attempt < max_attempts):
                                delay = min(initial_delay * (2 ** (attempt - 1)), 10.0)
                                logging.warning(
                                    f"[remove_role_assignments_for_group] Retryable error (attempt {attempt}/{max_attempts}): "
                                    f"{msg}. Waiting {delay:.1f}s..."
                                )
                                time.sleep(delay)
                                continue
                            
                            # Inne błędy - loguj i przejdź do następnego assignment
                            logging.warning(
                                f"[remove_role_assignments_for_group] Failed to remove assignment "
                                f"name={assignment.name} for group {group_id}: {msg}"
                            )
                            break
            
            if removed_count > 0:
                logging.info(
                    f"[remove_role_assignments_for_group] Removed {removed_count} role assignment(s) "
                    f"for group {group_id} at scope {scope}"
                )
            
            return removed_count
            
        except Exception as e:
            logging.error(
                f"[remove_role_assignments_for_group] Error removing role assignments for group {group_id}: {e}",
                exc_info=True
            )
            return removed_count
    
    def remove_role_assignments_for_user(
        self,
        user_id: str,
        scope: Optional[str] = None,
    ) -> int:
        """
        Removes all role assignments for a user.
        
        Returns count of removed assignments.
        """
        if scope is None:
            scope = f"/subscriptions/{self._subscription_id}"
        
        try:
            _validate_scope(scope)
        except ValueError as e:
            logging.error(f"[remove_role_assignments_for_user] Invalid scope: {e}")
            return 0
        
        removed_count = 0
        max_attempts = 3
        initial_delay = 2.0
        
        try:
            assignments = self._auth_client.role_assignments.list_for_scope(scope=scope)
            
            for assignment in assignments:
                if assignment.principal_id == user_id and assignment.principal_type == "User":
                    for attempt in range(1, max_attempts + 1):
                        try:
                            self._auth_client.role_assignments.delete(
                                scope=scope,
                                role_assignment_name=assignment.name
                            )
                            removed_count += 1
                            logging.info(
                                f"[remove_role_assignments_for_user] Removed role assignment "
                                f"name={assignment.name}, role_definition_id={assignment.role_definition_id} "
                                f"for user {user_id} at scope {scope}"
                            )
                            break  # Sukces - wyjdź z retry loop
                            
                        except Exception as e:
                            msg = str(e)
                            status_code = getattr(e, 'status_code', None)
                            
                            # 404/409 jako idempotent success (assignment już nie istnieje)
                            if status_code in (404, 409) or "NotFound" in msg or "Conflict" in msg:
                                logging.info(
                                    f"[remove_role_assignments_for_user] Assignment already removed "
                                    f"(idempotent success). name={assignment.name}, user_id={user_id}"
                                )
                                removed_count += 1
                                break
                            
                            if (status_code in (429, 500, 502, 503, 504) and attempt < max_attempts):
                                delay = min(initial_delay * (2 ** (attempt - 1)), 10.0)
                                logging.warning(
                                    f"[remove_role_assignments_for_user] Retryable error (attempt {attempt}/{max_attempts}): "
                                    f"{msg}. Waiting {delay:.1f}s..."
                                )
                                time.sleep(delay)
                                continue
                            
                            # Inne błędy - loguj i przejdź do następnego assignment
                            logging.warning(
                                f"[remove_role_assignments_for_user] Failed to remove assignment "
                                f"name={assignment.name} for user {user_id}: {msg}"
                            )
                            break
            
            if removed_count > 0:
                logging.info(
                    f"[remove_role_assignments_for_user] Removed {removed_count} role assignment(s) "
                    f"for user {user_id} at scope {scope}"
                )
            
            return removed_count
            
        except Exception as e:
            logging.error(
                f"[remove_role_assignments_for_user] Error removing role assignments for user {user_id}: {e}",
                exc_info=True
            )
            return removed_count
