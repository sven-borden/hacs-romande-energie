"""Sensor platform for Romande Energie integration."""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import UnitOfEnergy

from .const import (
    DOMAIN,
    SENSOR_TYPES,
    SENSOR_TYPE_DAILY_CONSUMPTION,
    SENSOR_TYPE_MONTHLY_CONSUMPTION,
    SENSOR_TYPE_LATEST_CONSUMPTION,  # Add this
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Romande Energie sensor based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api_client = hass.data[DOMAIN][entry.entry_id]["api_client"]

    sensors = []
    for sensor_type in SENSOR_TYPES:
        sensors.append(
            RomandeEnergieSensor(coordinator, api_client, entry, sensor_type)
        )

    async_add_entities(sensors)


class RomandeEnergieSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Romande Energie sensor."""

    def __init__(self, coordinator, api_client, entry, sensor_type):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.api_client = api_client
        self.entry = entry
        self.sensor_type = sensor_type
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_name = f"Romande Energie {SENSOR_TYPES[sensor_type]['name']}"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_icon = SENSOR_TYPES[sensor_type]['icon']
        self._attr_device_class = SENSOR_TYPES[sensor_type]['device_class']
        self._attr_state_class = SENSOR_TYPES[sensor_type]['state_class']

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Romande Energie",
            manufacturer="Romande Energie",
            model="Electricity Meter",
            entry_type="service",
        )

    @property
    def native_value(self) -> Optional[float]:
        """Return the state of the sensor."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return None
            
        try:
            consumption_data = self.coordinator.data["consumption"]
            values = consumption_data.get("values", [])

            if not values:
                return 0
                
            if self.sensor_type == SENSOR_TYPE_DAILY_CONSUMPTION:
                # Filter for today's data points and sum them
                today = datetime.now().strftime("%Y-%m-%d")
                today_values = [
                    float(point.get("value", 0)) 
                    for point in values 
                    if point.get("timestamp", "").startswith(today)
                ]
                return sum(today_values) if today_values else 0
                    
            elif self.sensor_type == SENSOR_TYPE_MONTHLY_CONSUMPTION:
                # If we have a total in the API response, use it
                if "total" in consumption_data and consumption_data["total"] is not None:
                    return float(consumption_data["total"])
                
                # Otherwise calculate monthly total from available values
                # Get first day of current month
                today = datetime.now()
                first_day = today.replace(day=1).strftime("%Y-%m-")
                
                monthly_values = [
                    float(point.get("value", 0)) 
                    for point in values 
                    if point.get("timestamp", "").startswith(first_day)
                ]
                return sum(monthly_values) if monthly_values else 0

            elif self.sensor_type == SENSOR_TYPE_LATEST_CONSUMPTION:
                # Get the most recent value
                if values:
                    # Sort by timestamp descending and take the first one
                    sorted_values = sorted(values, key=lambda x: x.get("timestamp", ""), reverse=True)
                    if sorted_values:
                        return float(sorted_values[0].get("value", 0))
                return 0
                
        except (KeyError, ValueError, TypeError) as err:
            _LOGGER.error(f"Error calculating sensor value: {err}")
            return None
