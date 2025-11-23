from azure.mgmt.resource import ResourceManagementClient
from azure_clients import get_credential
from config.settings import AZURE_SUBSCRIPTION_ID

class ResourceFinder:
    def __init__(self, cred=None, sub_id=None):
        cred = cred or get_credential()
        sub_id = sub_id or AZURE_SUBSCRIPTION_ID
        self._rm = ResourceManagementClient(cred, sub_id)

    def find_resources_by_tags(self, tag_filter: dict):
        # np. "course = 'uc2025' AND student = 's1234'"
        ...
