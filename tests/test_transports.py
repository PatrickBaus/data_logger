"""Tests of the ethernet and serial transports."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
import serial.tools.list_ports
import serial_asyncio

from devices.async_ethernet import AsyncEthernet
from devices.async_serial import AsyncSerial, find_device_by_vid
from devices.errors import NotConnectedError

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


def test_ethernet_query() -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        cmd = await reader.readuntil(b"\n")
        writer.write(b"echo " + cmd)
        await writer.drain()
        writer.close()

    async def test(port: int) -> None:
        conn = AsyncEthernet(host="127.0.0.1", port=port, timeout=1)
        await conn.connect()
        assert conn.is_connected
        await conn.write(b"*IDN?\n")
        assert await conn.read() == b"echo *IDN?\n"
        await conn.disconnect()
        assert not conn.is_connected

    asyncio.run(_with_server(handler, test))


def test_ethernet_eof_is_a_connection_error() -> None:
    """If the instrument closes the socket, the caller must see a ConnectionError, so it reconnects."""

    async def handler(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"incomplete")  # no separator
        await writer.drain()
        writer.close()

    async def test(port: int) -> None:
        conn = AsyncEthernet(host="127.0.0.1", port=port, timeout=1)
        await conn.connect()
        with pytest.raises(ConnectionError, match="closed by the remote end"):
            await conn.read()
        await conn.disconnect()

    asyncio.run(_with_server(handler, test))


def test_ethernet_timeout() -> None:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read()  # never answer, wait until the client disconnects
        writer.close()  # Python 3.12 waits for all connections to close when shutting down the server

    async def test(port: int) -> None:
        conn = AsyncEthernet(host="127.0.0.1", port=port, timeout=0.05)
        await conn.connect()
        with pytest.raises(TimeoutError):
            await conn.read()
        await conn.disconnect()

    asyncio.run(_with_server(handler, test))


def test_ethernet_not_connected() -> None:
    conn = AsyncEthernet(host="127.0.0.1", port=1)
    with pytest.raises(NotConnectedError):
        asyncio.run(conn.read())
    with pytest.raises(NotConnectedError):
        asyncio.run(conn.write(b"foo\n"))


def test_serial_requires_tty_or_vid_pid() -> None:
    with pytest.raises(ValueError):
        AsyncSerial()


def test_serial_not_connected_raises() -> None:
    """Previously, read() returned None and write() did nothing if the port was closed."""
    conn = AsyncSerial(tty="/dev/ttyDoesNotExist")
    with pytest.raises(NotConnectedError):
        asyncio.run(conn.read())
    with pytest.raises(NotConnectedError):
        asyncio.run(conn.write("foo\n"))


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
def test_serial_error_messages_describe_the_port(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any], comports: list[_Port], expected: str
) -> None:
    """A port configured by its VID/PID has no tty until the device is found. The messages used to say "None"."""
    monkeypatch.setattr(serial.tools.list_ports, "comports", _ports(*comports))

    async def open_serial_connection(url: str, **_kwargs: Any) -> None:
        raise ConnectionRefusedError(url)

    monkeypatch.setattr(serial_asyncio, "open_serial_connection", open_serial_connection)
    conn = AsyncSerial(**kwargs)
    with pytest.raises((ConnectionError, ConnectionRefusedError)):
        asyncio.run(conn.connect())  # looks up the tty, if configured by VID/PID
    with pytest.raises(NotConnectedError) as exc_info:
        asyncio.run(conn.read())
    assert str(exc_info.value) == f"Cannot read from {expected}. Not connected."
    assert str(conn) == f"AsyncSerial({expected})"


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
    conn = AsyncSerial(vid_pid=(0x0403, 0x6001), serial_number="AC01QN76")  # does not raise
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
