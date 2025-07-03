from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN, CONF_CONTRACT_ID, TZ, ATTR_ENERGY

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RomandeEnergySensor(coordinator, entry.data[CONF_CONTRACT_ID])])


class RomandeEnergySensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, contract_id: str):
        self._coordinator = coordinator
        self._attr_unique_id = f"romande_energy_{contract_id}_kwh"
        self._attr_name = "Romande Énergie Daily"
        self._attr_available = coordinator.last_update_success

        # Expose yesterday 00:00 as implicit last_reset (for statistics)
        yesterday = (datetime.now(tz=TZ) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        self._attr_last_reset = yesterday

        coordinator.async_add_listener(self.async_write_ha_state)

    # ------------------------------------------------------------------
    # Home Assistant core API
    # ------------------------------------------------------------------
    @property
    def native_value(self):
        return self._coordinator.data

    async def async_update(self):
        await self._coordinator.async_request_refresh()