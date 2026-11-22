from typing import Any, Generic, Protocol, TypeVar

from errors import UnknownDriverError


class Driver(Protocol):  # pylint: disable=too-few-public-methods
    """A class, that can be created by a factory. Its `driver()` is the name used in the configuration."""

    @classmethod
    def driver(cls) -> str: ...


DriverT = TypeVar("DriverT", bound=Driver)


class DriverFactory(Generic[DriverT]):
    """
    A logger factory to select the correct driver for given logger config.
    """

    def __init__(self) -> None:
        self.__available_drivers: dict[str, type[DriverT]] = {}

    def register(self, cls: type[DriverT]) -> None:
        """
        Register a driver with the factory. Should only be called in this file.

        Parameters
        ----------
        cls: type
            The driver class to register.
        """
        self.__available_drivers[cls.driver()] = cls

    def has(self, driver: str) -> bool:
        """Returns true if the driver has been registered

        Parameters
        """
        return driver in self.__available_drivers

    def get(self, driver: str, **kwargs: Any) -> DriverT:
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
        DriverT
            The object created by the driver

        Raises
        ----------
        ValueError
            Raised if the device driver is not registered
        """
        try:
            device = self.__available_drivers[driver]
        except KeyError:
            raise UnknownDriverError(f"No driver available for {driver}") from None

        return device(**kwargs)
