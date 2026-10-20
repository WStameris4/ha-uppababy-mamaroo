"""Sound volume and the shutdown timer."""

from __future__ import annotations

import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MamarooConfigEntry, protocol
from .entity import MamarooEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MamarooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the volume and timer numbers."""
    async_add_entities([MamarooVolume(entry), MamarooTimer(entry)])


class MamarooVolume(MamarooEntity, NumberEntity):
    """Volume, 1-4 like the panel's lights."""

    _attr_native_min_value = 1
    _attr_native_max_value = 4
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: MamarooConfigEntry) -> None:
        super().__init__(entry, "volume")

    @property
    def native_value(self) -> float | None:
        """Current volume, or none before a sound has been chosen."""
        return self.state_data.volume or None

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        await self._send(protocol.set_field(protocol.FIELD_VOLUME, int(value)))


class MamarooTimer(MamarooEntity, NumberEntity):
    """Shutdown timer in minutes: remaining time while set, 0 when off."""

    _attr_native_min_value = 0
    _attr_native_max_value = 240
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: MamarooConfigEntry) -> None:
        super().__init__(entry, "shutdown_timer")

    @property
    def native_value(self) -> float | None:
        """Minutes left, rounded up; the swing reports seconds."""
        state = self.state_data
        return math.ceil(state.timer_seconds / 60) if state.timer_active else 0

    async def async_set_native_value(self, value: float) -> None:
        """Set the timer; 0 cancels it."""
        await self._send(protocol.set_timer(int(value)))
