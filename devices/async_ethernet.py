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

class AsyncEthernet:
    @property
    def separator(self):
        return self.__separator

    @separator.setter
    def separator(self, value):
        self.__separator = value

    @property
    def is_connected(self):
        return self.__writer is not None and not self.__writer.is_closing()

    def __init__(self, host, port, separator=b'\n', timeout=None, **kwargs):
        self.__hostname = host, port
        self.__separator = separator
        self.__kwargs = kwargs
        self.__timeout = 0.1 if timeout is None else timeout # in seconds
        self.__reader, self.__writer = None, None
        self.__logger = logging.getLogger(__name__)

    async def read(self, length=None):
        if self.is_connected:
            if length is None:
                coro = self.__reader.readuntil(self.__separator)
            else:
                coro = self.__reader.readexactly(length)
            data = await asyncio.wait_for(coro, timeout=self.__timeout)
            return data.decode("utf-8")
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
            host, port = self.__hostname
            self.__reader, self.__writer = await asyncio.wait_for(
                asyncio.open_connection(host=host, port=port, **self.__kwargs),
                timeout=self.__timeout
            )
            self.__logger.info('Ethernet connection established')

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
                self.__logger.info('Ethernet connection closed')
