"""Small helpers: masking credentials for logs, parsing config booleans.

These helpers are independent of the Batcontrol core and raise ValueError
for values that cannot be interpreted.
"""
# Header names whose value carries a credential and must never be logged
# in full. Lower case, compared case-insensitively.
SENSITIVE_HEADERS = frozenset({
    'authorization',
    'proxy-authorization',
    'cookie',
    'set-cookie',
    'api-key',
    'x-api-key',
    'x-auth-token',
    'x-access-token',
})


def mask_secret(value, keep: int = 3) -> str:
    """Shorten a credential so it can be logged.

    Keeps the first and last ``keep`` characters, which is enough to tell
    two credentials apart or to recognise the configured one, without
    putting the secret itself into the log. Values short enough for the
    remainder to give the secret away are masked completely.

    Args:
        value: The credential, of any type
        keep: Number of characters to keep at each end

    Returns:
        The shortened representation, e.g. 'eyJ...9fQ'
    """
    if value is None:
        return '<unset>'
    text = str(value)
    if not text:
        return '<empty>'
    if len(text) <= keep * 2:
        return '*' * len(text)
    return f'{text[:keep]}...{text[-keep:]}'


def mask_sensitive_headers(headers) -> dict:
    """Copy an HTTP header mapping with every credential value shortened

    Logging a request's headers is useful for debugging, but an
    Authorization header holds a credential - for digest auth a hash of the
    password, which is replayable while the nonce is valid. Only the header
    values in SENSITIVE_HEADERS are shortened, so the remaining headers stay
    readable.
    """
    if not headers:
        return {}
    return {
        key: mask_secret(value) if str(key).lower() in SENSITIVE_HEADERS else value
        for key, value in headers.items()
    }


def parse_bool_flag(value) -> bool:
    """Parse a config boolean: 1/0 or true/false (case-insensitive)."""
    normalized = str(value).strip().lower()
    if normalized in ('1', 'true'):
        return True
    if normalized in ('0', 'false'):
        return False
    raise ValueError(f"Invalid boolean flag payload: {value!r}")
