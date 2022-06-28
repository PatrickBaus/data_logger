from __future__ import annotations

import asyncio
import datetime
import logging
from types import TracebackType
from typing import Type

import asyncio_mqtt
import simplejson as json

from logger.logger import DataEvent


class Mqttwriter:
    @classmethod
    @property
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "mqtt"

    def __init__(self, host: str, port: int, number_of_workers: int = 5) -> None:
        self.__host = str(host)
        self.__port = int(port)
        self.__number_of_workers = int(number_of_workers)
        self.__write_queue: asyncio.Queue[DataEvent] = asyncio.Queue()
        self.__running_tasks: set[asyncio.Task] = set()
        self.__logger = logging.getLogger(__name__)

    @staticmethod
    def _convert_to_json(timestamp: datetime.datetime, event: DataEvent):
        payload = {
            'timestamp': timestamp.timestamp(),
            'uuid': str(event.sender),
            'sid': event.sid,
            'value': event.value,
            'unit': event.unit
        }
        return event.topic, json.dumps(payload, use_decimal=True)

    async def _consumer(
            self,
            reconnect_interval: int = 5
    ) -> None:
        """
        Pushes the data from the input queue to the MQTT broker. It will make sure,
        that no data is lost if the MQTT broker disconnects.

        Parameters
        ----------
        reconnect_interval: int, default=5
            The time in seconds to wait between connection attempts.
        """
        has_error = False
        self.__logger.info("Connecting worker to MQTT broker (%s:%i).", self.__host, self.__port)
        item = None
        while "loop not cancelled":
            try:
                async with asyncio_mqtt.Client(hostname=self.__host, port=self.__port) as mqtt_client:
                    while "loop not cancelled":
                        if item is None:
                            # only get new data if we have pushed everything to the broker
                            item = await self.__write_queue.get()
                        try:
                            timestamp, events = item
                            payloads = [self._convert_to_json(timestamp, event) for event in events]
                        except TypeError:
                            self.__logger.exception("Error while serializing DataEvent: %s", item)
                            item = None    # Drop the event
                            self.__write_queue.task_done()
                            # await asyncio.sleep(0.01)
                        else:
                            for topic, payload in payloads:
                                pass
                                #self.__logger.info("Going to publish: %s to %s", payload, topic)
                                await mqtt_client.publish(topic, payload=payload, qos=2)
                            item = None  # Get a new event to publish
                            self.__write_queue.task_done()
                            has_error = False
            except asyncio_mqtt.error.MqttError as exc:
                # Only log an error once
                if not has_error:
                    self.__logger.error("MQTT error: %s. Retrying.", exc)
                await asyncio.sleep(reconnect_interval)
                has_error = True
            except Exception:   # pylint: disable=broad-except
                # Catch all exceptions, log them, then try to restart the worker.
                self.__logger.exception("Error while publishing data to MQTT broker. Reconnecting.")
                await asyncio.sleep(reconnect_interval)

    async def __aenter__(self) -> asyncio.Queue:
        self.__logger.info("Initializing MQTT writer")

        consumers = {asyncio.create_task(self._consumer()) for _ in range(self.__number_of_workers)}
        self.__running_tasks.update(consumers)

        return self.__write_queue

    async def __aexit__(
            self,
            exc_type: Type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None
    ) -> None:
        try:
            await asyncio.wait_for(self.__write_queue.join(), timeout=3)
        except asyncio.TimeoutError:
            self.__logger.error("Timeout while flushing the MQTT writer.")

        # Stop running tasks
        [task.cancel() for task in self.__running_tasks]
        self.__logger.info("MQTT endpoint at '%s:%i' closed.", self.__host, self.__port)
