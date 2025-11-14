# identity/user_manager.py

"""
Zarządzanie użytkownikami w Microsoft Entra ID (Azure AD)
z wykorzystaniem Microsoft Graph.

To jest odpowiednik AWS IAM UserManager z adaptera AWS.
"""

from typing import Optional

from msgraph.core import GraphClient

from azure_clients import get_graph_client
from config.settings import AZURE_UDOMAIN


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

    # =========================
    #  API
    # =========================

    def create_user(
        self,
        login: str,
        display_name: Optional[str] = None,
        initial_password: Optional[str] = None,
    ) -> str:
        """
        Tworzy użytkownika w Entra ID.
        Zwraca GUID (id) utworzonego użytkownika.
        """
        upn = self._login_to_upn(login)
        display_name = display_name or login
        initial_password = initial_password or "TempPassw0rd!"

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
        resp.raise_for_status()
        data = resp.json()
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
