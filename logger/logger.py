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
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from async_gpib import AsyncGpib
from prologix_gpib_async import AsyncPrologixGpibEthernetController
from tinkerforge_async import IPConnectionAsync, base58decode
from tinkerforge_async.bricklet_humidity_v2 import BrickletHumidityV2

from devices import (
    EE07,
    LDT5948,
    AsyncEthernet,
    AsyncSerial,
    Fluke1524,
    Fluke1590,
    Hp3458A,
    Keithley26xxB,
    Keithley2002,
    KeithleyDMM6500,
    Keysight34470A,
)


@dataclass(frozen=True)
class DataEvent:
    """
    The base class to encapsulate any data event.
    """

    sender: UUID
    sid: int
    topic: str
    value: Any
    unit: str
    timestamp: datetime = datetime.now(timezone.utc)

    def __str__(self):
        return str(self.value)


class LoggingDevice:
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
        base_topic: str | None = None,
    ) -> None:
        self.__device = device
        self.__uuid = uuid
        self.__device_name = device_name
        self.__column_names = (
            [
                "",
            ]
            if column_names is None
            else column_names
        )
        self.__initial_commands = [] if initial_commands is None else initial_commands
        self.__post_read_commands = [] if post_read_commands is None else post_read_commands
        self.__base_topic = base_topic if base_topic is not None else ""
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
        self.__logger.debug("Device %s connected", self.__device)
        await self.initialize()

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

    async def read(self) -> tuple[DataEvent, ...]:
        """
        Must be implemented to return a list/tuple of strings to be inserted into the log
        """
        self.__logger.debug("Reading %s...", self.__device_name)
        return ()

    async def post_read(self):
        await self.__batch_run([self.__device.write(cmd) for cmd in self.__post_read_commands])


class GenericLogger(LoggingDevice):
    async def read(self) -> tuple[DataEvent]:
        await super().read()
        data = await self.device.read()

        return (
            DataEvent(
                sender=self.uuid,
                sid=0,
                topic=self.base_topic,
                value=Decimal(data),
                unit="",
            ),
        )


class Keysight3458ALogger(GenericLogger):
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "hp3458a"

    def __init__(self, name: int | str, pad: int, timeout, *args, **kwargs):
        gpib_device = AsyncGpib(name=name, pad=pad, timeout=timeout)
        device = Hp3458A(connection=gpib_device)

        super().__init__(device, *args, **kwargs)

    async def get_log_header(self):
        cal_const71 = await self.device.get_acal1v()
        cal_const72 = await self.device.get_acal10v()
        cal_7v = await self.device.get_cal7v()
        cal_40k = await self.device.get_cal40k()
        temperature_acal_dcv = await self.device.get_temperature_acal_dcv()
        temperature = await self.device.get_temperature()

        return (
            f"HP3458A ACAL constants CAL71="
            f"{cal_const71}; CAL72={cal_const72}; ACAL TEMP={temperature_acal_dcv} °C;"
            f" 7Vref={cal_7v} V; 40kref={cal_40k} Ω; TEMP={temperature} °C"
        )


class Keysight34470ALogger(LoggingDevice):
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "ks34470a"

    def __init__(self, host: str, port: int, timeout, *args, **kwargs):
        connection = AsyncEthernet(host=host, port=port, timeout=timeout)
        device = Keysight34470A(connection=connection)

        super().__init__(device, *args, **kwargs)

    async def get_log_header(self):
        acal_date, acal_temperature = await self.device.get_acal_data()
        cal_date, cal_temperature, _ = await self.device.get_cal_data()
        uptime = await self.device.get_system_uptime()
        return (
            f"KS34470A CAL DATE={cal_date}; TEMP={cal_temperature} °C;"
            f" ACAL DATE={acal_date}; TEMP={acal_temperature} °C;"
            f" Uptime={uptime}"
        )

    async def read(self) -> tuple[DataEvent]:
        await super().read()
        data = await self.device.query("READ?")

        return (
            DataEvent(
                sender=self.uuid,
                sid=0,
                topic=self.base_topic,
                value=Decimal(data),
                unit="",
            ),
        )


class KeithleyDMM6500Logger(LoggingDevice):
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "dmm6500"

    def __init__(self, host: str, port: int, timeout, *args, **kwargs):
        connection = AsyncEthernet(host=host, port=port, timeout=timeout)
        device = KeithleyDMM6500(connection=connection)

        super().__init__(device, *args, **kwargs)

    async def read(self) -> tuple[DataEvent]:
        await super().read()
        data = await self.device.query("READ?")
        # data = await self.device.query("READ?", length=8)
        # data, = struct.unpack('d', data)  # The result of unpack is always a tuple, but we need only the first element
        return (
            DataEvent(
                sender=self.uuid,
                sid=0,
                topic=self.base_topic,
                value=Decimal(data),
                unit="",
            ),
        )


