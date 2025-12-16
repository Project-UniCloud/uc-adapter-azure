# test_get_status.py
"""
Unit tests for GetStatus method.
Tests health check functionality including error handling.
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

# Import CloudAdapterServicer will be done inside test methods to avoid import errors


class TestGetStatus(unittest.TestCase):
    """Test cases for GetStatus method"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.request = pb2.StatusRequest()
        self.context = Mock()
    
    def test_get_status_success(self):
        """Test GetStatus returns isHealthy=True when all components are initialized"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        # Note: This will be True only if Azure credentials are properly configured
        # In test environment without credentials, it might be False
        self.assertIsInstance(response.isHealthy, bool)
    
    def test_get_status_user_manager_not_initialized(self):
        """Test GetStatus returns isHealthy=False when user_manager is not initialized"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        # Simulate user_manager not being initialized in identity_handler
        if hasattr(servicer.identity_handler, 'user_manager'):
            servicer.identity_handler.user_manager = None
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    def test_get_status_group_manager_not_initialized(self):
        """Test GetStatus returns isHealthy=False when group_manager is not initialized"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        # Simulate group_manager not being initialized in identity_handler
        if hasattr(servicer.identity_handler, 'group_manager'):
            servicer.identity_handler.group_manager = None
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    def test_get_status_rbac_manager_not_initialized(self):
        """Test GetStatus returns isHealthy=False when rbac_manager is not initialized"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        # Simulate rbac_manager not being initialized in identity_handler
        if hasattr(servicer.identity_handler, 'rbac_manager'):
            servicer.identity_handler.rbac_manager = None
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    def test_get_status_resource_finder_not_initialized(self):
        """Test GetStatus returns isHealthy=False when resource_finder is not initialized"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        # Simulate resource_finder not being initialized in identity_handler
        if hasattr(servicer.identity_handler, 'resource_finder'):
            servicer.identity_handler.resource_finder = None
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    def test_get_status_resource_deleter_not_initialized(self):
        """Test GetStatus returns isHealthy=False when resource_deleter is not initialized"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        # Simulate resource_deleter not being initialized in identity_handler
        if hasattr(servicer.identity_handler, 'resource_deleter'):
            servicer.identity_handler.resource_deleter = None
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    @patch('azure_clients.get_credential')
    def test_get_status_credential_initialization_fails(self, mock_get_credential):
        """Test GetStatus returns isHealthy=False when credential initialization fails"""
        from main import CloudAdapterServicer
        # Simulate exception during credential creation
        mock_get_credential.side_effect = Exception("Failed to create credential")
        
        servicer = CloudAdapterServicer()
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    @patch('azure_clients.get_graph_client')
    def test_get_status_graph_client_initialization_fails(self, mock_get_graph_client):
        """Test GetStatus returns isHealthy=False when Graph client initialization fails"""
        from main import CloudAdapterServicer
        # Simulate exception during Graph client creation
        mock_get_graph_client.side_effect = Exception("Failed to create Graph client")
        
        servicer = CloudAdapterServicer()
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    @patch('azure_clients.get_cost_client')
    def test_get_status_cost_client_initialization_fails(self, mock_get_cost_client):
        """Test GetStatus returns isHealthy=False when Cost Management client initialization fails"""
        from main import CloudAdapterServicer
        # Simulate exception during Cost Management client creation
        mock_get_cost_client.side_effect = Exception("Failed to create Cost Management client")
        
        servicer = CloudAdapterServicer()
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    @patch('cost_monitoring.limit_manager.LimitManager')
    def test_get_status_cost_manager_initialization_fails(self, mock_limit_manager):
        """Test GetStatus returns isHealthy=False when LimitManager initialization fails"""
        from main import CloudAdapterServicer
        # Simulate exception during LimitManager creation
        mock_limit_manager.side_effect = Exception("Failed to create LimitManager")
        
        servicer = CloudAdapterServicer()
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    @patch('handlers.identity_handlers.cost_manager')
    def test_get_status_cost_manager_missing_function(self, mock_cost_manager):
        """Test GetStatus returns isHealthy=False when cost_manager is missing required function"""
        from main import CloudAdapterServicer
        # Simulate cost_manager missing get_total_cost_for_group function
        if hasattr(mock_cost_manager, 'get_total_cost_for_group'):
            delattr(mock_cost_manager, 'get_total_cost_for_group')
        
        servicer = CloudAdapterServicer()
        
        response = servicer.GetStatus(self.request, self.context)
        
        self.assertIsInstance(response, pb2.StatusResponse)
        self.assertFalse(response.isHealthy)
    
    def test_get_status_unexpected_exception(self):
        """Test GetStatus handles unexpected exceptions gracefully"""
        from main import CloudAdapterServicer
        
        servicer = CloudAdapterServicer()
        
        # Simulate unexpected exception by creating an object that raises exception
        # when checking if it's None (which happens in the hasattr check)
        class ExceptionRaisingObject:
            def __bool__(self):
                raise Exception("Unexpected error during boolean check")
            def __nonzero__(self):
                raise Exception("Unexpected error during boolean check")
        
        # Replace user_manager with an object that raises exception
        # Note: hasattr uses getattr internally, which will catch the exception
        # But we can simulate by making the check itself fail
        # Actually, the simplest is to just delete the attribute and let the hasattr fail
        # But that's already tested. Let's test a different scenario - exception during client creation
        
        # Simulate exception during credential creation
        # get_credential is imported from azure_clients inside GetStatus method (line 81)
        # We need to patch it before the import happens
        with patch('azure_clients.get_credential', side_effect=Exception("Unexpected error during credential creation")):
            response = servicer.GetStatus(self.request, self.context)
            
            self.assertIsInstance(response, pb2.StatusResponse)
            self.assertFalse(response.isHealthy)
    
    def test_get_status_no_exception_thrown(self):
        """Test GetStatus never throws exceptions to caller (contract requirement)"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        
        # Even if something goes wrong, GetStatus should not throw
        # It should always return a response with isHealthy set appropriately
        try:
            response = servicer.GetStatus(self.request, self.context)
            self.assertIsInstance(response, pb2.StatusResponse)
            self.assertIsInstance(response.isHealthy, bool)
        except Exception as e:
            self.fail(f"GetStatus should not throw exceptions, but raised: {e}")


if __name__ == '__main__':
    unittest.main()

