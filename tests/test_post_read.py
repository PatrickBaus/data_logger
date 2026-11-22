"""Tests of the post-read commands."""

from __future__ import annotations

import asyncio
import time

import pytest

from errors import ConfigurationError
from logger.logger import LoggingDevice, PostReadCommand, evaluate_delay

from .fakes import UUID_A, FakeConnection


def _post_read(commands: list, rounds: int, pause: float = 0) -> list[list[str]]:
    """Run post_read() several times and return the commands sent in each round."""
    conn = FakeConnection()
    device = LoggingDevice(conn, uuid=UUID_A, post_read_commands=commands)

    async def run():
        sent = []
        for _ in range(rounds):
            before = len(conn.written)
            await device.post_read()
            sent.append(conn.written[before:])
            await asyncio.sleep(pause)
        return sent

    return asyncio.run(run())


@pytest.mark.parametrize(
    "expression, expected",
    [(3600, 3600), (0.5, 0.5), ("60*60*24", 86400), ("1/4", 0.25), ("-(2**3) + 10", 2), (" 7 // 2 % 2 ", 1)],
)
def test_evaluate_delay(expression, expected):
    """Plain numbers from YAML used to fail: eval() only accepts strings."""
    assert evaluate_delay(expression) == expected


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').system('true')", "abs(-1)", "1 +", "1/0", "9**9**9", "'1'", None, True, [1]],
)
def test_evaluate_delay_rejects_code_and_invalid_values(expression):
    with pytest.raises(ConfigurationError):
        evaluate_delay(expression)


def test_plain_string_commands_run_after_every_read():
    """Plain strings, the format before post-read scripts were added, used to crash with an AttributeError."""
    assert _post_read(["*TRG", "INIT"], rounds=2) == [["*TRG", "INIT"], ["*TRG", "INIT"]]


def test_repeat():
    sent = _post_read([{"cmd": "ONCE", "repeat": 1}, {"cmd": "TWICE", "repeat": "2"}, {"cmd": "NEVER", "repeat": 0}], 3)
    assert sent == [["ONCE", "TWICE"], ["TWICE"], []]


def test_delay():
    # The first round runs right away, before the delay of 50 ms. The pause of 60 ms makes the second round late enough.
    sent = _post_read([{"cmd": "LATER", "delay": "1/20", "repeat": 1}, {"cmd": "ALWAYS"}], rounds=3, pause=0.06)
    assert sent == [["ALWAYS"], ["LATER", "ALWAYS"], ["ALWAYS"]]


def test_repeat_count_does_not_modify_the_configuration():
    config = [{"cmd": "ONCE", "repeat": 1}]
    _post_read(config, rounds=2)
    assert config == [{"cmd": "ONCE", "repeat": 1}]


@pytest.mark.parametrize(
    "config",
    [
        {"delay": 5},
        {"cmd": 5},
        {"cmd": "X", "dealy": 5},
        {"cmd": "X", "repeat": "often"},
        {"cmd": "X", "delay": "x"},
        5,
    ],
)
def test_invalid_configuration_is_reported_at_startup(config):
    with pytest.raises(ConfigurationError):
        LoggingDevice(FakeConnection(), uuid=UUID_A, post_read_commands=[config])


def test_post_read_command_from_config():
    assert PostReadCommand.from_config({"cmd": "X", "delay": "60*60"}) == PostReadCommand("X", 3600.0, -1)
    start = time.monotonic()
    with pytest.raises(ConfigurationError):
        evaluate_delay("2**99999")  # rejected without calculating it
    assert time.monotonic() - start < 1
