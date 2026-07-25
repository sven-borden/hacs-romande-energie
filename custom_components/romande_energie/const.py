"""Romande Énergie integration constants."""
from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

DOMAIN = "romande_energie"

# ---------------------------------------------------------------------------
# Config-entry keys
# ---------------------------------------------------------------------------
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_ACCOUNT_ID = "account_id"
CONF_CONTRACT_ID = "contract_id"
CONF_REFRESH_TOKEN = "refresh_token"

# ---------------------------------------------------------------------------
# API endpoints (verified against the live customer portal 2026-07-24)
# Base + every path uses a trailing slash.
# ---------------------------------------------------------------------------
BASE_URL = "https://api.espace-client.romande-energie.ch/v2"
LOGIN_ENDPOINT = f"{BASE_URL}/login/"
SEND_OTP_ENDPOINT = f"{BASE_URL}/login/send-otp/"
VALIDATE_OTP_ENDPOINT = f"{BASE_URL}/login/validate-otp/"
# NOTE: bare /refresh/, NOT /login/refresh/ (the latter is 404 for the customer portal).
REFRESH_ENDPOINT = f"{BASE_URL}/refresh/"
ACCOUNT_ENDPOINT = f"{BASE_URL}/accounts/{{account_id}}/"
CONTRACTS_ENDPOINT = f"{BASE_URL}/accounts/{{account_id}}/contracts-accounts/"
CURVE_ENDPOINT = f"{BASE_URL}/contracts-accounts/{{contract_id}}/curves/"

# ---------------------------------------------------------------------------
# Behaviour tuning
# ---------------------------------------------------------------------------
FETCH_DAYS = 30                             # Rolling window requested every poll.
TOKEN_EXP_MARGIN = 60                       # Seconds before access-token expiry we refresh.
# The refresh token lives ~30 min and the access token ~15 min. Each poll refreshes
# once the access token is within TOKEN_EXP_MARGIN of expiry, which rotates the
# refresh token too. UPDATE_INTERVAL must stay below BOTH the access-token TTL (so a
# refresh actually fires every cycle) and the ~30 min refresh-token TTL (so the
# refresh token never lapses between polls); otherwise the session dies and a fresh
# OTP login is required.
UPDATE_INTERVAL = timedelta(minutes=20)
HTTP_TIMEOUT = 30                           # Seconds per request.
# How far back the statistics writer looks for the cumulative-sum baseline that
# precedes the fetched window. Bounded to keep the query cheap; only an outage
# longer than this would hide the previous row and restart the sum from zero.
STAT_BASELINE_LOOKBACK = timedelta(days=400)

# Local time-zone for daily date boundaries and long-term-statistics timestamps.
TZ = ZoneInfo("Europe/Zurich")

# ---------------------------------------------------------------------------
# Curve payload constants
# ---------------------------------------------------------------------------
CURVE_TYPE_CONSUMPTION = "consumption"
CURVE_TYPE_SURPLUS = "surplus"
UNIT_KWH = "kWh"

# Long-term statistics ids are built per-contract in the coordinator
# ("<domain>:<contract_id>_consumption" / "_surplus") to avoid collisions
# between multiple configured accounts.
