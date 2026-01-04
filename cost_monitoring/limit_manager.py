# cost_monitoring/limit_manager.py

"""
Resource limit monitoring and cost queries for Azure adapter.
Counts users in Entra ID and VMs in subscription.
Provides cost query functions using Azure Cost Management API.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

from msgraph.core import GraphClient
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import QueryDefinition, QueryTimePeriod, QueryDataset, QueryAggregation, QueryGrouping

from azure_clients import get_graph_client, get_compute_client, get_credential, _validate_scope
from config.settings import AZURE_SUBSCRIPTION_ID
from identity.utils import normalize_name

logger = logging.getLogger(__name__)


class LimitExceededError(RuntimeError):
    """Raised when configured resource limit is exceeded."""
    pass


class LimitManager:
    """
    Monitors resource limits: user count in Entra ID, VM count in subscription.
    Provides cost query functions using Azure Cost Management API.
    """

    def __init__(
        self,
        graph_client: Optional[GraphClient] = None,
        compute_client=None,
    ) -> None:
        self._graph = graph_client or get_graph_client()
        self._compute = compute_client or get_compute_client()

    def count_users(self) -> int:
        """
        Returns approximate user count in Entra ID directory.
        
        Uses /users?$count=true&$top=1 with ConsistencyLevel: eventual header.
        Returns @odata.count value.
        """
        headers = {
            "ConsistencyLevel": "eventual",
        }
        params = {
            "$count": "true",
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


# =========================
#  COST MONITORING FUNCTIONS
#  Azure Cost Management API integration
# =========================

def _get_cost_client():
    """
    Get Azure Cost Management client.
    Wymusza HTTPS endpoint, aby uniknąć błędu "Bearer token authentication is not permitted for non-TLS".
    """
    cred = get_credential()
    # Wymuszamy HTTPS endpoint
    base_url = "https://management.azure.com"
    logger.info(f"[_get_cost_client] Initializing CostManagementClient with base_url: {base_url}")
    return CostManagementClient(credential=cred, base_url=base_url)


def _azure_service_to_short(name: str) -> str:
    """
    Maps Azure service names to short names (similar to AWS function).
    
    Args:
        name: Full Azure service name (e.g., "Microsoft.Compute/virtualMachines")
    
    Returns:
        Short service name (e.g., "vm")
    """
    n = (name or "").lower()
    
    # Map common Azure service types
    if "compute" in n or "virtualmachine" in n:
        return "vm"
    if "storage" in n:
        return "storage"
    if "network" in n or "networking" in n:
        return "network"
    if "database" in n or "sql" in n:
        return "database"
    if "keyvault" in n or "key vault" in n:
        return "keyvault"
    if "appservice" in n or "web" in n:
        return "appservice"
    if "container" in n or "aks" in n:
        return "container"
    if "monitor" in n or "insights" in n:
        return "monitor"
    if "backup" in n:
        return "backup"
    if "recovery" in n:
        return "recovery"
    
    # Extract short name from resource type (e.g., "Microsoft.Compute/virtualMachines" -> "vm")
    if "/" in n:
        parts = n.split("/")
        if len(parts) > 1:
            service_part = parts[-1]
            # Remove common prefixes
            service_part = service_part.replace("microsoft.", "").replace("azure.", "")
            return service_part[:10]  # Limit length
    
    return "other"


def _first_day_of_month(dt: datetime) -> datetime:
    """Returns first day of the month for given datetime."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _shift_months(dt: datetime, months: int) -> datetime:
    """Shift month preserving year, clamping to valid month range."""
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, 28)  # day won't matter since we set to first later
    return dt.replace(year=year, month=month, day=day)


