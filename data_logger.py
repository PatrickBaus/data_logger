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
from collections import deque
from datetime import datetime, timezone
from itertools import chain
import logging
import signal
import struct
import warnings

import aiofiles
import async_timeout
import numpy as np
from tinkerforge_async.ip_connection import IPConnectionAsync, NotConnectedError
from tinkerforge_async.ip_connection_helper import base58decode
from tinkerforge_async.bricklet_humidity_v2 import BrickletHumidityV2 as BrickletHumidity
# Devices
from async_gpib.async_gpib import AsyncGpib
from devices.async_serial import AsyncSerial
from devices.async_ethernet import AsyncEthernet
from devices.keithley import KeithleyDMM6500, Keithley2002
from devices.keysight import Hp3458A, Keysight34470A
from devices.fluke import Fluke1524
from devices.e_plus_e import EE07
from devices.ilx import LdtMode, LDT5948

from _version import __version__

DEFAULT_WAIT_TIMEOUT = 10 # in seconds
LOG_LEVEL = logging.INFO

class LoggingDevice():
    @property
    def column_names(self):
        """
        Returns a list/tuple of column names. The
        number of elements is the same as returned
        by the read() command.
        """
        return self.__column_names

    @property
    def device(self):
        return self.__device

    def __init__(self, device, device_name=None, column_names=None, initial_commands=None,
                 post_read_commands=None):
        self.__device = device
        self.__device_name = device_name
        self.__column_names = ["",] if column_names is None else column_names
        self.__initial_commands = [] if initial_commands is None else initial_commands
        self.__post_read_commands = [] if post_read_commands is None else post_read_commands
        self.__logger = logging.getLogger(__name__)

    async def __batch_run(self, coros, timeout=1):
        """
        Execute coros in order with a timeout
        """
        for coro in coros:
            with async_timeout.timeout(timeout):
                await coro

    async def connect(self):
        await self.__device.connect()

    async def disconnect(self):
        await self.__device.disconnect()

    async def get_id(self):
        return await self.__device.get_id()

    async def initialize(self):
        device_id = await self.get_id()
        self.__logger.info("Initializing %s", device_id)
        if self.__device_name is None:
            self.__device_name = device_id
        await self.__batch_run([self.__device.write(cmd) for cmd in self.__initial_commands])

    async def get_log_header(self):
        return ""

    async def read(self):
        """
        Must be implemented to return a list/tuple of strings to be inserted into the log
        """
        self.__logger.debug("Reading %s...", self.__device_name)

    async def post_read(self):
        await self.__batch_run([self.__device.write(cmd) for cmd in self.__post_read_commands])


class GenericLogger(LoggingDevice):
    async def read(self):
        await super().read()
        data = await self.device.read()
        return (str(data), )


class HP3458ALogger(GenericLogger):
    async def get_log_header(self):
        cal_const71 = await self.device.get_acal1V()
        cal_const72 = await self.device.get_acal10V()
        cal_7v = await self.device.get_cal7V()
        cal_40k = await self.device.get_cal40k()
        temperature_acal_dcv = await self.device.get_temperature_acal_dcv()

        return (f"HP3458A ACAL constants CAL71="
            f"{cal_const71}, CAL72={cal_const72}, TEMP={temperature_acal_dcv},"\
            f"7Vref={cal_7v}, 40kref={cal_40k}"
        )


class Keysight34470ALogger(GenericLogger):
    async def get_log_header(self):
        temperature_acal_ks4770a = await self.device.get_acalTemperature()

        return f"# KS34470A ACAL TEMP={temperature_acal_ks4770a}"


class LDT5948Logger(LoggingDevice):
    async def get_log_header(self):
        kp, ki, kd = await self.device.get_pid_constants()  # pylint: disable=invalid-name

        return f"LDT5948 PID constants Kp={kp:.2f}, Ki={ki:.3f}, Kd={kd:.3f}"

    async def read(self):
        await super().read()
        temperature, current, voltage, setpoint = await asyncio.gather(
            self.device.read_temperature(),
            self.device.read_current(),
            self.device.read_voltage(),
            self.device.get_temperature_setpoint()
        )
        return str(temperature), str(current), str(voltage), f"{setpoint:.3f}"


