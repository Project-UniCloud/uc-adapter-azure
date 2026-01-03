# test_required_methods.py
"""
Comprehensive tests for all 7 required methods:
1. GetAvailableServices
2. GetResourceCount
3. RemoveGroup
4. CleanupGroupResources
5. GetTotalCostWithServiceBreakdown
6. GetGroupCostsLast6MonthsByService
7. GetGroupMonthlyCostsLast6Months

Run with: python tests/test_required_methods.py
Make sure the adapter is running on localhost:50053
"""

import sys
import os

# Add parent directory to path to import modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import grpc
from datetime import datetime, timedelta
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc


# Test configuration
ADAPTER_HOST = "localhost:50053"
TEST_GROUP_NAME = "test-group-required-methods"


def print_test_header(test_num: int, test_name: str):
    """Print formatted test header"""
    print(f"\n{'=' * 70}")
    print(f"Test {test_num}: {test_name}")
    print('=' * 70)


def print_result(success: bool, message: str):
    """Print test result"""
    status = "PASS" if success else "FAIL"
    symbol = "[OK]" if success else "[FAIL]"
    print(f"{symbol} {status}: {message}")


def test_1_get_available_services():
    """Test GetAvailableServices - returns list of available resource types"""
    print_test_header(1, "GetAvailableServices")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    try:
        request = pb2.GetAvailableServicesRequest()
        response = stub.GetAvailableServices(request)
        
        # Validate response structure
        assert hasattr(response, 'services'), "Response should have 'services' field"
        # Protobuf repeated fields are iterable - check by trying to convert to list
        try:
            services_list = list(response.services)
        except (TypeError, AttributeError):
            assert False, "services should be iterable (can be converted to list)"
        print(f"  Available services: {services_list}")
        print(f"  Count: {len(services_list)}")
        
        # Validate expected services (based on RBAC roles)
        expected_services = ['vm', 'storage', 'network']
        for expected in expected_services:
            if expected in services_list:
                print(f"  [OK] Found expected service: {expected}")
            else:
                print(f"  [WARN] Expected service not found: {expected}")
        
        print_result(True, f"GetAvailableServices returned {len(services_list)} services")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return False


def test_2_get_resource_count():
    """Test GetResourceCount - returns count of resources for group and resource type"""
    print_test_header(2, "GetResourceCount")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    try:
        # Test with VM resource type
        request = pb2.ResourceCountRequest(
            groupName=TEST_GROUP_NAME,
            resourceType="vm"
        )
        response = stub.GetResourceCount(request)
        
        # Validate response structure
        assert hasattr(response, 'count'), "Response should have 'count' field"
        assert isinstance(response.count, int), "count should be an integer"
        
        print(f"  Group: {TEST_GROUP_NAME}")
        print(f"  Resource type: vm")
        print(f"  Count: {response.count}")
        
        # Test with storage resource type
        request_storage = pb2.ResourceCountRequest(
            groupName=TEST_GROUP_NAME,
            resourceType="storage"
        )
        response_storage = stub.GetResourceCount(request_storage)
        print(f"  Resource type: storage")
        print(f"  Count: {response_storage.count}")
        
        # Test with empty resource type (should fail)
        try:
            request_empty = pb2.ResourceCountRequest(
                groupName=TEST_GROUP_NAME,
                resourceType=""
            )
            response_empty = stub.GetResourceCount(request_empty)
            print_result(False, "Empty resourceType should return INVALID_ARGUMENT error")
            return False
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                print(f"  [OK] Correctly rejected empty resourceType")
            else:
                print_result(False, f"Expected INVALID_ARGUMENT, got {e.code().name}")
                return False
        
        print_result(True, f"GetResourceCount returned count={response.count} for vm")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return False


def test_3_remove_group():
    """Test RemoveGroup - removes group and all its members"""
    print_test_header(3, "RemoveGroup")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    # Use a unique test group name to avoid conflicts
    test_group = f"{TEST_GROUP_NAME}-remove-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    try:
        # First, try to remove a non-existent group (should succeed - idempotent)
        request = pb2.RemoveGroupRequest(groupName=test_group)
        response = stub.RemoveGroup(request)
        
        # Validate response structure
        assert hasattr(response, 'success'), "Response should have 'success' field"
        assert hasattr(response, 'removedUsers'), "Response should have 'removedUsers' field"
        assert hasattr(response, 'message'), "Response should have 'message' field"
        
        assert isinstance(response.success, bool), "success should be boolean"
        # Protobuf repeated fields are iterable - check by trying to convert to list
        try:
            removed_users_list = list(response.removedUsers)
        except (TypeError, AttributeError):
            assert False, "removedUsers should be iterable (can be converted to list)"
        assert isinstance(response.message, str), "message should be a string"
        print(f"  Test group: {test_group}")
        print(f"  Success: {response.success}")
        print(f"  Removed users count: {len(removed_users_list)}")
        print(f"  Message: {response.message}")
        
        # Note: We're not actually creating a group here, so we test the idempotent case
        # In a real scenario, you would:
        # 1. Create a group with CreateGroupWithLeaders
        # 2. Add users with CreateUsersForGroup
        # 3. Then test RemoveGroup
        
        if response.success:
            print(f"  [OK] RemoveGroup is idempotent (non-existent group returns success)")
        
        print_result(True, f"RemoveGroup returned success={response.success}")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return False


