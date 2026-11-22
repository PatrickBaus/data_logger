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
"""A serial connection, used by the instruments with an RS-232 or USB serial port."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import serial.tools.list_ports
import serial_asyncio

from devices.connections.base import Connection


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


class SerialConnection(Connection):
    """
    A serial connection to an instrument.

    If a VID/PID is given, the tty is looked up on every connection attempt, so the device is found again if it was
    unplugged and re-enumerated under a different name.

    Parameters
    ----------
    tty: str or None
        The device path like "/dev/ttyUSB0". Either `tty` or `vid_pid` is required.
    vid_pid: tuple of int or None
        The USB vendor and product id of the serial adapter
    serial_number: str or None
        The serial number of the USB serial adapter. Use it to tell apart several adapters with the same VID/PID.
    timeout: float or None
        The default timeout in seconds. None uses 0.1 s.
    **kwargs
        Passed to `serial_asyncio.open_serial_connection()`, for example the `baudrate`.
    """

    @property
    def is_connected(self) -> bool:
        return self.__writer is not None and not self.__writer.is_closing()

    def __init__(
        self,
        tty: str | None = None,
        vid_pid: tuple[int, int] | None = None,
        serial_number: str | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> None:
        if tty is None and vid_pid is None:
            raise ValueError("Either supply a tty string or a VID/PID tuple.")
        super().__init__(timeout=0.1 if timeout is None else timeout)
        self.__tty = tty
        self.__device_id = (vid_pid, serial_number)
        self.__kwargs = kwargs
        self.__reader: asyncio.StreamReader | None = None
        self.__writer: asyncio.StreamWriter | None = None
        self.__logger = logging.getLogger(__name__)

    def __str__(self) -> str:
        # If the port is configured by its VID/PID, the tty is unknown until a matching device is found. Describe it by
        # the VID/PID and the serial number and add the tty, once known.
        vid_pid, serial_number = self.__device_id
        if vid_pid is None:
            return str(self.__tty)
        description = f"VID:PID {vid_pid[0]:04x}:{vid_pid[1]:04x}"
        if serial_number is not None:
            description += f", serial number {serial_number}"
        if self.__tty is not None:
            description += f" ({self.__tty})"
        return description

    async def _connect(self) -> None:
        """
        Raises
        ------
        ConnectionError
            If no device with the configured VID/PID is attached
        """
        vid_pid, serial_number = self.__device_id
        if vid_pid is not None:
            self.__tty = find_device_by_vid(*vid_pid, serial_number=serial_number)
            if self.__tty is None:
                raise ConnectionError(f"No serial device found with {self}.")
        self.__reader, self.__writer = await asyncio.wait_for(
            serial_asyncio.open_serial_connection(url=self.__tty, **self.__kwargs), timeout=self.timeout
        )
        self.__writer.transport.serial.reset_input_buffer()  # type: ignore[union-attr]
        self.__logger.info("Serial connection established to %s", self)

    async def _disconnect(self) -> None:
        assert self.__writer is not None
        try:
            try:
                self.__writer.close()
                await self.__writer.wait_closed()
            except ConnectionResetError:
                pass  # We are no longer connected, so we can ignore it
        finally:
            # We guarantee, that the connection is removed
            self.__writer, self.__reader = None, None
            self.__logger.info("Serial connection disconnected from %s", self)

    async def _write(self, data: bytes, timeout: float) -> None:
        assert self.__writer is not None
        self.__writer.write(data)
        await asyncio.wait_for(self.__writer.drain(), timeout=timeout)

    async def _read_until(self, terminator: bytes, timeout: float) -> bytes:
        assert self.__reader is not None
        return await self.__read(self.__reader.readuntil(terminator), timeout)

    async def _read_exactly(self, length: int, timeout: float) -> bytes:
        assert self.__reader is not None
        return await self.__read(self.__reader.readexactly(length), timeout)

    async def __read(self, coro: Any, timeout: float) -> bytes:
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.IncompleteReadError as exc:
            raise ConnectionError(f"Serial connection to {self} closed.") from exc
