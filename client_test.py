# client_test.py
import grpc
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc

def main():
    channel = grpc.insecure_channel("localhost:50051")
    stub = pb2_grpc.CloudAdapterStub(channel)

    # przykładowe RPC – dopasuj do tego, co masz w .proto
    req = pb2.CreateGroupWithLeadersRequest(
        groupName="uc-thesis-demo",
        leaders=["uc.lead1", "uc.lead2"],
    )
    resp = stub.CreateGroupWithLeaders(req)
    print("Response:", resp)

if __name__ == "__main__":
    main()
