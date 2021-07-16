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
import serial_asyncio

class Fluke1524():
    def __init__(self, conn):
        self.__conn = conn
        self.__conn.separator = b'\r'
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
        self.write("")    # Flush input buffer of the device
        try:
            await asyncio.wait_for(self.read(), timeout=0.1)    # 100ms timeout
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
