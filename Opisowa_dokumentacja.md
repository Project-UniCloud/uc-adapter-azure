# Raport Techniczny: Azure Cloud Adapter dla UniCloud

## Spis treści
1. [Wprowadzenie](#wprowadzenie)
2. [Architektura systemu](#architektura-systemu)
3. [Struktura projektu i opis plików](#struktura-projektu-i-opis-plików)
4. [Biblioteki i zależności](#biblioteki-i-zależności)
5. [Komunikacja przez endpointy gRPC](#komunikacja-przez-endpointy-grpc)
6. [Mechanizm uprawnień RBAC](#mechanizm-uprawnień-rbac)
7. [Porównanie z adapterem AWS](#porównanie-z-adapterem-aws)
8. [Podsumowanie](#podsumowanie)

---

## 1. Wprowadzenie

Azure Cloud Adapter jest komponentem systemu UniCloud odpowiedzialnym za integrację z platformą Microsoft Azure. Adapter zapewnia standardowy interfejs gRPC do zarządzania zasobami Azure, tożsamościami (użytkownicy i grupy w Azure AD/Entra ID), monitorowaniem kosztów oraz kontrolą dostępu opartą na rolach (RBAC).

### Cel projektu
- Zapewnienie spójnego interfejsu API dla zarządzania zasobami Azure
- Automatyzacja tworzenia i zarządzania grupami oraz użytkownikami w Azure AD
- Monitorowanie kosztów zasobów przypisanych do grup
- Implementacja kontroli dostępu opartej na rolach (RBAC) dla różnych typów zasobów

---

## 2. Architektura systemu

Adapter Azure jest zbudowany w architekturze modułowej z wyraźnym podziałem odpowiedzialności:

```
uc-adapter-azure/
├── main.py                    # Punkt wejścia, serwer gRPC
├── azure_clients.py           # Centralne klienty Azure SDK
├── config/
│   └── settings.py            # Konfiguracja (zmienne środowiskowe)
├── handlers/                  # Handlery RPC metod
│   ├── identity_handlers.py  # Operacje na tożsamościach
│   ├── cost_handlers.py      # Operacje na kosztach
│   └── resource_handlers.py  # Operacje na zasobach
├── identity/                  # Zarządzanie tożsamościami
│   ├── user_manager.py        # Zarządzanie użytkownikami
│   ├── group_manager.py       # Zarządzanie grupami
│   ├── rbac_manager.py       # Zarządzanie uprawnieniami RBAC
│   └── utils.py              # Funkcje pomocnicze
├── clean_resources/           # Zarządzanie zasobami
│   ├── resource_finder.py    # Wyszukiwanie zasobów
│   └── resource_deleter.py   # Usuwanie zasobów
├── cost_monitoring/           # Monitorowanie kosztów
│   └── limit_manager.py      # Limity i koszty
└── protos/                    # Definicje protobuf
    └── adapter_interface.proto
```

### Wzorzec projektowy
Adapter wykorzystuje wzorzec **Handler Pattern**, gdzie główny serwer gRPC (`CloudAdapterServicer`) deleguje wywołania RPC do specjalizowanych handlerów:
- **IdentityHandlers** - operacje na użytkownikach i grupach
- **CostHandlers** - zapytania o koszty
- **ResourceHandlers** - operacje na zasobach Azure

---

## 3. Struktura projektu i opis plików

### 3.1. Pliki główne

#### `main.py` (~137 linii)
**Rola**: Punkt wejścia aplikacji, inicjalizacja serwera gRPC.

**Kluczowe komponenty**:
- `CloudAdapterServicer` - główna klasa serwera gRPC implementująca interfejs `CloudAdapter`
- `serve()` - funkcja uruchamiająca serwer gRPC na porcie 50053 (insecure channel)

**Metody RPC** (delegowane do handlerów):
- **Identity Management**: `GetStatus`, `GroupExists`, `CreateGroupWithLeaders`, `CreateUsersForGroup`, `RemoveGroup`, `AssignPolicies`, `UpdateGroupLeaders`
- **Cost Monitoring**: `GetTotalCostForGroup`, `GetTotalCostsForAllGroups`, `GetTotalCost`, `GetGroupCostWithServiceBreakdown`, `GetTotalCostWithServiceBreakdown`, `GetGroupCostsLast6MonthsByService`, `GetGroupMonthlyCostsLast6Months`
- **Resource Management**: `GetAvailableServices`, `GetResourceCount`, `CleanupGroupResources`

**Inicjalizacja**:
```python
def __init__(self):
    self.user_manager = AzureUserManager()
    self.group_manager = AzureGroupManager()
    self.rbac_manager = AzureRBACManager()
    self.resource_finder = ResourceFinder()
    self.resource_deleter = ResourceDeleter()
    # Handlery otrzymują menedżerów jako zależności
```

#### `azure_clients.py` (~100 linii)
**Rola**: Centralny moduł dostarczający klientów Azure SDK (analogiczny do `boto3` w AWS).

**Funkcje** (wszystkie z `@lru_cache` dla singletonów):
- `get_credential()` - zwraca `ClientSecretCredential` (uwierzytelnianie)
- `get_graph_client()` - klient Microsoft Graph API (zarządzanie użytkownikami/grupami)
- `get_resource_client()` - `ResourceManagementClient` (zarządzanie zasobami)
- `get_compute_client()` - `ComputeManagementClient` (zarządzanie maszynami wirtualnymi)
- `get_cost_client()` - `CostManagementClient` (monitorowanie kosztów, wymusza HTTPS endpoint)

**Funkcje pomocnicze**:
- `_validate_https_url(url)` - waliduje, że URL używa HTTPS
- `_validate_scope(scope)` - waliduje format scope (musi zaczynać się od `/subscriptions/`)

**Bezpieczeństwo**: Wszystkie funkcje walidują, że nie używają HTTP (tylko HTTPS) i poprawnego formatu scope.

### 3.2. Konfiguracja

#### `config/settings.py` (43 linie)
**Rola**: Zarządzanie konfiguracją poprzez zmienne środowiskowe.

**Zmienne środowiskowe**:
- `AZURE_TENANT_ID` - ID dzierżawy Azure AD
- `AZURE_CLIENT_ID` - ID aplikacji Azure AD
- `AZURE_CLIENT_SECRET` - Klucz tajny aplikacji
- `AZURE_SUBSCRIPTION_ID` - ID subskrypcji Azure
- `AZURE_UDOMAIN` - Domena Azure AD (np. `<AZURE_TENANT_DOMAIN>`)

**Funkcje**:
- `validate_config()` - waliduje obecność wszystkich wymaganych zmiennych

**Bezpieczeństwo**: Wszystkie wartości są pobierane ze zmiennych środowiskowych (nigdy nie są hardkodowane w kodzie).

### 3.3. Handlery RPC

#### `handlers/identity_handlers.py` (590 linii)
**Rola**: Implementacja operacji związanych z tożsamością.

**Metody**:
1. **`get_status(request, context)`**
   - Health check endpoint
   - Sprawdza inicjalizację wszystkich komponentów (user_manager, group_manager, rbac_manager, resource_finder, resource_deleter)
   - Weryfikuje możliwość utworzenia klientów Azure
   - Zwraca `StatusResponse(isHealthy=True/False)`

2. **`group_exists(request, context)`**
   - Sprawdza istnienie grupy w Azure AD
   - Normalizuje nazwę przed wyszukiwaniem
   - Zwraca `GroupExistsResponse(exists=True/False)`

3. **`create_group_with_leaders(request, context)`**
   - Tworzy grupę w Azure AD
   - Tworzy użytkowników-liderów i dodaje ich do grupy jako członków i właścicieli
   - Przypisuje role RBAC na podstawie `resourceTypes`
   - Implementuje rollback w przypadku błędów
   - Zwraca `GroupCreatedResponse(groupName=...)`

4. **`create_users_for_group(request, context)`**
   - Tworzy użytkowników i dodaje ich do istniejącej grupy
   - Obsługuje duplikaty (sprawdza przed dodaniem)
   - Kontynuuje mimo błędów części użytkowników
   - Dodaje suffix grupy do username (format: `{login}-{group_name}`)
   - Zwraca `CreateUsersForGroupResponse(message="Users successfully added")`

5. **`remove_group(request, context)`**
   - Usuwa grupę i wszystkich jej członków (użytkowników)
   - Operacja idempotentna (zwraca sukces jeśli grupa nie istnieje)
   - Zwraca `RemoveGroupResponse(success=True, removedUsers=[...])`

6. **`assign_policies(request, context)`**
   - Przypisuje role RBAC do grupy na podstawie typów zasobów
   - Obsługuje wiele typów zasobów w jednym wywołaniu
   - Zwraca `AssignPoliciesResponse(success=True/False, message=...)`

7. **`update_group_leaders(request, context)`**
   - Aktualizuje liderów istniejącej grupy (pełna synchronizacja)
   - Usuwa starych właścicieli, dodaje nowych
   - Tworzy nowych użytkowników-liderów jeśli nie istnieją
   - Dodaje nowych liderów jako członków i właścicieli grupy
   - Używa tego samego request/response co `CreateGroupWithLeaders`
   - Zwraca `GroupCreatedResponse(groupName=...)`

#### `handlers/cost_handlers.py` (235 linii)
**Rola**: Implementacja zapytań o koszty Azure.

**Metody**:
1. **`get_total_cost_for_group(request, context)`**
   - Zwraca całkowity koszt grupy w określonym okresie
   - Używa Azure Cost Management API z filtrowaniem po tagu `Group`

2. **`get_total_costs_for_all_groups(request, context)`**
   - Zwraca koszty wszystkich grup
   - Implementuje bezpieczną denormalizację nazw (dashes → spaces) tylko dla standardowego formatu z semestrem

3. **`get_total_cost(request, context)`**
   - Zwraca całkowity koszt subskrypcji Azure

4. **`get_group_cost_with_service_breakdown(request, context)`**
   - Zwraca koszt grupy z podziałem na usługi (VM, Storage, Network, etc.)

5. **`get_total_cost_with_service_breakdown(request, context)`**
   - Zwraca całkowity koszt subskrypcji z podziałem na usługi

6. **`get_group_costs_last_6_months_by_service(request, context)`**
   - Zwraca koszty grupy za ostatnie 6 miesięcy pogrupowane według usług

7. **`get_group_monthly_costs_last_6_months(request, context)`**
   - Zwraca miesięczne koszty grupy za ostatnie 6 miesięcy

**Funkcja pomocnicza**:
- `_safe_denormalize_group_name()` - bezpiecznie konwertuje nazwy z dashes na spaces tylko dla standardowego formatu z semestrem (np. "AI-2024L" → "AI 2024L")

#### `handlers/resource_handlers.py` (119 linii)
**Rola**: Implementacja operacji na zasobach Azure.

**Metody**:
1. **`get_available_services(request, context)`**
   - Zwraca listę dostępnych typów zasobów
   - Pobiera z `rbac_manager.RESOURCE_TYPE_ROLES.keys()`
   - Zwraca `GetAvailableServicesResponse(services=["vm", "storage", "network", ...])`

2. **`get_resource_count(request, context)`**
   - Zwraca liczbę zasobów przypisanych do grupy (filtrowanie po tagu `Group`)
   - Filtruje po typie zasobu (np. "vm", "storage")
   - Zwraca `ResourceCountResponse(count=...)`

3. **`cleanup_group_resources(request, context)`**
   - Usuwa wszystkie zasoby Azure związane z grupą
   - Wyszukuje zasoby po tagu `Group`
   - Usuwa zasoby przez `ResourceDeleter`
   - Zwraca `CleanupGroupResponse(success=True, deletedResources=[...])`

### 3.4. Zarządzanie tożsamościami

#### `identity/user_manager.py` (158 linii)
**Rola**: Zarządzanie użytkownikami w Azure AD przez Microsoft Graph API.

**Metody**:
- `create_user(login, display_name, initial_password, group_name)` - tworzy użytkownika, dodaje suffix grupy do username
- `delete_user(login_or_upn)` - usuwa użytkownika
- `get_user(login_or_upn)` - pobiera dane użytkownika
- `reset_password(login_or_upn, new_password)` - resetuje hasło

**Funkcje pomocnicze**:
- `_login_to_upn(login)` - konwertuje login na UPN (User Principal Name)
- `_generate_initial_password(group_name)` - generuje hasło zgodne z polityką Azure AD

#### `identity/group_manager.py` (~439 linii)
**Rola**: Zarządzanie grupami w Azure AD przez Microsoft Graph API.

**Metody główne**:
- `create_group(name, description, create_resource_group)` - tworzy grupę bezpieczeństwa (security group)
  - Opcjonalnie tworzy Azure Resource Group `rg-{normalized_name}` z tagiem `Group`
  - Zwraca tuple `(group_id, resource_group_name)`
- `delete_group(group_id)` - usuwa grupę
- `get_group_by_id(group_id)` - pobiera grupę po ID
- `get_group_by_name(name)` - wyszukuje grupę po nazwie (normalizuje przed wyszukiwaniem)

**Metody zarządzania członkami**:
- `add_member(group_id, user_id)` - dodaje członka do grupy (z retry logic dla replikacji)
- `add_owner(group_id, user_id)` - dodaje właściciela grupy (z retry logic)
- `remove_member(group_id, user_id)` - usuwa członka z grupy
- `remove_owner(group_id, user_id)` - usuwa właściciela grupy
- `list_members(group_id)` - zwraca listę członków grupy (ObjectIds)
- `list_owners(group_id)` - zwraca listę właścicieli grupy (ObjectIds)

**Mechanizm retry**: Metody `add_member` i `add_owner` implementują retry logic (5 prób, 3s opóźnienie) dla obsługi opóźnionej replikacji Azure AD.

**Resource Group**: Automatycznie tworzy Resource Group dla każdej grupy (fallback dla cleanup jeśli tagowanie nie działa).

#### `identity/rbac_manager.py` (~443 linie)
**Rola**: Zarządzanie przypisaniami ról RBAC w Azure.

**Mapowanie typów zasobów na role**:
```python
RESOURCE_TYPE_ROLES = {
    "vm": "Virtual Machine Contributor",
    "storage": "Storage Account Contributor",
    "network": "Network Contributor",
}
RESOURCE_TYPE_ORDER = ["network", "storage", "vm"]  # Kolejność przypisywania ról
```

**Metody główne**:
- `_get_role_definition_id(role_name)` - wyszukuje ID definicji roli w subskrypcji
- `assign_role_to_group(resource_type, group_id, scope)` - przypisuje rolę RBAC do grupy
  - Wyszukuje definicję roli na podstawie typu zasobu
  - Sprawdza czy przypisanie już istnieje (idempotentność)
  - Tworzy przypisanie roli na scope subskrypcji (domyślnie) lub resource group
  - Weryfikuje utworzenie przypisania po operacji
  - Implementuje retry logic (5 prób, 5s opóźnienie) dla obsługi `PrincipalNotFound` (opóźniona replikacja)
  - Zwraca tuple `(success: bool, reason: str)`

**Metody pomocnicze**:
- `_find_existing_role_assignment(scope, principal_id, role_definition_id)` - sprawdza czy przypisanie już istnieje
- `_verify_role_assignment_exists(scope, assignment_name)` - weryfikuje istnienie przypisania po utworzeniu
- `remove_role_assignments_for_group(group_id, scope)` - usuwa wszystkie przypisania ról dla grupy (z retry logic)
- `remove_role_assignments_for_user(user_id, scope)` - usuwa wszystkie przypisania ról dla użytkownika (z retry logic)

**Scope przypisania**: Domyślnie poziom subskrypcji (`/subscriptions/{subscription_id}`), można zawęzić do resource group.

**Idempotentność**: Wszystkie operacje są idempotentne - wielokrotne wywołanie nie powoduje duplikacji.

#### `identity/utils.py` (47 linii)
**Rola**: Funkcje pomocnicze do normalizacji nazw.

**Funkcje**:
- `normalize_name(name)` - normalizuje nazwy (spaces/underscores → dashes, polskie znaki → ASCII)
- `build_username_with_group_suffix(user_login, group_name)` - buduje username z suffixem grupy (format: `{login}-{normalized_group}`)

#### `identity/resource_tagging.py` (76 linii)
**Rola**: Mechanizm tagowania zasobów Azure z tagiem `Group` (odpowiednik AWS auto-tagging).

**Funkcje**:
- `ensure_resource_tagged(resource_id, group_name)` - dodaje tag `Group` do zasobu Azure
  - Pobiera aktualne tagi zasobu
  - Aktualizuje tag `Group` z znormalizowaną nazwą grupy
  - Wymaga uprawnień do modyfikacji zasobów (np. rola Tag Contributor)
  - Zwraca `True` jeśli tagowanie się powiodło

**Uwaga**: Tagowanie może być wywoływane przez użytkowników z odpowiednimi rolami. Nie jest automatyczne (wymaga Azure Policy lub ręcznego wywołania).

### 3.5. Zarządzanie zasobami

#### `clean_resources/resource_finder.py` (122 linie)
**Rola**: Wyszukiwanie zasobów Azure na podstawie tagów.

**Metody**:
- `find_resources_by_tags(tag_filter)` - wyszukuje zasoby pasujące do filtrów tagów
  - Przeszukuje wszystkie zasoby w subskrypcji
  - Porównuje tagi (z normalizacją wartości)
  - Zwraca listę słowników z informacjami: `{"id", "name", "type", "service", "resource_group"}`

**Funkcje pomocnicze**:
- `_extract_service_name(resource_type)` - ekstrahuje krótką nazwę usługi z pełnego typu zasobu Azure (np. `Microsoft.Compute/virtualMachines` → `vm`)

#### `clean_resources/resource_deleter.py` (111 linii)
**Rola**: Usuwanie zasobów Azure na podstawie typu.

**Metody**:
- `delete_resource(resource)` - usuwa zasób na podstawie typu
  - Obsługuje: VMs, Network Interfaces, Public IPs, Virtual Networks, Network Security Groups, Storage Accounts
  - Dla innych typów używa generycznego `ResourceManagementClient.resources.begin_delete_by_id()`
  - Zwraca komunikat sukcesu lub błędu

**Klienci używane**:
- `ComputeManagementClient` - dla maszyn wirtualnych
- `NetworkManagementClient` - dla zasobów sieciowych
- `StorageManagementClient` - dla kont magazynu
- `ResourceManagementClient` - dla generycznego usuwania

### 3.6. Monitorowanie kosztów

#### `cost_monitoring/limit_manager.py` (752 linie)
**Rola**: Zarządzanie limitami zasobów i monitorowanie kosztów.

**Klasa `LimitManager`**:
- `count_users()` - liczy użytkowników w Azure AD (używa `@odata.count` z Graph API)
- `count_vms()` - liczy maszyny wirtualne w subskrypcji
- `count_vms_in_resource_group(resource_group_name)` - liczy VMs w grupie zasobów
- `ensure_user_limit(max_users)` - sprawdza limit użytkowników (rzuca `LimitExceededError`)
- `ensure_vm_limit(max_vms, resource_group_name)` - sprawdza limit VMs
- `ensure_limits(max_users, max_vms, resource_group_name)` - sprawdza wiele limitów jednocześnie

**Funkcje kosztów** (używają Azure Cost Management API):
- `get_total_cost_for_group(group_tag_value, start_date, end_date)` - koszt grupy
- `get_group_cost_with_service_breakdown(...)` - koszt grupy z podziałem na usługi
- `get_total_costs_for_all_groups(start_date, end_date)` - koszty wszystkich grup
- `get_total_azure_cost(start_date, end_date)` - całkowity koszt subskrypcji
- `get_total_cost_with_service_breakdown(...)` - całkowity koszt z podziałem na usługi
- `get_group_cost_last_6_months_by_service(group_tag_value)` - koszty ostatnich 6 miesięcy pogrupowane według usług
- `get_group_monthly_costs_last_6_months(group_tag_value)` - miesięczne koszty ostatnich 6 miesięcy

**Funkcje pomocnicze**:
- `_azure_service_to_short(name)` - mapuje pełne nazwy usług Azure na krótkie (np. `Microsoft.Compute/virtualMachines` → `vm`)
- `_first_day_of_month(dt)` - zwraca pierwszy dzień miesiąca
- `_shift_months(dt, months)` - przesuwa datę o określoną liczbę miesięcy

### 3.7. Protobuf

#### `protos/adapter_interface.proto` (~169 linii)
**Rola**: Definicja interfejsu gRPC w formacie Protocol Buffers.

**Service `CloudAdapter`** - definiuje metody RPC:
- **Identity**: `GetStatus`, `GroupExists`, `CreateGroupWithLeaders`, `CreateUsersForGroup`, `RemoveGroup`, `AssignPolicies`
- **Cost**: `GetTotalCostForGroup`, `GetTotalCostsForAllGroups`, `GetTotalCost`, `GetGroupCostWithServiceBreakdown`, `GetTotalCostWithServiceBreakdown`, `GetGroupCostsLast6MonthsByService`, `GetGroupMonthlyCostsLast6Months`
- **Resource**: `GetAvailableServices`, `GetResourceCount`, `CleanupGroupResources`

**Wygenerowane pliki**:
- `adapter_interface_pb2.py` - klasy Python dla komunikatów (generowany przez protoc)
- `adapter_interface_pb2_grpc.py` - klasy Python dla serwisu gRPC (generowany przez protoc)

**Generowanie**: Użyj `generate_proto.sh` (Linux/Mac) lub `generate_proto.bat` (Windows) do regeneracji plików po zmianach w `.proto`.

### 3.8. Deployment i infrastruktura

#### `Dockerfile` (31 linii)
**Rola**: Definicja obrazu Docker dla adaptera.

**Charakterystyka**:
- Bazowy obraz: `python:3.11-slim`
- Użytkownik: `adapteruser` (UID 1001, non-root)
- Port: `50053` (gRPC)
- Entrypoint: `python main.py`

**Kroki build**:
1. Kopiowanie `requirements.txt` i instalacja zależności
2. Kopiowanie kodu aplikacji
3. Zmiana właściciela na non-root user
4. Uruchomienie jako non-root user

#### `docker-compose.yml` (25 linii)
**Rola**: Konfiguracja lokalnego środowiska deweloperskiego.

**Konfiguracja**:
- Serwis: `azure-adapter`
- Port mapping: `50053:50053`
- Zmienne środowiskowe: Wszystkie wymagane zmienne Azure (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, etc.)
- Healthcheck: Automatyczny health check przez wywołanie `GetStatus` gRPC
- Restart policy: `unless-stopped`

#### `.github/workflows/pipeline.yml`
**Rola**: CI/CD pipeline dla GitHub Actions.

**Funkcjonalność**:
- **Build job**: Buduje obraz Docker i pushuje do GHCR (GitHub Container Registry)
- **Deploy job**: Wywołuje webhook restart dla automatycznego wdrożenia (jeśli push do `main`)

**Trigger**: Push i Pull Request do brancha `main`

### 3.9. Testy i weryfikacja działania

Folder `tests/` zawiera testy integracyjne i smoke testy:

#### Rodzaje testów

**Smoke testy** (ręczne testy funkcjonalności):
- `smoke_test.py` - podstawowe smoke testy dla `user_manager` i `group_manager`
  - Testuje tworzenie grupy, użytkownika, dodawanie członków
  - Uruchomienie: `python tests/smoke_test.py`
- `limit_smoke_test.py` - testy limitów zasobów (liczenie użytkowników, VMs)
  - Uruchomienie: `python tests/limit_smoke_test.py`

**Unit testy** (unittest framework):
- `test_get_status.py` - testy health check endpoint (`GetStatus`)
  - Testuje inicjalizację komponentów, obsługę błędów
  - Uruchomienie: `python -m unittest tests.test_get_status`
- `test_required_methods.py` - weryfikacja wymaganych metod RPC

**Testy integracyjne**:
- `test_backend_connection.py` - testy formatów requestów zgodnych z backendem
  - Weryfikuje formaty protobuf messages dla integracji z backendem
- `test_rbac_idempotency.py` - testy idempotentności operacji RBAC
  - Sprawdza bezpieczeństwo wielokrotnego przypisywania ról
- `test_get_available_services_direct.py` - testy dostępnych usług
  - Weryfikuje listę dostępnych typów zasobów
- `test_get_total_costs_for_all_groups.py` - testy zapytań kosztowych
  - Testuje integrację z Azure Cost Management API
- `test_teardown_flow.py` - testy procesu usuwania grup i zasobów
- `test_teardown_users.py` - testy usuwania użytkowników
- `test_fixes_integration.py` - testy integracyjne poprawek
- `test_https_validation.py` - testy walidacji HTTPS
- `client_test.py` - testy klientów Azure SDK

#### Uruchomienie testów

**Wszystkie unit testy**:
```bash
python -m unittest discover tests
```

**Konkretny test**:
```bash
python -m unittest tests.test_get_status
python tests/smoke_test.py  # dla smoke testów
```

**Wymagania**: Wszystkie testy wymagają skonfigurowanych zmiennych środowiskowych (`.env` lub export) oraz prawidłowych credentials Azure.

---

## 4. Biblioteki i zależności

### 4.1. Lista bibliotek (`requirements.txt`)

#### Konfiguracja i środowisko
- **`python-dotenv`** - ładowanie zmiennych środowiskowych z pliku `.env`

#### Microsoft Graph API
- **`msgraph-core==0.2.2`** - klient Microsoft Graph API
  - Używany do zarządzania użytkownikami i grupami w Azure AD
  - Wersja 0.2.2 jest wymagana (nowsze wersje zmieniły API - `GraphClient` jest w `msgraph.core`)

#### Azure SDK
- **`azure-identity`** - uwierzytelnianie Azure (ClientSecretCredential)
- **`azure-mgmt-resource`** - zarządzanie zasobami (ResourceManagementClient)
- **`azure-mgmt-compute`** - zarządzanie maszynami wirtualnymi (ComputeManagementClient)
- **`azure-mgmt-network`** - zarządzanie zasobami sieciowymi (NetworkManagementClient)
- **`azure-mgmt-costmanagement`** - monitorowanie kosztów (CostManagementClient)
- **`azure-mgmt-authorization`** - zarządzanie RBAC (AuthorizationManagementClient)
- **`azure-mgmt-storage`** - zarządzanie kontami magazynu (StorageManagementClient)

#### gRPC i Protobuf
- **`grpcio>=1.76.0`** - framework gRPC dla Python
- **`grpcio-tools>=1.76.0`** - narzędzia do generowania kodu z plików `.proto`
- **`protobuf>=6.31.1`** - serializacja danych Protocol Buffers

**Uwaga**: Wersje gRPC i protobuf są zsynchronizowane dla kompatybilności (protobuf 6.x wymaga grpcio >= 1.76.0).

### 4.2. Zastosowanie bibliotek

| Biblioteka | Gdzie używana | Cel |
|------------|---------------|-----|
| `msgraph-core` | `azure_clients.py`, `identity/user_manager.py`, `identity/group_manager.py`, `cost_monitoring/limit_manager.py` | Zarządzanie użytkownikami i grupami w Azure AD |
| `azure-identity` | `azure_clients.py` | Uwierzytelnianie do usług Azure |
| `azure-mgmt-resource` | `azure_clients.py`, `clean_resources/resource_finder.py`, `clean_resources/resource_deleter.py` | Zarządzanie zasobami Azure |
| `azure-mgmt-compute` | `azure_clients.py`, `clean_resources/resource_deleter.py`, `cost_monitoring/limit_manager.py` | Zarządzanie maszynami wirtualnymi |
| `azure-mgmt-network` | `clean_resources/resource_deleter.py` | Zarządzanie zasobami sieciowymi |
| `azure-mgmt-costmanagement` | `azure_clients.py`, `cost_monitoring/limit_manager.py` | Monitorowanie kosztów |
| `azure-mgmt-authorization` | `identity/rbac_manager.py` | Przypisywanie ról RBAC |
| `azure-mgmt-storage` | `clean_resources/resource_deleter.py` | Zarządzanie kontami magazynu |
| `grpcio`, `protobuf` | `main.py`, wszystkie handlery | Komunikacja gRPC z backendem |

---

## 5. Komunikacja przez endpointy gRPC

### 5.1. Protokół komunikacji

Adapter używa **gRPC (gRPC Remote Procedure Calls)** z serializacją **Protocol Buffers** do komunikacji z backendem UniCloud.

**Port**: `50053` (domyślny)

**Protokół**: HTTP/2 z TLS (w produkcji) lub insecure (w rozwoju)

### 5.2. Lista endpointów RPC

#### 5.2.1. Identity Management

##### `GetStatus`
**Request**: `StatusRequest` (pusty)
**Response**: `StatusResponse { bool isHealthy }`
**Opis**: Health check endpoint. Sprawdza inicjalizację komponentów i dostępność klientów Azure.

##### `GroupExists`
**Request**: `GroupExistsRequest { string groupName }`
**Response**: `GroupExistsResponse { bool exists }`
**Opis**: Sprawdza istnienie grupy w Azure AD. Normalizuje nazwę przed wyszukiwaniem.

##### `CreateGroupWithLeaders`
**Request**: 
```protobuf
CreateGroupWithLeadersRequest {
  repeated string resourceTypes = 1;  // np. ["vm", "storage"]
  repeated string leaders = 2;      // np. ["s12345", "s67890"]
  string groupName = 3;               // np. "AI 2024L"
}
```
**Response**: `GroupCreatedResponse { string groupName }`
**Opis**: 
- Tworzy grupę w Azure AD
- Tworzy użytkowników-liderów i dodaje ich do grupy jako członków i właścicieli
- Przypisuje role RBAC na podstawie `resourceTypes` (używa pierwszego typu z listy)
- Dodaje suffix grupy do username liderów (format: `{login}-{normalized_group}`)

##### `CreateUsersForGroup`
**Request**: 
```protobuf
CreateUsersForGroupRequest {
  repeated string users = 1;    // np. ["s11111", "s22222"]
  string groupName = 2;         // np. "AI 2024L"
}
```
**Response**: `CreateUsersForGroupResponse { string message }`
**Opis**: 
- Tworzy użytkowników i dodaje ich do istniejącej grupy
- Sprawdza duplikaty przed dodaniem
- Kontynuuje mimo błędów części użytkowników
- Dodaje suffix grupy do username (format: `{login}-{normalized_group}`)
- Zwraca `message = "Users successfully added"`

##### `RemoveGroup`
**Request**: `RemoveGroupRequest { string groupName }`
**Response**: 
```protobuf
RemoveGroupResponse {
  bool success;
  repeated string removedUsers;
  string message;
}
```
**Opis**: Usuwa grupę i wszystkich jej członków (użytkowników). Operacja idempotentna.

##### `AssignPolicies`
**Request**: 
```protobuf
AssignPoliciesRequest {
  repeated string resourceTypes = 1;  // np. ["vm", "storage"]
  string groupName = 2;               // opcjonalne
  string userName = 3;                // opcjonalne (niezaimplementowane)
}
```
**Response**: `AssignPoliciesResponse { bool success; string message }`
**Opis**: Przypisuje role RBAC do grupy na podstawie typów zasobów. Obsługuje wiele typów w jednym wywołaniu.

##### `UpdateGroupLeaders`
**Request**: `CreateGroupWithLeadersRequest` (ten sam co dla `CreateGroupWithLeaders`)
```protobuf
CreateGroupWithLeadersRequest {
  repeated string resourceTypes = 1;
  repeated string leaders = 2;      // Nowi liderzy (zastąpią starych)
  string groupName = 3;
}
```
**Response**: `GroupCreatedResponse { string groupName }`
**Opis**: 
- Aktualizuje liderów istniejącej grupy (pełna synchronizacja)
- Usuwa starych właścicieli grupy, dodaje nowych
- Tworzy nowych użytkowników-liderów jeśli nie istnieją
- Dodaje nowych liderów jako członków i właścicieli grupy
- Operacja wymaga, aby grupa już istniała

#### 5.2.2. Cost Monitoring

##### `GetTotalCostForGroup`
**Request**: 
```protobuf
CostRequest {
  string startDate = 1;    // format: "YYYY-MM-DD"
  string endDate = 2;      // format: "YYYY-MM-DD"
  string groupName = 3;   // np. "AI 2024L"
}
```
**Response**: `CostResponse { double amount }`
**Opis**: Zwraca całkowity koszt grupy w określonym okresie. Używa Azure Cost Management API z filtrowaniem po tagu `Group`.

##### `GetTotalCostsForAllGroups`
**Request**: `CostRequest` (tylko `startDate` i `endDate` są używane)
**Response**: 
```protobuf
AllGroupsCostResponse {
  repeated GroupCost groupCosts = 1;  // GroupCost { string groupName; double amount; }
}
```
**Opis**: Zwraca koszty wszystkich grup. Implementuje bezpieczną denormalizację nazw (dashes → spaces) tylko dla standardowego formatu z semestrem.

##### `GetTotalCost`
**Request**: `CostRequest` (tylko `startDate` i `endDate` są używane)
**Response**: `CostResponse { double amount }`
**Opis**: Zwraca całkowity koszt subskrypcji Azure.

##### `GetGroupCostWithServiceBreakdown`
**Request**: 
```protobuf
GroupServiceBreakdownRequest {
  string groupName = 1;
  string startDate = 2;
  string endDate = 3;
}
```
**Response**: 
```protobuf
GroupServiceBreakdownResponse {
  double total;
  repeated ServiceCost breakdown = 2;  // ServiceCost { string serviceName; double amount; }
}
```
**Opis**: Zwraca koszt grupy z podziałem na usługi (VM, Storage, Network, etc.).

##### `GetTotalCostWithServiceBreakdown`
**Request**: `CostRequest` (tylko `startDate` i `endDate` są używane)
**Response**: `GroupServiceBreakdownResponse` (jak wyżej)
**Opis**: Zwraca całkowity koszt subskrypcji z podziałem na usługi.

##### `GetGroupCostsLast6MonthsByService`
**Request**: `GroupLast6MonthsCostRequest { string groupName }`
**Response**: `GroupCostMapResponse { map<string, double> costs }`
**Opis**: Zwraca koszty grupy za ostatnie 6 miesięcy pogrupowane według usług. Klucze mapy to krótkie nazwy usług (np. "vm", "storage").

##### `GetGroupMonthlyCostsLast6Months`
**Request**: `GroupLast6MonthsCostRequest { string groupName }`
**Response**: `GroupMonthlyCostsResponse { map<string, double> monthCosts }`
**Opis**: Zwraca miesięczne koszty grupy za ostatnie 6 miesięcy. Klucze mapy to daty w formacie "dd-MM-yyyy".

#### 5.2.3. Resource Management

##### `GetAvailableServices`
**Request**: `GetAvailableServicesRequest` (pusty)
**Response**: `GetAvailableServicesResponse { repeated string services }`
**Opis**: Zwraca listę dostępnych typów zasobów (np. `["vm", "storage", "network", "compute"]`). Pobiera z `rbac_manager.RESOURCE_TYPE_ROLES.keys()`.

##### `GetResourceCount`
**Request**: 
```protobuf
ResourceCountRequest {
  string groupName = 1;      // np. "AI 2024L"
  string resourceType = 2;   // np. "vm", "storage"
}
```
**Response**: `ResourceCountResponse { int32 count }`
**Opis**: Zwraca liczbę zasobów przypisanych do grupy (filtrowanie po tagu `Group`) i typie zasobu.

##### `CleanupGroupResources`
**Request**: 
```protobuf
CleanupGroupRequest {
  string groupName = 1;
  bool force = 2;  // nieużywane w obecnej implementacji
}
```
**Response**: 
```protobuf
CleanupGroupResponse {
  bool success;
  repeated string deletedResources;
  string message;
}
```
**Opis**: Usuwa wszystkie zasoby Azure związane z grupą. Wyszukuje zasoby po tagu `Group` i usuwa je przez `ResourceDeleter`.

### 5.3. Przykład komunikacji

**Backend wywołuje**:
```python
stub = CloudAdapterStub(channel)
request = CreateGroupWithLeadersRequest(
    resourceTypes=["vm"],
    leaders=["s12345", "s67890"],
    groupName="AI 2024L"
)
response = stub.CreateGroupWithLeaders(request)
# response.groupName = "AI 2024L"
```

**Adapter wykonuje**:
1. Normalizuje nazwę grupy: "AI 2024L" → "AI-2024L"
2. Tworzy grupę w Azure AD
3. Przypisuje rolę "Virtual Machine Contributor" do grupy (na podstawie `resourceTypes[0] = "vm"`)
4. Tworzy użytkowników: "s12345-AI-2024L", "s67890-AI-2024L"
5. Dodaje użytkowników do grupy jako członków i właścicieli
6. Zwraca `GroupCreatedResponse(groupName="AI 2024L")`

---

## 6. Mechanizm uprawnień RBAC

### 6.1. Przegląd systemu uprawnień

Azure Adapter używa **Azure RBAC (Role-Based Access Control)** do zarządzania uprawnieniami. RBAC w Azure działa inaczej niż IAM w AWS:
- **AWS IAM**: Polityki JSON przypisywane do grup/użytkowników
- **Azure RBAC**: Wbudowane role przypisywane do grup/użytkowników na określonym scope (subskrypcja, resource group, zasób)

### 6.2. Mapowanie typów zasobów na role RBAC

**Lokalizacja**: `identity/rbac_manager.py`, klasa `AzureRBACManager`, atrybut `RESOURCE_TYPE_ROLES`

```python
RESOURCE_TYPE_ROLES = {
    "vm": "Virtual Machine Contributor",
    "storage": "Storage Account Contributor",
    "network": "Network Contributor",
    "compute": "Virtual Machine Contributor",  # alias dla "vm"
}
```

**Wyjaśnienie**:
- `"vm"` → rola **"Virtual Machine Contributor"** - pozwala zarządzać maszynami wirtualnymi (tworzenie, usuwanie, modyfikacja)
- `"storage"` → rola **"Storage Account Contributor"** - pozwala zarządzać kontami magazynu
- `"network"` → rola **"Network Contributor"** - pozwala zarządzać zasobami sieciowymi (VNet, Network Interfaces, Public IPs, etc.)
- `"compute"` → rola **"Virtual Machine Contributor"** (alias dla "vm")

### 6.3. Proces przypisywania uprawnień

#### 6.3.1. W kodzie (`identity/rbac_manager.py`)

**Metoda**: `assign_role_to_group(resource_type, group_id, scope)`

**Kroki**:
1. **Walidacja typu zasobu**:
   ```python
   if resource_type not in self.RESOURCE_TYPE_ROLES:
       return False  # Nieznany typ zasobu
   ```

2. **Pobranie nazwy roli**:
   ```python
   role_name = self.RESOURCE_TYPE_ROLES[resource_type]
   # np. "vm" → "Virtual Machine Contributor"
   ```

3. **Wyszukanie definicji roli**:
   ```python
   role_definition_id = self._get_role_definition_id(role_name)
   # Wyszukuje w subskrypcji: /subscriptions/{subscription_id}
   # Używa filtru: roleName eq 'Virtual Machine Contributor'
   ```

4. **Określenie scope**:
   ```python
   if scope is None:
       scope = f"/subscriptions/{self._subscription_id}"
   # Domyślnie: poziom subskrypcji
   # Można zawęzić do resource group: /subscriptions/{id}/resourceGroups/{rg_name}
   ```

5. **Utworzenie przypisania roli**:
   ```python
   role_assignment_params = RoleAssignmentCreateParameters(
       role_definition_id=role_definition_id,
       principal_id=group_id,  # ObjectId grupy z Azure AD
       principal_type="Group",
   )
   ```

6. **Przypisanie z retry logic**:
   ```python
   for attempt in range(1, max_attempts + 1):
       try:
           self._auth_client.role_assignments.create(
               scope=scope,
               role_assignment_name=str(uuid.uuid4()),  # Unikalna nazwa
               parameters=role_assignment_params,
           )
           return True
       except Exception as e:
           if "PrincipalNotFound" in str(e) and attempt < max_attempts:
               # Opóźniona replikacja Azure AD - retry
               time.sleep(5.0)
               continue
           return False
   ```

#### 6.3.2. W Azure (przez Azure Portal/API)

**Co się dzieje w Azure**:
1. Azure RBAC tworzy **Role Assignment** w subskrypcji
2. Grupa Azure AD otrzymuje uprawnienia określone przez rolę
3. Wszyscy członkowie grupy dziedziczą uprawnienia

**Przykład**:
- Grupa: `AI-2024L` (ObjectId: `<AZURE_OBJECT_ID>`)
- Rola: `Virtual Machine Contributor` (RoleDefinitionId: `/subscriptions/<AZURE_SUBSCRIPTION_ID>/providers/Microsoft.Authorization/roleDefinitions/...`)
- Scope: `/subscriptions/<AZURE_SUBSCRIPTION_ID>`
- Rezultat: Wszyscy członkowie grupy `AI-2024L` mogą zarządzać maszynami wirtualnymi w całej subskrypcji

### 6.4. Uprawnienia dla poszczególnych typów zasobów

#### 6.4.1. VM (Virtual Machine)

**Rola**: `Virtual Machine Contributor`

**Uprawnienia** (wbudowane w rolę Azure):
- `Microsoft.Compute/virtualMachines/*` - pełne zarządzanie maszynami wirtualnymi
- `Microsoft.Network/networkInterfaces/*` - zarządzanie interfejsami sieciowymi
- `Microsoft.Storage/storageAccounts/*` - zarządzanie kontami magazynu (dla dysków VM)
- `Microsoft.Compute/disks/*` - zarządzanie dyskami

**Zakres**: Poziom subskrypcji (domyślnie) lub resource group

#### 6.4.2. Storage

**Rola**: `Storage Account Contributor`

**Uprawnienia**:
- `Microsoft.Storage/storageAccounts/*` - pełne zarządzanie kontami magazynu
- `Microsoft.Storage/storageAccounts/blobServices/*` - zarządzanie blob storage
- `Microsoft.Storage/storageAccounts/fileServices/*` - zarządzanie file storage

**Zakres**: Poziom subskrypcji (domyślnie) lub resource group

#### 6.4.3. Network

**Rola**: `Network Contributor`

**Uprawnienia**:
- `Microsoft.Network/virtualNetworks/*` - zarządzanie sieciami wirtualnymi
- `Microsoft.Network/networkInterfaces/*` - zarządzanie interfejsami sieciowymi
- `Microsoft.Network/publicIPAddresses/*` - zarządzanie publicznymi adresami IP
- `Microsoft.Network/networkSecurityGroups/*` - zarządzanie grupami zabezpieczeń sieciowych
- `Microsoft.Network/loadBalancers/*` - zarządzanie load balancerami

**Zakres**: Poziom subskrypcji (domyślnie) lub resource group

### 6.5. Wywołanie przypisania uprawnień

**Przypadek 1: Podczas tworzenia grupy** (`CreateGroupWithLeaders`)
```python
# W handlers/identity_handlers.py, metoda create_group_with_leaders()
resource_type = resource_types[0]  # Używa pierwszego typu z listy
success = self.rbac_manager.assign_role_to_group(
    resource_type=resource_type,  # np. "vm"
    group_id=group_id,             # ObjectId grupy
)
```

**Przypadek 2: Ręczne przypisanie** (`AssignPolicies`)
```python
# W handlers/identity_handlers.py, metoda assign_policies()
for resource_type in resource_types:  # Może być wiele typów
    success = self.rbac_manager.assign_role_to_group(
        resource_type=resource_type,  # np. "vm", "storage"
        group_id=group["id"]
    )
```

### 6.6. Różnice w stosunku do AWS

| Aspekt | AWS IAM | Azure RBAC |
|--------|---------|------------|
| **Format uprawnień** | Polityki JSON (inline lub managed) | Wbudowane role (predefiniowane) |
| **Przypisanie** | Polityka → Grupa | Rola → Grupa na scope |
| **Scope** | Zawsze poziom konta AWS | Subskrypcja, Resource Group, lub zasób |
| **Elastyczność** | Pełna kontrola (custom policies) | Ograniczona (tylko wbudowane role) |
| **Implementacja w adapterze** | JSON files w `config/policies/` | Mapowanie w `RESOURCE_TYPE_ROLES` |

---

## 7. Porównanie z adapterem AWS

### 7.1. Architektura

| Aspekt | Azure Adapter | AWS Adapter |
|--------|---------------|-------------|
| **Struktura** | Modułowa z handlerami | Monolityczna z menedżerami |
| **Wzorzec** | Handler Pattern (delegacja) | Direct Implementation |
| **Organizacja** | `handlers/`, `identity/`, `clean_resources/`, `cost_monitoring/` | `iam/`, `cost/`, `resources/`, `config/` |

**Azure**: Bardziej modularny, łatwiejszy w utrzymaniu dzięki wyraźnemu podziałowi odpowiedzialności.

### 7.2. Zarządzanie tożsamościami

| Funkcjonalność | Azure | AWS |
|----------------|-------|-----|
| **API** | Microsoft Graph API | AWS IAM API |
| **Biblioteka** | `msgraph-core` | `boto3` (IAM client) |
| **Grupy** | Azure AD Security Groups | IAM Groups |
| **Użytkownicy** | Azure AD Users | IAM Users |
| **Normalizacja nazw** | `normalize_name()` (spaces → dashes) | `normalize_name()` (spaces → dashes) |
| **Username format** | `{login}-{normalized_group}` | `{login}-{normalized_group}` |

**Różnice**:
- Azure używa Microsoft Graph API (REST), AWS używa boto3 (SDK)
- Azure AD ma opóźnioną replikację (wymaga retry logic), AWS IAM jest natychmiastowy
- Azure AD używa ObjectId (GUID), AWS używa nazw

### 7.3. Zarządzanie uprawnieniami

| Aspekt | Azure RBAC | AWS IAM |
|--------|------------|--------|
| **Mechanizm** | Wbudowane role przypisywane do grup | Polityki JSON przypisywane do grup |
| **Lokalizacja definicji** | `identity/rbac_manager.py` (`RESOURCE_TYPE_ROLES`) | `config/policies/*.json` (pliki JSON) |
| **Przypisanie** | `assign_role_to_group()` | `assign_policies_to_target()` |
| **Scope** | Subskrypcja/Resource Group | Zawsze poziom konta |
| **Elastyczność** | Ograniczona (tylko wbudowane role) | Pełna (custom policies) |

**Przykład mapowania**:

**Azure**:
```python
RESOURCE_TYPE_ROLES = {
    "vm": "Virtual Machine Contributor",
    "storage": "Storage Account Contributor",
}
```

**AWS**:
```json
// config/policies/student_ec2_policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ec2:RunInstances",
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1"
        }
      }
    }
  ]
}
```

**Różnice**:
- Azure: Wbudowane role (mniej elastyczne, ale bezpieczniejsze)
- AWS: Custom policies (bardziej elastyczne, ale wymagają zarządzania JSON)

### 7.4. Monitorowanie kosztów

| Aspekt | Azure | AWS |
|--------|-------|-----|
| **API** | Azure Cost Management API | AWS Cost Explorer API |
| **Biblioteka** | `azure-mgmt-costmanagement` | `boto3` (ce client) |
| **Filtrowanie** | Po tagu `Group` | Po tagu `Group` |
| **Funkcje** | `get_total_cost_for_group()`, `get_group_cost_with_service_breakdown()`, etc. | `get_total_cost_for_group()`, `get_group_cost_with_service_breakdown()`, etc. |

**Podobieństwa**: 

### 7.5. Zarządzanie zasobami

| Aspekt | Azure | AWS |
|--------|-------|-----|
| **Wyszukiwanie** | `ResourceManagementClient.resources.list()` + filtrowanie po tagach | AWS Resource Groups Tagging API |
| **Usuwanie** | Specjalizowane klienty (`ComputeManagementClient`, `NetworkManagementClient`, etc.) | `boto3` clients per service |
| **Tagowanie** | Tag `Group` na zasobach | Tag `Group` na zasobach |
| **Auto-tagging** | Niezaimplementowane | Lambda function dla auto-tagging (CloudTrail events) |

**Różnice**:
- Azure: Wymaga ręcznego tagowania zasobów (lub użycia Azure Policy)
- AWS: Ma automatyczne tagowanie przez Lambda function (reaguje na CloudTrail events)


### 7.6. Obsługa błędów i retry logic

| Aspekt | Azure | AWS |
|--------|-------|-----|
| **Replikacja katalogu** | Opóźniona (wymaga retry) | Natychmiastowa |
| **Retry w `add_member`** | Tak (5 prób, 3s opóźnienie) | Nie (nie wymagane) |
| **Retry w `assign_role`** | Tak (5 prób, 5s opóźnienie) | Nie (nie wymagane) |
| **Obsługa `PrincipalNotFound`** | Tak (retry logic) | Nie występuje |

**Azure**: Wymaga bardziej zaawansowanej obsługi błędów ze względu na opóźnioną replikację Azure AD.

### 7.8. Health Check

| Aspekt | Azure | AWS |
|--------|-------|-----|
| **Implementacja** | Sprawdza inicjalizację komponentów i dostępność klientów | Sprawdza globalny flag `AWS_ONLINE` |
| **Szczegółowość** | Weryfikuje każdy komponent osobno | Binarny (online/offline) |
| **Lokalizacja** | `handlers/identity_handlers.py::get_status()` | `main.py::GetStatus()` |

**Azure**: Bardziej szczegółowy health check, łatwiejszy w debugowaniu.

## 8. Deployment i środowisko produkcyjne

### 8.1. Wymagania systemowe

- **Python**: 3.11+
- **Docker**: Dla deploymentu kontenerowego
- **Azure Subscription**: Aktywna subskrypcja z odpowiednimi uprawnieniami
- **Service Principal**: Aplikacja Azure AD z wymaganymi uprawnieniami

### 8.2. Wymagane uprawnienia Service Principal

Service Principal (aplikacja Azure AD) musi mieć następujące uprawnienia:

**Microsoft Graph API**:
- `User.ReadWrite.All` - zarządzanie użytkownikami
- `Group.ReadWrite.All` - zarządzanie grupami
- `Directory.ReadWrite.All` - pełny dostęp do katalogu (opcjonalne, do czytania)

**Azure RBAC** (na poziomie subskrypcji):
- `User Access Administrator` lub `Owner` - dla przypisywania ról RBAC
- `Cost Management Reader` - dla zapytań kosztowych (opcjonalne)

**Azure Resource Manager**:
- `Contributor` na poziomie subskrypcji - dla zarządzania zasobami i tagowania

### 8.3. Konfiguracja zmiennych środowiskowych

Wszystkie zmienne muszą być ustawione przed uruchomieniem:

```bash
AZURE_TENANT_ID=<AZURE_TENANT_ID>
AZURE_CLIENT_ID=<AZURE_CLIENT_ID>
AZURE_CLIENT_SECRET=<AZURE_CLIENT_SECRET>
AZURE_SUBSCRIPTION_ID=<AZURE_SUBSCRIPTION_ID>
AZURE_UDOMAIN=<AZURE_TENANT_DOMAIN>
```

**Walidacja**: `validate_config()` jest wywoływana przy starcie - brakujące zmienne powodują błąd startu.

### 8.4. Uruchomienie lokalne

**Bez Docker**:
```bash
pip install -r requirements.txt
export AZURE_TENANT_ID=...
# ... ustaw pozostałe zmienne
python main.py
```

**Z Docker Compose**:
```bash
# Utwórz plik .env z zmiennymi środowiskowymi
docker-compose up
```

### 8.5. Uruchomienie produkcyjne

**Z obrazu Docker (GHCR)**:
```bash
docker pull ghcr.io/<OWNER>/uc-adapter-azure:latest
docker run -d \
  -p <GRPC_PORT>:<GRPC_PORT> \
  -e AZURE_TENANT_ID=<AZURE_TENANT_ID> \
  -e AZURE_CLIENT_ID=<AZURE_CLIENT_ID> \
  -e AZURE_CLIENT_SECRET=<AZURE_CLIENT_SECRET> \
  -e AZURE_SUBSCRIPTION_ID=<AZURE_SUBSCRIPTION_ID> \
  -e AZURE_UDOMAIN=<AZURE_TENANT_DOMAIN> \
  --name uc-adapter-azure \
  --restart unless-stopped \
  ghcr.io/<OWNER>/uc-adapter-azure:latest
```

**Health Check**: Kontener automatycznie sprawdza health przez `GetStatus` endpoint.

### 8.6. Monitorowanie

- **Logi**: Wszystkie logi są wyświetlane na stdout (konfiguracja w `main.py`)
- **Health Check**: Endpoint `GetStatus` zwraca stan komponentów
- **Docker Health Check**: Automatyczny health check co 30s (konfiguracja w `docker-compose.yml`)

### 8.7. Bezpieczeństwo

- **Credentials**: Nigdy nie są hardkodowane - zawsze ze zmiennych środowiskowych
- **Non-root user**: Kontener uruchamiany jako non-root (`adapteruser`)
- **HTTPS enforcement**: Wszystkie połączenia do Azure wymuszają HTTPS
- **Scope validation**: Wszystkie scope są walidowane przed użyciem

---

## 9. Ograniczenia i znane problemy

### 9.1. Ograniczenia implementacji

1. **Subscription-Scope RBAC**: Role przypisywane tylko na poziomie subskrypcji (nie resource group)
2. **Tag-based Discovery**: Resource cleanup wymaga tagu `Group` na zasobach
3. **Cost Query Latency**: Azure Cost Management API może mieć opóźnienie do 48h
4. **Eventual Consistency**: Azure AD replikacja może trwać do kilku sekund (obsługiwane przez retry)
5. **Single Resource Type per Group**: `CreateGroupWithLeaders` używa tylko pierwszego typu z listy

### 9.2. Znane problemy

- **PrincipalNotFound**: Może wystąpić podczas przypisywania ról zaraz po utworzeniu grupy (obsługiwane przez retry logic)
- **Cost API delays**: Dane kosztowe mogą nie być dostępne od razu po utworzeniu zasobu
- **Resource tagging**: Wymaga ręcznego tagowania lub Azure Policy (nie automatyczne)

### 9.3. Best practices

1. **Retry logic**: Wszystkie operacje na Azure AD mają retry logic dla eventual consistency
2. **Idempotentność**: Wszystkie operacje są idempotentne - bezpieczne wielokrotne wywołanie
3. **Error handling**: Błędy są logowane z pełnym stack trace dla debugowania
4. **Normalizacja nazw**: Wszystkie nazwy są normalizowane dla kompatybilności z AWS adapterem

---

## 10. Instrukcja konfiguracji Azure/Entra ID (zastępuje PDF)

### Cel
Celem jest przygotowanie tożsamości aplikacji (Service Principal) w Microsoft Entra ID oraz nadanie jej:
1) uprawnień Microsoft Graph (na poziomie Entra ID),
2) ról RBAC na poziomie subskrypcji Azure (dostęp do zasobów i kosztów).

### Wymagania wstępne
- Dostęp do Azure Portal oraz Microsoft Entra ID.
- Uprawnienia pozwalające na:
  - tworzenie rejestracji aplikacji w Entra ID,
  - nadawanie uprawnień API i wykonanie „Grant admin consent",
  - przypisywanie ról RBAC na poziomie subskrypcji.

### Krok 1 — Rejestracja aplikacji w Microsoft Entra ID (App registration)
1. Azure Portal → **Microsoft Entra ID**.
2. **App registrations** → **New registration**.
3. Ustaw:
   - **Name**: `<APP_REGISTRATION_NAME>` (rekomendowane: `uc-adapter-azure`),
   - **Supported account types**: single-tenant,
   - **Redirect URI**: puste (jeśli brak logowania interaktywnego).
4. **Register**.

Zanotuj:
- **Application (client) ID** → `<AZURE_CLIENT_ID>`
- **Directory (tenant) ID** → `<AZURE_TENANT_ID>`

### Krok 2 — Utworzenie Client Secret
1. Aplikacja → **Certificates & secrets** → **New client secret**.
2. Ustaw opis i datę wygaśnięcia zgodnie z polityką projektu.
3. Skopiuj natychmiast pole **Value** i zapisz jako `<AZURE_CLIENT_SECRET>`.

Uwaga: **Secret ID nie jest hasłem** — adapter wykorzystuje wyłącznie wartość **Value**.
Nie commituj sekretu do repozytorium; przechowuj go w bezpiecznym magazynie sekretów.

### Krok 3 — Microsoft Graph: API permissions (Application permissions)
1. Aplikacja → **API permissions** → **Add a permission** → **Microsoft Graph**.
2. Wybierz **Application permissions**.
3. Dodaj:
   - `User.ReadWrite.All`
   - `Group.ReadWrite.All`
4. Wykonaj **Grant admin consent** dla tenant.

Uwaga: w środowiskach least-privilege zweryfikuj, czy adapter faktycznie wymaga *ReadWrite*.

### Krok 4 — Azure RBAC: Role assignments na subskrypcji
1. Subskrypcja `<AZURE_SUBSCRIPTION_ID>` → **Access control (IAM)**.
2. **Add role assignment** dla Service Principal `<APP_REGISTRATION_NAME>`.
3. Przypisz role:
   - `Contributor`
   - `Cost Management Reader`
4. Sprawdź przypisania ról na właściwym zakresie (scope).

Uwaga: dobór ról powinien wynikać z faktycznych operacji adaptera; stosuj zasadę minimalnych uprawnień.

### Krok 5 — Konfiguracja zmiennych środowiskowych adaptera
Co najmniej:
- `AZURE_TENANT_ID=<AZURE_TENANT_ID>`
- `AZURE_CLIENT_ID=<AZURE_CLIENT_ID>`
- `AZURE_CLIENT_SECRET=<AZURE_CLIENT_SECRET>`
- `AZURE_SUBSCRIPTION_ID=<AZURE_SUBSCRIPTION_ID>`
- `AZURE_UDOMAIN=<AZURE_TENANT_DOMAIN>`

### Checklista (gdy konfiguracja nie działa)
- Czy wykonano **Grant admin consent** dla Microsoft Graph?
- Czy użyto wartości **Value** dla secretu (a nie „Secret ID")?
- Czy RBAC przypisano na właściwym scope?
- Czy wartości pochodzą z tej samej rejestracji aplikacji?
- Czy `<AZURE_SUBSCRIPTION_ID>` wskazuje subskrypcję z poprawnie nadanymi rolami?

---

