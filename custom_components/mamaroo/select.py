"""Motion pattern and built-in sound selection."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MamarooConfigEntry, protocol
from .entity import MamarooEntity

# Order as printed on the panel and in the manual; the swing numbers them 1-5.
MOTIONS = ["cruise", "bounce", "sway", "rock", "wave"]

# The app's names for the mamaRoo5's sounds 1-5 (5 plays audio streamed over
# Bluetooth); the swing reports 0 until one is chosen.
SOUNDS = ["jingle", "bliss", "chirp", "tide", "bluetooth_streaming"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MamarooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the motion and sound selects."""
    async_add_entities([MamarooMotionPattern(entry), MamarooSound(entry)])


class MamarooMotionPattern(MamarooEntity, SelectEntity):
    """Which motion pattern runs; choosing one starts it, like the panel."""

    _attr_options = MOTIONS

    def __init__(self, entry: MamarooConfigEntry) -> None:
        super().__init__(entry, "motion_pattern")

    @property
    def current_option(self) -> str | None:
        """The current pattern, also shown while stopped."""
        index = self.state_data.motion - 1
        return MOTIONS[index] if 0 <= index < len(MOTIONS) else None

    async def async_select_option(self, option: str) -> None:
        """Switch to a pattern and start moving."""
        state = self.state_data
        commands = [] if state.power else [protocol.set_flag(protocol.FIELD_POWER, True)]
        commands.append(protocol.set_field(protocol.FIELD_MOTION, MOTIONS.index(option) + 1))
        if not state.motion_enabled:
            commands.append(protocol.set_flag(protocol.FIELD_MOTION_ENABLED, True))
        await self._send(*commands)


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
