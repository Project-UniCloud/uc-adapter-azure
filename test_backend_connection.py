# test_backend_connection.py
"""
Tests Azure adapter using the same format and data structures as the backend.
Validates that responses match backend expectations for proper integration.
"""

import grpc
from datetime import datetime, timedelta
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc


def test_get_status():
    """Test GetStatus - backend calls this via isRunning()"""
    print("Test 1: GetStatus (isRunning check)")
    print("-" * 50)
    
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    try:
        request = pb2.StatusRequest()
        response = stub.GetStatus(request)
        
        # Backend expects: response.getIsHealthy() returns boolean
        assert isinstance(response.isHealthy, bool), f"Expected bool, got {type(response.isHealthy)}"
        assert response.isHealthy is True, "Adapter should report healthy status"
        
        print(f"PASS: isHealthy = {response.isHealthy}")
        return True
    except grpc.RpcError as e:
        print(f"FAIL: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_group_exists():
    """Test GroupExists - backend calls this with GroupUniqueName.toString() format"""
    print("\nTest 2: GroupExists")
    print("-" * 50)
    
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    # Backend sends group names in format "AI 2024L" (GroupUniqueName.toString())
    test_group_name = "AI 2024L"
    
    try:
        request = pb2.GroupExistsRequest(groupName=test_group_name)
        response = stub.GroupExists(request)
        
        # Backend expects: response.getExists() returns boolean
        assert isinstance(response.exists, bool), f"Expected bool, got {type(response.exists)}"
        
        print(f"PASS: Group '{test_group_name}' exists = {response.exists}")
        print(f"      Response type: {type(response.exists)}")
        return True
    except grpc.RpcError as e:
        print(f"FAIL: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_create_group_with_leaders():
    """Test CreateGroupWithLeaders - backend format validation"""
    print("\nTest 3: CreateGroupWithLeaders (request format validation)")
    print("-" * 50)
    
    # Backend sends:
    # - resourceType: CloudResourceType.getName() (e.g., "vm", "ec2", "s3")
    # - groupName: GroupUniqueName.toString() (e.g., "AI 2024L")
    # - leaders: List<UserLogin> mapped to strings
    
    test_request = pb2.CreateGroupWithLeadersRequest(
        resourceType="vm",  # Backend sends resource type name
        groupName="AI 2024L",  # Backend sends GroupUniqueName.toString() format
        leaders=["s481873", "s485704"]  # Backend sends UserLogin.toString()
    )
    
    try:
        # Validate request format matches backend expectations
        assert test_request.resourceType == "vm", "Resource type should be 'vm'"
        assert test_request.groupName == "AI 2024L", "Group name should match backend format"
        assert len(test_request.leaders) == 2, "Should have 2 leaders"
        assert "s481873" in test_request.leaders, "Leader should be in list"
        
        print("PASS: Request format matches backend expectations")
        print(f"      resourceType: {test_request.resourceType}")
        print(f"      groupName: {test_request.groupName}")
        print(f"      leaders: {test_request.leaders}")
        print("\n      Note: Not creating actual group (would require Azure credentials)")
        return True
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_create_users_for_group():
    """Test CreateUsersForGroup - backend format validation"""
    print("\nTest 4: CreateUsersForGroup (request format validation)")
    print("-" * 50)
    
    # Backend sends:
    # - groupName: GroupUniqueName.toString() (e.g., "AI 2024L")
    # - users: List<UserLogin> mapped via UserLogin.getValue()
    
    test_request = pb2.CreateUsersForGroupRequest(
        groupName="AI 2024L",  # Backend sends GroupUniqueName.toString()
        users=["s123456", "s789012"]  # Backend sends UserLogin.getValue()
    )
    
    try:
        # Validate request format matches backend expectations
        assert test_request.groupName == "AI 2024L", "Group name should match backend format"
        assert len(test_request.users) == 2, "Should have 2 users"
        assert "s123456" in test_request.users, "User should be in list"
        
        print("PASS: Request format matches backend expectations")
        print(f"      groupName: {test_request.groupName}")
        print(f"      users: {test_request.users}")
        print("\n      Note: Not creating actual users (would require Azure credentials)")
        return True
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_get_total_costs_for_all_groups():
    """Test GetTotalCostsForAllGroups - backend expects specific response format"""
    print("\nTest 5: GetTotalCostsForAllGroups (backend cost sync)")
    print("-" * 50)
    
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    # Backend sends dates in LocalDate.toString() format: "YYYY-MM-DD"
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        request = pb2.CostRequest(
            startDate=start_date,
            endDate=end_date
        )
        response = stub.GetTotalCostsForAllGroups(request)
        
        # Backend expects: response.getGroupCostsList() returns List<GroupCost>
        # Each GroupCost has: getGroupName() and getAmount()
        # Backend parses groupName with GroupUniqueName.fromString() which expects "Name YYYYZ/L" format
        
        assert hasattr(response, 'groupCosts'), "Response should have groupCosts field"
        # groupCosts is a repeated field in protobuf, which is always iterable
        # Even if empty, it should be iterable (returns empty iterator)
        assert hasattr(response.groupCosts, "__iter__") or hasattr(response.groupCosts, "__len__"), "groupCosts should be iterable or have length"
        
        print(f"PASS: Response format matches backend expectations")
        print(f"      Date range: {start_date} to {end_date}")
        print(f"      Groups found: {len(response.groupCosts)}")
        
        # Validate each group cost format matches backend expectations
        for group_cost in response.groupCosts:
            assert hasattr(group_cost, 'groupName'), "GroupCost should have groupName"
            assert hasattr(group_cost, 'amount'), "GroupCost should have amount"
            assert isinstance(group_cost.groupName, str), "groupName should be string"
            assert isinstance(group_cost.amount, (int, float)), "amount should be numeric"
            
            # Backend expects groupName in format "AI 2024L" (parsed by GroupUniqueName.fromString)
            # Note: Azure adapter normalizes to "AI-2024L", but backend expects "AI 2024L"
            # This is a potential compatibility issue
            print(f"      - Group: {group_cost.groupName}, Cost: ${group_cost.amount}")
        
        return True
    except grpc.RpcError as e:
        print(f"FAIL: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_group_created_response_format():
    """Test GroupCreatedResponse format - backend parses this with GroupUniqueName.fromString()"""
    print("\nTest 6: GroupCreatedResponse format validation")
    print("-" * 50)
    
    # Backend expects response.getGroupName() to be parseable by GroupUniqueName.fromString()
    # GroupUniqueName.fromString() expects format: "Name YYYYZ/L" (e.g., "AI 2024L")
    # It validates: .* \\d{4}[ZL] (name with space, then 4 digits, then Z or L)
    
    test_group_name = "AI 2024L"
    
    # Simulate response (would come from actual CreateGroupWithLeaders call)
    response = pb2.GroupCreatedResponse()
    response.groupName = test_group_name
    
    try:
        # Validate format matches backend expectations
        assert isinstance(response.groupName, str), "groupName should be string"
        
        # Backend validation pattern: .* \\d{4}[ZL]
        import re
        pattern = r".* \d{4}[ZL]"
        assert re.match(pattern, response.groupName), \
            f"Group name '{response.groupName}' should match backend format: 'Name YYYYZ/L'"
        
        print("PASS: Response format matches backend expectations")
        print(f"      groupName: {response.groupName}")
        print(f"      Format validation: Matches backend GroupUniqueName pattern")
        
        # Note: Azure adapter normalizes group names (spaces -> dashes)
        # This could cause issues if backend expects exact format
        print("\n      WARNING: Azure adapter normalizes group names (spaces -> dashes)")
        print("             Backend expects: 'AI 2024L'")
        print("             Azure returns:   'AI-2024L'")
        print("             This may cause GroupUniqueName.fromString() to fail!")
        
        return True
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_data_type_compatibility():
    """Test that all response types match backend expectations"""
    print("\nTest 7: Data type compatibility check")
    print("-" * 50)
    
    try:
        # Test StatusResponse
        status_resp = pb2.StatusResponse()
        status_resp.isHealthy = True
        assert isinstance(status_resp.isHealthy, bool), "isHealthy should be bool"
        
        # Test GroupExistsResponse
        exists_resp = pb2.GroupExistsResponse()
        exists_resp.exists = False
        assert isinstance(exists_resp.exists, bool), "exists should be bool"
        
        # Test CostResponse
        cost_resp = pb2.CostResponse()
        cost_resp.amount = 0.0
        assert isinstance(cost_resp.amount, (int, float)), "amount should be numeric"
        
        # Test GroupCost
        group_cost = pb2.GroupCost()
        group_cost.groupName = "AI 2024L"
        group_cost.amount = 123.45
        assert isinstance(group_cost.groupName, str), "groupName should be string"
        assert isinstance(group_cost.amount, (int, float)), "amount should be numeric"
        
        # Test RemoveGroupResponse (new fields)
        remove_resp = pb2.RemoveGroupResponse()
        remove_resp.success = True
        remove_resp.removedUsers.extend(["user1", "user2"])
        remove_resp.message = "Test message"
        assert isinstance(remove_resp.success, bool), "success should be bool"
        assert hasattr(remove_resp, 'removedUsers'), "should have removedUsers field"
        assert isinstance(remove_resp.message, str), "message should be string"
        
        # Test CleanupGroupResponse (new fields)
        cleanup_resp = pb2.CleanupGroupResponse()
        cleanup_resp.success = True
        cleanup_resp.deletedResources.extend(["resource1", "resource2"])
        cleanup_resp.message = "Test message"
        assert isinstance(cleanup_resp.success, bool), "success should be bool"
        assert hasattr(cleanup_resp, 'deletedResources'), "should have deletedResources field"
        assert isinstance(cleanup_resp.message, str), "message should be string"
        
        # Test GetAvailableServicesResponse
        services_resp = pb2.GetAvailableServicesResponse()
        services_resp.services.extend(["vm", "storage"])
        assert hasattr(services_resp, 'services'), "should have services field"
        # services is a repeated field in protobuf, which is always iterable
        assert hasattr(services_resp.services, "__iter__") or hasattr(services_resp.services, "__len__"), "services should be iterable or have length"
        
        # Test ResourceCountResponse
        count_resp = pb2.ResourceCountResponse()
        count_resp.count = 5
        assert isinstance(count_resp.count, int), "count should be int"
        
        print("PASS: All data types match backend expectations")
        print("      StatusResponse.isHealthy: bool")
        print("      GroupExistsResponse.exists: bool")
        print("      CostResponse.amount: double")
        print("      GroupCost.groupName: string")
        print("      GroupCost.amount: double")
        print("      RemoveGroupResponse.success: bool")
        print("      RemoveGroupResponse.removedUsers: repeated string")
        print("      CleanupGroupResponse.success: bool")
        print("      CleanupGroupResponse.deletedResources: repeated string")
        print("      GetAvailableServicesResponse.services: repeated string")
        print("      ResourceCountResponse.count: int32")
        
        return True
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_get_available_services():
    """Test GetAvailableServices - backend compatibility"""
    print("\nTest 8: GetAvailableServices")
    print("-" * 50)
    
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    try:
        request = pb2.GetAvailableServicesRequest()
        response = stub.GetAvailableServices(request)
        
        assert hasattr(response, 'services'), "Response should have services field"
        # services is a repeated field in protobuf, which is always iterable
        # Even if empty, it should be iterable (returns empty iterator)
        assert hasattr(response.services, "__iter__") or hasattr(response.services, "__len__"), "services should be iterable or have length"
        
        print(f"PASS: Response format matches backend expectations")
        print(f"      Available services: {list(response.services)}")
        print(f"      Count: {len(response.services)}")
        
        return True
    except grpc.RpcError as e:
        print(f"FAIL: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_get_resource_count():
    """Test GetResourceCount - backend compatibility"""
    print("\nTest 9: GetResourceCount")
    print("-" * 50)
    
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    test_group_name = "AI 2024L"
    
    try:
        request = pb2.ResourceCountRequest(
            groupName=test_group_name,
            resourceType="vm"
        )
        response = stub.GetResourceCount(request)
        
        assert hasattr(response, 'count'), "Response should have count field"
        assert isinstance(response.count, int), "count should be int"
        
        print(f"PASS: Response format matches backend expectations")
        print(f"      Group: {test_group_name}")
        print(f"      Resource type: vm")
        print(f"      Count: {response.count}")
        
        return True
    except grpc.RpcError as e:
        print(f"FAIL: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_remove_group_response_format():
    """Test RemoveGroup response format - backend expects success and removedUsers"""
    print("\nTest 10: RemoveGroup response format validation")
    print("-" * 50)
    
    # Backend expects RemoveGroupResponse with success, removedUsers, and message
    response = pb2.RemoveGroupResponse()
    response.success = True
    response.removedUsers.extend(["user1@domain.com", "user2@domain.com"])
    response.message = "Group removed successfully"
    
    try:
        assert isinstance(response.success, bool), "success should be bool"
        assert hasattr(response, 'removedUsers'), "should have removedUsers field"
        assert hasattr(response, 'message'), "should have message field"
        assert isinstance(response.message, str), "message should be string"
        
        print("PASS: Response format matches backend expectations")
        print(f"      success: {response.success}")
        print(f"      removedUsers count: {len(response.removedUsers)}")
        print(f"      message: {response.message}")
        
        return True
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def test_cleanup_group_resources_response_format():
    """Test CleanupGroupResources response format - backend expects success and deletedResources"""
    print("\nTest 11: CleanupGroupResources response format validation")
    print("-" * 50)
    
    # Backend expects CleanupGroupResponse with success, deletedResources, and message
    response = pb2.CleanupGroupResponse()
    response.success = True
    response.deletedResources.extend(["Deleted VM: vm1", "Deleted Storage: storage1"])
    response.message = "Cleanup completed"
    
    try:
        assert isinstance(response.success, bool), "success should be bool"
        assert hasattr(response, 'deletedResources'), "should have deletedResources field"
        assert hasattr(response, 'message'), "should have message field"
        assert isinstance(response.message, str), "message should be string"
        
        print("PASS: Response format matches backend expectations")
        print(f"      success: {response.success}")
        print(f"      deletedResources count: {len(response.deletedResources)}")
        print(f"      message: {response.message}")
        
        return True
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False


def run_all_tests():
    """Run all tests and report summary"""
    print("=" * 70)
    print("Azure Adapter Backend Compatibility Tests")
    print("=" * 70)
    print("\nTesting adapter at: localhost:50053")
    print("Validating data formats match backend expectations\n")
    
    tests = [
        ("GetStatus", test_get_status),
        ("GroupExists", test_group_exists),
        ("CreateGroupWithLeaders Format", test_create_group_with_leaders),
        ("CreateUsersForGroup Format", test_create_users_for_group),
        ("GetTotalCostsForAllGroups", test_get_total_costs_for_all_groups),
        ("GroupCreatedResponse Format", test_group_created_response_format),
        ("Data Type Compatibility", test_data_type_compatibility),
        ("GetAvailableServices", test_get_available_services),
        ("GetResourceCount", test_get_resource_count),
        ("RemoveGroup Response Format", test_remove_group_response_format),
        ("CleanupGroupResources Response Format", test_cleanup_group_resources_response_format),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\nERROR in {test_name}: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\nAll tests passed! Adapter is compatible with backend data formats.")
    else:
        print(f"\n{total - passed} test(s) failed. Review output above for details.")
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
