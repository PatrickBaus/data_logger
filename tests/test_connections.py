"""Tests of the connections: the common base class, the transports and the GPIB adapters."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
import serial.tools.list_ports
import serial_asyncio

from devices.connections import (
    EthernetConnection,
    GpibConnection,
    PrologixGpibConnection,
    SerialConnection,
    find_device_by_vid,
)
from devices.connections import gpib as gpib_module
from devices.connections import prologix as prologix_module
from devices.errors import NotConnectedError

from .fakes import FakeConnection

_Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]
_Port = tuple[int, int, str, str]  # VID, PID, serial number, device


async def _with_server(handler: _Handler, test: Callable[[int], Awaitable[None]]) -> None:
    server = await asyncio.start_server(handler, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with server:
            await test(port)
    finally:
        server.close()


async def _close_when_done(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Wait until the client disconnects, then close. Python 3.12 waits for all connections when closing a server."""
    await reader.read()
    writer.close()


# The base class, tested through the Ethernet connection
def test_query_adds_and_removes_the_terminators() -> None:
    received = []

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line = await reader.readuntil(b"\r\n")
        received.append(line)
        writer.write(b"reply to " + line)
        await writer.drain()
        await _close_when_done(reader, writer)

    async def test(port: int) -> None:
        conn = EthernetConnection(host="127.0.0.1", port=port, timeout=1)
        conn.read_terminator = b"\r\n"
        conn.write_terminator = b"\r\n"
        await conn.connect()
        try:
            assert await conn.query(b"*IDN?") == b"reply to *IDN?"
        finally:
            await conn.disconnect()

    asyncio.run(_with_server(handler, test))
    assert received == [b"*IDN?\r\n"]


def test_binary_read_removes_the_terminator_after_the_data() -> None:
    raw = struct.pack("d", 10.000012)

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(raw + b"\n")
        await writer.drain()
        await _close_when_done(reader, writer)

    async def test(port: int) -> None:
        conn = EthernetConnection(host="127.0.0.1", port=port, timeout=1)
        await conn.connect()
        try:
            assert await conn.query(b"READ?", length=8) == raw
        finally:
            await conn.disconnect()

    asyncio.run(_with_server(handler, test))


def test_empty_read_terminator_is_rejected() -> None:
    conn = EthernetConnection(host="127.0.0.1", port=1)
    with pytest.raises(ValueError):
        conn.read_terminator = b""


@pytest.mark.parametrize("method, args", [("read", ()), ("write", (b"X",)), ("query", (b"X",))])
def test_not_connected(method: str, args: tuple[bytes, ...]) -> None:
    conn = EthernetConnection(host="127.0.0.1", port=1)
    with pytest.raises(NotConnectedError, match="127.0.0.1:1. Not connected."):
        asyncio.run(getattr(conn, method)(*args))


def test_concurrent_queries_get_their_own_reply() -> None:
    """The lock keeps concurrent write/read pairs from interleaving."""

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while line := await reader.readline():
            await asyncio.sleep(0.01)  # a slow instrument
            writer.write(b"reply to " + line)
            await writer.drain()
        writer.close()

    async def test(port: int) -> None:
        conn = EthernetConnection(host="127.0.0.1", port=port, timeout=1)
        await conn.connect()
        commands = [f"MEAS{i}?".encode() for i in range(5)]
        try:
            replies = await asyncio.gather(*[conn.query(cmd) for cmd in commands])
        finally:
            await conn.disconnect()
        assert replies == [b"reply to " + cmd for cmd in commands]

    asyncio.run(_with_server(handler, test))


def test_read_waits_for_a_running_query() -> None:
    """A read() started while a query waits for its reply must not take that reply."""

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        await asyncio.sleep(0.05)  # a slow instrument
        writer.write(b"reply\nunsolicited\n")
        await writer.drain()
        await _close_when_done(reader, writer)

    async def test(port: int) -> None:
        conn = EthernetConnection(host="127.0.0.1", port=port, timeout=1)
        await conn.connect()
        try:
            query = asyncio.create_task(conn.query(b"MEAS?"))
            await asyncio.sleep(0.01)  # the query has sent its command and waits for the reply
            read = asyncio.create_task(conn.read())
            assert await query == b"reply"
            assert await read == b"unsolicited"
        finally:
            await conn.disconnect()

    asyncio.run(_with_server(handler, test))


