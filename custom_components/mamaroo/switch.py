"""Power, motion, sound and panel-lock switches."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MamarooConfigEntry, protocol
from .entity import MamarooEntity


@dataclass(frozen=True, kw_only=True)
class MamarooSwitchDescription(SwitchEntityDescription):
    """A boolean field of the swing."""

    field: int
    value: Callable[[protocol.SwingState], bool]
    # Turning on also powers the swing on, as the panel does.
    needs_power: bool = False


SWITCHES = (
    MamarooSwitchDescription(
        key="power", field=protocol.FIELD_POWER, value=lambda s: s.power
    ),
    MamarooSwitchDescription(
        key="motion",
        field=protocol.FIELD_MOTION_ENABLED,
        value=lambda s: s.power and s.motion_enabled,
        needs_power=True,
    ),
    MamarooSwitchDescription(
        key="sound",
        field=protocol.FIELD_SOUND_ENABLED,
        value=lambda s: s.power and s.sound_enabled,
        needs_power=True,
    ),
    MamarooSwitchDescription(
        key="panel_lock",
        field=protocol.FIELD_PANEL_LOCK,
        value=lambda s: s.panel_locked,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MamarooConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switches."""
    async_add_entities(MamarooSwitch(entry, description) for description in SWITCHES)


class MamarooSwitch(MamarooEntity, SwitchEntity):
    """One boolean field."""

    entity_description: MamarooSwitchDescription

    def __init__(
        self, entry: MamarooConfigEntry, description: MamarooSwitchDescription
    ) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Field value from the last report."""
        return self.entity_description.value(self.state_data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        description = self.entity_description
        commands = []
        if description.needs_power and not self.state_data.power:
            commands.append(protocol.set_flag(protocol.FIELD_POWER, True))
        commands.append(protocol.set_flag(description.field, True))
        await self._send(*commands)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._send(protocol.set_flag(self.entity_description.field, False))
