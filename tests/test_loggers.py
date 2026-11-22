"""Tests of the logging devices. They create the drivers and connections from the configuration and turn the
readings into data events. The connections are replaced by fakes."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from tinkerforge_async import base58decode

import logger.logger as logger_module
from devices import Wavemaster
from errors import ConfigurationError
from logger.logger import (
    DataEvent,
    EE07Logger,
    Fluke1524Logger,
    Fluke1590Logger,
    Keithley26xxBLogger,
    Keithley2002Logger,
    Keithley2002ScannerLogger,
    KeithleyDMM6500Logger,
    Keysight3458ALogger,
    Keysight34470ALogger,
    LDT5948Logger,
    LoggingDevice,
    TinkerforgeHumidity,
    TinkerforgeLogger,
    WavemasterLogger,
)

from .fakes import UUID_A, FakeConnection, FakeDevice


class _Connections:  # pylint: disable=too-few-public-methods  # A factory of factories
    """Creates fake connections instead of the real ones and records, how they were created."""

    def __init__(self) -> None:
        self.replies: dict[str, str | bytes | list[str | bytes | BaseException]] = {}
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.connections: list[FakeConnection] = []

    def factory(self, transport: str) -> Callable[..., FakeConnection]:
        def create(**kwargs: Any) -> FakeConnection:
            self.created.append((transport, kwargs))
            self.connections.append(FakeConnection(self.replies, connected=False))
            return self.connections[-1]

        return create


@pytest.fixture(name="connections")
def fixture_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Connections]:
    connections = _Connections()
    for name, transport in [
        ("EthernetConnection", "ethernet"),
        ("GpibConnection", "gpib"),
        ("PrologixGpibConnection", "prologix"),
        ("SerialConnection", "serial"),
    ]:
        monkeypatch.setattr(logger_module, name, connections.factory(transport))
    yield connections


def _values(events: tuple[DataEvent, ...]) -> list[tuple[int, str, Any, str]]:
    return [(event.sid, event.topic, event.value, event.unit) for event in events]


def _run(device: LoggingDevice[Any]) -> tuple[str, tuple[DataEvent, ...]]:
    """Connect, write the header, read once and disconnect."""

    async def test() -> tuple[str, tuple[DataEvent, ...]]:
        await device.connect()
        try:
            return await device.get_log_header(), await device.read()
        finally:
            await device.disconnect()

    return asyncio.run(test())


# The base class
def test_logging_device_base_class() -> None:
    fake = FakeDevice()
    device = LoggingDevice(fake, uuid=UUID_A, initial_commands=["*RST", "*CLS"])
    assert _run(device) == ("", ())
    assert fake.written == ["*RST", "*CLS"]
    assert device.column_names == [""]
    with pytest.raises(NotImplementedError):
        LoggingDevice.driver()


@pytest.mark.parametrize("device_name, expected", [(None, "FakeDevice"), ("My DMM", "My DMM")])
def test_logging_device_name(device_name: str | None, expected: str, caplog: pytest.LogCaptureFixture) -> None:
    """Without a configured name, the device is named by its id."""
    caplog.set_level("DEBUG")
    device = LoggingDevice(FakeDevice(), uuid=UUID_A, device_name=device_name)

    async def test() -> None:
        await device.connect()
        await device.read()

    asyncio.run(test())
    assert f"Reading {expected}..." in caplog.text


# Ethernet instruments
def test_ks34470a_logger(connections: _Connections) -> None:
    connections.replies.update(
        {
            "*IDN?": "Keysight Technologies,34470A,MY12345678,A.03.02",
            "CALibration:DATE?": "+2024,+01,+02",
            "CALibration:TIME?": "12,30,00.000",
            "CALibration:TEMPerature?": "+2.35E+01",
            "CALibration:STRing?": '"cal"',
            "SYSTem:ACALibration:DATE?": "+2026,+11,+20",
            "SYSTem:ACALibration:TIME?": "09,12,44.000",
            "SYSTem:ACALibration:TEMPerature?": "+2.41E+01",
            "SYSTem:UPTime?": "+3,+2,+1,+13",
            "READ?": "+1.00000123E+01",
        }
    )
    device = Keysight34470ALogger(host="192.168.1.10", port=5025, timeout=5, uuid=UUID_A, base_topic="dmm")
    header, events = _run(device)
    assert connections.created == [("ethernet", {"host": "192.168.1.10", "port": 5025, "timeout": 5})]
    assert header == (
        "KS34470A CAL DATE=2024-01-02 12:30:00+00:00; TEMP=23.5 °C; ACAL DATE=2026-11-20 09:12:44+00:00;"
        " TEMP=24.1 °C; Uptime=3 days, 2:01:13"
    )
    assert _values(events) == [(0, "dmm", Decimal("10.0000123"), "")]


def test_dmm6500_logger(connections: _Connections) -> None:
    connections.replies.update({"*IDN?": "KEITHLEY INSTRUMENTS,MODEL DMM6500", "READ?": "+1.0001E+04"})
    device = KeithleyDMM6500Logger(host="dmm", port=5025, timeout=5, uuid=UUID_A, base_topic="dmm")
    header, events = _run(device)
    assert connections.created == [("ethernet", {"host": "dmm", "port": 5025, "timeout": 5})]
    assert header == ""
    assert _values(events) == [(0, "dmm", Decimal("10001"), "")]


def test_k26xxb_logger(connections: _Connections) -> None:
    connections.replies.update(
        {
            "*IDN?": "Keithley Instruments Inc., Model 2612B, 4123456, 4.0.4",
            "print(smua.cal.date)": "0",
            "print(smub.cal.date)": "0",
            "print(smua.cal.due)": "86400",
            "print(smub.cal.due)": "86400",
            "print(localnode.revision)": "4.0.4",
            "print(localnode.serialno)": "4123456",
            "print(localnode.model)": "2612B",
            "print(smua.measure.i())": "1.23456e-03",
        }
    )
    device = Keithley26xxBLogger(host="smu", port=5025, timeout=5, uuid=UUID_A, base_topic="smu")
    header, events = _run(device)
    assert header == (
        "K2612B Serial 4123456; FW 4.0.4; Cal date ChA=1970-01-01 00:00:00+00:00; ChB=1970-01-01 00:00:00+00:00;"
        " Next Cal due ChA=1970-01-02 00:00:00+00:00; ChB=1970-01-02 00:00:00+00:00"
    )
    assert _values(events) == [(0, "smu", Decimal("0.00123456"), "A")]


# GPIB instruments
def test_hp3458a_logger(connections: _Connections) -> None:
    connections.replies.update(
        {
            "ID?": "HP3458A",
            "CAL? 71,1": "1.1",
            "CAL? 72,1": "7.2",
            "CAL? 175": "35.1",
            "CAL? 2": "7.1",
            "CAL? 1": "40000.5",
            "TEMP?": "36.2",
            "TRIG SGL": " 9.99999876E+00",  # The meter sends a reading after the trigger
        }
    )
    device = Keysight3458ALogger(name=0, pad=22, timeout=10, uuid=UUID_A)

    async def test() -> tuple[str, tuple[DataEvent, ...]]:
        await device.connect()
        header = await device.get_log_header()
        await device.device.write("TRIG SGL")
        return header, await device.read()

    header, events = asyncio.run(test())
    assert connections.created == [("gpib", {"name": 0, "pad": 22, "timeout": 10})]
    assert header == (
        "HP3458A ACAL constants CAL71=1.1; CAL72=7.2; ACAL TEMP=35.1 °C; 7Vref=7.1 V; 40kref=40000.5 Ω; TEMP=36.2 °C"
    )
    assert _values(events) == [(0, "", Decimal("9.99999876"), "")]


def _k2002_replies(connections: _Connections) -> None:
    connections.replies.update(
        {
            "*IDN?": "KEITHLEY INSTRUMENTS INC.,MODEL 2002",
            ":CALibration:PROTected:DATE?": "2022,11,29",
            ":CALibration:PROTected:NDUE?": "2023,11,29",
            ":DATA:FRESh?": [struct.pack("d", 7.04), struct.pack("d", 7.01)],
        }
    )


def test_k2002_logger(connections: _Connections) -> None:
    _k2002_replies(connections)
    device = Keithley2002Logger(name=0, pad=16, timeout=100, uuid=UUID_A, base_topic="k2002")
    header, events = _run(device)
    assert header == "K2002 Cal date=2022-11-29 00:00:00+00:00; Next Cal due=2023-11-29 00:00:00+00:00"
    assert _values(events) == [(0, "k2002", 7.04, "")]


def test_k2002_scanner_logger(connections: _Connections) -> None:
    _k2002_replies(connections)
    device = Keithley2002ScannerLogger(active_channels=[0, 3], name=0, pad=16, timeout=100, uuid=UUID_A, base_topic="s")
    _, events = _run(device)
    assert _values(events) == [(0, "s/channel1", 7.04, "V"), (3, "s/channel4", 7.01, "V")]
    assert connections.connections[0].written[-4:] == [
        ":rout:clos (@1)",
        ":DATA:FRESh?",
        ":rout:clos (@4)",
        ":DATA:FRESh?",
    ]
    assert device.column_names == ["K2002 CH1", "K2002 CH4"]


def test_k2002_invalid_binary_reading(connections: _Connections) -> None:
    """A reading, that is shorter than an 8 byte double, raises a ValueError, so the logger retries."""
    connections.replies.update({"*IDN?": "MODEL 2002", ":DATA:FRESh?": b"short"})
    for device in (
        Keithley2002Logger(name=0, pad=16, timeout=100, uuid=UUID_A),
        Keithley2002ScannerLogger(active_channels=[0], name=0, pad=16, timeout=100, uuid=UUID_A),
    ):

        async def test(device: Keithley2002Logger = device) -> None:
            await device.connect()
            await device.read()

        with pytest.raises(ValueError, match="invalid data"):
            asyncio.run(test())


def test_fluke1590_logger(connections: _Connections) -> None:
    connections.replies.update({"v": "VER: 1590,2.03", "new": "NEW: 1", "tem": "2: 10000.0869 O  15:02:52  10-31-22"})
    device = Fluke1590Logger(host="prologix", port=1234, pad=4, timeout=3, uuid=UUID_A, base_topic="fluke")
    header, events = _run(device)
    assert connections.created == [
        ("prologix", {"host": "prologix", "port": 1234, "pad": 4, "timeout": 3, "wait_delay": 1})
    ]
    assert header == ""
    assert _values(events) == [(1, "fluke/resistance/channel1", Decimal("10000.0869"), "Ω")]


def test_fluke1590_logger_configures_the_instrument(connections: _Connections) -> None:
    connections.replies.update({"v": "VER: 1590,2.03"})
    device = Fluke1590Logger(host="prologix", port=1234, pad=4, timeout=3, uuid=UUID_A)
    asyncio.run(device.connect())
    written = connections.connections[0].written
    assert written[:5] == ["v", "ter=lf", "ieed=on & ieet=on", "sact=r", "scrs=on & scrt=5"]
    assert written[5].startswith("dat=") and written[6:] == ["si=4", "ct=2", "st=4"]


# Serial instruments
@pytest.mark.parametrize(
    "port, expected",
    [
        ({"tty": "/dev/ttyUSB0"}, {"tty": "/dev/ttyUSB0"}),
        ({"vid": 0x0403, "pid": 0x6001, "serial_number": "A1"}, {"vid_pid": (0x0403, 0x6001), "serial_number": "A1"}),
    ],
    ids=["tty", "vid-pid"],
)
def test_ldt5948_logger(connections: _Connections, port: dict[str, Any], expected: dict[str, Any]) -> None:
    connections.replies.update(
        {
            "*IDN?": "ILX Lightwave,LDT-5948,59481234,1.30",
            "PID?": "15.00,0.003,2.000",
            "TIME?": "102:30:15",
            "MEAS:TEMP?": "23.252",
            "MEAS:ITE?": "0.516",
            "MEAS:VTE?": "0.937",
            "SET:TEMP?": "23",
        }
    )
    device = LDT5948Logger(timeout=0.5, baudrate=115200, uuid=UUID_A, base_topic="ldt", **port)
    header, events = _run(device)
    assert connections.created == [("serial", {**expected, "timeout": 0.5, "baudrate": 115200})]
    assert header == (
        "LDT5948 ILX Lightwave,LDT-5948,59481234,1.30; PID constants Kp=15.00; Ki=0.003; Kd=2.000; Uptime=102:30:15"
    )
    assert _values(events) == [
        (0, "ldt/temperature", Decimal("23.252"), "°C"),
        (1, "ldt/tec_current", Decimal("0.516"), "A"),
        (2, "ldt/tec_voltage", Decimal("0.937"), "V"),
        (3, "ldt/setpoint", Decimal("23.000"), "°C"),  # quantized to mK
    ]


def test_fluke1524_logger(connections: _Connections) -> None:
    connections.replies.update({"*IDN?": "HART,1524,A12345,1.10", "READ? 1": "28.046", "READ? 2": "32.102"})
    device = Fluke1524Logger(timeout=1, baudrate=9600, tty="/dev/ttyUSB1", uuid=UUID_A, base_topic="fluke")
    header, events = _run(device)
    assert header == "HART,1524,A12345,1.10"
    assert _values(events) == [
        (0, "fluke/temperature/channel1", Decimal("28.046"), "°C"),
        (1, "fluke/temperature/channel2", Decimal("32.102"), "°C"),
    ]


def test_ee07_logger(connections: _Connections) -> None:
    connections.replies.update({"*IDN?": "E+E Elektronik,EE07", "READ? 1": "27.47", "READ? 2": "23.39"})
    device = EE07Logger(timeout=0.5, baudrate=115200, tty="/dev/ttyACM0", uuid=UUID_A, base_topic="ee07")
    header, events = _run(device)
    assert header == "E+E Elektronik,EE07"
    assert _values(events) == [
        (0, "ee07/humidity", Decimal("27.47"), "%rH"),
        (1, "ee07/temperature", Decimal("23.39"), "°C"),
    ]


def test_wavemaster_logger() -> None:
    conn = FakeConnection({"*IDN?": "COHR, WaveMaster, 0123", "VAL?": "12345.6,1550.1234"}, connected=False)
    device = WavemasterLogger(Wavemaster(conn), uuid=UUID_A, base_topic="wavemaster")
    header, events = _run(device)
    assert header == ""
    assert _values(events) == [(0, "wavemaster", Decimal("1550.1234"), "nm")]


# Tinkerforge
class _FakeBricklet:  # pylint: disable=missing-function-docstring
    """Stand-in for the Tinkerforge humidity bricklet."""

    instances: list[_FakeBricklet] = []

    def __init__(self, uid: int, ipcon: Any) -> None:  # pylint: disable=unused-argument
        self.uid = uid
        self.humidity: list[Decimal | BaseException] = [Decimal("41.23")]
        self.connect_error: BaseException | None = None
        self.connect_calls = 0
        self.instances.append(self)

    async def connect(self) -> None:
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error

    async def disconnect(self) -> None:
        pass

    async def get_identity(self) -> tuple[str, str]:
        return "Dm6", "humidity v2"

    async def get_humidity(self) -> Decimal:
        value = self.humidity.pop(0) if len(self.humidity) > 1 else self.humidity[0]
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.fixture(name="bricklets")
def fixture_bricklets(monkeypatch: pytest.MonkeyPatch) -> list[_FakeBricklet]:
    _FakeBricklet.instances = []
    monkeypatch.setattr(logger_module, "BrickletHumidityV2", _FakeBricklet)
    return _FakeBricklet.instances


@pytest.mark.parametrize("uid, expected_uid", [(12345, 12345), ("Dm6", 12345)], ids=["int", "base58"])
def test_tinkerforge_logger(bricklets: list[_FakeBricklet], uid: int | str, expected_uid: int) -> None:
    device = TinkerforgeLogger(host="localhost", uid=uid, uuid=UUID_A, base_topic="tf")
    header, events = _run(device)
    (bricklet,) = bricklets
    assert bricklet.uid == (expected_uid if isinstance(uid, int) else base58decode(uid))
    assert header == ""
    assert _values(events) == [(0, "tf/humidity", Decimal("41.23"), "%rH")]
    assert asyncio.run(device.get_id()) == "('Dm6', 'humidity v2')"


@pytest.mark.parametrize("reconnect_fails", [False, True], ids=["reconnected", "reconnect-failed"])
def test_tinkerforge_logger_reconnects(
    bricklets: list[_FakeBricklet], reconnect_fails: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """A lost connection to the brick daemon is reported as a timeout, so the logger retries the reading."""
    device = TinkerforgeLogger(host="localhost", uid=12345, uuid=UUID_A)
    (bricklet,) = bricklets
    bricklet.humidity = [ConnectionResetError("lost"), Decimal("41.23")]
    bricklet.connect_error = OSError("brick daemon down") if reconnect_fails else None
    with pytest.raises(TimeoutError, match="Reconnecting"):
        asyncio.run(device.read())
    assert bricklet.connect_calls == 1
    assert ("Error during re-connect attempt" in caplog.text) == reconnect_fails


@pytest.mark.usefixtures("bricklets")
def test_tinkerforge_bricklet_does_not_accept_commands() -> None:
    device = TinkerforgeLogger(host="localhost", uid=12345, uuid=UUID_A).device
    assert isinstance(device, TinkerforgeHumidity)
    with pytest.raises(ConfigurationError, match="does not accept commands"):
        asyncio.run(device.write("*RST"))
