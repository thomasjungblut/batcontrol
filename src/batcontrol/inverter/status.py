""" What the inverter actually reports: its programmed rules and live power.

Read once per control cycle, after the mode was set, so the dashboard can
show whether the inverter does what the plan says. Power values in W with
one sign convention: battery_power_w > 0 charges the battery,
grid_power_w > 0 imports from the grid, load_power_w > 0 is consumption.
"""
import dataclasses
from typing import Optional, Tuple


@dataclasses.dataclass(frozen=True)
class InverterRule:
    """ One time-of-use entry as programmed on the inverter. """
    schedule_type: str      # CHARGE_MIN, CHARGE_MAX, DISCHARGE_MIN, DISCHARGE_MAX
    power_w: float
    start: str              # "HH:MM", inverter local time
    end: str
    active: bool


@dataclasses.dataclass(frozen=True)
class InverterStatus:  # pylint: disable=too-many-instance-attributes
    """ One reading of rules and power flow. """
    read_at: float                          # epoch seconds
    rules: Tuple[InverterRule, ...]
    battery_mode: Optional[str] = None      # e.g. "normal", "charge boost"
    battery_standby: Optional[bool] = None
    battery_power_w: Optional[float] = None
    grid_power_w: Optional[float] = None
    load_power_w: Optional[float] = None
    pv_power_w: Optional[float] = None

    def active_rules(self, schedule_type: str):
        """ The active rules of one type. """
        return [r for r in self.rules if r.active and r.schedule_type == schedule_type]