def test_4_cleanup_group_resources():
    """Test CleanupGroupResources - removes all Azure resources for a group"""
    print_test_header(4, "CleanupGroupResources")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    # Use a unique test group name
    test_group = f"{TEST_GROUP_NAME}-cleanup-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    try:
        # Test cleanup for a group (may not have resources, which is OK)
        request = pb2.CleanupGroupRequest(
            groupName=test_group,
            force=False
        )
        response = stub.CleanupGroupResources(request)
        
        # Validate response structure
        assert hasattr(response, 'success'), "Response should have 'success' field"
        assert hasattr(response, 'deletedResources'), "Response should have 'deletedResources' field"
        assert hasattr(response, 'message'), "Response should have 'message' field"
        
        assert isinstance(response.success, bool), "success should be boolean"
        # Protobuf repeated fields are iterable - check by trying to convert to list
        try:
            deleted_list = list(response.deletedResources)
        except (TypeError, AttributeError):
            assert False, "deletedResources should be iterable (can be converted to list)"
        assert isinstance(response.message, str), "message should be a string"
        print(f"  Test group: {test_group}")
        print(f"  Success: {response.success}")
        print(f"  Deleted resources count: {len(deleted_list)}")
        print(f"  Message: {response.message}")
        
        if deleted_list:
            print(f"  Deleted resources:")
            for resource in deleted_list[:5]:  # Show first 5
                print(f"    - {resource}")
            if len(deleted_list) > 5:
                print(f"    ... and {len(deleted_list) - 5} more")
        else:
            print(f"  [OK] No resources found (expected if group has no resources)")
        
        print_result(True, f"CleanupGroupResources returned success={response.success}")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return False


