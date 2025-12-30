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

from azure_clients import get_credential, _validate_scope
from config.settings import AZURE_SUBSCRIPTION_ID


class AzureRBACManager:
    """
    Klasa odpowiedzialna za przypisywanie ról RBAC do grup w Azure
    na podstawie typu zasobu (np. "vm", "storage").
    """

    # Mapowanie typu zasobu na nazwę wbudowanej roli RBAC
    # UWAGA: "compute" i "vm" mapują na tę samą rolę - używaj "compute" dla spójności
    RESOURCE_TYPE_ROLES = {
        "vm": "Virtual Machine Contributor",
        "storage": "Storage Account Contributor",
        "network": "Network Contributor",
        "compute": "Virtual Machine Contributor",  # compute i vm to aliasy - preferuj compute
        # W razie potrzeby można dodać kolejne typy
    }
    
    # Deterministyczna kolejność przypisywania ról (dla compose policy)
    # Kolejność: network → storage → compute (zależności i stabilność)
    RESOURCE_TYPE_ORDER = ["network", "storage", "compute", "vm"]

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
    
    def _find_existing_role_assignment(
        self,
        scope: str,
        principal_id: str,
        role_definition_id: str,
    ) -> Optional[object]:
        """
        Sprawdza czy role assignment już istnieje dla danego principal i roli.
        
        Args:
            scope: Scope przypisania (np. "/subscriptions/{id}")
            principal_id: objectId principal (grupy lub użytkownika)
            role_definition_id: Pełne ID definicji roli
        
        Returns:
            RoleAssignment object jeśli istnieje, None w przeciwnym razie
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
        Weryfikuje czy role assignment istnieje po utworzeniu.
        
        Args:
            scope: Scope przypisania
            assignment_name: Nazwa (ID) przypisania roli
        
        Returns:
            True jeśli assignment istnieje, False w przeciwnym razie
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
            # 404 oznacza że assignment nie istnieje
            if "404" in str(e) or "NotFound" in str(e):
                logging.warning(
                    f"[_verify_role_assignment_exists] Assignment not found after creation: "
                    f"name={assignment_name}, scope={scope}"
                )
                return False
            # Inne błędy - loguj i zwróć False
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
        
        # Walidacja scope - musi używać HTTPS format
        try:
            _validate_scope(scope)
        except ValueError as e:
            reason = f"Invalid scope format: {e}"
            logging.error(f"[assign_role_to_group] {reason}")
            return False, reason

        # KROK 1: Sprawdź czy assignment już istnieje (idempotency)
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
        
        # KROK 2: Utwórz nowy assignment (PUT)
        # Parametry przypisania roli – principalType=Group, bo podajemy objectId grupy
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
                # Unikalna nazwa przypisania roli (wymagane przez API)
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
                
                # KROK 3: Verify - sprawdź czy assignment rzeczywiście istnieje
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
                    # Assignment utworzony, ale weryfikacja nie powiodła się - może być opóźnienie propagacji
                    logging.warning(
                        f"[assign_role_to_group] Assignment created but verification failed. "
                        f"This may be due to propagation delay. assignment_name={assignment_name}, scope={scope}"
                    )
                    # Spróbuj jeszcze raz po krótkim opóźnieniu
                    if attempt < max_attempts:
                        time.sleep(2.0)
                        continue
                    else:
                        # Ostatnia próba - zwróć partial success (assignment utworzony, ale nie zweryfikowany)
                        return True, "Assignment created but verification failed (may be propagation delay)"

            except Exception as e:
                msg = str(e)
                last_exception = e

                # Obsługa "RoleAssignmentExists" jako success (idempotent)
                if ("RoleAssignmentExists" in msg or 
                    "already exists" in msg.lower() or 
                    "Conflict" in msg):
                    logging.info(
                        f"[assign_role_to_group] Assignment already exists (idempotent success). "
                        f"scope={scope}, principal_id={group_id}, role_definition_id={role_definition_id}, "
                        f"role_name='{role_name}', error_msg={msg}"
                    )
                    return True, ""

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
                reason = (
                    f"Exception during role assignment (attempt {attempt}/{max_attempts}): {msg}. "
                    f"scope={scope}, principal_id={group_id}, role_definition_id={role_definition_id}, "
                    f"role_name='{role_name}'"
                )
                logging.error(f"[assign_role_to_group] {reason}")
                
                # Jeśli to ostatnia próba, zwróć błąd
                if attempt >= max_attempts:
                    return False, reason

        # Nie udało się nawet po retry
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
        Usuwa wszystkie role assignments dla grupy.
        
        Args:
            group_id: objectId grupy w Entra ID
            scope: scope przypisania – domyślnie cała subskrypcja
        
        Returns:
            Liczba usuniętych assignments
        """
        if scope is None:
            scope = f"/subscriptions/{self._subscription_id}"
        
        # Walidacja scope
        try:
            _validate_scope(scope)
        except ValueError as e:
            logging.error(f"[remove_role_assignments_for_group] Invalid scope: {e}")
            return 0
        
        removed_count = 0
        max_attempts = 3
        initial_delay = 2.0
        
        try:
            # Listuj wszystkie role assignments na danym scope
            assignments = self._auth_client.role_assignments.list_for_scope(scope=scope)
            
            for assignment in assignments:
                # Sprawdź czy assignment jest dla tej grupy
                if assignment.principal_id == group_id and assignment.principal_type == "Group":
                    # Retry z exponential backoff dla usuwania
                    for attempt in range(1, max_attempts + 1):
                        try:
                            # Usuń assignment
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
                                removed_count += 1  # Licz jako usunięte
                                break
                            
                            # Retry dla 429/5xx
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
        Usuwa wszystkie role assignments dla użytkownika (np. starego lidera).
        
        Args:
            user_id: objectId użytkownika w Entra ID
            scope: scope przypisania – domyślnie cała subskrypcja
        
        Returns:
            Liczba usuniętych assignments
        """
        if scope is None:
            scope = f"/subscriptions/{self._subscription_id}"
        
        # Walidacja scope
        try:
            _validate_scope(scope)
        except ValueError as e:
            logging.error(f"[remove_role_assignments_for_user] Invalid scope: {e}")
            return 0
        
        removed_count = 0
        max_attempts = 3
        initial_delay = 2.0
        
        try:
            # Listuj wszystkie role assignments na danym scope
            assignments = self._auth_client.role_assignments.list_for_scope(scope=scope)
            
            for assignment in assignments:
                # Sprawdź czy assignment jest dla tego użytkownika
                if assignment.principal_id == user_id and assignment.principal_type == "User":
                    # Retry z exponential backoff dla usuwania
                    for attempt in range(1, max_attempts + 1):
                        try:
                            # Usuń assignment
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
                                removed_count += 1  # Licz jako usunięte
                                break
                            
                            # Retry dla 429/5xx
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
