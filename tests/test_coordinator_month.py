"""Tests for ``_calendar_month_total`` in ``coordinator.py``."""
from __future__ import annotations

from datetime import date

from custom_components.romande_energie.api import DailyPoint
from custom_components.romande_energie.coordinator import _calendar_month_total


def test_month_boundary_only_ref_month_summed():
    series = [
        DailyPoint(date(2026, 6, 30), 1.0),  # previous month -> excluded
        DailyPoint(date(2026, 7, 1), 2.0),
        DailyPoint(date(2026, 7, 15), 3.0),
        DailyPoint(date(2026, 8, 1), 4.0),  # next month -> excluded
    ]
    assert _calendar_month_total(series, date(2026, 7, 10)) == 5.0


def test_year_boundary_december_excluded_for_january_ref():
    series = [
        DailyPoint(date(2025, 12, 31), 100.0),  # same month number, prior year
        DailyPoint(date(2026, 1, 5), 2.0),
        DailyPoint(date(2026, 1, 20), 3.0),
    ]
    assert _calendar_month_total(series, date(2026, 1, 15)) == 5.0


def test_empty_month_returns_none():
    series = [DailyPoint(date(2026, 6, 1), 1.0)]
    assert _calendar_month_total(series, date(2026, 7, 1)) is None


def test_empty_series_returns_none():
    assert _calendar_month_total([], date(2026, 7, 1)) is None


def test_result_is_rounded_to_four_dp():
    series = [
        DailyPoint(date(2026, 7, 1), 0.123456),
        DailyPoint(date(2026, 7, 2), 0.654321),
    ]
    # 0.777777 -> rounded to 4 decimals.
    assert _calendar_month_total(series, date(2026, 7, 10)) == 0.7778
