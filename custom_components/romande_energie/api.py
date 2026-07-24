"""Thin async client for the Romande Énergie customer-portal API.

All HTTP lives here so the config flow and the coordinator share one
implementation. Pure parsing helpers are also here so they can be reasoned
about (and tested) in isolation.

Auth model (verified live 2026-07-24):
  login -> token scope=otp_pending  (cannot read data)
  send-otp -> SMS
  validate-otp -> token scope=full_access + refresh token
  refresh -> new full_access token + rotated refresh token (no OTP)

The refresh token lives ~30 min, so the caller must refresh inside that
window to stay logged in without a new OTP.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import date, datetime
from typing import Any, NamedTuple

import aiohttp

from .const import (
    CONTRACTS_ENDPOINT,
    CURVE_ENDPOINT,
    CURVE_TYPE_CONSUMPTION,
    HTTP_TIMEOUT,
    LOGIN_ENDPOINT,
    REFRESH_ENDPOINT,
    SEND_OTP_ENDPOINT,
    VALIDATE_OTP_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class RomandeEnergieError(Exception):
    """Base error for the integration."""


class CannotConnect(RomandeEnergieError):
    """Network / transport failure talking to the API."""


class AuthError(RomandeEnergieError):
    """Authentication/authorization failure (bad credentials, or a token the
    server rejected — e.g. an otp_pending or expired access token). Note that
    ``RefreshError`` subclasses this, so order ``except`` clauses accordingly."""


class OtpError(RomandeEnergieError):
    """The OTP code was rejected or expired."""


class RefreshError(AuthError):
    """The refresh token is expired/invalid -> a fresh OTP login is required."""


class ApiError(RomandeEnergieError):
    """Unexpected non-200 answer from a data endpoint."""


# ---------------------------------------------------------------------------
# JWT helpers (payload only, signature never verified — we only read claims)
# ---------------------------------------------------------------------------
def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Return the JWT payload dict without verifying the signature."""
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(raw)
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError) as err:
        raise AuthError(f"Malformed access token: {err}") from err


def account_id_from_token(access_token: str) -> str:
    """Extract the account id (JWT claim ``user_account_id``)."""
    account_id = _decode_jwt_payload(access_token).get("user_account_id")
    if not account_id:
        raise AuthError("Token missing user_account_id claim")
    return account_id


def token_expiry(access_token: str) -> int:
    """Return the access-token expiry as epoch seconds (0 if absent)."""
    return int(_decode_jwt_payload(access_token).get("exp", 0))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class RomandeEnergieApiClient:
    """Stateless async wrapper around the portal endpoints."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _post(
        self,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        try:
            async with self._session.post(
                url, json=json_body, headers=headers, timeout=timeout
            ) as resp:
                body = await resp.text()
                return resp.status, body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"POST {url} failed: {err}") from err

    async def _get(self, url: str, *, token: str, params: dict[str, Any] | None = None) -> Any:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        try:
            async with self._session.get(
                url, params=params, headers=headers, timeout=timeout
            ) as resp:
                body = await resp.text()
                return resp.status, body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"GET {url} failed: {err}") from err

    @staticmethod
    def _json(body: str) -> Any:
        try:
            return json.loads(body)
        except json.JSONDecodeError as err:
            raise ApiError(f"Non-JSON response: {body[:200]}") from err

    @staticmethod
    def _require(data: Any, *keys: str, ctx: str) -> dict[str, Any]:
        """Validate a 200 body carries the expected keys (else typed ApiError)."""
        if not isinstance(data, dict) or any(k not in data for k in keys):
            raise ApiError(f"{ctx} response missing expected keys {keys}")
        return data

    # ---- Auth -------------------------------------------------------------
    async def login(self, username: str, password: str) -> dict[str, Any]:
        """Step 1: exchange credentials for an otp_pending token."""
        status, body = await self._post(
            LOGIN_ENDPOINT, json_body={"username": username, "password": password}
        )
        if status in (400, 401, 403):
            raise AuthError("Invalid credentials")
        if status != 200:
            raise ApiError(f"Login failed: HTTP {status}")
        return self._require(self._json(body), "access_token", ctx="login")

    async def send_otp(self, otp_pending_token: str) -> dict[str, Any]:
        """Step 2: trigger the SMS OTP."""
        status, body = await self._post(SEND_OTP_ENDPOINT, token=otp_pending_token)
        if status in (401, 403):
            raise AuthError("otp_pending token rejected by send-otp")
        if status != 200:
            raise ApiError(f"send-otp failed: HTTP {status}")
        return self._require(self._json(body), "otp_id", ctx="send-otp")

    async def validate_otp(
        self, otp_pending_token: str, otp_id: str, otp_code: str
    ) -> dict[str, Any]:
        """Step 3: validate the SMS code -> full_access + refresh tokens."""
        status, body = await self._post(
            VALIDATE_OTP_ENDPOINT,
            token=otp_pending_token,
            json_body={"otp_id": otp_id, "otp_code": otp_code},
        )
        if status in (400, 401, 403):
            raise OtpError("Invalid or expired OTP code")
        if status != 200:
            raise ApiError(f"validate-otp failed: HTTP {status}")
        return self._require(
            self._json(body), "access_token", "refresh_token", ctx="validate-otp"
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Rotate the session with the refresh token (no OTP)."""
        status, body = await self._post(
            REFRESH_ENDPOINT, json_body={"refresh": refresh_token}
        )
        if status in (400, 401, 403):
            raise RefreshError("Refresh token expired/invalid")
        if status != 200:
            raise ApiError(f"refresh failed: HTTP {status}")
        return self._require(
            self._json(body), "access_token", "refresh_token", ctx="refresh"
        )

    # ---- Data -------------------------------------------------------------
    async def get_contracts(self, access_token: str, account_id: str) -> list[dict[str, Any]]:
        url = CONTRACTS_ENDPOINT.format(account_id=account_id)
        status, body = await self._get(url, token=access_token)
        if status in (401, 403):
            raise AuthError("Access token rejected fetching contracts")
        if status != 200:
            raise ApiError(f"contracts fetch failed: HTTP {status}")
        data = self._json(body)
        if not isinstance(data, list):
            raise ApiError("Contracts payload is not a list")
        return data

    async def get_curves(
        self, access_token: str, contract_id: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """Return the raw curve list for the given ISO date range (granularity DAILY)."""
        url = CURVE_ENDPOINT.format(contract_id=contract_id)
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "granularity": "DAILY",
        }
        status, body = await self._get(url, token=access_token, params=params)
        if status in (401, 403):
            raise AuthError("Access token rejected fetching curves")
        if status != 200:
            raise ApiError(f"curves fetch failed: HTTP {status}")
        data = self._json(body)
        if not isinstance(data, list):
            raise ApiError("Curves payload is not a list")
        return data


