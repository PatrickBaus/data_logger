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
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from async_gpib import AsyncGpib
from tinkerforge_async import IPConnectionAsync, base58decode
from tinkerforge_async.bricklet_humidity_v2 import BrickletHumidityV2

from devices.async_serial import AsyncSerial
from devices.e_plus_e import EE07
from devices.fluke import Fluke1524
from devices.ilx import LDT5948
from devices.keithley import Keithley2002


@dataclass(frozen=True)
class DataEvent:
    """
    The base class to encapsulate any data event.
    """
    timestamp: float = field(init=False)
    sender: UUID
    sid: int
    topic: str
    value: Any
    unit: str

    def __post_init__(self):
        # A slightly clumsy approach to setting the timestamp property, because this is frozen. Taken from:
        # https://docs.python.org/3/library/dataclasses.html#frozen-instances
        object.__setattr__(self, 'timestamp', datetime.now(timezone.utc))

    def __str__(self):
        return str(self.value)


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

    @property
    def uuid(self) -> UUID:
        return self.__uuid

    @property
    def base_topic(self) -> str:
        return self.__base_topic

    def __init__(
            self,
            device,
            uuid: UUID,
            device_name: str | None = None,
            column_names=None,
            initial_commands=None,
            post_read_commands=None,
            base_topic: str = None
    ) -> None:
        self.__device = device
        self.__uuid = uuid
        self.__device_name = device_name
        self.__column_names = ["", ] if column_names is None else column_names
        self.__initial_commands = [] if initial_commands is None else initial_commands
        self.__post_read_commands = [] if post_read_commands is None else post_read_commands
        self.__base_topic = base_topic
        self.__logger = logging.getLogger(__name__)

    @staticmethod
    async def __batch_run(coros, timeout=1):
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

        return (DataEvent(sender=self.uuid, sid=0, topic=self.base_topic, value=data, unit=''),)


class HP3458ALogger(GenericLogger):
    async def get_log_header(self):
        cal_const71 = await self.device.get_acal1v()
        cal_const72 = await self.device.get_acal10v()
        cal_7v = await self.device.get_cal7v()
        cal_40k = await self.device.get_cal40k()
        temperature_acal_dcv = await self.device.get_temperature_acal_dcv()

        return (f"HP3458A ACAL constants CAL71="
            f"{cal_const71}, CAL72={cal_const72}, TEMP={temperature_acal_dcv},"
            f"7Vref={cal_7v}, 40kref={cal_40k}"
        )


class Keysight34470ALogger(GenericLogger):
    async def get_log_header(self):
        temperature_acal_ks4770a = await self.device.get_acalTemperature()

        return f"# KS34470A ACAL TEMP={temperature_acal_ks4770a}"


class LDT5948Logger(LoggingDevice):
    @classmethod
    @property
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "ldt5948"

    def __init__(self, tty: str, timeout: int, baudrate: int, *args, **kwargs):
        connection = AsyncSerial(tty=tty, timeout=timeout, baudrate=baudrate)
        device = LDT5948(connection)
        super().__init__(device=device, *args, **kwargs)

    async def get_log_header(self):
        kp, ki, kd = await self.device.get_pid_constants()  # pylint: disable=invalid-name

        return f"LDT5948 PID constants Kp={kp:.2f}, Ki={ki:.3f}, Kd={kd:.3f}"

    async def read(self):
        await super().read()
        setpoint: Decimal
        temperature, current, voltage, setpoint = await asyncio.gather(
            self.device.read_temperature(),
            self.device.read_current(),
            self.device.read_voltage(),
            self.device.get_temperature_setpoint()
        )
        setpoint = setpoint.quantize(Decimal("1.000"))

        return (
            DataEvent(sender=self.uuid, sid=0, topic=self.base_topic + "/temperature", value=temperature, unit='°C'),
            DataEvent(sender=self.uuid, sid=1, topic=self.base_topic + "/tec_current", value=current, unit='A'),
            DataEvent(sender=self.uuid, sid=1, topic=self.base_topic + "/tec_voltage", value=voltage, unit='V'),
            DataEvent(sender=self.uuid, sid=1, topic=self.base_topic + "/setpoint", value=setpoint, unit='°C')
        )


