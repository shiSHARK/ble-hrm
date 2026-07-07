"""Initialize the BLE HRM integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_DEVICE_ADDRESS, CONF_DEVICE_NAME
from .manager import BLEConnectionManager

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BLE HRM from a config entry."""
    address = entry.data[CONF_DEVICE_ADDRESS].upper()
    name = entry.data.get(CONF_DEVICE_NAME) or f"HRM {address[-6:]}"
    
    # Initialize the shared coordinator object here
    manager = BLEConnectionManager(hass, address, name)
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = manager
    
    # Bind persistent background proxy monitoring hooks to this specific lifecycle entry
    entry.async_on_unload(manager.setup_tracking())
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
