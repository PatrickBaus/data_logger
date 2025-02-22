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
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import warnings
from collections.abc import AsyncIterator, Awaitable
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from itertools import chain
from types import TracebackType
from typing import Self, cast

import yaml

from _version import __version__
from factories import device_factory, endpoint_factory
from logger.logger import DataEvent

DEFAULT_WAIT_TIMEOUT = 10  # in seconds
LOG_LEVEL = logging.INFO
ERROR_LOG_FMT = "%(asctime)s %(name)-12s %(levelname)-8s %(message)s"


class DataGenerator:
    def __init__(self, sensors):
        self.__sensors = sensors
        self.__logger = logging.getLogger(__name__)

    async def __aenter__(self) -> Self:
        self.__logger.info("Initializing devices")
        self.__logger.debug("Devices to initialize: %s.", devices)
        # Connect to all devices
        coros = [device.connect() for device in self.__sensors]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result

        self.__logger.info("Devices initialized successfully.")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.__logger.debug("Disconnecting devices.")
        coros = [device.disconnect() for device in self.__sensors]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                self.__logger.error("Error during shutdown of the data generator.", exc_info=result)

    async def get_header(self) -> list[str]:
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

    async def read_sensors(self, time_interval) -> AsyncIterator[tuple[datetime, tuple[DataEvent, ...]]]:
        self.__logger.info("Reading data from devices")
        while "not canceled":
            try:
                coros: list[Awaitable[tuple[DataEvent] | None]]
                coros = [device.read() for device in self.__sensors]
                # Wait for the slowest device or at least {time_interval}
                coros.append(asyncio.sleep(time_interval))
                #  Strip the None result from sleep() at the end
                results = tuple((await asyncio.gather(*coros, return_exceptions=True))[:-1])
                done = True
                for result in results:
                    # We will raise the first error later.
                    if isinstance(result, BaseException):
                        done = False
                    if isinstance(result, Exception):
                        # Log all exceptions (except Timeouts, we will log it and retry later).
                        if not isinstance(result, TimeoutError):
                            self.__logger.error("Error during read.", exc_info=result)
                if done:  # pylint: disable=no-else-return
                    results = cast(tuple[tuple[DataEvent], ...], results)  # done is false if there are BaseExceptions
                    yield datetime.now(timezone.utc), tuple(sum(results, ()))  # flatten the tuple of tuples
                else:
                    # raise the first exception
                    for result in results:
                        if isinstance(result, Exception):
                            raise result

                # Run post-read
                coros = [device.post_read() for device in self.__sensors]
                await asyncio.gather(*coros)
            except ValueError:
                self.__logger.error("Sensor read invalid data. Retrying.")
            except asyncio.TimeoutError:
                self.__logger.error("Timeout during read. Retrying.")


class LoggingDaemon:
    def __init__(self, logging_devices, endpoints, time_interval=0):
        self.__devices = logging_devices
        self.__endpoints = {
            endpoint: endpoint_factory.get(driver=endpoint, **endpoints[endpoint]) for endpoint in endpoints
        }
        self.__time_interval = time_interval

        self.__logger = logging.getLogger(__name__)

    async def _read_sensors(self):
        async with AsyncExitStack() as stack:
            endpoint_queues = await asyncio.gather(
                *[stack.enter_async_context(endpoint) for endpoint in self.__endpoints.values()]
            )

            data_generator: DataGenerator = await stack.enter_async_context(DataGenerator(self.__devices))

            if "file" in self.__endpoints:
                await asyncio.gather(
                    *[self.__endpoints["file"].write(line for line in await data_generator.get_header())]
                )

            async for timestamp, data in data_generator.read_sensors(self.__time_interval):
                for queue in endpoint_queues:
                    queue.put_nowait((timestamp, data))
                self.__logger.info(",".join(map(str, data)))

    async def run(self):
        # Catch signals and shutdown
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        while "not cancelled":
            main_task = asyncio.create_task(self._read_sensors())
            for sig in signals:
                asyncio.get_running_loop().add_signal_handler(sig, main_task.cancel)
            try:
                await main_task
            except ConnectionError as exc:
                self.__logger.error("Connection error: %s. Reconnecting", exc)
            except asyncio.CancelledError:
                self.__logger.info("Logging daemon shut down.")
                raise
            finally:
                for sig in signals:
                    asyncio.get_running_loop().remove_signal_handler(sig)


def init_argparse() -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(
        usage="%(prog)s [-c config_file]",
        description="Read sensors and push the data to an MQTT server.",
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


# Report all mistakes managing asynchronous resources.
warnings.simplefilter("always", ResourceWarning)
# Enable logs from the ip connection. Set to debug for even more info
logging.basicConfig(level=LOG_LEVEL)

# Set up a file logger for errors
logfile_handler = logging.FileHandler("errors.log")
logfile_handler.setLevel(level=logging.ERROR)
logfile_handler.setFormatter(logging.Formatter(fmt=ERROR_LOG_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
logging.getLogger().addHandler(logfile_handler)

try:
    parser = init_argparse()
    args = parser.parse_args()

    try:
        with open(args.config_file, "r", encoding="utf-8") as file:
            measurement_config = yaml.safe_load(file)
    except FileNotFoundError:
        logging.getLogger(__name__).error("Config file not found")
        parser.print_help()
        sys.exit(1)

    devices = [device_factory.get(**device_config) for device_config in measurement_config.get("devices", [])]

    logging_daemon = LoggingDaemon(
        endpoints=measurement_config["endpoints"],
        logging_devices=devices,
        time_interval=0,
    )

    asyncio.run(logging_daemon.run(), debug=False)
except KeyboardInterrupt:
    # The loop will be canceled on a KeyboardInterrupt by the run() method, we
    # just want to suppress the exception
    pass
except asyncio.CancelledError:
    # The program will terminate now, so we swallow the error to supress
    # the error message
    pass
finally:
    logging.getLogger(__name__).info("Datalogger terminated. Have fun analyzing the data.")
