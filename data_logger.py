#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

import asyncio
from datetime import datetime, timezone
from itertools import chain
import logging
import signal
import warnings

import aiofiles
from async_timeout import timeout
# Devices
from devices.async_serial import AsyncSerial
from devices.coherent import Wavemaster
from logger.logger import WavemasterLogger

from _version import __version__

DEFAULT_WAIT_TIMEOUT = 10 # in seconds
LOG_LEVEL = logging.INFO

class LoggingDaemon():
    def __init__(self, filename, description, logging_devices, time_interval=0):
        self.__devices = logging_devices
        self.__file_description = description
        self.__time_interval = time_interval

        self.__timeout = self.__time_interval + DEFAULT_WAIT_TIMEOUT

        self.__logger = logging.getLogger(__name__)

        # drop the microseconds
        date = datetime.utcnow().replace(tzinfo=timezone.utc).replace(microsecond=0)
        self.__filename = filename.format(date=date.isoformat("_"))
        self.__filehandle = None

    async def __init_daemon(self):
        self.__logger.debug('Initializing Logging daemon.')

        # Connect to all loggers
        coros = [device.connect() for device in self.__devices.values()]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result

        self.__logger.info("Initializing devices")
        coros = [device.initialize() for device in self.__devices.values()]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result

        # Open file, buffering=1 means line buffering
        self.__filehandle = await aiofiles.open(self.__filename, mode='a+', buffering=1)
        self.__logger.info("File '%s' opened.", self.__filename)

        # Write header
        await self.__filehandle.write(("# This file was generated using the Python data logger"
            f" script v{__version__}.\n"
            "# Check https://github.com/PatrickBaus/data_logger for the latest version.\n"
        ))
        await self.__filehandle.write(f"# {self.__file_description}\n")
        coros = [device.get_log_header() for device in self.__devices.values()]
        file_headers = await asyncio.gather(*coros)
        await self.__filehandle.writelines(
            [f"# {file_header}\n" for file_header in file_headers if file_header]
        )

        # drop the microseconds
        date = datetime.utcnow().replace(tzinfo=timezone.utc).replace(microsecond=0)
        await self.__filehandle.write(f"# Log started at UTC: {date.isoformat()}\n")

        # Write column names
        column_names = list(
            chain(["Date",],*[device.column_names for device in self.__devices.values()])
        )
        await self.__filehandle.write(f"# {','.join(column_names)}\n")

    async def shutdown(self):
        self.__logger.debug("Disconnecting devices.")
        coros = [device.disconnect() for device in self.__devices.values()]
        await asyncio.gather(*coros)

        # Get all remaining running tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        # and stop them
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

        if self.__filehandle is not None:
            self.__logger.debug("Closing open file handles.")
            await self.__filehandle.close()
            self.__logger.info("File '%s' closed.", self.__filename)

    async def __read_packet(self, time_interval):
        try:
            async with timeout(self.__timeout):
                coros = [device.read() for device in self.__devices.values()]
                # Wait for the slowest device or at least {time_interval}
                coros.append(asyncio.sleep(time_interval))
                # strip the result of asyncio.sleep()
                results = (await asyncio.gather(*coros, return_exceptions=True))[:-1]
                done = True
                for result in results:
                    if isinstance(result, Exception):
                        self.__logger.error(result, exc_info=result)
                        done = False
                if done:    # pylint: disable=no-else-return
                    return (datetime.utcnow(), tuple(sum(results, ())))
                else:
                    return None, None
        except Exception:
            self.__logger.exception("Error during read.")
            return None, None

    async def __write_data_to_file(self, timestamp, data):
        await self.__filehandle.write(f"{timestamp},{','.join(data)}\n")

    async def __post_read(self, timestamp, data):   # pylint: disable=unused-argument
        # TODO: Hand timestamp and data to other devices
        coros = [device.post_read() for device in self.__devices.values()]
        await asyncio.gather(*coros)

    async def __main_loop(self):
        while 'loop not canceled':
            # Read packets and process them.
            try:
                timestamp, data = await self.__read_packet(self.__time_interval)
                if data is not None:
                    self.__logger.info(data)
                    await self.__write_data_to_file(timestamp=timestamp, data=data)
                    await self.__post_read(timestamp=timestamp, data=data)
            except ValueError as exc:
                self.__logger.exception("Invalid return value during data processing.")
            except Exception:
                self.__logger.exception("Error while running main_loop.")
                break

    async def run(self):
        # Catch signals and shutdown
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        #signals = (signal.SIGHUP, signal.SIGINT)
        for sig in signals:
            asyncio.get_running_loop().add_signal_handler(
                sig, lambda: asyncio.create_task(self.shutdown()))
        try:
            await self.__init_daemon()
            await self.__main_loop()
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
devices["wavemaster"] = WavemasterLogger(wavemaster, device_name="Wavemaster", column_names=["Wavelength",], initial_commands=WAVEMASTER_INIT_COMMANDS)

try:
    logging_daemon = LoggingDaemon(
        filename="data/wavelength_{date}.csv",    # {date} will later be replaced by the current date in isoformat
        description=(
        "This file contains Wavelength measurements of a Coherent Wavemaster wavemeter"
        ), logging_devices=devices, time_interval=1
    )

    asyncio.run(logging_daemon.run(), debug=False)
except KeyboardInterrupt:
    # The loop will be canceled on a KeyboardInterrupt by the run() method, we
    # just want to suppress the exception
    pass
