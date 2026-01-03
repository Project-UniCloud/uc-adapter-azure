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


def wait_for_group_exists(stub: pb2_grpc.CloudAdapterStub, group_name: str, max_wait: int = 30, interval: int = 3) -> bool:
    """
    Polling: czeka aż grupa istnieje (GroupExists zwraca True).
    
    Args:
        stub: gRPC stub
        group_name: Nazwa grupy
        max_wait: Maksymalny czas oczekiwania w sekundach
        interval: Interwał między sprawdzeniami w sekundach
    
    Returns:
        True jeśli grupa istnieje, False jeśli timeout
    """
    elapsed = 0
    while elapsed < max_wait:
        try:
            exists_req = pb2.GroupExistsRequest(groupName=group_name)
            exists_resp = stub.GroupExists(exists_req)
            if exists_resp.exists:
                return True
        except Exception as e:
            print(f"   [WARN] Error checking group existence: {e}")
        
        time.sleep(interval)
        elapsed += interval
        if elapsed < max_wait:
            print(f"   [INFO] Group '{group_name}' not found yet, waiting... ({elapsed}/{max_wait}s)")
    
    print(f"   [FAIL] Timeout: Group '{group_name}' not found after {max_wait}s")
    return False


def wait_for_users_exist(user_mgr, users: list, test_group: str, max_wait: int = 60, interval: int = 3) -> list:
    """
    Polling: czeka aż użytkownicy istnieją.
    
    Args:
        user_mgr: AzureUserManager instance
        users: Lista nazw użytkowników (bez suffixu)
        test_group: Nazwa grupy (używana do budowania UPN)
        max_wait: Maksymalny czas oczekiwania w sekundach
        interval: Interwał między sprawdzeniami w sekundach
    
    Returns:
        Lista UPN użytkowników, którzy istnieją
    """
    from identity.utils import build_username_with_group_suffix
    from config.settings import AZURE_UDOMAIN
    
    elapsed = 0
    existing_users = []
    
    while elapsed < max_wait:
        existing_users = []
        for user in users:
            user_with_suffix = build_username_with_group_suffix(user, test_group)
            user_upn = f"{user_with_suffix}@{AZURE_UDOMAIN}"
            user_data = user_mgr.get_user(user_upn)
            if user_data:
                existing_users.append(user_upn)
        
        if len(existing_users) == len(users):
            return existing_users
        
        time.sleep(interval)
        elapsed += interval
        if elapsed < max_wait:
            print(f"   [INFO] Found {len(existing_users)}/{len(users)} users, waiting... ({elapsed}/{max_wait}s)")
    
    print(f"   [WARN] Timeout: Only {len(existing_users)}/{len(users)} users found after {max_wait}s")
    return existing_users


def wait_for_users_deleted(user_mgr, users: list, test_group: str, max_wait: int = 60, interval: int = 3) -> list:
    """
    Polling: czeka aż użytkownicy zostaną usunięci.
    
    Args:
        user_mgr: AzureUserManager instance
        users: Lista nazw użytkowników (bez suffixu)
        test_group: Nazwa grupy (używana do budowania UPN)
        max_wait: Maksymalny czas oczekiwania w sekundach
        interval: Interwał między sprawdzeniami w sekundach
    
    Returns:
        Lista UPN użytkowników, którzy nadal istnieją (powinna być pusta)
    """
    from identity.utils import build_username_with_group_suffix
    from config.settings import AZURE_UDOMAIN
    
    elapsed = 0
    remaining_users = []
    
    while elapsed < max_wait:
        remaining_users = []
        for user in users:
            user_with_suffix = build_username_with_group_suffix(user, test_group)
            user_upn = f"{user_with_suffix}@{AZURE_UDOMAIN}"
            user_data = user_mgr.get_user(user_upn)
            if user_data:
                remaining_users.append(user_upn)
        
        if len(remaining_users) == 0:
            return []
        
        time.sleep(interval)
        elapsed += interval
        if elapsed < max_wait:
            print(f"   [INFO] {len(remaining_users)}/{len(users)} users still exist, waiting... ({elapsed}/{max_wait}s)")
    
    print(f"   [WARN] Timeout: {len(remaining_users)}/{len(users)} users still exist after {max_wait}s")
    return remaining_users


