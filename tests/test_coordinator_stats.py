"""Tests for the long-term-statistics writer in ``coordinator.py``.

The portal publishes a day with a partial value and completes it on a later
sync, so the writer must rewrite the fetched window rather than append to it.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.romande_energie import coordinator as coordinator_module
from custom_components.romande_energie.api import DailyPoint, RomandeEnergieApiClient
from custom_components.romande_energie.const import TZ
from custom_components.romande_energie.coordinator import RomandeEnergieCoordinator

STAT_ID = "romande_energie:CONTRACT_TEST_consumption"


class _FakeRecorder:
    """Stand-in for the recorder instance: runs the job inline."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)


@pytest.fixture
def stats_env(hass: HomeAssistant, config_entry, monkeypatch):
    """A coordinator with the recorder calls stubbed out.

    Yields ``(coordinator, captured)`` where ``captured`` collects every
    ``async_add_external_statistics`` call and lets a test seed the rows the
    period query returns.
    """
    config_entry.add_to_hass(hass)
    coordinator = RomandeEnergieCoordinator(
        hass, config_entry, AsyncMock(spec=RomandeEnergieApiClient)
    )
    captured: dict[str, Any] = {"calls": [], "rows": {}, "query": None}

    def fake_period(hass_arg, start, end, statistic_ids, period, units, types):
        captured["query"] = (start, end, statistic_ids, period, types)
        return captured["rows"]

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


async def test_empty_series_writes_nothing(stats_env) -> None:
    coordinator, captured = stats_env

    await coordinator._insert_statistics(STAT_ID, "Consumption", [])

    assert captured["calls"] == []


async def test_fresh_history_starts_the_sum_at_zero(stats_env) -> None:
    coordinator, captured = stats_env
    captured["rows"] = {}  # nothing stored before the window

    await coordinator._insert_statistics(STAT_ID, "Consumption", SERIES)

    metadata, points = captured["calls"][0]
    assert metadata["statistic_id"] == STAT_ID
    assert metadata["has_sum"] is True
    assert [p["sum"] for p in points] == [5.0, 11.0, 12.5]
    assert [p["state"] for p in points] == [5.0, 6.0, 1.5]
    assert [p["start"] for p in points] == [_midnight(p.day) for p in SERIES]


async def test_sum_continues_from_the_row_before_the_window(stats_env) -> None:
    coordinator, captured = stats_env
    captured["rows"] = {STAT_ID: [{"sum": 90.0}, {"sum": 100.0}]}  # last row wins

    await coordinator._insert_statistics(STAT_ID, "Consumption", SERIES)

    _metadata, points = captured["calls"][0]
    assert [p["sum"] for p in points] == [105.0, 111.0, 112.5]
    # The baseline is read strictly before the first day of the window.
    _start, end, statistic_ids, _period, _types = captured["query"]
    assert end == _midnight(date(2026, 7, 20))
    assert statistic_ids == {STAT_ID}


async def test_already_stored_days_are_rewritten_not_skipped(stats_env) -> None:
    """A day whose partial value was stored earlier is re-sent with the fix."""
    coordinator, captured = stats_env
    captured["rows"] = {STAT_ID: [{"sum": 100.0}]}
    corrected = [*SERIES[:2], DailyPoint(date(2026, 7, 22), 7.25)]

    await coordinator._insert_statistics(STAT_ID, "Consumption", corrected)

    _metadata, points = captured["calls"][0]
    assert len(points) == len(corrected)  # whole window re-sent
    assert points[-1]["state"] == 7.25
    assert points[-1]["sum"] == 118.25  # 100 + 5 + 6 + 7.25


async def test_missing_sum_in_baseline_row_restarts_from_zero(stats_env) -> None:
    coordinator, captured = stats_env
    captured["rows"] = {STAT_ID: [{"sum": None}]}

    await coordinator._insert_statistics(STAT_ID, "Consumption", SERIES)

    _metadata, points = captured["calls"][0]
    assert [p["sum"] for p in points] == [5.0, 11.0, 12.5]
