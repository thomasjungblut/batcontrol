""" Configuration of the web API

Parses the `api:` block of the batcontrol configuration. Home Assistant form
fields may deliver strings for booleans and integers, so every value goes
through an explicit conversion.
"""
import dataclasses
import logging
import secrets

from ..value_utils import parse_bool_flag

logger = logging.getLogger(__name__)

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 2187

# Path prefixes served by the application
API_PREFIX = '/api/v1'

# Bind addresses that mean "this machine only": no warning about an
# unauthenticated bind for these.
LOOPBACK_HOSTS = ('127.0.0.1', 'localhost', '::1', '[::1]')


def token_matches(presented, expected: str) -> bool:
    """ Constant-time comparison of a presented bearer token.

    Compares **bytes**, not strings, on purpose: ``secrets.compare_digest``
    raises ``TypeError`` for a string containing non-ASCII characters, so a
    request with ``Authorization: Bearer <umlaut>`` would come back as a 500
    with a traceback instead of a plain 401. It fails closed either way, but
    an authentication check must reject, not crash.

    ``presented`` may be raw header bytes (the ASGI path) or the string
    Starlette decoded from them, which is latin-1 and round-trips exactly.
    """
    if not presented or not expected:
        return False
    if isinstance(presented, str):
        presented = presented.encode('latin-1', 'replace')
    return secrets.compare_digest(presented, expected.encode('utf-8'))


@dataclasses.dataclass(frozen=True)
class ApiConfig:
    """ Validated `api:` configuration block.

    An empty auth_token means no authentication at all - there is
    deliberately no half protected state.
    """
    enabled: bool = False
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    dashboard_enabled: bool = True
    # Swagger UI (/docs) and the OpenAPI schema (/openapi.json).
    docs_enabled: bool = False
    auth_token: str = ''

    @property
    def auth_enabled(self) -> bool:
        """ True when the API requires a bearer token. """
        return bool(self.auth_token)

    def describe(self) -> str:
        """ One line summary for the startup log. Never includes a token. """
        return (
            f'http://{f"[{self.host}]" if ":" in self.host else self.host}'
            f':{self.port}'
            f' (dashboard: {"on" if self.dashboard_enabled else "off"},'
            f' docs: {"on" if self.docs_enabled else "off"},'
            f' auth: {"on" if self.auth_enabled else "off"})'
        )


def _unset(value) -> bool:
    """ True for a value that means "not configured".

    Home Assistant submits an empty string for an optional form field that
    was left blank, and a commented-out YAML key arrives as None. Both mean
    the same thing: use the default. Treating the empty string as a *value*
    turned a blank field into a startup failure.
    """
    return value is None or (isinstance(value, str) and not value.strip())


def _as_bool(value, key: str, default: bool) -> bool:
    if _unset(value):
        return default
    try:
        return parse_bool_flag(value)
    except ValueError as exc:
        raise ValueError(f'api.{key} must be true or false, got {value!r}') from exc


def _as_port(value) -> int:
    if _unset(value):
        return DEFAULT_PORT
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'api.port must be a number, got {value!r}') from exc
    if not 1 <= port <= 65535:
        raise ValueError(f'api.port must be between 1 and 65535, got {port}')
    return port


def _as_host(value) -> str:
    if _unset(value):
        return DEFAULT_HOST
    host = str(value).strip()
    # '[::1]' is URL notation; uvicorn needs the bare address to bind it.
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]
    return host


def from_config(configdict: dict) -> ApiConfig:
    """ Build an ApiConfig from the batcontrol configuration dictionary.

    A missing `api:` block yields a disabled API, which is the default for
    every existing installation.
    """
    section = configdict.get('api') or {}
    if not isinstance(section, dict):
        raise ValueError(
            f'api must be a configuration block, got {type(section).__name__}')

    config = ApiConfig(
        enabled=_as_bool(section.get('enabled'), 'enabled', False),
        host=_as_host(section.get('host')),
        port=_as_port(section.get('port')),
        dashboard_enabled=_as_bool(
            section.get('dashboard_enabled'), 'dashboard_enabled', True),
        docs_enabled=_as_bool(
            section.get('docs_enabled'), 'docs_enabled', False),
        auth_token=str(section.get('auth_token') or '').strip(),
    )

    if config.enabled and config.host not in LOOPBACK_HOSTS \
            and not config.auth_enabled:
        logger.warning(
            'API is bound to %s without an auth_token. Anyone on that'
            ' network can read your battery and price data and start a'
            ' manual charge. Set api.auth_token or put a reverse proxy in'
            ' front of it.', config.host
        )

    return config
