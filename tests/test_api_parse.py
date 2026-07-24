"""Tests for the pure curve-parsing helpers in ``api.py``."""
from __future__ import annotations

from datetime import date

from custom_components.romande_energie.api import (
    DailyPoint,
    latest_value,
    parse_daily_series,
)

D1 = "2026-06-01T00:00:00+02:00"
D2 = "2026-06-02T00:00:00+02:00"
D3 = "2026-06-03T00:00:00+02:00"


def _block(timestamps, curves, *, installations=None):
    """Wrap timestamps + curves into the portal's response shape."""
    if installations is None:
        installations = [{"curves": curves}]
    return [{"timestamps": timestamps, "installations": installations}]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_happy_path_consumption(sample_curves):
    series = parse_daily_series(sample_curves, "consumption")
    assert series == [
        DailyPoint(date(2026, 6, 1), 10.5),
        DailyPoint(date(2026, 6, 2), 11.0),
        DailyPoint(date(2026, 6, 3), 9.25),
        DailyPoint(date(2026, 6, 4), 12.0),
    ]


def test_happy_path_surplus_keeps_zero(sample_curves):
    # A real 0.0 value is data, not "missing", so it must be kept.
    series = parse_daily_series(sample_curves, "surplus")
    assert series == [
        DailyPoint(date(2026, 6, 1), 2.0),
        DailyPoint(date(2026, 6, 2), 1.5),
        DailyPoint(date(2026, 6, 3), 0.0),
        DailyPoint(date(2026, 6, 4), 3.25),
    ]


def test_default_curve_type_is_consumption(sample_curves):
    assert parse_daily_series(sample_curves) == parse_daily_series(
        sample_curves, "consumption"
    )


# ---------------------------------------------------------------------------
# Null handling / index alignment
# ---------------------------------------------------------------------------
def test_null_drop_keeps_index_alignment():
    payload = _block(
        [D1, D2, D3],
        [{"curve_type": "consumption", "values": ["1.0", None, "3.0"]}],
    )
    series = parse_daily_series(payload, "consumption")
    # The middle null day is dropped but D3 stays paired with "3.0".
    assert series == [
        DailyPoint(date(2026, 6, 1), 1.0),
        DailyPoint(date(2026, 6, 3), 3.0),
    ]


def test_trailing_null_dropped(sample_curves):
    series = parse_daily_series(sample_curves, "consumption")
    assert date(2026, 6, 5) not in {p.day for p in series}


# ---------------------------------------------------------------------------
# Degenerate / empty inputs
# ---------------------------------------------------------------------------
def test_empty_response():
    assert parse_daily_series([]) == []


def test_block_missing_keys():
    assert parse_daily_series([{}]) == []


def test_block_no_installations():
    assert parse_daily_series([{"timestamps": [D1], "installations": []}]) == []


def test_installation_without_curves():
    assert parse_daily_series([{"timestamps": [D1], "installations": [{}]}]) == []


def test_no_matching_curve_type():
    payload = _block([D1], [{"curve_type": "surplus", "values": ["1.0"]}])
    assert parse_daily_series(payload, "consumption") == []


# ---------------------------------------------------------------------------
# zip length mismatches (values shorter / longer than timestamps)
# ---------------------------------------------------------------------------
def test_values_shorter_than_timestamps():
    payload = _block(
        [D1, D2, D3],
        [{"curve_type": "consumption", "values": ["1.0", "2.0"]}],
    )
    series = parse_daily_series(payload, "consumption")
    assert series == [
        DailyPoint(date(2026, 6, 1), 1.0),
        DailyPoint(date(2026, 6, 2), 2.0),
    ]


def test_values_longer_than_timestamps():
    payload = _block(
        [D1, D2],
        [{"curve_type": "consumption", "values": ["1.0", "2.0", "3.0"]}],
    )
    series = parse_daily_series(payload, "consumption")
    assert series == [
        DailyPoint(date(2026, 6, 1), 1.0),
        DailyPoint(date(2026, 6, 2), 2.0),
    ]


# ---------------------------------------------------------------------------
# Summation across installations of the same type
# ---------------------------------------------------------------------------
def test_summation_across_two_installations():
    payload = _block(
        [D1, D2],
        curves=None,
        installations=[
            {"curves": [{"curve_type": "consumption", "values": ["10.0", "1.0"]}]},
            {"curves": [{"curve_type": "consumption", "values": ["5.0", "2.0"]}]},
        ],
    )
    series = parse_daily_series(payload, "consumption")
    assert series == [
        DailyPoint(date(2026, 6, 1), 15.0),
        DailyPoint(date(2026, 6, 2), 3.0),
    ]


def test_summation_across_two_curves_same_installation():
    payload = _block(
        [D1],
        [
            {"curve_type": "consumption", "values": ["4.0"]},
            {"curve_type": "consumption", "values": ["6.0"]},
        ],
    )
    series = parse_daily_series(payload, "consumption")
    assert series == [DailyPoint(date(2026, 6, 1), 10.0)]


# ---------------------------------------------------------------------------
# Unparseable values are dropped, good ones survive
# ---------------------------------------------------------------------------
def test_unparseable_value_dropped():
    payload = _block(
        [D1, D2],
        [{"curve_type": "consumption", "values": ["not-a-number", "2.0"]}],
    )
    series = parse_daily_series(payload, "consumption")
    assert series == [DailyPoint(date(2026, 6, 2), 2.0)]


# ---------------------------------------------------------------------------
# Wall-clock local calendar day (DST-safe: never converted to UTC)
# ---------------------------------------------------------------------------
def test_wall_clock_local_day_not_utc():
    # Just after local midnight: the UTC instant is the previous day, but the
    # parser must key on the wall-clock date (2026-06-01), not UTC (05-31).
    payload = _block(
        ["2026-06-01T00:30:00+02:00"],
        [{"curve_type": "consumption", "values": ["5.0"]}],
    )
    series = parse_daily_series(payload, "consumption")
    assert series == [DailyPoint(date(2026, 6, 1), 5.0)]


def test_different_offsets_same_local_day_are_summed():
    # A DST boundary can produce two rows on the same wall-clock day with
    # different UTC offsets; both must land on the same calendar day.
    payload = _block(
        ["2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"],
        [{"curve_type": "consumption", "values": ["1.0", "2.0"]}],
    )
    series = parse_daily_series(payload, "consumption")
    assert series == [DailyPoint(date(2026, 10, 25), 3.0)]


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------
def test_output_is_day_sorted():
    payload = _block(
        [D3, D1, D2],
        [{"curve_type": "consumption", "values": ["3.0", "1.0", "2.0"]}],
    )
    series = parse_daily_series(payload, "consumption")
    assert [p.day for p in series] == [
        date(2026, 6, 1),
        date(2026, 6, 2),
        date(2026, 6, 3),
    ]


# ---------------------------------------------------------------------------
# latest_value
# ---------------------------------------------------------------------------
def test_latest_value_returns_last(sample_curves):
    series = parse_daily_series(sample_curves, "consumption")
    assert latest_value(series) == DailyPoint(date(2026, 6, 4), 12.0)


def test_latest_value_empty_is_none():
    assert latest_value([]) is None
