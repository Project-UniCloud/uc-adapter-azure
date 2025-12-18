#!/usr/bin/env python3
"""
Bezpośredni test GetAvailableServices na Azure adapterze.
Użyj tego skryptu, aby sprawdzić czy adapter odpowiada poprawnie.

Uruchomienie:
    python tests/test_get_available_services_direct.py
"""

import os
import sys

# Dodaj parent directory do path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grpc
from protos import adapter_interface_pb2 as pb2
from protos import adapter_interface_pb2_grpc as pb2_grpc


def test_get_available_services(host="localhost", port=50053):
    """Test GetAvailableServices na Azure adapterze."""
    print(f"\n{'='*60}")
    print(f"Test GetAvailableServices - Azure Adapter")
    print(f"{'='*60}\n")
    print(f"Łączenie z: {host}:{port}")
    
    try:
        # Utwórz kanał gRPC
        channel = grpc.insecure_channel(f"{host}:{port}")
        
        # Sprawdź połączenie
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
            print("[OK] Połączenie z adapterem udane")
        except grpc.FutureTimeoutError:
            print("[FAIL] Nie można połączyć się z adapterem (timeout)")
            print(f"       Upewnij się, że Azure adapter jest uruchomiony na {host}:{port}")
            return False
        
        # Utwórz stub
        stub = pb2_grpc.CloudAdapterStub(channel)
        
        # Test GetStatus
        print("\n[1] Test GetStatus...")
        try:
            status_request = pb2.StatusRequest()
            status_response = stub.GetStatus(status_request)
            print(f"    Status: {'[OK] isHealthy=True' if status_response.isHealthy else '[WARN] isHealthy=False'}")
        except Exception as e:
            print(f"    [FAIL] GetStatus error: {e}")
            return False
        
        # Test GetAvailableServices
        print("\n[2] Test GetAvailableServices...")
        try:
            services_request = pb2.GetAvailableServicesRequest()
            services_response = stub.GetAvailableServices(services_request)
            services_list = list(services_response.services)
            
            print(f"    Liczba serwisów: {len(services_list)}")
            if services_list:
                print(f"    [OK] Serwisy: {services_list}")
                expected_services = ["vm", "storage", "network", "compute"]
                missing = set(expected_services) - set(services_list)
                if missing:
                    print(f"    [WARN] Brakujące serwisy: {missing}")
                else:
                    print(f"    [OK] Wszystkie oczekiwane serwisy są dostępne")
                return True
            else:
                print(f"    [FAIL] Lista serwisów jest pusta!")
                print(f"    Sprawdź konfigurację RESOURCE_TYPE_ROLES w identity/rbac_manager.py")
                return False
        except grpc.RpcError as e:
            print(f"    [FAIL] GetAvailableServices error: {e.code()} - {e.details()}")
            return False
        except Exception as e:
            print(f"    [FAIL] GetAvailableServices error: {e}")
            return False
        
    except Exception as e:
        print(f"\n[FAIL] Nieoczekiwany błąd: {e}")
        return False
    finally:
        channel.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test GetAvailableServices na Azure adapterze")
    parser.add_argument("--host", default="localhost", help="Host Azure adaptera (default: localhost)")
    parser.add_argument("--port", type=int, default=50053, help="Port Azure adaptera (default: 50053)")
    
    args = parser.parse_args()
    
    success = test_get_available_services(host=args.host, port=args.port)
    
    if success:
        print(f"\n{'='*60}")
        print("[OK] Test zakończony pomyślnie!")
        print(f"{'='*60}\n")
        sys.exit(0)
    else:
        print(f"\n{'='*60}")
        print("[FAIL] Test nie powiódł się!")
        print(f"{'='*60}\n")
        print("Rozwiązywanie problemów:")
        print("1. Sprawdź czy Azure adapter jest uruchomiony: python main.py")
        print("2. Sprawdź logi adaptera pod kątem błędów")
        print("3. Sprawdź czy port 50053 jest dostępny")
        print("4. Sprawdź konfigurację RESOURCE_TYPE_ROLES w identity/rbac_manager.py")
        print("\nZobacz też: TROUBLESHOOTING.md")
        sys.exit(1)

