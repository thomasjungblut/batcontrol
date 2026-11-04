"""The API: status view and the manual charge."""
import pytest
from fastapi.testclient import TestClient

from batcontrol.web.app import create_app
from batcontrol.web.config import ApiConfig

from .conftest import API_PATHS, FakeBatcontrol


def test_health(client):
    assert client.get('/api/v1/health').json() == {'ok': True, 'data': {'status': 'ok'}}


def test_status_shows_battery_plan_and_savings(client):
    body = client.get('/api/v1/status').json()
    assert body['ok'] is True
    data = body['data']
    assert data['battery']['soc'] == 40.0
    assert data['battery']['usable_wh'] == 3500.0
    assert data['mode'] == 'normal'
    plan = data['plan']
    assert plan['preview'] is False
    assert plan['deficit_wh'] == pytest.approx(1065, abs=1)
    (charge,) = plan['charges']
    assert charge['reason'] == 'night_reserve'
    assert charge['explanation'].startswith('Charge 03:00-03:30 at 21.0 ct')
    assert plan['saving_eur'] == pytest.approx(charge['saving_eur'])
    assert plan['monthly_saving_eur'] == pytest.approx(plan['saving_eur'] * 30, abs=0.01)


def test_timestamps_are_epoch_ms(client):
    data = client.get('/api/v1/status').json()['data']
    assert data['evaluated_at'] > 10**12
    assert data['plan']['charges'][0]['start'] > 10**12


def test_prices_cover_24_hours_and_mark_charges(client):
    prices = client.get('/api/v1/status').json()['data']['prices']
    assert len(prices) == 97  # the running slot + 24 h
    assert sum(1 for p in prices if p['charge'] == 'night_reserve') == 2


def test_no_data_before_the_first_cycle():
    app = create_app(FakeBatcontrol(with_data=False), ApiConfig(enabled=True))
    with TestClient(app) as client:
        response = client.get('/api/v1/status')
    assert response.status_code == 503
    assert response.json()['error'] == 'no_data'


def test_manual_charge_start_and_cancel(client, fake_bc):
    response = client.post('/api/v1/manual-charge', json={'minutes': 30})
    assert response.status_code == 200
    assert response.json()['data']['active'] is True
    assert fake_bc.manual_requests == [30]
    assert client.get('/api/v1/manual-charge').json()['data']['active'] is True

    response = client.delete('/api/v1/manual-charge')
    assert response.json()['data'] == {'active': False, 'until': None}


def test_manual_charge_defaults_to_one_hour(client, fake_bc):
    client.post('/api/v1/manual-charge')
    assert fake_bc.manual_requests == [60]


@pytest.mark.parametrize('minutes', [0, 241, 'soon'])
def test_manual_charge_rejects_bad_durations(client, fake_bc, minutes):
    assert client.post('/api/v1/manual-charge',
                       json={'minutes': minutes}).status_code == 422
    assert fake_bc.manual_requests == []


def test_documented_paths_match_the_schema(client):
    schema = client.get('/openapi.json').json()
    assert set(schema['paths']) == set(API_PATHS)


def test_every_numeric_field_names_its_unit(client):
    schema = client.get('/openapi.json').json()
    for name, model in schema['components']['schemas'].items():
        for field, spec in model.get('properties', {}).items():
            numeric = spec.get('type') in ('number', 'integer') or any(
                alt.get('type') in ('number', 'integer') for alt in spec.get('anyOf', []))
            if numeric:
                assert spec.get('description'), f'{name}.{field} has no description'


def test_writes_only_on_manual_charge(client):
    schema = client.get('/openapi.json').json()
    for path, ops in schema['paths'].items():
        if set(ops) - {'get'}:
            assert path == '/api/v1/manual-charge'


def test_status_shows_what_the_inverter_reports(client):
    data = client.get('/api/v1/status').json()['data']
    assert data['inverter']['rules'] == []
    assert data['inverter']['battery_power_w'] == -420
    assert data['inverter']['load_power_w'] == 420
    assert data['inverter_check'] is None
