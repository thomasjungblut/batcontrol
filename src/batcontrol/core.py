""" The control loop: read battery and prices, evaluate the rules, set the mode.

One evaluation every few minutes (see __main__.py). The web thread only reads
`self.last` (one immutable object, replaced in one assignment) and can ask
for a manual charge, which wakes the loop up instead of touching the
inverter from a request thread.
"""
import dataclasses
import datetime
import logging
import threading
import time
from typing import List, Optional

import pytz

from . import rules
from .inverter import InverterCommunicationError, create_inverter
from .tibber import TibberPrices

logger = logging.getLogger(__name__)

# Config keys of earlier versions that are accepted and ignored, so an
# existing configuration keeps working unchanged.
IGNORED_SECTIONS = ('consumption_forecast', 'solar_forecast_provider',
                    'pvinstallations', 'mqtt', 'evcc', 'battery_control_expert',
                    'peak_shaving', 'solar_limit', 'dynamic_network_fees')
USED_BATTERY_CONTROL_KEYS = ('min_price_difference', 'min_recharge_amount')

MANUAL_DEFAULT_MINUTES = 60
MANUAL_MAX_MINUTES = 240


@dataclasses.dataclass(frozen=True)
class CycleResult:
    """ Everything one evaluation produced, read by the web API. """
    evaluated_at: float           # epoch seconds
    battery: rules.Battery
    slots: tuple                  # rules.Slot, current and future
    plan: rules.Plan
    error: Optional[str] = None


def settings_from_config(config: dict) -> rules.Settings:
    """ The rule parameters, from the existing config keys. """
    bc = config.get('battery_control') or {}
    inverter = config.get('inverter') or {}
    rate = inverter.get('max_grid_charge_rate', inverter.get('max_charge_rate'))
    if rate is None:
        raise RuntimeError('inverter.max_grid_charge_rate is required')
    return rules.Settings(
        max_charge_rate_w=float(rate),
        min_price_difference=float(bc.get('min_price_difference',
                                          rules.DEFAULT_MIN_PRICE_DIFFERENCE)),
        min_recharge_wh=float(bc.get('min_recharge_amount',
                                     rules.DEFAULT_MIN_RECHARGE_WH)),
    )


def _log_ignored(config: dict) -> None:
    ignored: List[str] = [k for k in IGNORED_SECTIONS if k in config]
    bc = config.get('battery_control') or {}
    ignored += [f'battery_control.{k}' for k in bc
                if k not in USED_BATTERY_CONTROL_KEYS]
    if ignored:
        logger.info('Ignoring config keys that the simple rules do not use: %s',
                    ', '.join(ignored))
    resolution = config.get('time_resolution_minutes', 15)
    if int(resolution) != 15:
        logger.warning('time_resolution_minutes=%s ignored, always using 15 minutes',
                       resolution)


class Batcontrol:  # pylint: disable=too-many-instance-attributes
    """ Owns the inverter, the price source and the last evaluation. """

    def __init__(self, config: dict, *, inverter=None, prices=None):
        self.timezone = pytz.timezone(config.get('timezone', 'Europe/Berlin'))
        _log_ignored(config)
        self.settings = settings_from_config(config)

        utility = config.get('utility') or {}
        if prices is None:
            if str(utility.get('type', '')).lower() != 'tibber':
                raise RuntimeError(
                    f'Unsupported utility type "{utility.get("type")}". '
                    'Only "tibber" is supported.')
            prices = TibberPrices(utility.get('api_token') or utility.get('apikey'),
                                  self.timezone)
        self.prices = prices
        self.inverter = inverter if inverter is not None \
            else create_inverter(config['inverter'])

        self.last: Optional[CycleResult] = None
        self.next_evaluation: Optional[float] = None
        self.wakeup = threading.Event()
        self._lock = threading.Lock()
        self._manual_until: Optional[float] = None
        self._was_charging = False
        self._applied = None

    # --- manual override, called from the web thread -------------------

    @property
    def manual_until(self) -> Optional[float]:
        """ Epoch seconds a manual charge runs until, None if none. """
        with self._lock:
            if self._manual_until is not None and self._manual_until <= time.time():
                self._manual_until = None
            return self._manual_until

    def start_manual_charge(self, minutes: int = MANUAL_DEFAULT_MINUTES) -> float:
        """ Charge at full speed for `minutes`. Returns the end, epoch s. """
        minutes = max(1, min(int(minutes), MANUAL_MAX_MINUTES))
        with self._lock:
            self._manual_until = time.time() + minutes * 60
            until = self._manual_until
        logger.info('Manual charge requested for %d min', minutes)
        self.wakeup.set()
        return until

    def cancel_manual_charge(self) -> None:
        """ Stop a manual charge; the rules take over on the next cycle. """
        with self._lock:
            self._manual_until = None
        logger.info('Manual charge cancelled')
        self.wakeup.set()

    # --- the loop -------------------------------------------------------

    def read_battery(self) -> rules.Battery:
        """ One reading of the inverter. """
        return rules.Battery(
            soc=float(self.inverter.get_SOC()),
            capacity_wh=float(self.inverter.get_capacity()),
            min_soc=float(self.inverter.min_soc),
            max_soc=float(self.inverter.max_soc),
        )

    def evaluate(self, now: datetime.datetime, battery: rules.Battery,
                 slots) -> rules.Plan:
        """ Run the rules with the loop's state. """
        manual = self.manual_until
        return rules.plan(
            now, slots, battery, self.settings,
            was_charging=self._was_charging,
            manual_until=(datetime.datetime.fromtimestamp(manual, self.timezone)
                          if manual else None),
        )

    def apply(self, plan: rules.Plan) -> None:
        """ Tell the inverter what the plan says. """
        if plan.mode == rules.MODE_CHARGE:
            self.inverter.set_mode_force_charge(int(plan.charge_rate_w))
        else:
            self.inverter.set_mode_allow_discharge()
        applied = (plan.mode, plan.charge_rate_w)
        if applied != self._applied:
            logger.info('Mode %s (%s): %s', plan.mode, plan.reason, plan.headline)
            self._applied = applied
        self._was_charging = plan.reason == rules.REASON_NIGHT_RESERVE

    def run(self) -> Optional[CycleResult]:
        """ One evaluation. Skips the cycle when the inverter is unreachable. """
        now = datetime.datetime.now(self.timezone)
        try:
            battery = self.read_battery()
        except InverterCommunicationError as exc:
            logger.warning('Skipping cycle, inverter unreachable: %s', exc)
            return None
        slots = self.prices.get_slots(now)
        plan = self.evaluate(now, battery, slots)
        for note in plan.notes:
            logger.info('Note: %s', note)
        try:
            self.apply(plan)
        except InverterCommunicationError as exc:
            logger.warning('Could not set inverter mode: %s', exc)
            return None
        result = CycleResult(
            evaluated_at=time.time(),
            battery=battery,
            slots=tuple(slots),
            plan=plan,
        )
        self.last = result
        return result

    def shutdown(self) -> None:
        """ Restore the inverter configuration. """
        try:
            self.inverter.shutdown()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error('Inverter shutdown failed: %s', exc)
