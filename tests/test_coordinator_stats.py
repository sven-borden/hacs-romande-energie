"""Tests for the long-term-statistics writer in ``coordinator.py``.

The portal publishes a day with a partial value and completes it on a later
sync, so the writer must re-send the fetched window rather than append to it —
without ever letting the stored cumulative sum go backwards, which the Energy
dashboard would read as a meter reset.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.recorder.statistics import valid_statistic_id
from homeassistant.core import HomeAssistant

from custom_components.romande_energie import coordinator as coordinator_module
from custom_components.romande_energie.api import DailyPoint, RomandeEnergieApiClient
from custom_components.romande_energie.const import CONF_CONTRACT_ID, TZ
from custom_components.romande_energie.coordinator import (
    EPOCH,
    RomandeEnergieCoordinator,
)

from .conftest import build_config_entry

STAT_ID = "romande_energie:contract_test_consumption"


class _FakeRecorder:
    """Stand-in for the recorder instance: runs the job inline."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)


@pytest.fixture
def stats_env(hass: HomeAssistant, config_entry, monkeypatch):
    """A coordinator with the recorder calls stubbed out.

    Yields ``(coordinator, captured)``. ``captured["responses"]`` is the queue
    of results the period query returns, one per call, so a test can answer the
    narrow probe and the wide fallback differently. ``captured["calls"]``
    collects every ``async_add_external_statistics`` call and
    ``captured["queries"]`` every period query.
    """
    config_entry.add_to_hass(hass)
    coordinator = RomandeEnergieCoordinator(
        hass, config_entry, AsyncMock(spec=RomandeEnergieApiClient)
    )
    captured: dict[str, Any] = {"calls": [], "queries": [], "responses": []}

    def fake_period(hass_arg, start, end, *, statistic_ids, period, units, types):
        captured["queries"].append(
            {
                "start": start,
                "end": end,
                "statistic_ids": statistic_ids,
                "period": period,
                "types": types,
            }
        )
        if not captured["responses"]:
            return {}
        return captured["responses"].pop(0)

    monkeypatch.setattr(coordinator_module, "get_instance", lambda _hass: _FakeRecorder())
    monkeypatch.setattr(coordinator_module, "statistics_during_period", fake_period)
    monkeypatch.setattr(
        coordinator_module,
        "async_add_external_statistics",
        lambda _hass, metadata, points: captured["calls"].append((metadata, points)),
    )
    return coordinator, captured


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=TZ)


SERIES = [
    DailyPoint(date(2026, 7, 20), 5.0),
    DailyPoint(date(2026, 7, 21), 6.0),
    DailyPoint(date(2026, 7, 22), 1.5),  # still partial; a later sync completes it
]


# ---------------------------------------------------------------------------
# Statistic ids
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "contract_id", ["200123456", "CONTRACT_TEST", "CH-1234-5678", "9f8e7d6c-1234-4abc"]
)
async def test_statistic_ids_are_valid_for_any_contract_id(
    hass: HomeAssistant, contract_id: str
) -> None:
    """Uppercase and hyphens are legal in a contract id but not in a statistic id.

    Without slugifying, every write would raise HomeAssistantError and be
    swallowed by the best-effort handler, leaving the Energy dashboard
    permanently empty with only a log line to show for it.
    """
    entry = build_config_entry(data={CONF_CONTRACT_ID: contract_id})
    entry.add_to_hass(hass)
    coordinator = RomandeEnergieCoordinator(
        hass, entry, AsyncMock(spec=RomandeEnergieApiClient)
    )

    assert valid_statistic_id(coordinator._stat_id_consumption)
    assert valid_statistic_id(coordinator._stat_id_surplus)


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------
async def test_empty_series_writes_nothing(stats_env) -> None:
    coordinator, captured = stats_env

    await coordinator._insert_statistics(STAT_ID, "Consumption", [])

    assert captured["calls"] == []


async def test_fresh_history_starts_the_sum_at_zero(stats_env) -> None:
    coordinator, captured = stats_env
    captured["responses"] = [{}, {}]  # nothing stored, anywhere

    await coordinator._insert_statistics(STAT_ID, "Consumption", SERIES)

    metadata, points = captured["calls"][0]
    assert metadata["statistic_id"] == STAT_ID
    assert metadata["has_sum"] is True
    assert metadata["has_mean"] is False
    assert metadata["source"] == "romande_energie"
    assert metadata["unit_of_measurement"] == "kWh"
    assert [p["sum"] for p in points] == [5.0, 11.0, 12.5]
    assert [p["state"] for p in points] == [5.0, 6.0, 1.5]
    assert [p["start"] for p in points] == [_midnight(p.day) for p in SERIES]


