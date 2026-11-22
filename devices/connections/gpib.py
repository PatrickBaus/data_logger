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
"""A GPIB connection using a Linux-GPIB board, through the async-gpib library."""

from __future__ import annotations

from typing import Any

from async_gpib import AsyncGpib

from devices.connections.base import Connection


class GpibConnection(Connection):
    """
    A GPIB connection to an instrument using a Linux-GPIB board.

    GPIB ends each message with the EOI line, so a read returns one message and strips the read terminator, if the
    instrument sends one. The timeout is managed by Linux-GPIB, so the per-call timeouts of `read()`, `write()` and
    `query()` have no effect.

    Parameters
    ----------
    name: int or str
        The board index (e.g. 0) or the board name from the Linux-GPIB configuration (e.g. "gpib0")
    pad: int
        The primary GPIB address of the instrument
    timeout: float or None
        The timeout in seconds. None disables the timeout.
    **kwargs
        Passed to `AsyncGpib`, for example the secondary address `sad`.
    """

    @property
    def is_connected(self) -> bool:
        return self.__device.is_connected

    def __init__(self, name: int | str, pad: int, timeout: float | None = 10, **kwargs: Any) -> None:
        super().__init__(timeout=0 if timeout is None else timeout)
        self.__name = name
        self.__pad = pad
        self.__device = AsyncGpib(name=name, pad=pad, timeout=timeout, **kwargs)

    def __str__(self) -> str:
        return f"GPIB board {self.__name}, address {self.__pad}"

    async def serial_poll(self) -> int:
        """Read the status byte of the instrument."""
        return await self.__device.serial_poll()

    async def wait(self, eventmask: int) -> None:
        """Wait for one of the GPIB events in the mask, like RQS."""
        await self.__device.wait(eventmask)

    async def _connect(self) -> None:
        await self.__device.connect()

    async def _disconnect(self) -> None:
        await self.__device.disconnect()

    async def _write(self, data: bytes, timeout: float) -> None:
        await self.__device.write(data)

    async def _read_until(self, terminator: bytes, timeout: float) -> bytes:
        # Reads until EOI
        return await self.__device.read()

    async def _read_exactly(self, length: int, timeout: float) -> bytes:
        return await self.__device.read(length)
