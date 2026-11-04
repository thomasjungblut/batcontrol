""" Tibber 15-minute prices.

Fetches today's and tomorrow's QUARTER_HOURLY prices (total price incl.
taxes and fees, EUR/kWh) and returns them as absolute-time slots. Tomorrow's
prices are published around 13:00, so the client refetches every
`refresh_seconds`, and more often while tomorrow is still missing in the
afternoon. A failed fetch keeps the last good data.
"""
import datetime
import logging
import threading
import time
from typing import List, Optional

import requests

from .rules import Slot

logger = logging.getLogger(__name__)

URL = 'https://api.tibber.com/v1-beta/gql'
QUERY = """{ viewer { homes { currentSubscription { priceInfo(resolution: QUARTER_HOURLY) {
  today { total startsAt }
  tomorrow { total startsAt }
} } } } }"""

DEFAULT_REFRESH_SECONDS = 3600
# While tomorrow is missing after this hour, retry more often.
TOMORROW_EXPECTED_HOUR = 13
TOMORROW_RETRY_SECONDS = 600


def parse_prices(raw: dict, home: int = 0) -> List[Slot]:
    """ Turn a Tibber GraphQL response into sorted slots. """
    try:
        info = raw['data']['viewer']['homes'][home]['currentSubscription']['priceInfo']
    except (KeyError, IndexError, TypeError) as exc:
        errors = raw.get('errors') if isinstance(raw, dict) else None
        raise ValueError(f'Unexpected Tibber response: {errors or exc}') from exc
    slots = []
    for day in ('today', 'tomorrow'):
        for item in info.get(day) or []:
            if item.get('total') is None:
                continue
            slots.append(Slot(
                start=datetime.datetime.fromisoformat(item['startsAt']),
                price=float(item['total']),
            ))
    slots.sort(key=lambda s: s.start)
    return slots


class TibberPrices:
    """ Cached access to the Tibber price API. """

    def __init__(self, token: str, timezone,
                 refresh_seconds: int = DEFAULT_REFRESH_SECONDS,
                 session=None):
        if not token:
            raise ValueError('utility.api_token is required for Tibber')
        self._token = token
        self._timezone = timezone
        self._refresh_seconds = refresh_seconds
        self._session = session or requests.Session()
        self._slots: List[Slot] = []
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    @property
    def fetched_at(self) -> float:
        """ Epoch seconds of the last successful fetch, 0 if none. """
        return self._fetched_at

    def _fetch(self) -> List[Slot]:
        response = self._session.post(
            URL,
            json={'query': QUERY},
            headers={'Authorization': f'Bearer {self._token}'},
            timeout=30,
        )
        response.raise_for_status()
        return parse_prices(response.json())

    def _due(self, now: datetime.datetime) -> bool:
        age = time.time() - self._fetched_at
        if not self._slots or age >= self._refresh_seconds:
            return True
        if now.hour >= TOMORROW_EXPECTED_HOUR and age >= TOMORROW_RETRY_SECONDS:
            tomorrow = (now + datetime.timedelta(days=1)).date()
            return not any(s.start.astimezone(self._timezone).date() == tomorrow
                           for s in self._slots)
        return False

    def get_slots(self, now: Optional[datetime.datetime] = None) -> List[Slot]:
        """ Current and future slots, refreshed when due. """
        now = now or datetime.datetime.now(self._timezone)
        with self._lock:
            if self._due(now):
                try:
                    self._slots = self._fetch()
                    self._fetched_at = time.time()
                    logger.info('Tibber: %d price slots, until %s', len(self._slots),
                                self._slots[-1].end.isoformat() if self._slots else '-')
                except (requests.RequestException, ValueError) as exc:
                    # Never log the token; the exception text does not carry it.
                    logger.error('Tibber: fetching prices failed (%s), keeping %d '
                                 'cached slots', exc, len(self._slots))
            return [s for s in self._slots if s.end > now]
