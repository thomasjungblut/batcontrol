""" Common properties of an inverter backend """
from .inverter_interface import InverterInterface

DEFAULT_MIN_SOC = 5
DEFAULT_MAX_SOC = 100


class InverterBaseclass(InverterInterface):
    """ SoC limits and capacity shared by every backend. """

    def __init__(self, config):
        self.min_soc = -1
        self.max_soc = -1
        self.capacity = -1
        self.inverter_type = config.get('type')
        # Upper limit for PV -> battery charging in W; 0 means no limit.
        self.max_pv_charge_rate = config.get('max_pv_charge_rate', 0)

    def get_capacity(self) -> float:
        """ Gross capacity in Wh. """
        raise NotImplementedError

    def get_SOC(self) -> float:   # pylint: disable=invalid-name
        """ State of charge in percent. """
        raise NotImplementedError

    def shutdown(self):
        """ Nothing to restore by default. """
