"""Romande Énergie daily energy sensor."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_CONTRACT_ID, TZ

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Romande Énergie sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [RomandeEnergySensor(coordinator, entry.data[CONF_CONTRACT_ID])]
    )


class RomandeEnergySensor(SensorEntity):
    """Represent yesterday's energy consumption in kWh."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, contract_id: str) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"romande_energy_{contract_id}_kwh"
        self._attr_name = "Romande Énergie Daily"
        self._update_last_reset()
        coordinator.async_add_listener(self.async_write_ha_state)

    def _update_last_reset(self) -> None:
        yesterday_midnight = (
            datetime.now(tz=TZ) - timedelta(days=1)
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        self._attr_last_reset = yesterday_midnight

    # ---------- Home Assistant Entity hooks ----------
    @property
    def native_value(self):
        return self._coordinator.data

    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success

    async def async_update(self) -> None:
        await self._coordinator.async_request_refresh()
```python
"""Romande Énergie daily energy sensor."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_CONTRACT_ID, TZ

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        RomandeEnergySensor(coordinator, entry.data[CONF_CONTRACT_ID])
    ])


class RomandeEnergySensor(SensorEntity):
    """Sensor representing yesterday's electricity consumption."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, contract_id: str) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"romande_energy_{contract_id}_kwh"
        self._attr_name = "Romande Énergie Daily"
        self._attr_available = coordinator.last_update_success

        # Statistics last_reset
        yesterday_midnight = (
            datetime.now(tz=TZ) - timedelta(days=1)
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        self._attr_last_reset = yesterday_midnight

        coordinator.async_add_listener(self.async_write_ha_state)

    # ------------------------------------------------------------------
    # Home Assistant core API
    # ------------------------------------------------------------------
    @property
    def native_value(self):
        """Return yesterday's kWh value."""
        return self._coordinator.data

    async def async_update(self):
        await self._coordinator.async_request_refresh()
```python
"""Romande Énergie daily energy sensor."""
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