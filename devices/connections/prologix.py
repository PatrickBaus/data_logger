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
"""A GPIB connection using a Prologix GPIB-Ethernet adapter, through the prologix-gpib-async library."""

from __future__ import annotations

from typing import Any

from prologix_gpib_async import AsyncPrologixGpibEthernetController

from devices.connections.base import Connection


class PrologixGpibConnection(Connection):
    """
    A GPIB connection to an instrument using a Prologix GPIB-Ethernet adapter.

    The adapter reads until the instrument asserts EOI and ends each message with a newline. The timeout is managed by
    the Prologix library, so the per-call timeouts of `read()`, `write()` and `query()` have no effect.

    Parameters
    ----------
    host: str
        The hostname or IP address of the adapter
    pad: int
        The primary GPIB address of the instrument
    port: int
        The TCP port of the adapter
    timeout: float
        The GPIB timeout in seconds
    **kwargs
        Passed to `AsyncPrologixGpibEthernetController`, for example the `wait_delay` between the polls of the
        adapter.
    """

    @property
    def is_connected(self) -> bool:
        return self.__connected

    def __init__(self, host: str, pad: int, port: int = 1234, timeout: float = 3, **kwargs: Any) -> None:
        super().__init__(timeout=timeout)
        self.__host = host, port
        self.__pad = pad
        self.__controller = AsyncPrologixGpibEthernetController(
            hostname=host, port=port, pad=pad, timeout=timeout, **kwargs
        )
        self.__connected = False

    def __str__(self) -> str:
        return f"Prologix adapter {self.__host[0]}:{self.__host[1]}, GPIB address {self.__pad}"

    async def serial_poll(self) -> int:
        """Read the status byte of the instrument."""
        return await self.__controller.serial_poll(pad=self.__pad)

    async def wait(self, eventmask: int) -> None:
        """Wait for one of the GPIB events in the mask, like RQS."""
        await self.__controller.wait(eventmask)

    async def _connect(self) -> None:
        await self.__controller.connect()
        self.__connected = True

    async def _disconnect(self) -> None:
        try:
            await self.__controller.disconnect()
        finally:
            self.__connected = False

    async def _write(self, data: bytes, timeout: float) -> None:
        await self.__controller.write(data)

    async def _read_until(self, terminator: bytes, timeout: float) -> bytes:
        # Reads until EOI
        return await self.__controller.read()

    async def _read_exactly(self, length: int, timeout: float) -> bytes:
        return await self.__controller.read(length=length)
