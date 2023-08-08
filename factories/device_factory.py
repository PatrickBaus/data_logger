"""
This file contains the logger factory, that produces loggers using the parameters given by the configurations.
"""
from factories.generic_factory import DriverFactory
from logger.logger import EE07Logger, Fluke1524Logger, Fluke1590Logger, Keithley2002Logger, Keithley2002ScannerLogger, \
    KeithleyDMM6500Logger, Keysight34470ALogger, Keysight3458ALogger, LDT5948Logger, \
    TinkerforgeLogger


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
