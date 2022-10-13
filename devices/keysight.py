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

import async_timeout

class Hp3458A():
    def __init__(self, connection):
        self.__conn = connection

        self.__logger = logging.getLogger(__name__)

    async def get_id(self):
        await self.write("ID?")
        return await self.read()

    async def write(self, cmd):
        self.__logger.debug("Writing: %s", cmd)
        await self.__conn.write((cmd + "\n").encode("ascii"))

    async def read(self):
        return (await self.__conn.read()).strip().decode("utf-8")

    async def query(self, cmd):
        await self.write(cmd)
        return await self.read()

    async def beep(self):
        await self.__conn.write("BEEP")

    async def acal_dcv(self):
        self.__logger.debug("Running ACAL DCV. This will take 165 seconds.")
        await self.beep()
        await self.write("ACAL DCV")
        await asyncio.sleep(165)
        self.__logger.debug("ACAL done.")

    async def get_acal1v(self):
        return await self.query("CAL? 71,1")

    async def get_acal10v(self):
        return await self.query("CAL? 72,1")

    async def get_cal7v(self):
        return await self.query("CAL? 2")

    async def get_cal40k(self):
        return await self.query("CAL? 1")

    async def get_temperature_acal_dcv(self):
        return await self.query("CAL? 175")

    async def connect(self):
        self.__logger.debug("Connecting to HP3458A.")
        await self.__conn.connect()
        await self.write("END ALWAYS; TARM HOLD")  # Recommended during setup as per manual p. 51
        self.__logger.debug("Connected to HP3458A.")

    async def disconnect(self):
        await self.__conn.disconnect()


class Keysight34470A():
    def __init__(self, connection):
        self.__conn = connection

        self.__logger = logging.getLogger(__name__)
    async def connect(self):
        self.__logger.debug("Connecting to Keysight 34470A.")
        await self.__conn.connect()
        await self.write(":ABORt")
        try:
            with async_timeout.timeout(0.1):    # 100ms timeout
                await self.read()
        except asyncio.TimeoutError:
            pass
        self.__logger.debug("Connected to Keysight 34470A.")

    async def disconnect(self):
        await self.__conn.disconnect()

    async def write(self, cmd):
        await self.__conn.write((cmd + "\n").encode("ascii"))

    async def __read(self, length=None):
        # Strip the separator "\n"
        if length is None: # pylint: disable=no-else-return
            return (await self.__conn.read())[:-1].decode("utf-8")
        else:
            return (await self.__conn.read(length=length+1))[:-1]

    async def query(self, cmd):
        await self.write(cmd)
        return await self.__read()

    async def get_id(self):
        # Catch AttributeError if not connected
        return await self.query("*IDN?")

    async def beep(self):
        await self.write("SYSTem:BEEP")

    async def get_acal_data(self):
        acal_date_str = f"{await self.query('SYSTem:ACALibration:DATE?')} {await self.query('SYSTem:ACALibration:TIME?')}"
        acal_datetime = datetime.strptime(acal_date_str, "+%Y,+%m,+%d %H,%M,%S.%f").replace(tzinfo=timezone.utc)
        acal_temperature = Decimal(await self.query("SYSTem:ACALibration:TEMPerature?"))
        return acal_datetime, acal_temperature

    async def get_cal_data(self):
        cal_date_str = f"{await self.query('CALibration:DATE?')} {await self.query('CALibration:TIME?')}"
        cal_datetime = datetime.strptime(cal_date_str, "+%Y,+%m,+%d %H,%M,%S.%f").replace(tzinfo=timezone.utc)
        cal_temperature = Decimal(await self.query("CALibration:TEMPerature?"))
        cal_str = await self.query("CALibration:STRing?")
        print(cal_datetime, cal_temperature, cal_str)
        return cal_datetime, cal_temperature, cal_str

    async def get_system_uptime(self):
        uptime_str = await self.query("SYSTem:UPTime?")
        days, hours, minutes, seconds = map(int,uptime_str.split(","))
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)

    async def acal(self):
        return "+0"
#        There is a bug in the acal firmware. We will skip it for now
#        return await self.query("*CAL?")

    async def set_mode_resistance_2w(self):
        await self.write("SENSe:FUNC 'RES'")

    async def set_mode_resistance_4w(self):
        await self.write("SENSe:FUNC 'FRES'")

    async def set_nplc(self, nplc):
        await self.write("SENSe:RES:NPLC {nplc}".format(nplc=nplc))

    async def read(self):
        # TODO: Catch special SCPI values
        # TODO: Catch +-9.9E37 = +-Inf or raise an error
        # TODO: Catch 9.91E37 = NaN or raise an error
        try:
            with async_timeout.timeout(10):
                return await self.__read()
        except asyncio.TimeoutError:
            return None

    async def fetch(self):
        return await self.query("FETCH?")
