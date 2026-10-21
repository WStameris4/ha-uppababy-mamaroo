"""Choosing which advertisement to connect to."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from homeassistant.core import HomeAssistant

from custom_components.mamaroo.const import SERVICE_UUID
from custom_components.mamaroo.device import MamarooDevice, latest_swing

NOW = 1000.0


def _info(address: str, rssi: int, age: float, uuids: list[str] | None = None):
    return SimpleNamespace(
        address=address,
        device=SimpleNamespace(address=address),
        rssi=rssi,
        time=NOW - age,
        service_uuids=[SERVICE_UUID] if uuids is None else uuids,
    )


def _patched(infos: list):
    return (
        patch(
            "custom_components.mamaroo.device.bluetooth.async_discovered_service_info",
            return_value=infos,
        ),
        patch("custom_components.mamaroo.device.monotonic_time_coarse", return_value=NOW),
    )


def _pick(hass: HomeAssistant, infos: list, **kwargs) -> str | None:
    discovered, clock = _patched(infos)
    with discovered, clock:
        device = latest_swing(hass, **kwargs)
    return device.address if device else None


def _device_pick(device: MamarooDevice, infos: list, failures: list[str]) -> str | None:
    discovered, clock = _patched(infos)
    with discovered, clock:
        for address in failures:
            device._record_failure(address)
        picked = device._pick()
    return picked.address if picked else None


async def test_strongest_fresh_swing_wins(hass: HomeAssistant) -> None:
    # A faint identity heard more recently must not win.
    infos = [_info("AA:00:00:00:00:01", -47, age=5), _info("AA:00:00:00:00:02", -75, age=1)]
    assert _pick(hass, infos) == "AA:00:00:00:00:01"


async def test_stale_and_foreign_devices_are_ignored(hass: HomeAssistant) -> None:
    infos = [
        _info("AA:00:00:00:00:01", -40, age=120),
        _info("AA:00:00:00:00:03", -30, age=1, uuids=["0000180f-0000-1000-8000-00805f9b34fb"]),
        _info("AA:00:00:00:00:02", -80, age=2),
    ]
    assert _pick(hass, infos) == "AA:00:00:00:00:02"


async def test_nothing_in_range(hass: HomeAssistant) -> None:
    assert _pick(hass, [_info("AA:00:00:00:00:01", -40, age=300)]) is None


async def test_last_working_address_wins_while_advertising(hass: HomeAssistant) -> None:
    infos = [_info("AA:00:00:00:00:01", -47, age=5), _info("AA:00:00:00:00:02", -75, age=1)]
    assert _pick(hass, infos, prefer="AA:00:00:00:00:02") == "AA:00:00:00:00:02"
    assert _pick(hass, infos, prefer="AA:00:00:00:00:09") == "AA:00:00:00:00:01"


async def test_fewest_failures_wins_then_loudest(hass: HomeAssistant) -> None:
    infos = [_info("AA:00:00:00:00:01", -47, age=5), _info("AA:00:00:00:00:02", -75, age=1)]
    assert _pick(hass, infos, failures={"AA:00:00:00:00:01": 1}) == "AA:00:00:00:00:02"
    # Equal failures: back to the loudest, so neither is ever shut out.
    both = {"AA:00:00:00:00:01": 1, "AA:00:00:00:00:02": 1}
    assert _pick(hass, infos, failures=both) == "AA:00:00:00:00:01"


async def test_preferred_address_survives_a_quiet_spell(hass: HomeAssistant) -> None:
    # Connected identities stop advertising, so the one that worked goes quiet.
    infos = [_info("AA:00:00:00:00:01", -50, age=200), _info("AA:00:00:00:00:02", -75, age=1)]
    assert _pick(hass, infos, prefer="AA:00:00:00:00:01") == "AA:00:00:00:00:01"
    assert _pick(hass, infos) == "AA:00:00:00:00:02"


async def test_retired_address_is_dropped_after_misses(hass: HomeAssistant) -> None:
    # The swing retires addresses on a timer; a retired one lingers in history.
    infos = [_info("AA:00:00:00:00:01", -50, age=200), _info("AA:00:00:00:00:02", -75, age=1)]
    device = MamarooDevice(hass, uuid4(), "AA:00:00:00:00:01")
    assert _device_pick(device, infos, ["AA:00:00:00:00:01"]) == "AA:00:00:00:00:01"
    assert _device_pick(device, infos, ["AA:00:00:00:00:01"]) == "AA:00:00:00:00:02"


async def test_a_dead_address_never_takes_over(hass: HomeAssistant) -> None:
    # 01 is the swing's real address, refusing for a while; 02 never works.
    infos = [_info("AA:00:00:00:00:01", -63, age=1), _info("AA:00:00:00:00:02", -83, age=1)]
    device = MamarooDevice(hass, uuid4())
    picks = []
    for _ in range(6):
        picked = _device_pick(device, infos, [])
        picks.append(picked)
        _device_pick(device, infos, [picked])
    assert picks.count("AA:00:00:00:00:01") == 3
