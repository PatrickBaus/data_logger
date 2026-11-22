"""Tests of the logging devices."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

import pytest

from factories import device_factory
from logger.logger import DataEvent, Keithley2002ScannerLogger, Keysight34470ALogger, to_decimal

from .fakes import UUID_A, event


def test_data_event_timestamp_is_created_per_event() -> None:
    """The default used to be evaluated once, when the class was defined."""
    first = DataEvent(sender=UUID_A, sid=0, topic="a", value=1, unit="")
    time.sleep(0.01)
    second = DataEvent(sender=UUID_A, sid=0, topic="a", value=1, unit="")
    assert second.timestamp > first.timestamp
    assert first.timestamp.tzinfo is not None


def test_data_event_str() -> None:
    assert str(event(Decimal("1.5"))) == "1.5"


def test_to_decimal() -> None:
    assert to_decimal("+1.23E-3") == Decimal("0.00123")
    for invalid in ("garbage", None, ""):
        with pytest.raises(ValueError):
            to_decimal(invalid)


def _ks34470a() -> Keysight34470ALogger:
    return Keysight34470ALogger(host="127.0.0.1", port=5025, timeout=1, uuid=UUID_A, base_topic="sensors/ks")


def test_logger_read(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _ks34470a()

    async def query(_cmd: str) -> str:
        return "+1.00000E+00"

    monkeypatch.setattr(logger.device, "query", query)
    (result,) = asyncio.run(logger.read())
    assert result.value == Decimal("1") and result.topic == "sensors/ks" and result.sender == UUID_A


def test_logger_invalid_reading_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A garbled reading must raise a ValueError, so the data generator retries instead of crashing."""
    logger = _ks34470a()

    async def query(_cmd: str) -> str:
        return "garbage"

    monkeypatch.setattr(logger.device, "query", query)
    with pytest.raises(ValueError):
        asyncio.run(logger.read())


def test_k2002_scanner_column_names() -> None:
    default = Keithley2002ScannerLogger(active_channels=[0, 2], name=0, pad=16, timeout=100, uuid=UUID_A)
    assert default.column_names == ["K2002 CH1", "K2002 CH3"]
    # Configuring the column names used to fail with "got multiple values for keyword argument 'column_names'"
    custom = Keithley2002ScannerLogger(
        active_channels=[0, 2], name=0, pad=16, timeout=100, uuid=UUID_A, column_names=["Ref A", "Ref B"]
    )
    assert custom.column_names == ["Ref A", "Ref B"]


def test_device_factory_creates_devices_from_config() -> None:
    logger = device_factory.get(driver="ks34470a", host="127.0.0.1", port=5025, timeout=1, uuid=UUID_A)
    assert isinstance(logger, Keysight34470ALogger)
