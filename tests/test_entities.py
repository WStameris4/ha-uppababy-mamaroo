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
OFF = protocol.parse_status(bytes.fromhex("5305000000000000000038400003000000000000"))
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
    assert hass.states.get("switch.mamaroo_power").state == "on"
    assert hass.states.get("switch.mamaroo_motion").state == "on"
    assert hass.states.get("select.mamaroo_motion_pattern").state == "wave"
    assert hass.states.get("number.mamaroo_speed").state == "5"
    assert hass.states.get("switch.mamaroo_sound").state == "on"
    assert hass.states.get("select.mamaroo_sound_track").state == "tide"
    assert hass.states.get("number.mamaroo_volume").state == "4"
    assert hass.states.get("fan.mamaroo") is None


@pytest.mark.state(IDLE)
async def test_stopped_swing(hass: HomeAssistant, send: AsyncMock) -> None:
    assert hass.states.get("switch.mamaroo_motion").state == "off"
    # The pattern is still shown; speed has never been reported, so unknown.
    assert hass.states.get("select.mamaroo_motion_pattern").state == "cruise"
    assert hass.states.get("number.mamaroo_speed").state == "unknown"


@pytest.mark.state(MOVING)
async def test_last_values_stay_while_off(hass: HomeAssistant, send: AsyncMock) -> None:
    # Stopping motion and sound makes the swing report 0 for all three.
    hass.config_entries.async_entries(DOMAIN)[0].runtime_data._status(OFF)
    await hass.async_block_till_done()
    assert hass.states.get("switch.mamaroo_motion").state == "off"
    assert hass.states.get("number.mamaroo_speed").state == "5"
    assert hass.states.get("select.mamaroo_sound_track").state == "tide"
    assert hass.states.get("number.mamaroo_volume").state == "4"


async def _call(hass: HomeAssistant, domain: str, service: str, **data) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)


def _sent(send: AsyncMock) -> list[bytes]:
    return [call.args[0] for call in send.call_args_list]


@pytest.mark.state(IDLE)
async def test_motion_switch(hass: HomeAssistant, send: AsyncMock) -> None:
    await _call(hass, "switch", "turn_on", entity_id="switch.mamaroo_motion")
    assert _sent(send) == [bytes.fromhex("430201")]
    send.reset_mock()
    await _call(hass, "switch", "turn_off", entity_id="switch.mamaroo_motion")
    assert _sent(send) == [bytes.fromhex("430200")]


@pytest.mark.state(OFF)
async def test_motion_switch_powers_on_first(hass: HomeAssistant, send: AsyncMock) -> None:
    await _call(hass, "switch", "turn_on", entity_id="switch.mamaroo_motion")
    assert _sent(send) == [bytes.fromhex("430101"), bytes.fromhex("430201")]


@pytest.mark.state(IDLE)
async def test_speed_and_volume(hass: HomeAssistant, send: AsyncMock) -> None:
    await _call(hass, "number", "set_value", entity_id="number.mamaroo_speed", value=3)
    await _call(hass, "number", "set_value", entity_id="number.mamaroo_volume", value=2)
    assert _sent(send) == [bytes.fromhex("430603"), bytes.fromhex("430702")]


@pytest.mark.state(IDLE)
async def test_choosing_a_motion_starts_it(hass: HomeAssistant, send: AsyncMock) -> None:
    await _call(
        hass, "select", "select_option",
        entity_id="select.mamaroo_motion_pattern", option="rock",
    )
    assert _sent(send) == [bytes.fromhex("430404"), bytes.fromhex("430201")]


@pytest.mark.state(MOVING)
async def test_switching_motion_while_moving(hass: HomeAssistant, send: AsyncMock) -> None:
    await _call(
        hass, "select", "select_option",
        entity_id="select.mamaroo_motion_pattern", option="bounce",
    )
    assert _sent(send) == [bytes.fromhex("430402")]


@pytest.mark.state(IDLE)
async def test_choosing_a_sound_turns_sound_on(hass: HomeAssistant, send: AsyncMock) -> None:
    await _call(
        hass, "select", "select_option",
        entity_id="select.mamaroo_sound_track", option="bliss",
    )
    assert _sent(send) == [bytes.fromhex("430502"), bytes.fromhex("430301")]


@pytest.mark.state(TIMED)
async def test_timer_shows_minutes_left_and_sets_minutes(
    hass: HomeAssistant, send: AsyncMock
) -> None:
    assert hass.states.get("number.mamaroo_shutdown_timer").state == "30"
    await _call(hass, "number", "set_value", entity_id="number.mamaroo_shutdown_timer", value=45)
    assert _sent(send) == [bytes.fromhex("430a2d")]


@pytest.mark.state(IDLE)
async def test_timer_off_reads_zero(hass: HomeAssistant, send: AsyncMock) -> None:
    # Idle, the swing reports a 4 h countdown that is not an active timer.
    assert hass.states.get("number.mamaroo_shutdown_timer").state == "0"
