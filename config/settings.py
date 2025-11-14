# uc-adapter-azure/config/settings.py

import os
from dotenv import load_dotenv

load_dotenv()

AZURE_TENANT_ID ="a"
AZURE_CLIENT_ID ="b"
AZURE_CLIENT_SECRET ="c"
AZURE_SUBSCRIPTION_ID ="d"

AZURE_UDOMAIN ="hornungbartekgmail.onmicrosoft.com"

REQUIRED_VARS = [
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_UDOMAIN",
]



def validate_config() -> None:
    missing = [name for name in REQUIRED_VARS if os.getenv(name) is None]
    if missing:
        raise RuntimeError(
            f"Brak wymaganych zmiennych środowiskowych: {', '.join(missing)}"
        )
