# manual_identity_smoketest.py
"""
Ręczny smoke test dla identity.user_manager i identity.group_manager.

UWAGA: to faktycznie stworzy użytkownika i grupę w Entra ID,
więc używaj jakichś testowych nazw i po wszystkim sprawdź w portalu.
"""

from config.settings import validate_config
from identity.user_manager import AzureUserManager
from identity.group_manager import AzureGroupManager


def main():
    validate_config()

    user_mgr = AzureUserManager()
    group_mgr = AzureGroupManager()

    TEST_GROUP_NAME = "uc-test-group"
    TEST_LOGIN = "uc.test.user"   # zrobi się uc.test.user@<twoj_UDOMAIN>

    print(f"[+] Tworzę grupę: {TEST_GROUP_NAME!r}")
    group_id = group_mgr.create_group(TEST_GROUP_NAME, description="UC adapter smoke test")
    print(f"    -> group_id = {group_id}")

    print(f"[+] Tworzę użytkownika: {TEST_LOGIN!r}")
    user_id = user_mgr.create_user(
        login=TEST_LOGIN,
        display_name="UC Test User",
        initial_password="Un1Cloud!Test123",  # tymczasowe hasło
    )
    print(f"    -> user_id = {user_id}")

    print(f"[+] Dodaję użytkownika do grupy...")
    group_mgr.add_member(group_id, user_id)
    print("    -> OK")

    print(f"[+] Pobieram listę członków grupy...")
    members = group_mgr.list_members(group_id)
    print(f"    -> {len(members)} członków:")
    for m in members:
        print("       -", m.get("id"), m.get("userPrincipalName") or m.get("displayName"))

    print("[+] Usuwam członka z grupy...")
    group_mgr.remove_member(group_id, user_id)
    print("    -> OK (albo 404, jeśli Graph uzna że już go nie było)")

    print("[+] Usuwam użytkownika...")
    user_mgr.delete_user(TEST_LOGIN)
    print("    -> OK (albo 404)")

    print("[+] Usuwam grupę...")
    group_mgr.delete_group(group_id)
    print("    -> OK (albo 404)")

    print("\n[SMOKE TEST] Zakończono bez wyjątków.")


if __name__ == "__main__":
    main()