class LDT5948Logger(LoggingDevice):
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "ldt5948"

    def __init__(
        self,
        timeout: int,
        baudrate: int,
        *args,
        tty: str | None = None,
        vid: int | None = None,
        pid: int | None = None,
        serial_number: str | None = None,
        **kwargs,
    ):
        connection = (
            AsyncSerial(vid_pid=(vid, pid), serial_number=serial_number, timeout=timeout, baudrate=baudrate)
            if vid is not None and pid is not None
            else AsyncSerial(tty=tty, timeout=timeout, baudrate=baudrate)
        )
        device = LDT5948(connection)
        super().__init__(device, *args, **kwargs)

    async def get_log_header(self):
        (
            kp,
            ki,
            kd,
        ) = await self.device.get_pid_constants()  # pylint: disable=invalid-name
        uptime = await self.device.query("TIME?")

        return f"LDT5948 {await self.device.get_id()}; PID constants Kp={kp:.2f}; Ki={ki:.3f}; Kd={kd:.3f}; Uptime={uptime}"

    async def read(self) -> tuple[DataEvent, DataEvent, DataEvent, DataEvent]:
        await super().read()
        temperature: Decimal
        current: Decimal
        voltage: Decimal
        setpoint: Decimal
        temperature, current, voltage, setpoint = await asyncio.gather(
            self.device.read_temperature(),
            self.device.read_current(),
            self.device.read_voltage(),
            self.device.get_temperature_setpoint(),
        )
        setpoint = setpoint.quantize(Decimal("1.000"))

        return (
            DataEvent(
                sender=self.uuid,
                sid=0,
                topic=self.base_topic + "/temperature",
                value=temperature,
                unit="°C",
            ),
            DataEvent(
                sender=self.uuid,
                sid=1,
                topic=self.base_topic + "/tec_current",
                value=current,
                unit="A",
            ),
            DataEvent(
                sender=self.uuid,
                sid=2,
                topic=self.base_topic + "/tec_voltage",
                value=voltage,
                unit="V",
            ),
            DataEvent(
                sender=self.uuid,
                sid=3,
                topic=self.base_topic + "/setpoint",
                value=setpoint,
                unit="°C",
            ),
        )


class Keithley2002Logger(LoggingDevice):
    @classmethod
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

        super().__init__(device, *args, **kwargs)

    async def get_log_header(self):
        cal_date, cal_due_date = await self.device.get_cal_data()
        return f"K2002 Cal date={cal_date}; Next Cal due={cal_due_date}"

    async def query_channel(self, channel) -> DataEvent:
        await self.device.write(f":rout:clos (@{channel+1})")
        data = await self.device.query(":DATA:FRESh?", length=8)  # get a *new* 8 byte double from the instrument
        try:
            # The result of unpack is always a tuple, but we need only the first element
            (data,) = struct.unpack("d", data)
        except struct.error as exc:
            raise ValueError(f"Device returned invalid data {data}.") from exc
        return DataEvent(
            sender=self.uuid,
            sid=channel,
            topic=self.base_topic + f"/channel{channel+1}",
            value=data,
            unit="V",
        )

    async def read(self) -> tuple[DataEvent, ...]:
        await super().read()
        data = await self.device.query(":DATA:FRESh?", length=8)  # get a *new* 8 byte double from the instrument
        try:
            # The result of unpack is always a tuple, but we need only the first element
            (data,) = struct.unpack("d", data)
        except struct.error as exc:
            raise ValueError(f"Device returned invalid data {data}.") from exc
        return (DataEvent(sender=self.uuid, sid=0, topic=self.base_topic, value=data, unit=""),)


class Keithley2002ScannerLogger(Keithley2002Logger):
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "k2002_scanner"

    def __init__(self, active_channels: tuple[int], *args, **kwargs) -> None:
        super().__init__(
            column_names=[f"K2002 CH{channel+1}" for channel in active_channels],
            *args,
            **kwargs,
        )
        self.__active_channels = active_channels

    async def read(self) -> tuple[DataEvent, ...]:
        # pylint: disable=consider-using-generator
        return tuple([await self.query_channel(channel) for channel in self.__active_channels])


class Keithley26xxBLogger(LoggingDevice):
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "k26xxb"

    def __init__(self, host: str, port: int, timeout, *args, **kwargs):
        connection = AsyncEthernet(host=host, port=port, timeout=timeout)
        device = Keithley26xxB(connection=connection)

        super().__init__(device, *args, **kwargs)

    async def get_log_header(self):
        cal_date, cal_due_date = await self.device.get_cal_data()
        fw_version = await self.device.get_fw_version()
        sn = await self.device.get_serial_number()
        model = await self.device.get_model()
        return f"K{model} Serial {sn}; FW {fw_version}; Cal date ChA={cal_date[0]}; ChB={cal_date[1]}; Next Cal due ChA={cal_due_date[0]}; ChB={cal_due_date[1]}"

    async def read(self) -> tuple[DataEvent, ...]:
        await super().read()
        data = await self.device.query("print(smua.measure.r())")  # get a *new* 8 byte double from the instrument

        return (DataEvent(sender=self.uuid, sid=0, topic=self.base_topic, value=Decimal(data), unit=""),)


