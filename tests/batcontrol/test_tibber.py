"""The Tibber 15-minute price client."""
import datetime
from unittest.mock import MagicMock

import pytest
import pytz
import requests

from batcontrol.tibber import QUERY, TibberPrices, parse_prices

TZ = pytz.timezone('Europe/Berlin')


def response(today, tomorrow=None):
    return {'data': {'viewer': {'homes': [{'currentSubscription': {'priceInfo': {
        'today': today, 'tomorrow': tomorrow or []}}}]}}}


def quarter(hour, minute, price, day=4):
    return {'startsAt': f'2026-11-{day:02d}T{hour:02d}:{minute:02d}:00.000+01:00',
            'total': price}


def session_returning(*payloads):
    session = MagicMock()
    replies = []
    for payload in payloads:
        if isinstance(payload, Exception):
            replies.append(payload)
        else:
            reply = MagicMock()
            reply.json.return_value = payload
            replies.append(reply)
    session.post.side_effect = replies
    return session


def test_parse_keeps_15_minute_slots_in_order():
    raw = response([quarter(10, 15, 0.31), quarter(10, 0, 0.30)],
                   [quarter(0, 0, 0.2, day=5)])
    slots = parse_prices(raw)
    assert [s.price for s in slots] == [0.30, 0.31, 0.2]
    assert slots[0].end - slots[0].start == datetime.timedelta(minutes=15)


def test_parse_rejects_an_error_response():
    with pytest.raises(ValueError, match='invalid token'):
        parse_prices({'errors': [{'message': 'invalid token'}]})


def test_the_query_asks_for_quarter_hours():
    assert 'QUARTER_HOURLY' in QUERY


def test_get_slots_drops_the_past_and_caches():
    session = session_returning(response([quarter(10, 0, 0.3), quarter(10, 15, 0.31)]))
    prices = TibberPrices('token', TZ, session=session)
    now = TZ.localize(datetime.datetime(2026, 11, 4, 10, 20))
    assert [s.price for s in prices.get_slots(now)] == [0.31]
    assert [s.price for s in prices.get_slots(now)] == [0.31]
    assert session.post.call_count == 1
    headers = session.post.call_args.kwargs['headers']
    assert headers['Authorization'] == 'Bearer token'


def test_a_failed_refresh_keeps_the_last_prices(monkeypatch):
    session = session_returning(response([quarter(11, 0, 0.3)]),
                                requests.ConnectionError('down'))
    prices = TibberPrices('token', TZ, refresh_seconds=0, session=session)
    now = TZ.localize(datetime.datetime(2026, 11, 4, 10, 0))
    assert len(prices.get_slots(now)) == 1
    assert len(prices.get_slots(now)) == 1
    assert session.post.call_count == 2


def test_refetches_in_the_afternoon_until_tomorrow_arrives(monkeypatch):
    session = session_returning(response([quarter(14, 0, 0.3)]),
                                response([quarter(14, 0, 0.3)], [quarter(0, 0, 0.2, day=5)]))
    prices = TibberPrices('token', TZ, session=session)
    now = TZ.localize(datetime.datetime(2026, 11, 4, 13, 30))
    prices.get_slots(now)
    clock = {'t': prices.fetched_at + 700}
    monkeypatch.setattr('batcontrol.tibber.time.time', lambda: clock['t'])
    assert len(prices.get_slots(now)) == 2
    assert session.post.call_count == 2


def test_a_token_is_required():
    with pytest.raises(ValueError):
        TibberPrices('', TZ)
