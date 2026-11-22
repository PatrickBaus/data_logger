"""Tests of the data generator and the logging daemon."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pytest

import data_logger
from data_logger import DataGenerator, LoggingDaemon

from .fakes import FakeSensor, raises, returns


async def _collect(generator: DataGenerator, count: int) -> list[tuple[object, ...]]:
    results = []
    async for _timestamp, data in generator.read_sensors(time_interval=0):
        results.append(tuple(item.value for item in data))
        if len(results) == count:
            break
    return results


def test_read_sensors_flattens_the_data() -> None:
    sensors = [FakeSensor([returns(1, 2), returns(4, 5)]), FakeSensor([returns(3), returns(6)])]
    assert asyncio.run(_collect(DataGenerator(sensors), 2)) == [(1, 2, 3), (4, 5, 6)]
    assert sensors[0].post_reads == 1  # run between the two reads


@pytest.mark.parametrize(
    "error",
    [ValueError("bad"), InvalidOperation(), TimeoutError()],
    ids=["ValueError", "InvalidOperation", "TimeoutError"],
)
def test_read_sensors_retries_after_invalid_data(error: Exception) -> None:
    """InvalidOperation from Decimal() is not a ValueError and used to crash the logger."""
    sensor = FakeSensor([raises(error), returns(Decimal("1.5"))])
    assert asyncio.run(_collect(DataGenerator([sensor]), 1)) == [(Decimal("1.5"),)]


def test_read_sensors_raises_connection_errors() -> None:
    sensor = FakeSensor([raises(ConnectionResetError("lost"))])
    with pytest.raises(ConnectionResetError):
        asyncio.run(_collect(DataGenerator([sensor]), 1))


def test_read_sensors_raises_cancelled_error() -> None:
    """A cancelled read used to be skipped silently."""
    sensor = FakeSensor([raises(asyncio.CancelledError())])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_collect(DataGenerator([sensor]), 1))


def test_failed_connect_disconnects_the_other_devices() -> None:
    good = FakeSensor()
    bad = FakeSensor(connect_error=ConnectionRefusedError("refused"))

    async def test() -> None:
        async with DataGenerator([good, bad]):
            pass

    with pytest.raises(ConnectionRefusedError):
        asyncio.run(test())
    assert good.connect_calls == 1 and not good.connected


def test_get_header() -> None:
    sensors = [FakeSensor(column_names=["a", "b"]), FakeSensor(column_names=["c"])]
    header = asyncio.run(DataGenerator(sensors).get_header())
    assert header[0] == "# Fake sensor\n"
    assert header[2].startswith("# Log started at UTC: ")
    assert header[-1] == "# Date,a,b,c\n"


@pytest.mark.parametrize(
    "error",
    [ConnectionRefusedError("refused"), TimeoutError(), EOFError(), OSError("I/O error")],
    ids=["ConnectionRefusedError", "TimeoutError", "EOFError", "OSError"],
)
def test_daemon_reconnects_with_a_delay(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """Connection errors cause a reconnect after the reconnect interval, not a crash or a busy loop."""
    sensor = FakeSensor(connect_error=error)
    sleeps = []
    real_sleep = asyncio.sleep

    async def sleep(delay: float, *args: Any) -> None:
        if delay == 0:  # asyncio.sleep(0) of the fake sensor
            return await real_sleep(0, *args)
        sleeps.append(delay)
        if len(sleeps) == 3:
            raise asyncio.CancelledError()  # stop the daemon
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    daemon = LoggingDaemon(logging_devices=[sensor], endpoints={}, reconnect_interval=7)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(daemon.run())
    assert sensor.connect_calls == 3
    assert sleeps == [7, 7, 7]


def test_daemon_does_not_swallow_other_errors() -> None:
    sensor = FakeSensor([raises(RuntimeError("bug"))])
    daemon = LoggingDaemon(logging_devices=[sensor], endpoints={})
    with pytest.raises(RuntimeError):
        asyncio.run(daemon.run())


def test_daemon_stops_when_cancelled() -> None:
    async def test() -> None:
        daemon = LoggingDaemon(logging_devices=[FakeSensor()], endpoints={})
        task = asyncio.create_task(daemon.run())
        await asyncio.sleep(0.05)
        task.cancel()
        await task

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(test())


def test_main_without_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        data_logger.main(["-c", "does_not_exist.yml"])
    assert exc_info.value.code == 1


@pytest.fixture(name="sleeps")
def fixture_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Skip the reconnect delays of the daemon and record them."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def sleep(delay: float, *args: Any) -> None:
        if delay != 0:  # asyncio.sleep(0) of the fake sensor
            sleeps.append(delay)
        return await real_sleep(0, *args)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return sleeps


def test_daemon_gives_up_after_invalid_startup_data(sleeps: list[float]) -> None:
    """Invalid data during the startup, like a stale *IDN? reply, is retried 3 times, then the logger stops."""
    sensor = FakeSensor(connect_errors=[ValueError("stale reply")] * 10)
    daemon = LoggingDaemon(logging_devices=[sensor], endpoints={}, reconnect_interval=7)
    with pytest.raises(ValueError, match="stale reply"):
        asyncio.run(daemon.run())
    assert sensor.connect_calls == 1 + data_logger.MAX_STARTUP_RETRIES
    assert sleeps == [7] * data_logger.MAX_STARTUP_RETRIES
    assert not sensor.connected


def test_daemon_recovers_from_a_stale_reply(sleeps: list[float]) -> None:
    sensor = FakeSensor(
        [returns(1), raises(RuntimeError("stop the daemon"))],
        connect_errors=[ValueError("stale reply"), InvalidOperation(), None],
    )
    daemon = LoggingDaemon(logging_devices=[sensor], endpoints={}, reconnect_interval=7)
    with pytest.raises(RuntimeError, match="stop the daemon"):  # The startup succeeded and the logger read the data
        asyncio.run(daemon.run())
    assert sensor.connect_calls == 3
    assert sleeps == [7, 7]


def test_invalid_header_data_is_a_startup_failure(sleeps: list[float], tmp_path: Path) -> None:
    sensor = FakeSensor(
        [returns(1), raises(RuntimeError("stop the daemon"))],
        header_errors=[ValueError("stale reply"), None],
    )
    endpoints = {"file": {"filename": str(tmp_path / "log.csv"), "descriptor": "Test"}}
    daemon = LoggingDaemon(logging_devices=[sensor], endpoints=endpoints, reconnect_interval=7)
    with pytest.raises(RuntimeError, match="stop the daemon"):
        asyncio.run(daemon.run())
    assert sensor.header_calls == 2
    assert sleeps == [7]


def test_startup_failures_are_counted_again_after_a_successful_startup(sleeps: list[float]) -> None:
    """Only consecutive failures count. A stale reply days later, after a reconnect, gets its own retries."""
    stale = ValueError("stale reply")
    sensor = FakeSensor(
        [returns(1), raises(ConnectionResetError("connection lost")), returns(2), raises(RuntimeError("stop"))],
        connect_errors=[stale, stale, stale, None, stale, stale, stale, None],
    )
    daemon = LoggingDaemon(logging_devices=[sensor], endpoints={}, reconnect_interval=7)
    with pytest.raises(RuntimeError, match="stop"):
        asyncio.run(daemon.run())
    assert sensor.connect_calls == 8
    assert len(sleeps) == 3 + 1 + 3  # retries, the reconnect after the lost connection, retries


@pytest.fixture(name="root_handlers")
def fixture_root_handlers() -> Iterator[None]:
    """Remove the log handlers added by a test, so the log files of a test are not used by the others."""
    root = logging.getLogger()
    handlers = list(root.handlers)
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()


@pytest.mark.usefixtures("root_handlers")
def test_error_log_is_named_by_the_start_time(tmp_path: Path) -> None:
    """Each run gets its own error log, like the data file. It used to be errors.log, appended to by every run."""
    data_logger.setup_error_log(str(tmp_path / "logs" / "errors_{date}.log"))
    logs = tmp_path / "logs"
    assert not list(logs.iterdir())  # The file is created by the first error, not at startup
    logging.getLogger("test").info("not an error")
    assert not list(logs.iterdir())
    logging.getLogger("test").error("the instrument is on fire")

    (log,) = logs.iterdir()
    assert re.fullmatch(r"errors_\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2}\+00:00\.log", log.name)
    assert "the instrument is on fire" in log.read_text(encoding="utf-8")


@pytest.mark.usefixtures("root_handlers")
def test_error_log_without_date_is_appended_to(tmp_path: Path) -> None:
    for message in ("first run", "second run"):
        handler = data_logger.setup_error_log(str(tmp_path / "errors.log"))
        logging.getLogger("test").error(message)
        logging.getLogger().removeHandler(handler)
        handler.close()
    assert (tmp_path / "errors.log").read_text(encoding="utf-8").count(" run") == 2


@pytest.mark.usefixtures("root_handlers")
@pytest.mark.parametrize("configured", [True, False], ids=["configured", "default"])
def test_main_writes_errors_to_the_configured_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    config = "endpoints: {}\ndevices: []\n" + ("error_log: logs/run_{date}.log\n" if configured else "")
    (tmp_path / "config.yml").write_text(config, encoding="utf-8")

    async def run(_self: LoggingDaemon) -> None:
        logging.getLogger("test").error("logged during the run")

    monkeypatch.setattr(LoggingDaemon, "run", run)
    data_logger.main(["-c", "config.yml"])

    (log,) = (tmp_path / "logs").glob("run_*.log") if configured else tmp_path.glob("errors_*.log")
    assert "logged during the run" in log.read_text(encoding="utf-8")
