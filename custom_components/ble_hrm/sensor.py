"""Sensor platform for event-driven BLE Heart Rate integration with Watchdog."""
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
WATCHDOG_TIMEOUT = 30  # Seconds to wait for data before forcing a proxy roam

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
        self._watchdog_task: asyncio.Task | None = None

    def register_listener(self, listener: callback) -> callback:
        """Register entity listener update hooks."""
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def _notify_listeners(self) -> None:
        """Push fresh values out to registered entities."""
        for listener in self.listeners:
            listener()

    @callback
    def handle_availability_change(
        self, 
        service_info: bluetooth.BluetoothServiceInfoBleak, 
        change: bluetooth.BluetoothChange
    ) -> None:
        """Fires whenever a proxy picks up an advertisement packet."""
        if not self.connected:
            self.hass.async_create_task(self.async_connect())

    @callback
    def handle_unavailable(self, address: str) -> None:
        """Fires automatically when the proxy network completely loses track of the device."""
        _LOGGER.debug("Device at %s went out of range or entered deep sleep.", address)
        self.hass.async_create_task(self.async_disconnect())

    def setup_tracking(self):
        """Bind connection manager hooks directly to HA core tracking."""
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
        
        if bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True):
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

            self.client = BleakClient(
                ble_device, 
                disconnected_callback=self._handle_unexpected_disconnect
            )
            try:
                await self.client.connect()
                self.connected = True
                
                await self.client.start_notify(
                    HEART_RATE_MEASUREMENT_UUID, self._notification_handler
                )
                
                try:
                    bat_bytes = await self.client.read_gatt_char(BATTERY_LEVEL_UUID)
                    self.battery = int(bat_bytes[0])
                except Exception:
                    self.battery = None
                    
                self._notify_listeners()
                self._reset_watchdog()  # Start the watchdog timer on successful connection
            except Exception as err:
                _LOGGER.debug("Proxy connection attempt deferred for %s: %s", self.address, err)
                self.connected = False
                self.client = None

    def _handle_unexpected_disconnect(self, client: BleakClient) -> None:
        """Handle un-scheduled peripheral disconnections safely."""
        _LOGGER.debug("Strap at %s disconnected from proxy socket unexpectedly.", self.address)
        self.hass.async_create_task(self.async_disconnect())

    def _reset_watchdog(self) -> None:
        """Resets the 30-second stale data watchdog timer."""
        if self._watchdog_task:
            self._watchdog_task.cancel()
        self._watchdog_task = self.hass.async_create_task(self._async_watchdog_timeout())

    async def _async_watchdog_timeout(self) -> None:
        """Executes when no data packets arrive within the window threshold."""
        try:
            await asyncio.sleep(WATCHDOG_TIMEOUT)
            _LOGGER.warning(
                "No BLE data received for %d seconds from %s (Stale Connection). Forcing proxy roam.", 
                WATCHDOG_TIMEOUT, self.address
            )
            await self.async_disconnect()
        except asyncio.CancelledError:
            pass

    def _notification_handler(self, characteristic: Any, data: bytearray) -> None:
        """Decode raw BLE Heart Rate byte arrays and kick the watchdog."""
        self._reset_watchdog()  # <--- Fresh packet arrived! Kick the countdown back to 30.
        
        flags = data[0]
        if flags & 0x01:
            self.heart_rate = int.from_bytes(data[1:3], byteorder="little")
        else:
            self.heart_rate = data[1]
        self._notify_listeners()

    async def async_disconnect(self) -> None:
        """Clean breakdown of socket arrays to keep DB history uncorrupted."""
        async with self._lock:
            # Cancel the watchdog loop so it doesn't trigger a circular disconnect loop
            if self._watchdog_task:
                self._watchdog_task.cancel()
                self._watchdog_task = None
                
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
