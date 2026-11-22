#!/usr/bin/env python3
# ##### BEGIN GPL LICENSE BLOCK #####
#
# Copyright (C) 2021  Patrick Baus
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####
"""
The data logger. It reads the instruments listed in the configuration file and pushes the data to the
configured endpoints.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import warnings
from collections.abc import AsyncIterator, Awaitable, Sequence
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from decimal import InvalidOperation
from itertools import chain
from types import TracebackType
from typing import Any, Protocol, Self, cast

import yaml

from _version import __version__
from endpoints import Filewriter
from factories import device_factory, endpoint_factory
from logger.logger import DataEvent

DEFAULT_WAIT_TIMEOUT = 10  # in seconds
DEFAULT_RECONNECT_INTERVAL = 5  # in seconds
# Retries after invalid data during the startup, before the logger gives up. Typically caused by a stale reply in the
# buffer of an instrument, which shifts all following replies.
MAX_STARTUP_RETRIES = 3
LOG_LEVEL = logging.INFO
# The name of the error log. "{date}" is replaced by the start time, like in the name of the data file.
DEFAULT_ERROR_LOG = "errors_{date}.log"
ERROR_LOG_FMT = "%(asctime)s %(name)-12s %(levelname)-8s %(message)s"


class Sensor(Protocol):
    """The methods of a logging device, that are used by the `DataGenerator`."""

    @property
    def column_names(self) -> list[str]: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def get_log_header(self) -> str: ...

    async def read(self) -> tuple[DataEvent, ...]: ...

    async def post_read(self) -> None: ...


class DataGenerator:
    """
    Connects to the logging devices and reads them in a loop.
    """

    def __init__(self, sensors: Sequence[Sensor]) -> None:
        self.__sensors = sensors
        self.__logger = logging.getLogger(__name__)

    async def __aenter__(self) -> Self:
        self.__logger.info("Initializing devices")
        self.__logger.debug("Devices to initialize: %s.", self.__sensors)
        # Connect to all devices
        coros = [device.connect() for device in self.__sensors]
        results = await asyncio.gather(*coros, return_exceptions=True)
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            # __aexit__() is not called if __aenter__() fails, so disconnect the devices, that did connect.
            await self.__disconnect_all()
            raise errors[0]

        self.__logger.info("Devices initialized successfully.")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.__disconnect_all()

    async def __disconnect_all(self) -> None:
        self.__logger.debug("Disconnecting devices.")
        coros = [device.disconnect() for device in self.__sensors]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                self.__logger.error("Error during shutdown of the data generator.", exc_info=result)

    async def get_header(self) -> list[str]:
        """
        Create the header of the log file. It contains the info header of each device and the column names.
        """
        self.__logger.debug("Creating file header")
        # create info header
        coros = [device.get_log_header() for device in self.__sensors]
        headers = await asyncio.gather(*coros)
        result = [f"# {header}\n" for header in headers if header]
        # drop the microseconds
        date = datetime.now(timezone.utc).replace(microsecond=0)
        result.append(f"# Log started at UTC: {date.isoformat()}\n")

        # create column names
        column_names = chain(
            [
                "Date",
            ],
            *[device.column_names for device in self.__sensors],
        )
        result.append(f"# {','.join(column_names)}\n")
        return result

    async def read_sensors(self, time_interval: float) -> AsyncIterator[tuple[datetime, tuple[DataEvent, ...]]]:
        """
        Read all devices in a loop and yield the data of each round.

        Invalid data and timeouts are logged and the round is skipped. Other errors, for example connection errors, are
        raised to the caller.

        Parameters
        ----------
        time_interval: float
            The minimum time in seconds between two rounds. The slowest device determines the actual interval.
        """
        self.__logger.info("Reading data from devices")
        while "not canceled":
            try:
                coros: list[Awaitable[tuple[DataEvent, ...] | None]]
                coros = [device.read() for device in self.__sensors]
                # Wait for the slowest device or at least {time_interval}
                coros.append(asyncio.sleep(time_interval))
                #  Strip the None result from sleep() at the end
                results = tuple((await asyncio.gather(*coros, return_exceptions=True))[:-1])
                errors = [result for result in results if isinstance(result, BaseException)]
                for error in errors:
                    # Log all exceptions (except Timeouts, we will log it and retry later).
                    if isinstance(error, Exception) and not isinstance(error, TimeoutError):
                        self.__logger.error("Error during read.", exc_info=error)
                if errors:
                    # Raise the first error. This includes BaseExceptions like asyncio.CancelledError, which must not
                    # be swallowed.
                    raise errors[0]

                events = cast(tuple[tuple[DataEvent, ...], ...], results)  # all results are data, errors were raised
                yield datetime.now(timezone.utc), tuple(chain.from_iterable(events))  # flatten the tuple of tuples

                # Run post-read
                await asyncio.gather(*[device.post_read() for device in self.__sensors])
            except (ValueError, InvalidOperation):
                # InvalidOperation is raised by Decimal() and is not a ValueError
                self.__logger.error("Sensor read invalid data. Retrying.")
            except TimeoutError:
                # This includes OSError(errno.ETIMEDOUT), Python raises it as TimeoutError.
                self.__logger.error("Timeout during read. Retrying.")
            # Other errors, like OSError(errno.ENETUNREACH) "Network is unreachable", are raised to the logging
            # daemon, which reconnects after the reconnect interval.


def _describe(exc: BaseException) -> str:
    """Describe an error for the log. Some errors have no message, and the log messages add their own period."""
    return (str(exc) or type(exc).__name__).rstrip(".")


class LoggingDaemon:  # pylint: disable=too-few-public-methods
    """
    Connects the devices with the endpoints and reconnects them, if the connection is lost or the startup fails with
    invalid data.
    """

    def __init__(
        self,
        logging_devices: Sequence[Sensor],
        endpoints: dict[str, dict[str, Any]],
        time_interval: float = 0,
        reconnect_interval: float = DEFAULT_RECONNECT_INTERVAL,
    ) -> None:
        self.__devices = logging_devices
        self.__endpoints = {
            endpoint: endpoint_factory.get(driver=endpoint, **endpoints[endpoint]) for endpoint in endpoints
        }
        self.__time_interval = time_interval
        self.__reconnect_interval = reconnect_interval
        self.__startup_failures = 0

        self.__logger = logging.getLogger(__name__)

    async def _read_sensors(self) -> None:
        async with AsyncExitStack() as stack:
            endpoint_queues = await asyncio.gather(
                *[stack.enter_async_context(endpoint) for endpoint in self.__endpoints.values()]
            )

            data_generator: DataGenerator = await stack.enter_async_context(DataGenerator(self.__devices))

            file_endpoint = self.__endpoints.get("file")
            if isinstance(file_endpoint, Filewriter):
                await file_endpoint.write(await data_generator.get_header())
            self.__startup_failures = 0  # The startup succeeded

            async for timestamp, data in data_generator.read_sensors(self.__time_interval):
                for queue in endpoint_queues:
                    queue.put_nowait((timestamp, data))
                self.__logger.info(",".join(map(str, data)))

    async def run(self) -> None:
        """
        Run the logger until it is cancelled or receives SIGHUP, SIGTERM or SIGINT. Connection errors cause a
        reconnect after `reconnect_interval` seconds. Invalid data during the startup does the same, but only
        `MAX_STARTUP_RETRIES` times in a row.

        Raises
        ------
        ValueError
            If the startup failed with invalid data more than `MAX_STARTUP_RETRIES` times in a row
        """
        # Catch signals and shutdown. Cancel this task, not only the current attempt, so that a signal also stops the
        # logger while it is waiting to reconnect.
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        loop = asyncio.get_running_loop()
        this_task = asyncio.current_task()
        assert this_task is not None
        for sig in signals:
            loop.add_signal_handler(sig, this_task.cancel)
        try:
            while "not cancelled":
                try:
                    await self._read_sensors()
                except (OSError, EOFError) as exc:
                    self.__logger.error(
                        "Connection error: %s. Reconnecting in %g s.", _describe(exc), self.__reconnect_interval
                    )
                    await asyncio.sleep(self.__reconnect_interval)
                except (ValueError, InvalidOperation) as exc:
                    # The read loop handles invalid data itself, so this comes from connecting, initializing the
                    # instruments or writing the header. Typically a stale reply in the buffer of an instrument.
                    self.__startup_failures += 1
                    if self.__startup_failures > MAX_STARTUP_RETRIES:
                        self.__logger.error(
                            "Invalid data during the startup: %s. Giving up after %d retries.",
                            _describe(exc),
                            MAX_STARTUP_RETRIES,
                        )
                        raise
                    self.__logger.error(
                        "Invalid data during the startup: %s. Retrying in %g s (retry %d of %d).",
                        _describe(exc),
                        self.__reconnect_interval,
                        self.__startup_failures,
                        MAX_STARTUP_RETRIES,
                    )
                    await asyncio.sleep(self.__reconnect_interval)
        except asyncio.CancelledError:
            self.__logger.info("Logging daemon shut down.")
            raise
        finally:
            for sig in signals:
                loop.remove_signal_handler(sig)


def init_argparse() -> argparse.ArgumentParser:
    """Create the command line parser."""
    arg_parser = argparse.ArgumentParser(
        usage="%(prog)s [-c config_file]",
        description="Read sensors and push the data to one or more endpoints.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    arg_parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"{arg_parser.prog} version {__version__}",
    )
    arg_parser.add_argument(
        "-c",
        "--config_file",
        default="config.yml",
        help="The configuration file for the measurement.",
    )
    return arg_parser


def setup_logging() -> None:
    """Log to the console."""
    # Report all mistakes managing asynchronous resources.
    warnings.simplefilter("always", ResourceWarning)
    # Enable logs from the ip connection. Set to debug for even more info
    logging.basicConfig(level=LOG_LEVEL)


def setup_error_log(filename: str) -> logging.FileHandler:
    """
    Log errors to a file. "{date}" in the filename is replaced by the start time, so each run gets its own file. A
    filename without "{date}" is appended to. The file is only created, when the first error is logged.

    Parameters
    ----------
    filename: str
        The name of the error log, for example "logs/errors_{date}.log". Missing directories are created.

    Returns
    -------
    logging.FileHandler
        The handler added to the root logger
    """
    # drop the microseconds, like the name of the data file
    date = datetime.now(timezone.utc).replace(microsecond=0)
    path = filename.format(date=date.isoformat("_"))
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    logfile_handler = logging.FileHandler(path, encoding="utf-8", delay=True)
    logfile_handler.setLevel(level=logging.ERROR)
    logfile_handler.setFormatter(logging.Formatter(fmt=ERROR_LOG_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(logfile_handler)
    return logfile_handler


def main(argv: Sequence[str] | None = None) -> None:
    """Parse the command line, load the configuration and run the logger."""
    setup_logging()
    try:
        parser = init_argparse()
        args = parser.parse_args(argv)

        try:
            with open(args.config_file, "r", encoding="utf-8") as file:
                measurement_config = yaml.safe_load(file)
        except FileNotFoundError:
            logging.getLogger(__name__).error("Config file not found")
            parser.print_help()
            sys.exit(1)

        setup_error_log(measurement_config.get("error_log", DEFAULT_ERROR_LOG))

        devices = [device_factory.get(**device_config) for device_config in measurement_config.get("devices", [])]

        logging_daemon = LoggingDaemon(
            endpoints=measurement_config.get("endpoints", {}),
            logging_devices=devices,
            time_interval=measurement_config.get("time_interval", 0),
            reconnect_interval=measurement_config.get("reconnect_interval", DEFAULT_RECONNECT_INTERVAL),
        )

        asyncio.run(logging_daemon.run(), debug=False)
    except KeyboardInterrupt:
        # The loop will be canceled on a KeyboardInterrupt by the run() method, we
        # just want to suppress the exception
        pass
    except asyncio.CancelledError:
        # The program will terminate now, so we swallow the error to suppress
        # the error message
        pass
    finally:
        logging.getLogger(__name__).info("Datalogger terminated. Have fun analyzing the data.")


if __name__ == "__main__":
    main()
