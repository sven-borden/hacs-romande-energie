"""Romande Energie Custom Integration."""
import logging
import asyncio
import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
DOMAIN = "romande_energie"
PLATFORMS = ["sensor"]

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up integration from configuration.yaml (if used)."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up integration from the config flow."""
    hass.data.setdefault(DOMAIN, {})
    # Load platforms (e.g., sensor) from the config entry
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok

async def async_login(session: aiohttp.ClientSession, username: str, password: str):
    """Authenticate and return tokens."""
    url = "https://api.espace-client.romande-energie.ch/api/login/"
    payload = {"username": username, "password": password}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with session.post(url, json=payload, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
        _LOGGER.debug("Login response: %s", data)
        return data.get("access"), data.get("refresh")

async def async_get_session(session: aiohttp.ClientSession, access_token: str):
    """Retrieve session details."""
    url = "https://api.espace-client.romande-energie.ch/users/session/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
        _LOGGER.debug("Session response: %s", data)
        return data

async def async_get_contracts(session: aiohttp.ClientSession, session_id: str):
    """Retrieve contracts for a given session."""
    url = f"https://api.espace-client.romande-energie.ch/accounts/{session_id}/contracts/"
    headers = {"Accept": "application/json"}
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
        _LOGGER.debug("Contracts response: %s", data)
        return data

async def async_get_consumption(session: aiohttp.ClientSession, contract_id: str, from_date: str, to_date: str):
    """Fetch electricity consumption curves."""
    url = (
        f"https://api.espace-client.romande-energie.ch/contracts/"
        f"{contract_id}/services/electricity/curves/?from_date={from_date}&to_date={to_date}"
    )
    headers = {"Accept": "application/json"}
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
        _LOGGER.debug("Consumption response: %s", data)
        return data