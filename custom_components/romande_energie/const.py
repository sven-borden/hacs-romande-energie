"""Constants for the Romande Energie integration."""
from datetime import timedelta

DOMAIN = "romande_energie"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
MIN_SCAN_INTERVAL = timedelta(minutes=30)

# API endpoints
API_BASE_URL = "https://api.espace-client.romande-energie.ch"
API_LOGIN_URL = f"{API_BASE_URL}/api/login/"
API_SESSION_URL = f"{API_BASE_URL}/users/session/"
API_ACCOUNTS_URL = f"{API_BASE_URL}/accounts"
API_CONTRACTS_URL = f"{API_BASE_URL}/contracts"

# Default headers
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
}

# Sensor types
SENSOR_TYPE_DAILY_CONSUMPTION = "daily_consumption"
SENSOR_TYPE_MONTHLY_CONSUMPTION = "monthly_consumption"

SENSOR_TYPES = {
    SENSOR_TYPE_DAILY_CONSUMPTION: {
        "name": "Daily Consumption",
        "icon": "mdi:flash",
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
    SENSOR_TYPE_MONTHLY_CONSUMPTION: {
        "name": "Monthly Consumption",
        "icon": "mdi:flash",
        "unit": "kWh", 
        "device_class": "energy",
        "state_class": "total_increasing",
    },
}