class TinkerforgeLogger(LoggingDevice):
    @classmethod
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
        super().__init__(device, *args, **kwargs)

    # TODO: Rework TF api to be more general
    async def read(self) -> tuple[DataEvent]:
        await super().read()
        try:
            value = await self.device.get_humidity()
        except ConnectionError as exc:
            try:
                await self.device.connect()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.getLogger(__name__).exception("Error during re-connect attempt to Tinkerforge Brick daemon.")
            raise asyncio.TimeoutError("Connection to Tinkerforge bricklet timed out. Reconnecting.") from exc
        return (
            DataEvent(
                sender=self.uuid,
                sid=0,
                topic=self.base_topic + "/humidity",
                value=value,
                unit="%rH",
            ),
        )

    async def get_id(self):
        return await self.device.get_identity()


class Fluke1524Logger(LoggingDevice):
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "fluke1524"

    def __init__(
        self,
        timeout: int,
        baudrate: int,
        *args,
        tty: str | None = None,
        vid: int | None = None,
        pid: int | None = None,
        serial_number: str | None = None,
        **kwargs,
    ):
        connection = (
            AsyncSerial(vid_pid=(vid, pid), serial_number=serial_number, timeout=timeout, baudrate=baudrate)
            if vid is not None and pid is not None
            else AsyncSerial(tty=tty, timeout=timeout, baudrate=baudrate)
        )
        device = Fluke1524(connection)
        super().__init__(device, *args, **kwargs)

    # TODO: Rework API
    async def read(self) -> tuple[DataEvent, DataEvent]:
        await super().read()
        temperature1, temperature2 = await asyncio.gather(self.device.read_sensor1(), self.device.read_sensor2())
        return (
            DataEvent(
                sender=self.uuid,
                sid=0,
                topic=self.base_topic + "/temperature/channel1",
                value=Decimal(temperature1),
                unit="°C",
            ),
            DataEvent(
                sender=self.uuid,
                sid=1,
                topic=self.base_topic + "/temperature/channel2",
                value=Decimal(temperature2),
                unit="°C",
            ),
        )


class Fluke1590Logger(LoggingDevice):
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "fluke1590"

    def __init__(self, host: str, port: int, pad, timeout, *args, **kwargs):
        gpib_device = AsyncPrologixGpibEthernetController(hostname=host, port=port, pad=pad, timeout=timeout)
        device = Fluke1590(connection=gpib_device)

        super().__init__(device, *args, **kwargs)

    async def read(self) -> tuple[DataEvent]:
        channel, value, unit, _ = await self.device.read_temperature()
        return (
            DataEvent(
                sender=self.uuid,
                sid=channel,
                topic=f"{self.base_topic}/resistance/channel{channel}",
                value=value,
                unit=unit,
            ),
        )

    async def initialize(self):
        await super().initialize()
        await self.device.set_line_termination(self.device.LineTerminator.LF)
        await self.device.set_timestamp(date=True, time=True)  # print date and time with each reading
        await self.device.set_mode(self.device.SamplingMode.RUN)
        await self.device.set_screensaver(5 * 60)
        await self.device.set_time(datetime.now(UTC))
        await self.device.set_sample_interval(4)
        await self.device.set_conversion_time(2)
        await self.device.set_integration_time(4)


class EE07Logger(LoggingDevice):
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "ee07"

    def __init__(
        self,
        timeout: int,
        baudrate: int,
        *args,
        tty: str | None = None,
        vid: int | None = None,
        pid: int | None = None,
        serial_number: str | None = None,
        **kwargs,
    ):
        connection = (
            AsyncSerial(vid_pid=(vid, pid), serial_number=serial_number, timeout=timeout, baudrate=baudrate)
            if vid is not None and pid is not None
            else AsyncSerial(tty=tty, timeout=timeout, baudrate=baudrate)
        )
        device = EE07(connection)
        super().__init__(device, *args, **kwargs)

    async def read(self) -> tuple[DataEvent, DataEvent]:
        await super().read()
        humidity, temperature = await asyncio.gather(self.device.read_sensor1(), self.device.read_sensor2())
        return (
            DataEvent(
                sender=self.uuid,
                sid=0,
                topic=self.base_topic + "/humidity",
                value=Decimal(humidity),
                unit="%rH",
            ),
            DataEvent(
                sender=self.uuid,
                sid=1,
                topic=self.base_topic + "/temperature",
                value=Decimal(temperature),
                unit="°C",
            ),
        )


class WavemasterLogger(LoggingDevice):
    async def read(self) -> tuple[DataEvent]:
        await super().read()
        wavelength = await self.device.read_wavelength()
        return (
            DataEvent(
                sender=self.uuid,
                sid=0,
                topic=self.base_topic,
                value=wavelength,
                unit="nm",
            ),
        )
