"""BLE connection to a Mamaroo Smart Swing."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import contextlib
import logging
from uuid import UUID, uuid4

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from bluetooth_data_tools import monotonic_time_coarse

from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from . import protocol
from .const import CHAR_UUID, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)

FRESH_SECONDS = 60
PREFER_SECONDS = 900
REPLY_TIMEOUT = 3.0
WRITE_TIMEOUT = 5.0
PAIRING_TIMEOUT = 30.0
# How long a failed connect counts against an address.
FAILURE_SECONDS = 300
# Failures before the last working address stops being preferred; the swing
# retires addresses on a timer, and a retired one stays in the history.
PREFER_MISSES = 2
# The swing ends every connection after about 30 s (HCI 0x13, remote user
# terminated) and the reconnect takes 2-3 s, so ride through short gaps.
GRACE_SECONDS = 15
SEND_WAIT_SECONDS = 10
RECONNECT_DELAYS = (2, 5, 10, 15, 30)
# Device Information service strings, read once per run.
DEVICE_INFO = {
    "00002a29-0000-1000-8000-00805f9b34fb": "manufacturer",
    "00002a24-0000-1000-8000-00805f9b34fb": "model",
    "00002a25-0000-1000-8000-00805f9b34fb": "serial_number",
    "00002a27-0000-1000-8000-00805f9b34fb": "hardware",
    "00002a26-0000-1000-8000-00805f9b34fb": "firmware",
    "00002a28-0000-1000-8000-00805f9b34fb": "software",
}


class MamarooError(Exception):
    """Talking to the swing failed."""


def latest_swing(
    hass: HomeAssistant,
    prefer: str | None = None,
    failures: Mapping[str, int] | None = None,
) -> BLEDevice | None:
    """Return the address to connect to.

    One swing advertises under several addresses at once (one of them changes
    at power-up and on a timer), and not all of them accept connections, so it
    is found by its service UUID rather than a stored MAC. The address that
    last worked wins if heard in the last 15 minutes; otherwise, of those heard
    in the last minute, the one with the fewest recent failures, then the
    loudest. Ranking rather than excluding means an address that refuses for a
    while is retried, never shut out in favour of one that never works.
    """
    now = monotonic_time_coarse()
    swings = [
        info
        for info in bluetooth.async_discovered_service_info(hass, connectable=True)
        if SERVICE_UUID in info.service_uuids
    ]
    # A connected identity stops advertising, so the address that just worked
    # looks stale after a few connect/disconnect cycles; give it longer.
    for info in swings:
        if info.address == prefer and now - info.time < PREFER_SECONDS:
            return info.device
    infos = [info for info in swings if now - info.time < FRESH_SECONDS]
    if not infos:
        return None
    failures = failures or {}
    return min(infos, key=lambda info: (failures.get(info.address, 0), -info.rssi)).device


class MamarooSession:
    """One GATT connection: writes commands and routes replies."""

    def __init__(
        self,
        client: BleakClient,
        on_status: Callable[[protocol.SwingState], None] | None = None,
    ) -> None:
        self._client = client
        self._on_status = on_status
        self._waiters: dict[int, asyncio.Future[bytes]] = {}
        # The adapter or proxy that carries this link, when HA reports it.
        self.source: str | None = None
        char = client.services.get_characteristic(CHAR_UUID)
        if char is None:
            raise MamarooError("swing characteristic not found")
        self._char = char
        self._with_response = "write" in char.properties
        _LOGGER.debug("characteristic properties %s", char.properties)

    @classmethod
    async def open(
        cls,
        device: BLEDevice,
        get_device: Callable[[], BLEDevice | None],
        disconnected: Callable[[BleakClient], None] | None = None,
        on_status: Callable[[protocol.SwingState], None] | None = None,
        max_attempts: int = 4,
    ) -> MamarooSession:
        """Connect and subscribe to notifications."""
        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            device.name or "mamaRoo",
            disconnected_callback=disconnected,
            ble_device_callback=lambda: get_device() or device,
            max_attempts=max_attempts,
        )
        try:
            session = cls(client, on_status)
            details = getattr(device, "details", None)
            details = details if isinstance(details, dict) else {}
            session.source = details.get("source")
            await client.start_notify(session._char, session._notified)
        except BaseException:
            await client.disconnect()
            raise
        return session

    @property
    def connected(self) -> bool:
        """Whether the GATT link is up."""
        return self._client.is_connected

    def _notified(self, _sender: object, data: bytearray) -> None:
        data = bytes(data)
        _LOGGER.debug("notify %s", data.hex())
        if not data:
            return
        if data[0] in (protocol.OP_STATUS, protocol.OP_ACK):
            try:
                state = protocol.parse_status(data)
            except ValueError:
                _LOGGER.warning("Unparsed status packet %s", data.hex())
                return
            if self._on_status:
                self._on_status(state)
            return
        waiter = self._waiters.pop(data[0], None)
        if waiter and not waiter.done():
            waiter.set_result(data)

    def expect(self, opcode: int) -> asyncio.Future[bytes]:
        """Register interest in the next reply with this opcode."""
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._waiters[opcode] = future
        return future

    async def write(self, data: bytes) -> None:
        """Write one command."""
        _LOGGER.debug("write %s", data.hex())
        try:
            async with asyncio.timeout(WRITE_TIMEOUT):
                await self._client.write_gatt_char(
                    self._char, data, response=self._with_response
                )
        except TimeoutError as err:
            raise MamarooError(f"write of {data.hex()} timed out") from err

    async def request(
        self, data: bytes, reply: int | None = None, timeout: float = REPLY_TIMEOUT
    ) -> bytes:
        """Write a command and wait for its reply (by default, the same opcode)."""
        future = self.expect(data[0] if reply is None else reply)
        await self.write(data)
        try:
            return await asyncio.wait_for(future, timeout)
        except TimeoutError as err:
            raise MamarooError(f"no reply to {data.hex()}") from err

    async def read_info(self) -> dict[str, str]:
        """Read the Device Information strings."""
        info: dict[str, str] = {}
        for service in self._client.services:
            for char in service.characteristics:
                key = DEVICE_INFO.get(char.uuid)
                if key is None or "read" not in char.properties:
                    continue
                async with asyncio.timeout(REPLY_TIMEOUT):
                    raw = bytes(await self._client.read_gatt_char(char))
                value = raw.decode("utf-8", "replace").strip("\x00 ")
                # The swing has a serial number characteristic but leaves it empty.
                if value:
                    info[key] = value
        return info

    async def bond(self) -> dict[str, object]:
        """Ask for a Bluetooth bond over this link (experimental).

        The swing advertises resolvable private addresses; a bonded central
        holds its identity key and so could follow it across rotations.
        """
        paired = await self._client.pair()
        return {"paired": paired, "address": self._client.address, "via": self.source}

    async def close(self) -> None:
        """Disconnect."""
        with contextlib.suppress(BleakError):
            await self._client.disconnect()


async def async_pair(hass: HomeAssistant) -> tuple[UUID | None, UUID, str]:
    """Register a new pairing ID; the swing must be in pairing mode.

    Observed exchange (2026-10-20):
        -> b0                 <- b0 00 <16-byte bluetooth id>
                              <- b2 01 ...   (unprompted)
        -> b2 00              <- b1 01 ...   (the swing asks for a pairing ID)
        -> b1 01 <uuid>       <- b3 xx 00    (pairing accepted)
    """
    device = latest_swing(hass)
    if device is None:
        raise MamarooError("no swing in range")
    _LOGGER.debug("pairing with %s", device.address)
    # Few attempts: the swing only stays in pairing mode briefly.
    session = await MamarooSession.open(
        device, lambda: latest_swing(hass), max_attempts=2
    )
    try:
        reply = protocol.parse_bluetooth_id(
            await session.request(protocol.get_bluetooth_id())
        )
        _LOGGER.debug("bluetooth id reply %s", reply)
        prompt = await session.request(
            protocol.begin_pairing(), protocol.OP_SET_PAIRING_ID
        )
        _LOGGER.debug("pairing id prompt %s", prompt.hex())
        pairing_id = uuid4()
        result = session.expect(protocol.OP_HANDSHAKE_RESULT)
        await session.write(protocol.set_pairing_id(pairing_id))
        try:
            outcome = await asyncio.wait_for(result, PAIRING_TIMEOUT)
        except TimeoutError as err:
            raise MamarooError("swing never confirmed the pairing") from err
        _LOGGER.debug("handshake result %s", outcome.hex())
        if not protocol.handshake_ok(outcome):
            raise MamarooError(f"pairing refused: {outcome.hex()}")
        return reply.bluetooth_id, pairing_id, device.address
    finally:
        await session.close()


class MamarooDevice:
    """Keeps a handshaken connection to the swing and tracks its state."""

    def __init__(
        self,
        hass: HomeAssistant,
        pairing_id: UUID,
        address: str | None = None,
        on_info: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        self._hass = hass
        self._on_info = on_info
        self.info: dict[str, str] | None = None
        self._pairing_id = pairing_id
        self._address = address
        # Addresses that have completed a handshake. One swing advertises
        # several, and some never accept a connection; only those are ranked down.
        self._good: set[str] = {address} if address else set()
        # Recent connect failures of addresses that never worked: count, last.
        self._failed: dict[str, tuple[int, float]] = {}
        self._misses = 0
        self._session: MamarooSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._lost = asyncio.Event()
        self._seen = asyncio.Event()
        self._unsub_adv: CALLBACK_TYPE | None = None
        self._listeners: set[Callable[[], None]] = set()
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._lost_at: float | None = None
        self._grace: asyncio.TimerHandle | None = None
        self.state: protocol.SwingState | None = None
        # The swing reports 0 for speed while motion is off and for sound and
        # volume while sound is off; these keep the last real values to show.
        self.last_speed = 0
        self.last_sound = 0
        self.last_volume = 0

    @property
    def connected(self) -> bool:
        """Whether the handshaken link is up right now."""
        return self._session is not None and self._session.connected

    @property
    def available(self) -> bool:
        """Connected, or only just dropped and probably reconnecting."""
        if self.connected:
            return True
        return (
            self._lost_at is not None
            and monotonic_time_coarse() - self._lost_at < GRACE_SECONDS
        )

    @callback
    def add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        """Call update whenever state or availability changes."""
        self._listeners.add(update)
        return lambda: self._listeners.discard(update)

    @callback
    def _notify_listeners(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def _status(self, state: protocol.SwingState) -> None:
        self.state = state
        self.last_speed = state.speed or self.last_speed
        self.last_sound = state.sound or self.last_sound
        self.last_volume = state.volume or self.last_volume
        self._notify_listeners()

    @callback
    def _advertised(
        self, _info: bluetooth.BluetoothServiceInfoBleak, _change: object
    ) -> None:
        self._seen.set()

    def _disconnected(self, _client: BleakClient) -> None:
        self._hass.loop.call_soon_threadsafe(self._lost.set)

    def start(self) -> None:
        """Start the keep-connected loop."""
        self._unsub_adv = bluetooth.async_register_callback(
            self._hass,
            self._advertised,
            bluetooth.BluetoothCallbackMatcher(service_uuid=SERVICE_UUID, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        self._task = self._hass.async_create_background_task(
            self._run(), "mamaroo connection"
        )

    async def stop(self) -> None:
        """Stop the loop and disconnect."""
        if self._unsub_adv:
            self._unsub_adv()
        if self._grace:
            self._grace.cancel()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._session:
            await self._session.close()
            self._session = None

    def _pick(self) -> BLEDevice | None:
        now = monotonic_time_coarse()
        failures = {
            address: count
            for address, (count, when) in self._failed.items()
            if now - when < FAILURE_SECONDS
        }
        prefer = self._address if self._misses < PREFER_MISSES else None
        return latest_swing(self._hass, prefer, failures)

    def _record_failure(self, address: str) -> None:
        if address == self._address:
            self._misses += 1
        # A one-off GATT error on an address that works is not a reason to
        # wander off to one that never has.
        if address in self._good:
            return
        now = monotonic_time_coarse()
        count, when = self._failed.get(address, (0, now))
        if now - when >= FAILURE_SECONDS:
            count = 0
        self._failed[address] = (count + 1, now)

    async def _connect(self) -> None:
        device = self._pick()
        if device is None:
            raise MamarooError("no swing in range")
        self._lost.clear()
        try:
            session = await MamarooSession.open(
                device, self._pick, self._disconnected, self._status, max_attempts=2
            )
        except BleakError:
            self._record_failure(device.address)
            raise
        try:
            await self._handshake(session)
        except asyncio.CancelledError:
            await session.close()
            raise
        except BaseException:
            self._record_failure(device.address)
            await session.close()
            raise
        self._failed.pop(device.address, None)
        self._good.add(device.address)
        self._address = device.address
        self._misses = 0
        self._session = session
        self._lost_at = None
        if self._grace:
            self._grace.cancel()
            self._grace = None
        self._ready.set()
        _LOGGER.debug("connected to %s", device.address)
        self._notify_listeners()

    async def _read_info(self) -> None:
        """Read firmware, hardware and the like once; retry on a later link."""
        if self.info is not None or self._session is None:
            return
        try:
            self.info = await self._session.read_info()
        except (BleakError, TimeoutError) as err:
            _LOGGER.debug("device information read failed: %s", err)
            return
        if self._on_info:
            self._on_info(self.info)

    async def _handshake(self, session: MamarooSession) -> None:
        """Prove the pairing, the way the app does after every connect.

            -> b0               <- b0 00 <bluetooth id>
                                <- b2 01 ...   (the swing's prompt)
            -> b2 01 <id>       <- b3 xx 00    (accepted)
        """
        prompt = session.expect(protocol.OP_HANDSHAKE)
        await session.request(protocol.get_bluetooth_id())
        try:
            await asyncio.wait_for(prompt, REPLY_TIMEOUT)
        except TimeoutError as err:
            raise MamarooError("swing sent no handshake prompt") from err
        result = await session.request(
            protocol.handshake(self._pairing_id), protocol.OP_HANDSHAKE_RESULT
        )
        if not protocol.handshake_ok(result):
            raise MamarooError(f"handshake refused: {result.hex()}; re-pair the swing")

    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                await self._connect()
            except (BleakError, MamarooError, TimeoutError) as err:
                delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
                attempt += 1
                _LOGGER.debug("connect failed (%s); retrying in %ss", err, delay)
                await asyncio.sleep(delay)
                if latest_swing(self._hass) is None:
                    # Unplugged or out of range: wait for it to advertise again.
                    self._seen.clear()
                    await self._seen.wait()
                continue
            attempt = 0
            await self._read_info()
            await self._lost.wait()
            self._session = None
            self._ready.clear()
            self._lost_at = monotonic_time_coarse()
            _LOGGER.debug("disconnected")
            # Entities stay available through the grace period; re-check after.
            self._grace = self._hass.loop.call_later(
                GRACE_SECONDS + 1, self._notify_listeners
            )

    async def bond(self) -> dict[str, object]:
        """Bond with the swing over the next live link (experimental)."""
        async with self._lock:
            if not self.connected:
                try:
                    await asyncio.wait_for(self._ready.wait(), SEND_WAIT_SECONDS)
                except TimeoutError as err:
                    raise MamarooError("swing is not connected") from err
            assert self._session is not None
            try:
                result = await self._session.bond()
            except (BleakError, NotImplementedError) as err:
                raise MamarooError(f"bonding failed: {err!r}") from err
        _LOGGER.info("bond result %s", result)
        return result

    async def send(self, data: bytes) -> None:
        """Send a command, waiting briefly if the link is being re-established.

        The swing confirms with a 0x41 packet, which updates state.
        """
        async with self._lock:
            if not self.connected:
                try:
                    await asyncio.wait_for(self._ready.wait(), SEND_WAIT_SECONDS)
                except TimeoutError as err:
                    raise MamarooError("swing is not connected") from err
            assert self._session is not None
            await self._session.write(data)
