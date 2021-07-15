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
import async_timeout

class KeithleyDMM6500():
    def __init__(self, connection):
        self.__conn = connection

    async def connect(self):
        await self.__conn.connect()
        try:
            with async_timeout.timeout(0.1):    # 100ms timeout
                await self.read()
        except asyncio.TimeoutError:
            pass

    async def disconnect(self):
        await self.__conn.disconnect()

    async def write(self, cmd):
        await self.__conn.write((cmd + "\n").encode("ascii"))

    async def __read(self, length=None):
        # Strip the separator "\n"
        if length is None: # pylint: disable=no-else-return
            return (await self.__conn.read())[:-1].decode("utf-8")
        else:
            return (await self.__conn.read(len=len+1))[:-1]

    async def query(self, cmd, length=None):
        await self.write(cmd)
        return await self.__read(length)

    async def get_id(self):
        # TODO: Catch AttributeError if not connected
        return await self.query("*IDN?")

    async def set_mode_resistance_2w(self):
        await self.write("SENS:FUNC 'RES'")

    async def set_nplc(self, nplc):
        await self.write("SENS:RES:NPLC {nplc}".format(nplc=nplc))

    async def read(self):
        await self.write("READ?")
        try:
            return await self.__read()
        except asyncio.TimeoutError:
            return None


class Keithley2002():
    def __init__(self, connection):
        self.__conn = connection

    async def get_id(self):
        # Catch AttributeError if not connected
        await self.write("*IDN?")
        return await self.read()

    async def write(self, cmd):
        await self.__conn.write((cmd + "\n").encode("ascii"))

    async def read(self, length=None):
        # if length is set, return the bytes untouched
        if length is None:  # pylint: disable=no-else-return
            return (await self.__conn.read()).strip().decode("utf-8")
        else:
            return (await self.__conn.read(length=length+1))[:-1]

    async def query(self, cmd, length=None):
        await self.write(cmd)
        return await self.read(length)

    async def connect(self):
        await self.__conn.connect()

    async def disconnect(self):
        await self.__conn.disconnect()
