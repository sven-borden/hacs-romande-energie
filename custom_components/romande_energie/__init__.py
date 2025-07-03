"""Set‑up for the Romande Énergie custom component."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_point_in_time

from .const import DOMAIN, TZ
from .coordinator import RomandeEnergieCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create coordinator and forward setups to platform(s)."""
    session = aiohttp_client.async_get_clientsession(hass)
    coordinator = RomandeEnergieCoordinator(hass, entry.data, session)

    await coordinator.async_refresh()  # First fetch during set‑up

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Schedule daily update precisely at 08:00 local time.
    @callback
    def _schedule_daily_refresh(now: datetime):
        async def _run_refresh(_: datetime):
            await coordinator.async_refresh()

        # Figure next 08:00.
        next_run_date = (now.astimezone(TZ).date() + timedelta(days=1))
        next_run_dt = datetime.combine(next_run_date, time(hour=8), tzinfo=TZ)
        async_track_point_in_time(hass, _run_refresh, next_run_dt)

    _schedule_daily_refresh(datetime.now(timezone.utc))

    for platform in PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok