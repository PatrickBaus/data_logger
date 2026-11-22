"""Tests of the ILX LDT-5948, E+E EE07 and Coherent WaveMaster drivers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from decimal import Decimal
from typing import Any

import pytest

from devices import EE07, LDT5948, Wavemaster
from devices.ilx import LdtMode

from .fakes import FakeConnection


# ILX LDT-5948. The device answers every command, so writes are queries.
def test_ldt5948_connect_and_id() -> None:
    conn = FakeConnection({"*IDN?": "ILX Lightwave,LDT-5948,59481234,1.30"}, connected=False)
    device = LDT5948(conn)

    async def test() -> str:
        await device.connect()  # Discards a pending reply. There is none, the flush times out.
        identity = await device.get_id()
        await device.disconnect()
        return identity

    assert asyncio.run(test()) == "ILX Lightwave,LDT-5948,59481234,1.30"
    assert device.connection is conn and not conn.connected


@pytest.mark.parametrize(
    "method, cmd",
    [
        ("read_temperature", "MEAS:TEMP?"),
        ("read_current", "MEAS:ITE?"),
        ("read_voltage", "MEAS:VTE?"),
        ("get_temperature_setpoint", "SET:TEMP?"),
        ("get_current_setpoint", "SET:ITE?"),
    ],
)
@pytest.mark.parametrize("reply, expected", [("23.252", Decimal("23.252")), ("garbage", None)])
def test_ldt5948_values(method: str, cmd: str, reply: str, expected: Decimal | None) -> None:
    coro: Coroutine[Any, Any, Decimal] = getattr(LDT5948(FakeConnection({cmd: reply})), method)()
    if expected is None:
        with pytest.raises(ValueError, match="garbage"):
            asyncio.run(coro)
    else:
        assert asyncio.run(coro) == expected


@pytest.mark.parametrize("reply, expected", [("1", True), ("0", False), ("2", None)])
def test_ldt5948_is_enabled(reply: str, expected: bool | None) -> None:
    coro = LDT5948(FakeConnection({"OUTPUT?": reply})).is_enabled()
    if expected is None:
        with pytest.raises(ValueError, match="Invalid return value: 2"):
            asyncio.run(coro)
    else:
        assert asyncio.run(coro) is expected


@pytest.mark.parametrize(
    "method, args, cmd",
    [
        ("set_pid_constants", (15, 0.003, 2), "PID 15.00,0.003,2.000"),
        ("set_temperature_setpoint", (23.0,), "SET:TEMP 23.000"),
        ("set_current_setpoint", (0.5,), "SET:ITE 0.500"),
        ("set_mode", (LdtMode.T,), "MODE T"),
    ],
)
def test_ldt5948_settings(method: str, args: tuple[Any, ...], cmd: str) -> None:
    conn = FakeConnection({cmd: ""})
    action: Callable[..., Coroutine[Any, Any, None]] = getattr(LDT5948(conn), method)
    asyncio.run(action(*args))
    assert conn.written == [cmd]


@pytest.mark.parametrize("constants", [(-1, 0, 0), (10000, 0, 0), (0, 1000, 0), (0, 0, 1000)])
def test_ldt5948_pid_constants_out_of_range(constants: tuple[float, float, float]) -> None:
    conn = FakeConnection()
    with pytest.raises(AssertionError):
        asyncio.run(LDT5948(conn).set_pid_constants(*constants))
    assert not conn.written


def test_ldt5948_get_mode_and_read() -> None:
    conn = FakeConnection({"MODE?": "T"})
    device = LDT5948(conn)

    async def test() -> tuple[LdtMode, str]:
        mode = await device.get_mode()
        return mode, await device.read()  # reads the reply to the last command again

    assert asyncio.run(test()) == (LdtMode.T, "T")


# E+E EE07 and Coherent WaveMaster: both flush all pending replies on connect
@pytest.mark.parametrize("driver", [EE07, Wavemaster])
def test_connect_flushes_all_pending_replies(driver: type[EE07 | Wavemaster]) -> None:
    conn = FakeConnection({"": ["stale 1", "stale 2", TimeoutError()]}, connected=False)
    device = driver(conn)

    async def test() -> None:
        await device.connect()
        await device.disconnect()

    asyncio.run(test())
    assert conn.written == [""]  # An empty command
    assert conn.read_timeouts == [1.0, 1.0, 1.0]  # Read until the device had nothing more to say
    assert device.connection is conn and not conn.connected


@pytest.mark.parametrize("method, cmd", [("read_sensor1", "READ? 1"), ("read_sensor2", "READ? 2")])
@pytest.mark.parametrize("reply, expected", [("45.23", Decimal("45.23")), ("garbage", None)])
def test_ee07_read_sensor(method: str, cmd: str, reply: str, expected: Decimal | None) -> None:
    coro: Coroutine[Any, Any, Decimal] = getattr(EE07(FakeConnection({cmd: reply})), method)()
    if expected is None:
        with pytest.raises(ValueError, match="garbage"):
            asyncio.run(coro)
    else:
        assert asyncio.run(coro) == expected


def test_ee07_id() -> None:
    assert asyncio.run(EE07(FakeConnection({"*IDN?": "E+E Elektronik,EE07"})).get_id()) == "E+E Elektronik,EE07"


@pytest.mark.parametrize("reply, expected", [("12345.6,1550.1234", Decimal("1550.1234")), ("12345.6,x", None)])
def test_wavemaster_read_wavelength(reply: str, expected: Decimal | None) -> None:
    coro = Wavemaster(FakeConnection({"VAL?": reply})).read_wavelength()
    if expected is None:
        with pytest.raises(ValueError, match="12345.6,x"):
            asyncio.run(coro)
    else:
        assert asyncio.run(coro) == expected


def test_wavemaster_context_manager_and_id() -> None:
    conn = FakeConnection({"*IDN?": "COHR, WaveMaster, 0123"}, connected=False)

    async def test() -> str:
        async with Wavemaster(conn) as device:
            assert conn.connected
            await device.write("*IDN?")
            raw = await device.read()
            assert raw == "COHR, WaveMaster, 0123"
            return await device.get_id()

    assert asyncio.run(test()) == "WaveMaster, 0123"  # The manufacturer is removed
    assert not conn.connected
