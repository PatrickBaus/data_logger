"""
MQTT endpoint to push data to an MQTT broker
"""

from __future__ import annotations

import asyncio
import datetime
import itertools
import logging
import re
from types import TracebackType

import aiomqtt
import simplejson as json
from pydantic import BaseModel, field_validator

from logger.logger import DataEvent

# A regular expression to match a hostname with an optional port.
# It adheres to RFC 1035 (https://www.rfc-editor.org/rfc/rfc1035) and matches ports
# between 0-65535.
HOSTNAME_REGEX = (
    r"^((?=.{1,255}$)[0-9A-Za-z](?:(?:[0-9A-Za-z]|-){0,61}[0-9A-Za-z])?(?:\.[0-9A-Za-z](?:(?:["
    r"0-9A-Za-z]|-){0,61}[0-9A-Za-z])?)*\.?)(?:\:([0-9]{1,4}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{"
    r"2}|655[0-2][0-9]|6553[0-5]))?$"
)


class MQTTParams(BaseModel):
    """
    Parameters used to connect to the MQTT broker.

    Parameters
    ----------
    hosts: List of Tuple of str and int
        A list of host:port tuples. The list contains the servers of a cluster. If no port is provided it defaults to
        1883. If port number 0 is provided the default value of 1883 is used.
    username: str or None
        The username used for authentication. Set to None if no username is required
    password: str or None
        The password used for authentication. Set to None if no username is required
    """

    hosts: list[tuple[str, int]]
    username: str | None
    password: str | None

    @field_validator("hosts", mode="before")
    @classmethod
    def ensure_list_of_hosts(cls, value: str) -> list[tuple[str, int]]:
        """
        Parse
        Parameters
        ----------
        value: str
            Either a single hostname:port string or a comma separated list of hostname:port strings.

        Returns
        -------
        list of tuple of str and int
            A list of (hostname, port) tuples.
        """
        hosts = value.split(",")
        result = []
        for host in hosts:
            host = host.strip()
            match = re.search(HOSTNAME_REGEX, host)
            if match is None:
                raise ValueError(f"'{value}' is not a valid hostname or list of hostnames.")
            result.append(
                (
                    match.group(1),
                    int(match.group(2)) if match.group(2) and not match.group(2) == "0" else 1883,
                )
            )
        return result