class Keithley2002Logger(LoggingDevice):
    @classmethod
    @property
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "k2002"

    def __init__(self, name: int | str, pad: int, timeout, *args, **kwargs):
        gpib_device = AsyncGpib(name=name, pad=pad, timeout=timeout)
        device = Keithley2002(connection=gpib_device)

        super().__init__(device=device, *args, **kwargs)

    async def query_channel(self, channel):
        await self.device.write(f":rout:clos (@{channel+1})")
        data = await self.device.query("FETCH?", length=8)
        data = struct.unpack('d', data)[0]      # The result of unpack is always a tuple
        return DataEvent(sender=self.uuid, sid=channel, topic=self.base_topic + f"/channel{channel}", value=data, unit='V')

    async def read(self):
        await super().read()
        data = await self.device.query("FETCH?", length=8)  # get an 8 byte double from the instrument
        data, = struct.unpack('d', data)
        return (DataEvent(sender=self.uuid, sid=0, topic=self.base_topic, value=data, unit=''),)


class Keithley2002ScannerLogger(Keithley2002Logger):
    @classmethod
    @property
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "k2002_scanner"

    def __init__(
            self,
            active_channels: tuple[int],
            *args,
            **kwargs
    ) -> None:
        super().__init__(column_names=[f"K2002 CH{channel+1}" for channel in active_channels], *args, **kwargs)
        self.__active_channels = active_channels

    async def read(self):
        return [await self.query_channel(channel) for channel in self.__active_channels]


class TinkerforgeLogger(LoggingDevice):
    @classmethod
    @property
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "tinkerforge"

    def __init__(self, host: str, uid: int | str, *args, **kwargs):
        ipcon = IPConnectionAsync(host=host)
        if isinstance(uid, int):
            device = BrickletHumidityV2(uid, ipcon)
        else:
            device = BrickletHumidityV2(base58decode(uid), ipcon)
        super().__init__(device=device, *args, **kwargs)


    # TODO: Rework TF api to be more general
    async def read(self):
        await super().read()
        try:
            value = await self.device.get_humidity()
        except ConnectionError as exc:
            try:
                await self.device.connect()
            except Exception:
                logging.getLogger(__name__).exception(
                    "Error during re-connect attempt to Tinkerforge Brick daemon."
                )
            raise asyncio.TimeoutError(
                "Connection to Tinkerforge bricklet timed out. Reconnecting."
            ) from exc
        return (DataEvent(sender=self.uuid, sid=0, topic=self.base_topic, value=value, unit='%rH'),)

    async def get_id(self):
        return await self.device.get_identity()


class Fluke1524Logger(LoggingDevice):
    @classmethod
    @property
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "fluke1524"

    def __init__(self, tty: str, timeout: int, baudrate: int, *args, **kwargs):
        connection = AsyncSerial(tty=tty, timeout=timeout, baudrate=baudrate)
        device = Fluke1524(connection)
        super().__init__(device=device, *args, **kwargs)

    # TODO: Rework API
    async def read(self):
        await super().read()
        temperature1, temperature2 = await asyncio.gather(
            self.device.read_sensor1(),
            self.device.read_sensor2()
        )
        return (
            DataEvent(sender=self.uuid, sid=0, topic=self.base_topic, value=temperature1, unit='°C'),
            DataEvent(sender=self.uuid, sid=1, topic=self.base_topic, value=temperature2, unit='°C'),
        )


class EE07Logger(LoggingDevice):
    @classmethod
    @property
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "ee07"

    def __init__(self, tty: str, timeout: int, baudrate: int, *args, **kwargs):
        connection = AsyncSerial(tty=tty, timeout=timeout, baudrate=baudrate)
        device = EE07(connection)
        super().__init__(device=device, *args, **kwargs)

    async def read(self):
        await super().read()
        humidity = await self.device.read_sensor1()
        temperature = await self.device.read_sensor2()
        return (
            DataEvent(sender=self.uuid, sid=0, topic=self.base_topic, value=humidity, unit='%rH'),
            DataEvent(sender=self.uuid, sid=1, topic=self.base_topic, value=temperature, unit='°C'),
        )

class WavemasterLogger(LoggingDevice):
    async def read(self):
        await super().read()
        wavelength = await self.device.read_wavelength()
        return (DataEvent(sender=self.uuid, sid=0, topic=self.base_topic, value=wavelength, unit='nm'),)
