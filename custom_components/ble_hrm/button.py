"""Button platform for BLE HRM integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
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
    """Set up the button platform from a config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BLEHRMReconnectButton(manager)])


class BLEHRMReconnectButton(ButtonEntity):
    """Button to force reconnect to the BLE HRM device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:bluetooth-connect"

    def __init__(self, manager: BLEConnectionManager) -> None:
        """Initialize the reconnect button."""
        self.manager = manager
        self._attr_name = "Force Reconnect"
        self._attr_unique_id = f"{manager.address}_force_reconnect"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.address)},
            name=manager.name,
            manufacturer="Garmin",
            model="HRM Device",
            connections={("bluetooth", manager.address)},
        )

    async def async_press(self) -> None:
        """Press the button to execute force reconnection logic."""
        await self.manager.async_force_reconnect()
