"""Tests of the file and MQTT endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

import aiomqtt
import pytest
from pydantic import ValidationError

from endpoints import Filewriter, MqttWriter
from endpoints.mqtt import MQTTParams

from .fakes import event

TIMESTAMP = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_filewriter(tmp_path: Path) -> None:
    filename = tmp_path / "logs" / "test_{date}.csv"

    async def test() -> None:
        writer = Filewriter(filename=str(filename), descriptor="A test")
        async with writer as queue:
            await writer.write(["# Date,a,b\n"])
            queue.put_nowait((TIMESTAMP, (event(Decimal("1.5")), event(2))))

    asyncio.run(test())
    (path,) = (tmp_path / "logs").iterdir()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[2] == "# A test"
    assert lines[3] == "# Date,a,b"
    assert lines[4] == f"{TIMESTAMP},1.5,2"


def test_filewriter_write_requires_context() -> None:
    with pytest.raises(RuntimeError):
        asyncio.run(Filewriter(filename="unused.csv", descriptor="").write(["foo"]))


@pytest.mark.parametrize(
    "hosts, expected",
    [
        ("example.com", [("example.com", 1883)]),
        ("example1.com:1884, example2.com:0", [("example1.com", 1884), ("example2.com", 1883)]),
        (["example1.com:1884", "10.0.0.1"], [("example1.com", 1884), ("10.0.0.1", 1883)]),  # YAML list
    ],
)
def test_mqtt_hosts(hosts: str | list[str], expected: list[tuple[str, int]]) -> None:
    assert MQTTParams.model_validate({"hosts": hosts, "username": None, "password": None}).hosts == expected


@pytest.mark.parametrize("hosts", ["", "bad host", "example.com:70000", []])
def test_mqtt_invalid_hosts(hosts: str | list[str]) -> None:
    with pytest.raises(ValidationError):
        MQTTParams.model_validate({"hosts": hosts, "username": None, "password": None})


@pytest.mark.parametrize("topic", ["", "sensors/#", "sensors/+/temperature"])
def test_mqtt_invalid_topics_are_rejected(topic: str) -> None:
    with pytest.raises(ValueError):
        MqttWriter._convert_to_json(TIMESTAMP, event(1, topic=topic))  # pylint: disable=protected-access


class FakeMqttClient:  # pylint: disable=missing-function-docstring
    """
    Stand-in for aiomqtt.Client. The errors in `connect_errors` and `publish_errors` are raised by the connection
    attempts and the publications one after another.
    """

    published: list[tuple[str, str]] = []
    hosts: list[tuple[str, int]] = []
    connect_errors: list[BaseException] = []
    publish_errors: list[BaseException] = []

    def __init__(self, hostname: str, port: int, **_kwargs: Any) -> None:
        self.hosts.append((hostname, port))

    async def __aenter__(self) -> Self:
        if self.connect_errors:
            raise self.connect_errors.pop(0)
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass

    async def publish(self, topic: str, payload: str, qos: int) -> None:  # pylint: disable=unused-argument
        if self.publish_errors:
            raise self.publish_errors.pop(0)
        self.published.append((topic, payload))


@pytest.fixture(name="mqtt_client")
def fixture_mqtt_client(monkeypatch: pytest.MonkeyPatch) -> type[FakeMqttClient]:
    FakeMqttClient.published, FakeMqttClient.hosts = [], []
    FakeMqttClient.connect_errors, FakeMqttClient.publish_errors = [], []
    monkeypatch.setattr(aiomqtt, "Client", FakeMqttClient)
    return FakeMqttClient


def test_mqtt_invalid_event_does_not_block_the_queue(mqtt_client: type[FakeMqttClient]) -> None:
    """An event with an empty topic used to be retried forever and block the worker."""

    async def test() -> None:
        writer = MqttWriter(hosts="localhost", username=None, password=None, number_of_workers=1)
        async with writer as queue:
            queue.put_nowait((TIMESTAMP, (event(1, topic=""), event(Decimal("2.5"), topic="sensors/a"))))
            queue.put_nowait((TIMESTAMP, (event(3, topic="sensors/b"),)))
            await asyncio.wait_for(queue.join(), timeout=1)

    asyncio.run(test())
    assert [topic for topic, _ in mqtt_client.published] == ["sensors/a", "sensors/b"]
    assert '"value": 2.5' in mqtt_client.published[0][1]
    assert '"timestamp": 1767323045.0' in mqtt_client.published[0][1]


def test_mqtt_worker_reconnects_after_errors(
    mqtt_client: type[FakeMqttClient], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Each kind of error is logged and the worker reconnects, cycling through the brokers. No data is lost."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def sleep(delay: float) -> None:
        if delay:
            sleeps.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    mqtt_client.connect_errors = [
        aiomqtt.MqttCodeError(5, "Not authorized"),
        aiomqtt.MqttCodeError(5, "Not authorized"),  # The same error is only logged once
        ConnectionRefusedError(),
        aiomqtt.MqttError("[Errno 111] Connection refused"),
        aiomqtt.MqttError("[Errno -3] Temporary failure in name resolution"),
        aiomqtt.MqttError("[Errno 113] No route to host"),
        aiomqtt.MqttError("Operation timed out"),
        RuntimeError("bug"),
    ]
    mqtt_client.publish_errors = [aiomqtt.MqttError("Disconnected during publish")]

    async def test() -> None:
        writer = MqttWriter(hosts="broker1:1883,broker2", username=None, password=None, number_of_workers=1)
        async with writer as queue:
            queue.put_nowait((TIMESTAMP, (event(1, topic="sensors/a"),)))
            await asyncio.wait_for(queue.join(), timeout=5)

    asyncio.run(test())
    # The event survived the failed publish
    assert [topic for topic, _ in mqtt_client.published] == ["sensors/a"]
    assert mqtt_client.hosts[:4] == [("broker1", 1883), ("broker2", 1883), ("broker1", 1883), ("broker2", 1883)]
    assert len(sleeps) == 9  # A delay before each of the 9 reconnects
    messages = [record.getMessage() for record in caplog.records if record.levelname == "ERROR"]
    assert messages[0].startswith("MQTT error:") and messages[1].startswith("Connection refused by MQTT server")
    assert sum(message.startswith("MQTT error:") for message in messages) == 1
    assert "Temporary failure in name resolution of MQTT server (broker1:1883). Retrying." in messages  # 5th attempt
    assert "Error while publishing data to MQTT broker. Reconnecting." in messages
    assert messages.count("MQTT Connection error. Retrying.") == 3  # Errno 113, no errno, the failed publish


async def _join_timeout() -> None:
    raise TimeoutError()


def test_mqtt_flush_timeout_is_logged(mqtt_client: type[FakeMqttClient], caplog: pytest.LogCaptureFixture) -> None:
    """If the broker cannot be reached, the queue is not flushed. The writer gives up after 3 s."""
    mqtt_client.connect_errors = [ConnectionRefusedError()] * 100

    async def test() -> None:
        writer = MqttWriter(hosts="broker", username=None, password=None, number_of_workers=1)
        async with writer as queue:
            queue.put_nowait((TIMESTAMP, (event(1, topic="sensors/a"),)))
            queue.join = _join_timeout  # type: ignore[method-assign]

    asyncio.run(test())
    assert "Timeout while flushing the MQTT writer." in caplog.text


def test_filewriter_exit_without_enter_is_a_no_op(tmp_path: Path) -> None:
    asyncio.run(Filewriter(filename=str(tmp_path / "x.csv"), descriptor="").__aexit__(None, None, None))
    assert not list(tmp_path.iterdir())


def test_filewriter_flush_timeout_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    async def test() -> None:
        async with Filewriter(filename=str(tmp_path / "x.csv"), descriptor="") as queue:
            queue.join = _join_timeout  # type: ignore[method-assign]

    asyncio.run(test())
    assert "Timeout while flushing the file writer." in caplog.text


def test_filewriter_write_error_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """An item, that cannot be written, stops the writer. The error is logged on shutdown."""

    async def test() -> None:
        async with Filewriter(filename=str(tmp_path / "x.csv"), descriptor="") as queue:
            queue.put_nowait((TIMESTAMP, 42))  # type: ignore[arg-type]  # not a tuple of events

    asyncio.run(test())
    assert "Error during shutdown of the file writer" in caplog.text
