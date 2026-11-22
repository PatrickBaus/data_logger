"""Tests of the Keithley DMM6500, 2002 and 26xxB drivers."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import pytest

from devices import GpibConnection, Keithley26xxB, Keithley2002, KeithleyDMM6500

from .fakes import FakeConnection


class _FakeGpib(GpibConnection):
    """A GPIB connection, that answers serial polls and waits without a GPIB board."""

    def __init__(self, wait_error: BaseException | None = None) -> None:
        super().__init__(name=0, pad=16)
        self.wait_error = wait_error
        self.waited_for: list[int] = []

    async def serial_poll(self) -> int:
        return 0x40

    async def wait(self, eventmask: int) -> None:
        self.waited_for.append(eventmask)
        if self.wait_error is not None:
            raise self.wait_error


# DMM6500
def test_dmm6500_connect_flushes_and_disconnects() -> None:
    conn = FakeConnection(connected=False)
    device = KeithleyDMM6500(conn)

    async def test() -> None:
        await device.connect()  # The flush times out, there is nothing to read
        await device.disconnect()

    asyncio.run(test())
    assert conn.written == [":ABORt"]
    assert not conn.connected


def test_dmm6500_read() -> None:
    conn = FakeConnection({"READ?": "+1.0001E+04", "*IDN?": "KEITHLEY INSTRUMENTS,MODEL DMM6500"})
    device = KeithleyDMM6500(conn)

    async def test() -> tuple[str | None, str | None, str]:
        nothing = await device.read()  # Nothing was asked, the read times out
        await device.write("READ?")
        return nothing, await device.read(), await device.get_id()

    assert asyncio.run(test()) == (None, "+1.0001E+04", "KEITHLEY INSTRUMENTS,MODEL DMM6500")


@pytest.mark.parametrize(
    "method, args, cmd",
    [("set_mode_resistance_2w", (), "SENS:FUNC 'RES'"), ("set_nplc", (10,), "SENS:RES:NPLC 10")],
)
def test_dmm6500_commands(method: str, args: tuple[Any, ...], cmd: str) -> None:
    conn = FakeConnection()
    action: Callable[..., Coroutine[Any, Any, None]] = getattr(KeithleyDMM6500(conn), method)
    asyncio.run(action(*args))
    assert conn.written == [cmd]


# Keithley 2002
def test_k2002_cal_data_and_id() -> None:
    conn = FakeConnection(
        {
            ":CALibration:PROTected:DATE?": "2022,11,29",
            ":CALibration:PROTected:NDUE?": "2023,11,29",
            "*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2002,1234567,A10  /A02\n",
        },
        connected=False,
    )
    device = Keithley2002(conn)

    async def test() -> tuple[tuple[datetime, datetime], str]:
        await device.connect()
        result = await device.get_cal_data(), await device.get_id()
        await device.disconnect()
        return result

    (cal_date, due_date), identity = asyncio.run(test())
    assert (cal_date, due_date) == (datetime(2022, 11, 29, tzinfo=UTC), datetime(2023, 11, 29, tzinfo=UTC))
    assert identity == "KEITHLEY INSTRUMENTS INC.,MODEL 2002,1234567,A10  /A02"  # stripped
    assert not conn.connected


@pytest.mark.parametrize(
    "cmd, test_error, written",
    [
        (":SENS:VOLT:DC:NPLC 10", True, [":SENS:VOLT:DC:NPLC 10", ":SYSTem:ERRor?"]),
        (":SENS:VOLT:DC:NPLC 10", False, [":SENS:VOLT:DC:NPLC 10"]),
        ("*RST", True, ["*RST"]),  # Common commands do not query the error queue
    ],
    ids=["test-error", "no-test", "common-command"],
)
def test_k2002_write_tests_for_errors(
    cmd: str, test_error: bool, written: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    conn = FakeConnection({":SYSTem:ERRor?": '-113,"Undefined header"'})
    asyncio.run(Keithley2002(conn).write(cmd, test_error=test_error))
    assert conn.written == written
    assert ("Undefined header" in caplog.text) == (len(written) == 2)


def test_k2002_read() -> None:
    raw = struct.pack("d", 7.04254)
    conn = FakeConnection({":FETCh?": " 7.04254E+00", ":DATA:FRESh?": raw})
    device = Keithley2002(conn)

    async def test() -> tuple[str, bytes]:
        await device.write(":FETCh?")
        text = await device.read()
        await device.write(":DATA:FRESh?")
        return text, await device.read(length=8)

    assert asyncio.run(test()) == ("7.04254E+00", raw)


def test_k2002_gpib_functions() -> None:
    conn = _FakeGpib()
    device = Keithley2002(conn)

    async def test() -> int:
        await device.wait_for_data()
        return await device.serial_poll()

    assert asyncio.run(test()) == 0x40
    assert conn.waited_for == [(1 << 11) | (1 << 14)]  # RQS or TIMO


def test_k2002_wait_timeout_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(TimeoutError):
        asyncio.run(Keithley2002(_FakeGpib(wait_error=TimeoutError())).wait_for_data())
    assert "Timeout during wait" in caplog.text


# Keithley 26xxB
def test_k26xxb_info() -> None:
    conn = FakeConnection(
        {
            "print(smua.cal.date)": "1.6696800e+09",
            "print(smub.cal.date)": "1.6696800e+09",
            "print(smua.cal.due)": "1.7012160e+09",
            "print(smub.cal.due)": "1.7012160e+09",
            "print(localnode.revision)": "4.0.4",
            "print(localnode.serialno)": "4123456",
            "print(localnode.model)": "2612B",
            "*IDN?": "Keithley Instruments Inc., Model 2612B, 4123456, 4.0.4",
        },
        connected=False,
    )
    device = Keithley26xxB(conn)

    async def test() -> tuple[Any, ...]:
        await device.connect()  # The flush times out, there is nothing to read
        result = (
            await device.get_cal_data(),
            await device.get_fw_version(),
            await device.get_serial_number(),
            await device.get_model(),
            await device.get_id(),
        )
        await device.disconnect()
        return result

    cal_data, firmware, serial_number, model, identity = asyncio.run(test())
    cal_date = datetime.fromtimestamp(1669680000, UTC)
    due_date = datetime.fromtimestamp(1701216000, UTC)
    assert cal_data == ((cal_date, cal_date), (due_date, due_date))
    assert (firmware, serial_number, model) == ("4.0.4", "4123456", "2612B")
    assert identity.startswith("Keithley Instruments Inc., Model 2612B")
    assert not conn.connected


def test_k26xxb_read_and_write() -> None:
    conn = FakeConnection({"print(smua.measure.i())": "1.23456e-03"})
    device = Keithley26xxB(conn)

    async def test() -> tuple[str | None, str | None]:
        nothing = await device.read()  # Nothing was asked, the read times out
        await device.write("print(smua.measure.i())")
        return nothing, await device.read()

    assert asyncio.run(test()) == (None, "1.23456e-03")


@pytest.mark.parametrize("driver", [KeithleyDMM6500, Keithley26xxB])
def test_connect_does_not_wait_for_a_silent_instrument(driver: type[KeithleyDMM6500 | Keithley26xxB]) -> None:
    """The flush on connect gives up after 100 ms, if the instrument does not answer."""
    conn = FakeConnection(connected=False, read_delay=10)

    async def test() -> None:
        await asyncio.wait_for(driver(conn).connect(), timeout=1)

    asyncio.run(test())
    assert conn.connected
