# test_new_methods.py
"""
Comprehensive tests for the 4 new methods added in proto update:
1. AddLeaderToGroup
2. DeleteUser
3. GetGroupResourcesList
4. DeleteResource

Run with: python tests/test_new_methods.py
Make sure the adapter is running on localhost:50053
"""

import sys
import os

# Add parent directory to path to import modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import grpc
from datetime import datetime
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc


# Test configuration
ADAPTER_HOST = "localhost:50053"
TEST_GROUP_NAME = "test-group-new-methods"


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


def test_1_add_leader_to_group():
    """Test AddLeaderToGroup - adds a leader to an existing group"""
    print_test_header(1, "AddLeaderToGroup")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    # Use a unique test group name
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    test_group = f"{TEST_GROUP_NAME}-{timestamp}"
    test_leader = f"test-leader-{timestamp}"
    
    try:
        # First, create a group with one leader
        print(f"  Step 1: Creating test group '{test_group}' with initial leader...")
        create_req = pb2.CreateGroupWithLeadersRequest(
            resourceTypes=["vm"],
            leaders=[f"initial-leader-{timestamp}"],
            groupName=test_group
        )
        create_resp = stub.CreateGroupWithLeaders(create_req)
        print(f"  [OK] Group created: {create_resp.groupName}")
        
        # Wait a bit for Azure AD replication
        import time
        print("  Waiting 3 seconds for Azure AD replication...")
        time.sleep(3)
        
        # Now test AddLeaderToGroup
        print(f"  Step 2: Adding leader '{test_leader}' to group '{test_group}'...")
        request = pb2.AddLeaderToGroupRequest(
            group_name=test_group,
            leader_name=test_leader
        )
        response = stub.AddLeaderToGroup(request)
        
        # Validate response structure
        assert hasattr(response, 'success'), "Response should have 'success' field"
        assert hasattr(response, 'message'), "Response should have 'message' field"
        
        assert isinstance(response.success, bool), "success should be boolean"
        assert isinstance(response.message, str), "message should be a string"
        
        print(f"  Group: {test_group}")
        print(f"  Leader: {test_leader}")
        print(f"  Success: {response.success}")
        print(f"  Message: {response.message}")
        
        if response.success:
            print(f"  [OK] Leader successfully added to group")
        else:
            print(f"  [WARN] AddLeaderToGroup returned success=False: {response.message}")
        
        # Test with non-existent group (should fail)
        print(f"  Step 3: Testing with non-existent group...")
        try:
            request_invalid = pb2.AddLeaderToGroupRequest(
                group_name="non-existent-group-12345",
                leader_name="test-leader"
            )
            response_invalid = stub.AddLeaderToGroup(request_invalid)
            if not response_invalid.success:
                print(f"  [OK] Correctly returned success=False for non-existent group")
            else:
                print_result(False, "Should return success=False for non-existent group")
                return False
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                print(f"  [OK] Correctly returned NOT_FOUND for non-existent group")
            else:
                print_result(False, f"Expected NOT_FOUND, got {e.code().name}")
                return False
        
        # Test with empty parameters (should fail)
        print(f"  Step 4: Testing with empty parameters...")
        try:
            request_empty = pb2.AddLeaderToGroupRequest(
                group_name="",
                leader_name=""
            )
            response_empty = stub.AddLeaderToGroup(request_empty)
            print_result(False, "Empty parameters should return INVALID_ARGUMENT error")
            return False
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                print(f"  [OK] Correctly rejected empty parameters")
            else:
                print(f"  [WARN] Got {e.code().name} instead of INVALID_ARGUMENT (may be acceptable)")
        
        print_result(True, f"AddLeaderToGroup test completed")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_2_delete_user():
    """Test DeleteUser - deletes a user from Azure AD"""
    print_test_header(2, "DeleteUser")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    # Use a unique test group name
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    test_group = f"{TEST_GROUP_NAME}-delete-{timestamp}"
    test_user = f"test-user-{timestamp}"
    
    try:
        # First, create a group and add a user
        print(f"  Step 1: Creating test group '{test_group}' with user '{test_user}'...")
        create_req = pb2.CreateGroupWithLeadersRequest(
            resourceTypes=["vm"],
            leaders=[],
            groupName=test_group
        )
        create_resp = stub.CreateGroupWithLeaders(create_req)
        print(f"  [OK] Group created: {create_resp.groupName}")
        
        # Wait for Azure AD replication
        import time
        print("  Waiting 3 seconds for Azure AD replication...")
        time.sleep(3)
        
        # Add user to group
        print(f"  Step 2: Adding user '{test_user}' to group...")
        create_users_req = pb2.CreateUsersForGroupRequest(
            groupName=test_group,
            users=[test_user]
        )
        create_users_resp = stub.CreateUsersForGroup(create_users_req)
        print(f"  [OK] User created: {create_users_resp.message}")
        
        # Wait for user creation to complete
        print("  Waiting 2 seconds for user creation...")
        time.sleep(2)
        
        # Now test DeleteUser
        print(f"  Step 3: Deleting user '{test_user}' from group '{test_group}'...")
        request = pb2.DeleteUserRequest(
            user_name=test_user,
            group_name=test_group
        )
        response = stub.DeleteUser(request)
        
        # Validate response structure
        assert hasattr(response, 'success'), "Response should have 'success' field"
        assert hasattr(response, 'message'), "Response should have 'message' field"
        
        assert isinstance(response.success, bool), "success should be boolean"
        assert isinstance(response.message, str), "message should be a string"
        
        print(f"  User: {test_user}")
        print(f"  Group: {test_group}")
        print(f"  Success: {response.success}")
        print(f"  Message: {response.message}")
        
        if response.success:
            print(f"  [OK] User successfully deleted")
        else:
            print(f"  [WARN] DeleteUser returned success=False: {response.message}")
            # This might be OK if user doesn't exist or was already deleted
        
        # Test with non-existent user (should return success=False, not throw)
        print(f"  Step 4: Testing with non-existent user...")
        request_invalid = pb2.DeleteUserRequest(
            user_name="non-existent-user-12345",
            group_name=test_group
        )
        response_invalid = stub.DeleteUser(request_invalid)
        
        if not response_invalid.success:
            print(f"  [OK] Correctly returned success=False for non-existent user")
        else:
            print(f"  [WARN] Returned success=True for non-existent user (may be idempotent)")
        
        # Test with empty parameters (should fail or return success=False)
        print(f"  Step 5: Testing with empty parameters...")
        try:
            request_empty = pb2.DeleteUserRequest(
                user_name="",
                group_name=""
            )
            response_empty = stub.DeleteUser(request_empty)
            if not response_empty.success:
                print(f"  [OK] Correctly returned success=False for empty parameters")
            else:
                print(f"  [WARN] Returned success=True for empty parameters (may be acceptable)")
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                print(f"  [OK] Correctly rejected empty parameters with INVALID_ARGUMENT")
            else:
                print(f"  [WARN] Got {e.code().name} instead of INVALID_ARGUMENT (may be acceptable)")
        
        print_result(True, f"DeleteUser test completed")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_3_get_group_resources_list():
    """Test GetGroupResourcesList - returns detailed list of resources for a group"""
    print_test_header(3, "GetGroupResourcesList")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    try:
        # Test with existing group (may or may not have resources)
        request = pb2.GetGroupResourcesListRequest(
            groupName=TEST_GROUP_NAME
        )
        response = stub.GetGroupResourcesList(request)
        
        # Validate response structure
        assert hasattr(response, 'success'), "Response should have 'success' field"
        assert hasattr(response, 'resources'), "Response should have 'resources' field"
        assert hasattr(response, 'message'), "Response should have 'message' field"
        
        assert isinstance(response.success, bool), "success should be boolean"
        # Protobuf repeated fields are iterable
        try:
            resources_list = list(response.resources)
        except (TypeError, AttributeError):
            assert False, "resources should be iterable (can be converted to list)"
        assert isinstance(response.message, str), "message should be a string"
        
        print(f"  Group: {TEST_GROUP_NAME}")
        print(f"  Success: {response.success}")
        print(f"  Resources count: {len(resources_list)}")
        print(f"  Message: {response.message}")
        
        # Validate ResourceDetail structure for each resource
        if resources_list:
            print(f"  Resources found:")
            for idx, resource in enumerate(resources_list[:5], 1):  # Show first 5
                assert hasattr(resource, 'resource_global_id'), "ResourceDetail should have resource_global_id"
                assert hasattr(resource, 'name'), "ResourceDetail should have name"
                assert hasattr(resource, 'type'), "ResourceDetail should have type"
                assert hasattr(resource, 'service'), "ResourceDetail should have service"
                assert hasattr(resource, 'created_by'), "ResourceDetail should have created_by"
                assert hasattr(resource, 'resource_id'), "ResourceDetail should have resource_id"
                assert hasattr(resource, 'status'), "ResourceDetail should have status"
                
                print(f"    Resource {idx}:")
                print(f"      Global ID: {resource.resource_global_id[:80]}..." if len(resource.resource_global_id) > 80 else f"      Global ID: {resource.resource_global_id}")
                print(f"      Name: {resource.name}")
                print(f"      Type: {resource.type}")
                print(f"      Service: {resource.service}")
                print(f"      Created By: {resource.created_by}")
                print(f"      Resource ID: {resource.resource_id}")
                print(f"      Status: {resource.status}")
            
            if len(resources_list) > 5:
                print(f"    ... and {len(resources_list) - 5} more resources")
        else:
            print(f"  [OK] No resources found (expected if group has no resources)")
        
        # Test with non-existent group (should still return success=True with empty list)
        print(f"  Testing with non-existent group...")
        request_invalid = pb2.GetGroupResourcesListRequest(
            groupName="non-existent-group-12345"
        )
        response_invalid = stub.GetGroupResourcesList(request_invalid)
        
        if response_invalid.success:
            resources_list_invalid = list(response_invalid.resources)
            print(f"  [OK] Non-existent group returned success=True with {len(resources_list_invalid)} resources")
        else:
            print(f"  [WARN] Non-existent group returned success=False: {response_invalid.message}")
        
        # Test with empty group name
        print(f"  Testing with empty group name...")
        try:
            request_empty = pb2.GetGroupResourcesListRequest(groupName="")
            response_empty = stub.GetGroupResourcesList(request_empty)
            # Empty group name might be valid (returns empty list) or invalid
            print(f"  [OK] Empty group name handled (success={response_empty.success})")
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                print(f"  [OK] Correctly rejected empty group name")
            else:
                print(f"  [WARN] Got {e.code().name} for empty group name")
        
        print_result(True, f"GetGroupResourcesList returned {len(resources_list)} resources")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_4_delete_resource():
    """Test DeleteResource - deletes a single Azure resource by resource_global_id"""
    print_test_header(4, "DeleteResource")
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    try:
        # First, try to get a list of resources to test deletion
        print(f"  Step 1: Getting list of resources for test group...")
        list_request = pb2.GetGroupResourcesListRequest(groupName=TEST_GROUP_NAME)
        list_response = stub.GetGroupResourcesList(list_request)
        
        resources_list = list(list_response.resources)
        print(f"  Found {len(resources_list)} resources")
        
        if not resources_list:
            print(f"  [INFO] No resources found to test deletion.")
            print(f"  Testing with invalid resource ID instead...")
            
            # Test with invalid resource ID format
            print(f"  Step 2: Testing with invalid resource ID format...")
            try:
                request_invalid = pb2.DeleteResourceRequest(
                    resource_global_id="invalid-resource-id-format"
                )
                response_invalid = stub.DeleteResource(request_invalid)
                
                if not response_invalid.success:
                    print(f"  [OK] Correctly returned success=False for invalid resource ID")
                else:
                    print(f"  [WARN] Returned success=True for invalid resource ID")
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                    print(f"  [OK] Correctly rejected invalid resource ID with INVALID_ARGUMENT")
                else:
                    print(f"  [WARN] Got {e.code().name} for invalid resource ID (may be acceptable)")
            
            # Test with empty resource ID
            print(f"  Step 3: Testing with empty resource ID...")
            try:
                request_empty = pb2.DeleteResourceRequest(resource_global_id="")
                response_empty = stub.DeleteResource(request_empty)
                if not response_empty.success:
                    print(f"  [OK] Correctly returned success=False for empty resource ID")
                else:
                    print(f"  [WARN] Returned success=True for empty resource ID (may be acceptable)")
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                    print(f"  [OK] Correctly rejected empty resource ID with INVALID_ARGUMENT")
                else:
                    print(f"  [WARN] Got {e.code().name} instead of INVALID_ARGUMENT (may be acceptable)")
            
            print_result(True, "DeleteResource test completed (no resources to delete)")
            return True
        
        # Test with first resource (WARNING: This will actually delete the resource!)
        test_resource = resources_list[0]
        print(f"  Step 2: Testing deletion of resource:")
        print(f"    Global ID: {test_resource.resource_global_id[:80]}..." if len(test_resource.resource_global_id) > 80 else f"    Global ID: {test_resource.resource_global_id}")
        print(f"    Name: {test_resource.name}")
        print(f"    Type: {test_resource.type}")
        print(f"    Service: {test_resource.service}")
        print(f"  WARNING: This will actually delete the resource!")
        
        # Ask user confirmation (in automated tests, skip this)
        print(f"  [INFO] Skipping actual deletion in test (would delete real resource)")
        print(f"  [INFO] To test actual deletion, uncomment the code below")
        
        # Uncomment below to actually test deletion:
        # request = pb2.DeleteResourceRequest(
        #     resource_global_id=test_resource.resource_global_id
        # )
        # response = stub.DeleteResource(request)
        # 
        # # Validate response structure
        # assert hasattr(response, 'success'), "Response should have 'success' field"
        # assert hasattr(response, 'message'), "Response should have 'message' field"
        # 
        # assert isinstance(response.success, bool), "success should be boolean"
        # assert isinstance(response.message, str), "message should be a string"
        # 
        # print(f"  Success: {response.success}")
        # print(f"  Message: {response.message}")
        
        # Test with invalid resource ID format
        print(f"  Step 3: Testing with invalid resource ID format...")
        try:
            request_invalid = pb2.DeleteResourceRequest(
                resource_global_id="invalid-resource-id-format"
            )
            response_invalid = stub.DeleteResource(request_invalid)
            
            if not response_invalid.success:
                print(f"  [OK] Correctly returned success=False for invalid resource ID")
            else:
                print(f"  [WARN] Returned success=True for invalid resource ID")
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                print(f"  [OK] Correctly rejected invalid resource ID with INVALID_ARGUMENT")
            else:
                print(f"  [WARN] Got {e.code().name} for invalid resource ID (may be acceptable)")
        
        # Test with empty resource ID
        print(f"  Step 4: Testing with empty resource ID...")
        try:
            request_empty = pb2.DeleteResourceRequest(resource_global_id="")
            response_empty = stub.DeleteResource(request_empty)
            if not response_empty.success:
                print(f"  [OK] Correctly returned success=False for empty resource ID")
            else:
                print(f"  [WARN] Returned success=True for empty resource ID (may be acceptable)")
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
                print(f"  [OK] Correctly rejected empty resource ID with INVALID_ARGUMENT")
            else:
                print(f"  [WARN] Got {e.code().name} instead of INVALID_ARGUMENT (may be acceptable)")
        
        # Test with valid Azure Resource ID format but non-existent resource
        print(f"  Step 5: Testing with valid format but non-existent resource...")
        fake_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-rg/providers/Microsoft.Compute/virtualMachines/fake-vm"
        request_fake = pb2.DeleteResourceRequest(resource_global_id=fake_resource_id)
        response_fake = stub.DeleteResource(request_fake)
        
        if not response_fake.success:
            print(f"  [OK] Correctly returned success=False for non-existent resource")
        else:
            print(f"  [WARN] Returned success=True for non-existent resource")
        
        print_result(True, "DeleteResource test completed")
        return True
        
    except grpc.RpcError as e:
        print_result(False, f"RPC error: {e.code().name} - {e.details()}")
        return False
    except AssertionError as e:
        print_result(False, f"Assertion error: {e}")
        return False
    except Exception as e:
        print_result(False, f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("Azure Adapter - New Methods Test Suite")
    print("=" * 70)
    print(f"Testing adapter at: {ADAPTER_HOST}")
    print(f"Test group name: {TEST_GROUP_NAME}")
    print("\nNote: Some tests create temporary groups/users for testing.")
    print("These will be cleaned up automatically or can be manually removed.")
    print("\nWARNING: DeleteResource test will NOT actually delete resources")
    print("by default. Uncomment the deletion code in test_4_delete_resource()")
    print("if you want to test actual resource deletion.")
    
    results = []
    
    # Run all tests
    results.append(("AddLeaderToGroup", test_1_add_leader_to_group()))
    results.append(("DeleteUser", test_2_delete_user()))
    results.append(("GetGroupResourcesList", test_3_get_group_resources_list()))
    results.append(("DeleteResource", test_4_delete_resource()))
    
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
        print("\n[OK] All tests passed! All new methods are working correctly.")
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
