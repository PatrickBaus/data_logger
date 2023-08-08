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
import logging


class KeithleyDMM6500:
    def __init__(self, connection):
        self.__conn = connection

    async def connect(self):
        await self.__conn.connect()
        await self.write(":ABORt")
        try:
            await asyncio.wait_for(self.read(), timeout=0.1)  # 100ms timeout
        except asyncio.TimeoutError:
            pass

    async def disconnect(self):
        await self.__conn.disconnect()

    async def write(self, cmd):
        await self.__conn.write((cmd + "\n").encode("ascii"))

    async def __read(self, length=None):
        # Strip the separator "\n"
        if length is None:  # pylint: disable=no-else-return
            return (await self.__conn.read())[:-1].decode("utf-8")
        else:
            return (await self.__conn.read(length=length+1))[:-1]

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
        try:
            return await self.__read()
        except asyncio.TimeoutError:
            return None


class Keithley2002:
    def __init__(self, connection):
        self.__conn = connection
        self.__logger = logging.getLogger(__name__)

    async def get_id(self):
        # Catch AttributeError if not connected
        await self.write("*IDN?", test_error=False)
        return await self.read()

    async def get_cal_data(self):
        cal_date_str = await self.query(':CALibration:PROTected:DATE?')
        cal_datetime = datetime.strptime(cal_date_str, "%Y,%m,%d").replace(tzinfo=timezone.utc)
        due_date_str = await self.query(':CALibration:PROTected:NDUE?')
        due_datetime = datetime.strptime(due_date_str, "%Y,%m,%d").replace(tzinfo=timezone.utc)

        #cal_const_str = await self.query(':CALibration:PROTected:DATA?')

        return cal_datetime, due_datetime

    async def wait_for_data(self):
        try:
            await self.__conn.wait((1 << 11) | (1 << 14))    # Wait for RQS or TIMO
        except asyncio.TimeoutError:
            self.__logger.warning("Timeout during wait. Is the IbaAUTOPOLL(0x7) bit set for the board? Or the timeout set too low?")
            raise

    async def write(self, cmd, test_error=False):
        await self.__conn.write((cmd + "\n").encode("ascii"))
        if cmd.lower() == "*opc?":
            await self.read()
        elif test_error and not cmd.startswith("*"):
            await self.__conn.write((":SYSTem:ERRor?" + "\n").encode("ascii"))
            print(await self.read())

    async def read(self, length=None):
        # if length is set, return the bytes untouched
        if length is None:  # pylint: disable=no-else-return
            return (await self.__conn.read()).strip().decode("utf-8")
        else:
            return (await self.__conn.read(length=length+1))[:-1]

    async def query(self, cmd, length=None):
        await self.write(cmd, test_error=False)
        try:
            result = await self.read(length)
            return result
        except Exception:
            import traceback
            traceback.print_exc()

    async def serial_poll(self):
        return await self.__conn.serial_poll()

    async def connect(self):
        await self.__conn.connect()

    async def disconnect(self):
        await self.__conn.disconnect()
