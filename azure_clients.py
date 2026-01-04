# azure_clients.py
"""
Central Azure service client factory module.
Provides cached client instances for Graph API, Resource Manager, Compute, and Cost Management.
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


def _validate_https_url(url: str) -> None:
    """Validates that URL uses HTTPS. Raises ValueError if not."""
    if not url.startswith("https://"):
        raise ValueError(f"URL must use HTTPS: {url}")


def _validate_scope(scope: str) -> None:
    """
    Validates scope format (must start with /subscriptions/).
    
    Raises ValueError if scope is invalid or contains http://.
    """
    if not scope.startswith("/subscriptions/"):
        raise ValueError(f"Scope must start with '/subscriptions/': {scope}")
    if "http://" in scope.lower():
        raise ValueError(f"Scope must not contain http:// (use HTTPS): {scope}")


@lru_cache(maxsize=1)
def get_credential() -> ClientSecretCredential:
    """Returns shared ClientSecretCredential instance from config settings."""
    return ClientSecretCredential(
        tenant_id=AZURE_TENANT_ID,
        client_id=AZURE_CLIENT_ID,
        client_secret=AZURE_CLIENT_SECRET,
    )


@lru_cache(maxsize=1)
def get_graph_client() -> GraphClient:
    """Returns Microsoft Graph API client for identity management operations."""
    credential = get_credential()
    scopes = ["https://graph.microsoft.com/.default"]
    return GraphClient(credential=credential, scopes=scopes)


@lru_cache(maxsize=1)
def get_resource_client() -> ResourceManagementClient:
    """
    Returns Azure Resource Manager client for resource groups and resource management.
    
    Validates subscription ID does not contain http:// (Azure SDK uses HTTPS by default).
    """
    credential = get_credential()
    if "http://" in str(AZURE_SUBSCRIPTION_ID).lower():
        raise ValueError(f"Subscription ID must not contain http://: {AZURE_SUBSCRIPTION_ID}")
    return ResourceManagementClient(credential, AZURE_SUBSCRIPTION_ID)


@lru_cache(maxsize=1)
def get_compute_client() -> ComputeManagementClient:
    """
    Returns Azure Compute Management client for VM operations.
    
    Validates subscription ID does not contain http://.
    """
    credential = get_credential()
    if "http://" in str(AZURE_SUBSCRIPTION_ID).lower():
        raise ValueError(f"Subscription ID must not contain http://: {AZURE_SUBSCRIPTION_ID}")
    return ComputeManagementClient(credential, AZURE_SUBSCRIPTION_ID)


@lru_cache(maxsize=1)
def get_cost_client() -> CostManagementClient:
    """
    Returns Azure Cost Management client for subscription cost queries.
    
    Enforces HTTPS endpoint to avoid "Bearer token authentication is not permitted for non-TLS" errors.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    credential = get_credential()
    base_url = "https://management.azure.com"
    _validate_https_url(base_url)
    logger.info(f"[get_cost_client] Initializing CostManagementClient with base_url: {base_url}")
    return CostManagementClient(credential=credential, base_url=base_url)
