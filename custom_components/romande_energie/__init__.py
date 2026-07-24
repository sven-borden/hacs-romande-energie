"""Set-up for the Romande Énergie custom component."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import aiohttp_client

from .api import RomandeEnergieApiClient
from .const import DOMAIN
from .coordinator import RomandeEnergieCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
SERVICE_UPDATE_NOW = "update_now"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create coordinator, do first refresh, forward platforms, register service."""
    session = aiohttp_client.async_get_clientsession(hass)
    coordinator = RomandeEnergieCoordinator(hass, entry, RomandeEnergieApiClient(session))
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


def _register_services(hass: HomeAssistant) -> None:
    """Register the update_now service once (coordinator polling handles the rest)."""
    if hass.services.has_service(DOMAIN, SERVICE_UPDATE_NOW):
        return

    async def _update_now(call: ServiceCall) -> None:
        """Force an immediate refresh on every loaded coordinator."""
        for coord in hass.data.get(DOMAIN, {}).values():
            await coord.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_UPDATE_NOW, _update_now)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry; drop the service once the last entry is gone."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            hass.services.async_remove(DOMAIN, SERVICE_UPDATE_NOW)
    return unload_ok
