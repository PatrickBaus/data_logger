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
import logging

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
            await asyncio.wait_for(coro, timeout=timeout)

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
        cal_const71 = await self.device.get_acal1v()
        cal_const72 = await self.device.get_acal10v()
        cal_7v = await self.device.get_cal7v()
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
        data = await self.device.query("FETCH?", length=8)  # get an 8 byte double from the instrument
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

class WavemasterLogger(LoggingDevice):
    async def read(self):
        await super().read()
        wavelength = await self.device.read_wavelength()
        return (str(wavelength), )
