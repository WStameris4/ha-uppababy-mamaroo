"""Pairing, replayed from the exchange captured from a real swing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from homeassistant.core import HomeAssistant

from custom_components.mamaroo.device import MamarooDevice, MamarooError, async_pair

BLUETOOTH_ID = UUID("04830803-c1c2-0483-0803-c1c204830803")
PAD = bytes(18)


DIS = {
    "00002a26-0000-1000-8000-00805f9b34fb": b"1.2.3\x00",
    "00002a27-0000-1000-8000-00805f9b34fb": b"B",
}


class FakeServices:
    """The swing's GATT table: its control service plus Device Information."""

    def __init__(self) -> None:
        self._services = [
            SimpleNamespace(
                uuid="622d0100-2416-0fa7-e132-2f1495cc2ce0",
                characteristics=[
                    SimpleNamespace(
                        uuid="622d0101-2416-0fa7-e132-2f1495cc2ce0",
                        properties=["read", "write", "notify"],
                    )
                ],
            ),
            SimpleNamespace(
                uuid="0000180a-0000-1000-8000-00805f9b34fb",
                characteristics=[
                    SimpleNamespace(uuid=uuid, properties=["read"]) for uuid in DIS
                ],
            ),
        ]

    def __iter__(self):
        return iter(self._services)

    def get_characteristic(self, _uuid):
        return SimpleNamespace(properties=["write", "notify"])


class FakeClient:
    """A BleakClient that answers writes the way the swing did."""

    def __init__(self, handshake_result: bytes = bytes.fromhex("b30100")) -> None:
        self.services = FakeServices()
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
        elif data[:2] in (b"\xb1\x01", b"\xb2\x01"):
            self._notify(None, bytearray(self._handshake_result.ljust(20, b"\x00")))

    async def read_gatt_char(self, char) -> bytearray:
        return bytearray(DIS[char.uuid])

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
    bluetooth_id, pairing_id, address = await _pair(hass, client)
    assert bluetooth_id == BLUETOOTH_ID
    assert address == "7E:17:C2:25:47:0E"
    assert client.written == [
        b"\xb0",
        b"\xb2\x00",
        b"\xb1\x01" + pairing_id.bytes,
    ]
    assert not client.is_connected


async def test_refused_pairing_raises(hass: HomeAssistant) -> None:
    with pytest.raises(MamarooError, match="refused"):
        await _pair(hass, FakeClient(handshake_result=bytes.fromhex("b30101")))


async def _connect(hass: HomeAssistant, client: FakeClient) -> MamarooDevice:
    device = MamarooDevice(hass, PAIRING_ID)
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
        await device._connect()
    return device


PAIRING_ID = UUID("762ac690-8736-4067-b1c8-9aad0c05b375")


async def test_reconnect_asks_for_the_prompt_first(hass: HomeAssistant) -> None:
    client = FakeClient()
    device = await _connect(hass, client)
    # As the app does: b0 first, wait for the swing's b2 prompt, then prove the ID.
    assert client.written == [b"\xb0", b"\xb2\x01" + PAIRING_ID.bytes]
    assert device.available


async def test_reconnect_refused(hass: HomeAssistant) -> None:
    client = FakeClient(handshake_result=bytes.fromhex("b30101"))
    with pytest.raises(MamarooError, match="refused"):
        await _connect(hass, client)
    assert not client.is_connected


async def test_a_working_address_is_never_avoided(hass: HomeAssistant) -> None:
    device = MamarooDevice(hass, PAIRING_ID, "7E:17:C2:25:47:0E")
    device._record_failure("7E:17:C2:25:47:0E")
    device._record_failure("42:2D:8F:6D:FB:52")
    assert list(device._failed) == ["42:2D:8F:6D:FB:52"]


async def test_device_information_is_read_once(hass: HomeAssistant) -> None:
    reported = []
    device = await _connect(hass, FakeClient())
    device._on_info = reported.append
    await device._read_info()
    await device._read_info()
    assert device.info == {"firmware": "1.2.3", "hardware": "B"}
    assert reported == [device.info]
