"""Fixtures for the web API tests.

The API reads only `last`, `next_evaluation`, `settings` and `manual_until`
from the core and calls the two manual charge methods. The stand-in below
provides exactly those, with a real plan computed by the rules, so a test
fails with an AttributeError if the API starts reading anything else.
"""
import datetime
import time

import pytest
import pytz
from fastapi.testclient import TestClient

from batcontrol import rules
from batcontrol.core import CycleResult, check_inverter
from batcontrol.inverter.status import InverterRule, InverterStatus
from batcontrol.web.app import create_app
from batcontrol.web.config import ApiConfig

TZ = pytz.timezone('Europe/Berlin')

# Every documented path, mapped to a URL that answers with the fixtures.
API_PATHS = {
    '/api/v1/health': '/api/v1/health',
    '/api/v1/status': '/api/v1/status',
    '/api/v1/manual-charge': '/api/v1/manual-charge',
}

# Night prices with a clear morning peak, EUR/kWh per hour.
HOURLY = [0.24, 0.23, 0.22, 0.21, 0.21, 0.23, 0.30, 0.33, 0.31, 0.28, 0.25, 0.24,
          0.23, 0.23, 0.24, 0.26, 0.29, 0.34, 0.35, 0.33, 0.30, 0.28, 0.26, 0.25]


def make_slots(day=datetime.date(2026, 11, 4), days=2, hourly=None):
    """15-minute slots for `days` days starting at midnight of `day`."""
    hourly = hourly or HOURLY
    start = TZ.localize(datetime.datetime.combine(day, datetime.time()))
    slots = []
    for i in range(days * 96):
        when = (start + datetime.timedelta(minutes=15 * i)).astimezone(TZ)
        slots.append(rules.Slot(TZ.normalize(when), hourly[when.hour]))
    return slots


class FakeBatcontrol:
    """The parts of core.Batcontrol the web layer uses."""

    def __init__(self, *, with_data=True, now=None, soc=40.0):
        self.settings = rules.Settings(max_charge_rate_w=3800)
        self.next_evaluation = time.time() + 120
        self.manual_requests = []
        self._manual_until = None
        self.last = None
        if with_data:
            now = now or TZ.localize(datetime.datetime(2026, 11, 4, 22, 7))
            battery = rules.Battery(soc=soc, capacity_wh=10000, min_soc=5, max_soc=100)
            slots = [s for s in make_slots() if s.end > now]
            plan = rules.plan(now, slots, battery, self.settings)
            inverter = InverterStatus(
                read_at=time.time(), rules=(), battery_mode='normal',
                battery_standby=False, battery_power_w=-420.0,
                grid_power_w=0.0, load_power_w=420.0, pv_power_w=0.0)
            self.last = CycleResult(evaluated_at=time.time(), battery=battery,
                                    slots=tuple(slots), plan=plan, inverter=inverter,
                                    inverter_check=check_inverter(plan, inverter))

    @property
    def manual_until(self):
        return self._manual_until

    def start_manual_charge(self, minutes=60):
        self.manual_requests.append(minutes)
        self._manual_until = time.time() + minutes * 60
        return self._manual_until

    def cancel_manual_charge(self):
        self.manual_requests.append('cancel')
        self._manual_until = None


@pytest.fixture(name='fake_bc')
def fixture_fake_bc():
    return FakeBatcontrol()


@pytest.fixture(name='client')
def fixture_client(fake_bc):
    config = ApiConfig(enabled=True, docs_enabled=True)
    with TestClient(create_app(fake_bc, config), base_url='http://127.0.0.1') as client:
        yield client
