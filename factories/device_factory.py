"""
This file contains the logger factory, that produces loggers using the parameters given by the configurations.
"""

from logger import (
    EE07Logger,
    Fluke1524Logger,
    Fluke1590Logger,
    Keithley2002Logger,
    Keithley2002ScannerLogger,
    KeithleyDMM6500Logger,
    Keysight3458ALogger,
    Keysight34470ALogger,
    LDT5948Logger,
    TinkerforgeLogger,
)

from .generic_factory import DriverFactory

device_factory = DriverFactory()
device_factory.register(cls=TinkerforgeLogger)
device_factory.register(cls=Keysight3458ALogger)
device_factory.register(cls=Keysight34470ALogger)
device_factory.register(cls=Keithley2002Logger)
device_factory.register(cls=Keithley2002ScannerLogger)
device_factory.register(cls=KeithleyDMM6500Logger)
device_factory.register(cls=EE07Logger)
device_factory.register(cls=Fluke1524Logger)
device_factory.register(cls=Fluke1590Logger)
device_factory.register(cls=LDT5948Logger)
