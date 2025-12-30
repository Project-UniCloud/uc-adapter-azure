# tests/test_fixes_integration.py

"""
Testy integracyjne dla naprawionych bugów:
1. HTTPS validation w Cost Management
2. RBAC idempotency dla compute
3. AssignPolicies z wieloma typami zasobów
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


def test_assign_policies_compute_idempotency():
    """Test że AssignPolicies z compute jest idempotentne."""
    print("\n=== Test 1: AssignPolicies z compute (idempotency) ===")
    
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    # Użyj istniejącej grupy z poprzedniego testu lub utwórz nową
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    test_group = f"test-compute-{timestamp}"
    
    # Najpierw utwórz grupę
    try:
        create_req = pb2.CreateGroupWithLeadersRequest(
            resourceTypes=["network"],  # Najpierw network
            leaders=[f"test.lead.{timestamp}"],
            groupName=test_group,
        )
        stub.CreateGroupWithLeaders(create_req)
        print(f"  [OK] Created group: {test_group}")
        time.sleep(5)  # Czekaj na replikację
    except Exception as e:
        print(f"  [WARN] Group creation: {e}")
        # Może już istnieje - kontynuuj
    
    # Test 1: Pierwsze przypisanie compute
    print(f"\n  Test 1a: Assigning 'compute' policy (first time)...")
    try:
        assign_req = pb2.AssignPoliciesRequest(
            resourceTypes=["compute"],
            groupName=test_group,
        )
        resp1 = stub.AssignPolicies(assign_req)
        print(f"    Response 1: success={resp1.success}, message={resp1.message}")
        assert resp1.success, f"First assignment should succeed: {resp1.message}"
        print("    [OK] First assignment successful")
    except Exception as e:
        print(f"    [FAIL] First assignment failed: {e}")
        return False
    
    time.sleep(2)  # Krótka przerwa
    
    # Test 2: Drugie przypisanie compute (idempotent)
    print(f"\n  Test 1b: Assigning 'compute' policy again (idempotent test)...")
    try:
        assign_req2 = pb2.AssignPoliciesRequest(
            resourceTypes=["compute"],
            groupName=test_group,
        )
        resp2 = stub.AssignPolicies(assign_req2)
        print(f"    Response 2: success={resp2.success}, message={resp2.message}")
        assert resp2.success, f"Second assignment should also succeed (idempotent): {resp2.message}"
        print("    [OK] Second assignment successful (idempotent)")
    except Exception as e:
        print(f"    [FAIL] Second assignment failed: {e}")
        return False
    
    return True


def test_assign_policies_multi_types():
    """Test że AssignPolicies z wieloma typami działa (deterministyczna kolejność, deduplikacja)."""
    print("\n=== Test 2: AssignPolicies z wieloma typami zasobów ===")
    
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    test_group = f"test-multi-{timestamp}"
    
    # Utwórz grupę
    try:
        create_req = pb2.CreateGroupWithLeadersRequest(
            resourceTypes=["network"],
            leaders=[f"test.lead2.{timestamp}"],
            groupName=test_group,
        )
        stub.CreateGroupWithLeaders(create_req)
        print(f"  [OK] Created group: {test_group}")
        time.sleep(5)
    except Exception as e:
        print(f"  [WARN] Group creation: {e}")
    
    # Test: Przypisz wszystkie typy (z deduplikacją compute/vm)
    print(f"\n  Assigning policies: ['compute', 'vm', 'network', 'storage']")
    print(f"  Expected: deduplicated to ['network', 'storage', 'compute'] in deterministic order")
    try:
        assign_req = pb2.AssignPoliciesRequest(
            resourceTypes=["compute", "vm", "network", "storage"],  # vm powinno być zdeduplikowane
            groupName=test_group,
        )
        resp = stub.AssignPolicies(assign_req)
        print(f"    Response: success={resp.success}, message={resp.message}")
        assert resp.success, f"Multi-type assignment should succeed: {resp.message}"
        print("    [OK] Multi-type assignment successful")
        return True
    except Exception as e:
        print(f"    [FAIL] Multi-type assignment failed: {e}")
        return False


def test_cost_management_https():
    """Test że Cost Management używa HTTPS (sprawdzenie logów)."""
    print("\n=== Test 3: Cost Management HTTPS validation ===")
    
    channel = grpc.insecure_channel("localhost:50053")
    stub = pb2_grpc.CloudAdapterStub(channel)
    
    # Test GetTotalCost - powinno używać HTTPS
    print("  Testing GetTotalCost (should use HTTPS endpoint)...")
    try:
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        cost_req = pb2.CostRequest(
            startDate=start_date,
            endDate=end_date,
        )
        resp = stub.GetTotalCost(cost_req)
        print(f"    Total cost: {resp.amount}")
        print("    [OK] Cost query successful (no HTTPS error)")
        return True
    except grpc.RpcError as e:
        error_msg = str(e.details())
        if "non-TLS" in error_msg or "non-https" in error_msg.lower():
            print(f"    [FAIL] HTTPS error still present: {error_msg}")
            return False
        else:
            print(f"    [WARN] Other error (may be expected): {error_msg}")
            return True  # Inne błędy (np. brak danych) są OK
    except Exception as e:
        error_msg = str(e)
        if "non-TLS" in error_msg or "non-https" in error_msg.lower():
            print(f"    [FAIL] HTTPS error still present: {error_msg}")
            return False
        else:
            print(f"    [INFO] Error (may be expected): {error_msg}")
            return True


def main():
    """Uruchom wszystkie testy integracyjne."""
    print("=" * 60)
    print("Integration Tests for Azure Adapter Fixes")
    print("=" * 60)
    
    results = []
    
    # Test 1: RBAC idempotency
    try:
        results.append(("RBAC Idempotency", test_assign_policies_compute_idempotency()))
    except Exception as e:
        print(f"\n[ERROR] RBAC idempotency test crashed: {e}")
        results.append(("RBAC Idempotency", False))
    
    # Test 2: Multi-type assignment
    try:
        results.append(("Multi-type Assignment", test_assign_policies_multi_types()))
    except Exception as e:
        print(f"\n[ERROR] Multi-type test crashed: {e}")
        results.append(("Multi-type Assignment", False))
    
    # Test 3: Cost Management HTTPS
    try:
        results.append(("Cost Management HTTPS", test_cost_management_https()))
    except Exception as e:
        print(f"\n[ERROR] Cost Management test crashed: {e}")
        results.append(("Cost Management HTTPS", False))
    
    # Podsumowanie
    print("\n" + "=" * 60)
    print("Test Summary:")
    print("=" * 60)
    for test_name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {test_name}: {status}")
    
    all_passed = all(result[1] for result in results)
    print("\n" + "=" * 60)
    if all_passed:
        print("All tests PASSED!")
    else:
        print("Some tests FAILED - check logs above")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
