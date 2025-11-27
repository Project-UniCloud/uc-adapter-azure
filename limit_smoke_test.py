# limit_smoke_test.py
"""
Ręczny smoke test dla cost_monitoring.limit_manager.
-odczytuje liczby użytkowników i VM-ek oraz testuje rzucanie LimitExceededError.
"""

from config.settings import validate_config
from cost_monitoring.limit_manager import LimitManager, LimitExceededError


def main() -> None:
    validate_config()

    lm = LimitManager()

    # ===== UŻYTKOWNICY =====
    print("[+] Liczę użytkowników w Entra ID...")
    user_count = lm.count_users()
    print(f"    -> {user_count} użytkowników")

    print("[+] Test ensure_user_limit przy wysokim limicie (powinno być OK)...")
    lm.ensure_user_limit(user_count + 100)
    print(f"    -> OK (max_users = {user_count + 100})")

    print("[+] Test ensure_user_limit przy limicie równym aktualnej liczbie (powinien rzucić)...")
    try:
        lm.ensure_user_limit(user_count)
    except LimitExceededError as e:
        print(f"    -> LimitExceededError OK: {e}")
    else:
        print("    -> UWAGA: LimitExceededError NIE został rzucony (nieoczekiwane)")

    # ===== VM =====
    print("\n[+] Liczę VM-ki w całej subskrypcji...")
    vm_count = lm.count_vms()
    print(f"    -> {vm_count} VM-ek")

    print("[+] Test ensure_vm_limit przy wysokim limicie (powinno być OK)...")
    lm.ensure_vm_limit(vm_count + 100)
    print(f"    -> OK (max_vms = {vm_count + 100})")

    print("[+] Test ensure_vm_limit przy limicie równym aktualnej liczbie (powinien rzucić)...")
    try:
        lm.ensure_vm_limit(vm_count)
    except LimitExceededError as e:
        print(f"    -> LimitExceededError OK: {e}")
    else:
        print("    -> UWAGA: LimitExceededError NIE został rzucony (nieoczekiwane)")

    print("\n[LIMIT SMOKE TEST] Zakończono.")


if __name__ == "__main__":
    main()
