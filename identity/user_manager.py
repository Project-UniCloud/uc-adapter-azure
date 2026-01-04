"""
User management in Microsoft Entra ID using Microsoft Graph API.
"""

import logging
from typing import Optional

from msgraph.core import GraphClient

from azure_clients import get_graph_client
from config.settings import AZURE_UDOMAIN
from identity.utils import build_username_with_group_suffix, normalize_name

logger = logging.getLogger(__name__)


class AzureUserManager:
    """Wrapper for Microsoft Graph API user management operations."""

    def __init__(self, graph_client: Optional[GraphClient] = None) -> None:
        self._graph = graph_client or get_graph_client()

    def _login_to_upn(self, login: str) -> str:
        """Converts login to User Principal Name using AZURE_UDOMAIN."""
        if "@" in login:
            return login
        return f"{login}@{AZURE_UDOMAIN}"

    def _generate_initial_password(self, group_name: Optional[str]) -> str:
        """
        Generates initial password compliant with Entra ID password policy.
        
        Uses normalized group_name as base if provided, otherwise uses default.
        Ensures complexity: lowercase, uppercase, digit, special character.
        """
        if group_name:
            base = normalize_name(group_name)
        else:
            base = "TempPassw0rd"

        if len(base) < 6:
            base = base + "Group"

        return f"{base}A1!"

    def create_user(
        self,
        login: str,
        display_name: Optional[str] = None,
        initial_password: Optional[str] = None,
        group_name: Optional[str] = None,
    ) -> str:
        """
        Creates a user in Entra ID.
        
        If group_name is provided, adds suffix to username (matches AWS adapter format).
        If initial_password is not provided, generates password compliant with Entra ID policy.
        
        Returns user GUID (id).
        """
        if group_name:
            login = build_username_with_group_suffix(login, group_name)

        upn = self._login_to_upn(login)
        display_name = display_name or login

        if initial_password is None:
            initial_password = self._generate_initial_password(group_name)

        body = {
            "accountEnabled": True,
            "displayName": display_name,
            "mailNickname": login.replace(" ", "-"),
            "userPrincipalName": upn,
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
                "password": initial_password,
            },
        }

        resp = self._graph.post("/users", json=body)
        if resp.status_code != 201:
            logger.error(
                f"Graph create_user error: status={resp.status_code}, body={resp.text}"
            )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Created user: {login} (UPN: {upn})")
        return data["id"]

    def delete_user(self, login_or_upn: str) -> None:
        """Deletes user by login or UPN. Treats 404 (not found) as success."""
        upn = self._login_to_upn(login_or_upn)

        resp = self._graph.delete(f"/users/{upn}")
        if resp.status_code not in (204, 404):
            resp.raise_for_status()

    def get_user(self, login_or_upn: str) -> Optional[dict]:
        """Retrieves user data as dict, or None if user doesn't exist."""
        upn = self._login_to_upn(login_or_upn)
        resp = self._graph.get(f"/users/{upn}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def reset_password(self, login_or_upn: str, new_password: str) -> bool:
        """Sets new password for user. Returns True on success, False if user doesn't exist."""
        upn = self._login_to_upn(login_or_upn)

        body = {
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
                "password": new_password,
            }
        }

        resp = self._graph.patch(f"/users/{upn}", json=body)
        if resp.status_code == 404:
            return False

        resp.raise_for_status()
        return True
