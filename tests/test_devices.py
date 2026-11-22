"""Tests of the instrument drivers using fake connections."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from devices import (
    EE07,
    LDT5948,
    Fluke1524,
    Fluke1590,
    Hp3458A,
    Keithley26xxB,
    Keithley2002,
    KeithleyDMM6500,
    Keysight34470A,
)
from devices.connections import Connection
from devices.fluke import InvalidDataError

from .fakes import FakeConnection


@pytest.mark.parametrize("method, cmd", [("get_temperature", "TEMP?"), ("get_temperature_acal_dcv", "CAL? 175")])
def test_hp3458a_invalid_reply_raises_value_error(method: str, cmd: str) -> None:
    """The conversion used to happen outside the try block and leak decimal.InvalidOperation."""
    device = Hp3458A(FakeConnection({cmd: "garbage"}))
    with pytest.raises(ValueError, match="garbage"):
        asyncio.run(getattr(device, method)())


def test_hp3458a_temperature() -> None:
    device = Hp3458A(FakeConnection({"TEMP?": "35.6"}))
    assert asyncio.run(device.get_temperature()) == Decimal("35.6")


def _ks_cal_replies(temperature: str) -> dict[str, str | bytes]:
    return {
        "CALibration:DATE?": "+2024,+01,+02",
        "CALibration:TIME?": "12,30,00.000",
        "CALibration:TEMPerature?": temperature,
        "CALibration:STRing?": '"cal string"',
    }


def test_keysight34470a_cal_data() -> None:
    device = Keysight34470A(FakeConnection(_ks_cal_replies("+2.35E+01")))
    cal_date, temperature, cal_str = asyncio.run(device.get_cal_data())
    assert cal_date == datetime(2024, 1, 2, 12, 30, tzinfo=timezone.utc)
    assert temperature == Decimal("23.5")
    assert cal_str == '"cal string"'


def test_keysight34470a_invalid_cal_temperature_raises_value_error() -> None:
    device = Keysight34470A(FakeConnection(_ks_cal_replies("garbage")))
    with pytest.raises(ValueError):
        asyncio.run(device.get_cal_data())


@pytest.mark.parametrize("value, expected", [(True, "OUTPUT 1"), (False, "OUTPUT 0"), (1, "OUTPUT 1")])
def test_ldt5948_set_enabled(value: bool, expected: str) -> None:
    """It used to send "OUTPUT True" and "OUTPUT False"."""
    conn = FakeConnection({expected: ""})
    device = LDT5948(conn)

    async def test() -> None:
        await device.connect()
        await device.set_enabled(value)

    asyncio.run(test())
    assert conn.written[-1] == expected


async def _connected_fluke(replies: dict[str, str | bytes]) -> Fluke1590:
    device = Fluke1590(FakeConnection(replies))
    await device.connect()
    return device


@pytest.mark.parametrize(
    "reply, expected_timestamp",
    [
        ("1: 10000.0879 O  15:02:52    10-31-22  ", datetime(2022, 10, 31, 15, 2, 52, tzinfo=timezone.utc)),
        ("1: 10000.0906 O  10-31-22  ", datetime(2022, 10, 31, tzinfo=timezone.utc)),
    ],
)
def test_fluke1590_read_temperature(reply: str, expected_timestamp: datetime) -> None:
    async def test() -> tuple[int, Decimal, str, datetime]:
        device = await _connected_fluke({"new": "NEW: 1", "tem": reply})
        return await device.read_temperature()

    channel, value, unit, timestamp = asyncio.run(test())
    assert (channel, unit, timestamp) == (0, "Ω", expected_timestamp)
    assert isinstance(value, Decimal)


def test_fluke1590_timestamps_are_timezone_aware() -> None:
    async def test() -> list[datetime]:
        results = []
        for reply in ("1: 10000.0902 O  15:24:06   ", "1: 10000.0869 O"):
            device = await _connected_fluke({"new": "NEW: 1", "tem": reply})
            results.append((await device.read_temperature())[3])
        return results

    for timestamp in asyncio.run(test()):
        assert timestamp.tzinfo is not None
        assert timestamp.year > 2000  # a time without a date used to return a date in 1900


@pytest.mark.parametrize("reply", ["garbage", "1: 10000.0869 K"])
def test_fluke1590_invalid_data(reply: str) -> None:
    async def test() -> None:
        device = await _connected_fluke({"new": "NEW: 1", "tem": reply})
        await device.read_temperature()

    with pytest.raises(InvalidDataError):
        asyncio.run(test())


@pytest.mark.parametrize("reply, expected", [("SCR SAV: OFF", 0), ("SCR SAV: ON", 300)])
def test_fluke1590_get_screensaver(reply: str, expected: int) -> None:
    async def test() -> int:
        device = await _connected_fluke({"scrs": reply, "scrt": "SCR SAV TIME (MIN): 5"})
        return await device.get_screensaver()

    assert asyncio.run(test()) == expected


def test_fluke1590_query_requires_connection() -> None:
    with pytest.raises(ConnectionError):
        asyncio.run(Fluke1590(FakeConnection(connected=False)).query("v"))


@pytest.mark.parametrize("driver", [Keysight34470A, KeithleyDMM6500, Keithley26xxB, Keithley2002])
def test_binary_query_returns_bytes(
    driver: type[Keysight34470A | KeithleyDMM6500 | Keithley26xxB | Keithley2002],
) -> None:
    """A read by length is a binary transfer, like a double with :FORM:DATA REAL,64. It must not be decoded."""
    raw = struct.pack("d", 10.000012)  # not valid UTF-8
    device = driver(FakeConnection({"READ?": raw, "*IDN?": "MODEL,123"}))

    async def test() -> tuple[bytes, str]:
        return await device.query("READ?", length=8), await device.query("*IDN?")

    binary, text = asyncio.run(test())
    assert binary == raw and struct.unpack("d", binary) == (10.000012,)
    assert text == "MODEL,123"


@pytest.mark.parametrize(
    "driver, read_terminator, write_terminator",
    [(LDT5948, b"\r\n", b"\r\n"), (Fluke1524, b"\r", b"\r\n"), (EE07, b"\n", b"\n"), (Fluke1590, b"\n", b"\n")],
)
def test_drivers_configure_their_terminators(
    driver: Callable[[Connection], object], read_terminator: bytes, write_terminator: bytes
) -> None:
    """The terminators are set by the driver, they are part of the protocol of the instrument."""
    conn = FakeConnection({"*IDN?": "MODEL,123"})
    driver(conn)
    assert (conn.read_terminator, conn.write_terminator) == (read_terminator, write_terminator)


def test_ldt5948_sends_the_terminator() -> None:
    conn = FakeConnection({"OUTPUT 1": ""})
    asyncio.run(LDT5948(conn).set_enabled(True))
    assert conn.raw_written == [b"OUTPUT 1\r\n"]


def test_k2002_opc_waits_for_the_reply() -> None:
    """Writing *OPC? waits for the instrument to finish. It is a query, so the reply does not stay in the buffer."""
    conn = FakeConnection({"*OPC?": "1", "*IDN?": "KEITHLEY,2002"})
    device = Keithley2002(conn)

    async def test() -> str:
        await device.write("*OPC?")
        return await device.get_id()

    assert asyncio.run(test()) == "KEITHLEY,2002"


@pytest.mark.parametrize("method, args", [("serial_poll", ()), ("wait_for_data", ())])
def test_k2002_gpib_functions_need_a_gpib_connection(method: str, args: tuple[()]) -> None:
    with pytest.raises(TypeError, match="is not a GPIB connection"):
        asyncio.run(getattr(Keithley2002(FakeConnection()), method)(*args))


@pytest.mark.parametrize(
    "reply",
    ["15.00,0.003", "15.00,0.003,2.000,1", "a,b,c", "ILX Lightwave,LDT-5948,59481234,1.30"],
    ids=["too-few", "too-many", "not-numbers", "stale-idn-reply"],
)
def test_ldt5948_invalid_pid_constants(reply: str) -> None:
    """The constants are unpacked into exactly three values, an invalid reply raises a ValueError."""
    with pytest.raises(ValueError):
        asyncio.run(LDT5948(FakeConnection({"PID?": reply})).get_pid_constants())


def test_ldt5948_pid_constants() -> None:
    kp, ki, kd = asyncio.run(LDT5948(FakeConnection({"PID?": "15.00,0.003,2.000"})).get_pid_constants())
    assert (kp, ki, kd) == (Decimal("15.00"), Decimal("0.003"), Decimal("2.000"))
