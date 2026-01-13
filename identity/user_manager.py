"""
User management in Microsoft Entra ID using Microsoft Graph API.
"""

import logging
from typing import Optional

from msgraph.core import GraphClient

from azure_clients import get_graph_client
from config.settings import AZURE_UDOMAIN
from identity.utils import build_username_with_group_suffix, normalize_name, make_mail_nickname, make_upn_local_part

logger = logging.getLogger(__name__)


class AzureUserManager:
    """Wrapper for Microsoft Graph API user management operations."""

    def __init__(self, graph_client: Optional[GraphClient] = None) -> None:
        self._graph = graph_client or get_graph_client()

    def _login_to_upn(self, login: str) -> str:
        """
        Converts login to User Principal Name using AZURE_UDOMAIN.
        
        Ensures UPN local part (before @) is max 64 characters (Azure AD requirement).
        If login exceeds 64 chars, truncates and adds hash suffix for uniqueness.
        """
        if "@" in login:
            return login
        
        # Ensure local part is max 64 chars (Azure AD requirement)
        local_part = make_upn_local_part(login)
        return f"{local_part}@{AZURE_UDOMAIN}"

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
        # Store original login for mailNickname (must be short, ≤64 chars)
        original_login = login
        
        # Build full username with group suffix (AWS adapter format)
        if group_name:
            full_username = build_username_with_group_suffix(login, group_name)
        else:
            full_username = login

        # Generate UPN with local part max 64 chars (Azure AD requirement)
        upn = self._login_to_upn(full_username)
        display_name = display_name or full_username

        if initial_password is None:
            initial_password = self._generate_initial_password(group_name)

        # Generate mailNickname (must be 1-64 chars, Azure AD requirement)
        # Use original login (without group suffix) for mailNickname to keep it short
        # If group_name is provided, add short hash suffix for uniqueness across groups
        # Group name is preserved in displayName and UPN for readability
        if group_name:
            # Add short hash of group name for uniqueness (ensures same user in different groups has different mailNickname)
            import hashlib
            group_hash = hashlib.md5(normalize_name(group_name).encode()).hexdigest()[:6]
            base_for_nickname = f"{original_login}-{group_hash}"
        else:
            base_for_nickname = original_login
        
        mail_nickname = make_mail_nickname(base_for_nickname)
        
        # Validate mailNickname length before sending request
        if len(mail_nickname) < 1 or len(mail_nickname) > 64:
            error_msg = (
                f"mailNickname validation failed: length={len(mail_nickname)} "
                f"(must be 1-64 chars). mailNickname='{mail_nickname}', original_login='{original_login}'"
            )
            logger.error(f"[create_user] {error_msg}")
            raise ValueError(error_msg)
        
        logger.debug(
            f"[create_user] Generated mailNickname: '{mail_nickname}' "
            f"(length={len(mail_nickname)}, from base='{base_for_nickname}', original_login='{original_login}')"
        )

        body = {
            "accountEnabled": True,
            "displayName": display_name,
            "mailNickname": mail_nickname,
            "userPrincipalName": upn,
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
                "password": initial_password,
            },
        }

        resp = self._graph.post("/users", json=body)
        if resp.status_code != 201:
            error_details = resp.text
            try:
                error_json = resp.json()
                if "error" in error_json:
                    error_msg = error_json["error"].get("message", error_details)
                    error_code = error_json["error"].get("code", "Unknown")
                    upn_local_part = upn.split("@")[0] if "@" in upn else upn
                    logger.error(
                        f"Graph create_user error: status={resp.status_code}, "
                        f"code={error_code}, message={error_msg}, "
                        f"UPN={upn} (total_length={len(upn)}, local_part_length={len(upn_local_part)}), "
                        f"mailNickname={body['mailNickname']} (length={len(body['mailNickname'])})"
                    )
                else:
                    logger.error(
                        f"Graph create_user error: status={resp.status_code}, body={error_details}"
                    )
            except Exception:
                logger.error(
                    f"Graph create_user error: status={resp.status_code}, body={error_details}"
                )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Created user: {full_username} (UPN: {upn})")
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
