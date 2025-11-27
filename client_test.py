# client_test.py
import grpc

from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc


def main() -> None:
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)

    group_name = "uc-thesis-demo"
    leaders = ["uc.lead1", "uc.lead2"]
    users = ["uc.student1", "uc.student2"]

    # 1) Prosty healthcheck: GetStatus
    print("== GetStatus ==")
    try:
        status_resp = stub.GetStatus(pb2.StatusRequest())
        print(f"  isHealthy = {status_resp.isHealthy}")
    except grpc.RpcError as e:
        print(f"  GetStatus RPC error: code={e.code().name}, details={e.details()}")

    # 2) Tworzenie grupy + liderów
    print("\n== CreateGroupWithLeaders ==")
    try:
        create_group_req = pb2.CreateGroupWithLeadersRequest(
            resourceType="vm",   # backend i tak tego używa głównie jako stringa
            leaders=leaders,
            groupName=group_name,
        )
        create_group_resp = stub.CreateGroupWithLeaders(create_group_req)
        print(f"  Response: {create_group_resp}")
    except grpc.RpcError as e:
        print(
            f"  CreateGroupWithLeaders RPC error: "
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
    except grpc.RpcError as e:
        print(f"  GroupExists RPC error: code={e.code().name}, details={e.details()}")

    # 4) Dodanie studentów do istniejącej grupy
    print("\n== CreateUsersForGroup ==")
    try:
        create_users_req = pb2.CreateUsersForGroupRequest(
            groupName=group_name,
            users=users,
        )
        create_users_resp = stub.CreateUsersForGroup(create_users_req)
        print(f"  Response: {create_users_resp.message}")
    except grpc.RpcError as e:
        print(
            f"  CreateUsersForGroup RPC error: "
            f"code={e.code().name}, details={e.details()}"
        )


if __name__ == "__main__":
    main()
