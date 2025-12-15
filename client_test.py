# client_test.py
import grpc
from datetime import datetime

from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc


def main() -> None:
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)

    # Use unique group name with timestamp to avoid conflicts
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    group_name = f"uc-test-{timestamp}"
    leaders = [f"uc.lead1.{timestamp}", f"uc.lead2.{timestamp}"]
    users = [f"uc.student1.{timestamp}", f"uc.student2.{timestamp}"]

    # 1) Prosty healthcheck: GetStatus
    print("== GetStatus ==")
    try:
        status_resp = stub.GetStatus(pb2.StatusRequest())
        print(f"  isHealthy = {status_resp.isHealthy}")
    except grpc.RpcError as e:
        print(f"  GetStatus RPC error: code={e.code().name}, details={e.details()}")

    # 2) Tworzenie grupy + liderów
    print("\n== CreateGroupWithLeaders ==")
    print(f"  Group: {group_name}")
    print(f"  Leaders: {leaders}")
    try:
        create_group_req = pb2.CreateGroupWithLeadersRequest(
            resourceType="vm",   # backend i tak tego używa głównie jako stringa
            leaders=leaders,
            groupName=group_name,
        )
        create_group_resp = stub.CreateGroupWithLeaders(create_group_req)
        print(f"  Response: groupName={create_group_resp.groupName}")
        print("  ✓ Group created successfully")
    except grpc.RpcError as e:
        error_msg = str(e.details())
        if "already exists" in error_msg or "ObjectConflict" in error_msg:
            print(f"  ⚠ Warning: User may already exist: {error_msg}")
            print("  Continuing with other tests...")
        else:
            print(
                f"  ✗ CreateGroupWithLeaders RPC error: "
                f"code={e.code().name}, details={e.details()}"
            )
            # Jeśli to się wywali, dalsze testy i tak nie mają sensu
            return

    # 3) Sprawdzenie, czy grupa istnieje
    print("\n== GroupExists ==")
    try:
        exists_req = pb2.GroupExistsRequest(groupName=group_name)
        exists_resp = stub.GroupExists(exists_req)
        print(f"  GroupExists({group_name!r}) -> {exists_resp.exists}")
        if exists_resp.exists:
            print("  ✓ Group exists")
        else:
            print("  ⚠ Group not found (may need time to replicate)")
    except grpc.RpcError as e:
        print(f"  ✗ GroupExists RPC error: code={e.code().name}, details={e.details()}")

    # 4) Dodanie studentów do istniejącej grupy
    print("\n== CreateUsersForGroup ==")
    print(f"  Users: {users}")
    try:
        create_users_req = pb2.CreateUsersForGroupRequest(
            groupName=group_name,
            users=users,
        )
        create_users_resp = stub.CreateUsersForGroup(create_users_req)
        print(f"  Response: {create_users_resp.message}")
        print("  ✓ Users created successfully")
    except grpc.RpcError as e:
        error_msg = str(e.details())
        if "already exists" in error_msg or "ObjectConflict" in error_msg:
            print(f"  ⚠ Warning: Users may already exist: {error_msg}")
        else:
            print(
                f"  ✗ CreateUsersForGroup RPC error: "
                f"code={e.code().name}, details={e.details()}"
            )
    
    # 5) Test GetAvailableServices
    print("\n== GetAvailableServices ==")
    try:
        services_resp = stub.GetAvailableServices(pb2.GetAvailableServicesRequest())
        print(f"  Available services: {list(services_resp.services)}")
        print(f"  Count: {len(services_resp.services)}")
    except grpc.RpcError as e:
        print(f"  ✗ GetAvailableServices RPC error: code={e.code().name}, details={e.details()}")
    
    # 6) Test GetResourceCount
    print("\n== GetResourceCount ==")
    try:
        count_req = pb2.ResourceCountRequest(groupName=group_name, resourceType="vm")
        count_resp = stub.GetResourceCount(count_req)
        print(f"  Resource count (vm): {count_resp.count}")
    except grpc.RpcError as e:
        print(f"  ✗ GetResourceCount RPC error: code={e.code().name}, details={e.details()}")
    
    print("\n== Test Summary ==")
    print("  Note: If you see 'already exists' warnings, users/groups from previous tests")
    print("  may still exist in Azure AD. This is normal and doesn't indicate a problem.")


if __name__ == "__main__":
    main()
