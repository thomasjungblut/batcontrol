"""Reading rules and power flow back from the Fronius, and the rule compare."""
import time
from unittest.mock import MagicMock

from cachetools import TTLCache

from batcontrol.inverter.fronius import FroniusWR

# Shape of a real GEN24 reply (firmware 1.3x, BYD at min SoC, waking up).
POWERFLOW = {
    'Inverters': {'1': {'Battery_Mode': 'charge boost', 'SOC': 6.2, 'P': -93.1}},
    'Site': {'BatteryStandby': True, 'P_Akku': -2194.0, 'P_Grid': 3562.0,
             'P_Load': -1295.0, 'P_PV': None},
}
CHARGE_RULE = {'Active': True, 'Power': 3800, 'ScheduleType': 'CHARGE_MIN',
               'TimeTable': {'Start': '00:00', 'End': '23:59'},
               'Weekdays': {d: True for d in ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')}}


def bare_inverter():
    """A FroniusWR without the constructor, which talks to the device."""
    wr = object.__new__(FroniusWR)
    wr.inverter_id = '1'
    wr._time_of_use_cache = TTLCache(maxsize=1, ttl=170)
    wr._soc_cache = TTLCache(maxsize=1, ttl=30)
    wr._powerflow = (time.time(), POWERFLOW)
    return wr


def test_read_status_converts_fronius_signs():
    wr = bare_inverter()
    wr.get_time_of_use = MagicMock(return_value=[CHARGE_RULE])
    status = wr.read_status()
    (rule,) = status.rules
    assert (rule.schedule_type, rule.power_w, rule.start, rule.end, rule.active) == \
        ('CHARGE_MIN', 3800, '00:00', '23:59', True)
    assert status.battery_power_w == 2194      # charging is positive
    assert status.load_power_w == 1295
    assert status.grid_power_w == 3562         # import is positive
    assert status.pv_power_w is None
    assert status.battery_mode == 'charge boost'
    assert status.battery_standby is True


def test_no_rules_means_normal_operation():
    wr = bare_inverter()
    wr.get_time_of_use = MagicMock(return_value=[])
    assert wr.read_status().rules == ()


def test_a_disabled_rule_is_rewritten():
    """Regression: the compare ignored Active, so a rule switched off in the
    Fronius UI was never written again while batcontrol reported charging."""
    wr = bare_inverter()
    disabled = {**CHARGE_RULE, 'Active': False}
    assert not wr._compare_timeofuse_essentials([disabled], [CHARGE_RULE])


def test_a_changed_window_is_rewritten():
    wr = bare_inverter()
    short = {**CHARGE_RULE, 'TimeTable': {'Start': '00:00', 'End': '06:00'}}
    assert not wr._compare_timeofuse_essentials([short], [CHARGE_RULE])


def test_identical_rules_skip_the_write():
    wr = bare_inverter()
    with_meta = {**CHARGE_RULE, 'TimeTable': {**CHARGE_RULE['TimeTable'], '_End_meta': {}}}
    assert wr._compare_timeofuse_essentials([with_meta], [CHARGE_RULE])
