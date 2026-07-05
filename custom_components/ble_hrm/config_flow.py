"""Config flow for BLE HRM."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_DEVICE_ADDRESS, CONF_DEVICE_NAME, DOMAIN, HEART_RATE_SERVICE_UUID

_LOGGER = logging.getLogger(__name__)

class BLEHRMConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BLE HRM."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize configuration flow tracking arrays."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle automatic background discovery via Bluetooth proxy scans."""
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        name = discovery_info.name or f"HRM {discovery_info.address[-6:]}"
        self.context["title_placeholders"] = {"name": name}
        
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm automatic passive discovery pop-ups."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or self._discovery_info.address,
                data={
                    CONF_DEVICE_ADDRESS: self._discovery_info.address.upper(),
                    CONF_DEVICE_NAME: self._discovery_info.name,
                },
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name or self._discovery_info.address
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the interactive setup wizard (Scan, filter, deduplicate, and choose)."""
        if user_input is not None:
            selected_address = user_input[CONF_DEVICE_ADDRESS]
            
            if selected_address == "manual":
                return await self.async_step_manual()
                
            await self.async_set_unique_id(selected_address.upper())
            self._abort_if_unique_id_configured()
            
            friendly_name = self._discovered_devices.get(selected_address, selected_address)
            clean_name = friendly_name.split(" (")[0]
            
            return self.async_create_entry(
                title=clean_name,
                data={
                    CONF_DEVICE_ADDRESS: selected_address.upper(),
                    CONF_DEVICE_NAME: clean_name if "Unknown HRM Device" not in clean_name else f"HRM {selected_address[-6:]}",
                },
            )

        # 1. Fetch unique IDs of all integrations that have already been configured
        configured_addresses = {
            entry.unique_id for entry in self._async_current_entries()
            if entry.unique_id
        }

        # 2. Query Home Assistant's central Bluetooth cache for live proxy captures
        current_discoveries = async_discovered_service_info(self.hass, connectable=True)
        
        self._discovered_devices = {}
        for discovery in current_discoveries:
            if HEART_RATE_SERVICE_UUID in discovery.service_uuids:
                address = discovery.address.upper()
                
                # 3. Deduplication Check: Skip it if it's already added to Home Assistant
                if address in configured_addresses:
                    continue
                    
                name = discovery.name or "Unknown HRM Device"
                self._discovered_devices[address] = f"{name} ({address})"

        # Insert manual bypass hook
        self._discovered_devices["manual"] = "Configure a device address manually..."

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE_ADDRESS, 
                        description={"suggested_value": "Select discovered device"}
                    ): vol.In(self._discovered_devices)
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Fallback input window to type a known MAC address manually."""
        if user_input is not None:
            address = user_input[CONF_DEVICE_ADDRESS].upper()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=user_input.get(CONF_DEVICE_NAME) or f"HRM {address[-6:]}",
                data={
                    CONF_DEVICE_ADDRESS: address,
                    CONF_DEVICE_NAME: user_input.get(CONF_DEVICE_NAME),
                },
            )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ADDRESS): str,
                    vol.Optional(CONF_DEVICE_NAME): str,
                }
            ),
        )
