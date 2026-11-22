"""Tests of the HP/Keysight 3458A and Keysight 34470A drivers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from devices import Hp3458A, Keysight34470A

from .fakes import FakeConnection


@pytest.mark.parametrize(
    "method, cmd",
    [
        ("get_acal1v", "CAL? 71,1"),
        ("get_acal10v", "CAL? 72,1"),
        ("get_cal7v", "CAL? 2"),
        ("get_cal40k", "CAL? 1"),
        ("get_temperature_acal_dcv", "CAL? 175"),
        ("get_temperature", "TEMP?"),
    ],
)
@pytest.mark.parametrize("reply, expected", [(" 1.23456E+00", Decimal("1.23456")), ("garbage", None)])
def test_hp3458a_calibration_values(method: str, cmd: str, reply: str, expected: Decimal | None) -> None:
    device = Hp3458A(FakeConnection({cmd: reply}))
    coro: Coroutine[Any, Any, Decimal] = getattr(device, method)()
    if expected is None:
        with pytest.raises(ValueError, match="garbage"):
            asyncio.run(coro)
    else:
        assert asyncio.run(coro) == expected


def test_hp3458a_connect_and_identify() -> None:
    conn = FakeConnection({"ID?": "HP3458A"}, connected=False)
    device = Hp3458A(conn)

    async def test() -> str:
        await device.connect()
        identity = await device.get_id()
        await device.disconnect()
        return identity

    assert asyncio.run(test()) == "HP3458A"
    assert conn.written[0] == "END ALWAYS; TARM HOLD"  # The setup recommended by the manual
    assert not conn.connected


def test_hp3458a_read() -> None:
    conn = FakeConnection({"TRIG SGL": " 9.99999876E+00"})
    device = Hp3458A(conn)

    async def test() -> str:
        await device.write("TRIG SGL")
        return await device.read()

    assert asyncio.run(test()) == "9.99999876E+00"


def test_hp3458a_acal_dcv(monkeypatch: pytest.MonkeyPatch) -> None:
    """ACAL DCV takes 165 s. The driver waits for it, the test skips the wait."""
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    conn = FakeConnection()
    asyncio.run(Hp3458A(conn).acal_dcv())
    assert conn.written == ["BEEP", "ACAL DCV"]
    assert sleeps == [165]


def _ks_cal(temperature: str = "+2.35E+01") -> dict[str, str | bytes]:
    return {
        "CALibration:DATE?": "+2024,+01,+02",
        "CALibration:TIME?": "12,30,00.000",
        "CALibration:TEMPerature?": temperature,
        "CALibration:STRing?": '"cal string"',
        "SYSTem:ACALibration:DATE?": "+2026,+11,+20",
        "SYSTem:ACALibration:TIME?": "09,12,44.000",
        "SYSTem:ACALibration:TEMPerature?": temperature,
        "SYSTem:UPTime?": "+3,+2,+1,+13",
        "FETCH?": "+1.00000000E+01",
        "*IDN?": "Keysight Technologies,34470A,MY12345678,A.03.02",
    }


def test_ks34470a_connect_flushes_and_disconnects() -> None:
    """Connecting aborts a running measurement and discards a pending reply."""
    conn = FakeConnection(connected=False)
    device = Keysight34470A(conn)

    async def test() -> None:
        await device.connect()
        await device.disconnect()

    asyncio.run(test())
    assert conn.written == [":ABORt"]
    assert not conn.connected


def test_ks34470a_acal_data() -> None:
    acal_date, temperature = asyncio.run(Keysight34470A(FakeConnection(_ks_cal())).get_acal_data())
    assert acal_date == datetime(2026, 11, 20, 9, 12, 44, tzinfo=timezone.utc)
    assert temperature == Decimal("23.5")


def test_ks34470a_invalid_acal_temperature() -> None:
    with pytest.raises(ValueError, match="garbage"):
        asyncio.run(Keysight34470A(FakeConnection(_ks_cal("garbage"))).get_acal_data())


def test_ks34470a_uptime_id_and_fetch() -> None:
    device = Keysight34470A(FakeConnection(_ks_cal()))

    async def test() -> tuple[timedelta, str, str]:
        return await device.get_system_uptime(), await device.get_id(), await device.fetch()

    uptime, identity, value = asyncio.run(test())
    assert uptime == timedelta(days=3, hours=2, minutes=1, seconds=13)
    assert identity.startswith("Keysight Technologies,34470A")
    assert value == "+1.00000000E+01"


@pytest.mark.parametrize(
    "method, args, cmd",
    [
        ("beep", (), "SYSTem:BEEP"),
        ("set_mode_resistance_2w", (), "SENSe:FUNC 'RES'"),
        ("set_mode_resistance_4w", (), "SENSe:FUNC 'FRES'"),
        ("set_nplc", (10,), "SENSe:RES:NPLC 10"),
    ],
)
def test_ks34470a_commands(method: str, args: tuple[Any, ...], cmd: str) -> None:
    conn = FakeConnection()
    action: Callable[..., Coroutine[Any, Any, None]] = getattr(Keysight34470A(conn), method)
    asyncio.run(action(*args))
    assert conn.written == [cmd]


def test_ks34470a_read() -> None:
    conn = FakeConnection({"INIT": "+9.99999876E+00"})
    device = Keysight34470A(conn)

    async def test() -> str:
        await device.write("INIT")
        return await device.read()

    assert asyncio.run(test()) == "+9.99999876E+00"


@pytest.mark.parametrize("reply, error_logged", [("+0", False), ("+1", True)], ids=["success", "failed"])
def test_ks34470a_acal(reply: str, error_logged: bool, caplog: pytest.LogCaptureFixture) -> None:
    """ACAL takes about 15 s, so the timeout of the query is extended."""
    conn = FakeConnection({"*CAL?": reply})
    asyncio.run(Keysight34470A(conn).acal())
    assert conn.read_timeouts == [pytest.approx(14.5 * 1.1)]
    assert ("Error during ACAL of 34470A." in caplog.text) == error_logged