class Keithley2002Logger(LoggingDevice):
    async def read(self):
        await super().read()
        data = await self.device.query("FETCH?", len=8)  # get an 8 byte double from the instrument
        data, = struct.unpack('d', data)
        return (str(data), )


class TinkerforgeLogger(LoggingDevice):
    # TODO: Rework TF api to be more general
    async def read(self):
        await super().read()
        try:
            value = await self.device.get_humidity()
        except NotConnectedError as exc:
            try:
                await self.device.connect()
            except Exception:
                self.__logger.exception(
                    "Error during re-connect attempt to Tinkerforge Brick daemon."
                )
            raise asyncio.TimeoutError(
                "Connection to Tinkerforge bricklet timed out. Reconnecting."
            ) from exc
        return (str(value), )

    async def get_id(self):
        return await self.device.get_identity()

class Fluke1524Logger(LoggingDevice):
    # TODO: Rework API
    async def read(self):
        await super().read()
        temperature1, temperature2 = await asyncio.gather(
            self.device.read_sensor1(),
            self.device.read_sensor2()
        )
        return str(temperature1), str(temperature2)


class EE07Logger(LoggingDevice):
    async def read(self):
        await super().read()
        humidity = await self.device.read_sensor1()
        temperature = await self.device.read_sensor2()
        return str(humidity), str(temperature)

class LoggingDaemon():
    @property
    def timeout(self):
        """
        Returns the timeout for async operations in seconds
        """
        return self.__timeout

    @timeout.setter
    def timeout(self, value):
        self.__timeout = abs(int(value))

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
        self.__logger.debug('Initializing Logging daemon')

        # Connect to all loggers
        coros = [device.connect() for device in self.__devices.values()]
        await asyncio.gather(*coros)

        self.__logger.info("Initializing devices")
        coros = [device.initialize() for device in self.__devices.values()]
        await asyncio.gather(*coros)

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
        # Get all running tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        # and stop them
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

        self.__logger.debug("Disconnecting devices.")
        coros = [device.disconnect() for device in self.__devices.values()]
        try:
            await asyncio.gather(*coros)
        except asyncio.CancelledError:
            pass

        if self.__filehandle is not None:
            self.__logger.debug("Closing open file handles.")
            await self.__filehandle.close()
            self.__logger.info("File '%s' closed.", self.__filename)

    async def __read_packet(self, time_interval):
        try:
            with async_timeout.timeout(self.timeout):
                coros = [device.read() for device in self.__devices.values()]
                # Wait for the slowest device or at least {time_interval}
                coros.append(asyncio.sleep(time_interval))
                # strip the result of asyncio.sleep()
                results = (await asyncio.gather(*coros, return_exceptions=True))[:-1]
                done = True
                for result in results:
                    if isinstance(result, Exception):
                        self.__logger.error(result)
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

    @staticmethod
    def __generate_triangle_queue(start, stop, stepsize, time_step, soak_time=None,
                                  starting_point=None):
        n_steps= int(abs(stop-start)/stepsize)
        if soak_time is None:
            soak_time = time_step

        direction = 1 if start < stop else -1
        temp_steps = [start + x*stepsize for x in chain(range(0,direction*n_steps,direction),
                                                        range(direction*n_steps,0,direction*-1))]
        time_steps = [soak_time,] + (n_steps-1) * [time_step,] + [soak_time,] + (n_steps-1) * [time_step,]
        ramp = deque(zip(time_steps, temp_steps))
        if starting_point is not None:
            # locate the current starting point assuming it is a monotonic ramp
            temp_steps = np.asarray(temp_steps)
            index = (np.abs(temp_steps - starting_point)).argmin()
            ramp.rotate(-index)
        return ramp

    async def __main_loop(self):
        start_time = datetime.utcnow()
        ldt_5948 = None if self.__devices.get("LDT5948") is None else self.__devices.get("LDT5948").device
        #await ldt_5948.set_temperature_setpoint(23)
        temperature_setpoint = None if ldt_5948 is None else float(await ldt_5948.get_temperature_setpoint())

        # Generate a ramp
        start_temp, stop_temp = 50, 20
        soak_time = 60*60*4    # allow 4 h soak time at the corners
        temperature_ramp = None if ldt_5948 is None else self.__generate_triangle_queue(start_temp,
            stop_temp, stepsize=0.25, time_step=450, soak_time=soak_time,
            starting_point=temperature_setpoint
        )
        #temperature_ramp = None    # set to None to disable the ramp

        if temperature_ramp is not None:
            if not (await ldt_5948.get_mode()) == LdtMode.T:
                await ldt_5948.set_mode(LdtMode.T)
            await ldt_5948.set_temperature_setpoint(temperature_ramp[0][1])    # seed the ramp
            temperature_setpoint = float(await ldt_5948.get_temperature_setpoint())
            temperature_ramp.rotate(-1)
            self.__logger.info("Starting temperature cycle at: %.3f °C", temperature_setpoint)

            if not await ldt_5948.is_enabled():
                await ldt_5948.set_enabled(True)

        try:
            while 'loop not canceled':
                # Read packets and process them.
                try:
                    timestamp, data = await self.__read_packet(self.__time_interval)
                    if data is not None:
                        self.__logger.info(data)
                        await self.__write_data_to_file(timestamp=timestamp, data=data)
                        await self.__post_read(timestamp=timestamp, data=data)

                        if temperature_ramp is not None and (timestamp-start_time).total_seconds() >= temperature_ramp[-1][0]:
                            current_temperature = float(await self.__devices["LDT5948"].device.read_temperature())
                            temperature_setpoint = float(await self.__devices["LDT5948"].device.get_temperature_setpoint())

                            if abs(current_temperature - temperature_setpoint) <= 0.1:
                                self.__logger.info("Setting temperature to: %.3f °C", temperature_ramp[0][1])
                                await self.__devices["LDT5948"].device.set_temperature_setpoint(temperature_ramp[0][1])
                                temperature_ramp.rotate(-1)
                                start_time = timestamp
                            else:
                                self.__logger.warning((
                                    "Temperature has not settled yet. Delaying next step."
                                    "Temperature setpoint: %.3f °C, current temperature: %.3f °C,"
                                    "Required delta: 100 mK."),
                                    temperature_setpoint, current_temperature
                                )
                except ValueError as exc:
                    self.__logger.error(exc)

        except asyncio.CancelledError:
            self.__logger.info('DgTemp daemon serial connection closed')
        except Exception as exc:
            self.__logger.exception("Error while running main_loop")

    async def run(self):
        # Catch signals and shutdown
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        #signals = (signal.SIGHUP, signal.SIGINT)
        for sig in signals:
            asyncio.get_running_loop().add_signal_handler(
                sig, lambda: asyncio.create_task(self.shutdown()))

        await self.__init_daemon()
        await self.__main_loop()

