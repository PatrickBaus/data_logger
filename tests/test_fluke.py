"""Tests of the Fluke 1590 and 1524 drivers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from devices import Fluke1524, Fluke1590
from devices.fluke import LineTerminator, SamplingMode

from .fakes import FakeConnection


@pytest.fixture(name="sleeps")
def fixture_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Skip the waits of the driver and record them."""
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        if delay:  # sleep(0) is the fake connection yielding to other tasks
            sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return sleeps


# Fluke 1590
def test_fluke1590_connect_read_write() -> None:
    conn = FakeConnection({"tem": "1: 10000.0869 O"}, connected=False)
    device = Fluke1590(conn)

    async def test() -> str:
        await device.connect()
        await device.write("tem")
        result = await device.read()
        await device.disconnect()
        return result

    assert asyncio.run(test()) == "1: 10000.0869 O"
    assert not conn.connected


@pytest.mark.parametrize(
    "setter, getter, cmd",
    [
        ("set_conversion_time", "get_conversion_time", "ct"),
        ("set_sample_interval", "get_sample_interval", "si"),
        ("set_integration_time", "get_integration_time", "st"),
    ],
)
def test_fluke1590_timing(setter: str, getter: str, cmd: str) -> None:
    conn = FakeConnection({cmd: "4"})
    device = Fluke1590(conn)

    async def test() -> float:
        await getattr(device, setter)(4.7)  # rounded down to whole seconds
        result: float = await getattr(device, getter)()
        return result

    assert asyncio.run(test()) == 4.0
    assert conn.written == [f"{cmd}=4", cmd]


def test_fluke1590_read_temperature_waits_for_new_data(sleeps: list[float]) -> None:
    conn = FakeConnection({"new": ["NEW: 0", "garbage", "NEW: 1"], "tem": "1: 10000.0869 O"})
    channel, value, unit, _ = asyncio.run(Fluke1590(conn).read_temperature())
    assert (channel, value, unit) == (0, Decimal("10000.0869"), "Ω")
    assert sleeps == [0.2, 0.2]  # polled until the device had a new reading


def test_fluke1590_read_channel(sleeps: list[float]) -> None:
    """The manual allows at most 5 commands per second, so the driver waits before reading a channel."""
    conn = FakeConnection({"tc(2)": "2: 100.00412 O"})
    assert asyncio.run(Fluke1590(conn).read_channel(1)) == "100.00412"
    assert sleeps == [1.2]


def test_fluke1590_get_id() -> None:
    assert asyncio.run(Fluke1590(FakeConnection({"v": "VER: 1590,2.03"})).get_id()) == "Fluke,1590,0,2.03"


@pytest.mark.parametrize(
    "method, args, cmd",
    [
        ("set_mode", (SamplingMode.RUN,), "sact=r"),
        ("set_screensaver", (0,), "scrs=off"),
        ("set_screensaver", (300,), "scrs=on & scrt=5"),
        ("set_time", (datetime(2026, 11, 22, 9, 5, 7, tzinfo=timezone.utc),), "dat=11-22-26 & ti=09:05:07"),
        ("set_line_termination", (LineTerminator.CRLF,), "ter=cl"),
        ("set_timestamp", (True, False), "ieed=on & ieet=off"),
        ("set_timestamp", (), "ieed=off & ieet=off"),
    ],
)
def test_fluke1590_settings(method: str, args: tuple[Any, ...], cmd: str) -> None:
    conn = FakeConnection()
    action: Callable[..., Coroutine[Any, Any, None]] = getattr(Fluke1590(conn), method)
    asyncio.run(action(*args))
    assert conn.written == [cmd]


def test_fluke1590_get_settings() -> None:
    conn = FakeConnection(
        {
            "ti": "TIME: 09:05:07 ",
            "dat": "DATE: 11-22-26 ",
            "ter": "IEEE TERM: LF",
            "ieed": "IEEE DATE: ON",
            "ieet": "IEEE TIME: OFF",
            "rr(0)": "REF RES 0 (EXT): 25.000105",
            "rr(1)": "REF RES 1 (INT): 1.0000012",
            "rr(2)": "REF RES 2 (INT): 10.000034",
            "rr(3)": "REF RES 3 (INT): 100.00051",
            "rr(4)": "REF RES 4 (INT): 10000.067",
        }
    )
    device = Fluke1590(conn)

    async def test() -> tuple[Any, ...]:
        return (
            await device.get_time(),
            await device.get_line_termination(),
            await device.get_timestamp(),
            await device.get_reference_resistor_value(),
        )

    time, terminator, timestamp, references = asyncio.run(test())
    assert time == datetime(2026, 11, 22, 9, 5, 7)  # The device clock has no timezone
    assert terminator is LineTerminator.LF
    assert timestamp == (True, False)
    assert references == tuple(
        Decimal(value) for value in ("25.000105", "1.0000012", "10.000034", "100.00051", "10000.067")
    )


# Fluke 1524
@pytest.mark.parametrize("pending", [True, False], ids=["pending-reply", "no-reply"])
def test_fluke1524_connect_flushes_the_device(pending: bool) -> None:
    conn = FakeConnection({"": "stale"} if pending else {}, connected=False)
    device = Fluke1524(conn)

    async def test() -> None:
        await device.connect()
        await device.disconnect()

    asyncio.run(test())
    assert conn.raw_written == [b"\r\n"]  # An empty command flushes the input buffer of the device
    assert not conn.connected


@pytest.mark.parametrize("method, cmd", [("read_sensor1", "READ? 1"), ("read_sensor2", "READ? 2")])
@pytest.mark.parametrize("reply, expected", [("23.4512", Decimal("23.4512")), ("garbage", None)])
def test_fluke1524_read_sensor(method: str, cmd: str, reply: str, expected: Decimal | None) -> None:
    coro: Coroutine[Any, Any, Decimal] = getattr(Fluke1524(FakeConnection({cmd: reply})), method)()
    if expected is None:
        with pytest.raises(ValueError, match="garbage"):
            asyncio.run(coro)
    else:
        assert asyncio.run(coro) == expected


def test_fluke1524_read_and_id() -> None:
    conn = FakeConnection({"*IDN?": "HART,1524,A12345,1.10", "FETC? 1": "23.4512"})
    device = Fluke1524(conn)

    async def test() -> tuple[str, str]:
        identity = await device.get_id()
        await device.write("FETC? 1")
        return identity, await device.read()

    assert asyncio.run(test()) == ("HART,1524,A12345,1.10", "23.4512")
