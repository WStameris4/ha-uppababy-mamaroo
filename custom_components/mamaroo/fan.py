"""The swing's motion as a fan: on/off, speed and motion pattern."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from . import MamarooConfigEntry, protocol
from .entity import MamarooEntity

SPEED_RANGE = (1, 5)
# Order as printed on the panel and in the manual.
MOTIONS = ["cruise", "bounce", "sway", "rock", "wave"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MamarooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the motion entity."""
    async_add_entities([MamarooMotion(entry)])


class MamarooMotion(MamarooEntity, FanEntity):
    """Motion on/off, speed 1-5 and motion pattern."""

    _attr_name = None
    _attr_preset_modes = MOTIONS
    _attr_speed_count = SPEED_RANGE[1]
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
    )

    def __init__(self, entry: MamarooConfigEntry) -> None:
        super().__init__(entry, "motion")

    @property
    def is_on(self) -> bool:
        """Moving."""
        state = self.state_data
        return state.power and state.motion_enabled

    @property
    def percentage(self) -> int | None:
        """Speed as a percentage."""
        if not self.is_on or not self.state_data.speed:
            return 0
        return ranged_value_to_percentage(SPEED_RANGE, self.state_data.speed)

    @property
    def preset_mode(self) -> str | None:
        """Current motion pattern."""
        index = self.state_data.motion - 1
        return MOTIONS[index] if 0 <= index < len(MOTIONS) else None

    def _power_on(self) -> list[bytes]:
        return [] if self.state_data.power else [
            protocol.set_flag(protocol.FIELD_POWER, True)
        ]

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Start moving, optionally at a speed or pattern."""
        commands = self._power_on()
        if preset_mode is not None:
            commands.append(
                protocol.set_field(protocol.FIELD_MOTION, MOTIONS.index(preset_mode) + 1)
            )
        if percentage is not None:
            commands.append(
                protocol.set_field(
                    protocol.FIELD_SPEED,
                    math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage)),
                )
            )
        commands.append(protocol.set_flag(protocol.FIELD_MOTION_ENABLED, True))
        await self._send(*commands)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop moving."""
        await self._send(protocol.set_flag(protocol.FIELD_MOTION_ENABLED, False))

    async def async_set_percentage(self, percentage: int) -> None:
        """Set speed; 0 stops."""
        if percentage == 0:
            await self.async_turn_off()
            return
        await self.async_turn_on(percentage=percentage)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the motion pattern."""
        await self.async_turn_on(preset_mode=preset_mode)
