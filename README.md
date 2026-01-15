# Azure Cloud Adapter

## Overview

Azure Cloud Adapter to serwis gRPC, który łączy backend UniCloud z platformą Microsoft Azure:
- zarządza użytkownikami i grupami w Microsoft Entra ID (Azure AD),
- przypisuje role RBAC dla grup (VM / storage / network),
- udostępnia metody do pobierania kosztów (Azure Cost Management),
- sprząta zasoby w oparciu o tag `Group`.

Jest odpowiednikiem `uc-adapter-aws`, ale dla Azure – backend widzi jeden, spójny interfejs gRPC, a różnice między chmurami są ukryte w adapterach.

## Jak wyglądają konta studenckie

- **Login w UniCloud**: np. `s123456`.
- **Nazwa grupy z backendu**: np. `Azure test 2025Z`.
- **Normalizacja nazwy grupy**:
  - `normalize_name("Azure test 2025Z")` → `Azure-test-2025Z`.
- **UPN w Entra ID**:
  - `full_username = f"{login}-{normalized_group}"`,
  - `upn = f"{full_username}@{AZURE_UDOMAIN}"`, np.  
    `s123456-Azure-test-2025Z@hornungbartekgmail.onmicrosoft.com`.

### Hasło początkowe (do zmiany przy 1. logowaniu)

Generator haseł w `identity/user_manager.py` działa tak:
- jeśli `group_name` jest podana:
  - `base = normalize_name(group_name)` (np. `Azure-test-2025Z`),
  - jeśli `len(base) < 6`, to `base += "Group"`,
  - hasło startowe: `f"{base}A1!"`.
- przykład: dla `group_name = "Azure test 2025Z"`  
  `base = "Azure-test-2025Z"` → hasło: **`Azure-test-2025ZA1!`**.

Przy tworzeniu użytkownika adapter ustawia:
- `passwordProfile.password = <tak wygenerowane hasło>`,
- `forceChangePasswordNextSignIn = True` – Entra wymusza zmianę hasła przy pierwszym logowaniu.

## Grupa Entra vs Resource Group w Azure

Ważne jest rozróżnienie dwóch typów „grup”:

- **Grupa Entra ID** – np. `Azure-test-2025Z`:
  - przechowuje użytkowników,
  - na niej lądują role RBAC (np. `Virtual Machine Contributor`).

- **Resource Group w Azure** – np. `rg-Azure-test-2025Z`:
  - kontener zasobów (VM, VNet, dyski, itp.),
  - adapter może ją **automatycznie utworzyć** przy `CreateGroupWithLeaders`,
  - dostaje tag `Group = Azure-test-2025Z`,
  - służy jako **fallback** przy sprzątaniu (można skasować całą RG, jeśli tagi nie są konsekwentnie ustawione).

Adapter znajduje zasoby **po tagu**:
- `clean_resources/ResourceFinder` szuka zasobów z `tags["Group"] == normalize_name(groupName)`,
- przeszukuje całą subskrypcję – zasoby mogą być w dowolnej Resource Group,
- jeżeli zasoby tworzone ręcznie (np. z portalu) **nie mają** tagu `Group`, to:
  - nie pojawią się w `GetGroupResourcesList` / `CleanupGroupResources`,
  - nadal można je usunąć poprzez skasowanie całej `rg-<group>` (fallback).

## Konfiguracja (env)

Najważniejsze zmienne środowiskowe:

| Variable              | Description                                   |
|-----------------------|-----------------------------------------------|
| `AZURE_TENANT_ID`     | Azure AD / Entra ID Tenant ID (GUID)        |
| `AZURE_CLIENT_ID`     | Application (Service Principal) Client ID   |
| `AZURE_CLIENT_SECRET` | Application Secret (Value, nie „Secret ID”) |
| `AZURE_SUBSCRIPTION_ID` | Azure Subscription ID (GUID)              |
| `AZURE_UDOMAIN`       | Domena UPN, np. `xxx.onmicrosoft.com`       |

Weryfikacja przy starcie:
- `config/settings.validate_config()` sprawdza obecność wszystkich powyższych,
- brak którejkolwiek powoduje błąd startu serwisu.

Wymagane uprawnienia dla Service Principal:
- **Microsoft Graph (Application)**:
  - `User.ReadWrite.All`,
  - `Group.ReadWrite.All`,
  - z **Grant admin consent** na tenant.
- **Azure RBAC (najprościej na poziomie subskrypcji)**:
  - `Contributor`,
  - opcjonalnie `Cost Management Reader` dla zapytań kosztowych.

Szczegółowa instrukcja konfiguracji jest w  
`[uc-adapter-azure/Opisowa_dokumentacja.md](Opisowa_dokumentacja.md)` (sekcja o Entra / Azure RBAC).

## Architektura (skrót)

- `main.py` – serwer gRPC (`CloudAdapterServicer`) na porcie 50053,
- `handlers/` – implementacja metod gRPC:
  - `identity_handlers.py` – grupy, użytkownicy, RBAC,
  - `cost_handlers.py` – koszty z Azure Cost Management,
  - `resource_handlers.py` – lista zasobów, liczenie, cleanup.
- `identity/`:
  - `user_manager.py` – tworzenie użytkowników, hasła startowe, reset,
  - `group_manager.py` – grupy Entra + opcjonalne `rg-<group>` w Azure,
  - `rbac_manager.py` – przypisanie ról (`vm` → `Virtual Machine Contributor`, itd.),
  - `utils.py` – `normalize_name`, budowanie loginu z suffixem grupy.
- `clean_resources/`:
  - `resource_finder.py` – wyszukiwanie zasobów po tagu `Group`,
  - `resource_deleter.py` – usuwanie zasobów konkretnych typów.
- `cost_monitoring/limit_manager.py` – liczenie VMs / użytkowników, zapytania kosztowe.
- `azure_clients.py` – fabryka klientów Azure SDK i Graph (`ClientSecretCredential` + `@lru_cache`).

Szczegółowy opis modułów i endpointów gRPC znajduje się w  
`[Opisowa_dokumentacja.md](Opisowa_dokumentacja.md)`.

## Quick start

1. Ustaw zmienne środowiskowe (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_SUBSCRIPTION_ID`, `AZURE_UDOMAIN`).
2. Zainstaluj zależności:
   ```bash
   pip install -r requirements.txt
   ```
3. Uruchom adapter lokalnie:
   ```bash
   python main.py
   ```
   Serwer gRPC nasłuchuje na porcie `50053` (insecure – w produkcji zalecany reverse proxy / TLS).
4. Alternatywnie użyj Dockera:
   ```bash
   docker-compose up
   ```

Backend UniCloud łączy się przez gRPC (`CloudAdapter` z `protos/adapter_interface.proto`) i wywołuje m.in.:
- `CreateGroupWithLeaders`, `CreateUsersForGroup`, `RemoveGroup`, `AssignPolicies`,
- `GetTotalCostForGroup`, `GetTotalCostsForAllGroups`,
- `GetAvailableServices`, `GetResourceCount`, `CleanupGroupResources`.

## Testy

Podstawowe testy (wymagają prawdziwego połączenia z Azure i poprawnych envów):

```bash
python -m unittest discover tests
python tests/smoke_test.py
```

Szczegóły dot. scenariuszy testowych (teardown grup, RBAC, koszty) są opisane w  
`Opisowa_dokumentacja.md`.
