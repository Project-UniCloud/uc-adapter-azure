# test_new_methods_unit.py
"""
Unit tests for the 4 new methods (using mocks):
1. AddLeaderToGroup
2. DeleteUser
3. GetGroupResourcesList
4. DeleteResource

These tests use mocks and don't require a running adapter.
Run with: python tests/test_new_methods_unit.py
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import grpc

import sys
import os

# Add parent directory to path to import main module
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from protos import adapter_interface_pb2 as pb2


class TestAddLeaderToGroup(unittest.TestCase):
    """Unit tests for AddLeaderToGroup method"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.request = pb2.AddLeaderToGroupRequest(
            group_name="test-group",
            leader_name="test-leader"
        )
        self.context = Mock()
    
    @patch('handlers.identity_handlers.normalize_name')
    @patch('handlers.identity_handlers.build_username_with_group_suffix')
    def test_add_leader_to_group_success(self, mock_build_username, mock_normalize):
        """Test AddLeaderToGroup succeeds when group exists"""
        from main import CloudAdapterServicer
        
        # Setup mocks
        mock_normalize.return_value = "test-group"
        mock_build_username.return_value = "test-leader-test-group@domain.com"
        
        servicer = CloudAdapterServicer()
        
        # Mock group exists
        mock_group = {"id": "group-id-123"}
        servicer.identity_handler.group_manager.get_group_by_name = Mock(return_value=mock_group)
        
        # Mock user creation/retrieval
        servicer.identity_handler.user_manager.get_user = Mock(return_value=None)
        servicer.identity_handler.user_manager.create_user = Mock(return_value="user-id-123")
        
        # Mock group operations
        servicer.identity_handler.group_manager.add_member = Mock()
        servicer.identity_handler.group_manager.add_owner = Mock()
        
        response = servicer.AddLeaderToGroup(self.request, self.context)
        
        self.assertIsInstance(response, pb2.AddLeaderToGroupResponse)
        self.assertTrue(response.success)
        self.assertIn("successfully added", response.message.lower())
    
    def test_add_leader_to_group_group_not_found(self):
        """Test AddLeaderToGroup fails when group doesn't exist"""
        from main import CloudAdapterServicer
        
        servicer = CloudAdapterServicer()
        
        # Mock group doesn't exist
        servicer.identity_handler.group_manager.get_group_by_name = Mock(return_value=None)
        
        response = servicer.AddLeaderToGroup(self.request, self.context)
        
        self.assertIsInstance(response, pb2.AddLeaderToGroupResponse)
        self.assertFalse(response.success)
        self.assertEqual(grpc.StatusCode.NOT_FOUND, self.context.set_code.call_args[0][0])


