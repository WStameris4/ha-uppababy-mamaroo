"""Byte-level protocol of the Mamaroo Smart Swing (mamaRoo5).

Decoded from the UPPAbaby Connect Android app. Every command is written to a
single characteristic, and the swing answers on the same characteristic with
a notification that starts with the opcode it is answering. Unsolicited state
reports start with 0x53 ("S").
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

OP_ACK = 0x41  # "A": state after a 0x43 write, same layout as a status report
OP_SET = 0x43  # "C": set one field, 0x43 <field> <value...>
OP_STATUS = 0x53  # "S": state report from the swing, about once a second
OP_GET_BLUETOOTH_ID = 0xB0
OP_SET_PAIRING_ID = 0xB1
OP_HANDSHAKE = 0xB2
OP_HANDSHAKE_RESULT = 0xB3
OP_SAVE_PRESET = 0xDA
OP_SELECT_PRESET = 0xDB
OP_GET_PRESET = 0xDC
OP_RESET_PRESET = 0xDD
OP_SET_WIFI = 0xF8

FIELD_POWER = 0x01
FIELD_MOTION_ENABLED = 0x02
FIELD_SOUND_ENABLED = 0x03
FIELD_MOTION = 0x04
FIELD_SOUND = 0x05
FIELD_SPEED = 0x06
FIELD_VOLUME = 0x07
FIELD_TIMER = 0x0A
FIELD_PANEL_LOCK = 0x0B


def set_field(field: int, value: int) -> bytes:
    """Build a one-byte field write."""
    return bytes((OP_SET, field, value & 0xFF))


def set_flag(field: int, on: bool) -> bytes:
    """Build a boolean field write."""
    return set_field(field, 1 if on else 0)


def set_timer(minutes: int) -> bytes:
    """Build a shutdown-timer write (big-endian u16; 0 cancels)."""
    return bytes((OP_SET, FIELD_TIMER, (minutes >> 8) & 0xFF, minutes & 0xFF))


def get_bluetooth_id() -> bytes:
    """Ask the swing for its Bluetooth ID."""
    return bytes((OP_GET_BLUETOOTH_ID,))


def begin_pairing() -> bytes:
    """Open a new pairing (handshake version 0, no ID)."""
    return bytes((OP_HANDSHAKE, 0x00))


def set_pairing_id(pairing_id: UUID) -> bytes:
    """Register a new pairing ID with the swing."""
    return bytes((OP_SET_PAIRING_ID, 0x01)) + pairing_id.bytes


def handshake(pairing_id: UUID) -> bytes:
    """Prove a stored pairing ID after connecting."""
    return bytes((OP_HANDSHAKE, 0x01)) + pairing_id.bytes


def select_preset(number: int) -> bytes:
    """Start preset 1-3."""
    return bytes((OP_SELECT_PRESET, number & 0xFF))


@dataclass(frozen=True, slots=True)
class BluetoothIdReply:
    """Reply to get_bluetooth_id."""

    status: int
    bluetooth_id: UUID | None


def parse_bluetooth_id(data: bytes) -> BluetoothIdReply:
    """Parse a 0xB0 reply: status, then a 16-byte ID when status is 0."""
    status = data[1]
    if status == 0 and len(data) >= 18:
        return BluetoothIdReply(status, UUID(bytes=bytes(data[2:18])))
    return BluetoothIdReply(status, None)


def handshake_ok(data: bytes) -> bool:
    """A 0xB3 handshake result succeeds when its third byte is 0."""
    return len(data) >= 3 and data[0] == OP_HANDSHAKE_RESULT and data[2] == 0


@dataclass(frozen=True, slots=True)
class SwingState:
    """State report from a mamaRoo5 (the app's MMR5 status layout).

    Confirmed against the panel: motion 1-5 = the panel's icons left to right,
    speed 1-5, sound 1-4, volume 1-4; the timer counts down in seconds while
    moving (14400 = 4 h when idle).
    """

    motion: int
    speed: int
    sound: int
    volume: int
    power: bool
    motion_enabled: bool
    sound_enabled: bool
    timer_active: bool
    timer_seconds: int
    preset: int
    panel_locked: bool


def parse_status(data: bytes) -> SwingState:
    """Parse a 0x53 state report or a 0x41 write acknowledgement."""
    if len(data) < 13 or data[0] not in (OP_STATUS, OP_ACK):
        raise ValueError(f"not a status packet: {data.hex()}")
    return SwingState(
        motion=data[1],
        speed=data[2],
        sound=data[3],
        volume=data[4],
        power=data[5] == 1,
        motion_enabled=data[6] == 1,
        sound_enabled=data[7] == 1,
        timer_seconds=(data[10] << 8) | data[11],
        timer_active=data[12] == 1,
        preset=data[14] if len(data) > 14 else 0,
        panel_locked=len(data) > 15 and data[15] == 1,
    )
