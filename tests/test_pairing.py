"""Pairing, replayed from the exchange captured from a real swing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from homeassistant.core import HomeAssistant

from custom_components.mamaroo.device import MamarooError, async_pair

BLUETOOTH_ID = UUID("04830803-c1c2-0483-0803-c1c204830803")
PAD = bytes(18)


class FakeClient:
    """A BleakClient that answers writes the way the swing did."""

    def __init__(self, handshake_result: bytes = bytes.fromhex("b30100")) -> None:
        self.services = SimpleNamespace(
            get_characteristic=lambda _uuid: SimpleNamespace(properties=["write", "notify"])
        )
        self.is_connected = True
        self.written: list[bytes] = []
        self._handshake_result = handshake_result
        self._notify = None

    async def start_notify(self, _char, callback) -> None:
        self._notify = callback
        callback(None, bytearray(20))  # the swing's initial empty value

    async def write_gatt_char(self, _char, data: bytes, response: bool) -> None:
        self.written.append(bytes(data))
        if data == b"\xb0":
            self._notify(None, bytearray(b"\xb0\x00" + BLUETOOTH_ID.bytes + b"\x00\x00"))
            self._notify(None, bytearray(b"\xb2\x01" + PAD))  # unprompted
        elif data == b"\xb2\x00":
            self._notify(None, bytearray(b"\xb1\x01" + PAD))
        elif data[:2] == b"\xb1\x01":
            self._notify(None, bytearray(self._handshake_result.ljust(20, b"\x00")))

    async def disconnect(self) -> None:
        self.is_connected = False


async def _pair(hass: HomeAssistant, client: FakeClient):
    with (
        patch(
            "custom_components.mamaroo.device.latest_swing",
            return_value=SimpleNamespace(address="7E:17:C2:25:47:0E", name="mamaRoo5"),
        ),
        patch(
            "custom_components.mamaroo.device.establish_connection",
            AsyncMock(return_value=client),
        ),
    ):
        return await async_pair(hass)


async def test_pairing_follows_the_swing(hass: HomeAssistant) -> None:
    client = FakeClient()
    bluetooth_id, pairing_id = await _pair(hass, client)
    assert bluetooth_id == BLUETOOTH_ID
    assert client.written == [
        b"\xb0",
        b"\xb2\x00",
        b"\xb1\x01" + pairing_id.bytes,
    ]
    assert not client.is_connected


async def test_refused_pairing_raises(hass: HomeAssistant) -> None:
    with pytest.raises(MamarooError, match="refused"):
        await _pair(hass, FakeClient(handshake_result=bytes.fromhex("b30101")))
