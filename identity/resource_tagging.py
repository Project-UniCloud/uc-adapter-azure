# identity/resource_tagging.py

"""
Resource tagging mechanism for Azure resources with Group tag.

Note: Tagging requires permissions to modify resources.
Can be called by users with appropriate roles (e.g. Tag Contributor).
"""

import logging
from typing import Optional

from azure.mgmt.resource import ResourceManagementClient
from azure.core.exceptions import HttpResponseError

from azure_clients import get_resource_client
from identity.utils import normalize_name

logger = logging.getLogger(__name__)


def ensure_resource_tagged(resource_id: str, group_name: str) -> bool:
    """
    Dodaje tag 'Group' do zasobu Azure.
    
    Args:
        resource_id: Pełne ID zasobu Azure (np. "/subscriptions/.../resourceGroups/.../providers/.../...")
        group_name: Nazwa grupy (zostanie znormalizowana)
    
    Returns:
        True jeśli tagowanie się powiodło, False w przeciwnym razie
    """
    try:
        resource_client = get_resource_client()
        normalized_group = normalize_name(group_name)
        
        # Pobierz aktualne tagi zasobu
        try:
            resource = resource_client.resources.get_by_id(resource_id, "2021-04-01")
            current_tags = resource.tags or {}
        except HttpResponseError as e:
            if e.status_code == 404:
                logger.warning(f"[ensure_resource_tagged] Resource not found: {resource_id}")
                return False
            raise
        
        # Dodaj tag Group jeśli jeszcze go nie ma lub jest inny
        if current_tags.get("Group") != normalized_group:
            current_tags["Group"] = normalized_group
            logger.info(
                f"[ensure_resource_tagged] Tagging resource {resource_id} "
                f"with Group={normalized_group}"
            )
            
            # Zaktualizuj zasób z nowymi tagami
            resource_client.resources.begin_update_by_id(
                resource_id, "2021-04-01", {"tags": current_tags}
            ).wait()
            
            logger.info(f"[ensure_resource_tagged] Successfully tagged resource {resource_id}")
            return True
        else:
            logger.debug(
                f"[ensure_resource_tagged] Resource {resource_id} already has "
                f"correct tag Group={normalized_group}"
            )
            return True
            
    except Exception as e:
        logger.error(
            f"[ensure_resource_tagged] Error tagging resource {resource_id}: {e}",
            exc_info=True
        )
        return False
