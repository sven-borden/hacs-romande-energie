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
# A failed poll does not rotate the refresh token, so waiting a whole
# UPDATE_INTERVAL before trying again leaves a 40 min gap that outlives the ~30 min
# refresh-token TTL — one network blip would then cost the user an SMS. The
# coordinator falls back to this interval until a poll succeeds; two consecutive
# retries still fit inside the TTL.
POLL_RETRY_INTERVAL = timedelta(minutes=3)
# A refresh that fails on transport (or a portal 5xx) is retried inside the same
# poll, for the same reason: the refresh token is ageing while we wait.
REFRESH_ATTEMPTS = 3
REFRESH_RETRY_DELAY = 5                     # Seconds between refresh attempts.
HTTP_TIMEOUT = 30                           # Seconds per request.

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
