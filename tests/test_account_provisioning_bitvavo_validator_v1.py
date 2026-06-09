"""
Tests for RealBitvavoCredentialValidator.

All tests mock HTTP transport — broker_private_calls=0 in automated tests.
No real Bitvavo API calls are made.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.account_provisioning.bitvavo_credential_validator_v1 import RealBitvavoCredentialValidator
from src.account_provisioning.contracts_v1 import PlainBitvavoCredential
from src.execution.bitvavo_client import (
    BROKER_PRIVATE_READ_PERMISSION_ENV,
    BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE,
)


_VALID_KEY = "real-api-key-abc"
_VALID_SECRET = "real-api-secret-xyz"
_PERMISSION_GRANTED = BROKER_PRIVATE_READ_PERMISSION_GRANTED_VALUE


def _credential(api_key=_VALID_KEY, api_secret=_VALID_SECRET):
    return PlainBitvavoCredential(venue="bitvavo", api_key=api_key, api_secret=api_secret)


def _mock_response(status_code: int, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or []
    if status_code >= 400:
        from requests.exceptions import HTTPError
        resp.raise_for_status.side_effect = HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Permission guard
# ---------------------------------------------------------------------------

def test_blocked_without_permission_env(monkeypatch=None) -> None:
    import os
    env_backup = os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)
    try:
        result = RealBitvavoCredentialValidator().validate(_credential())
        assert result.success is False
        assert result.safe_error_code == "VALIDATION_UNAVAILABLE"
        assert result.validation_state == "VALIDATION_UNAVAILABLE"
    finally:
        if env_backup is not None:
            os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = env_backup


def test_blocked_with_wrong_permission_value() -> None:
    import os
    old = os.environ.get(BROKER_PRIVATE_READ_PERMISSION_ENV)
    os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = "wrong-value"
    try:
        result = RealBitvavoCredentialValidator().validate(_credential())
        assert result.success is False
        assert result.safe_error_code == "VALIDATION_UNAVAILABLE"
    finally:
        if old is None:
            os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)
        else:
            os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = old


# ---------------------------------------------------------------------------
# Success path (mock HTTP 200)
# ---------------------------------------------------------------------------

def test_valid_credentials_return_valid_private_read() -> None:
    import os
    os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = _PERMISSION_GRANTED
    try:
        balance_resp = _mock_response(200, [{"symbol": "EUR", "available": "100.00", "inOrder": "0"}])
        orders_resp = _mock_response(200, [])
        with patch("requests.get", side_effect=[balance_resp, orders_resp]):
            result = RealBitvavoCredentialValidator().validate(_credential())
        assert result.success is True
        assert result.validation_state == "VALID_PRIVATE_READ"
        assert "read_balance" in result.capabilities
        assert "read_orders" in result.capabilities
    finally:
        os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)


def test_valid_credentials_no_safe_error_code() -> None:
    import os
    os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = _PERMISSION_GRANTED
    try:
        with patch("requests.get", side_effect=[_mock_response(200, []), _mock_response(200, [])]):
            result = RealBitvavoCredentialValidator().validate(_credential())
        assert result.safe_error_code is None
    finally:
        os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)


# ---------------------------------------------------------------------------
# Auth failure (HTTP 401/403)
# ---------------------------------------------------------------------------

def test_http_401_returns_invalid_credentials() -> None:
    import os
    os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = _PERMISSION_GRANTED
    try:
        with patch("requests.get", return_value=_mock_response(401)):
            result = RealBitvavoCredentialValidator().validate(_credential())
        assert result.success is False
        assert result.validation_state == "INVALID_CREDENTIALS"
        assert result.safe_error_code == "INVALID_CREDENTIALS"
    finally:
        os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)


def test_http_403_returns_invalid_credentials() -> None:
    import os
    os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = _PERMISSION_GRANTED
    try:
        with patch("requests.get", return_value=_mock_response(403)):
            result = RealBitvavoCredentialValidator().validate(_credential())
        assert result.success is False
        assert result.safe_error_code == "INVALID_CREDENTIALS"
    finally:
        os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)


# ---------------------------------------------------------------------------
# Server/network failures → VALIDATION_UNAVAILABLE
# ---------------------------------------------------------------------------

def test_http_500_returns_unavailable() -> None:
    import os
    os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = _PERMISSION_GRANTED
    try:
        with patch("requests.get", return_value=_mock_response(500)):
            result = RealBitvavoCredentialValidator().validate(_credential())
        assert result.success is False
        assert result.safe_error_code == "VALIDATION_UNAVAILABLE"
    finally:
        os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)


def test_connection_error_returns_unavailable() -> None:
    import os
    from requests.exceptions import ConnectionError as ReqConnError
    os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = _PERMISSION_GRANTED
    try:
        with patch("requests.get", side_effect=ReqConnError("unreachable")):
            result = RealBitvavoCredentialValidator().validate(_credential())
        assert result.success is False
        assert result.safe_error_code == "VALIDATION_UNAVAILABLE"
    finally:
        os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)


def test_timeout_returns_unavailable() -> None:
    import os
    from requests.exceptions import Timeout
    os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = _PERMISSION_GRANTED
    try:
        with patch("requests.get", side_effect=Timeout("timeout")):
            result = RealBitvavoCredentialValidator().validate(_credential())
        assert result.success is False
        assert result.safe_error_code == "VALIDATION_UNAVAILABLE"
    finally:
        os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)


# ---------------------------------------------------------------------------
# Credential isolation — explicit credentials, no global env fallback
# ---------------------------------------------------------------------------

def test_validator_uses_explicit_credentials_not_global_env() -> None:
    """Validator must pass explicit api_key/api_secret to BitvavoClient."""
    import os
    os.environ[BROKER_PRIVATE_READ_PERMISSION_ENV] = _PERMISSION_GRANTED
    os.environ["BITVAVO_API_KEY"] = "global-env-key-joost"
    os.environ["BITVAVO_API_SECRET"] = "global-env-secret-joost"
    try:
        captured_headers: list[dict] = []

        def _capture_get(url, **kwargs):
            headers = kwargs.get("headers", {})
            captured_headers.append(headers)
            return _mock_response(200, [])

        with patch("requests.get", side_effect=_capture_get):
            RealBitvavoCredentialValidator().validate(
                PlainBitvavoCredential(venue="bitvavo", api_key="hugo-specific-key", api_secret="hugo-specific-secret")
            )

        assert len(captured_headers) >= 1
        for h in captured_headers:
            access_key = h.get("Bitvavo-Access-Key", "")
            assert access_key != "global-env-key-joost", "validator must use hugo's explicit key, not joost's global env key"
            if access_key:
                assert access_key == "hugo-specific-key"
    finally:
        os.environ.pop(BROKER_PRIVATE_READ_PERMISSION_ENV, None)
        os.environ.pop("BITVAVO_API_KEY", None)
        os.environ.pop("BITVAVO_API_SECRET", None)


# ---------------------------------------------------------------------------
# Architecture safety
# ---------------------------------------------------------------------------

def test_no_broker_writes_in_validator() -> None:
    source = Path("src/account_provisioning/bitvavo_credential_validator_v1.py").read_text()
    assert "place_order" not in source
    assert "cancel_order" not in source


def test_validator_uses_explicit_not_default_client() -> None:
    source = Path("src/account_provisioning/bitvavo_credential_validator_v1.py").read_text()
    assert "api_key=credential.api_key" in source
    assert "api_secret=credential.api_secret" in source


if __name__ == "__main__":
    tests = [
        test_blocked_without_permission_env,
        test_blocked_with_wrong_permission_value,
        test_valid_credentials_return_valid_private_read,
        test_valid_credentials_no_safe_error_code,
        test_http_401_returns_invalid_credentials,
        test_http_403_returns_invalid_credentials,
        test_http_500_returns_unavailable,
        test_connection_error_returns_unavailable,
        test_timeout_returns_unavailable,
        test_validator_uses_explicit_credentials_not_global_env,
        test_no_broker_writes_in_validator,
        test_validator_uses_explicit_not_default_client,
    ]
    for t in tests:
        t()
    print("ok")
