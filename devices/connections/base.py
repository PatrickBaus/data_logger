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
"""
The common interface of all connections to the instruments. The transports only implement the raw I/O, the base class
adds the line terminators, the timeouts and the locking.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from devices.errors import NotConnectedError


class Connection(ABC):
    """
    A connection to an instrument. All data is bytes. `write()` appends the write terminator, `read()` strips the read
    terminator, so the drivers send and receive bare commands and replies.

    Reads, writes and queries are serialized by a lock, so that concurrent queries do not interleave and a read cannot
    take the reply of a running query.

    Parameters
    ----------
    timeout: float
        The default timeout in seconds for reads and writes. Transports, whose library manages the timeout itself,
        ignore it.
    read_terminator: bytes
        The terminator, that ends each reply of the instrument
    write_terminator: bytes
        The terminator appended to each command
    """

    @property
    def timeout(self) -> float:
        """The default timeout in seconds."""
        return self.__timeout

    @property
    def read_terminator(self) -> bytes:
        """The terminator, that ends each reply of the instrument. It is removed by `read()`."""
        return self.__read_terminator

    @read_terminator.setter
    def read_terminator(self, value: bytes) -> None:
        if not value:
            raise ValueError("The read terminator must not be empty.")
        self.__read_terminator = value

    @property
    def write_terminator(self) -> bytes:
        """The terminator appended to each command by `write()`."""
        return self.__write_terminator

    @write_terminator.setter
    def write_terminator(self, value: bytes) -> None:
        self.__write_terminator = value

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True if the connection is open."""

    def __init__(self, timeout: float, read_terminator: bytes = b"\n", write_terminator: bytes = b"\n") -> None:
        self.__timeout = timeout
        self.__read_terminator = b""
        self.read_terminator = read_terminator
        self.__write_terminator = write_terminator
        self.__lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open the connection, unless it is already open."""
        if self.is_connected:
            return
        await self._connect()

    async def disconnect(self) -> None:
        """Close the connection, unless it is already closed."""
        if self.is_connected:
            await self._disconnect()

    async def read(self, length: int | None = None, timeout: float | None = None) -> bytes:
        """
        Read a reply. Waits for a running query to finish, so it cannot take the reply of the query.

        Parameters
        ----------
        length: int or None
            Read exactly `length` bytes of binary data, followed by the read terminator, instead of reading until the
            read terminator.
        timeout: float or None
            The timeout in seconds. None uses the default timeout of the connection.

        Returns
        -------
        bytes
            The reply without the read terminator

        Raises
        ------
        NotConnectedError
            If the connection is not open
        ConnectionError
            If the connection was closed by the other end
        TimeoutError
            If no reply arrived in time
        """
        async with self.__get_lock("read from"):
            return await self.__read(length, timeout)

    async def write(self, data: bytes, timeout: float | None = None) -> None:
        """
        Write a command and append the write terminator. Waits for a running query to finish.

        Raises
        ------
        NotConnectedError
            If the connection is not open
        TimeoutError
            If the data could not be sent in time
        """
        async with self.__get_lock("write to"):
            await self.__write(data, timeout)

    async def query(self, data: bytes, length: int | None = None, timeout: float | None = None) -> bytes:
        """
        Write a command and read the reply. Queries, reads and writes are serialized, so each caller gets the reply to
        its own command. See `read()` and `write()` for the parameters and errors.
        """
        async with self.__get_lock("query"):
            await self.__write(data, timeout)
            return await self.__read(length, timeout)

    def __get_lock(self, action: str) -> asyncio.Lock:
        if not self.is_connected:
            raise NotConnectedError(f"Cannot {action} {self}. Not connected.")
        return self.__lock

    # The private methods do not take the lock, the caller must hold it. asyncio.Lock is not reentrant, so query()
    # cannot call the public methods while holding it.
    async def __read(self, length: int | None, timeout: float | None) -> bytes:
        # Check again, the connection might have been closed while waiting for the lock
        if not self.is_connected:
            raise NotConnectedError(f"Cannot read from {self}. Not connected.")
        timeout = self.__timeout if timeout is None else timeout
        if length is None:
            return (await self._read_until(self.__read_terminator, timeout)).removesuffix(self.__read_terminator)
        data = await self._read_exactly(length + len(self.__read_terminator), timeout)
        return data[:length]

    async def __write(self, data: bytes, timeout: float | None) -> None:
        if not self.is_connected:
            raise NotConnectedError(f"Cannot write to {self}. Not connected.")
        await self._write(data + self.__write_terminator, self.__timeout if timeout is None else timeout)

    # The raw I/O, implemented by the transports
    @abstractmethod
    def __str__(self) -> str:
        """Describe the connection for error and log messages."""

    @abstractmethod
    async def _connect(self) -> None:
        """Open the connection."""

    @abstractmethod
    async def _disconnect(self) -> None:
        """Close the connection. The connection must be removed, even if closing fails."""

    @abstractmethod
    async def _write(self, data: bytes, timeout: float) -> None:
        """Write the data as is."""

    @abstractmethod
    async def _read_until(self, terminator: bytes, timeout: float) -> bytes:
        """
        Read a reply including the terminator. Transports, that receive whole messages, like GPIB, may return a message
        without the terminator.
        """

    @abstractmethod
    async def _read_exactly(self, length: int, timeout: float) -> bytes:
        """Read `length` bytes."""
