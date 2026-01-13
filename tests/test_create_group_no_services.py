# test_create_group_no_services.py
"""
Test: CreateGroupWithLeaders bez resourceTypes (pusta lista usług)
Sprawdza czy grupa jest tworzona w Azure AD nawet gdy nie ma przypisanych usług.
"""

import sys
import os
import time

# Add parent directory to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import grpc
from datetime import datetime
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc

ADAPTER_HOST = "localhost:50053"


def test_create_group_without_services():
    """Test tworzenia grupy bez przypisanych usług"""
    print("\n" + "=" * 70)
    print("Test: CreateGroupWithLeaders bez resourceTypes")
    print("=" * 70)
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    test_group = f"test-group-no-services-{timestamp}"
    test_leader = f"test-leader-{timestamp}"
    
    try:
        # Step 1: Create group without resourceTypes
        print(f"\nStep 1: Tworzenie grupy '{test_group}' bez usług (pusta lista resourceTypes)...")
        req = pb2.CreateGroupWithLeadersRequest(
            resourceTypes=[],  # Pusta lista!
            leaders=[test_leader],
            groupName=test_group
        )
        resp = stub.CreateGroupWithLeaders(req)
        print(f"  [OK] Group created: {resp.groupName}")
        
        # Step 2: Verify group exists
        print(f"\nStep 2: Sprawdzanie czy grupa istnieje w Azure AD...")
        exists_req = pb2.GroupExistsRequest(groupName=test_group)
        exists_resp = stub.GroupExists(exists_req)
        
        if exists_resp.exists:
            print(f"  [OK] Group exists: True")
        else:
            print(f"  [FAIL] Group exists: False - grupa nie została utworzona!")
            return False
        
        # Step 3: Verify leader user was created
        print(f"\nStep 3: Sprawdzanie czy lider został utworzony...")
        time.sleep(3)  # Wait for Azure AD replication
        
        from identity.user_manager import AzureUserManager
        from identity.utils import build_username_with_group_suffix
        
        um = AzureUserManager()
        username = build_username_with_group_suffix(test_leader, test_group)
        user = um.get_user(username)
        
        if user:
            upn = user.get("userPrincipalName", "N/A")
            print(f"  [OK] Leader user exists: {upn}")
        else:
            print(f"  [WARN] Leader user not found yet (may need more replication time)")
            print(f"         Expected username: {username}")
        
        print("\n" + "=" * 70)
        print("[SUKCES] Test przeszedl - grupa zostala utworzona bez uslug!")
        print("=" * 70)
        return True
        
    except grpc.RpcError as e:
        print(f"\n[FAIL] RPC error: {e.code()} - {e.details()}")
        return False
    except Exception as e:
        print(f"\n[FAIL] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_create_group_without_services()
    sys.exit(0 if success else 1)