async def test_sum_continues_from_the_row_before_the_window(stats_env) -> None:
    coordinator, captured = stats_env
    captured["responses"] = [{STAT_ID: [{"sum": 90.0}, {"sum": 100.0}]}]  # last row wins

    await coordinator._insert_statistics(STAT_ID, "Consumption", SERIES)

    _metadata, points = captured["calls"][0]
    assert [p["sum"] for p in points] == [105.0, 111.0, 112.5]
    # One query only: the day before the window answered it.
    assert len(captured["queries"]) == 1
    probe = captured["queries"][0]
    assert probe["end"] == _midnight(date(2026, 7, 20))  # exclusive: excludes day 1
    assert probe["start"] == _midnight(date(2026, 7, 19))
    assert probe["statistic_ids"] == {STAT_ID}
    # "day"/"week"/"month" realign end_time forward, which would fold the
    # window's own first row into its baseline.
    assert probe["period"] == "hour"


async def test_missing_probe_day_falls_back_to_the_whole_history(stats_env) -> None:
    """An outage leaves no row immediately before the window; older ones remain."""
    coordinator, captured = stats_env
    captured["responses"] = [{}, {STAT_ID: [{"sum": 100.0}]}]

    await coordinator._insert_statistics(STAT_ID, "Consumption", SERIES)

    _metadata, points = captured["calls"][0]
    assert [p["sum"] for p in points] == [105.0, 111.0, 112.5]
    assert captured["queries"][1]["start"] == EPOCH
    assert captured["queries"][1]["end"] == _midnight(date(2026, 7, 20))


async def test_unreadable_baseline_sum_writes_nothing(stats_env, caplog) -> None:
    """Better no statistics than a window rewritten below the history it continues."""
    coordinator, captured = stats_env
    captured["responses"] = [{STAT_ID: [{"sum": None}]}]

    await coordinator._insert_statistics(STAT_ID, "Consumption", SERIES)

    assert captured["calls"] == []
    assert "carries no sum" in caplog.text


# ---------------------------------------------------------------------------
# The rewrite itself
# ---------------------------------------------------------------------------
async def test_already_stored_days_are_rewritten_not_skipped(stats_env) -> None:
    """A day whose partial value was stored earlier is re-sent with the fix."""
    coordinator, captured = stats_env
    captured["responses"] = [{STAT_ID: [{"sum": 100.0}]}]
    corrected = [*SERIES[:2], DailyPoint(date(2026, 7, 22), 7.25)]

    await coordinator._insert_statistics(STAT_ID, "Consumption", corrected)

    _metadata, points = captured["calls"][0]
    assert len(points) == len(corrected)  # whole window re-sent
    assert points[-1]["state"] == 7.25
    assert points[-1]["sum"] == 118.25  # 100 + 5 + 6 + 7.25


async def test_days_missing_from_the_payload_are_written_as_zero(stats_env) -> None:
    """Gaps keep the stored sums monotonic.

    The parser drops days the portal returns as null. Skipping them here would
    leave a day written by an earlier poll holding a sum that includes its
    value while the days after it are rewritten without it — a backwards step
    the Energy dashboard reads as a meter reset.
    """
    coordinator, captured = stats_env
    captured["responses"] = [{STAT_ID: [{"sum": 100.0}]}]
    holed = [DailyPoint(date(2026, 7, 20), 5.0), DailyPoint(date(2026, 7, 23), 4.0)]

    await coordinator._insert_statistics(STAT_ID, "Consumption", holed)

    _metadata, points = captured["calls"][0]
    assert [p["start"].date() for p in points] == [
        date(2026, 7, 20),
        date(2026, 7, 21),
        date(2026, 7, 22),
        date(2026, 7, 23),
    ]
    assert [p["state"] for p in points] == [5.0, 0.0, 0.0, 4.0]
    sums = [p["sum"] for p in points]
    assert sums == sorted(sums)  # never steps backwards
    assert sums[-1] == 109.0


