"""Protocol encoding and decoding."""

from __future__ import annotations

from uuid import UUID

import pytest

from custom_components.mamaroo import protocol

PAIRING_ID = UUID("00112233-4455-6677-8899-aabbccddeeff")


def test_field_writes() -> None:
    assert protocol.set_flag(protocol.FIELD_POWER, True) == bytes.fromhex("430101")
    assert protocol.set_flag(protocol.FIELD_MOTION_ENABLED, False) == bytes.fromhex("430200")
    assert protocol.set_field(protocol.FIELD_SPEED, 5) == bytes.fromhex("430605")
    assert protocol.set_timer(300) == bytes.fromhex("430a012c")


def test_pairing_commands() -> None:
    assert protocol.get_bluetooth_id() == b"\xb0"
    assert protocol.begin_pairing() == bytes.fromhex("b200")
    # UUIDs go on the wire big-endian (most significant long first).
    assert protocol.set_pairing_id(PAIRING_ID) == bytes.fromhex(
        "b101" "00112233445566778899aabbccddeeff"
    )
    assert protocol.handshake(PAIRING_ID) == bytes.fromhex(
        "b201" "00112233445566778899aabbccddeeff"
    )


def test_parse_bluetooth_id() -> None:
    reply = protocol.parse_bluetooth_id(bytes.fromhex("b000") + PAIRING_ID.bytes)
    assert reply == protocol.BluetoothIdReply(0, PAIRING_ID)
    assert protocol.parse_bluetooth_id(bytes.fromhex("b001")).bluetooth_id is None


def test_handshake_result() -> None:
    assert protocol.handshake_ok(bytes.fromhex("b30100"))
    assert not protocol.handshake_ok(bytes.fromhex("b30101"))
    assert not protocol.handshake_ok(bytes.fromhex("b301"))


def test_parse_status() -> None:
    #           op mo sp so vo pw me se -- -- timer ta -- pr lk
    data = bytes.fromhex("53 02 03 01 04 01 01 00 00 00 00 1e 01 00 02 01".replace(" ", ""))
    assert protocol.parse_status(data) == protocol.SwingState(
        motion=2,
        speed=3,
        sound=1,
        volume=4,
        power=True,
        motion_enabled=True,
        sound_enabled=False,
        timer_active=True,
        timer_seconds=30,
        preset=2,
        panel_locked=True,
    )


def test_parse_status_rejects_other_packets() -> None:
    with pytest.raises(ValueError):
        protocol.parse_status(bytes.fromhex("b30100"))


def test_parse_captured_packets() -> None:
    # Wave at speed 5, sound 4 at volume 4, all on, 4 h timer counting down.
    moving = protocol.parse_status(bytes.fromhex("53050504040101010000380e0003000000000000"))
    assert (moving.motion, moving.speed, moving.sound, moving.volume) == (5, 5, 4, 4)
    assert moving.power and moving.motion_enabled and moving.sound_enabled
    assert moving.timer_seconds == 0x380E
    # The 0x41 acknowledgement of a write carries the same layout.
    ack = protocol.parse_status(bytes.fromhex("41010100000101010000383d0003000000000000"))
    assert ack.sound_enabled and ack.motion == 1 and ack.speed == 1
