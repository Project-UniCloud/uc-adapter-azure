# test_get_total_costs_for_all_groups.py
"""
Regression tests for GetTotalCostsForAllGroups method.
Tests that group name denormalization does not corrupt names that legitimately contain dashes.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path to import main module
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from protos import adapter_interface_pb2 as pb2


class TestGetTotalCostsForAllGroups(unittest.TestCase):
    """Test cases for GetTotalCostsForAllGroups method"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.request = pb2.CostRequest()
        self.request.startDate = "2025-01-01"
        self.request.endDate = "2025-01-31"
        self.context = Mock()
    
    def test_standard_format_denormalization(self):
        """Test that standard format names are denormalized correctly"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        
        # Mock cost_manager.get_total_costs_for_all_groups to return normalized names
        with patch('handlers.cost_handlers.cost_manager.get_total_costs_for_all_groups') as mock_get_costs:
            mock_get_costs.return_value = {
                "AI-2024L": 100.0,
                "Test-Group-2024L": 200.0,
            }
            
            response = servicer.GetTotalCostsForAllGroups(self.request, self.context)
            
            # Check that names were denormalized
            group_names = [gc.groupName for gc in response.groupCosts]
            self.assertIn("AI 2024L", group_names)
            self.assertIn("Test Group 2024L", group_names)
            
            # Check costs
            costs_dict = {gc.groupName: gc.amount for gc in response.groupCosts}
            self.assertEqual(costs_dict["AI 2024L"], 100.0)
            self.assertEqual(costs_dict["Test Group 2024L"], 200.0)
    
    def test_non_standard_format_preservation(self):
        """
        REGRESSION TEST: Names that legitimately contain dashes (without semester) 
        must NOT be denormalized.
        
        This prevents corruption of names like "A-B" -> "A B".
        """
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        
        # Mock cost_manager.get_total_costs_for_all_groups to return names with dashes
        with patch('handlers.cost_handlers.cost_manager.get_total_costs_for_all_groups') as mock_get_costs:
            mock_get_costs.return_value = {
                "A-B": 50.0,  # Name that legitimately contains dash
                "My-Group": 75.0,  # Name that legitimately contains dash
                "Test-Name": 25.0,  # Name that legitimately contains dash
            }
            
            response = servicer.GetTotalCostsForAllGroups(self.request, self.context)
            
            # Check that names were NOT denormalized (preserved as-is)
            group_names = [gc.groupName for gc in response.groupCosts]
            self.assertIn("A-B", group_names, "Name 'A-B' must NOT be denormalized to 'A B'")
            self.assertIn("My-Group", group_names, "Name 'My-Group' must NOT be denormalized")
            self.assertIn("Test-Name", group_names, "Name 'Test-Name' must NOT be denormalized")
            
            # Verify they were NOT changed
            self.assertNotIn("A B", group_names, "Name 'A-B' must NOT become 'A B'")
            self.assertNotIn("My Group", group_names, "Name 'My-Group' must NOT become 'My Group'")
            self.assertNotIn("Test Name", group_names, "Name 'Test-Name' must NOT become 'Test Name'")
            
            # Check costs
            costs_dict = {gc.groupName: gc.amount for gc in response.groupCosts}
            self.assertEqual(costs_dict["A-B"], 50.0)
            self.assertEqual(costs_dict["My-Group"], 75.0)
            self.assertEqual(costs_dict["Test-Name"], 25.0)
    
    def test_mixed_format_handling(self):
        """Test that both standard and non-standard formats are handled correctly"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        
        # Mock cost_manager.get_total_costs_for_all_groups to return mixed names
        with patch('handlers.cost_handlers.cost_manager.get_total_costs_for_all_groups') as mock_get_costs:
            mock_get_costs.return_value = {
                "AI-2024L": 100.0,  # Standard format - should be denormalized
                "A-B": 50.0,  # Non-standard format - should be preserved
                "Test-Group-2024L": 200.0,  # Standard format - should be denormalized
                "My-Group": 75.0,  # Non-standard format - should be preserved
            }
            
            response = servicer.GetTotalCostsForAllGroups(self.request, self.context)
            
            # Check standard format names were denormalized
            group_names = [gc.groupName for gc in response.groupCosts]
            self.assertIn("AI 2024L", group_names)
            self.assertIn("Test Group 2024L", group_names)
            
            # Check non-standard format names were preserved
            self.assertIn("A-B", group_names, "Name 'A-B' must NOT be denormalized")
            self.assertIn("My-Group", group_names, "Name 'My-Group' must NOT be denormalized")
            
            # Verify non-standard names were NOT changed
            self.assertNotIn("A B", group_names, "Name 'A-B' must NOT become 'A B'")
            self.assertNotIn("My Group", group_names, "Name 'My-Group' must NOT become 'My Group'")
            
            # Check costs
            costs_dict = {gc.groupName: gc.amount for gc in response.groupCosts}
            self.assertEqual(costs_dict["AI 2024L"], 100.0)
            self.assertEqual(costs_dict["A-B"], 50.0)
            self.assertEqual(costs_dict["Test Group 2024L"], 200.0)
            self.assertEqual(costs_dict["My-Group"], 75.0)
    
    def test_safe_denormalize_group_name_method(self):
        """Test the _safe_denormalize_group_name method directly"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        
        # Standard format - should be denormalized
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name("AI-2024L"), "AI 2024L")
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name("Test-Group-2024L"), "Test Group 2024L")
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name("DS-2025Z"), "DS 2025Z")
        
        # Non-standard format - should be preserved
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name("A-B"), "A-B")
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name("My-Group"), "My-Group")
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name("Test-Name"), "Test-Name")
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name("Some-Other-Name"), "Some-Other-Name")
        
        # Edge cases
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name("2024L"), "2024L")  # Only semester
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name(""), "")  # Empty string
        self.assertEqual(servicer.cost_handler._safe_denormalize_group_name("AI-2024"), "AI-2024")  # No semester suffix
    
    def test_empty_costs_dict(self):
        """Test that empty costs dict returns empty response"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        
        with patch('handlers.cost_handlers.cost_manager.get_total_costs_for_all_groups') as mock_get_costs:
            mock_get_costs.return_value = {}
            
            response = servicer.GetTotalCostsForAllGroups(self.request, self.context)
            
            self.assertEqual(len(response.groupCosts), 0)
    
    def test_error_handling(self):
        """Test that errors are handled gracefully"""
        from main import CloudAdapterServicer
        servicer = CloudAdapterServicer()
        
        with patch('handlers.cost_handlers.cost_manager.get_total_costs_for_all_groups') as mock_get_costs:
            mock_get_costs.side_effect = Exception("Cost API error")
            
            response = servicer.GetTotalCostsForAllGroups(self.request, self.context)
            
            # Should return empty response on error
            self.assertEqual(len(response.groupCosts), 0)
            # Context should have error code set
            self.assertEqual(self.context.set_code.call_count, 1)


if __name__ == '__main__':
    unittest.main()

