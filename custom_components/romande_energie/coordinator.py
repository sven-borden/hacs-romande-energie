"""DataUpdateCoordinator for the Romande Énergie integration.

Keeps the session warm by refreshing before the access token expires, pulls a
rolling window of daily curves each poll, feeds long-term statistics into the
recorder and exposes the latest daily/monthly figures to the sensors.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
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
    TOKEN_EXP_MARGIN,
    TZ,
    UNIT_KWH,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _calendar_month_total(series: list[DailyPoint], ref: date) -> float | None:
    """Sum the values of ``series`` that fall in ref's calendar month.

    The curve request uses a rolling window, so ``curves_statistics.total`` is a
    rolling total, not month-to-date — compute the calendar month ourselves.
    """
    month = [p.value for p in series if p.day.year == ref.year and p.day.month == ref.month]
    return round(sum(month), 4) if month else None


@dataclass(frozen=True)
class RomandeEnergieData:
    """Snapshot handed to the sensors each poll.

    Pairing the value with its day in a single ``DailyPoint`` makes the
    "value present but day missing" state unrepresentable.
    """

    consumption: DailyPoint | None
    consumption_month_total: float | None
    surplus: DailyPoint | None
    surplus_month_total: float | None

    @property
    def has_surplus(self) -> bool:
        """True when the account reports surplus (solar) data."""
        return self.surplus is not None


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
            consumption=api.latest_value(cons),
            consumption_month_total=_calendar_month_total(cons, today),
            surplus=api.latest_value(surp),
            surplus_month_total=_calendar_month_total(surp, today),
        )

    # ---- Statistics -------------------------------------------------------
    async def _insert_statistics(
        self, stat_id: str, name_suffix: str, series: list[DailyPoint]
    ) -> None:
        """Append daily cumulative-sum statistics, skipping already-stored days."""
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
        last = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, stat_id, True, {"sum"}
        )
        running = 0.0
        last_ts: float | None = None
        prev = last.get(stat_id)
        if prev:
            # Only continue an existing series when we can read both its running
            # sum and its last timestamp; otherwise emitting a fresh series would
            # push the cumulative sum backwards (read as a meter reset).
            prev_sum = prev[0].get("sum")
            last_ts = prev[0].get("start")
            if prev_sum is None or last_ts is None:
                _LOGGER.warning(
                    "Last %s statistic missing sum/start; skipping this cycle",
                    stat_id,
                )
                return
            running = float(prev_sum)

        points: list[StatisticData] = []
        for point in series:
            start = datetime(point.day.year, point.day.month, point.day.day, tzinfo=TZ)
            if last_ts is not None and start.timestamp() <= last_ts:
                continue
            running += point.value
            points.append(StatisticData(start=start, state=point.value, sum=running))
        if points:
            async_add_external_statistics(self.hass, metadata, points)