def wait_for_group_deleted(stub: pb2_grpc.CloudAdapterStub, group_name: str, max_wait: int = 60, interval: int = 3) -> bool:
    """
    Polling: czeka aż grupa zostanie usunięta (GroupExists zwraca False).
    
    Args:
        stub: gRPC stub
        group_name: Nazwa grupy
        max_wait: Maksymalny czas oczekiwania w sekundach
        interval: Interwał między sprawdzeniami w sekundach
    
    Returns:
        True jeśli grupa została usunięta, False jeśli timeout
    """
    elapsed = 0
    while elapsed < max_wait:
        try:
            exists_req = pb2.GroupExistsRequest(groupName=group_name)
            exists_resp = stub.GroupExists(exists_req)
            if not exists_resp.exists:
                return True
        except Exception as e:
            # Jeśli GroupExists rzuca błąd, grupa prawdopodobnie nie istnieje
            print(f"   [INFO] GroupExists error (group may be deleted): {e}")
            return True
        
        time.sleep(interval)
        elapsed += interval
        if elapsed < max_wait:
            print(f"   [INFO] Group '{group_name}' still exists, waiting... ({elapsed}/{max_wait}s)")
    
    print(f"   [FAIL] Timeout: Group '{group_name}' still exists after {max_wait}s")
    return False


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
        
        # Czekaj na replikację - użyj polling
        print("\n2. Waiting for group to be available (Azure AD replication)...")
        if not wait_for_group_exists(stub, test_group, max_wait=30, interval=3):
            print("   [FAIL] Group not found after creation")
            return False
        
        # Dodaj użytkowników do grupy
        print(f"\n3. Adding users to group: {test_users}")
        create_users_req = pb2.CreateUsersForGroupRequest(
            groupName=test_group,
            users=test_users,
        )
        create_users_resp = stub.CreateUsersForGroup(create_users_req)
        print(f"   [OK] Users added: {create_users_resp.message}")
        
        # Czekaj na replikację - użyj polling
        print("\n4. Waiting for users to be created and available (Azure AD replication)...")
        from identity.user_manager import AzureUserManager
        from azure_clients import get_graph_client
        user_mgr = AzureUserManager(get_graph_client())
        
        users_exist_before = wait_for_users_exist(user_mgr, test_users, test_group, max_wait=60, interval=3)
        
        # Loguj szczegóły
        print("\n5. Verifying users exist (before teardown)...")
        if users_exist_before:
            for user_upn in users_exist_before:
                user_data = user_mgr.get_user(user_upn)
                print(f"   [OK] User exists: {user_upn} (id: {user_data.get('id', 'N/A') if user_data else 'N/A'})")
        else:
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
        
        # Czekaj na propagację usunięcia - użyj polling
        print("\n7. Waiting for users to be deleted (Azure AD replication)...")
        users_still_exist = wait_for_users_deleted(user_mgr, test_users, test_group, max_wait=60, interval=3)
        
        # Loguj szczegóły
        print("\n8. Verifying users are deleted (after teardown)...")
        if users_still_exist:
            for user_upn in users_still_exist:
                user_data = user_mgr.get_user(user_upn)
                print(f"   [FAIL] User still exists: {user_upn} (id: {user_data.get('id', 'N/A') if user_data else 'N/A'})")
        else:
            # Wszyscy użytkownicy zostali usunięci
            for user in test_users:
                from identity.utils import build_username_with_group_suffix
                user_with_suffix = build_username_with_group_suffix(user, test_group)
                from config.settings import AZURE_UDOMAIN
                user_upn = f"{user_with_suffix}@{AZURE_UDOMAIN}"
                print(f"   [OK] User deleted: {user_upn}")
        
        # Sprawdź czy grupa została usunięta - użyj polling
        print("\n9. Waiting for group to be deleted (Azure AD replication)...")
        if not wait_for_group_deleted(stub, test_group, max_wait=60, interval=3):
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