def get_total_cost_for_group(group_tag_value: str, start_date: str, end_date: str = None) -> float:
    """
    Get total cost for a group based on tag filtering.
    
    Args:
        group_tag_value: Group name (tag value)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format (defaults to today)
    
    Returns:
        Total cost as float (rounded to 2 decimals)
    """
    if end_date is None:
        end_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    try:
        client = _get_cost_client()
        normalized_group = normalize_name(group_tag_value)
        
        # Query definition for cost query
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(
                from_property=start_date,
                to=end_date
            ),
            dataset=QueryDataset(
                granularity="Monthly",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                },
                filter={
                    "tags": {
                        "name": "Group",
                        "operator": "In",
                        "values": [normalized_group]
                    }
                } if normalized_group else None
            )
        )
        
        # Execute query
        scope = f"/subscriptions/{AZURE_SUBSCRIPTION_ID}"
        # Walidacja scope - musi zaczynać się od /subscriptions/ i nie zawierać http://
        try:
            from azure_clients import _validate_scope
            _validate_scope(scope)
        except ValueError as e:
            logger.error(f"[get_total_cost_for_group] Invalid scope: {e}")
            return 0.0
        logger.info(f"[get_total_cost_for_group] Querying Cost Management API at scope: {scope}")
        result = client.query.usage(scope=scope, parameters=query)
        
        total = 0.0
        if result.rows:
            for row in result.rows:
                # Cost is typically in the first column
                if len(row) > 0:
                    try:
                        total += float(row[0])
                    except (ValueError, TypeError):
                        pass
        
        return round(total, 2)
    
    except Exception as e:
        logger.error(f"Error fetching costs for group {group_tag_value}: {e}", exc_info=True)
        return 0.0


def get_group_cost_with_service_breakdown(group_tag_value: str, start_date: str, end_date: str = None) -> Dict:
    """
    Get group cost with breakdown by service.
    
    Args:
        group_tag_value: Group name (tag value)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format (defaults to today)
    
    Returns:
        Dict with 'total' and 'by_service' keys
    """
    if end_date is None:
        end_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    try:
        client = _get_cost_client()
        normalized_group = normalize_name(group_tag_value)
        
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(
                from_property=start_date,
                to=end_date
            ),
            dataset=QueryDataset(
                granularity="Monthly",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                },
                grouping=[
                    QueryGrouping(type="Dimension", name="ResourceType")
                ],
                filter={
                    "tags": {
                        "name": "Group",
                        "operator": "In",
                        "values": [normalized_group]
                    }
                } if normalized_group else None
            )
        )
        
        scope = f"/subscriptions/{AZURE_SUBSCRIPTION_ID}"
        # Walidacja scope
        try:
            _validate_scope(scope)
        except ValueError as e:
            logger.error(f"[get_group_cost_with_service_breakdown] Invalid scope: {e}")
            return {'total': 0.0, 'by_service': {}}
        logger.info(f"[get_group_cost_with_service_breakdown] Querying Cost Management API at scope: {scope}")
        result = client.query.usage(scope=scope, parameters=query)
        
        cost_by_service = {}
        total_cost = 0.0
        
        if result.rows:
            for row in result.rows:
                if len(row) >= 2:
                    service_name = str(row[0]) if row[0] else "unknown"
                    amount = float(row[1]) if row[1] else 0.0
                    
                    if amount <= 0:
                        continue
                    
                    short_name = _azure_service_to_short(service_name)
                    cost_by_service[short_name] = cost_by_service.get(short_name, 0.0) + amount
                    total_cost += amount
        
        return {
            'total': round(total_cost, 2),
            'by_service': {k: round(v, 2) for k, v in sorted(
                cost_by_service.items(),
                key=lambda item: item[1],
                reverse=True
            )}
        }
    
    except Exception as e:
        logger.error(f"Error fetching service breakdown for group {group_tag_value}: {e}", exc_info=True)
        return {
            'total': 0.0,
            'by_service': {}
        }


def get_total_costs_for_all_groups(start_date: str, end_date: str = None) -> Dict[str, float]:
    """
    Get costs for all groups based on tag grouping.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format (defaults to today)
    
    Returns:
        Dict mapping group names to costs
    """
    if end_date is None:
        end_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    group_costs = {}
    
    try:
        client = _get_cost_client()
        
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(
                from_property=start_date,
                to=end_date
            ),
            dataset=QueryDataset(
                granularity="Monthly",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                },
                grouping=[
                    QueryGrouping(type="Tag", name="Group")
                ]
            )
        )
        
        scope = f"/subscriptions/{AZURE_SUBSCRIPTION_ID}"
        # Walidacja scope
        try:
            _validate_scope(scope)
        except ValueError as e:
            logger.error(f"[get_total_costs_for_all_groups] Invalid scope: {e}")
            return {}
        logger.info(f"[get_total_costs_for_all_groups] Querying Cost Management API at scope: {scope}")
        result = client.query.usage(scope=scope, parameters=query)
        
        if result.rows:
            for row in result.rows:
                if len(row) >= 2:
                    group_name = str(row[0]) if row[0] else "unknown"
                    cost = float(row[1]) if row[1] else 0.0
                    
                    # Remove tag prefix if present (Azure Cost Management API format)
                    if "$" in group_name:
                        group_name = group_name.split("$", 1)[1]
                    
                    # Note: group_name here is the value from the "Group" tag.
                    # It may be normalized (with dashes) or original (with spaces).
                    # Denormalization (dashes -> spaces) is handled in main.py
                    # to prevent corrupting names that legitimately contain dashes.
                    
                    group_costs[group_name] = group_costs.get(group_name, 0.0) + cost
        
        # Return raw group names from tags (may contain dashes or spaces)
        # main.py will handle safe denormalization for backend compatibility
        return {group: round(cost, 2) for group, cost in group_costs.items()}
    
    except Exception as e:
        logger.error(f"Error fetching costs for all groups: {e}", exc_info=True)
        return {}


