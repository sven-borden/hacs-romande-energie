"""DataUpdateCoordinator for the Romande Énergie integration.

Keeps the session warm by refreshing before the access token expires, pulls a
rolling window of daily curves each poll, feeds long-term statistics into the
recorder and exposes the latest daily/monthly figures to the sensors.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import api
from .api import (
    ApiError,
    AuthError,
    CannotConnect,
    DailyPoint,
    RefreshError,
    RomandeEnergieApiClient,
)
from .const import (
    CONF_ACCOUNT_ID,
    CONF_CONTRACT_ID,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    CURVE_TYPE_CONSUMPTION,
    CURVE_TYPE_SURPLUS,
    DOMAIN,
    FETCH_DAYS,
    STAT_BASELINE_LOOKBACK,
    TOKEN_EXP_MARGIN,
    TZ,
    UNIT_KWH,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _day_start(day: date) -> datetime:
    """Local midnight of ``day`` — the statistic timestamp for that day."""
    return datetime(day.year, day.month, day.day, tzinfo=TZ)


def _calendar_month_total(series: list[DailyPoint], ref: date) -> float | None:
    """Sum the values of ``series`` that fall in ref's calendar month.

    The curve request uses a rolling window, so ``curves_statistics.total`` is a
    rolling total, not month-to-date — compute the calendar month ourselves.
    """
    month = [p.value for p in series if p.day.year == ref.year and p.day.month == ref.month]
    return round(sum(month), 4) if month else None


def _settled(series: list[DailyPoint]) -> list[DailyPoint]:
    """Drop the newest day of ``series``.

    The portal syncs once a day, so its most recent day is still being filled
    in and reads far too low until the next sync completes it. Only the days
    behind it are final, so the daily sensors read from those.
    """
    return series[:-1]


@dataclass(frozen=True)
class RomandeEnergieData:
    """Snapshot handed to the sensors each poll.

    Pairing the value with its day in a single ``DailyPoint`` makes the
    "value present but day missing" state unrepresentable. ``consumption`` and
    ``surplus`` are the newest *settled* day; the month totals cover every day
    fetched, including the one still syncing.
    """

    consumption: DailyPoint | None
    consumption_month_total: float | None
    surplus: DailyPoint | None
    surplus_month_total: float | None
    has_surplus: bool


class RomandeEnergieCoordinator(DataUpdateCoordinator[RomandeEnergieData]):
    """Coordinate token refresh, curve polling and statistics ingestion."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: RomandeEnergieApiClient
    ) -> None:
        self.client = client
        self.config_entry = entry
        self.username: str = entry.data[CONF_USERNAME]
        self.password: str = entry.data[CONF_PASSWORD]
        self.account_id: str = entry.data[CONF_ACCOUNT_ID]
        self.contract_id: str = entry.data[CONF_CONTRACT_ID]
        # Per-contract statistic ids so multiple accounts never collide.
        self._stat_id_consumption = f"{DOMAIN}:{self.contract_id}_consumption"
        self._stat_id_surplus = f"{DOMAIN}:{self.contract_id}_surplus"
        self._access_token: str | None = None
        self._token_exp: int = 0
        self._refresh_token: str = entry.data[CONF_REFRESH_TOKEN]
        super().__init__(
            hass,
            _LOGGER,
            name="Romande Énergie",
            update_interval=UPDATE_INTERVAL,
        )

    # ---- Auth -------------------------------------------------------------
    async def _ensure_token(self) -> None:
        """Refresh the access token if missing or close to expiry."""
        now = datetime.now(tz=TZ).timestamp()
        if self._access_token and self._token_exp - now > TOKEN_EXP_MARGIN:
            return
        try:
            tokens = await self.client.refresh(self._refresh_token)
        except RefreshError as err:  # refresh token dead -> HA reauth (fresh OTP)
            raise ConfigEntryAuthFailed(str(err)) from err
        self._access_token = tokens["access_token"]
        self._refresh_token = tokens["refresh_token"]
        self._token_exp = api.token_expiry(self._access_token)
        await self._persist_refresh_token()  # rotate: save the new refresh token

    async def _persist_refresh_token(self) -> None:
        """Store the rotated refresh token back on the config entry."""
        if self._refresh_token != self.config_entry.data.get(CONF_REFRESH_TOKEN):
            new = {**self.config_entry.data, CONF_REFRESH_TOKEN: self._refresh_token}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new)

    # ---- Poll -------------------------------------------------------------
    async def _async_update_data(self) -> RomandeEnergieData:
        try:
            await self._ensure_token()
            today = datetime.now(tz=TZ).date()
            start = (today - timedelta(days=FETCH_DAYS)).isoformat()
            end = (today + timedelta(days=1)).isoformat()
            raw = await self.client.get_curves(
                self._access_token, self.contract_id, start, end
            )
        except ConfigEntryAuthFailed:
            raise
        except AuthError as err:  # access token rejected mid-poll -> reauth
            raise ConfigEntryAuthFailed(str(err)) from err
        except (CannotConnect, ApiError) as err:
            raise UpdateFailed(str(err)) from err

        cons = api.parse_daily_series(raw, CURVE_TYPE_CONSUMPTION)
        surp = api.parse_daily_series(raw, CURVE_TYPE_SURPLUS)

        # Long-term statistics feed the energy dashboard but are auxiliary: a
        # recorder hiccup must not blank the sensors, so failures are logged only.
        try:
            await self._insert_statistics(
                self._stat_id_consumption, "Consumption", cons
            )
            if surp:
                await self._insert_statistics(self._stat_id_surplus, "Surplus", surp)
        except Exception as err:  # noqa: BLE001 - stats are best-effort
            _LOGGER.warning("Failed to write long-term statistics: %s", err)

        return RomandeEnergieData(
            consumption=api.latest_value(_settled(cons)),
            consumption_month_total=_calendar_month_total(cons, today),
            surplus=api.latest_value(_settled(surp)),
            surplus_month_total=_calendar_month_total(surp, today),
            # Judged on the full series: a brand-new account whose only day is
            # still syncing still has surplus.
            has_surplus=bool(surp),
        )

    # ---- Statistics -------------------------------------------------------
    async def _insert_statistics(
        self, stat_id: str, name_suffix: str, series: list[DailyPoint]
    ) -> None:
        """Rewrite the whole fetched window as daily cumulative-sum statistics.

        The portal syncs once a day, so a recent day is published with a partial
        value and is completed by a later sync. Days already written must
        therefore be re-sent with their corrected value, not skipped: external
        statistics are keyed on ``start``, so re-sending updates them in place.
        The cumulative sum is rebuilt from the sum stored just before the window
        so the rewritten rows stay continuous with the older history.
        """
        if not series:
            return
        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"Romande Énergie {name_suffix}",
            source=DOMAIN,
            statistic_id=stat_id,
            unit_of_measurement=UNIT_KWH,
        )
        window_start = _day_start(series[0].day)
        running = await self._sum_before(stat_id, window_start)

        points: list[StatisticData] = []
        for point in series:
            running += point.value
            points.append(
                StatisticData(
                    start=_day_start(point.day), state=point.value, sum=running
                )
            )
        async_add_external_statistics(self.hass, metadata, points)

    async def _sum_before(self, stat_id: str, window_start: datetime) -> float:
        """Return the cumulative sum stored for the last day before the window.

        0.0 when nothing is stored before it — either a fresh install or a
        history that starts inside the window, both of which start from zero.
        The lookback is bounded so the query stays cheap; only an outage longer
        than it could leave an older row unseen.
        """
        rows = await get_instance(self.hass).async_add_executor_job(
            partial(
                statistics_during_period,
                self.hass,
                window_start - STAT_BASELINE_LOOKBACK,
                window_start,
                {stat_id},
                "hour",  # our points are daily; "hour" returns them unaggregated
                None,
                {"sum"},
            )
        )
        stored = rows.get(stat_id) or []
        if not stored:
            return 0.0
        last_sum = stored[-1].get("sum")
        if last_sum is None:
            _LOGGER.warning(
                "Last %s statistic before %s has no sum; restarting from zero",
                stat_id,
                window_start.date(),
            )
            return 0.0
        return float(last_sum)