# Ethernet
def test_ethernet_eof_is_a_connection_error() -> None:
    """If the instrument closes the socket, the caller must see a ConnectionError, so it reconnects."""

    async def handler(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"incomplete")  # no terminator
        await writer.drain()
        writer.close()

    async def test(port: int) -> None:
        conn = EthernetConnection(host="127.0.0.1", port=port, timeout=1)
        await conn.connect()
        try:
            with pytest.raises(ConnectionError, match="closed by the remote end"):
                await conn.read()
        finally:
            await conn.disconnect()

    asyncio.run(_with_server(handler, test))


def test_ethernet_timeout() -> None:
    async def test(port: int) -> None:
        conn = EthernetConnection(host="127.0.0.1", port=port, timeout=5)
        await conn.connect()
        try:
            with pytest.raises(TimeoutError):
                await conn.read(timeout=0.05)  # overrides the default timeout
        finally:
            await conn.disconnect()

    asyncio.run(_with_server(_close_when_done, test))


# Serial
def test_serial_requires_tty_or_vid_pid() -> None:
    with pytest.raises(ValueError):
        SerialConnection()


def _ports(*ports: _Port) -> Callable[[], list[SimpleNamespace]]:
    return lambda: [SimpleNamespace(vid=vid, pid=pid, serial_number=sn, device=dev) for vid, pid, sn, dev in ports]


def test_find_device_by_vid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        serial.tools.list_ports,
        "comports",
        _ports((0x0403, 0x6001, "A", "/dev/ttyUSB0"), (0x0403, 0x6001, "B", "/dev/ttyUSB1")),
    )
    assert find_device_by_vid(0x0403, 0x6001) == "/dev/ttyUSB0"
    assert find_device_by_vid(0x0403, 0x6001, serial_number="B") == "/dev/ttyUSB1"
    assert find_device_by_vid(0x0403, 0x6001, serial_number="C") is None
    assert find_device_by_vid(0x1234, 0x6001) is None


def test_serial_device_is_looked_up_on_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing USB adapter must not fail at startup, but raise a ConnectionError on connect, so it is retried."""
    monkeypatch.setattr(serial.tools.list_ports, "comports", _ports())
    conn = SerialConnection(vid_pid=(0x0403, 0x6001), serial_number="AC01QN76")  # does not raise
    with pytest.raises(ConnectionError, match="No serial device found with VID:PID 0403:6001, serial number AC01QN76."):
        asyncio.run(conn.connect())

    opened = []

    async def open_serial_connection(url: str, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        opened.append(url)
        raise ConnectionRefusedError("stop here")

    monkeypatch.setattr(serial.tools.list_ports, "comports", _ports((0x0403, 0x6001, "AC01QN76", "/dev/X")))
    monkeypatch.setattr(serial_asyncio, "open_serial_connection", open_serial_connection)
    with pytest.raises(ConnectionRefusedError):
        asyncio.run(conn.connect())
    assert opened == ["/dev/X"]


@pytest.mark.parametrize(
    "kwargs, comports, expected",
    [
        ({"tty": "/dev/ttyUSB0"}, [], "/dev/ttyUSB0"),
        ({"vid_pid": (0x0403, 0x6001)}, [], "VID:PID 0403:6001"),
        ({"vid_pid": (0x0403, 0x6001), "serial_number": "A"}, [], "VID:PID 0403:6001, serial number A"),
        (
            {"vid_pid": (0x0403, 0x6001), "serial_number": "A"},
            [(0x0403, 0x6001, "A", "/dev/ttyUSB3")],
            "VID:PID 0403:6001, serial number A (/dev/ttyUSB3)",
        ),
    ],
    ids=["tty", "vid-pid", "vid-pid-serial", "vid-pid-serial-found"],
)
def test_serial_messages_describe_the_port(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any], comports: list[_Port], expected: str
) -> None:
    """A port configured by its VID/PID has no tty until the device is found. The messages used to say "None"."""
    monkeypatch.setattr(serial.tools.list_ports, "comports", _ports(*comports))

    async def open_serial_connection(url: str, **_kwargs: Any) -> None:
        raise ConnectionRefusedError(url)

    monkeypatch.setattr(serial_asyncio, "open_serial_connection", open_serial_connection)
    conn = SerialConnection(**kwargs)
    with pytest.raises((ConnectionError, ConnectionRefusedError)):
        asyncio.run(conn.connect())  # looks up the tty, if configured by VID/PID
    with pytest.raises(NotConnectedError) as exc_info:
        asyncio.run(conn.read())
    assert str(exc_info.value) == f"Cannot read from {expected}. Not connected."
    assert str(conn) == expected


class _SerialWriter:  # pylint: disable=too-few-public-methods
    """Wraps a TCP stream writer, so it looks like the writer of a serial connection."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.__writer = writer
        self.transport = SimpleNamespace(serial=SimpleNamespace(reset_input_buffer=lambda: None))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__writer, name)