# ---------------------------------------------------------------------------
# Pure parsing helpers for the curve payload
# ---------------------------------------------------------------------------
class DailyPoint(NamedTuple):
    """One day's reading. ``value`` is always a real float (never None)."""

    day: date
    value: float


def _first_block(curves_response: list[dict[str, Any]]) -> dict[str, Any] | None:
    return curves_response[0] if curves_response else None


def parse_daily_series(
    curves_response: list[dict[str, Any]], curve_type: str = CURVE_TYPE_CONSUMPTION
) -> list[DailyPoint]:
    """Return day-sorted ``DailyPoint``s for ``curve_type``, dropping null days.

    ``values[i]`` aligns with ``timestamps[i]``; values are strings, or null for
    days with no data yet. Values from multiple installations/curves of the same
    type are summed per day (household total). Parse problems are logged rather
    than silently swallowed so a portal format change is diagnosable.
    """
    block = _first_block(curves_response)
    if not block:
        return []

    timestamps: list[str] = block.get("timestamps") or []
    installations = block.get("installations") or []
    dedup: dict[date, float] = {}
    seen_values = False
    for installation in installations:
        for curve in installation.get("curves") or []:
            if curve.get("curve_type") != curve_type:
                continue
            values = curve.get("values") or []
            if len(values) != len(timestamps):
                _LOGGER.warning(
                    "%s curve length mismatch: %d timestamps vs %d values; "
                    "days may be misaligned",
                    curve_type,
                    len(timestamps),
                    len(values),
                )
            for ts, value in zip(timestamps, values):
                if value is None:
                    continue
                seen_values = True
                try:
                    day = datetime.fromisoformat(ts).date()
                    parsed = float(value)
                except (ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "Dropping unparseable %s point ts=%r value=%r: %s",
                        curve_type,
                        ts,
                        value,
                        err,
                    )
                    continue
                dedup[day] = dedup.get(day, 0.0) + parsed

    if seen_values and not dedup:
        # Non-null values were present but none parsed -> likely a format change.
        _LOGGER.warning(
            "No %s values could be parsed although the payload contained data; "
            "the portal response format may have changed",
            curve_type,
        )
    return [DailyPoint(day, value) for day, value in sorted(dedup.items())]


def latest_value(series: list[DailyPoint]) -> DailyPoint | None:
    """Return the most recent ``DailyPoint`` (series is day-sorted), or None."""
    return series[-1] if series else None
