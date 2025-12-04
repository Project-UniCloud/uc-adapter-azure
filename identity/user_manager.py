"""
Zarządzanie użytkownikami w Microsoft Entra ID (Azure AD)
z wykorzystaniem Microsoft Graph.

To jest odpowiednik AWS IAM UserManager z adaptera AWS.
"""

import logging
from typing import Optional

from msgraph.core import GraphClient

from azure_clients import get_graph_client
from config.settings import AZURE_UDOMAIN
from identity.utils import build_username_with_group_suffix, normalize_name

logger = logging.getLogger(__name__)


class AzureUserManager:
    """
    Prosty wrapper na Microsoft Graph do operacji na użytkownikach.
    """

    def __init__(self, graph_client: Optional[GraphClient] = None) -> None:
        self._graph = graph_client or get_graph_client()

    # =========================
    #  Pomocnicze
    # =========================

    def _login_to_upn(self, login: str) -> str:
        """
        Zamienia prosty login (np. 'jan.kowalski') na pełny UPN
        'jan.kowalski@twojadomena.onmicrosoft.com'
        korzystając z AZURE_UDOMAIN z config/settings.py.
        """
        if "@" in login:
            return login
        return f"{login}@{AZURE_UDOMAIN}"

    def _generate_initial_password(self, group_name: Optional[str]) -> str:
        """
        Generuje hasło początkowe zgodne z polityką haseł Entra ID.

        Jeśli jest podane group_name, używa go (po normalizacji) jako bazy
        i dodaje sufiks zapewniający złożoność (duża litera, cyfra, znak specjalny).
        Jeśli group_name nie ma, używa domyślnej bazy.
        """
        if group_name:
            base = normalize_name(group_name)
        else:
            # Domyślna sensowna baza – ma już dużą literę i cyfrę
            base = "TempPassw0rd"

        # Jeśli baza jest bardzo krótka, lekko ją wydłuż
        if len(base) < 6:
            base = base + "Group"

        # Dodaj sufiks zapewniający 3+ kategorie znaków
        # (małe litery z base, DUŻA litera, cyfra, znak specjalny)
        return f"{base}A1!"

    # =========================
    #  API
    # =========================

    def create_user(
        self,
        login: str,
        display_name: Optional[str] = None,
        initial_password: Optional[str] = None,
        group_name: Optional[str] = None,
    ) -> str:
        """
        Tworzy użytkownika w Entra ID.

        Jeśli podano group_name, dodaje suffix do username (matches AWS adapter format).
        Jeśli nie podano initial_password, generuje hasło z wykorzystaniem group_name
        jako bazy, ale tak, aby spełnić politykę złożoności haseł Entra ID.

        Zwraca GUID (id) utworzonego użytkownika.
        """
        # Add group suffix to username if group_name provided (matches AWS adapter)
        if group_name:
            login = build_username_with_group_suffix(login, group_name)

        upn = self._login_to_upn(login)
        display_name = display_name or login

        # Generate password if not provided explicitly
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
        """
        Usuwa użytkownika po loginie lub UPN.
        Brak użytkownika traktujemy jako OK (404 ignorujemy).
        """
        upn = self._login_to_upn(login_or_upn)

        resp = self._graph.delete(f"/users/{upn}")
        if resp.status_code not in (204, 404):
            resp.raise_for_status()

    def get_user(self, login_or_upn: str) -> Optional[dict]:
        """
        Pobiera dane użytkownika (dict) lub None gdy nie istnieje.
        """
        upn = self._login_to_upn(login_or_upn)
        resp = self._graph.get(f"/users/{upn}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def reset_password(self, login_or_upn: str, new_password: str) -> bool:
        """
        Ustawia nowe hasło użytkownika.
        Zwraca True, gdy się udało; False gdy użytkownik nie istnieje.
        """
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
