"""Fake connections and devices used by the tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

from logger.logger import DataEvent

UUID_A = UUID("15d9f44c-03b4-465b-b596-4cb623d57199")


class FakeConnection:  # pylint: disable=missing-function-docstring
    """Stand-in for the transports. Replies are looked up by the last command written."""

    def __init__(self, replies: dict[str, str | bytes] | None = None, terminator: str = "\n") -> None:
        self.replies = {} if replies is None else replies
        self.terminator = terminator
        self.written: list[str] = []
        self.timeout = 1.0
        self.wait_delay: float | None = None

    @staticmethod
    def _to_str(cmd: str | bytes) -> str:
        return cmd.decode("ascii") if isinstance(cmd, bytes) else cmd

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    def set_wait_delay(self, value: float) -> None:
        self.wait_delay = value

    async def write(self, cmd: str | bytes) -> None:
        self.written.append(self._to_str(cmd).rstrip("\r\n"))

    async def read(self, **_kwargs) -> bytes:
        if not self.written or self.written[-1] not in self.replies:
            raise TimeoutError("No reply")  # Like a real instrument, that does not answer
        reply = self.replies[self.written[-1]]
        if isinstance(reply, str):
            reply = (reply + self.terminator).encode("utf-8")
        return reply


class FakeStrConnection(FakeConnection):
    """Like FakeConnection, but returns strings like AsyncSerial."""

    async def read(self, **_kwargs) -> str:  # type: ignore[override]
        return (await super().read()).decode("utf-8")


def as_transport(fake: FakeConnection) -> Any:
    """
    The drivers are typed with the transports they are used with. The fake has the same interface, so hand it to the
    drivers as one of them.
    """
    return fake


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
