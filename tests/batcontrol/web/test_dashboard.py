"""The static dashboard and the manual charge end to end."""
import pathlib
import re
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from batcontrol import rules
from batcontrol.core import Batcontrol
from batcontrol.web.app import STATIC_DIR, create_app
from batcontrol.web.config import ApiConfig

from ..test_core import CONFIG, make_inverter


def test_the_dashboard_is_served(client):
    page = client.get('/')
    assert page.status_code == 200
    assert 'app.js' in page.text
    for asset in ('app.js', 'style.css', 'favicon.svg', 'manifest.webmanifest'):
        assert client.get(f'/{asset}').status_code == 200, asset


def test_assets_use_relative_urls_and_no_network():
    """Works behind a subpath and without internet egress."""
    for path in pathlib.Path(STATIC_DIR).iterdir():
        if path.suffix not in ('.html', '.js', '.css'):
            continue
        text = path.read_text(encoding='utf-8')
        assert not re.search(r'(src|href)="/', text), path.name
        assert not re.search(r'https?://', text), path.name


def test_the_api_is_not_shadowed_by_the_dashboard(client):
    assert client.get('/api/v1/health').json()['ok'] is True


def test_the_button_charges_through_the_real_core():
    """POST /manual-charge -> next cycle sets force charge at full speed."""
    prices = MagicMock()
    prices.get_slots.return_value = []
    bc = Batcontrol(CONFIG, inverter=make_inverter(soc=90), prices=prices)
    bc.run()
    bc.inverter.set_mode_allow_discharge.assert_called_once()

    with TestClient(create_app(bc, ApiConfig(enabled=True))) as client:
        assert client.post('/api/v1/manual-charge', json={'minutes': 60}).status_code == 200
        assert bc.wakeup.is_set()
        bc.run()
        bc.inverter.set_mode_force_charge.assert_called_once_with(3800)
        status = client.get('/api/v1/status').json()['data']
        assert status['reason'] == rules.REASON_MANUAL
        assert status['manual_until'] is not None

        client.delete('/api/v1/manual-charge')
        bc.run()
        assert client.get('/api/v1/status').json()['data']['mode'] == 'normal'
