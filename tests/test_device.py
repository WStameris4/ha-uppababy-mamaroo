"""Choosing which advertisement to connect to."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.mamaroo.const import SERVICE_UUID
from custom_components.mamaroo.device import latest_swing

NOW = 1000.0


def _info(address: str, rssi: int, age: float, uuids: list[str] | None = None):
    return SimpleNamespace(
        address=address,
        device=SimpleNamespace(address=address),
        rssi=rssi,
        time=NOW - age,
        service_uuids=[SERVICE_UUID] if uuids is None else uuids,
    )


def _pick(hass: HomeAssistant, infos: list, **kwargs) -> str | None:
    with (
        patch(
            "custom_components.mamaroo.device.bluetooth.async_discovered_service_info",
            return_value=infos,
        ),
        patch("custom_components.mamaroo.device.monotonic_time_coarse", return_value=NOW),
    ):
        device = latest_swing(hass, **kwargs)
    return device.address if device else None


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


async def test_failed_addresses_are_avoided(hass: HomeAssistant) -> None:
    infos = [_info("AA:00:00:00:00:01", -47, age=5), _info("AA:00:00:00:00:02", -75, age=1)]
    assert _pick(hass, infos, avoid=["AA:00:00:00:00:01"]) == "AA:00:00:00:00:02"
    # With everything avoided, still try the loudest rather than nothing.
    assert _pick(hass, infos, avoid=["AA:00:00:00:00:01", "AA:00:00:00:00:02"]) == "AA:00:00:00:00:01"
