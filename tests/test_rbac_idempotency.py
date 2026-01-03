# tests/test_rbac_idempotency.py

"""
Testy jednostkowe dla RBAC idempotency w Azure adapterze.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from azure.mgmt.authorization.models import RoleAssignment


class TestRBACIdempotency:
    """Testy idempotency dla RBAC role assignments."""
    
    @patch('identity.rbac_manager.AuthorizationManagementClient')
    def test_find_existing_role_assignment_finds_existing(self, mock_auth_client_class):
        """Test że _find_existing_role_assignment znajduje istniejący assignment."""
        from identity.rbac_manager import AzureRBACManager
        
        # Mock existing assignment
        mock_assignment = Mock()
        mock_assignment.principal_id = "group-123"
        mock_assignment.role_definition_id = "role-def-456"
        mock_assignment.name = "assignment-789"
        
        mock_auth_client = Mock()
        mock_auth_client.role_assignments.list_for_scope.return_value = [mock_assignment]
        mock_auth_client_class.return_value = mock_auth_client
        
        manager = AzureRBACManager()
        result = manager._find_existing_role_assignment(
            scope="/subscriptions/sub-123",
            principal_id="group-123",
            role_definition_id="role-def-456"
        )
        
        assert result is not None
        assert result.name == "assignment-789"
        mock_auth_client.role_assignments.list_for_scope.assert_called_once()
    
    @patch('identity.rbac_manager.AuthorizationManagementClient')
    def test_find_existing_role_assignment_not_found(self, mock_auth_client_class):
        """Test że _find_existing_role_assignment zwraca None gdy nie ma assignment."""
        from identity.rbac_manager import AzureRBACManager
        
        mock_auth_client = Mock()
        mock_auth_client.role_assignments.list_for_scope.return_value = []
        mock_auth_client_class.return_value = mock_auth_client
        
        manager = AzureRBACManager()
        result = manager._find_existing_role_assignment(
            scope="/subscriptions/sub-123",
            principal_id="group-123",
            role_definition_id="role-def-456"
        )
        
        assert result is None
    
    @patch('identity.rbac_manager.AuthorizationManagementClient')
    def test_verify_role_assignment_exists_success(self, mock_auth_client_class):
        """Test że _verify_role_assignment_exists zwraca True gdy assignment istnieje."""
        from identity.rbac_manager import AzureRBACManager
        
        mock_assignment = Mock()
        mock_auth_client = Mock()
        mock_auth_client.role_assignments.get.return_value = mock_assignment
        mock_auth_client_class.return_value = mock_auth_client
        
        manager = AzureRBACManager()
        result = manager._verify_role_assignment_exists(
            scope="/subscriptions/sub-123",
            assignment_name="assignment-789"
        )
        
        assert result is True
        mock_auth_client.role_assignments.get.assert_called_once()
    
    @patch('identity.rbac_manager.AuthorizationManagementClient')
    def test_verify_role_assignment_exists_not_found(self, mock_auth_client_class):
        """Test że _verify_role_assignment_exists zwraca False gdy assignment nie istnieje."""
        from identity.rbac_manager import AzureRBACManager
        
        mock_auth_client = Mock()
        mock_auth_client.role_assignments.get.side_effect = Exception("404 NotFound")
        mock_auth_client_class.return_value = mock_auth_client
        
        manager = AzureRBACManager()
        result = manager._verify_role_assignment_exists(
            scope="/subscriptions/sub-123",
            assignment_name="assignment-789"
        )
        
        assert result is False
    
    @patch('identity.rbac_manager.AuthorizationManagementClient')
    @patch('identity.rbac_manager.time.sleep')
    def test_assign_role_to_group_idempotent(self, mock_sleep, mock_auth_client_class):
        """Test że drugie wywołanie assign_role_to_group zwraca success (idempotent)."""
        from identity.rbac_manager import AzureRBACManager
        
        # Mock: pierwsze wywołanie - assignment nie istnieje, tworzymy nowy
        # drugie wywołanie - assignment już istnieje
        mock_existing_assignment = Mock()
        mock_existing_assignment.principal_id = "group-123"
        mock_existing_assignment.role_definition_id = "role-def-456"
        mock_existing_assignment.name = "assignment-existing"
        
        mock_new_assignment = Mock()
        mock_new_assignment.name = "assignment-new"
        
        mock_auth_client = Mock()
        # Pierwsze wywołanie: nie ma istniejącego, tworzymy nowy
        mock_auth_client.role_assignments.list_for_scope.return_value = []  # Nie ma istniejącego
        mock_auth_client.role_assignments.create.return_value = mock_new_assignment
        mock_auth_client.role_assignments.get.return_value = mock_new_assignment  # Verify success
        mock_auth_client.role_definitions.list.return_value = [Mock(id="role-def-456")]
        mock_auth_client_class.return_value = mock_auth_client
        
        manager = AzureRBACManager()
        
        # Pierwsze wywołanie - powinno utworzyć assignment
        success1, reason1 = manager.assign_role_to_group(
            resource_type="vm",
            group_id="group-123"
        )
        assert success1 is True
        
        # Drugie wywołanie - powinno znaleźć istniejący (idempotent)
        mock_auth_client.role_assignments.list_for_scope.return_value = [mock_existing_assignment]
        success2, reason2 = manager.assign_role_to_group(
            resource_type="compute",
            group_id="group-123"
        )
        assert success2 is True
        assert reason2 == ""  # Idempotent success
    
    @patch('identity.rbac_manager.AuthorizationManagementClient')
    @patch('identity.rbac_manager.time.sleep')
    def test_assign_role_to_group_handles_role_assignment_exists(self, mock_sleep, mock_auth_client_class):
        """Test że "RoleAssignmentExists" exception jest traktowane jako success."""
        from identity.rbac_manager import AzureRBACManager
        
        mock_auth_client = Mock()
        mock_auth_client.role_assignments.list_for_scope.return_value = []  # Nie ma istniejącego
        # create() rzuca exception "RoleAssignmentExists"
        mock_auth_client.role_assignments.create.side_effect = Exception("RoleAssignmentExists: ...")
        mock_auth_client.role_definitions.list.return_value = [Mock(id="role-def-456")]
        mock_auth_client_class.return_value = mock_auth_client
        
        manager = AzureRBACManager()
        success, reason = manager.assign_role_to_group(
            resource_type="vm",
            group_id="group-123"
        )
        
        assert success is True  # Powinno być traktowane jako success