def test_serial_query(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line = await reader.readuntil(b"\r\n")
        writer.write(b"reply to " + line.removesuffix(b"\r\n") + b"\r")
        await writer.drain()
        await _close_when_done(reader, writer)

    async def test(port: int) -> None:
        async def open_serial_connection(
            url: str, **_kwargs: Any  # pylint: disable=unused-argument
        ) -> tuple[asyncio.StreamReader, _SerialWriter]:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            return reader, _SerialWriter(writer)

        monkeypatch.setattr(serial_asyncio, "open_serial_connection", open_serial_connection)
        conn = SerialConnection(tty="/dev/ttyFake", timeout=1)
        conn.read_terminator = b"\r"
        conn.write_terminator = b"\r\n"
        await conn.connect()
        try:
            assert await conn.query(b"READ? 1") == b"reply to READ? 1"
        finally:
            await conn.disconnect()

    asyncio.run(_with_server(handler, test))


# GPIB adapters
class _FakeGpibLibrary:  # pylint: disable=missing-function-docstring
    """Stand-in for AsyncGpib and AsyncPrologixGpibEthernetController."""

    instances: list[_FakeGpibLibrary] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.is_connected = False
        self.written: list[bytes] = []
        self.reads: list[int | None] = []
        self.reply = b""
        self.calls: list[tuple[Any, ...]] = []
        self.instances.append(self)

    async def connect(self) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def write(self, data: bytes) -> None:
        self.written.append(data)

    async def read(self, length: int | None = None) -> bytes:
        self.reads.append(length)
        return self.reply if length is None else self.reply[:length]

    async def serial_poll(self, **kwargs: Any) -> int:
        self.calls.append(("serial_poll", kwargs))
        return 0x40

    async def wait(self, mask: int) -> None:
        self.calls.append(("wait", mask))


class _FakeLinuxGpib(_FakeGpibLibrary):
    """AsyncGpib reads at most 512 bytes by default. The Prologix library reads until the end of the message."""

    async def read(self, length: int | None = 512) -> bytes:
        return await super().read(length)


@pytest.fixture(name="fake_gpib")
def fixture_fake_gpib(monkeypatch: pytest.MonkeyPatch) -> list[_FakeGpibLibrary]:
    _FakeGpibLibrary.instances = []
    monkeypatch.setattr(gpib_module, "AsyncGpib", _FakeLinuxGpib)
    monkeypatch.setattr(prologix_module, "AsyncPrologixGpibEthernetController", _FakeGpibLibrary)
    return _FakeGpibLibrary.instances


@pytest.mark.parametrize(
    "create, description",
    [
        (lambda: GpibConnection(name=0, pad=16, timeout=10), "GPIB board 0, address 16"),
        (
            lambda: PrologixGpibConnection(host="prologix", pad=16, timeout=3, wait_delay=1),
            "Prologix adapter prologix:1234, GPIB address 16",
        ),
    ],
    ids=["linux-gpib", "prologix"],
)
def test_gpib_adapters(
    fake_gpib: list[_FakeGpibLibrary],
    create: Callable[[], GpibConnection | PrologixGpibConnection],
    description: str,
) -> None:
    conn = create()
    (library,) = fake_gpib
    assert str(conn) == description

    async def test() -> None:
        assert not conn.is_connected
        await conn.connect()
        assert conn.is_connected
        library.reply = b"MODEL,123\n"
        assert await conn.query(b"*IDN?") == b"MODEL,123"
        library.reply = b"NO TERMINATOR"  # GPIB messages end with EOI, the terminator is optional
        assert await conn.read() == b"NO TERMINATOR"
        library.reply = struct.pack("d", 1.5) + b"\n"
        assert await conn.read(length=8) == struct.pack("d", 1.5)
        assert await conn.serial_poll() == 0x40
        await conn.wait(1 << 11)
        await conn.disconnect()
        assert not conn.is_connected

    asyncio.run(test())
    assert library.written == [b"*IDN?\n"]
    assert library.reads[:2] == [None, None]  # Text is read until the end of the message, however long it is
    assert library.reads[-1] == 9  # 8 bytes of data and the terminator
    assert ("wait", 1 << 11) in library.calls


def test_gpib_adapter_arguments(fake_gpib: list[_FakeGpibLibrary]) -> None:
    GpibConnection(name="gpib0", pad=16, timeout=100)
    PrologixGpibConnection(host="prologix", pad=4, port=1234, timeout=3, wait_delay=1)
    gpib, prologix = fake_gpib
    assert gpib.kwargs == {"name": "gpib0", "pad": 16, "timeout": 100}
    assert prologix.kwargs == {"hostname": "prologix", "port": 1234, "pad": 4, "timeout": 3, "wait_delay": 1}


def test_prologix_serial_poll_addresses_the_instrument(fake_gpib: list[_FakeGpibLibrary]) -> None:
    conn = PrologixGpibConnection(host="prologix", pad=4)

    async def test() -> None:
        await conn.connect()
        await conn.serial_poll()

    asyncio.run(test())
    assert ("serial_poll", {"pad": 4}) in fake_gpib[0].calls


def test_disconnect_is_a_no_op_if_not_connected() -> None:
    conn = EthernetConnection(host="127.0.0.1", port=1)
    asyncio.run(conn.disconnect())
    assert not conn.is_connected


@pytest.mark.parametrize("method, args", [("read", ()), ("write", (b"X",))])
def test_connection_closed_while_waiting_for_the_lock(method: str, args: tuple[bytes, ...]) -> None:
    """A read or write, that waits for a running query, finds the connection closed, when it gets the lock."""
    conn = FakeConnection({"MEAS?": "1.234"})

    async def test() -> None:
        conn.read_gate = asyncio.Event()
        query = asyncio.create_task(conn.query(b"MEAS?"))
        while not conn.read_timeouts:  # The query holds the lock and waits for the reply
            await asyncio.sleep(0)
        waiting = asyncio.create_task(getattr(conn, method)(*args))
        for _ in range(3):  # Let the read or write run until it waits for the lock
            await asyncio.sleep(0)
        assert not waiting.done()
        await conn.disconnect()
        conn.read_gate.set()
        assert await query == b"1.234"
        with pytest.raises(NotConnectedError, match="FakeConnection. Not connected."):
            await waiting

    asyncio.run(test())


def test_ethernet_disconnect_ignores_a_reset_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    async def wait_closed(_self: asyncio.StreamWriter) -> None:
        raise ConnectionResetError("Connection reset by peer")

    async def test(port: int) -> None:
        conn = EthernetConnection(host="127.0.0.1", port=port, timeout=1)
        await conn.connect()
        monkeypatch.setattr(asyncio.StreamWriter, "wait_closed", wait_closed)
        await conn.disconnect()
        monkeypatch.undo()
        assert not conn.is_connected

    asyncio.run(_with_server(_close_when_done, test))


def _serial_over_tcp(monkeypatch: pytest.MonkeyPatch, port: int) -> SerialConnection:
    """A serial connection, that talks to a TCP server instead of a serial port."""

    async def open_serial_connection(
        url: str, **_kwargs: Any  # pylint: disable=unused-argument
    ) -> tuple[asyncio.StreamReader, _SerialWriter]:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        return reader, _SerialWriter(writer)

    monkeypatch.setattr(serial_asyncio, "open_serial_connection", open_serial_connection)
    return SerialConnection(tty="/dev/ttyFake", timeout=1)


def test_serial_binary_read(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = struct.pack("d", 1.5)

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        writer.write(raw + b"\n")
        await writer.drain()
        await _close_when_done(reader, writer)

    async def test(port: int) -> None:
        conn = _serial_over_tcp(monkeypatch, port)
        await conn.connect()
        try:
            assert await conn.query(b"READ?", length=8) == raw
        finally:
            await conn.disconnect()

    asyncio.run(_with_server(handler, test))


def test_serial_eof_is_a_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unplugged USB adapter closes the port. The caller must see a ConnectionError, so it reconnects."""

    async def handler(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"incomplete")  # no terminator
        await writer.drain()
        writer.close()

    async def test(port: int) -> None:
        conn = _serial_over_tcp(monkeypatch, port)
        await conn.connect()
        try:
            with pytest.raises(ConnectionError, match="Serial connection to /dev/ttyFake closed."):
                await conn.read()
        finally:
            await conn.disconnect()

    asyncio.run(_with_server(handler, test))


def test_serial_disconnect_ignores_a_reset_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    async def wait_closed(_self: asyncio.StreamWriter) -> None:
        raise ConnectionResetError("Connection reset by peer")

    async def test(port: int) -> None:
        conn = _serial_over_tcp(monkeypatch, port)
        await conn.connect()
        monkeypatch.setattr(asyncio.StreamWriter, "wait_closed", wait_closed)
        await conn.disconnect()
        monkeypatch.undo()
        assert not conn.is_connected

    asyncio.run(_with_server(_close_when_done, test))
