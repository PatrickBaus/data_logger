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
import re
from datetime import datetime
from decimal import Decimal
from enum import Enum, unique
from typing import TypeAlias


class InvalidDataError(ValueError):
    """Raised if the device does not return the expected result."""


@unique
class SamplingMode(Enum):
    RUN = "r"
    STOP = "st"
    SAMPLEs = "sn"  # pylint: disable=invalid-name


@unique
class LineTerminator(Enum):
    CR = "cr"
    LF = "lf"
    CRLF = "cl"


class Fluke1590:  # pylint: disable=too-many-public-methods
    SamplingMode: TypeAlias = SamplingMode
    LineTerminator: TypeAlias = LineTerminator
    # Regex tested against:
    # "1: 10000.0900 O  7:57:00    11-1-22  "
    # "1: 10000.0879 O  15:02:52    10-31-22  "
    # "1: 10000.0906 O  10-31-22  "
    # "1: 10000.0902 O  15:24:06   "
    # "1: 10000.0869 O"
    MEASUREMENT_REGEX = re.compile(
        r"^(\d): (\d+\.?\d*) (.)\s*(?:((?:[01]?\d|2[0-3]):[0-5]\d:[0-5]\d)\s*)?(?:(\d{1,2}-\d{1,2}-\d{2})\s*)?$"
    )

    UNIT_CONVERSION = {"O": "Ω"}

    def __init__(self, connection) -> None:
        self.__conn = connection
        self.__lock: asyncio.Lock | None = None

    async def read(self) -> str:
        # Strip the separator "\n"
        return (await self.__conn.read())[:-1].decode("utf-8")

    async def write(self, cmd: str) -> None:
        await self.__conn.write((cmd + "\n").encode("ascii"))

    async def query(self, cmd: str) -> str:
        if self.__lock is None:
            raise ConnectionError("Not connected.")
        async with self.__lock:
            await self.write(cmd)
            result = await self.read()
            return result

    async def connect(self) -> None:
        await self.__conn.connect()
        self.__conn.set_wait_delay(1)
        self.__lock = asyncio.Lock()

    async def disconnect(self) -> None:
        await self.__conn.disconnect()

    async def set_conversion_time(self, time: float) -> None:
        await self.write(f"ct={int(time)}")

    async def get_conversion_time(self) -> float:
        return float(await self.query("ct"))

    async def set_sample_interval(self, time: float) -> None:
        await self.write(f"si={int(time)}")

    async def get_sample_interval(self) -> float:
        return float(await self.query("si"))

    async def set_integration_time(self, time: float) -> None:
        await self.write(f"st={int(time)}")

    async def get_integration_time(self) -> float:
        return float(await self.query("st"))

    async def has_data(self) -> bool:
        result = await self.query("new")
        m = re.match(r"^NEW: (\d+)$", result)
        return m is not None and int(m.group(1)) > 0

    async def read_temperature(self) -> tuple[int, Decimal, str, datetime]:
        while not await self.has_data():
            await asyncio.sleep(0.2)
        result = await self.query("tem")
        try:
            channel, value, unit, time, date = self.MEASUREMENT_REGEX.split(result)[1:-1]
        except ValueError:
            # Raised if the regex does not match, and therefore we have no values to unpack
            raise InvalidDataError(f"The device {self} returned invalid data: '{result}'") from None
        if date is not None and time is not None:
            timestamp = datetime.strptime(f"{date} {time}", "%m-%d-%y %H:%M:%S")
        elif date is None and time is not None:
            timestamp = datetime.strptime(time, "%H:%M:%S")
        elif date is not None and time is None:
            timestamp = datetime.strptime(date, "%m-%d-%y")
        else:
            timestamp = datetime.utcnow()
        return int(channel) - 1, Decimal(value), self.UNIT_CONVERSION[unit], timestamp

    async def read_channel(self, channel: int) -> str:
        # The manual states, no more than 5 commands per second (see 8.3 Digital Interface Commands in the manual)
        await asyncio.sleep(1.2)
        result = await self.query(f"tc({channel+1})")
        result, _ = result.removeprefix(f"{channel+1}: ").split(" ")  # (result, unit)
        return result

    async def get_id(self) -> str:
        # v[ersion] command
        result = await self.query("v")
        model, version = result.removeprefix("VER: ").split(",")
        return f"Fluke,{model},0,{version}"

    async def set_mode(self, mode: SamplingMode) -> None:
        await self.write(f"sact={mode.value}")

    async def set_screensaver(self, timeout: int) -> None:
        """
        Enable or disable the screensaver. If the timeout is set to 0, The screensaver will be disabled.
        Parameters
        ----------
        timeout: int
            The time in seconds until the screen saver is activated. Internally this will be rounded to minutes.
            Set to 0 to deactivate the screen saver.
        """
        if timeout <= 0:
            await self.write("scrs=off")
        else:
            await self.write(f"scrs=on & scrt={int(timeout)//60}")

    async def get_screensaver(self) -> int:
        enabled = await self.query("scrs")
        if not enabled:
            return 0

        time = await self.query("scrt")
        time = time.removeprefix("SCR SAV TIME (MIN): ")
        return int(time) * 60

    async def set_time(self, time: datetime) -> None:
        await self.write(f"dat={time.strftime('%m-%d-%y')} & ti={time.strftime('%H:%M:%S')}")

    async def get_time(self) -> datetime:
        time = await self.query("ti")
        time = time.removeprefix("TIME: ").rstrip()
        date = await self.query("dat")
        date = date.removeprefix("DATE: ").rstrip()
        return datetime.strptime(f"{date} {time}", "%m-%d-%y %H:%M:%S")

    async def get_reference_resistor_value(
        self,
    ) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        # reference 0: external
        # reference 1: 1 Ω
        # reference 2: 10 Ω
        # reference 2: 100 Ω
        # reference 3: 10 kΩ
        refs = [await self.query(f"rr({i})") for i in range(5)]
        refs[0] = refs[0].removeprefix("REF RES 0 (EXT): ")
        results = tuple(Decimal(ref.removeprefix(f"REF RES {i} (INT): ")) for i, ref in enumerate(refs))
        assert len(results) == 5
        return results

    async def set_line_termination(self, terminator: LineTerminator) -> None:
        await self.write(f"ter={terminator.value}")

    async def get_line_termination(self) -> LineTerminator:
        result = await self.query("ter")
        result = result.removeprefix("IEEE TERM: ").lower()
        return self.LineTerminator(result)

    async def set_timestamp(self, date: bool = False, time: bool = False) -> None:
        """
        Timestamp the measurement results.
        Parameters
        ----------
        date: bool
            Return the date with each measurement.
        time: bool
            Return the time with each measurement.
        """
        await self.write(f"ieed={'on' if date else 'off'} & ieet={'on' if time else 'off'}")

    async def get_timestamp(self) -> tuple[bool, bool]:
        date = await self.query("ieed")
        date = date.removeprefix("IEEE DATE: ").lower()
        time = await self.query("ieet")
        time = time.removeprefix("IEEE TIME: ").lower()
        return date == "on", time == "on"


class Fluke1524:
    def __init__(self, conn):
        self.__conn = conn
        self.__conn.separator = b"\r"
        self.__lock = None

    async def read(self):
        # Strip the separator "\n"
        return (await self.__conn.read())[:-1]

    async def write(self, cmd):
        await self.__conn.write(cmd + "\r\n")

    async def query(self, cmd):
        async with self.__lock:
            await self.write(cmd)
            result = await self.read()
            return result

    async def connect(self):
        await self.__conn.connect()
        self.__lock = asyncio.Lock()
        await self.write("")  # Flush input buffer of the device
        try:
            await asyncio.wait_for(self.read(), timeout=0.1)  # 100ms timeout
        except asyncio.TimeoutError:
            pass

    async def disconnect(self):
        await self.__conn.disconnect()

    async def read_sensor1(self):
        return await self.query("READ? 1")

    async def read_sensor2(self):
        return await self.query("READ? 2")

    async def get_id(self):
        return await self.query("*IDN?")
