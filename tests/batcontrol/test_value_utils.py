"""Tests for value parsing helpers in value_utils."""
import pytest

from batcontrol.value_utils import (
    mask_secret,
    mask_sensitive_headers,
    parse_bool_flag,
)


class TestParseBoolFlag:
    """parse_bool_flag() parses config booleans."""

    @pytest.mark.parametrize("payload,expected", [
        ("1", True), ("true", True), ("True", True), ("TRUE", True),
        (" 1 ", True), (" true ", True),
        ("0", False), ("false", False), ("False", False), ("FALSE", False),
        (" 0 ", False), (" false ", False),
    ])
    def test_valid_payloads(self, payload, expected):
        assert parse_bool_flag(payload) is expected

    @pytest.mark.parametrize("payload", ["", "maybe", "2", "yes", "on"])
    def test_invalid_payload_raises(self, payload):
        with pytest.raises(ValueError):
            parse_bool_flag(payload)








class TestMaskSecret:
    """mask_secret() keeps a credential recognisable without logging it.

    Code scanning alert py/clear-text-logging-sensitive-data: the Fronius
    digest Authorization header is derived from the inverter password and was
    logged in full by the auth debug logger.
    """

    def test_keeps_first_and_last_three_characters(self):
        assert mask_secret('eyJhbGciOiJIUzI1NiJ9fQ') == 'eyJ...9fQ'

    def test_recognisable_but_not_reusable(self):
        token = 'A' * 40 + 'xyz'
        masked = mask_secret(token)
        assert masked.startswith('AAA')
        assert masked.endswith('xyz')
        assert token not in masked
        assert len(masked) == 9

    @pytest.mark.parametrize("secret", ['', None])
    def test_unset_and_empty(self, secret):
        assert mask_secret(secret) in ('<unset>', '<empty>')

    @pytest.mark.parametrize("secret", ['a', 'ab', 'abc', 'abcdef'])
    def test_short_secrets_are_masked_completely(self, secret):
        """Keeping both ends of a short secret would give it away"""
        masked = mask_secret(secret)
        assert masked == '*' * len(secret)
        assert secret not in masked

    def test_keep_is_configurable(self):
        assert mask_secret('0123456789', keep=2) == '01...89'

    def test_non_string_values(self):
        assert mask_secret(1234567890) == '123...890'


class TestMaskSensitiveHeaders:
    """Only credential headers are shortened, the rest stays readable"""

    def test_authorization_is_masked(self):
        digest = ('Digest username="customer", realm="Webinterface area", '
                  'nonce="abc", response="0123456789abcdef"')

        masked = mask_sensitive_headers({'Authorization': digest})

        assert masked['Authorization'] == 'Dig...ef"'
        assert 'response="0123456789abcdef"' not in masked['Authorization']

    def test_other_headers_are_untouched(self):
        headers = {'Content-Type': 'application/json', 'Accept': '*/*'}

        assert mask_sensitive_headers(headers) == headers

    @pytest.mark.parametrize("name", [
        'Authorization', 'authorization', 'AUTHORIZATION',
        'Proxy-Authorization', 'Cookie', 'Set-Cookie', 'X-Api-Key',
        'api-key', 'X-Auth-Token', 'x-access-token',
    ])
    def test_sensitive_header_names(self, name):
        masked = mask_sensitive_headers({name: 'secretvalue123'})
        assert masked[name] == 'sec...123'

    def test_original_mapping_is_not_modified(self):
        headers = {'Authorization': 'secretvalue123'}

        mask_sensitive_headers(headers)

        assert headers['Authorization'] == 'secretvalue123'

    @pytest.mark.parametrize("headers", [None, {}])
    def test_empty_headers(self, headers):
        assert mask_sensitive_headers(headers) == {}


