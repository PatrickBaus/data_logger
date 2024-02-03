from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from types import TracebackType

import aiofiles
from aiofiles.threadpool.text import AsyncTextIOWrapper

from _version import __version__
from logger.logger import DataEvent


class Filewriter:
    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "file"

    def __init__(self, filename: str, descriptor: str) -> None:
        # drop the microseconds
        date = datetime.now(timezone.utc).replace(microsecond=0)
        self.__filename = filename.format(date=date.isoformat("_"))
        self.__file_descriptor = descriptor
        self.__logger = logging.getLogger(__name__)
        self.__filehandle: AsyncTextIOWrapper | None = None
        self.__write_queue: asyncio.Queue[tuple[datetime, tuple[DataEvent, ...]]] = asyncio.Queue()
        self.__running_tasks: set[asyncio.Task] = set()

    async def __aenter__(self) -> asyncio.Queue:
        self.__logger.info("Initializing file writer")
        # Check if the directory exists, else create it, unless there is no directory specified
        if not os.path.exists(os.path.dirname(self.__filename)) and os.path.dirname(self.__filename):
            os.makedirs(os.path.dirname(self.__filename))
        # Open file, buffering=1 means line buffering
        self.__filehandle = await aiofiles.open(self.__filename, mode="a+", buffering=1)
        self.__logger.info("File '%s' opened.", self.__filename)

        # Write header
        await self.__filehandle.write(
            (
                "# This file was generated using the Python data logger"
                f" script v{__version__}.\n"
                "# Check https://github.com/PatrickBaus/data_logger for the latest version.\n"
                f"# {self.__file_descriptor}\n"
            )
        )

        task = asyncio.create_task(self._queue_writer())
        self.__running_tasks.add(task)

        return self.__write_queue

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.__filehandle is not None:
            try:
                await asyncio.wait_for(self.__write_queue.join(), timeout=3)
            except asyncio.TimeoutError:
                self.__logger.error("Timeout while flushing the file writer.")

            # Stop running tasks
            for task in self.__running_tasks:
                task.cancel()
            results = await asyncio.gather(*self.__running_tasks, self.__filehandle.close(), return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    self.__logger.error("Error during shutdown of the file writer", exc_info=result)

            self.__logger.debug("Closing open file handles.")
            try:
                await self.__filehandle.close()
            finally:
                self.__filehandle = None
            self.__logger.info("File '%s' closed.", self.__filename)

    async def write(self, lines):
        for line in lines:
            await self.__filehandle.write(line)

    async def _queue_writer(self) -> None:
        assert self.__filehandle is not None  # Cannot change later as the queue will be joined first
        while "queue not joined":
            try:
                timestamp, items = await self.__write_queue.get()
                await self.__filehandle.write(f"{timestamp},{','.join(map(str, items))}\n")
                self.__write_queue.task_done()
            except Exception:
                self.__write_queue.task_done()
                raise
