# clean_resources/resource_finder.py

"""
Finds Azure resources by tags.
Similar to AWS Resource Groups Tagging API functionality.
"""

import logging
from typing import List, Dict, Optional
from azure.mgmt.resource import ResourceManagementClient
from azure_clients import get_credential
from config.settings import AZURE_SUBSCRIPTION_ID
from identity.utils import normalize_name

logger = logging.getLogger(__name__)


class ResourceFinder:
    """
    Finds Azure resources based on tag filters.
    Similar to AWS find_resources_by_group functionality.
    """
    
    def __init__(self, cred=None, sub_id=None):
        cred = cred or get_credential()
        sub_id = sub_id or AZURE_SUBSCRIPTION_ID
        self._rm = ResourceManagementClient(cred, sub_id)
    
    def find_resources_by_tags(self, tag_filter: dict) -> List[Dict]:
        """
        Finds resources that match the given tag filter.
        
        Args:
            tag_filter: Dict with tag key-value pairs, e.g., {"Group": "AI-2024L"}
        
        Returns:
            List of dicts with resource info: {"id", "name", "type", "service", "resource_group"}
        """
        resources = []
        
        try:
            # List all resources in subscription
            # Note: For better performance with large subscriptions, consider using Azure Resource Graph
            for resource in self._rm.resources.list():
                # Check if resource has tags and matches filter
                if resource.tags:
                    tags_match = True
                    for key, value in tag_filter.items():
                        # Normalize tag values for comparison
                        normalized_value = normalize_name(str(value))
                        tag_value = normalize_name(str(resource.tags.get(key, "")))
                        
                        if tag_value != normalized_value:
                            tags_match = False
                            break
                    
                    if tags_match:
                        # Extract service name from resource type
                        # e.g., "Microsoft.Compute/virtualMachines" -> "vm"
                        resource_type = resource.type or ""
                        service = self._extract_service_name(resource_type)
                        
                        # Extract resource group from resource ID
                        resource_group = None
                        if resource.id and "/resourceGroups/" in resource.id:
                            parts = resource.id.split("/resourceGroups/")
                            if len(parts) > 1:
                                resource_group = parts[1].split("/")[0]
                        
                        resources.append({
                            "id": resource.id,
                            "name": resource.name,
                            "type": resource_type,
                            "service": service,
                            "resource_group": resource_group
                        })
            
            logger.info(f"Found {len(resources)} resources matching tags: {tag_filter}")
            return resources
        
        except Exception as e:
            logger.error(f"Error finding resources by tags: {e}", exc_info=True)
            return []
    
    def _extract_service_name(self, resource_type: str) -> str:
        """
        Extracts short service name from Azure resource type.
        
        Args:
            resource_type: Full Azure resource type, e.g., "Microsoft.Compute/virtualMachines"
        
        Returns:
            Short service name, e.g., "vm"
        """
        if not resource_type:
            return "unknown"
        
        rtype_lower = resource_type.lower()
        
        if "compute" in rtype_lower or "virtualmachine" in rtype_lower:
            return "vm"
        if "storage" in rtype_lower:
            return "storage"
        if "network" in rtype_lower:
            return "network"
        if "database" in rtype_lower or "sql" in rtype_lower:
            return "database"
        if "keyvault" in rtype_lower:
            return "keyvault"
        if "appservice" in rtype_lower or "web" in rtype_lower:
            return "appservice"
        if "container" in rtype_lower or "aks" in rtype_lower:
            return "container"
        
        # Extract from resource type format: "Microsoft.Service/ResourceType"
        if "/" in resource_type:
            parts = resource_type.split("/")
            if len(parts) > 1:
                return parts[-1].lower()
        
        return "other"
