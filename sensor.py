"""Sensor platform for event-driven BLE Heart Rate integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient

from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    BATTERY_LEVEL_UUID,
    CONF_DEVICE_ADDRESS,
    CONF_DEVICE_NAME,
    DOMAIN,
    HEART_RATE_MEASUREMENT_UUID,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    address = entry.data[CONF_DEVICE_ADDRESS].upper()
    name = entry.data.get(CONF_DEVICE_NAME) or f"HRM {address[-6:]}"
    
    manager = BLEConnectionManager(hass, address, name)
    
    entities = [
        BLEHeartRateSensor(manager),
        BLEBatterySensor(manager),
    ]
    
    async_add_entities(entities)
    
    # Establish persistent listening loops outside the initialization flow
    entry.async_on_unload(manager.setup_tracking())

class BLEConnectionManager:
    """Manages continuous active GATT socket streams over HA Proxies."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        """Initialize the connection manager."""
        self.hass = hass
        self.address = address
        self.name = name
        self.client: BleakClient | None = None
        self.connected = False
        self.listeners: list[callback] = []
        self.heart_rate: int | None = None
        self.battery: int | None = None
        self._lock = asyncio.Lock()

    def register_listener(self, listener: callback) -> callback:
        """Register entity listener update hooks."""
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def _notify_listeners(self) -> None:
        """Push fresh values out to registered entities."""
        for listener in self.listeners:
            listener()

    @callback
    def handle_availability_change(self, service_info: bluetooth.BluetoothServiceInfoBleak) -> None:
        """Fires whenever a proxy picks up an advertisement packet."""
        if not self.connected:
            self.hass.async_create_task(self.async_connect())

    @callback
    def handle_unavailable(self, address: str) -> None:
        """Fires automatically when the proxy network loses track of the device."""
        _LOGGER.debug("Device went out of range or entered deep sleep.")
        self.hass.async_create_task(self.async_disconnect())

    def setup_tracking(self):
        """Bind connection manager hooks directly to HA core tracking."""
        # Unsubscribe tracking tokens
        unload_track = bluetooth.async_register_callback(
            self.hass,
            self.handle_availability_change,
            bluetooth.BluetoothCallbackMatcher(address=self.address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        
        unload_avail = bluetooth.async_track_unavailable(
            self.hass,
            self.handle_unavailable,
            self.address,
        )
        
        # Fire initial connection scan attempt asynchronously
        if ble_device := bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True):
            self.hass.async_create_task(self.async_connect())

        def _cleanup():
            unload_track()
            unload_avail()
            self.hass.async_create_task(self.async_disconnect())

        return _cleanup

    async def async_connect(self) -> None:
        """Secure active GATT socket via closest available proxy routing."""
        async with self._lock:
            if self.connected:
                return

            ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
            if not ble_device:
                return

            self.client = BleakClient(ble_device)
            try:
                await self.client.connect()
                self.connected = True
                
                # Setup standard event notification stream
                await self.client.start_notify(
                    HEART_RATE_MEASUREMENT_UUID, self._notification_handler
                )
                
                # Fetch baseline battery diagnostic metric once upon handshake
                try:
                    bat_bytes = await self.client.read_gatt_char(BATTERY_LEVEL_UUID)
                    self.battery = int(bat_bytes[0])
                except Exception:
                    self.battery = None
                    
                self._notify_listeners()
            except Exception as err:
                _LOGGER.debug("Proxy connection attempt deferred: %s", err)
                self.connected = False
                self.client = None

    def _notification_handler(self, sender: int, data: bytearray) -> None:
        """Decode raw BLE Heart Rate byte arrays."""
        flags = data[0]
        if flags & 0x01:
            self.heart_rate = int.from_bytes(data[1:3], byteorder="little")
        else:
            self.heart_rate = data[1]
        self._notify_listeners()

    async def async_disconnect(self) -> None:
        """Clean breakdown of socket arrays to keep DB history uncorrupted."""
        async with self._lock:
            self.heart_rate = None
            self.battery = None
            self.connected = False
            if self.client:
                try:
                    await self.client.disconnect()
                except Exception:
                    pass
                self.client = None
            self._notify_listeners()


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
        """Reflect entity status safely."""
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
