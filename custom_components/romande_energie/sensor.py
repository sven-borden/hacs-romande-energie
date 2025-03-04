"""Sensor platform for Romande Énergie."""
import logging
import aiohttp
from datetime import date, timedelta
from homeassistant.helpers.entity import Entity
from . import DOMAIN, async_login, async_get_session, async_get_contracts, async_get_consumption

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors from config entry."""
    username = entry.data.get("username")
    password = entry.data.get("password")
    async_add_entities([RomandeEnergieConsumptionSensor(username, password)], True)

class RomandeEnergieConsumptionSensor(Entity):
    """Representation of a Romande Énergie Consumption sensor."""

    def __init__(self, username: str, password: str):
        """Initialize the sensor."""
        self._username = username
        self._password = password
        self._state = None
        self._attr_name = "Romande Énergie Daily Consumption"

    @property
    def name(self):
        return self._attr_name

    @property
    def state(self):
        return self._state

    async def async_update(self):
        """Fetch new state data for the sensor."""
        async with aiohttp.ClientSession() as session:
            try:
                access_token, refresh_token = await async_login(session, self._username, self._password)
                session_info = await async_get_session(session, access_token)
                session_id = session_info.get("SessionID")
                contracts = await async_get_contracts(session, session_id)
                contract_id = "YOUR_CONTRACT_ID"  # Replace this with logic to select the correct contract

                today = date.today()
                from_date = (today - timedelta(days=1)).isoformat()
                to_date = today.isoformat()

                consumption_data = await async_get_consumption(session, contract_id, from_date, to_date)
                self._state = consumption_data.get("total", 0)
            except Exception as err:
                _LOGGER.error("Error updating Romande Énergie sensor: %s", err)