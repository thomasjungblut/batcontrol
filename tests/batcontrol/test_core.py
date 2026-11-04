"""The control loop: config keys, applying the plan, manual charge."""
from unittest.mock import MagicMock

import pytest

from batcontrol import rules
from batcontrol.core import Batcontrol, settings_from_config
from batcontrol.inverter import InverterCommunicationError

# The user's real config, minus credentials: every key must still load.
CONFIG = {
    'timezone': 'Europe/Berlin',
    'loglevel': 'info',
    'time_resolution_minutes': 15,
    'consumption_forecast': {'type': 'csv', 'csv': {'annual_consumption': 10000}},
    'battery_control': {
        'min_price_difference': 0.05,
        'min_price_difference_rel': 0.10,
        'always_allow_discharge_limit': 0.7,
        'max_charging_from_grid_limit': 0.6,
        'min_grid_charge_soc': 0.35,
        'grid_charge_target_strategy': 'fixed',
        'min_recharge_amount': 500,
    },
    'api': {'enabled': True, 'host': '0.0.0.0', 'port': 2187},
    'inverter': {'type': 'fronius_gen24', 'address': '192.0.2.1', 'user': 'customer',
                 'password': 'x', 'max_grid_charge_rate': 3800},
    'utility': {'type': 'tibber', 'api_token': 'x'},
    'solar_forecast_provider': 'fcsolarapi',
    'pvinstallations': [{'name': 'HausFront', 'kWp': 9900}],
}


def make_inverter(soc=40.0):
    inverter = MagicMock()
    inverter.get_SOC.return_value = soc
    inverter.get_capacity.return_value = 10000
    inverter.min_soc = 5
    inverter.max_soc = 100
    return inverter


@pytest.fixture(name='bc')
def fixture_bc():
    prices = MagicMock()
    prices.get_slots.return_value = []
    return Batcontrol(CONFIG, inverter=make_inverter(), prices=prices)


def test_settings_come_from_the_existing_keys():
    settings = settings_from_config(CONFIG)
    assert settings == rules.Settings(max_charge_rate_w=3800,
                                      min_price_difference=0.05,
                                      min_recharge_wh=500)


def test_unused_keys_are_logged_not_rejected(caplog):
    with caplog.at_level('INFO'):
        Batcontrol(CONFIG, inverter=make_inverter(), prices=MagicMock())
    assert 'pvinstallations' in caplog.text
    assert 'battery_control.max_charging_from_grid_limit' in caplog.text


def test_only_tibber_is_supported():
    config = {**CONFIG, 'utility': {'type': 'awattar'}}
    with pytest.raises(RuntimeError, match='tibber'):
        Batcontrol(config, inverter=make_inverter())


def test_only_the_gen24_is_supported():
    from batcontrol.inverter import create_inverter
    with pytest.raises(RuntimeError, match='fronius_gen24'):
        create_inverter({'type': 'fronius-modbus'})


def test_normal_mode_allows_discharge(bc):
    result = bc.run()
    assert result.plan.mode == rules.MODE_NORMAL
    bc.inverter.set_mode_allow_discharge.assert_called_once()
    bc.inverter.set_mode_force_charge.assert_not_called()
    assert bc.last is result


def test_manual_charge_forces_full_speed_and_can_be_cancelled(bc):
    bc.start_manual_charge(60)
    assert bc.wakeup.is_set()
    bc.run()
    bc.inverter.set_mode_force_charge.assert_called_once_with(3800)
    assert bc.last.plan.reason == rules.REASON_MANUAL

    bc.cancel_manual_charge()
    assert bc.manual_until is None
    bc.run()
    bc.inverter.set_mode_allow_discharge.assert_called_once()


def test_manual_duration_is_clamped(bc):
    import time
    until = bc.start_manual_charge(10_000)
    assert until - time.time() <= 240 * 60 + 1


def test_an_unreachable_inverter_skips_the_cycle(bc):
    bc.inverter.get_SOC.side_effect = InverterCommunicationError('get_SOC')
    assert bc.run() is None
    assert bc.last is None
    bc.inverter.set_mode_allow_discharge.assert_not_called()
