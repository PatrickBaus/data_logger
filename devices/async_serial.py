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
"""An asyncio serial connection used by the serial (RS-232/USB) instruments."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import serial.tools.list_ports
import serial_asyncio


def find_device_by_vid(vid: int, pid: int, serial_number: str | None = None) -> str | None:
    """
    Look up the tty of a USB serial adapter.

    Parameters
    ----------
    vid: int
        The USB vendor id
    pid: int
        The USB product id
    serial_number: str or None
        The serial number of the adapter. Use it to tell apart several adapters with the same VID/PID.

    Returns
    -------
    str or None
        The device path like "/dev/ttyUSB0" or None if no matching device was found.
    """
    for port in serial.tools.list_ports.comports():
        if port.vid == vid and port.pid == pid:
            if serial_number is not None and serial_number != port.serial_number:
                continue
            return port.device
    return None


class AsyncSerial:  # pylint: disable=too-many-instance-attributes
    """
    A line based serial connection. Reads return decoded strings including the separator, writes take strings.

    If a VID/PID is given, the tty is looked up on every connection attempt, so the device is found again if it was
    unplugged and re-enumerated under a different name.
    """

    @property
    def separator(self) -> bytes:
        """The line separator used by `read()`."""
        return self.__separator

    @separator.setter
    def separator(self, value: bytes) -> None:
        self.__separator = value

    @property
    def is_connected(self) -> bool:
        """True if the connection is open."""
        return self.__writer is not None and not self.__writer.is_closing()

    def __init__(  # pylint: disable=too-many-arguments
        self,
        tty: str | None = None,
        vid_pid: tuple[int, int] | None = None,
        serial_number: str | None = None,
        separator: bytes = b"\n",
        timeout: float | None = None,
        **kwargs: Any,
    ) -> None:
        self.__tty = find_device_by_vid(*vid_pid, serial_number=serial_number) if vid_pid is not None else tty
        if self.__tty is None:
            raise ValueError("Either supply a tty string or a VID/PID tuple.")
        self.__separator = separator
        self.__lock = None
        self.__kwargs = kwargs
        self.__timeout = 0.1 if timeout is None else timeout  # in seconds
        self.__reader: asyncio.StreamReader | None = None
        self.__writer: asyncio.StreamWriter | None = None
        self.__logger = logging.getLogger(__name__)

    def __str__(self) -> str:
        return f"AsyncSerial({self.__tty})"

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
            self.__lock = asyncio.Lock()
            self.__reader, self.__writer = await asyncio.wait_for(
                serial_asyncio.open_serial_connection(url=self.__tty, **self.__kwargs), timeout=self.__timeout
            )

            self.__writer.transport.serial.reset_input_buffer()
            self.__logger.info("Serial connection established to '%s'", self.__tty)

    async def disconnect(self) -> None:
        """Close the connection. The connection is always removed, even if closing fails."""
        if self.is_connected:
            try:
                # self.__reader._transport.close()  # This is (probably) not needed
                try:
                    self.__writer.close()
                    await self.__writer.wait_closed()
                except ConnectionResetError:
                    pass  # We are no longer connected, so we can ignore it
            finally:
                # We guarantee, that the connection is removed
                self.__writer, self.__reader = None, None
                self.__logger.info("Serial connection disconnected from %s", self.__tty)
