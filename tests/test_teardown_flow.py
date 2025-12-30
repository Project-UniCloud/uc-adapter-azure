# tests/test_teardown_flow.py

"""
Testy jednostkowe dla teardown flow w Azure adapterze.
Weryfikacja kolejności operacji i idempotency.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call


class TestTeardownFlow:
    """Testy dla pełnego flow teardown grupy."""
    
    @patch('handlers.identity_handlers.ResourceFinder')
    @patch('handlers.identity_handlers.ResourceDeleter')
    @patch('handlers.identity_handlers.AzureRBACManager')
    @patch('handlers.identity_handlers.AzureGroupManager')
    @patch('handlers.identity_handlers.AzureUserManager')
    def test_remove_group_order_of_operations(
        self,
        mock_user_manager_class,
        mock_group_manager_class,
        mock_rbac_manager_class,
        mock_resource_deleter_class,
        mock_resource_finder_class
    ):
        """Test że remove_group wykonuje operacje w prawidłowej kolejności."""
        from handlers.identity_handlers import IdentityHandlers
        
        # Setup mocks
        mock_group = Mock()
        mock_group["id"] = "group-123"
        mock_group_manager = Mock()
        mock_group_manager.get_group_by_name.return_value = mock_group
        mock_group_manager.list_members.return_value = [
            {"id": "user-1", "objectType": "User", "userPrincipalName": "user1@example.com"}
        ]
        mock_group_manager_class.return_value = mock_group_manager
        
        mock_rbac_manager = Mock()
        mock_rbac_manager.remove_role_assignments_for_group.return_value = 2
        mock_rbac_manager.remove_role_assignments_for_user.return_value = 1
        mock_rbac_manager_class.return_value = mock_rbac_manager
        
        mock_resource_finder = Mock()
        mock_resource_finder.find_resources_by_tags.return_value = []
        mock_resource_finder_class.return_value = mock_resource_finder
        
        mock_resource_deleter = Mock()
        mock_resource_deleter_class.return_value = mock_resource_deleter
        
        mock_user_manager = Mock()
        mock_user_manager_class.return_value = mock_user_manager
        
        # Create handler
        handler = IdentityHandlers(
            user_manager=mock_user_manager,
            group_manager=mock_group_manager,
            rbac_manager=mock_rbac_manager,
            resource_finder=mock_resource_finder,
            resource_deleter=mock_resource_deleter,
        )
        
        # Create request
        from protos import adapter_interface_pb2 as pb2
        request = pb2.RemoveGroupRequest()
        request.groupName = "test-group"
        context = Mock()
        
        # Execute
        response = handler.remove_group(request, context)
        
        # Verify kolejność wywołań
        call_order = []
        for call_obj in mock_rbac_manager.method_calls:
            call_order.append(call_obj[0])
        for call_obj in mock_resource_finder.method_calls:
            call_order.append(f"resource_finder.{call_obj[0]}")
        for call_obj in mock_user_manager.method_calls:
            call_order.append(f"user_manager.{call_obj[0]}")
        for call_obj in mock_group_manager.method_calls:
            if call_obj[0] == "delete_group":
                call_order.append("group_manager.delete_group")
        
        # Sprawdź że remove_role_assignments_for_group było wywołane PRZED resource cleanup
        assert "remove_role_assignments_for_group" in call_order
        assert "resource_finder.find_resources_by_tags" in call_order
        rbac_idx = call_order.index("remove_role_assignments_for_group")
        resource_idx = call_order.index("resource_finder.find_resources_by_tags")
        assert rbac_idx < resource_idx, "Role assignments should be removed before resource cleanup"
        
        # Sprawdź że remove_role_assignments_for_user było wywołane PRZED delete_user
        assert "remove_role_assignments_for_user" in call_order
        assert "user_manager.delete_user" in call_order
        user_rbac_idx = call_order.index("remove_role_assignments_for_user")
        user_delete_idx = call_order.index("user_manager.delete_user")
        assert user_rbac_idx < user_delete_idx, "User role assignments should be removed before user deletion"
        
        # Sprawdź że delete_group było wywołane na końcu
        assert "group_manager.delete_group" in call_order
        group_delete_idx = call_order.index("group_manager.delete_group")
        assert group_delete_idx == len(call_order) - 1, "Group deletion should be last"
    
    @patch('identity.rbac_manager.AuthorizationManagementClient')
    @patch('identity.rbac_manager.time.sleep')
    def test_remove_role_assignments_handles_404_as_success(self, mock_sleep, mock_auth_client_class):
        """Test że 404 przy usuwaniu assignment jest traktowane jako success (idempotent)."""
        from identity.rbac_manager import AzureRBACManager
        
        # Mock assignment
        mock_assignment = Mock()
        mock_assignment.principal_id = "group-123"
        mock_assignment.principal_type = "Group"
        mock_assignment.name = "assignment-123"
        mock_assignment.role_definition_id = "role-def-456"
        
        # Mock exception z status_code 404
        mock_404_exception = Exception("404 NotFound")
        mock_404_exception.status_code = 404
        
        mock_auth_client = Mock()
        mock_auth_client.role_assignments.list_for_scope.return_value = [mock_assignment]
        mock_auth_client.role_assignments.delete.side_effect = mock_404_exception
        mock_auth_client_class.return_value = mock_auth_client
        
        manager = AzureRBACManager()
        removed_count = manager.remove_role_assignments_for_group("group-123")
        
        # 404 powinno być liczone jako usunięte (idempotent success)
        assert removed_count == 1
    
    @patch('identity.rbac_manager.AuthorizationManagementClient')
    @patch('identity.rbac_manager.time.sleep')
    def test_remove_role_assignments_retry_on_429(self, mock_sleep, mock_auth_client_class):
        """Test że retry działa dla 429 (rate limit)."""
        from identity.rbac_manager import AzureRBACManager
        
        mock_assignment = Mock()
        mock_assignment.principal_id = "group-123"
        mock_assignment.principal_type = "Group"
        mock_assignment.name = "assignment-123"
        mock_assignment.role_definition_id = "role-def-456"
        
        # Pierwsze wywołanie: 429, drugie: sukces
        mock_429_exception = Exception("429 Too Many Requests")
        mock_429_exception.status_code = 429
        
        mock_auth_client = Mock()
        mock_auth_client.role_assignments.list_for_scope.return_value = [mock_assignment]
        mock_auth_client.role_assignments.delete.side_effect = [
            mock_429_exception,  # Pierwsza próba
            None  # Druga próba - sukces
        ]
        mock_auth_client_class.return_value = mock_auth_client
        
        manager = AzureRBACManager()
        removed_count = manager.remove_role_assignments_for_group("group-123")
        
        # Powinno się udać po retry
        assert removed_count == 1
        # Sprawdź że sleep był wywołany (exponential backoff)
        assert mock_sleep.called
