# tests/test_teardown_users.py

"""
Test teardown flow - sprawdza czy usunięcie grupy usuwa użytkowników w tej grupie.
"""

import sys
import os
import time
from datetime import datetime

# Add parent directory to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import grpc
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc


def test_teardown_removes_users():
    """Test że RemoveGroup usuwa użytkowników w grupie."""
    print("\n" + "=" * 60)
    print("Test: Teardown removes users from group")
    print("=" * 60)
    
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    test_group = f"test-teardown-{timestamp}"
    test_users = [
        f"test.user1.{timestamp}",
        f"test.user2.{timestamp}",
    ]
    
    print(f"\n1. Creating group: {test_group}")
    print(f"   Users to add: {test_users}")
    
    try:
        # Utwórz grupę
        create_req = pb2.CreateGroupWithLeadersRequest(
            resourceTypes=["network"],
            leaders=[f"test.lead.{timestamp}"],
            groupName=test_group,
        )
        create_resp = stub.CreateGroupWithLeaders(create_req)
        print(f"   [OK] Group created: {create_resp.groupName}")
        
        # Czekaj na replikację
        print("\n2. Waiting 5 seconds for Azure AD replication...")
        time.sleep(5)
        
        # Dodaj użytkowników do grupy
        print(f"\n3. Adding users to group: {test_users}")
        create_users_req = pb2.CreateUsersForGroupRequest(
            groupName=test_group,
            users=test_users,
        )
        create_users_resp = stub.CreateUsersForGroup(create_users_req)
        print(f"   [OK] Users added: {create_users_resp.message}")
        
        # Czekaj na replikację - dłużej dla Azure AD
        print("\n4. Waiting 10 seconds for user creation and group membership to replicate...")
        time.sleep(10)
        
        # Sprawdź czy użytkownicy istnieją (przez GroupExists i próbę pobrania)
        print("\n5. Verifying users exist (before teardown)...")
        from identity.user_manager import AzureUserManager
        from azure_clients import get_graph_client
        user_mgr = AzureUserManager(get_graph_client())
        
        users_exist_before = []
        for user in test_users:
            # Użytkownicy mają suffix grupy w formacie: {user}-{normalized_group}
            from identity.utils import build_username_with_group_suffix
            user_with_suffix = build_username_with_group_suffix(user, test_group)
            # UPN będzie: {user_with_suffix}@{AZURE_UDOMAIN}
            from config.settings import AZURE_UDOMAIN
            user_upn = f"{user_with_suffix}@{AZURE_UDOMAIN}"
            user_data = user_mgr.get_user(user_upn)
            if user_data:
                users_exist_before.append(user_upn)
                print(f"   [OK] User exists: {user_upn} (id: {user_data.get('id', 'N/A')})")
            else:
                print(f"   [WARN] User not found: {user_upn}")
        
        if not users_exist_before:
            print("   [WARN] No users found - they may not have been created yet")
            print("   Continuing with teardown test anyway...")
        
        # Teraz usuń grupę
        print(f"\n6. Removing group: {test_group}")
        print("   Expected: Group removed, users removed, role assignments removed")
        remove_req = pb2.RemoveGroupRequest(groupName=test_group)
        remove_resp = stub.RemoveGroup(remove_req)
        
        print(f"   Response: success={remove_resp.success}")
        print(f"   Message: {remove_resp.message}")
        print(f"   Removed users: {list(remove_resp.removedUsers)}")
        
        if not remove_resp.success:
            print("   [FAIL] RemoveGroup returned success=False")
            return False
        
        # Czekaj na propagację usunięcia - Azure AD może potrzebować więcej czasu
        print("\n7. Waiting 10 seconds for deletion to propagate...")
        time.sleep(10)
        
        # Sprawdź czy użytkownicy zostali usunięci
        print("\n8. Verifying users are deleted (after teardown)...")
        users_still_exist = []
        for user in test_users:
            from identity.utils import build_username_with_group_suffix
            user_with_suffix = build_username_with_group_suffix(user, test_group)
            from config.settings import AZURE_UDOMAIN
            user_upn = f"{user_with_suffix}@{AZURE_UDOMAIN}"
            user_data = user_mgr.get_user(user_upn)
            if user_data:
                users_still_exist.append(user_upn)
                print(f"   [FAIL] User still exists: {user_upn} (id: {user_data.get('id', 'N/A')})")
            else:
                print(f"   [OK] User deleted: {user_upn}")
        
        # Sprawdź czy grupa została usunięta
        print("\n9. Verifying group is deleted...")
        exists_req = pb2.GroupExistsRequest(groupName=test_group)
        exists_resp = stub.GroupExists(exists_req)
        if exists_resp.exists:
            print(f"   [FAIL] Group still exists: {test_group}")
            return False
        else:
            print(f"   [OK] Group deleted: {test_group}")
        
        # Podsumowanie
        print("\n" + "=" * 60)
        if users_still_exist:
            print("TEST FAILED: Some users still exist after teardown:")
            for user in users_still_exist:
                print(f"  - {user}")
            return False
        else:
            print("TEST PASSED: All users and group were successfully removed")
            print("=" * 60)
            return True
            
    except grpc.RpcError as e:
        print(f"\n[ERROR] gRPC error: code={e.code().name}, details={e.details()}")
        return False
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}", exc_info=True)
        return False


def main():
    """Uruchom test teardown."""
    try:
        success = test_teardown_removes_users()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\nTest crashed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
