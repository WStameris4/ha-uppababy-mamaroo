"""Entities read state reports and send the right bytes."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mamaroo import protocol
from custom_components.mamaroo.const import CONF_PAIRING_ID, DOMAIN
from custom_components.mamaroo.device import MamarooDevice

MOVING = protocol.parse_status(bytes.fromhex("53050504040101010000380e0003000000000000"))
IDLE = protocol.parse_status(bytes.fromhex("5301000000010000000038400003000000000000"))
TIMED = protocol.parse_status(bytes.fromhex("5305010000010100000007070102000000000000"))


@pytest.fixture
async def send(hass: HomeAssistant, request: pytest.FixtureRequest) -> AsyncGenerator[AsyncMock]:
    """Set up the swing with the state named by the test's `state` mark."""
    state = request.node.get_closest_marker("state").args[0]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="04830803-c1c2-0483-0803-c1c204830803",
        data={CONF_PAIRING_ID: "762ac690-8736-4067-b1c8-9aad0c05b375"},
    )
    entry.add_to_hass(hass)
    send = AsyncMock()
    with (
        patch.object(MamarooDevice, "start"),
        patch.object(MamarooDevice, "stop", AsyncMock()),
        patch.object(MamarooDevice, "available", new_callable=PropertyMock, return_value=True),
        patch.object(MamarooDevice, "send", send),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        entry.runtime_data._status(state)
        await hass.async_block_till_done()
        yield send


@pytest.mark.state(MOVING)
async def test_states_follow_the_report(hass: HomeAssistant, send: AsyncMock) -> None:
    fan = hass.states.get("fan.mamaroo")
    assert fan.state == "on"
    assert fan.attributes["preset_mode"] == "wave"
    assert fan.attributes["percentage"] == 100
    assert hass.states.get("select.mamaroo_sound_track").state == "sound_4"
    assert hass.states.get("number.mamaroo_volume").state == "4"
    assert hass.states.get("switch.mamaroo_sound").state == "on"


@pytest.mark.state(IDLE)
async def test_controls_send_the_panel_commands(hass: HomeAssistant, send: AsyncMock) -> None:
    await hass.services.async_call(
        "fan", "set_preset_mode",
        {"entity_id": "fan.mamaroo", "preset_mode": "sway"}, blocking=True,
    )
    assert [c.args[0] for c in send.call_args_list] == [
        bytes.fromhex("430403"), bytes.fromhex("430201"),
    ]
    send.reset_mock()
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.mamaroo_sound_track", "option": "sound_2"}, blocking=True,
    )
    assert [c.args[0] for c in send.call_args_list] == [
        bytes.fromhex("430502"), bytes.fromhex("430301"),
    ]
    send.reset_mock()
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.mamaroo_volume", "value": 3}, blocking=True,
    )
    assert send.call_args.args[0] == bytes.fromhex("430703")


@pytest.mark.state(TIMED)
async def test_timer_shows_minutes_left_and_sets_minutes(
    hass: HomeAssistant, send: AsyncMock
) -> None:
    assert hass.states.get("number.mamaroo_shutdown_timer").state == "30"
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.mamaroo_shutdown_timer", "value": 45}, blocking=True,
    )
    assert send.call_args.args[0] == bytes.fromhex("430a2d")


@pytest.mark.state(IDLE)
async def test_timer_off_reads_zero(hass: HomeAssistant, send: AsyncMock) -> None:
    # Idle, the swing reports a 4 h countdown that is not an active timer.
    assert hass.states.get("number.mamaroo_shutdown_timer").state == "0"
