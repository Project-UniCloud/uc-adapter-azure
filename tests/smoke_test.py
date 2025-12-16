# manual_identity_smoketest.py
"""
Ręczny smoke test dla identity.user_manager i identity.group_manager.

"""

import sys
import os

# Add parent directory to path to import modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import time

from config.settings import validate_config
from identity.user_manager import AzureUserManager
from identity.group_manager import AzureGroupManager


def main() -> None:
    # 1. Walidacja konfiguracji (.env / settings.py)
    validate_config()

    user_mgr = AzureUserManager()
    group_mgr = AzureGroupManager()

    TEST_GROUP_NAME = "uc-test-group7"
    TEST_LOGIN = "uc.test.user7"  # wynik uc.test.user5@<twoj_UDOMAIN>

    # 2. Tworzenie grupy
    print(f"[+] Tworzę grupę: {TEST_GROUP_NAME!r}")
    group_id = group_mgr.create_group(
        TEST_GROUP_NAME,
        description="UC adapter smoke test",
    )
    print(f"    -> group_id = {group_id}")

    # 3. Tworzenie użytkownika
    print(f"[+] Tworzę użytkownika: {TEST_LOGIN!r}")
    user_id = user_mgr.create_user(
        login=TEST_LOGIN,
        display_name="UC Test User",
        initial_password="Un1Cloud!Test123",  # tymczasowe hasło
    )
    print(f"    -> user_id = {user_id}")

    # 4. Krótkie oczekiwanie na replikację katalogu
    print("[+] Czekam chwilę, aż katalog się zreplikuje (10s)...")
    time.sleep(10)

    # 5. Dodanie użytkownika do grupy (z retry w środku add_member)
    print("[+] Dodaję użytkownika do grupy...")
    group_mgr.add_member(group_id, user_id)
    print("    -> OK")

    # 6. Pobieranie listy członków z prostym pollingiem
    print("[+] Pobieram listę członków grupy (z oczekiwaniem)...")

    max_wait = 30  # maksymalny czas oczekiwania w sekundach
    step = 5       # odstęp między kolejnymi próbami
    elapsed = 0
    members = []

    while True:
        members = group_mgr.list_members(group_id)

        # Jeśli użytkownik jest już wśród członków – kończymy
        if any(m.get("id") == user_id for m in members):
            break

        if elapsed >= max_wait:
            print(
                f"    -> po {elapsed}s użytkownika nadal nie widać w members; "
                f"Graph może być opóźniony, ale add_member zakończył się bez błędu."
            )
            break

        print(f"    -> jeszcze brak członka w grupie, czekam {step}s...")
        time.sleep(step)
        elapsed += step

    print(f"    -> {len(members)} członków:")
    for m in members:
        print(
            "       -",
            m.get("id"),
            m.get("userPrincipalName") or m.get("displayName"),
        )

    # 7. Cleanup

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
