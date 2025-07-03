"""Coordinator in charge of talking to Romande‑Énergie API."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp
import jwt
from dateutil import tz
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    LOGIN_ENDPOINT,
    CONTRACTS_ENDPOINT,
    CURVE_ENDPOINT,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_ACCOUNT_ID,
    CONF_CONTRACT_ID,
    FETCH_DAYS,
    TOKEN_EXP_MARGIN,
    TZ,
    ATTR_ENERGY,
)

_LOGGER = logging.getLogger(__name__)


class RomandeEnergieCoordinator(DataUpdateCoordinator[float]):
    """Handle authentication, token refresh, and daily energy retrieval."""

    def __init__(self, hass: HomeAssistant, conf: dict[str, Any], session: aiohttp.ClientSession) -> None:
        self.hass = hass
        self._session = session
        self._username: str = conf[CONF_USERNAME]
        self._password: str = conf[CONF_PASSWORD]
        self._contract_id: str = conf[CONF_CONTRACT_ID]
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_exp: int = 0  # epoch seconds

        super().__init__(
            hass,
            _LOGGER,
            name="Romande Énergie",
            update_interval=timedelta(days=1),  # actual timing set in __init__.py
        )

    # ---------------------------------------------------------------------
    # Public helpers used by platform(s)
    # ---------------------------------------------------------------------
    async def async_get_yesterday_kwh(self) -> float | None:
        """Return yesterday's kWh if available (else None)."""
        return self.data  # coordinator.data is yesterday's value

    # ---------------------------------------------------------------------
    # DataUpdateCoordinator hooks
    # ---------------------------------------------------------------------
    async def _async_update_data(self) -> float:
        """Fetch yesterday's consumption and return its kWh value."""
        await self._ensure_token()
        yesterday_value = await self._fetch_yesterday_kwh()
        if yesterday_value is None:
            raise UpdateFailed("No data returned for yesterday")
        return yesterday_value

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _login(self) -> None:
        """Authenticate and store tokens."""
        payload = {"username": self._username, "password": self._password}
        async with self._session.post(LOGIN_ENDPOINT, json=payload, timeout=20) as resp:
            if resp.status != 200:
                raise UpdateFailed(f"Login failed: HTTP {resp.status}")
            data = await resp.json()

        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        decoded = jwt.decode(self._access_token, options={"verify_signature": False})
        self._token_exp = decoded["exp"]
        self._account_id = decoded[CONF_ACCOUNT_ID]

    async def _ensure_token(self) -> None:
        if not self._access_token or (self._token_exp - datetime.now(tz=tz.UTC).timestamp() < TOKEN_EXP_MARGIN):
            await self._login()

    async def _fetch_yesterday_kwh(self) -> float | None:
        """Fetch last 30 days and return value for yesterday."""
        # Compute dates
        today = datetime.now(tz=TZ).date()
        start_date = (today - timedelta(days=FETCH_DAYS)).isoformat()
        end_date = today.isoformat()

        url = CURVE_ENDPOINT.format(contract_id=self._contract_id)
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "granularity": "DAILY",
        }
        headers = {"Authorization": f"Bearer {self._access_token}"}

        async with self._session.get(url, params=params, headers=headers, timeout=20) as resp:
            if resp.status != 200:
                raise UpdateFailed(f"Curve fetch failed: HTTP {resp.status}")
            curves = await resp.json()

        target_date = (today - timedelta(days=1)).isoformat()
        for item in curves:
            # Field names are inferred; adapt if API differs.
            if item.get("date") == target_date:
                return float(item.get("value"))  # kWh assumed in "value"
        _LOGGER.debug("Yesterday (%s) not found in curve response", target_date)
        return None