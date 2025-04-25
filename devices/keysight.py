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
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from devices.async_ethernet import AsyncEthernet


class Hp3458A:
    def __init__(self, connection) -> None:
        self.__conn = connection

        self.__logger = logging.getLogger(__name__)

    async def get_id(self) -> str:
        await self.write("ID?")
        return await self.read()

    async def write(self, cmd: str) -> None:
        self.__logger.debug("Writing: %s", cmd)
        await self.__conn.write((cmd + "\n").encode("ascii"))

    async def read(self) -> str:
        return (await self.__conn.read()).strip().decode("utf-8")

    async def query(self, cmd: str) -> str:
        await self.write(cmd)
        return await self.read()

    async def beep(self) -> None:
        await self.write("BEEP")

    async def acal_dcv(self) -> None:
        self.__logger.debug("Running ACAL DCV. This will take 165 seconds.")
        await self.beep()
        await self.write("ACAL DCV")
        await asyncio.sleep(165)
        self.__logger.debug("ACAL done.")

    async def get_acal1v(self) -> Decimal:
        result = await self.query("CAL? 71,1")

        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def get_acal10v(self) -> Decimal:
        result = await self.query("CAL? 72,1")

        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def get_cal7v(self) -> Decimal:
        result = await self.query("CAL? 2")

        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def get_cal40k(self) -> Decimal:
        result = await self.query("CAL? 1")

        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def get_temperature_acal_dcv(self) -> Decimal:
        result = Decimal(await self.query("CAL? 175"))

        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def get_temperature(self) -> Decimal:
        result = Decimal(await self.query("TEMP?"))

        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def connect(self) -> None:
        self.__logger.debug("Connecting to HP3458A.")
        await self.__conn.connect()
        await self.write("END ALWAYS; TARM HOLD")  # Recommended during setup as per manual p. 51
        self.__logger.debug("Connected to HP3458A.")

    async def disconnect(self) -> None:
        await self.__conn.disconnect()


class Keysight34470A:
    def __init__(self, connection: AsyncEthernet) -> None:
        self.__conn = connection

        self.__logger = logging.getLogger(__name__)

    async def connect(self) -> None:
        self.__logger.debug("Connecting to Keysight 34470A.")
        await self.__conn.connect()
        await self.write(":ABORt")
        try:
            await asyncio.wait_for(self.read(), timeout=0.1)  # 100ms timeout
        except asyncio.TimeoutError:
            pass
        self.__logger.debug("Connected to Keysight 34470A.")

    async def disconnect(self) -> None:
        await self.__conn.disconnect()

    async def write(self, cmd: str) -> None:
        await self.__conn.write((cmd + "\n").encode("ascii"))

    async def __read(self, length: int | None = None, **kwargs) -> str:
        # Strip the separator "\n"
        if length is None:  # pylint: disable=no-else-return
            return (await self.__conn.read(**kwargs))[:-1].decode("utf-8")
        else:
            return (await self.__conn.read(length=length + 1, **kwargs))[:-1]

    async def query(self, cmd: str, **kwargs) -> str:
        await self.write(cmd)
        return await self.__read(**kwargs)

    async def get_id(self) -> str:
        # Catch AttributeError if not connected
        return await self.query("*IDN?")

    async def beep(self) -> None:
        await self.write("SYSTem:BEEP")

    async def get_acal_data(self) -> tuple[datetime, Decimal]:
        acal_date_str = (
            f"{await self.query('SYSTem:ACALibration:DATE?')} {await self.query('SYSTem:ACALibration:TIME?')}"
        )
        acal_datetime = datetime.strptime(acal_date_str, "+%Y,+%m,+%d %H,%M,%S.%f").replace(tzinfo=timezone.utc)
        acal_temperature = await self.query("SYSTem:ACALibration:TEMPerature?")
        try:
            return acal_datetime, Decimal(acal_temperature)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {acal_temperature} to Decimal") from exc

    async def get_cal_data(self) -> tuple[datetime, Decimal, str]:
        cal_date_str = f"{await self.query('CALibration:DATE?')} {await self.query('CALibration:TIME?')}"
        cal_datetime = datetime.strptime(cal_date_str, "+%Y,+%m,+%d %H,%M,%S.%f").replace(tzinfo=timezone.utc)
        cal_temperature = Decimal(await self.query("CALibration:TEMPerature?"))
        cal_str = await self.query("CALibration:STRing?")

        try:
            return cal_datetime, Decimal(cal_temperature), cal_str
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {cal_temperature} to Decimal") from exc

    async def get_system_uptime(self) -> timedelta:
        uptime_str = await self.query("SYSTem:UPTime?")
        days, hours, minutes, seconds = map(int, uptime_str.split(","))
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)

    async def acal(self) -> None:
        """
        Run auto-calibration. ACAL takes about 14.5 seconds.
        Note: There is a bug in the acal firmware, which will cause an offset and drift back to zero offset afterwards.
        It is therefore not recommended (IMHO) to run this.
        """
        self.__logger.debug("Running ACAL on 34470A this will take about 15 seconds.")
        result = await self.query("*CAL?", timeout=max(self.__conn.timeout, 14.5 * 1.1))
        self.__logger.debug("Finished ACAL on 34470A.")
        if result != "+0":
            self.__logger.error("Error during ACAL of 34470A.")

    async def set_mode_resistance_2w(self) -> None:
        await self.write("SENSe:FUNC 'RES'")

    async def set_mode_resistance_4w(self) -> None:
        await self.write("SENSe:FUNC 'FRES'")

    async def set_nplc(self, nplc: int) -> None:
        await self.write(f"SENSe:RES:NPLC {nplc}")

    async def read(self) -> str:
        # TODO: Catch special SCPI values
        # TODO: Catch +-9.9E37 = +-Inf or raise an error
        # TODO: Catch 9.91E37 = NaN or raise an error
        return await asyncio.wait_for(self.__read(), timeout=10)

    async def fetch(self) -> str:
        return await self.query("FETCH?")
