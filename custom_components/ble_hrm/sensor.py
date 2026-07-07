"""Sensor platform for event-driven BLE Heart Rate integration."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorStateClass,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .manager import BLEConnectionManager

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        BLEHeartRateSensor(manager),
        BLEBatterySensor(manager),
    ]
    
    async_add_entities(entities)


class BLEHRMBaseSensor(SensorEntity):
    """Base framework for generic BLE sensor instances."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: BLEConnectionManager) -> None:
        """Initialize base architecture attributes."""
        self.manager = manager
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.address)},
            name=manager.name,
            manufacturer="Garmin",
            model="HRM Device",
            connections={("bluetooth", manager.address)},
        )

    async def async_added_to_hass(self) -> None:
        """Register native database push callback notifications."""
        self.async_on_remove(self.manager.register_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        """Reflect entity status safely based on proxy link health."""
        return self.manager.connected


class BLEHeartRateSensor(BLEHRMBaseSensor):
    """Real-time pulse entity reporting."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "bpm"
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, manager: BLEConnectionManager) -> None:
        """Initialize."""
        super().__init__(manager)
        self._attr_name = "Heart Rate"
        self._attr_unique_id = f"{manager.address}_heart_rate"

    @property
    def native_value(self) -> int | None:
        """Return state."""
        return self.manager.heart_rate


class BLEBatterySensor(BLEHRMBaseSensor):
    """Battery runtime tracking diagnostics."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, manager: BLEConnectionManager) -> None:
        """Initialize."""
        super().__init__(manager)
        self._attr_name = "Battery"
        self._attr_unique_id = f"{manager.address}_battery"

    @property
    def native_value(self) -> int | None:
        """Return state."""
        return self.manager.battery
