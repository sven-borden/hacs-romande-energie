"""Tests for the coordinator's token handling and poll orchestration."""
from __future__ import annotations

import time
from datetime import date
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.romande_energie.api import (
    AuthError,
    CannotConnect,
    DailyPoint,
    RefreshError,
    RomandeEnergieApiClient,
)
from custom_components.romande_energie.const import CONF_REFRESH_TOKEN
from custom_components.romande_energie.coordinator import (
    RomandeEnergieCoordinator,
    RomandeEnergieData,
)

from .conftest import make_jwt


def _make_coordinator(hass, entry, client) -> RomandeEnergieCoordinator:
    """Register the entry and build a coordinator wired to ``client``."""
    entry.add_to_hass(hass)
    coordinator = RomandeEnergieCoordinator(hass, entry, client)
    # Defensive: keep the coordinator pointed at our entry regardless of how
    # the installed HA version initialises DataUpdateCoordinator.config_entry.
    coordinator.config_entry = entry
    return coordinator


@pytest.fixture
def client() -> AsyncMock:
    """An async mock standing in for the real API client."""
    return AsyncMock(spec=RomandeEnergieApiClient)


# ---------------------------------------------------------------------------
# _ensure_token
# ---------------------------------------------------------------------------
async def test_ensure_token_fast_path_skips_refresh(
    hass: HomeAssistant, config_entry, client
) -> None:
    coordinator = _make_coordinator(hass, config_entry, client)
    coordinator._access_token = "still-valid"
    coordinator._token_exp = int(time.time()) + 3600  # well beyond the margin

    await coordinator._ensure_token()

    client.refresh.assert_not_called()
    assert coordinator._access_token == "still-valid"


async def test_ensure_token_refreshes_and_persists_rotated_token(
    hass: HomeAssistant, config_entry, client
) -> None:
    coordinator = _make_coordinator(hass, config_entry, client)
    new_access = make_jwt("ACCT_TEST", exp=int(time.time()) + 3600)
    client.refresh.return_value = {
        "access_token": new_access,
        "refresh_token": "REFRESH_ROTATED",
    }

    await coordinator._ensure_token()

    client.refresh.assert_awaited_once_with("REFRESH_TEST")
    assert coordinator._access_token == new_access
    assert coordinator._refresh_token == "REFRESH_ROTATED"
    # The rotated refresh token is persisted back onto the config entry.
    assert config_entry.data[CONF_REFRESH_TOKEN] == "REFRESH_ROTATED"


async def test_ensure_token_refresh_error_raises_auth_failed(
    hass: HomeAssistant, config_entry, client
) -> None:
    coordinator = _make_coordinator(hass, config_entry, client)
    client.refresh.side_effect = RefreshError("refresh token dead")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._ensure_token()


# ---------------------------------------------------------------------------
# _async_update_data
# ---------------------------------------------------------------------------
async def test_update_auth_error_maps_to_auth_failed(
    hass: HomeAssistant, config_entry, client
) -> None:
    coordinator = _make_coordinator(hass, config_entry, client)
    coordinator._access_token = "still-valid"
    coordinator._token_exp = int(time.time()) + 3600
    client.get_curves.side_effect = AuthError("token rejected")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_update_cannot_connect_maps_to_update_failed(
    hass: HomeAssistant, config_entry, client
) -> None:
    coordinator = _make_coordinator(hass, config_entry, client)
    coordinator._access_token = "still-valid"
    coordinator._token_exp = int(time.time()) + 3600
    client.get_curves.side_effect = CannotConnect("network down")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_update_survives_statistics_failure(
    hass: HomeAssistant, config_entry, client, sample_curves
) -> None:
    coordinator = _make_coordinator(hass, config_entry, client)
    client.get_curves.return_value = sample_curves
    # Statistics are best-effort: a raising writer must not fail the update.
    coordinator._insert_statistics = AsyncMock(side_effect=RuntimeError("boom"))

    # Freeze "now" inside the sample month so the calendar-month totals are
    # deterministic (the fixture curves are dated June 2026).
    with freeze_time("2026-06-15 12:00:00"):
        coordinator._access_token = "still-valid"
        coordinator._token_exp = int(time.time()) + 3600
        data = await coordinator._async_update_data()

    assert isinstance(data, RomandeEnergieData)
    assert data.consumption is not None
    # June 4 is the newest day in the fixture but is still syncing, so the
    # daily sensors read the settled day behind it.
    assert data.consumption == DailyPoint(date(2026, 6, 3), 9.25)
    assert data.consumption_month_total == 42.75  # totals still count June 4
    assert data.surplus == DailyPoint(date(2026, 6, 3), 0.0)
    assert data.surplus_month_total == 6.75
    assert data.has_surplus is True


async def test_update_reports_surplus_before_any_day_has_settled(
    hass: HomeAssistant, config_entry, client, sample_curves
) -> None:
    """A single, still-syncing day leaves no settled value but is still surplus."""
    coordinator = _make_coordinator(hass, config_entry, client)
    one_day = [{**sample_curves[0], "timestamps": sample_curves[0]["timestamps"][:1]}]
    one_day[0]["installations"] = [
        {
            "installation_id": "INST_TEST",
            "curves": [
                {"curve_type": "consumption", "unit": "kWh", "values": ["10.5"]},
                {"curve_type": "surplus", "unit": "kWh", "values": ["2.0"]},
            ],
        }
    ]
    client.get_curves.return_value = one_day
    coordinator._insert_statistics = AsyncMock()

    with freeze_time("2026-06-15 12:00:00"):
        coordinator._access_token = "still-valid"
        coordinator._token_exp = int(time.time()) + 3600
        data = await coordinator._async_update_data()

    assert data.consumption is None
    assert data.surplus is None
    assert data.consumption_month_total == 10.5
    assert data.has_surplus is True
