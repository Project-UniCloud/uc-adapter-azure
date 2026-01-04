# identity/group_manager.py

"""
Group management in Microsoft Entra ID using Microsoft Graph API.
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

    def create_group(
        self, 
        name: str, 
        description: Optional[str] = None,
        create_resource_group: bool = True
    ) -> Tuple[str, Optional[str]]:
        """
        Creates a security group in Entra ID.
        
        Normalizes group name (spaces → dashes) for AWS adapter compatibility.
        Optionally creates Azure Resource Group for fallback cleanup.
        
        Returns tuple (group_id, resource_group_name).
        """
        normalized_name = normalize_name(name)

        body = {
            "displayName": normalized_name,
            "mailEnabled": False,
            "mailNickname": normalized_name.replace(" ", "-").lower(),
            "securityEnabled": True,
        }

        if description:
            body["description"] = description

        resp = self._graph.post("/groups", json=body)
        resp.raise_for_status()
        data = resp.json()
        group_id = data["id"]
        
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
        Creates Resource Group named rg-{normalized_group_name} with Group tag.
        
        Returns Resource Group name or None on error.
        """
        try:
            resource_client = get_resource_client()
            resource_group_name = f"rg-{normalized_group_name}"
            
            try:
                existing_rg = resource_client.resource_groups.get(resource_group_name)
                if existing_rg:
                    logger.info(
                        f"[_create_resource_group_for_group] Resource Group '{resource_group_name}' "
                        f"already exists"
                    )
                    return resource_group_name
            except Exception:
                pass
            
            tags = {"Group": normalized_group_name}
            resource_client.resource_groups.create_or_update(
                resource_group_name,
                {"location": "westeurope", "tags": tags}
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
        """Deletes group by id. Treats 404 (not found) as success."""
        resp = self._graph.delete(f"/groups/{group_id}")
        if resp.status_code not in (204, 404):
            resp.raise_for_status()

    def get_group_by_id(self, group_id: str) -> Optional[Dict]:
        """Returns group data as dict, or None if group doesn't exist."""
        resp = self._graph.get(f"/groups/{group_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_group_by_name(self, name: str) -> Optional[Dict]:
        """
        Finds group by displayName.
        
        Normalizes name before searching. Returns group data if exactly one found,
        None if zero or multiple matches.
        """
        normalized_name = normalize_name(name)
        params = {
            "$filter": f"displayName eq '{normalized_name}'",
        }
        resp = self._graph.get("/groups", params=params)
        resp.raise_for_status()
        items = resp.json().get("value", [])

        if len(items) == 1:
            return items[0]
        return None

    def add_member(
        self,
        group_id: str,
        user_id: str,
        retries: int = 5,
        initial_delay: float = 3.0,
    ) -> None:
        """
        Adds user to group with retry mechanism.
        
        Handles 404 (replication), 429 (rate limit), 5xx (server errors).
        Uses exponential backoff with max delay 30s.
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

            if status in (404, 429) or (500 <= status < 600):
                last_resp = resp
                last_status = status
                
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
        Adds owner to group with retry mechanism.
        
        Handles 404 (replication), 429 (rate limit), 5xx (server errors).
        Uses exponential backoff with max delay 30s.
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

            if status in (404, 429) or (500 <= status < 600):
                last_resp = resp
                last_status = status
                
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
        """Removes user from group. Treats 404 (not found) as success."""
        resp = self._graph.delete(f"/groups/{group_id}/members/{user_id}/$ref")
        if resp.status_code not in (204, 404):
            resp.raise_for_status()

    def list_members(self, group_id: str) -> List[Dict]:
        """
        Returns list of group members (each element is dict with directoryObject data).
        
        Note: pagination (@odata.nextLink) not implemented for large groups.
        """
        members: List[Dict] = []

        params = {
            "$select": "id,userPrincipalName"
        }
        resp = self._graph.get(f"/groups/{group_id}/members", params=params)
        resp.raise_for_status()
        data = resp.json()
        members.extend(data.get("value", []))

        return members
    
    def list_user_members(self, group_id: str) -> List[Dict]:
        """
        Returns list of User members only, filtering out other object types.
        
        Uses /groups/{group_id}/members with filtering, or fallback to
        /members/microsoft.graph.user endpoint.
        """
        user_members: List[Dict] = []
        
        try:
            params = {
                "$select": "id,userPrincipalName"
            }
            
            all_members = []
            endpoint_path = f"/groups/{group_id}/members"
            
            while endpoint_path:
                resp = self._graph.get(endpoint_path, params=params)
                resp.raise_for_status()
                data = resp.json()
                page_members = data.get("value", [])
                all_members.extend(page_members)
                
                next_link = data.get("@odata.nextLink")
                if next_link:
                    logger.debug(f"[list_user_members] Pagination: Retrieved {len(page_members)} members, more pages available")
                    if next_link.startswith("https://graph.microsoft.com/v1.0"):
                        endpoint_path = next_link.replace("https://graph.microsoft.com/v1.0", "")
                        params = None
                    else:
                        endpoint_path = None
                else:
                    endpoint_path = None
            
            logger.debug(f"[list_user_members] Retrieved {len(all_members)} total members from group {group_id}")
            
            for member in all_members:
                odata_type = member.get("@odata.type", "")
                if "#microsoft.graph.user" in odata_type:
                    user_id = member.get("id")
                    upn = member.get("userPrincipalName", "")
                    if user_id:
                        user_members.append({
                            "id": user_id,
                            "userPrincipalName": upn
                        })
            
            logger.info(f"[list_user_members] Found {len(user_members)} user members in group {group_id} (from {len(all_members)} total members)")
            
        except Exception as e:
            logger.warning(
                f"[list_user_members] Error getting user members: {e}. "
                f"Trying alternative endpoint...",
                exc_info=True
            )
            try:
                params = {
                    "$select": "id,userPrincipalName"
                }
                
                fallback_users = []
                endpoint_path = f"/groups/{group_id}/members/microsoft.graph.user"
                
                while endpoint_path:
                    resp = self._graph.get(endpoint_path, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    page_users = data.get("value", [])
                    fallback_users.extend(page_users)
                    
                    next_link = data.get("@odata.nextLink")
                    if next_link:
                        logger.debug(f"[list_user_members] Fallback pagination: Retrieved {len(page_users)} users, more pages available")
                        if next_link.startswith("https://graph.microsoft.com/v1.0"):
                            endpoint_path = next_link.replace("https://graph.microsoft.com/v1.0", "")
                            params = None
                        else:
                            endpoint_path = None
                    else:
                        endpoint_path = None
                
                user_members.extend(fallback_users)
                logger.info(f"[list_user_members] Fallback endpoint found {len(fallback_users)} users")
            except Exception as e2:
                logger.error(
                    f"[list_user_members] Both methods failed. Last error: {e2}",
                    exc_info=True
                )
        
        return user_members
    
    def list_owners(self, group_id: str) -> List[str]:
        """Returns list of user IDs (GUIDs) of group owners."""
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
        """Removes owner from group. Treats 404 (not found) as success."""
        try:
            resp = self._graph.delete(f"/groups/{group_id}/owners/{user_id}/$ref")
            if resp.status_code not in (204, 404):
                resp.raise_for_status()
            logger.info(f"[remove_owner] Removed owner {user_id} from group {group_id}")
        except Exception as e:
            logger.warning(f"[remove_owner] Error removing owner {user_id} from group {group_id}: {e}")
