# azure_clients.py
"""
Centralny moduł trzymający klientów do usług Azure, używany w całym adapterze.

Analogiczna libka z AWS  boto3.client(...)
"""

from functools import lru_cache

from azure.identity import ClientSecretCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.costmanagement import CostManagementClient
from msgraph.core import GraphClient

from config.settings import (
    AZURE_TENANT_ID,
    AZURE_CLIENT_ID,
    AZURE_CLIENT_SECRET,
    AZURE_SUBSCRIPTION_ID,
)


# =========================
#  Walidacja HTTPS
# =========================

def _validate_https_url(url: str) -> None:
    """
    Waliduje że URL używa HTTPS. Rzuca ValueError jeśli nie.
    
    Args:
        url: URL do walidacji
    
    Raises:
        ValueError: Jeśli URL nie zaczyna się od https://
    """
    if not url.startswith("https://"):
        raise ValueError(f"URL must use HTTPS: {url}")


def _validate_scope(scope: str) -> None:
    """
    Waliduje że scope ma prawidłowy format (zaczyna się od /subscriptions/).
    Rzuca ValueError jeśli nie.
    
    Args:
        scope: Scope do walidacji (np. "/subscriptions/{subscription_id}")
    
    Raises:
        ValueError: Jeśli scope nie zaczyna się od /subscriptions/ lub zawiera http://
    """
    if not scope.startswith("/subscriptions/"):
        raise ValueError(f"Scope must start with '/subscriptions/': {scope}")
    if "http://" in scope.lower():
        raise ValueError(f"Scope must not contain http:// (use HTTPS): {scope}")


# =========================
#  Wspólne poświadczenia
# =========================

@lru_cache(maxsize=1)
def get_credential() -> ClientSecretCredential:
    """
    Zwraca współdzielony obiekt ClientSecretCredential oparty na wartościach z config/settings.py
    (tenant id, client id, client secret).
    """
    return ClientSecretCredential(
        tenant_id=AZURE_TENANT_ID,
        client_id=AZURE_CLIENT_ID,
        client_secret=AZURE_CLIENT_SECRET,
    )


# =========================
#  Klient Microsoft Graph
# =========================

@lru_cache(maxsize=1)
def get_graph_client() -> GraphClient:
    """
    Klient Microsoft Graph, wykorzystywany w identity/user_manager.py i identity/group_manager.py.
    """
    credential = get_credential()
    scopes = ["https://graph.microsoft.com/.default"]
    return GraphClient(credential=credential, scopes=scopes)


# =========================
#  Resource Manager (ARM)
# =========================

@lru_cache(maxsize=1)
def get_resource_client() -> ResourceManagementClient:
    """
    Klient ResourceManagementClient – odpowiednik boto3.client('ec2') / 'resourcegroupstaggingapi'
   pozwala zarządzać resource groupami i zasobami.
    
    Wymusza walidację że subscription_id nie zawiera http:// (Azure SDK domyślnie używa HTTPS).
    """
    credential = get_credential()
    # Walidacja że subscription_id nie zawiera http:// (Azure SDK używa HTTPS domyślnie)
    if "http://" in str(AZURE_SUBSCRIPTION_ID).lower():
        raise ValueError(f"Subscription ID must not contain http://: {AZURE_SUBSCRIPTION_ID}")
    return ResourceManagementClient(credential, AZURE_SUBSCRIPTION_ID)


@lru_cache(maxsize=1)
def get_compute_client() -> ComputeManagementClient:
    """
    ComputeManagementClient – operacje na VM-kach itp.
    Przyda się później przy clean-upie / terminowaniu VMów.
    
    Wymusza walidację że subscription_id nie zawiera http:// (Azure SDK domyślnie używa HTTPS).
    """
    credential = get_credential()
    # Walidacja że subscription_id nie zawiera http://
    if "http://" in str(AZURE_SUBSCRIPTION_ID).lower():
        raise ValueError(f"Subscription ID must not contain http://: {AZURE_SUBSCRIPTION_ID}")
    return ComputeManagementClient(credential, AZURE_SUBSCRIPTION_ID)


@lru_cache(maxsize=1)
def get_cost_client() -> CostManagementClient:
    """
    Cost Management – zapytania o koszty subskrypcji (odpowiednik AWS Cost Explorer).
    Będzie używany w cost_monitoring/limit_manager.py.
    
    Wymusza HTTPS endpoint, aby uniknąć błędu "Bearer token authentication is not permitted for non-TLS".
    """
    import logging
    logger = logging.getLogger(__name__)
    
    credential = get_credential()
    # Wymuszamy HTTPS endpoint - domyślnie management.azure.com używa HTTPS, ale lepiej być explicite
    base_url = "https://management.azure.com"
    _validate_https_url(base_url)  # Walidacja że base_url używa HTTPS
    logger.info(f"[get_cost_client] Initializing CostManagementClient with base_url: {base_url}")
    # subscription_id podajesz później jako scope w zapytaniu
    return CostManagementClient(credential=credential, base_url=base_url)
