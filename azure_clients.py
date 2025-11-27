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
    """
    credential = get_credential()
    return ResourceManagementClient(credential, AZURE_SUBSCRIPTION_ID)


@lru_cache(maxsize=1)
def get_compute_client() -> ComputeManagementClient:
    """
    ComputeManagementClient – operacje na VM-kach itp.
    Przyda się później przy clean-upie / terminowaniu VMów.
    """
    credential = get_credential()
    return ComputeManagementClient(credential, AZURE_SUBSCRIPTION_ID)


@lru_cache(maxsize=1)
def get_cost_client() -> CostManagementClient:
    """
    Cost Management – zapytania o koszty subskrypcji (odpowiednik AWS Cost Explorer).
    Będzie używany w cost_monitoring/limit_manager.py.
    """
    credential = get_credential()
    # subscription_id podajesz później jako scope w zapytaniu
    return CostManagementClient(credential)