# Report all mistakes managing asynchronous resources.
warnings.simplefilter('always', ResourceWarning)
# Enable logs from the ip connection. Set to debug for even more info
logging.basicConfig(level=LOG_LEVEL)

devices = {}    # If using Python < 3.7 use an ordered dict to ensure insertion order
# The output file will have the same column order as the `devices` (ordered) dict

ipcon = IPConnectionAsync(host='10.0.0.5')
bricklet = BrickletHumidity(base58decode("Dm6"), ipcon) # Create tinkerforge sensor device

# 5 second timeout as 10*10 PLC with AZERO takes about 4 seconds
#gpib_device = AsyncGpib(name=0, pad=22, timeout=5*1000)
#hp3458a = Hp3458A(connection=gpib_device)
HP3458A_INIT_COMMANDS = [
    "BEEP",
#    "RESET",
#    "PRESET NORM",
    "OFORMAT ASCII",
#    "END ALWAYS",
    "TRIG AUTO",
    "TARM AUTO",
    "NRDGS 1,AUTO",
    "DCV 10",
#    "RATIO ON",
    "AZERO ON",
    "NDIG 9",
    "NPLC 100",
    "BEEP",
]

# 5 second timeout as 6*10 PLC with AZERO takes about 3.5 seconds
#gpib_device = AsyncGpib(name=0, pad=16, timeout=5*1000)
#k2002 = Keithley2002(connection=gpib_device)
K2002_INIT_COMMANDS = [
    "*RST",
    "*CLS",
    ":SYST:AZER:TYPE SYNC",  # azero to line sync
    ":SYST:LSYN:STAT ON",    # line sync
    ":SENS:FUNC 'VOLT:DC'",
     # Do NPLC 60, because the 2002 is slower than the 3458A by a factor of 1.5
    ":SENS:VOLT:DC:DIG 9;NPLC 10;AVER:COUN 6;TCON REP;STAT ON",
    ":SENS:VOLT:DC:RANG 20",
    ":FORM:DATA REAL,64",
    ":FORM:ELEM READing",    # only return the reading, not stuff like the channel or a timestamp
#    ":FORM:EXP HPR",  # Needs FW > A06, possibly A09
    ":INITiate:CONTinuous OFF",    # disable continuous triggering
    ":INIT",
]
K2002_POST_READ_COMMANDS = [
    ":ABORt",
    ":INIT",
]

