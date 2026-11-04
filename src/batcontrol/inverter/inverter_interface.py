""" Interface for inverter backends """

from abc import ABC, abstractmethod


class InverterInterface(ABC):
    """ What the control loop needs from an inverter. """

    @abstractmethod
    def set_mode_force_charge(self, chargerate: float):
        """ Charge the battery from the grid with `chargerate` W. """

    @abstractmethod
    def set_mode_avoid_discharge(self):
        """ Keep the battery from discharging. """

    @abstractmethod
    def set_mode_allow_discharge(self):
        """ Normal operation. """

    @abstractmethod
    def get_capacity(self) -> float:
        """ Gross capacity in Wh. """

    @abstractmethod
    def get_SOC(self) -> float:  # pylint: disable=invalid-name
        """ State of charge in percent. """

    @abstractmethod
    def shutdown(self):
        """ Restore the inverter configuration batcontrol changed. """
