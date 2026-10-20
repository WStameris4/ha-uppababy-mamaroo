"""BLE connection to a Mamaroo Smart Swing."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import logging
from uuid import UUID, uuid4

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from . import protocol
from .const import CHAR_UUID, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)

REPLY_TIMEOUT = 3.0
PAIRING_TIMEOUT = 30.0
RECONNECT_DELAYS = (2, 5, 10, 30, 60)


class MamarooError(Exception):
    """Talking to the swing failed."""


def latest_swing(hass: HomeAssistant) -> BLEDevice | None:
    """Return the most recently heard swing.

    The swing advertises from rotating random addresses, so it is found by its
    service UUID rather than by a stored MAC.
    """
    infos = [
        info
        for info in bluetooth.async_discovered_service_info(hass, connectable=True)
        if SERVICE_UUID in info.service_uuids
    ]
    if not infos:
        return None
    return max(infos, key=lambda info: info.time).device


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
        char = client.services.get_characteristic(CHAR_UUID)
        if char is None:
            raise MamarooError("swing characteristic not found")
        self._char = char
        self._with_response = "write" in char.properties

    @classmethod
    async def open(
        cls,
        device: BLEDevice,
        get_device: Callable[[], BLEDevice | None],
        disconnected: Callable[[BleakClient], None] | None = None,
        on_status: Callable[[protocol.SwingState], None] | None = None,
    ) -> MamarooSession:
        """Connect and subscribe to notifications."""
        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            device.name or "mamaRoo",
            disconnected_callback=disconnected,
            ble_device_callback=lambda: get_device() or device,
        )
        try:
            session = cls(client, on_status)
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
        if data[0] == protocol.OP_STATUS:
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
        await self._client.write_gatt_char(
            self._char, data, response=self._with_response
        )

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

    async def close(self) -> None:
        """Disconnect."""
        with contextlib.suppress(BleakError):
            await self._client.disconnect()


async def async_pair(hass: HomeAssistant) -> tuple[UUID | None, UUID]:
    """Register a new pairing ID; the swing must be in pairing mode.

    Mirrors the app: read the Bluetooth ID, open a pairing, write a fresh
    random pairing ID, then wait for the handshake result.
    """
    device = latest_swing(hass)
    if device is None:
        raise MamarooError("no swing in range")
    session = await MamarooSession.open(device, lambda: latest_swing(hass))
    try:
        reply = protocol.parse_bluetooth_id(
            await session.request(protocol.get_bluetooth_id())
        )
        _LOGGER.debug("bluetooth id reply %s", reply)
        opened = await session.request(protocol.begin_pairing())
        _LOGGER.debug("begin pairing reply %s", opened.hex())
        pairing_id = uuid4()
        result = session.expect(protocol.OP_HANDSHAKE_RESULT)
        ack = await session.request(protocol.set_pairing_id(pairing_id))
        _LOGGER.debug("pairing id reply %s", ack.hex())
        try:
            outcome = await asyncio.wait_for(result, PAIRING_TIMEOUT)
        except TimeoutError as err:
            raise MamarooError("swing never confirmed the pairing") from err
        _LOGGER.debug("handshake result %s", outcome.hex())
        if not protocol.handshake_ok(outcome):
            raise MamarooError(f"pairing refused: {outcome.hex()}")
        return reply.bluetooth_id, pairing_id
    finally:
        await session.close()


class MamarooDevice:
    """Keeps a handshaken connection to the swing and tracks its state."""

    def __init__(self, hass: HomeAssistant, pairing_id: UUID) -> None:
        self._hass = hass
        self._pairing_id = pairing_id
        self._session: MamarooSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._lost = asyncio.Event()
        self._seen = asyncio.Event()
        self._unsub_adv: CALLBACK_TYPE | None = None
        self._listeners: set[Callable[[], None]] = set()
        self._lock = asyncio.Lock()
        self.state: protocol.SwingState | None = None

    @property
    def available(self) -> bool:
        """Whether commands can be sent right now."""
        return self._session is not None and self._session.connected

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
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._session:
            await self._session.close()
            self._session = None

    async def _connect(self) -> None:
        device = latest_swing(self._hass)
        if device is None:
            raise MamarooError("no swing in range")
        self._lost.clear()
        session = await MamarooSession.open(
            device,
            lambda: latest_swing(self._hass),
            self._disconnected,
            self._status,
        )
        try:
            result = await session.request(
                protocol.handshake(self._pairing_id), protocol.OP_HANDSHAKE_RESULT
            )
        except BaseException:
            await session.close()
            raise
        if not protocol.handshake_ok(result):
            await session.close()
            raise MamarooError(f"handshake refused: {result.hex()}; re-pair the swing")
        self._session = session
        _LOGGER.debug("connected to %s", device.address)
        self._notify_listeners()

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
            await self._lost.wait()
            self._session = None
            _LOGGER.debug("disconnected")
            self._notify_listeners()

    async def send(self, data: bytes) -> None:
        """Send a command; the swing's next status report updates state."""
        async with self._lock:
            if not self.available or self._session is None:
                raise MamarooError("swing is not connected")
            await self._session.write(data)
