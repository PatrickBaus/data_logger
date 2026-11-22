"""Tests of the file and MQTT endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import aiomqtt
import pytest
from pydantic import ValidationError

from endpoints import Filewriter, MqttWriter
from endpoints.mqtt import MQTTParams

from .fakes import event

TIMESTAMP = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_filewriter(tmp_path):
    filename = tmp_path / "logs" / "test_{date}.csv"

    async def test():
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


def test_filewriter_write_requires_context():
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
def test_mqtt_hosts(hosts, expected):
    assert MQTTParams(hosts=hosts, username=None, password=None).hosts == expected


@pytest.mark.parametrize("hosts", ["", "bad host", "example.com:70000", []])
def test_mqtt_invalid_hosts(hosts):
    with pytest.raises(ValidationError):
        MQTTParams(hosts=hosts, username=None, password=None)


@pytest.mark.parametrize("topic", ["", "sensors/#", "sensors/+/temperature"])
def test_mqtt_invalid_topics_are_rejected(topic):
    with pytest.raises(ValueError):
        MqttWriter._convert_to_json(TIMESTAMP, event(1, topic=topic))  # pylint: disable=protected-access


class FakeMqttClient:  # pylint: disable=missing-function-docstring
    """Stand-in for aiomqtt.Client."""

    published: list[tuple[str, str]] = []

    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        pass

    async def publish(self, topic: str, payload: str, qos: int) -> None:  # pylint: disable=unused-argument
        self.published.append((topic, payload))


def test_mqtt_invalid_event_does_not_block_the_queue(monkeypatch):
    """An event with an empty topic used to be retried forever and block the worker."""
    FakeMqttClient.published = []
    monkeypatch.setattr(aiomqtt, "Client", FakeMqttClient)

    async def test():
        writer = MqttWriter(hosts="localhost", username=None, password=None, number_of_workers=1)
        async with writer as queue:
            queue.put_nowait((TIMESTAMP, (event(1, topic=""), event(Decimal("2.5"), topic="sensors/a"))))
            queue.put_nowait((TIMESTAMP, (event(3, topic="sensors/b"),)))
            await asyncio.wait_for(queue.join(), timeout=1)

    asyncio.run(test())
    assert [topic for topic, _ in FakeMqttClient.published] == ["sensors/a", "sensors/b"]
    assert '"value": 2.5' in FakeMqttClient.published[0][1]
    assert '"timestamp": 1767323045.0' in FakeMqttClient.published[0][1]