def get_total_azure_cost(start_date: str, end_date: str = None) -> float:
    """
    Get total Azure subscription cost.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format (defaults to today)
    
    Returns:
        Total cost as float (rounded to 2 decimals)
    """
    if end_date is None:
        end_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    try:
        client = _get_cost_client()
        
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(
                from_property=start_date,
                to=end_date
            ),
            dataset=QueryDataset(
                granularity="Monthly",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                }
            )
        )
        
        scope = f"/subscriptions/{AZURE_SUBSCRIPTION_ID}"
        # Walidacja scope
        try:
            _validate_scope(scope)
        except ValueError as e:
            logger.error(f"[get_total_azure_cost] Invalid scope: {e}")
            return 0.0
        logger.info(f"[get_total_azure_cost] Querying Cost Management API at scope: {scope}")
        result = client.query.usage(scope=scope, parameters=query)
        
        total = 0.0
        if result.rows:
            for row in result.rows:
                if len(row) > 0:
                    try:
                        total += float(row[0])
                    except (ValueError, TypeError):
                        pass
        
        return round(total, 2)
    
    except Exception as e:
        logger.error(f"[get_total_azure_cost] Error fetching total Azure cost: {e}", exc_info=True)
        return 0.0


def get_total_cost_with_service_breakdown(start_date: str, end_date: str = None) -> Dict:
    """
    Get total Azure cost with service breakdown.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format (defaults to today)
    
    Returns:
        Dict with 'total' and 'by_service' keys
    """
    if end_date is None:
        end_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    try:
        client = _get_cost_client()
        
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(
                from_property=start_date,
                to=end_date
            ),
            dataset=QueryDataset(
                granularity="Monthly",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                },
                grouping=[
                    QueryGrouping(type="Dimension", name="ResourceType")
                ]
            )
        )
        
        scope = f"/subscriptions/{AZURE_SUBSCRIPTION_ID}"
        # Walidacja scope
        try:
            _validate_scope(scope)
        except ValueError as e:
            logger.error(f"[get_total_cost_with_service_breakdown] Invalid scope: {e}")
            return {'total': 0.0, 'by_service': {}}
        logger.info(f"[get_total_cost_with_service_breakdown] Querying Cost Management API at scope: {scope}")
        result = client.query.usage(scope=scope, parameters=query)
        
        total_cost = 0.0
        cost_by_service = {}
        
        if result.rows:
            for row in result.rows:
                if len(row) >= 2:
                    service_name = str(row[0]) if row[0] else "unknown"
                    amount = float(row[1]) if row[1] else 0.0
                    
                    if amount <= 0:
                        continue
                    
                    short_name = _azure_service_to_short(service_name)
                    cost_by_service[short_name] = cost_by_service.get(short_name, 0.0) + amount
                    total_cost += amount
        
        return {
            'total': round(total_cost, 2),
            'by_service': {k: round(v, 2) for k, v in sorted(
                cost_by_service.items(),
                key=lambda item: item[1],
                reverse=True
            )}
        }
    
    except Exception as e:
        logger.error(f"Error fetching total cost with service breakdown: {e}", exc_info=True)
        return {
            'total': 0.0,
            'by_service': {}
        }


