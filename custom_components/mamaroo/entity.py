"""Base entity for the Mamaroo integration."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import MamarooConfigEntry
from .const import DOMAIN
from .device import MamarooDevice, MamarooError
from .protocol import SwingState


class MamarooEntity(Entity):
    """An entity backed by the swing's state reports."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: MamarooConfigEntry, key: str) -> None:
        self._device: MamarooDevice = entry.runtime_data
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            manufacturer="UPPAbaby",
            model="Mamaroo Smart Swing",
            name="Mamaroo",
        )

    @property
    def available(self) -> bool:
        """Available while connected and reporting state."""
        return self._device.available and self._device.state is not None

    @property
    def state_data(self) -> SwingState:
        """The latest state report."""
        assert self._device.state is not None
        return self._device.state

    async def async_added_to_hass(self) -> None:
        """Follow state reports."""
        self.async_on_remove(self._device.add_listener(self.async_write_ha_state))

    async def _send(self, *commands: bytes) -> None:
        try:
            for command in commands:
                await self._device.send(command)
        except MamarooError as err:
            raise HomeAssistantError(str(err)) from err
