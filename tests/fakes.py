"""Fake connections and devices used by the tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from uuid import UUID

from devices.connections import Connection
from logger.logger import DataEvent

UUID_A = UUID("15d9f44c-03b4-465b-b596-4cb623d57199")


# A reply of the fake connection: text, binary data or a list of replies, answered one after another. An exception is
# raised instead of answering.
Reply = str | bytes | list[str | bytes | BaseException]


class FakeConnection(Connection):  # pylint: disable=missing-function-docstring
    """
    An in-memory connection. The reply to a command is looked up by the last command written. Commands and replies
    are stored without terminators, the base class adds and removes them, like for a real connection. A list of
    replies is answered in order, the last one is repeated. An exception as a reply is raised instead.
    """

    @property
    def is_connected(self) -> bool:
        return self.connected

    def __init__(
        self,
        replies: Mapping[str, Reply] | None = None,
        connected: bool = True,
        read_delay: float = 0,
    ) -> None:
        super().__init__(timeout=1.0)
        self.read_delay = read_delay  # Wait this long before answering, like a slow or silent instrument
        self.read_gate: asyncio.Event | None = None  # If set, the replies wait until the event is set
        self.replies = {} if replies is None else replies
        self.connected = connected
        self.written: list[str] = []  # the commands without the write terminator
        self.raw_written: list[bytes] = []
        self.read_timeouts: list[float] = []

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
        replies = self.replies[self.written[-1]]
        if isinstance(replies, list):
            reply = replies.pop(0) if len(replies) > 1 else replies[0]
        else:
            reply = replies
        if isinstance(reply, BaseException):
            raise reply
        return (reply.encode("utf-8") if isinstance(reply, str) else reply) + self.read_terminator

    async def _read_until(self, terminator: bytes, timeout: float) -> bytes:
        self.read_timeouts.append(timeout)
        await asyncio.sleep(self.read_delay)
        if self.read_gate is not None:
            await self.read_gate.wait()
        return self.__reply()

    async def _read_exactly(self, length: int, timeout: float) -> bytes:
        self.read_timeouts.append(timeout)
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


class FakeSensor:  # pylint: disable=missing-function-docstring,too-many-instance-attributes
    """
    A logging device, whose read() returns the results of `reads` one after another. `connect_errors` and
    `header_errors` are the outcomes of the calls of connect() and get_log_header() one after another, None is a
    success. Once used up, connect() raises `connect_error`, if set.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        reads: list[Callable[[], tuple[DataEvent, ...]]] | None = None,
        *,
        connect_error: BaseException | None = None,
        column_names: list[str] | None = None,
        connect_errors: list[BaseException | None] | None = None,
        header_errors: list[BaseException | None] | None = None,
        disconnect_error: BaseException | None = None,
    ) -> None:
        self.reads = [] if reads is None else reads
        self.connect_error = connect_error
        self.connect_errors = [] if connect_errors is None else connect_errors
        self.header_errors = [] if header_errors is None else header_errors
        self.disconnect_error = disconnect_error
        self.column_names = ["fake"] if column_names is None else column_names
        self.connected = False
        self.connect_calls = 0
        self.header_calls = 0
        self.post_reads = 0

    async def connect(self) -> None:
        self.connect_calls += 1
        await asyncio.sleep(0)
        error = self.connect_errors.pop(0) if self.connect_errors else self.connect_error
        if error is not None:
            raise error
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False
        if self.disconnect_error is not None:
            raise self.disconnect_error

    async def get_log_header(self) -> str:
        self.header_calls += 1
        error = self.header_errors.pop(0) if self.header_errors else None
        if error is not None:
            raise error
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
