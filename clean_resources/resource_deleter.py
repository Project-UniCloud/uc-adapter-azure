# clean_resources/resource_deleter.py

"""
Deletes Azure resources.
Similar to AWS delete_resource functionality.
"""

import logging
from typing import Dict, Optional
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.storage import StorageManagementClient
from azure_clients import get_credential
from config.settings import AZURE_SUBSCRIPTION_ID

logger = logging.getLogger(__name__)


class ResourceDeleter:
    """
    Deletes Azure resources based on resource type.
    Similar to AWS delete_resource functionality.
    """
    
    def __init__(self, cred=None, sub_id=None):
        cred = cred or get_credential()
        sub_id = sub_id or AZURE_SUBSCRIPTION_ID
        self._compute_client = ComputeManagementClient(cred, sub_id)
        self._network_client = NetworkManagementClient(cred, sub_id)
        self._resource_client = ResourceManagementClient(cred, sub_id)
        self._storage_client = StorageManagementClient(cred, sub_id)
    
    def delete_resource(self, resource: Dict) -> str:
        """
        Deletes an Azure resource based on its type.
        
        Args:
            resource: Dict with resource info: {"id", "name", "type", "service", "resource_group"}
        
        Returns:
            Success message string
        """
        resource_id = resource.get("id")
        resource_name = resource.get("name")
        resource_type = resource.get("type", "")
        resource_group = resource.get("resource_group")
        service = resource.get("service", "").lower()
        
        if not all([resource_id, resource_name, resource_group]):
            return f"Skipping deletion for incomplete resource info: {resource}"
        
        try:
            # Delete based on service type or resource type
            if service == "vm" or "virtualmachine" in resource_type.lower():
                logger.info(f"Deleting VM: {resource_name} in resource group {resource_group}")
                self._compute_client.virtual_machines.begin_delete(
                    resource_group, resource_name
                ).wait()
                return f"Deleted VM: {resource_name}"
            
            elif service == "network" or "network" in resource_type.lower():
                if "networkinterface" in resource_type.lower():
                    logger.info(f"Deleting Network Interface: {resource_name} in resource group {resource_group}")
                    self._network_client.network_interfaces.begin_delete(
                        resource_group, resource_name
                    ).wait()
                    return f"Deleted Network Interface: {resource_name}"
                
                elif "publicipaddress" in resource_type.lower():
                    logger.info(f"Deleting Public IP: {resource_name} in resource group {resource_group}")
                    self._network_client.public_ip_addresses.begin_delete(
                        resource_group, resource_name
                    ).wait()
                    return f"Deleted Public IP: {resource_name}"
                
                elif "virtualnetwork" in resource_type.lower():
                    logger.info(f"Deleting Virtual Network: {resource_name} in resource group {resource_group}")
                    self._network_client.virtual_networks.begin_delete(
                        resource_group, resource_name
                    ).wait()
                    return f"Deleted Virtual Network: {resource_name}"
                
                elif "networksecuritygroup" in resource_type.lower():
                    logger.info(f"Deleting Network Security Group: {resource_name} in resource group {resource_group}")
                    self._network_client.network_security_groups.begin_delete(
                        resource_group, resource_name
                    ).wait()
                    return f"Deleted Network Security Group: {resource_name}"
            
            elif service == "storage" or "storage" in resource_type.lower():
                logger.info(f"Deleting Storage Account: {resource_name} in resource group {resource_group}")
                self._storage_client.storage_accounts.begin_delete(
                    resource_group, resource_name
                ).wait()
                return f"Deleted Storage Account: {resource_name}"
            
            else:
                # Generic deletion using Resource Management Client
                logger.info(f"Deleting resource: {resource_name} ({resource_type}) in resource group {resource_group}")
                self._resource_client.resources.begin_delete_by_id(
                    resource_id, "2021-04-01"  # API version
                ).wait()
                return f"Deleted resource: {resource_name} ({resource_type})"
        
        except Exception as e:
            error_msg = f"Error deleting {resource_type} {resource_name}: {e}"
            logger.error(error_msg, exc_info=True)
            return error_msg

