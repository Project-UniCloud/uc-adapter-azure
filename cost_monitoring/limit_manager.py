# cost_monitoring/limit_manager.py

"""
Proste limity zasobów w środowisku Azure na potrzeby adaptera.

Rola:
- policzenie, ilu użytkowników mamy w Entra ID (Azure AD),
- policzenie, ile maszyn wirtualnych jest w subskrypcji,
- metody ensure_* do egzekwowania limitów (rzucają wyjątek przy przekroczeniu).

To jest funkcjonalny odpowiednik AWS-owego LimitManagera, ale zamiast
budżetów/Cost Explorera opiera się na prostych licznikach obiektów:
- użytkownicy (Graph /users),
- maszyny wirtualne (ComputeManagementClient.virtual_machines).
"""

from typing import Optional

from msgraph.core import GraphClient

from azure_clients import get_graph_client, get_compute_client


class LimitExceededError(RuntimeError):
    """
    Wyjątek rzucany, gdy przekroczony jest skonfigurowany limit zasobów.
    """

    pass


class LimitManager:
    """
    Klasa odpowiedzialna za monitorowanie prostych limitów:
    - liczby użytkowników w katalogu,
    - liczby VM-ek w subskrypcji lub w danej grupie zasobów.

    Do komunikacji z Azure używa:
    - Microsoft Graph (GraphClient) – liczenie użytkowników,
    - Azure Compute Management (ComputeManagementClient) – liczenie VM-ek.

    Domyślnie pobiera klientów z azure_clients.get_graph_client / get_compute_client,
    ale w testach można je wstrzyknąć ręcznie.
    """

    def __init__(
        self,
        graph_client: Optional[GraphClient] = None,
        compute_client=None,
    ) -> None:
        # Graph – użytkownicy Entra ID
        self._graph = graph_client or get_graph_client()
        # Compute – maszyny wirtualne
        self._compute = compute_client or get_compute_client()

    # =========================
    #  UŻYTKOWNICY
    # =========================

    def count_users(self) -> int:
        """
        Zwraca przybliżoną (w praktyce bardzo dokładną) liczbę użytkowników
        w katalogu Entra ID.

        Technicznie:
        - używamy /users?$count=true&$top=1
        - wymagany nagłówek ConsistencyLevel: eventual,
        - interesuje nas pole @odata.count.

        Dla małego katalogu (jak na subskrypcji studenckiej / trial)
        jest to w pełni wystarczające.
        """
        headers = {
            "ConsistencyLevel": "eventual",
        }
        params = {
            "$count": "true",
            # nie potrzebujemy wszystkich obiektów, interesuje nas tylko licznik
            "$top": 1,
        }

        resp = self._graph.get("/users", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

        count = data.get("@odata.count")
        if isinstance(count, int):
            return count

        # Fallback na wypadek, gdyby @odata.count z jakiegoś powodu nie było
        value = data.get("value", [])
        return len(value)

    def ensure_user_limit(self, max_users: int) -> None:
        """
        Sprawdza, czy liczba użytkowników nie przekracza/będzie przekraczać limitu.

        Jeżeli aktualna liczba użytkowników >= max_users, rzuca LimitExceededError.
        W typowym scenariuszu adapter wywoła tę metodę PRZED tworzeniem nowych
        studentów/liderów, żeby nie przebić limitu subskrypcji.
        """
        current = self.count_users()
        if current >= max_users:
            raise LimitExceededError(
                f"User limit exceeded: current={current}, max={max_users}"
            )

    # =========================
    #  MASZYNY WIRTUALNE
    # =========================

    def count_vms(self) -> int:
        """
        Zwraca liczbę maszyn wirtualnych w całej subskrypcji.

        Korzysta z:
            ComputeManagementClient.virtual_machines.list_all()
        i liczy elementy w pagerze.
        """
        pager = self._compute.virtual_machines.list_all()
        return sum(1 for _ in pager)

    def count_vms_in_resource_group(self, resource_group_name: str) -> int:
        """
        Zwraca liczbę maszyn wirtualnych w podanej grupie zasobów.

        Użyteczne, jeśli chcesz narzucać limit per-grupa zamiast globalnie.
        """
        pager = self._compute.virtual_machines.list(resource_group_name)
        return sum(1 for _ in pager)

    def ensure_vm_limit(
        self,
        max_vms: int,
        resource_group_name: Optional[str] = None,
    ) -> None:
        """
        Egzekwuje limit liczby VM-ek.

        Jeżeli:
        - resource_group_name jest None → liczony jest cały subscription-level,
        - w przeciwnym wypadku liczona jest tylko wskazana grupa zasobów.

        Przy current >= max_vms rzuca LimitExceededError.
        """
        if resource_group_name:
            current = self.count_vms_in_resource_group(resource_group_name)
            scope_desc = f"resource group '{resource_group_name}'"
        else:
            current = self.count_vms()
            scope_desc = "subscription"

        if current >= max_vms:
            raise LimitExceededError(
                f"VM limit exceeded in {scope_desc}: current={current}, max={max_vms}"
            )

    # =========================
    #  KOMBINACJA LIMITÓW
    # =========================

    def ensure_limits(
        self,
        max_users: Optional[int] = None,
        max_vms: Optional[int] = None,
        resource_group_name: Optional[str] = None,
    ) -> None:
        """
        Wygodna metoda do jednoczesnego sprawdzenia kilku limitów.

        Przykład użycia w adapterze:
            limit_mgr.ensure_limits(
                max_users=200,
                max_vms=10,
                resource_group_name="uc-lab-rg",
            )

        Każdy limit jest opcjonalny – jeśli None, to jest ignorowany.
        """
        if max_users is not None:
            self.ensure_user_limit(max_users)

        if max_vms is not None:
            self.ensure_vm_limit(max_vms, resource_group_name=resource_group_name)
