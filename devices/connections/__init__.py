"""The connections to the instruments. All share the interface of `Connection`."""

from .base import Connection
from .ethernet import EthernetConnection
from .gpib import GpibConnection
from .prologix import PrologixGpibConnection
from .serial import SerialConnection, find_device_by_vid

__all__ = [
    "Connection",
    "EthernetConnection",
    "GpibConnection",
    "PrologixGpibConnection",
    "SerialConnection",
    "find_device_by_vid",
]