class TestDeleteUser(unittest.TestCase):
    """Unit tests for DeleteUser method"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.request = pb2.DeleteUserRequest(
            user_name="test-user",
            group_name="test-group"
        )
        self.context = Mock()
    
    @patch('handlers.identity_handlers.normalize_name')
    @patch('handlers.identity_handlers.build_username_with_group_suffix')
    def test_delete_user_success(self, mock_build_username, mock_normalize):
        """Test DeleteUser succeeds"""
        from main import CloudAdapterServicer
        
        # Setup mocks
        mock_normalize.return_value = "test-group"
        mock_build_username.return_value = "test-user-test-group@domain.com"
        
        servicer = CloudAdapterServicer()
        
        # Mock user deletion
        servicer.identity_handler.user_manager.delete_user = Mock()
        
        response = servicer.DeleteUser(self.request, self.context)
        
        self.assertIsInstance(response, pb2.DeleteUserResponse)
        self.assertTrue(response.success)
        self.assertIn("deleted successfully", response.message.lower())
    
    @patch('handlers.identity_handlers.normalize_name')
    @patch('handlers.identity_handlers.build_username_with_group_suffix')
    def test_delete_user_not_found(self, mock_build_username, mock_normalize):
        """Test DeleteUser handles user not found gracefully"""
        from main import CloudAdapterServicer
        
        # Setup mocks
        mock_normalize.return_value = "test-group"
        mock_build_username.return_value = "test-user-test-group@domain.com"
        
        servicer = CloudAdapterServicer()
        
        # Mock user not found exception
        from azure.core.exceptions import ResourceNotFoundError
        servicer.identity_handler.user_manager.delete_user = Mock(
            side_effect=ResourceNotFoundError("User not found")
        )
        
        response = servicer.DeleteUser(self.request, self.context)
        
        self.assertIsInstance(response, pb2.DeleteUserResponse)
        self.assertFalse(response.success)
        self.assertIn("not found", response.message.lower())


class TestGetGroupResourcesList(unittest.TestCase):
    """Unit tests for GetGroupResourcesList method"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.request = pb2.GetGroupResourcesListRequest(
            groupName="test-group"
        )
        self.context = Mock()
    
    @patch('handlers.resource_handlers.normalize_name')
    def test_get_group_resources_list_success(self, mock_normalize):
        """Test GetGroupResourcesList returns resources"""
        from main import CloudAdapterServicer
        
        # Setup mocks
        mock_normalize.return_value = "test-group"
        
        servicer = CloudAdapterServicer()
        
        # Mock resources found
        mock_resources = [
            {
                "id": "/subscriptions/123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                "name": "vm1",
                "type": "Microsoft.Compute/virtualMachines",
                "service": "vm",
                "resource_group": "rg"
            }
        ]
        servicer.resource_handler.resource_finder.find_resources_by_tags = Mock(
            return_value=mock_resources
        )
        
        # Mock resource client
        with patch('handlers.resource_handlers.get_resource_client') as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            
            mock_resource = Mock()
            mock_resource.tags = {"Name": "Test VM", "CreatedBy": "test-user"}
            mock_resource.properties = {"provisioningState": "Succeeded"}
            
            mock_client.resources.get_by_id = Mock(return_value=mock_resource)
            
            response = servicer.GetGroupResourcesList(self.request, self.context)
        
        self.assertIsInstance(response, pb2.GetGroupResourcesListResponse)
        self.assertTrue(response.success)
        self.assertGreater(len(list(response.resources)), 0)
    
    @patch('handlers.resource_handlers.normalize_name')
    def test_get_group_resources_list_no_resources(self, mock_normalize):
        """Test GetGroupResourcesList returns empty list when no resources"""
        from main import CloudAdapterServicer
        
        # Setup mocks
        mock_normalize.return_value = "test-group"
        
        servicer = CloudAdapterServicer()
        
        # Mock no resources found
        servicer.resource_handler.resource_finder.find_resources_by_tags = Mock(
            return_value=[]
        )
        
        response = servicer.GetGroupResourcesList(self.request, self.context)
        
        self.assertIsInstance(response, pb2.GetGroupResourcesListResponse)
        self.assertTrue(response.success)
        self.assertEqual(len(list(response.resources)), 0)
        self.assertIn("no resources found", response.message.lower())


