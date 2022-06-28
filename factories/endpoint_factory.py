"""
This file contains the logger factory, that produces loggers using the parameters given by the configurations.
"""

from endpoints.filewriter import Filewriter
from endpoints.mqtt import Mqttwriter
from factories.generic_factory import DriverFactory

endpoint_factory = DriverFactory()
endpoint_factory.register(cls=Filewriter)
endpoint_factory.register(cls=Mqttwriter)
