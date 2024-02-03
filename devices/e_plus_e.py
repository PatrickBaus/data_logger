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
from decimal import Decimal, InvalidOperation


class EE07:
    @property
    def connection(self):
        return self.__conn

    def __init__(self, conn) -> None:
        self.__conn = conn
        self.__lock: asyncio.Lock | None = None

    async def read(self) -> str:
        # Strip the separator
        return (await self.__conn.read())[:-1]

    async def write(self, cmd: str) -> None:
        await self.__conn.write(cmd + "\n")

    async def query(self, cmd: str) -> str:
        if self.__lock is None:
            raise ConnectionError("Not connected.")
        async with self.__lock:
            await self.write(cmd)
            result = await self.read()
            return result

    async def connect(self) -> None:
        await self.__conn.connect()
        self.__lock = asyncio.Lock()
        await self.write("")  # Flush input buffer of the device
        while "device output buffer not empty":
            try:
                await asyncio.wait_for(self.read(), timeout=0.1)  # 100ms timeout
            except asyncio.TimeoutError:
                break

    async def disconnect(self) -> None:
        await self.__conn.disconnect()

    async def read_sensor1(self) -> Decimal:
        result = await self.query("READ? 1")

        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def read_sensor2(self) -> Decimal:
        result = await self.query("READ? 2")

        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def get_id(self) -> str:
        return await self.query("*IDN?")
