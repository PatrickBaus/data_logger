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

import asyncio
import logging
import signal
import warnings
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from itertools import chain
from types import TracebackType
from typing import List, Type
import yaml

from factories import endpoint_factory
from factories.device_factory import device_factory

try:
    from typing import Self  # Python >=3.11
except ImportError:
    from typing_extensions import Self

# Devices
from devices.async_serial import AsyncSerial
from devices.coherent import Wavemaster

DEFAULT_WAIT_TIMEOUT = 10  # in seconds
LOG_LEVEL = logging.INFO


class DataGenerator:
    def __init__(self, sensors):
        self.__sensors = sensors
        self.__logger = logging.getLogger(__name__)

    async def __aenter__(self) -> Self:
        self.__logger.info("Initializing devices")
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
            exc_type: Type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None
    ) -> None:
        self.__logger.debug("Disconnecting devices.")
        coros = [device.disconnect() for device in self.__sensors]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                self.__logger.error("Error during shutdown of the data generator.", exc_info=result)

    async def get_header(self) -> List[str]:
        self.__logger.debug("Creating file header")
        # create info header
        coros = [device.get_log_header() for device in self.__sensors]
        headers = await asyncio.gather(*coros)
        result = [f"# {header}\n" for header in headers if header]
        # drop the microseconds
        date = datetime.utcnow().replace(tzinfo=timezone.utc).replace(microsecond=0)
        result.append(f"# Log started at UTC: {date.isoformat()}\n")

        # create column names
        column_names = chain(["Date", ], *[device.column_names for device in self.__sensors])
        result.append(f"# {','.join(column_names)}\n")
        return result

    async def read_sensors(self, time_interval):
        self.__logger.info("Reading data from devices")
        while "not canceled":
            try:
                coros = [device.read() for device in self.__sensors]
                # Wait for the slowest device or at least {time_interval}
                coros.append(asyncio.sleep(time_interval))
                results = (await asyncio.gather(*coros, return_exceptions=True))[:-1]
                results = tuple(results)
                done = True
                for result in results:
                    if isinstance(result, Exception):
                        self.__logger.error("Error during read.", exc_info=result)
                        done = False
                if done:  # pylint: disable=no-else-return
                    yield datetime.utcnow(), tuple(sum(results, ()))

                # Run post-read
                coros = [device.post_read() for device in self.__sensors]
                await asyncio.gather(*coros)
            except asyncio.TimeoutError:
                self.__logger.error("Timeout during read. Retrying.")
            except Exception:
                self.__logger.exception("Error during read.")

class LoggingDaemon:
    def __init__(self, filename, description, logging_devices, endpoints, time_interval=0):
        self.__devices = logging_devices
        self.__endpoints = {endpoint: endpoint_factory.get(driver=endpoint, **endpoints[endpoint]) for endpoint in endpoints}
        self.__file_description = description
        self.__time_interval = time_interval

        self.__timeout = self.__time_interval + DEFAULT_WAIT_TIMEOUT

        self.__logger = logging.getLogger(__name__)

        # drop the microseconds
        date = datetime.utcnow().replace(tzinfo=timezone.utc).replace(microsecond=0)
        self.__filename = filename.format(date=date.isoformat("_"))
        self.__filehandle = None

    async def __init_daemon(self):
        async with AsyncExitStack() as stack:
            endpoint_queues = await asyncio.gather(
                *[stack.enter_async_context(endpoint) for endpoint in self.__endpoints.values()]
            )

            data_generator: DataGenerator = await stack.enter_async_context(DataGenerator(self.__devices))

            if "file" in self.__endpoints:
                await asyncio.gather(
                    *[self.__endpoints['file'].write(line for line in await data_generator.get_header())]
                )

            async for timestamp, data in data_generator.read_sensors(self.__time_interval):
                for queue in endpoint_queues:
                    queue.put_nowait((timestamp, data))
                self.__logger.info(','.join(map(str, data)))


    async def run(self):
        # Catch signals and shutdown
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        main_task = asyncio.create_task(self.__init_daemon())
        for sig in signals:
            asyncio.get_running_loop().add_signal_handler(
                sig, lambda: main_task.cancel())
        try:
            await main_task
        except asyncio.CancelledError:
            self.__logger.info('Logging daemon shut down.')


# Report all mistakes managing asynchronous resources.
warnings.simplefilter('always', ResourceWarning)
# Enable logs from the ip connection. Set to debug for even more info
logging.basicConfig(level=LOG_LEVEL)

devices = {}    # If using Python < 3.7 use an ordered dict to ensure insertion order
# The output file will have the same column order as the `devices` (ordered) dict

serial_device = AsyncSerial(tty="/dev/ttyUSB5", timeout=2)
wavemaster = Wavemaster(connection=serial_device)

WAVEMASTER_INIT_COMMANDS = [
    "PRD 1",    # 1 second interval
]
#devices["wavemaster"] = WavemasterLogger(
#    wavemaster, device_name="Wavemaster", column_names=["Wavelength", ], initial_commands=WAVEMASTER_INIT_COMMANDS
#)

#ipcon = IPConnectionAsync(host='192.168.1.164')
#ipcon = IPConnectionAsync(host='10.0.0.5')
#bricklet = BrickletHumidityV2(base58decode("PTk"), ipcon) # Create tinkerforge sensor device
#devices["humidity_bricklet"] = TinkerforgeLogger(
#    bricklet, uuid=UUID('772ca54f-f1f1-48c3-bf6e-104ae64c1c2d'), device_name="humidity", column_names=["Humidity (TF)",]
#)

try:
    with open('config.yml', 'r') as file:
        measurement_config = yaml.safe_load(file)

    devices = [device_factory.get(**device_config) for device_config in measurement_config.get('devices', [])]

    logging_daemon = LoggingDaemon(
        endpoints=measurement_config['endpoints'],
        filename="data/wavelength_{date}.csv",    # {date} will later be replaced by the current date in iso format
        description=(
            "This file contains Wavelength measurements of a Coherent Wavemaster wavemeter"
        ), logging_devices=devices, time_interval=1
    )

    asyncio.run(logging_daemon.run(), debug=False)
except KeyboardInterrupt:
    # The loop will be canceled on a KeyboardInterrupt by the run() method, we
    # just want to suppress the exception
    pass
