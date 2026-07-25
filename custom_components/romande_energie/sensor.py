"""Romande Énergie energy sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RomandeEnergieCoordinator, RomandeEnergieData


@dataclass(frozen=True, kw_only=True)
class RomandeEnergieSensorEntityDescription(SensorEntityDescription):
    """Describe a Romande Énergie sensor."""

    value_fn: Callable[[RomandeEnergieData], float | None]
    day_fn: Callable[[RomandeEnergieData], date | None] | None = None
    surplus: bool = False  # True => only added when data.has_surplus


# state_class deliberately unset: external statistics carry the Energy-dashboard
# history, so a state_class here would double-count.
#
# The ``*_yesterday`` keys are misnomers now that the sensors report the newest
# settled day, which is often older than yesterday. They stay anyway: the keys
# build the unique ids (see ``_attr_unique_id``), so renaming them would orphan
# every existing entity and its history.
DESCRIPTIONS: tuple[RomandeEnergieSensorEntityDescription, ...] = (
    RomandeEnergieSensorEntityDescription(
        key="consumption_yesterday",
        name="Consommation (jour)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda d: d.consumption.value if d.consumption else None,
        day_fn=lambda d: d.consumption.day if d.consumption else None,
    ),
    RomandeEnergieSensorEntityDescription(
        key="consumption_month",
        name="Consommation (mois)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda d: d.consumption_month_total,
    ),
    RomandeEnergieSensorEntityDescription(
        key="surplus_yesterday",
        name="Excédent (jour)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        surplus=True,
        value_fn=lambda d: d.surplus.value if d.surplus else None,
        day_fn=lambda d: d.surplus.day if d.surplus else None,
    ),
    RomandeEnergieSensorEntityDescription(
        key="surplus_month",
        name="Excédent (mois)",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        surplus=True,
        value_fn=lambda d: d.surplus_month_total,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors from a config entry."""
    coordinator: RomandeEnergieCoordinator = hass.data[DOMAIN][entry.entry_id]
    # First refresh already ran, so coordinator.data is populated.
    has_surplus = bool(coordinator.data and coordinator.data.has_surplus)
    entities = [
        RomandeEnergieSensor(coordinator, description)
        for description in DESCRIPTIONS
        if has_surplus or not description.surplus
    ]
    async_add_entities(entities)


class RomandeEnergieSensor(
    CoordinatorEntity[RomandeEnergieCoordinator], SensorEntity
):
    """A single Romande Énergie energy sensor."""

    _attr_has_entity_name = True
    entity_description: RomandeEnergieSensorEntityDescription

    def __init__(
        self,
        coordinator: RomandeEnergieCoordinator,
        description: RomandeEnergieSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{coordinator.contract_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.contract_id)},
            name="Romande Énergie",
            manufacturer="Romande Énergie",
            model="Espace client",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value from the coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose the measured day (for the daily sensors, which define day_fn).

        Which day that is depends on how far the portal has synced, so the
        sensors state it rather than leaving it implied.
        """
        day_fn = self.entity_description.day_fn
        data = self.coordinator.data
        if day_fn is None or data is None:
            return None
        day = day_fn(data)
        return {"measurement_day": day.isoformat()} if day else None
