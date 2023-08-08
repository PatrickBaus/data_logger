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
from decimal import Decimal, InvalidOperation
from enum import Enum

class LdtMode(Enum):
    T = "T"
    SENSOR = "SENSOR"
    ITE = "ITE"
    VTE = "VTE"
    RAC = "RAC"

class LDT5948:
    @property
    def connection(self):
        return self.__conn

    def __init__(self, conn):
        self.__conn = conn
        self.__lock = None

    async def read(self):
        # Strip the separator "\r\n"
        return (await self.__conn.read())[:-2]

    async def __write(self, cmd):
        await self.__conn.write(cmd + "\r\n")

    async def write(self, cmd):
        async with self.__lock:
            await self.__write(cmd)
            await self.read()

    async def connect(self):
        await self.__conn.connect()
        self.__lock = asyncio.Lock()
        try:
            await asyncio.wait_for(self.read(), timeout=0.1)    # 100ms timeout
        except asyncio.TimeoutError:
            pass

    async def disconnect(self):
        await self.__conn.disconnect()

    async def query(self, cmd):
        async with self.__lock:
            await self.__write(cmd)
            result = await self.read()
            return result

    async def get_id(self) -> str:
        return await self.query("*IDN?")

    async def read_temperature(self) -> Decimal:
        result = await self.query("MEAS:TEMP?")
        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def read_current(self) -> Decimal:
        result = await self.query("MEAS:ITE?")
        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def read_voltage(self) -> Decimal:
        result = await self.query("MEAS:VTE?")
        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to Decimal") from exc

    async def set_enabled(self, value):
        await self.write(f"OUTPUT {bool(value)}")

    async def is_enabled(self) -> bool:
        result = await self.query("OUTPUT?")
        if result == '1':
            result = True
        elif result == '0':
            result = False
        else:
            raise ValueError(f"Invalid return value: {result}")
        return result

    async def set_pid_constants(self, kp, ki, kd):  # pylint: disable=invalid-name
        assert 0 <= kp <= 9999.99
        assert 0 <= ki <= 999.999
        assert 0 <= kd <= 999.999
        await self.write(f"PID {kp:.2f},{ki:.3f},{kd:.3f}")

    async def get_pid_constants(self) -> tuple[Decimal, Decimal, Decimal]:
        result = await self.query("PID?")
        return tuple(map(Decimal, result.split(",")))

    async def set_temperature_setpoint(self, value):
        await self.write(f"SET:TEMP {value:.3f}")

    async def get_temperature_setpoint(self) -> Decimal:
        return Decimal(await self.query("SET:TEMP?"))

    async def set_mode(self, mode):
        await self.write(f"MODE {mode.value}")

    async def get_mode(self) -> LdtMode:
        return LdtMode(await self.query("MODE?"))

    async def set_current_setpoint(self, value):
        await self.write(f"SET:ITE {value:.3f}")

    async def get_current_setpoint(self) -> Decimal:
        result = await self.query("SET:ITE?")
        try:
            return Decimal(result)
        except InvalidOperation as exc:
            raise ValueError(f"Could not convert {result} to decimal") from exc
