# identity/rbac_manager.py

"""
Zarządzanie przypisaniami ról RBAC w Azure na podstawie typu zasobu.
To jest odpowiednik polityk IAM z adaptera AWS – ale w świecie Azure RBAC.
"""

import logging
from typing import Optional
import uuid
import time

from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

from azure_clients import get_credential
from config.settings import AZURE_SUBSCRIPTION_ID


class AzureRBACManager:
    """
    Klasa odpowiedzialna za przypisywanie ról RBAC do grup w Azure
    na podstawie typu zasobu (np. "vm", "storage").
    """

    # Mapowanie typu zasobu na nazwę wbudowanej roli RBAC
    RESOURCE_TYPE_ROLES = {
        "vm": "Virtual Machine Contributor",
        "storage": "Storage Account Contributor",
        "network": "Network Contributor",
        "compute": "Virtual Machine Contributor",
        # W razie potrzeby można dodać kolejne typy
    }

    def __init__(self, credential=None, subscription_id: Optional[str] = None) -> None:
        cred = credential or get_credential()
        sub_id = subscription_id or AZURE_SUBSCRIPTION_ID
        self._auth_client = AuthorizationManagementClient(cred, sub_id)
        self._subscription_id = sub_id

    def _get_role_definition_id(self, role_name: str) -> Optional[str]:
        """
        Zwraca pełne ID definicji roli (roleDefinitionId) dla podanej nazwy roli.

        Szuka roli na scope:
            /subscriptions/{subscriptionId}

        Jeśli nie znajdzie albo wystąpi błąd – zwraca None.
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

    def assign_role_to_group(
        self,
        resource_type: str,
        group_id: str,
        scope: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Przypisuje rolę RBAC do grupy na podstawie typu zasobu.

        Args:
            resource_type: typ zasobu (np. "vm", "storage", "compute")
            group_id: objectId grupy w Entra ID
            scope: scope przypisania – domyślnie cała subskrypcja
                   (np. "/subscriptions/...").
                   Można zawęzić do resource group:
                   "/subscriptions/.../resourceGroups/<RG_NAME>"

        Returns:
            Tuple (success: bool, reason: str):
            - (True, "") – jeśli przypisanie się udało
            - (False, reason) – jeśli pominięto lub nie powiodło się, z opisem powodu
        """
        # Walidacja resource_type z lepszym komunikatem błędu
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

        # Parametry przypisania roli – principalType=Group, bo podajemy objectId grupy
        role_assignment_params = RoleAssignmentCreateParameters(
            role_definition_id=role_definition_id,
            principal_id=group_id,
            principal_type="Group",
        )

        max_attempts = 5
        delay_seconds = 5.0

        for attempt in range(1, max_attempts + 1):
            try:
                # Unikalna nazwa przypisania roli (wymagane przez API)
                assignment_name = str(uuid.uuid4())

                self._auth_client.role_assignments.create(
                    scope=scope,
                    role_assignment_name=assignment_name,
                    parameters=role_assignment_params,
                )
                logging.info(
                    f"[assign_role_to_group] Successfully assigned role '{role_name}' "
                    f"to group {group_id} for resource type '{resource_type}' at scope '{scope}'"
                )
                return True, ""

            except Exception as e:
                msg = str(e)

                # Typowy przypadek tuż po utworzeniu grupy:
                # PrincipalNotFound – katalog jeszcze nie „zna” objectId
                if "PrincipalNotFound" in msg and attempt < max_attempts:
                    logging.warning(
                        f"[assign_role_to_group] PrincipalNotFound for group {group_id} "
                        f"when assigning role '{role_name}' (attempt {attempt}/{max_attempts}) – "
                        f"waiting {delay_seconds}s for replication..."
                    )
                    time.sleep(delay_seconds)
                    continue

                # Inne błędy - loguj szczegóły
                reason = f"Exception during role assignment (attempt {attempt}/{max_attempts}): {msg}"
                logging.error(f"[assign_role_to_group] {reason}")
                
                # Jeśli to ostatnia próba, zwróć błąd
                if attempt >= max_attempts:
                    return False, reason

        # Nie udało się nawet po retry
        reason = (
            f"Failed to assign role '{role_name}' to group {group_id} "
            f"for resource type '{resource_type}' after {max_attempts} attempts. "
            f"Last error: {msg if 'msg' in locals() else 'Unknown error'}"
        )
        logging.error(f"[assign_role_to_group] {reason}")
        return False, reason
    
    def remove_role_assignments_for_user(
        self,
        user_id: str,
        scope: Optional[str] = None,
    ) -> int:
        """
        Usuwa wszystkie role assignments dla użytkownika (np. starego lidera).
        
        Args:
            user_id: objectId użytkownika w Entra ID
            scope: scope przypisania – domyślnie cała subskrypcja
        
        Returns:
            Liczba usuniętych assignments
        """
        if scope is None:
            scope = f"/subscriptions/{self._subscription_id}"
        
        removed_count = 0
        
        try:
            # Listuj wszystkie role assignments na danym scope
            assignments = self._auth_client.role_assignments.list_for_scope(scope=scope)
            
            for assignment in assignments:
                # Sprawdź czy assignment jest dla tego użytkownika
                if assignment.principal_id == user_id and assignment.principal_type == "User":
                    try:
                        # Usuń assignment
                        self._auth_client.role_assignments.delete(
                            scope=scope,
                            role_assignment_name=assignment.name
                        )
                        removed_count += 1
                        logging.info(
                            f"[remove_role_assignments_for_user] Removed role assignment "
                            f"'{assignment.role_definition_id}' for user {user_id} at scope {scope}"
                        )
                    except Exception as e:
                        logging.warning(
                            f"[remove_role_assignments_for_user] Failed to remove assignment "
                            f"'{assignment.name}' for user {user_id}: {e}"
                        )
            
            if removed_count > 0:
                logging.info(
                    f"[remove_role_assignments_for_user] Removed {removed_count} role assignment(s) "
                    f"for user {user_id}"
                )
            
            return removed_count
            
        except Exception as e:
            logging.error(
                f"[remove_role_assignments_for_user] Error removing role assignments for user {user_id}: {e}",
                exc_info=True
            )
            return removed_count