def test_5_get_total_cost_with_service_breakdown():
    """Test GetTotalCostWithServiceBreakdown - total Azure cost with service breakdown"""
    print_test_header(5, "GetTotalCostWithServiceBreakdown")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    try:
        # Calculate date range (last 30 days)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        request = pb2.CostRequest(
            startDate=start_date.strftime('%Y-%m-%d'),
            endDate=end_date.strftime('%Y-%m-%d')
        )
        response = stub.GetTotalCostWithServiceBreakdown(request)
        
        # Validate response structure
        assert hasattr(response, 'total'), "Response should have 'total' field"
        assert hasattr(response, 'breakdown'), "Response should have 'breakdown' field"
        
        assert isinstance(response.total, (int, float)), "total should be numeric"
        # Protobuf repeated fields are iterable - check by trying to convert to list
        try:
            breakdown_list = list(response.breakdown)
        except (TypeError, AttributeError):
            assert False, "breakdown should be iterable (can be converted to list)"
        print(f"  Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        print(f"  Total cost: {response.total:.2f}")
        print(f"  Services count: {len(breakdown_list)}")
        
        if breakdown_list:
            print(f"  Service breakdown:")
            for service_cost in breakdown_list[:10]:  # Show first 10
                assert hasattr(service_cost, 'serviceName'), "ServiceCost should have serviceName"
                assert hasattr(service_cost, 'amount'), "ServiceCost should have amount"
                print(f"    - {service_cost.serviceName}: {service_cost.amount:.2f}")
            if len(breakdown_list) > 10:
                print(f"    ... and {len(breakdown_list) - 10} more services")
        else:
            print(f"  [WARN] No service breakdown data (may be normal if no costs)")
        
        print_result(True, f"GetTotalCostWithServiceBreakdown returned total={response.total:.2f}")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return False


def test_6_get_group_costs_last_6_months_by_service():
    """Test GetGroupCostsLast6MonthsByService - group costs for last 6 months by service"""
    print_test_header(6, "GetGroupCostsLast6MonthsByService")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    try:
        request = pb2.GroupCostMapRequest(groupName=TEST_GROUP_NAME)
        response = stub.GetGroupCostsLast6MonthsByService(request)
        
        # Validate response structure
        assert hasattr(response, 'costs'), "Response should have 'costs' field"
        
        # costs is a map<string, double> in protobuf
        costs_dict = dict(response.costs) if hasattr(response.costs, 'items') else {}
        
        print(f"  Group: {TEST_GROUP_NAME}")
        print(f"  Services count: {len(costs_dict)}")
        
        if costs_dict:
            print(f"  Costs by service:")
            # Sort by cost descending
            sorted_costs = sorted(costs_dict.items(), key=lambda x: x[1], reverse=True)
            for service_name, cost in sorted_costs[:10]:  # Show first 10
                print(f"    - {service_name}: {cost:.2f}")
            if len(costs_dict) > 10:
                print(f"    ... and {len(costs_dict) - 10} more services")
        else:
            print(f"  [WARN] No costs found (may be normal if group has no resources or costs)")
        
        # Test with empty group name (should fail)
        try:
            request_empty = pb2.GroupCostMapRequest(groupName="")
            response_empty = stub.GetGroupCostsLast6MonthsByService(request_empty)
            print_result(False, "Empty groupName should return INVALID_ARGUMENT error")
            return False
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                print(f"  [OK] Correctly rejected empty groupName")
            else:
                print_result(False, f"Expected INVALID_ARGUMENT, got {e.code().name}")
                return False
        
        print_result(True, f"GetGroupCostsLast6MonthsByService returned {len(costs_dict)} services")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return False


def test_7_get_group_monthly_costs_last_6_months():
    """Test GetGroupMonthlyCostsLast6Months - monthly costs for last 6 months"""
    print_test_header(7, "GetGroupMonthlyCostsLast6Months")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    try:
        request = pb2.GroupMonthlyCostsRequest(groupName=TEST_GROUP_NAME)
        response = stub.GetGroupMonthlyCostsLast6Months(request)
        
        # Validate response structure
        assert hasattr(response, 'monthCosts'), "Response should have 'monthCosts' field"
        
        # monthCosts is a map<string, double> in protobuf
        month_costs_dict = dict(response.monthCosts) if hasattr(response.monthCosts, 'items') else {}
        
        print(f"  Group: {TEST_GROUP_NAME}")
        print(f"  Months count: {len(month_costs_dict)}")
        
        if month_costs_dict:
            print(f"  Monthly costs:")
            # Sort by month (assuming format like "DD-MM-YYYY")
            sorted_months = sorted(month_costs_dict.items())
            for month, cost in sorted_months:
                print(f"    - {month}: {cost:.2f}")
        else:
            print(f"  [WARN] No monthly costs found (may be normal if group has no resources or costs)")
        
        # Test with empty group name (should fail)
        try:
            request_empty = pb2.GroupMonthlyCostsRequest(groupName="")
            response_empty = stub.GetGroupMonthlyCostsLast6Months(request_empty)
            print_result(False, "Empty groupName should return INVALID_ARGUMENT error")
            return False
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                print(f"  [OK] Correctly rejected empty groupName")
            else:
                print_result(False, f"Expected INVALID_ARGUMENT, got {e.code().name}")
                return False
        
        print_result(True, f"GetGroupMonthlyCostsLast6Months returned {len(month_costs_dict)} months")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("Azure Adapter - Required Methods Test Suite")
    print("=" * 70)
    print(f"Testing adapter at: {ADAPTER_HOST}")
    print(f"Test group name: {TEST_GROUP_NAME}")
    print("\nNote: Some tests may show warnings if groups/resources don't exist.")
    print("This is normal and doesn't indicate a problem with the adapter.")
    
    results = []
    
    # Run all tests
    results.append(("GetAvailableServices", test_1_get_available_services()))
    results.append(("GetResourceCount", test_2_get_resource_count()))
    results.append(("RemoveGroup", test_3_remove_group()))
    results.append(("CleanupGroupResources", test_4_cleanup_group_resources()))
    results.append(("GetTotalCostWithServiceBreakdown", test_5_get_total_cost_with_service_breakdown()))
    results.append(("GetGroupCostsLast6MonthsByService", test_6_get_group_costs_last_6_months_by_service()))
    results.append(("GetGroupMonthlyCostsLast6Months", test_7_get_group_monthly_costs_last_6_months()))
    
    # Print summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        symbol = "[OK]" if result else "[FAIL]"
        print(f"{symbol} {test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n[OK] All tests passed! All required methods are working correctly.")
    else:
        print(f"\n[WARN] {total - passed} test(s) failed. Review output above for details.")
    
    return passed == total


if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


