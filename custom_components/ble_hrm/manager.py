"""Shared Connection Manager for BLE HRM."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .const import (
    BATTERY_LEVEL_UUID,
    HEART_RATE_MEASUREMENT_UUID,
)

_LOGGER = logging.getLogger(__name__)
WATCHDOG_TIMEOUT = 30

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

    def setup_tracking(self):
        """Bind connection manager hooks directly to HA core tracking."""
        unload_track = bluetooth.async_register_callback(
            self.hass,
            self.handle_availability_change,
            bluetooth.BluetoothCallbackMatcher(address=self.address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        
        if bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True):
            self.hass.async_create_task(self.async_connect())

        return unload_track

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
                self._reset_watchdog()
            except Exception as err:
                _LOGGER.debug("Proxy connection attempt deferred for %s: %s", self.address, err)
                self.connected = False
                self.client = None

    async def async_force_reconnect(self) -> None:
        """Forcefully break any existing locks and attempt an instant connection."""
        _LOGGER.info("Manual force reconnect triggered for strap at %s", self.address)
        await self.async_disconnect()
        # Give the proxy a minor breath interval to cycle the socket
        await asyncio.sleep(0.5)
        if bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True):
            self.hass.async_create_task(self.async_connect())

    def _handle_unexpected_disconnect(self, client: BleakClient) -> None:
        """Handle un-scheduled peripheral disconnections safely."""
        _LOGGER.debug("Strap at %s disconnected from proxy socket unexpectedly.", self.address)
        self.hass.async_create_task(self.async_disconnect())

    def _reset_watchdog(self) -> None:
        """Resets the stale data watchdog timer."""
        if self._watchdog_task:
            self._watchdog_task.cancel()
        self._watchdog_task = self.hass.async_create_task(self._async_watchdog_timeout())

    async def _async_watchdog_timeout(self) -> None:
        """Executes when no data packets arrive within the window threshold."""
        try:
            await asyncio.sleep(WATCHDOG_TIMEOUT)
            _LOGGER.warning("Watchdog timeout expired for %s. Forcing proxy roam.", self.address)
            await self.async_disconnect()
        except asyncio.CancelledError:
            pass

    def _notification_handler(self, characteristic: Any, data: bytearray) -> None:
        """Decode raw BLE Heart Rate byte arrays and kick the watchdog."""
        self._reset_watchdog()
        flags = data[0]
        if flags & 0x01:
            self.heart_rate = int.from_bytes(data[1:3], byteorder="little")
        else:
            self.heart_rate = data[1]
        self._notify_listeners()

    async def async_disconnect(self) -> None:
        """Clean breakdown of socket arrays to keep DB history uncorrupted."""
        async with self._lock:
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