def get_group_cost_last_6_months_by_service(group_tag_value: str) -> Dict[str, float]:
    """
    Get group costs for last 6 months grouped by service.
    
    Args:
        group_tag_value: Group name (tag value)
    
    Returns:
        Dict mapping service short names to total costs
    """
    now = datetime.now(timezone.utc)
    month_start = _first_day_of_month(now)
    start_dt = _first_day_of_month(_shift_months(month_start, -5))
    end_dt = _first_day_of_month(_shift_months(month_start, 1))
    
    start_date = start_dt.strftime('%Y-%m-%d')
    end_date = end_dt.strftime('%Y-%m-%d')
    
    try:
        client = _get_cost_client()
        normalized_group = normalize_name(group_tag_value)
        
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(
                from_property=start_date,
                to=end_date
            ),
            dataset=QueryDataset(
                granularity="Monthly",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                },
                grouping=[
                    QueryGrouping(type="Dimension", name="ResourceType")
                ],
                filter={
                    "tags": {
                        "name": "Group",
                        "operator": "In",
                        "values": [normalized_group]
                    }
                } if normalized_group else None
            )
        )
        
        scope = f"/subscriptions/{AZURE_SUBSCRIPTION_ID}"
        # Walidacja scope
        try:
            _validate_scope(scope)
        except ValueError as e:
            logger.error(f"[get_group_cost_last_6_months_by_service] Invalid scope: {e}")
            return {}
        logger.info(f"[get_group_cost_last_6_months_by_service] Querying Cost Management API at scope: {scope}")
        result = client.query.usage(scope=scope, parameters=query)
        
        costs: Dict[str, float] = {}
        if result.rows:
            for row in result.rows:
                if len(row) >= 2:
                    service_name = str(row[0]) if row[0] else "unknown"
                    amount = float(row[1]) if row[1] else 0.0
                    
                    if amount <= 0:
                        continue
                    
                    short_name = _azure_service_to_short(service_name)
                    costs[short_name] = round(costs.get(short_name, 0.0) + amount, 10)
        
        return {k: round(v, 2) for k, v in costs.items()}
    
    except Exception as e:
        logger.error(f"Error fetching last 6 months costs for group {group_tag_value}: {e}", exc_info=True)
        return {}


def get_group_monthly_costs_last_6_months(group_tag_value: str) -> Dict[str, float]:
    """
    Get monthly costs for last 6 months for a group.
    
    Args:
        group_tag_value: Group name (tag value)
    
    Returns:
        Dict mapping month strings (dd-MM-yyyy) to costs
    """
    now = datetime.now(timezone.utc)
    month_start = _first_day_of_month(now)
    start_dt = _first_day_of_month(_shift_months(month_start, -5))
    end_dt = _first_day_of_month(_shift_months(month_start, 1))
    
    start_date = start_dt.strftime('%Y-%m-%d')
    end_date = end_dt.strftime('%Y-%m-%d')
    
    # Prepare month keys
    months_keys = []
    for i in range(0, 6):
        m_dt = _shift_months(_first_day_of_month(start_dt), i)
        months_keys.append(m_dt.strftime('%d-%m-%Y'))
    month_costs: Dict[str, float] = {k: 0.0 for k in months_keys}
    
    try:
        client = _get_cost_client()
        normalized_group = normalize_name(group_tag_value)
        
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(
                from_property=start_date,
                to=end_date
            ),
            dataset=QueryDataset(
                granularity="Monthly",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                },
                filter={
                    "tags": {
                        "name": "Group",
                        "operator": "In",
                        "values": [normalized_group]
                    }
                } if normalized_group else None
            )
        )
        
        scope = f"/subscriptions/{AZURE_SUBSCRIPTION_ID}"
        # Walidacja scope
        try:
            _validate_scope(scope)
        except ValueError as e:
            logger.error(f"[get_group_monthly_costs_last_6_months] Invalid scope: {e}")
            return month_costs
        logger.info(f"[get_group_monthly_costs_last_6_months] Querying Cost Management API at scope: {scope}")
        result = client.query.usage(scope=scope, parameters=query)
        
        if result.columns and result.rows:
            # Find date column index
            date_col_idx = None
            cost_col_idx = None
            for idx, col in enumerate(result.columns):
                if col.name and "date" in col.name.lower():
                    date_col_idx = idx
                if col.name and "cost" in col.name.lower():
                    cost_col_idx = idx
            
            for row in result.rows:
                if date_col_idx is not None and cost_col_idx is not None:
                    if len(row) > max(date_col_idx, cost_col_idx):
                        period_start = str(row[date_col_idx])
                        try:
                            # Parse date and convert to dd-MM-yyyy
                            dt = datetime.strptime(period_start, '%Y-%m-%d')
                            key = dt.strftime('%d-%m-%Y')
                            amount = float(row[cost_col_idx]) if row[cost_col_idx] else 0.0
                            if key in month_costs:
                                month_costs[key] = round(amount, 2)
                        except (ValueError, TypeError):
                            pass
        
        return month_costs
    
    except Exception as e:
        logger.error(f"Error fetching monthly costs for group {group_tag_value}: {e}", exc_info=True)
        return month_costs