class TestDeleteResource(unittest.TestCase):
    """Unit tests for DeleteResource method"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.request = pb2.DeleteResourceRequest(
            resource_global_id="/subscriptions/123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
        )
        self.context = Mock()
    
    def test_delete_resource_success(self):
        """Test DeleteResource succeeds"""
        from main import CloudAdapterServicer
        
        servicer = CloudAdapterServicer()
        
        # Mock resource deleter
        servicer.resource_handler.resource_deleter.delete_resource = Mock(
            return_value="Deleted VM: vm1"
        )
        
        # Mock service name extraction
        servicer.resource_handler.resource_finder._extract_service_name = Mock(
            return_value="vm"
        )
        
        response = servicer.DeleteResource(self.request, self.context)
        
        self.assertIsInstance(response, pb2.DeleteResourceResponse)
        self.assertTrue(response.success)
        self.assertIn("deleted", response.message.lower())
    
    def test_delete_resource_empty_id(self):
        """Test DeleteResource fails with empty resource ID"""
        from main import CloudAdapterServicer
        
        servicer = CloudAdapterServicer()
        
        request_empty = pb2.DeleteResourceRequest(resource_global_id="")
        response = servicer.DeleteResource(request_empty, self.context)
        
        self.assertIsInstance(response, pb2.DeleteResourceResponse)
        self.assertFalse(response.success)
        self.assertEqual(grpc.StatusCode.INVALID_ARGUMENT, self.context.set_code.call_args[0][0])
    
    def test_delete_resource_invalid_format(self):
        """Test DeleteResource fails with invalid resource ID format"""
        from main import CloudAdapterServicer
        
        servicer = CloudAdapterServicer()
        
        request_invalid = pb2.DeleteResourceRequest(
            resource_global_id="invalid-format"
        )
        response = servicer.DeleteResource(request_invalid, self.context)
        
        self.assertIsInstance(response, pb2.DeleteResourceResponse)
        self.assertFalse(response.success)
        self.assertEqual(grpc.StatusCode.INVALID_ARGUMENT, self.context.set_code.call_args[0][0])
    
    def test_delete_resource_deletion_fails(self):
        """Test DeleteResource handles deletion failure"""
        from main import CloudAdapterServicer
        
        servicer = CloudAdapterServicer()
        
        # Mock resource deleter fails
        servicer.resource_handler.resource_deleter.delete_resource = Mock(
            return_value="Error deleting resource: Access denied"
        )
        
        # Mock service name extraction
        servicer.resource_handler.resource_finder._extract_service_name = Mock(
            return_value="vm"
        )
        
        response = servicer.DeleteResource(self.request, self.context)
        
        self.assertIsInstance(response, pb2.DeleteResourceResponse)
        self.assertFalse(response.success)
        self.assertIn("error", response.message.lower())


class TestNewMethodsIntegration(unittest.TestCase):
    """Integration-style tests that verify method contracts"""
    
    def test_add_leader_to_group_response_structure(self):
        """Test AddLeaderToGroup response has correct structure"""
        response = pb2.AddLeaderToGroupResponse()
        response.success = True
        response.message = "Leader added"
        
        self.assertTrue(hasattr(response, 'success'))
        self.assertTrue(hasattr(response, 'message'))
        self.assertIsInstance(response.success, bool)
        self.assertIsInstance(response.message, str)
    
    def test_delete_user_response_structure(self):
        """Test DeleteUser response has correct structure"""
        response = pb2.DeleteUserResponse()
        response.success = True
        response.message = "User deleted"
        
        self.assertTrue(hasattr(response, 'success'))
        self.assertTrue(hasattr(response, 'message'))
        self.assertIsInstance(response.success, bool)
        self.assertIsInstance(response.message, str)
    
    def test_get_group_resources_list_response_structure(self):
        """Test GetGroupResourcesList response has correct structure"""
        response = pb2.GetGroupResourcesListResponse()
        response.success = True
        response.message = "Resources retrieved"
        
        # Add a sample resource
        resource = pb2.ResourceDetail(
            resource_global_id="/subscriptions/123/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            name="vm1",
            type="Virtual Machine",
            service="vm",
            created_by="test-user",
            resource_id="vm1",
            status="running"
        )
        response.resources.append(resource)
        
        self.assertTrue(hasattr(response, 'success'))
        self.assertTrue(hasattr(response, 'resources'))
        self.assertTrue(hasattr(response, 'message'))
        self.assertIsInstance(response.success, bool)
        self.assertEqual(len(list(response.resources)), 1)
        
        # Validate ResourceDetail structure
        first_resource = list(response.resources)[0]
        self.assertTrue(hasattr(first_resource, 'resource_global_id'))
        self.assertTrue(hasattr(first_resource, 'name'))
        self.assertTrue(hasattr(first_resource, 'type'))
        self.assertTrue(hasattr(first_resource, 'service'))
        self.assertTrue(hasattr(first_resource, 'created_by'))
        self.assertTrue(hasattr(first_resource, 'resource_id'))
        self.assertTrue(hasattr(first_resource, 'status'))
    
    def test_delete_resource_response_structure(self):
        """Test DeleteResource response has correct structure"""
        response = pb2.DeleteResourceResponse()
        response.success = True
        response.message = "Resource deleted"
        
        self.assertTrue(hasattr(response, 'success'))
        self.assertTrue(hasattr(response, 'message'))
        self.assertIsInstance(response.success, bool)
        self.assertIsInstance(response.message, str)


if __name__ == '__main__':
    unittest.main()