async def test_unchanged_window_is_not_rewritten(stats_env) -> None:
    """We poll every 20 minutes; the portal publishes once a day."""
    coordinator, captured = stats_env
    captured["responses"] = [{STAT_ID: [{"sum": 100.0}]}]

    await coordinator._insert_statistics(STAT_ID, "Consumption", SERIES)
    await coordinator._insert_statistics(STAT_ID, "Consumption", list(SERIES))

    assert len(captured["calls"]) == 1
    assert len(captured["queries"]) == 1  # the second poll queried nothing either


async def test_changed_window_is_rewritten(stats_env) -> None:
    coordinator, captured = stats_env
    captured["responses"] = [
        {STAT_ID: [{"sum": 100.0}]},
        {STAT_ID: [{"sum": 100.0}]},
    ]

    await coordinator._insert_statistics(STAT_ID, "Consumption", SERIES)
    await coordinator._insert_statistics(
        STAT_ID, "Consumption", [*SERIES[:2], DailyPoint(date(2026, 7, 22), 7.25)]
    )

    assert len(captured["calls"]) == 2
    assert captured["calls"][1][1][-1]["state"] == 7.25


# ---------------------------------------------------------------------------
# Against the real recorder
# ---------------------------------------------------------------------------
@pytest.mark.recorder
async def test_rewrite_updates_stored_rows_in_place(
    hass: HomeAssistant, config_entry
) -> None:
    """The premise the whole design rests on, checked against HA itself.

    Re-sending a day must update its row rather than duplicate it, and the
    corrected value must land — via the real recorder, not a stub.
    """
    from homeassistant.components.recorder.statistics import statistics_during_period
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    config_entry.add_to_hass(hass)
    coordinator = RomandeEnergieCoordinator(
        hass, config_entry, AsyncMock(spec=RomandeEnergieApiClient)
    )
    stat_id = coordinator._stat_id_consumption

    await coordinator._insert_statistics(stat_id, "Consumption", SERIES)
    await async_wait_recording_done(hass)

    # Same window, last day completed by the portal's next sync.
    corrected = [*SERIES[:2], DailyPoint(date(2026, 7, 22), 7.25)]
    await coordinator._insert_statistics(stat_id, "Consumption", corrected)
    await async_wait_recording_done(hass)

    stored = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        _midnight(date(2026, 7, 1)),
        _midnight(date(2026, 8, 1)),
        {stat_id},
        "hour",
        None,
        {"state", "sum"},
    )
    rows = stored[stat_id]
    assert len(rows) == len(SERIES)  # updated in place, not appended
    assert [row["state"] for row in rows] == [5.0, 6.0, 7.25]
    assert [row["sum"] for row in rows] == [5.0, 11.0, 18.25]

    # And a later window continues from what is stored rather than restarting.
    later = [DailyPoint(date(2026, 7, 23), 2.0)]
    await coordinator._insert_statistics(stat_id, "Consumption", later)
    await async_wait_recording_done(hass)

    stored = await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        _midnight(date(2026, 7, 23)),
        _midnight(date(2026, 7, 24)),
        {stat_id},
        "hour",
        None,
        {"sum"},
    )
    assert stored[stat_id][0]["sum"] == 20.25


@pytest.mark.recorder
async def test_baseline_survives_a_gap_longer_than_the_probe(
    hass: HomeAssistant, config_entry
) -> None:
    """A window starting well after the stored history still continues its sum."""
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    config_entry.add_to_hass(hass)
    coordinator = RomandeEnergieCoordinator(
        hass, config_entry, AsyncMock(spec=RomandeEnergieApiClient)
    )
    stat_id = coordinator._stat_id_consumption

    await coordinator._insert_statistics(stat_id, "Consumption", SERIES)
    await async_wait_recording_done(hass)

    # Two months later — nothing sits in the day before this window.
    resumed = [DailyPoint(date(2026, 9, 20), 3.0)]
    await coordinator._insert_statistics(stat_id, "Consumption", resumed)
    await async_wait_recording_done(hass)

    baseline = await coordinator._sum_before(
        stat_id, _midnight(date(2026, 9, 20)) + timedelta(days=1)
    )
    assert baseline == 15.5  # 5 + 6 + 1.5 + 3, not restarted from zero
