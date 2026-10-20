"""Sound volume."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MamarooConfigEntry, protocol
from .entity import MamarooEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MamarooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the volume number."""
    async_add_entities([MamarooVolume(entry)])


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
