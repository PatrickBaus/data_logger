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
from datetime import UTC, datetime, timezone
from typing import overload

from devices.connections import Connection, GpibConnection, PrologixGpibConnection


class KeithleyDMM6500:
    def __init__(self, connection: Connection) -> None:
        self.__conn = connection

    async def connect(self) -> None:
        await self.__conn.connect()
        await self.write(":ABORt")
        try:
            await asyncio.wait_for(self.read(), timeout=0.1)  # 100ms timeout
        except asyncio.TimeoutError:
            pass

    async def disconnect(self) -> None:
        await self.__conn.disconnect()

    async def write(self, cmd: str) -> None:
        await self.__conn.write(cmd.encode("ascii"))

    async def __read(self) -> str:
        return (await self.__conn.read()).decode("utf-8")

    @overload
    async def query(self, cmd: str, length: None = None) -> str: ...

    @overload
    async def query(self, cmd: str, length: int) -> bytes: ...

    async def query(self, cmd: str, length: int | None = None) -> str | bytes:
        """Text replies are returned as str. If the length is given, the reply is binary and returned as bytes."""
        result = await self.__conn.query(cmd.encode("ascii"), length=length)
        return result if length is not None else result.decode("utf-8")

    async def get_id(self) -> str:
        # TODO: Catch AttributeError if not connected
        return await self.query("*IDN?")

    async def set_mode_resistance_2w(self) -> None:
        await self.write("SENS:FUNC 'RES'")

    async def set_nplc(self, nplc: float) -> None:
        await self.write(f"SENS:RES:NPLC {nplc}")

    async def read(self) -> str | None:
        try:
            return await self.__read()
        except asyncio.TimeoutError:
            return None


class Keithley2002:
    def __init__(self, connection: Connection) -> None:
        self.__conn = connection
        self.__logger = logging.getLogger(__name__)

    async def get_id(self) -> str:
        # Catch AttributeError if not connected
        return await self.query("*IDN?")

    async def get_cal_data(self) -> tuple[datetime, datetime]:
        cal_date_str = await self.query(":CALibration:PROTected:DATE?")
        cal_datetime = datetime.strptime(cal_date_str, "%Y,%m,%d").replace(tzinfo=timezone.utc)
        due_date_str = await self.query(":CALibration:PROTected:NDUE?")
        due_datetime = datetime.strptime(due_date_str, "%Y,%m,%d").replace(tzinfo=timezone.utc)

        # cal_const_str = await self.query(':CALibration:PROTected:DATA?')

        return cal_datetime, due_datetime

    def __gpib(self) -> GpibConnection | PrologixGpibConnection:
        if not isinstance(self.__conn, (GpibConnection, PrologixGpibConnection)):
            raise TypeError(f"{self.__conn} is not a GPIB connection.")
        return self.__conn

    async def wait_for_data(self) -> None:
        try:
            await self.__gpib().wait((1 << 11) | (1 << 14))  # Wait for RQS or TIMO
        except asyncio.TimeoutError:
            self.__logger.warning(
                "Timeout during wait. Is the IbaAUTOPOLL(0x7) bit set for the board? Or the timeout set too low?"
            )
            raise

    async def write(self, cmd: str, test_error: bool = False) -> None:
        if cmd.lower() == "*opc?":
            # Wait until the device has finished all pending operations
            await self.__conn.query(cmd.encode("ascii"))
            return
        await self.__conn.write(cmd.encode("ascii"))
        if test_error and not cmd.startswith("*"):
            self.__logger.warning(await self.query(":SYSTem:ERRor?"))

    @overload
    async def read(self, length: None = None) -> str: ...

    @overload
    async def read(self, length: int) -> bytes: ...

    async def read(self, length: int | None = None) -> str | bytes:
        """Text replies are returned as str. If the length is given, the reply is binary and returned as bytes."""
        result = await self.__conn.read(length=length)
        return result if length is not None else result.decode("utf-8").strip()

    @overload
    async def query(self, cmd: str, length: None = None) -> str: ...

    @overload
    async def query(self, cmd: str, length: int) -> bytes: ...

    async def query(self, cmd: str, length: int | None = None) -> str | bytes:
        """Text replies are returned as str. If the length is given, the reply is binary and returned as bytes."""
        result = await self.__conn.query(cmd.encode("ascii"), length=length)
        return result if length is not None else result.decode("utf-8").strip()

    async def serial_poll(self) -> int:
        return await self.__gpib().serial_poll()

    async def connect(self) -> None:
        await self.__conn.connect()

    async def disconnect(self) -> None:
        await self.__conn.disconnect()


class Keithley26xxB:
    def __init__(self, connection: Connection) -> None:
        self.__conn = connection

    async def connect(self) -> None:
        await self.__conn.connect()
        try:
            await asyncio.wait_for(self.read(), timeout=0.1)  # 100ms timeout
        except asyncio.TimeoutError:
            pass

    async def disconnect(self) -> None:
        await self.__conn.disconnect()

    async def get_id(self) -> str:
        # Catch AttributeError if not connected
        return await self.query("*IDN?")

    async def get_cal_data(self) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]]:
        cal_date_str = await self.query("print(smua.cal.date)"), await self.query("print(smub.cal.date)")
        cal_datetime = tuple(map(lambda x: datetime.fromtimestamp(x, UTC), map(float, cal_date_str)))
        assert len(cal_datetime) == 2
        due_date_str = await self.query("print(smua.cal.due)"), await self.query("print(smub.cal.due)")
        due_datetime = tuple(map(lambda x: datetime.fromtimestamp(x, UTC), map(float, due_date_str)))
        assert len(due_datetime) == 2

        return cal_datetime, due_datetime

    async def get_fw_version(self) -> str:
        return await self.query("print(localnode.revision)")

    async def get_serial_number(self) -> str:
        return await self.query("print(localnode.serialno)")

    async def get_model(self) -> str:
        return await self.query("print(localnode.model)")

    async def write(self, cmd: str) -> None:
        await self.__conn.write(cmd.encode("ascii"))

    async def __read(self) -> str:
        return (await self.__conn.read()).decode("utf-8")

    @overload
    async def query(self, cmd: str, length: None = None) -> str: ...

    @overload
    async def query(self, cmd: str, length: int) -> bytes: ...

    async def query(self, cmd: str, length: int | None = None) -> str | bytes:
        """Text replies are returned as str. If the length is given, the reply is binary and returned as bytes."""
        result = await self.__conn.query(cmd.encode("ascii"), length=length)
        return result if length is not None else result.decode("utf-8")

    async def read(self) -> str | None:
        try:
            return await self.__read()
        except asyncio.TimeoutError:
            return None