#dmm6500 = KeithleyDMM6500(AsyncEthernet(host='192.168.1.232', port=5025))
# TODO: Add line sync and filter
DMM6500_INIT_COMMANDS = [
    "SYSTEM:BEEP 1000,0.1",
#    "*RST",
    "SENS:FUNC 'TEMP'",
    "SENS:TEMP:TRAN THER",
    "SENS:TEMP:THER 10000",
    "SENS:TEMP:NPLC 10",
    "DISP:TEMP:DIG 6",
    "SENS:TEMP:LINE:SYNC ON",
]

#ks34470a = Keysight34470A(AsyncEthernet(host="192.168.1.191", port=5025))
KS34470A_INIT_COMMANDS = [
    "SYSTEM:BEEP",
#    "SYSTEM:PRESET",
#    "CONF:CURRENT:DC",
#    "SENSE:CURRENT:RANGE 1",
#    "SENSE:CURRENT:ZERO:AUTO ON",
#    "SENSE:CURRENT:NPLC 100",
    "CONF:VOLTAGE:DC",
    "SENSE:VOLTAGE:RANGE 1",
    "SENSE:VOLTAGE:ZERO:AUTO ON",
    "SENSE:VOLTAGE:NPLC 10",
    "SENSE:VOLTAGE:IMPEDANCE:AUTO ON",
]

fluke1524 = Fluke1524(AsyncSerial("/dev/ttyUSB1", timeout=0.5, baudrate=9600))
#ee07 = EE07(AsyncSerial("/dev/ttyACM0", timeout=0.5, baudrate=115200))
#ldt5948 = LDT5948(AsyncSerial("/dev/ttyUSB0", timeout=0.5, baudrate=115200))

#devices["KS34470A"] = Keysight_34470A_Logger(ks34470a, device_name="KS34470A", column_names=["Value KS34470A",], initial_commands=KS34470A_INIT_COMMANDS)
#devices["HP3458A"] = HP_3458A_Logger(hp3458a, device_name="3458A", column_names=["Value HP3458A",], initial_commands=HP3458A_INIT_COMMANDS)
#devices["Fluke1524"] = Fluke_1524_Logger(fluke1524, device_name="temperature",column_names=["Temperature 10k Thermistor", "Temperature PT100"])
devices["humidity_bricklet"] = TinkerforgeLogger(bricklet, device_name="humidity", column_names=["Humidity (Ambient)",])
#devices["EE07"] = EE07_Logger(ee07, device_name="EE07 humidity probe", column_names=["Humidity (DUT)", "Temperature humidity sensor (DUT)"])
#devices["DMM6500"] = GenericLogger(dmm6500, device_name="DMM6500", column_names=["Value DMM6500",], initial_commands=DMM6500_INIT_COMMANDS)
#devices["K2002"] = Keithley_2002_Logger(k2002, device_name="K2002", column_names=["Value K2002",], initial_commands=K2002_INIT_COMMANDS, post_read_commands=K2002_POST_READ_COMMANDS)
#devices["LDT5948"] = LDT_5948_Logger(ldt5948, device_name="ILX temperature controller", column_names=["Temperature in loop", "TEC current", "TEC voltage", "Temperature setpoint"])

try:
    logging_daemon = LoggingDaemon(
        filename="LM399_Tempco_{date}.csv",    # {date} will later be replaced by the current date in isoformat
        description=(
        "This file contains voltage measurements accross a 100 Ω shunt resistor driven by the"
        " digital current driver."
        ), logging_devices=devices, time_interval=1
    )

    asyncio.run(logging_daemon.run(), debug=False)
except KeyboardInterrupt:
    # The loop will be canceled on a KeyboardInterrupt by the run() method, we
    # just want to suppress the exception
    pass
