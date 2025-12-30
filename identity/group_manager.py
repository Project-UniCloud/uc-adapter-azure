# identity/group_manager.py

"""
Zarządzanie grupami w Microsoft Entra ID (Azure AD) z użyciem Microsoft Graph.

To jest odpowiednik AWS-owego IAM GroupManager:
- tworzenie grup
- dodawanie / usuwanie członków
- pobieranie informacji o grupie
"""

import time
import logging
from typing import Optional, List, Dict, Tuple

from msgraph.core import GraphClient

from azure_clients import get_graph_client, get_resource_client
from config.settings import AZURE_SUBSCRIPTION_ID
from identity.utils import normalize_name

logger = logging.getLogger(__name__)


class AzureGroupManager:
    """
    Klasa enkapsulująca operacje na grupach.
    Domyślnie korzysta z globalnego GraphClienta (get_graph_client),
    ale pozwala wstrzyknąć inny w testach.
    """

    def __init__(self, graph_client: Optional[GraphClient] = None) -> None:
        self._graph = graph_client or get_graph_client()

    # ========= OPERACJE PODSTAWOWE =========

    def create_group(
        self, 
        name: str, 
        description: Optional[str] = None,
        create_resource_group: bool = True
    ) -> Tuple[str, Optional[str]]:
        """
        Tworzy nową grupę bezpieczeństwa (security group) w Entra ID.
        Normalizuje nazwę grupy (spaces → dashes) dla zgodności z AWS adapterem.
        
        Opcjonalnie tworzy również Resource Group w Azure dla tej grupy (fallback cleanup).

        Args:
            name: Nazwa grupy
            description: Opcjonalny opis grupy
            create_resource_group: Czy utworzyć Resource Group dla grupy (domyślnie True)

        Zwraca:
            Tuple (group_id: str, resource_group_name: Optional[str]):
            - group_id: id grupy (GUID), którego używamy dalej np. w add_member
            - resource_group_name: nazwa utworzonej Resource Group lub None
        """
        # Normalize group name (matches AWS adapter behavior)
        normalized_name = normalize_name(name)

        body = {
            "displayName": normalized_name,
            "mailEnabled": False,  # klasyczna security group, bez skrzynki pocztowej
            "mailNickname": normalized_name.replace(" ", "-").lower(),
            "securityEnabled": True,
        }

        if description:
            body["description"] = description

        resp = self._graph.post("/groups", json=body)
        resp.raise_for_status()
        data = resp.json()
        group_id = data["id"]
        
        # Utwórz Resource Group dla grupy (fallback cleanup)
        resource_group_name = None
        if create_resource_group:
            try:
                resource_group_name = self._create_resource_group_for_group(normalized_name)
                logger.info(
                    f"[create_group] Created Resource Group '{resource_group_name}' "
                    f"for group '{normalized_name}'"
                )
            except Exception as e:
                logger.warning(
                    f"[create_group] Failed to create Resource Group for group '{normalized_name}': {e}. "
                    f"Continuing without RG (cleanup will rely on tags only)."
                )
        
        return group_id, resource_group_name
    
    def _create_resource_group_for_group(self, normalized_group_name: str) -> Optional[str]:
        """
        Tworzy Resource Group dla grupy o nazwie rg-{normalized_group_name} z tagiem Group.
        
        Args:
            normalized_group_name: Znormalizowana nazwa grupy
        
        Returns:
            Nazwa utworzonej Resource Group lub None w przypadku błędu
        """
        try:
            resource_client = get_resource_client()
            resource_group_name = f"rg-{normalized_group_name}"
            
            # Sprawdź czy RG już istnieje
            try:
                existing_rg = resource_client.resource_groups.get(resource_group_name)
                if existing_rg:
                    logger.info(
                        f"[_create_resource_group_for_group] Resource Group '{resource_group_name}' "
                        f"already exists"
                    )
                    return resource_group_name
            except Exception:
                # RG nie istnieje - utworzymy nowy
                pass
            
            # Utwórz nowy Resource Group z tagiem Group
            tags = {"Group": normalized_group_name}
            resource_client.resource_groups.create_or_update(
                resource_group_name,
                {"location": "westeurope", "tags": tags}  # Domyślna lokalizacja
            )
            
            logger.info(
                f"[_create_resource_group_for_group] Created Resource Group '{resource_group_name}' "
                f"with tag Group={normalized_group_name}"
            )
            return resource_group_name
            
        except Exception as e:
            logger.error(
                f"[_create_resource_group_for_group] Error creating Resource Group: {e}",
                exc_info=True
            )
            return None

    def delete_group(self, group_id: str) -> None:
        """
        Usuwa grupę po id. 404 traktujemy jako OK.
        """
        resp = self._graph.delete(f"/groups/{group_id}")
        if resp.status_code not in (204, 404):
            resp.raise_for_status()

    def get_group_by_id(self, group_id: str) -> Optional[Dict]:
        """
        Zwraca słownik z danymi grupy o podanym id lub None, jeśli nie istnieje.
        """
        resp = self._graph.get(f"/groups/{group_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_group_by_name(self, name: str) -> Optional[Dict]:
        """
        Wyszukuje grupę po displayName.
        Normalizuje nazwę przed wyszukiwaniem (spaces → dashes).
        Jeśli znajdzie dokładnie jedną – zwraca jej dane.
        Jeśli brak grup / więcej niż jedna – zwraca None.
        """
        # Normalize group name before searching (matches AWS adapter behavior)
        normalized_name = normalize_name(name)
        params = {
            "$filter": f"displayName eq '{normalized_name}'",
        }
        resp = self._graph.get("/groups", params=params)
        resp.raise_for_status()
        items = resp.json().get("value", [])

        if len(items) == 1:
            return items[0]

        # Brak lub więcej niż jedna – dla przejrzystości raportujemy None
        return None

    # ========= CZŁONKOSTWO =========

    def add_member(
        self,
        group_id: str,
        user_id: str,
        retries: int = 5,
        initial_delay: float = 3.0,
    ) -> None:
        """
        Dodaje użytkownika do grupy z ulepszonym mechanizmem retry:
        - Obsługuje 404 (replikacja katalogu), 429 (rate limit), 5xx (błędy serwera)
        - Używa exponential backoff z maksymalnym delay 30s

        Implementacja zgodna z API Graph:
        POST /groups/{group_id}/members/$ref
        body: { "@odata.id": "https://graph.microsoft.com/v1.0/directoryObjects/{user_id}" }

        :param group_id: GUID grupy
        :param user_id: GUID użytkownika (taki, jaki zwraca AzureUserManager.create_user)
        :param retries: ile razy ponawiać próbę
        :param initial_delay: początkowe opóźnienie (w sekundach) - będzie rosło wykładniczo
        """
        ref = {
            "@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"
        }

        last_resp = None
        last_status = None

        for attempt in range(1, retries + 1):
            resp = self._graph.post(f"/groups/{group_id}/members/$ref", json=ref)
            status = resp.status_code

            if status in (204, 201):
                # Dodano pomyślnie
                if attempt > 1:
                    logger.info(
                        f"[add_member] Successfully added member after {attempt} attempts "
                        f"(group_id={group_id}, user_id={user_id})"
                    )
                return

            # Retry dla: 404 (replikacja), 429 (rate limit), 5xx (błędy serwera)
            if status in (404, 429) or (500 <= status < 600):
                last_resp = resp
                last_status = status
                
                # Exponential backoff: delay = initial_delay * (2^(attempt-1)), max 30s
                delay = min(initial_delay * (2 ** (attempt - 1)), 30.0)
                
                error_type = {
                    404: "ResourceNotFound (replication delay)",
                    429: "Too Many Requests (rate limit)",
                }.get(status, f"Server error ({status})")
                
                logger.warning(
                    f"[add_member] {error_type} dla group_id={group_id}, user_id={user_id} "
                    f"(attempt {attempt}/{retries}) – czekam {delay:.1f}s..."
                )
                
                if attempt < retries:
                    time.sleep(delay)
                    continue
            else:
                # Inne błędy (np. 400, 403) - nie retry, od razu błąd
                logger.error(
                    f"[add_member] ERROR adding member: status={status}, "
                    f"group_id={group_id}, user_id={user_id}, body={resp.text}"
                )
                resp.raise_for_status()
                return

        # Po wszystkich próbach nadal błąd – logujemy szczegóły i wywalamy wyjątek
        if last_resp is not None:
            logger.error(
                f"[add_member] FAILED po {retries} próbach. "
                f"Ostatni status: {last_status}, group_id={group_id}, user_id={user_id}"
            )
            try:
                logger.error(f"[add_member] Response body: {last_resp.json()}")
            except Exception:
                logger.error(f"[add_member] Raw response body: {last_resp.text}")
            last_resp.raise_for_status()

    def add_owner(
        self,
        group_id: str,
        user_id: str,
        retries: int = 5,
        initial_delay: float = 3.0,
    ) -> None:
        """
        Dodaje właściciela (owner) do grupy z ulepszonym mechanizmem retry:
        - Obsługuje 404 (replikacja katalogu), 429 (rate limit), 5xx (błędy serwera)
        - Używa exponential backoff z maksymalnym delay 30s

        POST /groups/{group_id}/owners/$ref
        body: { "@odata.id": "https://graph.microsoft.com/v1.0/directoryObjects/{user_id}" }
        
        :param group_id: GUID grupy
        :param user_id: GUID użytkownika
        :param retries: ile razy ponawiać próbę
        :param initial_delay: początkowe opóźnienie (w sekundach) - będzie rosło wykładniczo
        """
        ref = {
            "@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"
        }

        last_resp = None
        last_status = None

        for attempt in range(1, retries + 1):
            resp = self._graph.post(f"/groups/{group_id}/owners/$ref", json=ref)
            status = resp.status_code

            if status in (204, 201):
                # Dodano pomyślnie
                if attempt > 1:
                    logger.info(
                        f"[add_owner] Successfully added owner after {attempt} attempts "
                        f"(group_id={group_id}, user_id={user_id})"
                    )
                return

            # Retry dla: 404 (replikacja), 429 (rate limit), 5xx (błędy serwera)
            if status in (404, 429) or (500 <= status < 600):
                last_resp = resp
                last_status = status
                
                # Exponential backoff: delay = initial_delay * (2^(attempt-1)), max 30s
                delay = min(initial_delay * (2 ** (attempt - 1)), 30.0)
                
                error_type = {
                    404: "ResourceNotFound (replication delay)",
                    429: "Too Many Requests (rate limit)",
                }.get(status, f"Server error ({status})")
                
                logger.warning(
                    f"[add_owner] {error_type} dla group_id={group_id}, user_id={user_id} "
                    f"(attempt {attempt}/{retries}) – czekam {delay:.1f}s..."
                )
                
                if attempt < retries:
                    time.sleep(delay)
                    continue
            else:
                # Inne błędy (np. 400, 403) - nie retry, od razu błąd
                logger.error(
                    f"[add_owner] ERROR adding owner: status={status}, "
                    f"group_id={group_id}, user_id={user_id}, body={resp.text}"
                )
                resp.raise_for_status()
                return

        if last_resp is not None:
            logger.error(
                f"[add_owner] FAILED po {retries} próbach. "
                f"Ostatni status: {last_status}, group_id={group_id}, user_id={user_id}"
            )
            try:
                logger.error(f"[add_owner] Response body: {last_resp.json()}")
            except Exception:
                logger.error(f"[add_owner] Raw response body: {last_resp.text}")
            last_resp.raise_for_status()

    def remove_member(self, group_id: str, user_id: str) -> None:
        """
        Usuwa użytkownika z grupy.

        DELETE /groups/{group_id}/members/{user_id}/$ref
        """
        resp = self._graph.delete(f"/groups/{group_id}/members/{user_id}/$ref")
        if resp.status_code not in (204, 404):
            # 204 – usunięto, 404 – już go tam nie było
            resp.raise_for_status()

    def list_members(self, group_id: str) -> List[Dict]:
        """
        Zwraca listę członków grupy (każdy element to dict z danymi directoryObject).

        Uwaga: dla dużych grup trzeba by dodać obsługę @odata.nextLink.
        """
        members: List[Dict] = []

        # Użyj $select aby uzyskać potrzebne pola (id, userPrincipalName, @odata.type)
        params = {
            "$select": "id,userPrincipalName,@odata.type"
        }
        resp = self._graph.get(f"/groups/{group_id}/members", params=params)
        resp.raise_for_status()
        data = resp.json()
        members.extend(data.get("value", []))

        return members
    
    def list_user_members(self, group_id: str) -> List[Dict]:
        """
        Zwraca listę tylko użytkowników (User) w grupie, pomijając inne typy obiektów.
        
        Używa /groups/{group_id}/members z filtrowaniem lub fallback do /members/microsoft.graph.user.
        """
        user_members: List[Dict] = []
        
        try:
            # Próba 1: Pobierz wszystkich członków i filtruj (najbardziej niezawodne)
            params = {
                "$select": "id,userPrincipalName,@odata.type"
            }
            resp = self._graph.get(f"/groups/{group_id}/members", params=params)
            resp.raise_for_status()
            data = resp.json()
            all_members = data.get("value", [])
            
            logger.debug(f"[list_user_members] Retrieved {len(all_members)} total members from group {group_id}")
            
            # Filtruj tylko użytkowników
            for member in all_members:
                odata_type = member.get("@odata.type", "")
                # Graph API zwraca "#microsoft.graph.user" dla użytkowników
                if "#microsoft.graph.user" in odata_type:
                    # Upewnij się, że mamy id i userPrincipalName
                    user_id = member.get("id")
                    upn = member.get("userPrincipalName", "")
                    if user_id:
                        user_members.append({
                            "id": user_id,
                            "userPrincipalName": upn
                        })
            
            logger.info(f"[list_user_members] Found {len(user_members)} user members in group {group_id}")
            
        except Exception as e:
            logger.warning(
                f"[list_user_members] Error getting user members: {e}. "
                f"Trying alternative endpoint...",
                exc_info=True
            )
            # Fallback: spróbuj bezpośredniego endpointu (może nie działać w niektórych wersjach Graph API)
            try:
                params = {
                    "$select": "id,userPrincipalName"
                }
                resp = self._graph.get(f"/groups/{group_id}/members/microsoft.graph.user", params=params)
                resp.raise_for_status()
                data = resp.json()
                user_members.extend(data.get("value", []))
                logger.info(f"[list_user_members] Fallback endpoint found {len(user_members)} users")
            except Exception as e2:
                logger.error(
                    f"[list_user_members] Both methods failed. Last error: {e2}",
                    exc_info=True
                )
        
        return user_members
    
    def list_owners(self, group_id: str) -> List[str]:
        """
        Zwraca listę user_id właścicieli (owners) grupy.
        
        Args:
            group_id: GUID grupy
        
        Returns:
            Lista user_id (GUID) właścicieli grupy
        """
        owners: List[str] = []
        
        try:
            resp = self._graph.get(f"/groups/{group_id}/owners")
            resp.raise_for_status()
            data = resp.json()
            
            for owner in data.get("value", []):
                if owner.get("objectType") == "User":
                    owner_id = owner.get("id")
                    if owner_id:
                        owners.append(owner_id)
            
            logger.info(f"[list_owners] Found {len(owners)} owners for group {group_id}")
            return owners
        except Exception as e:
            logger.error(f"[list_owners] Error listing owners for group {group_id}: {e}", exc_info=True)
            return []
    
    def remove_owner(self, group_id: str, user_id: str) -> None:
        """
        Usuwa właściciela (owner) z grupy.
        
        DELETE /groups/{group_id}/owners/{user_id}/$ref
        
        Args:
            group_id: GUID grupy
            user_id: GUID użytkownika do usunięcia z owners
        """
        try:
            resp = self._graph.delete(f"/groups/{group_id}/owners/{user_id}/$ref")
            if resp.status_code not in (204, 404):
                # 204 – usunięto, 404 – już go tam nie było
                resp.raise_for_status()
            logger.info(f"[remove_owner] Removed owner {user_id} from group {group_id}")
        except Exception as e:
            logger.warning(f"[remove_owner] Error removing owner {user_id} from group {group_id}: {e}")
            # Nie rzucamy wyjątku - może owner już nie istnieje
