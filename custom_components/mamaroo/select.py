"""Built-in sound selection."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MamarooConfigEntry, protocol
from .entity import MamarooEntity

# Numbered as on the panel; the swing reports 0 until one is chosen.
SOUNDS = ["sound_1", "sound_2", "sound_3", "sound_4"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MamarooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sound select."""
    async_add_entities([MamarooSound(entry)])


class MamarooSound(MamarooEntity, SelectEntity):
    """Which built-in sound plays."""

    _attr_options = SOUNDS

    def __init__(self, entry: MamarooConfigEntry) -> None:
        super().__init__(entry, "sound_track")

    @property
    def current_option(self) -> str | None:
        """The selected sound, or none before one is chosen."""
        index = self.state_data.sound - 1
        return SOUNDS[index] if 0 <= index < len(SOUNDS) else None

    async def async_select_option(self, option: str) -> None:
        """Play a sound, turning sound on if it was off."""
        commands = [protocol.set_field(protocol.FIELD_SOUND, SOUNDS.index(option) + 1)]
        if not self.state_data.sound_enabled:
            commands.append(protocol.set_flag(protocol.FIELD_SOUND_ENABLED, True))
        await self._send(*commands)
