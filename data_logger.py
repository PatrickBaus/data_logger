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
import signal
import sys
import warnings
from collections.abc import AsyncIterator, Awaitable, Sequence
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from decimal import InvalidOperation
from itertools import chain
from types import TracebackType
from typing import Any, Self, cast

import yaml

from _version import __version__
from factories import device_factory, endpoint_factory
from logger.logger import DataEvent, LoggingDevice

DEFAULT_WAIT_TIMEOUT = 10  # in seconds
DEFAULT_RECONNECT_INTERVAL = 5  # in seconds
LOG_LEVEL = logging.INFO
ERROR_LOG_FMT = "%(asctime)s %(name)-12s %(levelname)-8s %(message)s"


class DataGenerator:
    """
    Connects to the logging devices and reads them in a loop.
    """

    def __init__(self, sensors: Sequence[LoggingDevice]) -> None:
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


class LoggingDaemon:  # pylint: disable=too-few-public-methods
    """
    Connects the devices with the endpoints and reconnects them, if the connection is lost.
    """

    def __init__(
        self,
        logging_devices: Sequence[LoggingDevice],
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

        self.__logger = logging.getLogger(__name__)

    async def _read_sensors(self) -> None:
        async with AsyncExitStack() as stack:
            endpoint_queues = await asyncio.gather(
                *[stack.enter_async_context(endpoint) for endpoint in self.__endpoints.values()]
            )

            data_generator: DataGenerator = await stack.enter_async_context(DataGenerator(self.__devices))

            if "file" in self.__endpoints:
                await self.__endpoints["file"].write(await data_generator.get_header())

            async for timestamp, data in data_generator.read_sensors(self.__time_interval):
                for queue in endpoint_queues:
                    queue.put_nowait((timestamp, data))
                self.__logger.info(",".join(map(str, data)))

    async def run(self) -> None:
        """
        Run the logger until it is cancelled or receives SIGHUP, SIGTERM or SIGINT. Connection errors cause a
        reconnect after `reconnect_interval` seconds.
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
                        "Connection error: %s. Reconnecting in %.0f s.",
                        str(exc) or type(exc).__name__,
                        self.__reconnect_interval,
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
    """Log to the console and log errors to the file errors.log."""
    # Report all mistakes managing asynchronous resources.
    warnings.simplefilter("always", ResourceWarning)
    # Enable logs from the ip connection. Set to debug for even more info
    logging.basicConfig(level=LOG_LEVEL)

    # Set up a file logger for errors
    logfile_handler = logging.FileHandler("errors.log")
    logfile_handler.setLevel(level=logging.ERROR)
    logfile_handler.setFormatter(logging.Formatter(fmt=ERROR_LOG_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(logfile_handler)


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
