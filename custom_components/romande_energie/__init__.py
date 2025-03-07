"""The Romande Energie integration."""
import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RomandeEnergieApiClient
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Romande Energie component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Romande Energie from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    
    _LOGGER.debug("Setting up Romande Energie integration for %s", username)
    _LOGGER.info("Attempting initial connection to Romande Energie API")
    
    session = async_get_clientsession(hass)
    api_client = RomandeEnergieApiClient(username, password, session)
    
    # Test the connection
    if not await api_client.login():
        _LOGGER.error("Failed to authenticate with Romande Energie API")
        raise ConfigEntryNotReady("Failed to connect to Romande Energie API")
    _LOGGER.info("Successfully authenticated with Romande Energie API")
    
    # Define update interval (allow override through options)
    update_interval = timedelta(
        seconds=entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL.total_seconds())
    )
    
    async def async_update_data():
        """Fetch data from API."""
        _LOGGER.info("Starting data update from Romande Energie API") # TODO debug
        try:
            # Get last 24 hours consumption data
            end_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            start_time = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            _LOGGER.debug("Fetching consumption data for period %s to %s", start_time, end_time)
            consumption_data = await api_client.get_electricity_consumption(
                from_date=start_time, to_date=end_time
            )
            
            if not consumption_data:
                _LOGGER.error("Failed to fetch consumption data: Empty response")
                raise UpdateFailed("Failed to fetch consumption data")
            
            _LOGGER.debug("Successfully retrieved consumption data")
            return {
                "consumption": consumption_data,
            }
        except Exception as err:
            _LOGGER.error("Error communicating with API: %s", str(err), exc_info=True)
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=update_interval,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api_client": api_client,
        "coordinator": coordinator,
    }

    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok