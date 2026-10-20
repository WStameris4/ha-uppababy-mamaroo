"""The UPPAbaby Mamaroo Smart Swing integration."""

from __future__ import annotations

from uuid import UUID

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ADDRESS, CONF_PAIRING_ID, DOMAIN, SERVICE_SEND_COMMAND
from .device import MamarooDevice, MamarooError

PLATFORMS = [Platform.FAN, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type MamarooConfigEntry = ConfigEntry[MamarooDevice]

SEND_COMMAND_SCHEMA = vol.Schema({vol.Required("data"): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the raw-command service."""

    async def send_command(call: ServiceCall) -> None:
        try:
            data = bytes.fromhex(call.data["data"].replace(" ", ""))
        except ValueError as err:
            raise ServiceValidationError(f"not hex: {call.data['data']}") from err
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries or not data:
            raise ServiceValidationError("no swing configured or empty command")
        try:
            await entries[0].runtime_data.send(data)
        except MamarooError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_COMMAND, send_command, schema=SEND_COMMAND_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MamarooConfigEntry) -> bool:
    """Set up the swing from a config entry."""
    device = MamarooDevice(
        hass, UUID(entry.data[CONF_PAIRING_ID]), entry.data.get(CONF_ADDRESS)
    )
    entry.runtime_data = device
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    device.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MamarooConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop()
    return unloaded
