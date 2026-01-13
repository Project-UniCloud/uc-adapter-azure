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
    """Test walidacji - CreateGroupWithLeaders powinien zwracać błąd gdy resourceTypes jest puste (jak AWS)"""
    print("\n" + "=" * 70)
    print("Test: CreateGroupWithLeaders bez resourceTypes (walidacja)")
    print("=" * 70)
    
    channel = grpc.insecure_channel(ADAPTER_HOST)
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    test_group = f"test-group-no-services-{timestamp}"
    test_leader = f"test-leader-{timestamp}"
    
    try:
        # Step 1: Try to create group without resourceTypes - should fail
        print(f"\nStep 1: Próba utworzenia grupy '{test_group}' bez usług (pusta lista resourceTypes)...")
        req = pb2.CreateGroupWithLeadersRequest(
            resourceTypes=[],  # Pusta lista!
            leaders=[test_leader],
            groupName=test_group
        )
        resp = stub.CreateGroupWithLeaders(req)
        print(f"  [FAIL] Group was created unexpectedly: {resp.groupName}")
        print(f"  Expected: INVALID_ARGUMENT error")
        return False
        
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
            print(f"  [OK] Correctly rejected with INVALID_ARGUMENT")
            print(f"  Error message: {e.details()}")
            
            # Step 2: Verify group was NOT created
            print(f"\nStep 2: Sprawdzanie czy grupa NIE została utworzona...")
            exists_req = pb2.GroupExistsRequest(groupName=test_group)
            exists_resp = stub.GroupExists(exists_req)
            
            if not exists_resp.exists:
                print(f"  [OK] Group does not exist (correct - validation prevented creation)")
            else:
                print(f"  [FAIL] Group exists: True - grupa została utworzona mimo błędu!")
                return False
            
            print("\n" + "=" * 70)
            print("[SUKCES] Test przeszedl - walidacja dziala poprawnie (jak AWS)!")
            print("=" * 70)
            return True
        else:
            print(f"  [FAIL] Wrong error code: {e.code()} (expected INVALID_ARGUMENT)")
            print(f"  Error details: {e.details()}")
            return False
    except Exception as e:
        print(f"\n[FAIL] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_create_group_without_services()
    sys.exit(0 if success else 1)
