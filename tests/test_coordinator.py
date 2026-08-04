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

from custom_components.romande_energie import coordinator as coordinator_module
from custom_components.romande_energie.api import (
    ApiError,
    AuthError,
    CannotConnect,
    DailyPoint,
    RefreshError,
    RomandeEnergieApiClient,
)
from custom_components.romande_energie.const import (
    CONF_REFRESH_TOKEN,
    POLL_RETRY_INTERVAL,
    REFRESH_ATTEMPTS,
    UPDATE_INTERVAL,
)
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


@pytest.fixture(autouse=True)
def no_refresh_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the wait between refresh attempts so retry tests stay instant."""
    monkeypatch.setattr(coordinator_module, "REFRESH_RETRY_DELAY", 0)


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

    # A rejected refresh token is dead: retrying only delays the reauth flow.
    assert client.refresh.await_count == 1


@pytest.mark.parametrize("error", [CannotConnect("network down"), ApiError("HTTP 502")])
async def test_ensure_token_retries_a_lost_refresh(
    hass: HomeAssistant, config_entry, client, error: Exception
) -> None:
    """One blip must not strand the refresh token until the next poll."""
    coordinator = _make_coordinator(hass, config_entry, client)
    new_access = make_jwt("ACCT_TEST", exp=int(time.time()) + 3600)
    client.refresh.side_effect = [
        error,
        {"access_token": new_access, "refresh_token": "REFRESH_ROTATED"},
    ]

    await coordinator._ensure_token()

    assert client.refresh.await_count == 2
    assert coordinator._access_token == new_access
    assert config_entry.data[CONF_REFRESH_TOKEN] == "REFRESH_ROTATED"


async def test_ensure_token_gives_up_after_the_attempt_budget(
    hass: HomeAssistant, config_entry, client
) -> None:
    """A lasting outage surfaces as UpdateFailed, not an endless retry loop."""
    coordinator = _make_coordinator(hass, config_entry, client)
    client.refresh.side_effect = CannotConnect("network down")

    with pytest.raises(CannotConnect):
        await coordinator._ensure_token()

    assert client.refresh.await_count == REFRESH_ATTEMPTS


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

    # Reauth stops the polling, so there is no point shortening the interval.
    assert coordinator.update_interval == UPDATE_INTERVAL


async def test_update_cannot_connect_maps_to_update_failed(
    hass: HomeAssistant, config_entry, client
) -> None:
    coordinator = _make_coordinator(hass, config_entry, client)
    coordinator._access_token = "still-valid"
    coordinator._token_exp = int(time.time()) + 3600
    client.get_curves.side_effect = CannotConnect("network down")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    # A failed poll leaves the refresh token un-rotated, so the next attempt has
    # to land well inside its ~30 min TTL rather than a whole interval later.
    assert coordinator.update_interval == POLL_RETRY_INTERVAL


async def test_successful_update_restores_the_poll_interval(
    hass: HomeAssistant, config_entry, client, sample_curves
) -> None:
    coordinator = _make_coordinator(hass, config_entry, client)
    coordinator.update_interval = POLL_RETRY_INTERVAL  # as a previous failure left it
    client.get_curves.return_value = sample_curves
    coordinator._insert_statistics = AsyncMock()

    with freeze_time("2026-06-05 12:00:00"):
        coordinator._access_token = "still-valid"
        coordinator._token_exp = int(time.time()) + 3600
        await coordinator._async_update_data()

    assert coordinator.update_interval == UPDATE_INTERVAL


async def test_update_survives_statistics_failure(
    hass: HomeAssistant, config_entry, client, sample_curves
) -> None:
    coordinator = _make_coordinator(hass, config_entry, client)
    client.get_curves.return_value = sample_curves
    # Statistics are best-effort: a raising writer must not fail the update.
    coordinator._insert_statistics = AsyncMock(side_effect=RuntimeError("boom"))

    # Freeze "now" the day after the fixture's newest parsed day, so the
    # calendar-month totals are deterministic and that day counts as unsettled.
    with freeze_time("2026-06-05 12:00:00"):
        coordinator._access_token = "still-valid"
        coordinator._token_exp = int(time.time()) + 3600
        data = await coordinator._async_update_data()

    assert isinstance(data, RomandeEnergieData)
    assert data.consumption is not None
    # Jun 5 is null in the fixture and dropped by the parser, making Jun 4 the
    # newest parsed day. Frozen "today" is Jun 5, so Jun 4 may still be syncing
    # and the daily sensors read the settled day behind it.
    assert data.consumption == DailyPoint(date(2026, 6, 3), 9.25)
    assert data.consumption_month_total == 42.75  # totals still count Jun 4
    assert data.surplus == DailyPoint(date(2026, 6, 3), 0.0)
    assert data.surplus_month_total == 6.75
    assert data.has_surplus is True


async def test_statistics_go_to_their_own_ids(
    hass: HomeAssistant, config_entry, client, sample_curves
) -> None:
    """Folding surplus into the consumption meter would double the dashboard."""
    coordinator = _make_coordinator(hass, config_entry, client)
    client.get_curves.return_value = sample_curves
    coordinator._insert_statistics = AsyncMock()

    with freeze_time("2026-06-05 12:00:00"):
        coordinator._access_token = "still-valid"
        coordinator._token_exp = int(time.time()) + 3600
        await coordinator._async_update_data()

    written = {call.args[0]: call.args[2] for call in coordinator._insert_statistics.await_args_list}
    assert set(written) == {
        coordinator._stat_id_consumption,
        coordinator._stat_id_surplus,
    }
    assert written[coordinator._stat_id_consumption][-1] == DailyPoint(
        date(2026, 6, 4), 12.0
    )
    assert written[coordinator._stat_id_surplus][-1] == DailyPoint(
        date(2026, 6, 4), 3.25
    )


async def test_settled_keeps_the_newest_day_when_the_portal_lags(
    hass: HomeAssistant, config_entry, client, sample_curves
) -> None:
    """A day the portal stopped advancing days ago is final, not partial."""
    coordinator = _make_coordinator(hass, config_entry, client)
    client.get_curves.return_value = sample_curves
    coordinator._insert_statistics = AsyncMock()

    # A week past the newest day in the fixture: later syncs have had every
    # chance to complete Jun 4, so dropping it would just lose a real reading.
    with freeze_time("2026-06-11 12:00:00"):
        coordinator._access_token = "still-valid"
        coordinator._token_exp = int(time.time()) + 3600
        data = await coordinator._async_update_data()

    assert data.consumption == DailyPoint(date(2026, 6, 4), 12.0)


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

    with freeze_time("2026-06-01 12:00:00"):  # that single day is today's
        coordinator._access_token = "still-valid"
        coordinator._token_exp = int(time.time()) + 3600
        data = await coordinator._async_update_data()

    assert data.consumption is None
    assert data.surplus is None
    assert data.consumption_month_total == 10.5
    assert data.has_surplus is True