class MqttWriter:
    """
    Consumer takes data and writes it to an MQTT broker as JSON dict.
    """

    @classmethod
    def driver(cls) -> str:
        """
        Returns
        -------
        str
            The driver that identifies it to the factory
        """
        return "mqtt"

    def __init__(self, hosts: str, username: str | None, password: str | None, number_of_workers: int = 5) -> None:
        self.__mqtt_params = MQTTParams(
            hosts=hosts,
            username=username,
            password=password,
        )
        self.__number_of_workers = int(number_of_workers)
        self.__write_queue: asyncio.Queue[tuple[datetime.datetime, tuple[DataEvent, ...]]] = asyncio.Queue()
        self.__running_tasks: set[asyncio.Task] = set()
        self.__logger = logging.getLogger(__name__)

    @staticmethod
    def _convert_to_json(timestamp: datetime.datetime, event: DataEvent):
        payload = {
            "timestamp": timestamp.timestamp(),
            "uuid": str(event.sender),
            "sid": event.sid,
            "value": event.value,
            "unit": event.unit,
        }
        return event.topic, json.dumps(payload, use_decimal=True)

    @staticmethod
    def _calculate_timeout(last_reconnect_attempt: float, reconnect_interval: float) -> float:
        """
        Calculates the time to wait between reconnect attempts.
        Parameters
        ----------
        last_reconnect_attempt: A timestamp in seconds
        reconnect_interval: The reconnect interval in seconds

        Returns
        -------
        float
            The number of seconds to wait. This is a number greater than 0.
        """
        return max(
            0.0,
            reconnect_interval - (asyncio.get_running_loop().time() - last_reconnect_attempt),
        )

    async def _consumer(self, reconnect_interval: int = 5) -> None:  # pylint: disable=too-many-branches
        """
        Pushes the data from the input queue to the MQTT broker. It will make sure,
        that no data is lost if the MQTT broker disconnects.

        Parameters
        ----------
        reconnect_interval: int, default=5
            The time in seconds to wait between connection attempts.
        """
        error_code = 0  # 0 = success
        item: tuple[datetime.datetime, tuple[DataEvent, ...]] | None = None
        last_reconnect_attempt = asyncio.get_running_loop().time() - reconnect_interval
        for host in itertools.cycle(self.__mqtt_params.hosts):
            # Wait for at least reconnect_interval before connecting again
            timeout = self._calculate_timeout(last_reconnect_attempt, reconnect_interval)
            if timeout > 0:
                self.__logger.info("Delaying reconnect by %.0f s.", timeout)
            await asyncio.sleep(timeout)
            last_reconnect_attempt = asyncio.get_running_loop().time()
            try:
                self.__logger.info(
                    "Connecting worker to MQTT broker (%s:%i).",
                    *host,
                )
                async with aiomqtt.Client(hostname=host[0], port=host[1]) as mqtt_client:
                    while "queue not done":
                        if item is None:
                            # only get new data if we have pushed everything to the broker
                            item = await self.__write_queue.get()
                        try:
                            timestamp, events = item
                            payloads = [self._convert_to_json(timestamp, event) for event in events]
                        except TypeError:
                            self.__logger.exception("Error while serializing DataEvent: %s.", item)
                            item = None  # Drop the event
                            self.__write_queue.task_done()
                        else:
                            for topic, payload in payloads:
                                # self.__logger.info("Going to publish: %s to %s", payload, topic)
                                await mqtt_client.publish(topic, payload=payload, qos=2)
                            item = None  # Get a new event to publish
                            self.__write_queue.task_done()
                            error_code = 0  # 0 = success
            except aiomqtt.MqttCodeError as exc:
                # Only log an error once
                if error_code != exc.rc:
                    error_code = exc.rc
                    self.__logger.error("MQTT error: %s. Retrying.", exc)
            except ConnectionRefusedError:
                self.__logger.error(
                    "Connection refused by MQTT server (%s:%i). Retrying.",
                    *host,
                )
            except aiomqtt.MqttError as exc:
                error = re.search(r"\[Errno (\d+)]", str(exc))
                if error is not None:
                    error_code = int(error.group(1))
                    if error_code == 111:
                        self.__logger.error(
                            "Connection refused by MQTT server (%s:%i). Retrying.",
                            *host,
                        )
                    elif error_code == -3:
                        self.__logger.error(
                            "Temporary failure in name resolution of MQTT server (%s:%i). Retrying.",
                            *host,
                        )
                    else:
                        self.__logger.exception("MQTT Connection error. Retrying.")
                else:
                    self.__logger.error("MQTT Connection error. Retrying.")
            except Exception:  # pylint: disable=broad-except
                # Catch all exceptions, log them, then try to restart the worker.
                self.__logger.exception("Error while publishing data to MQTT broker. Reconnecting.")

    async def __aenter__(self) -> asyncio.Queue:
        self.__logger.info("Initializing MQTT writer")

        consumers = {asyncio.create_task(self._consumer()) for _ in range(self.__number_of_workers)}
        self.__running_tasks.update(consumers)

        return self.__write_queue

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await asyncio.wait_for(self.__write_queue.join(), timeout=3)
        except asyncio.TimeoutError:
            self.__logger.error("Timeout while flushing the MQTT writer.")

        # Stop running tasks
        for task in self.__running_tasks:
            task.cancel()
        self.__logger.info("MQTT endpoint at '%s' closed.", self.__mqtt_params.hosts)
