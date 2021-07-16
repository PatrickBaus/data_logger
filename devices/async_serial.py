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

import serial_asyncio

class AsyncSerial:
    @property
    def separator(self):
        return self.__separator

    @separator.setter
    def separator(self, value):
        self.__separator = value

    @property
    def is_connected(self):
        return self.__writer is not None and not self.__writer.is_closing()

    def __init__(self, tty, separator=b'\n', timeout=None, **kwargs):
        self.__tty = tty
        self.__separator = separator
        self.__lock = None
        self.__kwargs = kwargs
        self.__timeout = 0.1 if timeout is None else timeout # in seconds
        self.__reader, self.__writer = None, None
        self.__logger = logging.getLogger(__name__)

    async def read(self, length=None):
        if self.is_connected:
            try:
                async with timeout(self.__timeout) as context_manager:
                    async with self.__lock:
                        if length is None:
                            # Read until the separator
                            data = await self.__reader.readuntil(self.__separator)
                        else:
                            # read $length bytes
                            data = await self.__reader.readexactly(length)
                    return data.decode("utf-8")
            except asyncio.CancelledError:
                if context_manager.expired:
                    raise asyncio.TimeoutError() from None
                raise
        else:
            # TODO: raise custom error
            pass

    async def write(self, cmd):
        if self.is_connected:
            self.__writer.write(cmd.encode())
            await asyncio.wait_for(self.__writer.drain(), timeout=self.__timeout)
        else:
            # TODO: raise custom error
            pass

    async def connect(self):
        if not self.is_connected:
            self.__lock = asyncio.Lock()
            self.__reader, self.__writer = await asyncio.wait_for(
                await serial_asyncio.open_serial_connection(url=self.__tty, **self.__kwargs),
                timeout=self.__timeout
            )

            self.__writer.transport.serial.reset_input_buffer()
            self.__logger.info("Serial connection established")

    async def disconnect(self):
        if self.is_connected:
            try:
                # self.__reader._transport.close()  # This is (probably) not needed
                try:
                    self.__writer.close()
                    await self.__writer.wait_closed()
                except ConnectionResetError:
                    pass    # We are no loger connected, so we can ignore it
            finally:
                # We guarantee, that the connection is removed
                self.__writer, self.__reader = None, None
                self.__logger.info("Serial connection closed")
