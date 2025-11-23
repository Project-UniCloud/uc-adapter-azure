# identity/group_manager.py

"""
Zarządzanie grupami w Microsoft Entra ID (Azure AD) z użyciem Microsoft Graph.

To jest odpowiednik AWS-owego IAM GroupManager:
- tworzenie grup
- dodawanie / usuwanie członków
- pobieranie informacji o grupie
"""

import time
from typing import Optional, List, Dict

from msgraph.core import GraphClient

from azure_clients import get_graph_client


class AzureGroupManager:
    """
    Klasa enkapsulująca operacje na grupach.
    Domyślnie korzysta z globalnego GraphClienta (get_graph_client),
    ale pozwala wstrzyknąć inny w testach.
    """

    def __init__(self, graph_client: Optional[GraphClient] = None) -> None:
        self._graph = graph_client or get_graph_client()

    # ========= OPERACJE PODSTAWOWE =========

    def create_group(self, name: str, description: Optional[str] = None) -> str:
        """
        Tworzy nową grupę bezpieczeństwa (security group) w Entra ID.

        Zwraca:
            id grupy (GUID), którego używamy dalej np. w add_member.
        """
        body = {
            "displayName": name,
            "mailEnabled": False,  # klasyczna security group, bez skrzynki pocztowej
            "mailNickname": name.replace(" ", "-").lower(),
            "securityEnabled": True,
        }

        if description:
            body["description"] = description

        resp = self._graph.post("/groups", json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["id"]

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
        Jeśli znajdzie dokładnie jedną – zwraca jej dane.
        Jeśli brak grup / więcej niż jedna – zwraca None.
        """
        params = {
            "$filter": f"displayName eq '{name}'",
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
        delay: float = 3.0,
    ) -> None:
        """
        Dodaje użytkownika do grupy z prostym mechanizmem retry na wypadek
        opóźnionej replikacji katalogu (częste 404 Request_ResourceNotFound
        tuż po utworzeniu grupy lub użytkownika).

        Implementacja zgodna z API Graph:
        POST /groups/{group_id}/members/$ref
        body: { "@odata.id": "https://graph.microsoft.com/v1.0/directoryObjects/{user_id}" }

        :param group_id: GUID grupy
        :param user_id: GUID użytkownika (taki, jaki zwraca AzureUserManager.create_user)
        :param retries: ile razy ponawiać próbę po 404
        :param delay: opóźnienie (w sekundach) między próbami
        """
        ref = {
            "@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"
        }

        last_resp = None

        for attempt in range(1, retries + 1):
            resp = self._graph.post(f"/groups/{group_id}/members/$ref", json=ref)

            if resp.status_code in (204, 201):
                # Dodano pomyślnie
                return

            if resp.status_code == 404:
                # Typowy przypadek: katalog jeszcze się nie zreplikował
                last_resp = resp
                print(
                    f"[AzureGroupManager.add_member] 404 ResourceNotFound dla group_id={group_id} "
                    f"(attempt {attempt}/{retries}) – czekam {delay}s..."
                )
                time.sleep(delay)
                continue

            # Inne błędy traktujemy od razu jako poważne
            print(
                "[AzureGroupManager.add_member] ERROR:",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()

        # Po wszystkich próbach nadal 404 – logujemy szczegóły i wywalamy wyjątek
        if last_resp is not None:
            print("[AzureGroupManager.add_member] FAILED po wielu próbach. Odpowiedź Graph:")
            print("  status:", last_resp.status_code)
            try:
                print("  body:", last_resp.json())
            except Exception:
                print("  raw body:", last_resp.text)
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

        resp = self._graph.get(f"/groups/{group_id}/members")
        resp.raise_for_status()
        data = resp.json()
        members.extend(data.get("value", []))

        return members
