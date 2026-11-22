"""Fake connections and devices used by the tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from uuid import UUID

from devices.connections import Connection
from logger.logger import DataEvent

UUID_A = UUID("15d9f44c-03b4-465b-b596-4cb623d57199")


class FakeConnection(Connection):  # pylint: disable=missing-function-docstring
    """
    An in-memory connection. The reply to a command is looked up by the last command written. Commands and replies
    are stored without terminators, the base class adds and removes them, like for a real connection.
    """

    @property
    def is_connected(self) -> bool:
        return self.connected

    def __init__(self, replies: dict[str, str | bytes] | None = None, connected: bool = True) -> None:
        super().__init__(timeout=1.0)
        self.replies = {} if replies is None else replies
        self.connected = connected
        self.written: list[str] = []  # the commands without the write terminator
        self.raw_written: list[bytes] = []

    def __str__(self) -> str:
        return "FakeConnection"

    async def _connect(self) -> None:
        self.connected = True

    async def _disconnect(self) -> None:
        self.connected = False

    async def _write(self, data: bytes, timeout: float) -> None:
        self.raw_written.append(data)
        self.written.append(data.removesuffix(self.write_terminator).decode("utf-8"))

    def __reply(self) -> bytes:
        if not self.written or self.written[-1] not in self.replies:
            raise TimeoutError("No reply")  # Like a real instrument, that does not answer
        reply = self.replies[self.written[-1]]
        return (reply.encode("utf-8") if isinstance(reply, str) else reply) + self.read_terminator

    async def _read_until(self, terminator: bytes, timeout: float) -> bytes:
        return self.__reply()

    async def _read_exactly(self, length: int, timeout: float) -> bytes:
        return self.__reply()[:length]


class FakeDevice:  # pylint: disable=missing-function-docstring
    """Stand-in for an instrument driver. Records the commands written to it."""

    def __init__(self) -> None:
        self.written: list[str] = []

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def get_id(self) -> str:
        return "FakeDevice"

    async def write(self, cmd: str) -> None:
        self.written.append(cmd)


class FakeSensor:  # pylint: disable=missing-function-docstring
    """A logging device, whose read() returns the results of `reads` one after another."""

    def __init__(
        self,
        reads: list[Callable[[], tuple[DataEvent, ...]]] | None = None,
        connect_error: BaseException | None = None,
        column_names: list[str] | None = None,
    ) -> None:
        self.reads = [] if reads is None else reads
        self.connect_error = connect_error
        self.column_names = ["fake"] if column_names is None else column_names
        self.connected = False
        self.connect_calls = 0
        self.post_reads = 0

    async def connect(self) -> None:
        self.connect_calls += 1
        await asyncio.sleep(0)
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def get_log_header(self) -> str:
        return "Fake sensor"

    async def read(self) -> tuple[DataEvent, ...]:
        await asyncio.sleep(0)
        if self.reads:
            return self.reads.pop(0)()
        await asyncio.sleep(3600)  # nothing left to return, block until cancelled
        raise AssertionError("unreachable")

    async def post_read(self) -> None:
        self.post_reads += 1


def event(value: object, topic: str = "sensors/test", sid: int = 0) -> DataEvent:
    """Create a data event."""
    return DataEvent(sender=UUID_A, sid=sid, topic=topic, value=value, unit="V")


def returns(*values: object) -> Callable[[], tuple[DataEvent, ...]]:
    """A read, that returns events with the given values."""
    return lambda: tuple(event(value, sid=i) for i, value in enumerate(values))


def raises(exc: BaseException) -> Callable[[], tuple[DataEvent, ...]]:
    """A read, that raises the given exception."""

    def _read() -> tuple[DataEvent, ...]:
        raise exc

    return _read
