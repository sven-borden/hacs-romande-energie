"""Romande Énergie integration constants."""
from zoneinfo import ZoneInfo

DOMAIN = "romande_energie"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_ACCOUNT_ID = "account_id"
CONF_CONTRACT_ID = "contract_id"

BASE_URL = "https://api.espace-client.romande-energie.ch/v2"
LOGIN_ENDPOINT = f"{BASE_URL}/login/"
CONTRACTS_ENDPOINT = f"{BASE_URL}/accounts/{{account_id}}/contracts-accounts/"
CURVE_ENDPOINT = f"{BASE_URL}/contracts-accounts/{{contract_id}}/curves/"

FETCH_DAYS = 30                 # Rolling window requested every day
TOKEN_EXP_MARGIN = 300          # Seconds before expiry when we refresh
TZ = ZoneInfo("Europe/Zurich")  # Local time‑zone for scheduling

ATTR_ENERGY = "energy"