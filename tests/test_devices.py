"""Tests of the instrument drivers using fake connections."""

from __future__ import annotations

import asyncio
import struct
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from devices import LDT5948, Fluke1590, Hp3458A, Keithley26xxB, Keithley2002, KeithleyDMM6500, Keysight34470A
from devices.fluke import InvalidDataError

from .fakes import FakeConnection, FakeStrConnection, as_transport


@pytest.mark.parametrize("method, cmd", [("get_temperature", "TEMP?"), ("get_temperature_acal_dcv", "CAL? 175")])
def test_hp3458a_invalid_reply_raises_value_error(method, cmd):
    """The conversion used to happen outside the try block and leak decimal.InvalidOperation."""
    device = Hp3458A(as_transport(FakeConnection({cmd: "garbage"})))
    with pytest.raises(ValueError, match="garbage"):
        asyncio.run(getattr(device, method)())


def test_hp3458a_temperature():
    device = Hp3458A(as_transport(FakeConnection({"TEMP?": "35.6"})))
    assert asyncio.run(device.get_temperature()) == Decimal("35.6")


def _ks_cal_replies(temperature: str) -> dict[str, str | bytes]:
    return {
        "CALibration:DATE?": "+2024,+01,+02",
        "CALibration:TIME?": "12,30,00.000",
        "CALibration:TEMPerature?": temperature,
        "CALibration:STRing?": '"cal string"',
    }


def test_keysight34470a_cal_data():
    device = Keysight34470A(as_transport(FakeConnection(_ks_cal_replies("+2.35E+01"))))
    cal_date, temperature, cal_str = asyncio.run(device.get_cal_data())
    assert cal_date == datetime(2024, 1, 2, 12, 30, tzinfo=timezone.utc)
    assert temperature == Decimal("23.5")
    assert cal_str == '"cal string"'


def test_keysight34470a_invalid_cal_temperature_raises_value_error():
    device = Keysight34470A(as_transport(FakeConnection(_ks_cal_replies("garbage"))))
    with pytest.raises(ValueError):
        asyncio.run(device.get_cal_data())


@pytest.mark.parametrize("value, expected", [(True, "OUTPUT 1"), (False, "OUTPUT 0"), (1, "OUTPUT 1")])
def test_ldt5948_set_enabled(value, expected):
    """It used to send "OUTPUT True" and "OUTPUT False"."""
    conn = FakeStrConnection({expected: ""}, terminator="\r\n")
    device = LDT5948(as_transport(conn))

    async def test():
        await device.connect()
        await device.set_enabled(value)

    asyncio.run(test())
    assert conn.written[-1] == expected


async def _connected_fluke(replies: dict[str, str | bytes]) -> Fluke1590:
    device = Fluke1590(as_transport(FakeConnection(replies)))
    await device.connect()
    return device


@pytest.mark.parametrize(
    "reply, expected_timestamp",
    [
        ("1: 10000.0879 O  15:02:52    10-31-22  ", datetime(2022, 10, 31, 15, 2, 52, tzinfo=timezone.utc)),
        ("1: 10000.0906 O  10-31-22  ", datetime(2022, 10, 31, tzinfo=timezone.utc)),
    ],
)
def test_fluke1590_read_temperature(reply, expected_timestamp):
    async def test():
        device = await _connected_fluke({"new": "NEW: 1", "tem": reply})
        return await device.read_temperature()

    channel, value, unit, timestamp = asyncio.run(test())
    assert (channel, unit, timestamp) == (0, "Ω", expected_timestamp)
    assert isinstance(value, Decimal)


def test_fluke1590_timestamps_are_timezone_aware():
    async def test():
        results = []
        for reply in ("1: 10000.0902 O  15:24:06   ", "1: 10000.0869 O"):
            device = await _connected_fluke({"new": "NEW: 1", "tem": reply})
            results.append((await device.read_temperature())[3])
        return results

    for timestamp in asyncio.run(test()):
        assert timestamp.tzinfo is not None
        assert timestamp.year > 2000  # a time without a date used to return a date in 1900


@pytest.mark.parametrize("reply", ["garbage", "1: 10000.0869 K"])
def test_fluke1590_invalid_data(reply):
    async def test():
        device = await _connected_fluke({"new": "NEW: 1", "tem": reply})
        await device.read_temperature()

    with pytest.raises(InvalidDataError):
        asyncio.run(test())


@pytest.mark.parametrize("reply, expected", [("SCR SAV: OFF", 0), ("SCR SAV: ON", 300)])
def test_fluke1590_get_screensaver(reply, expected):
    async def test():
        device = await _connected_fluke({"scrs": reply, "scrt": "SCR SAV TIME (MIN): 5"})
        return await device.get_screensaver()

    assert asyncio.run(test()) == expected


def test_fluke1590_query_requires_connection():
    with pytest.raises(ConnectionError):
        asyncio.run(Fluke1590(as_transport(FakeConnection())).query("v"))


@pytest.mark.parametrize("driver", [Keysight34470A, KeithleyDMM6500, Keithley26xxB, Keithley2002])
def test_binary_query_returns_bytes(driver):
    """A read by length is a binary transfer, like a double with :FORM:DATA REAL,64. It must not be decoded."""
    raw = struct.pack("d", 10.000012)  # not valid UTF-8
    device = driver(FakeConnection({"READ?": raw + b"\n", "*IDN?": "MODEL,123"}))

    async def test():
        return await device.query("READ?", length=8), await device.query("*IDN?")

    binary, text = asyncio.run(test())
    assert binary == raw and struct.unpack("d", binary) == (10.000012,)
    assert text == "MODEL,123"
