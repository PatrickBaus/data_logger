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
"""A TCP connection, used by the instruments with an Ethernet port (SCPI or TSP over a raw socket)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from devices.connections.base import Connection


class EthernetConnection(Connection):
    """
    A TCP connection to an instrument.

    Parameters
    ----------
    host: str
        The hostname or IP address of the instrument
    port: int
        The TCP port, for example 5025 for SCPI
    timeout: float or None
        The default timeout in seconds. None uses 0.1 s.
    **kwargs
        Passed to `asyncio.open_connection()`
    """

    @property
    def is_connected(self) -> bool:
        return self.__writer is not None and not self.__writer.is_closing()

    def __init__(self, host: str, port: int, timeout: float | None = None, **kwargs: Any) -> None:
        super().__init__(timeout=0.1 if timeout is None else timeout)
        self.__host = host, port
        self.__kwargs = kwargs
        self.__reader: asyncio.StreamReader | None = None
        self.__writer: asyncio.StreamWriter | None = None
        self.__logger = logging.getLogger(__name__)

    def __str__(self) -> str:
        return f"{self.__host[0]}:{self.__host[1]}"

    async def _connect(self) -> None:
        host, port = self.__host
        self.__reader, self.__writer = await asyncio.wait_for(
            asyncio.open_connection(host=host, port=port, **self.__kwargs), timeout=self.timeout
        )
        self.__logger.info("Ethernet connection established to %s", self)

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
            self.__logger.info("Ethernet connection disconnected from %s", self)

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
            # The remote end closed the connection (EOF). Report it as a connection error, so the caller reconnects.
            raise ConnectionError(f"Connection to {self} closed by the remote end.") from exc
