"""DataUpdateCoordinator for the Romande Énergie integration.

Keeps the session warm by refreshing before the access token expires, pulls a
rolling window of daily curves each poll, feeds long-term statistics into the
recorder and exposes the newest settled daily figure plus the month-to-date
totals to the sensors.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    StatisticsRow,
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

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
    POLL_RETRY_INTERVAL,
    REFRESH_ATTEMPTS,
    REFRESH_RETRY_DELAY,
    TOKEN_EXP_MARGIN,
    TZ,
    UNIT_KWH,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Lower bound for the fallback baseline query: "everything ever stored".
EPOCH = datetime(1970, 1, 1, tzinfo=TZ)


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


def _settled(series: list[DailyPoint], today: date) -> list[DailyPoint]:
    """Drop the newest day while the portal may still be completing it.

    The portal syncs once a day and publishes the day it is working on with a
    value far below its real total — around a fifth of it, observed
    2026-07-25 — until a later sync fills it in. ``series`` has already had its
    null days dropped by the parser, so its newest entry is the newest day
    carrying any value at all; that is the one that may still move. When the
    portal is lagging further behind, later syncs have already had their chance
    to complete its newest day, so that day is kept.
    """
    if series and series[-1].day >= today - timedelta(days=1):
        return series[:-1]
    return series


def _fill_gaps(series: list[DailyPoint]) -> list[DailyPoint]:
    """Return one point per calendar day the series spans, 0.0 where it has none.

    Statistics rows have to stay contiguous. A day the portal has stopped
    publishing (or has not published yet) would otherwise keep the sum an
    earlier poll gave it while the days after it are rewritten without its
    value, leaving the stored sums non-monotonic — which the Energy dashboard
    reads as a meter reset. A zero written here is corrected by a later poll
    once the portal publishes that day.
    """
    by_day = {point.day: point.value for point in series}
    day, last = series[0].day, series[-1].day
    filled: list[DailyPoint] = []
    while day <= last:
        filled.append(DailyPoint(day, by_day.get(day, 0.0)))
        day += timedelta(days=1)
    return filled


@dataclass(frozen=True)
class RomandeEnergieData:
    """Snapshot handed to the sensors each poll.

    Pairing the value with its day in a single ``DailyPoint`` makes the
    "value present but day missing" state unrepresentable. ``consumption`` and
    ``surplus`` are the newest *settled* day. The month totals cover the days
    of the current calendar month within the fetched window — including the day
    still syncing, so they climb as the portal completes it. ``has_surplus`` is
    judged on the full series, so it stays true for an account whose only day
    has yet to settle.
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
        # Per-contract statistic ids so multiple accounts never collide. The
        # contract id comes from the portal and only slugs are valid in a
        # statistic id, so an id carrying uppercase letters or hyphens would
        # make every write raise HomeAssistantError.
        contract_slug = slugify(self.contract_id)
        self._stat_id_consumption = f"{DOMAIN}:{contract_slug}_consumption"
        self._stat_id_surplus = f"{DOMAIN}:{contract_slug}_surplus"
        # Last window handed to the recorder per statistic id, to skip re-writing
        # an unchanged one on every poll.
        self._written: dict[str, list[DailyPoint]] = {}
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
        tokens = await self._refresh_tokens()
        self._access_token = tokens["access_token"]
        self._refresh_token = tokens["refresh_token"]
        self._token_exp = api.token_expiry(self._access_token)
        await self._persist_refresh_token()  # rotate: save the new refresh token

    async def _refresh_tokens(self) -> dict[str, Any]:
        """Rotate the session, retrying a refresh that never got an answer.

        The refresh token expires ~30 min after the rotation that issued it, and
        only a successful refresh renews it. Giving up on the first transport
        failure or portal 5xx means the next attempt is a whole poll interval
        later, which can land past that TTL — the user then has to re-enter an SMS
        code because of one blip. Retrying inside the poll keeps the ageing window
        short.

        A ``RefreshError`` is not retried: the portal has already rejected the
        token, so further attempts only delay the reauth flow. Note a refresh that
        *timed out* may still have rotated the token server-side, in which case
        the retry sends a token the portal has burned and gets that same
        ``RefreshError`` — unrecoverable either way, since the replacement was in
        the answer we never received.
        """
        for _ in range(REFRESH_ATTEMPTS - 1):
            try:
                return await self._refresh_once()
            except (CannotConnect, ApiError) as err:
                _LOGGER.debug(
                    "Token refresh failed (%s); retrying in %s s", err, REFRESH_RETRY_DELAY
                )
                await asyncio.sleep(REFRESH_RETRY_DELAY)
        return await self._refresh_once()  # last attempt: let the failure surface

    async def _refresh_once(self) -> dict[str, Any]:
        """One refresh call, with a dead refresh token mapped to HA reauth."""
        try:
            return await self.client.refresh(self._refresh_token)
        except RefreshError as err:  # refresh token dead -> HA reauth (fresh OTP)
            raise ConfigEntryAuthFailed(str(err)) from err

    async def _persist_refresh_token(self) -> None:
        """Store the rotated refresh token back on the config entry."""
        if self._refresh_token != self.config_entry.data.get(CONF_REFRESH_TOKEN):
            new = {**self.config_entry.data, CONF_REFRESH_TOKEN: self._refresh_token}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new)

    # ---- Poll -------------------------------------------------------------
    async def _async_update_data(self) -> RomandeEnergieData:
        """Poll, coming back sooner than usual while polls are failing.

        Only a successful poll rotates the refresh token, so a failed one starts
        a clock: wait the full UPDATE_INTERVAL and the gap since the last rotation
        reaches 40 min, outliving the ~30 min refresh-token TTL and costing the
        user an SMS. Retrying on POLL_RETRY_INTERVAL keeps several attempts inside
        the TTL, so a transient outage no longer ends the session. An expired
        refresh token raises ConfigEntryAuthFailed instead, which stops the
        polling altogether — no interval to tune there.
        """
        try:
            data = await self._poll()
        except UpdateFailed:
            self.update_interval = POLL_RETRY_INTERVAL
            raise
        self.update_interval = UPDATE_INTERVAL
        return data

    async def _poll(self) -> RomandeEnergieData:
        """Fetch the rolling window and build the snapshot for the sensors."""
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
        except Exception:  # noqa: BLE001 - stats are best-effort
            # exception(), not warning(): a failure here is silent to the user
            # (the sensors keep updating) so the traceback is the only lead.
            _LOGGER.exception("Failed to write long-term statistics")

        return RomandeEnergieData(
            consumption=api.latest_value(_settled(cons, today)),
            consumption_month_total=_calendar_month_total(cons, today),
            surplus=api.latest_value(_settled(surp, today)),
            surplus_month_total=_calendar_month_total(surp, today),
            # Judged on the full series: a brand-new account whose only day is
            # still syncing still has surplus.
            has_surplus=bool(surp),
        )

    # ---- Statistics -------------------------------------------------------
    async def _insert_statistics(
        self, stat_id: str, name_suffix: str, series: list[DailyPoint]
    ) -> None:
        """Upsert the fetched window as daily cumulative-sum statistics.

        The portal syncs once a day, so a recent day is published with a partial
        value and is completed by a later sync. Days already written must
        therefore be re-sent with their corrected value, not skipped: external
        statistics are keyed on (statistic_id, start), so re-sending a day
        updates its row in place. The cumulative sum is rebuilt from the sum
        stored just before the window so the rewritten rows stay continuous
        with the older history.

        Note that re-sending only ever adds or updates rows — the recorder
        never deletes the ones we leave out — which is why the points are gap
        filled rather than skipped.
        """
        if not series:
            return
        points_for = _fill_gaps(series)
        if self._written.get(stat_id) == points_for:
            # The portal publishes once a day but we poll every 20 minutes;
            # re-sending an unchanged window would be ~60 recorder writes an
            # hour for nothing, which is real wear on an SD-card install.
            return

        window_start = _day_start(points_for[0].day)
        running = await self._sum_before(stat_id, window_start)
        if running is None:
            return  # already logged; writing now would corrupt the history

        metadata = StatisticMetaData(
            has_mean=False,
            has_sum=True,
            name=f"Romande Énergie {name_suffix}",
            source=DOMAIN,
            statistic_id=stat_id,
            unit_of_measurement=UNIT_KWH,
        )
        points: list[StatisticData] = []
        for point in points_for:
            running += point.value
            points.append(
                StatisticData(
                    start=_day_start(point.day), state=point.value, sum=running
                )
            )
        async_add_external_statistics(self.hass, metadata, points)
        self._written[stat_id] = points_for

    async def _sum_before(self, stat_id: str, window_start: datetime) -> float | None:
        """Return the cumulative sum stored for the last day before the window.

        0.0 means this statistic has no history at all before the window — a
        fresh install, or one whose history starts inside it — so the window
        may start counting from zero. ``None`` means history exists but its
        running total could not be read: the caller must then write nothing,
        because restarting from zero would rewrite the window far below the
        history it continues and read as a meter reset on the Energy dashboard.
        """
        # The day before the window answers this on every normal poll; the wide
        # query is only reached when that day is missing (an outage, a purge).
        probe = await self._stored_sums(stat_id, window_start - timedelta(days=1), window_start)
        stored = probe or await self._stored_sums(stat_id, EPOCH, window_start)
        if not stored:
            return 0.0
        last_sum = stored[-1].get("sum")
        if last_sum is None:
            _LOGGER.warning(
                "Last stored %s statistic before %s carries no sum; skipping the "
                "write rather than restarting the total from zero",
                stat_id,
                window_start.date(),
            )
            return None
        return float(last_sum)

    async def _stored_sums(
        self, stat_id: str, start: datetime, end: datetime
    ) -> list[StatisticsRow]:
        """Return the stored rows for ``stat_id`` in [start, end), oldest first."""
        rows = await get_instance(self.hass).async_add_executor_job(
            partial(
                statistics_during_period,
                self.hass,
                start,
                end,
                statistic_ids={stat_id},
                # "hour" is the only safe period here. It returns our daily rows
                # unaggregated, and — unlike "day"/"week"/"month" — it leaves
                # end_time alone: those realign it forward, which would pull the
                # window's own first row into its baseline and inflate the sum.
                period="hour",
                units=None,
                types={"sum"},
            )
        )
        return rows.get(stat_id) or []
