from typing import Any

from errors import UnknownDriverError


class DriverFactory:
    """
    A logger factory to select the correct driver for given logger config.
    """
    def __init__(self):
        self.__available_drivers = {}

    def register(self, cls: Any) -> None:
        """
        Register a driver with the factory. Should only be called in this file.

        Parameters
        ----------
        cls: Any
            The driver class to register.
        """
        self.__available_drivers[cls.driver] = cls

    def has(self, driver: str):
        """Returns true if the driver has been registered

        Parameters
        """
        return driver in self.__available_drivers

    def get(self, driver: str, **kwargs: Any) -> Any:
        """
        Look up the driver for a given database entry. Raises a `ValueError` if the driver is not registered.

        Parameters
        ----------
        driver: str
            A string identifying the driver.
        connection: Any
            The host connection

        Returns
        -------
        Any
            A sensor device driver object

        Raises
        ----------
        ValueError
            Raised if the device driver is not registered
        """
        try:
            device = self.__available_drivers[driver]
        except KeyError:
            raise UnknownDriverError(f"No driver available for {driver}") from None
        else:
            return device(**kwargs)
