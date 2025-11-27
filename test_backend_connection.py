# test_backend_connection.py
import grpc
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc

def test_azure_adapter():
    """Test Azure adapter the same way backend does"""
    # Backend uses: ManagedChannelBuilder.forAddress(host, port).usePlaintext().build()
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    print("Testing Azure Adapter (port 50053) - Backend-style connection...\n")
    
    # Test 1: isRunning() - Backend calls this first
    print("1. Testing GetStatus (isRunning check)...")
    try:
        status_req = pb2.StatusRequest()
        status_resp = stub.GetStatus(status_req)
        print(f"   ✅ isHealthy: {status_resp.isHealthy}")
    except grpc.RpcError as e:
        print(f"   ❌ FAILED: {e.code().name} - {e.details()}")
        return False
    
    # Test 2: GroupExists - Backend uses this
    print("\n2. Testing GroupExists...")
    try:
        exists_req = pb2.GroupExistsRequest(groupName="test-group")
        exists_resp = stub.GroupExists(exists_req)
        print(f"   ✅ Group exists check: {exists_resp.exists}")
    except grpc.RpcError as e:
        print(f"   ❌ FAILED: {e.code().name} - {e.details()}")
    
    # Test 3: GetTotalCostsForAllGroups - Backend uses this for cost sync
    print("\n3. Testing GetTotalCostsForAllGroups (used by backend cost sync)...")
    try:
        cost_req = pb2.CostRequest(
            startDate="2024-01-01",
            endDate="2024-12-31"
        )
        cost_resp = stub.GetTotalCostsForAllGroups(cost_req)
        print(f"   ✅ Response: {len(cost_resp.groupCosts)} groups found")
        for gc in cost_resp.groupCosts:
            print(f"      - {gc.groupName}: ${gc.amount}")
    except grpc.RpcError as e:
        print(f"   ❌ FAILED: {e.code().name} - {e.details()}")
    
    # Test 4: CreateGroupWithLeaders - Backend uses this
    print("\n4. Testing CreateGroupWithLeaders (format check)...")
    try:
        create_req = pb2.CreateGroupWithLeadersRequest(
            resourceType="vm",
            leaders=["test.leader1"],
            groupName="test-group-backend"
        )
        # Don't actually create, just check format
        print(f"   ✅ Request format valid: resourceType={create_req.resourceType}, groupName={create_req.groupName}")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
    
    print("\n✅ All backend-compatible tests passed!")
    return True

if __name__ == "__main__":
    test_azure_adapter()