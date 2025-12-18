# uc-adapter-azure/config/settings.py

import os
from dotenv import load_dotenv

load_dotenv()

# Wszystkie wartości MUSZĄ być pobierane ze zmiennych środowiskowych
# W Dockerze są przekazywane przez docker-compose.yml
# W lokalnym środowisku można użyć pliku .env

AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID")
AZURE_UDOMAIN = os.getenv("AZURE_UDOMAIN")

REQUIRED_VARS = [
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_UDOMAIN",
]


def validate_config() -> None:
    """
    Waliduje, czy wszystkie wymagane zmienne środowiskowe są ustawione.
    Powinno być wywoływane przy starcie aplikacji (w main.py).
    """
    missing = []
    for var_name in REQUIRED_VARS:
        value = os.getenv(var_name)
        if value is None or value.strip() == "":
            missing.append(var_name)
    
    if missing:
        raise RuntimeError(
            f"Brak wymaganych zmiennych środowiskowych: {', '.join(missing)}. "
            f"Upewnij się, że są ustawione w docker-compose.yml lub pliku .env"
        )
