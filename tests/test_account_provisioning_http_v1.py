"""
HTTP-layer tests for POST /synth/web-auth/connect-bitvavo.

Uses a mock connect_bitvavo callable — DB state is not tested here.
See test_account_provisioning_service_v1.py for service/DB tests.
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from wsgiref.util import setup_testing_defaults

from src.account_provisioning.account_provisioning_service_v1 import (
    AuthenticatedProfileIdentity,
    ProvisioningResult,
)
from src.web.web_auth_http_v1 import SESSION_COOKIE_NAME, build_wsgi_app
from src.web.website_registration_v1 import (
    MemoryMailer,
    MockProofOfHumanProvider,
    SqliteWebsiteRegistrationRepository,
    WebsiteRegistrationService,
)


_NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)

_SUCCESS_RESULT = ProvisioningResult(
    ok=True,
    profile_code="hugo",
    account_connection_state="READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED",
    landing_path="/synth/accounts/hugo/profit-plan.html",
    refresh_pending=True,
)

_INVALID_RESULT = ProvisioningResult(ok=False, error_code="INVALID_CREDENTIALS")
_UNAVAILABLE_RESULT = ProvisioningResult(ok=False, error_code="VALIDATION_UNAVAILABLE")
_ALREADY_CONNECTED_RESULT = ProvisioningResult(
    ok=False,
    error_code="ACCOUNT_ALREADY_CONNECTED",
    profile_code="hugo",
    landing_path="/synth/accounts/hugo/profit-plan.html",
)


def _make_mock_connect_bitvavo(result: ProvisioningResult):
    calls: list[dict[str, Any]] = []

    def fn(identity, api_key, api_secret, confirmed, now_utc):
        calls.append({
            "identity": identity,
            "api_key": api_key,
            "api_secret": api_secret,
            "confirmed": confirmed,
        })
        return result

    return fn, calls


def _build_app(connect_bitvavo=None):
    conn = sqlite3.connect(":memory:")
    repo = SqliteWebsiteRegistrationRepository(conn)
    repo.create_schema()
    mailer = MemoryMailer(sent_messages=[])
    service = WebsiteRegistrationService(
        repository=repo,
        proof_provider=MockProofOfHumanProvider(),
        mailer=mailer,
        base_url="https://synth.example",
    )
    app = build_wsgi_app(service=service, connect_bitvavo=connect_bitvavo)
    return app, service, mailer, conn


def _invoke(
    app: Any,
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    cookie: str | None = None,
    origin: str | None = None,
    content_length: int | None = None,
    raw_body: bytes | None = None,
) -> tuple[int, dict[str, str], dict[str, Any]]:
    environ: dict[str, Any] = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    if raw_body is not None:
        body = raw_body
    else:
        body = json.dumps(payload or {}).encode("utf-8")
    actual_length = content_length if content_length is not None else len(body)
    environ["CONTENT_LENGTH"] = str(actual_length)
    environ["CONTENT_TYPE"] = "application/json"
    environ["wsgi.input"] = io.BytesIO(body)
    if cookie:
        environ["HTTP_COOKIE"] = cookie
    if origin:
        environ["HTTP_ORIGIN"] = origin

    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers

    chunks = app(environ, start_response)
    text = b"".join(chunks).decode("utf-8")
    status_code = int(str(captured["status"]).split(" ", 1)[0])
    headers = {key: value for key, value in captured["headers"]}
    return status_code, headers, json.loads(text)


def _register_and_login(app, service, mailer) -> str:
    """Register hugo, verify email, login. Returns session cookie string."""
    _invoke(app, method="POST", path="/synth/web-auth/register", payload={
        "email": "hugo@example.com",
        "profile_code": "hugo",
        "password": "VerySecurePassword123",
        "proof_response": "test-human-ok",
    })
    token = mailer.sent_messages[-1]["verification_url"].split("token=", 1)[1]
    _invoke(app, method="POST", path="/synth/web-auth/verify-email", payload={"token": token})
    _, login_headers, _ = _invoke(app, method="POST", path="/synth/web-auth/login", payload={
        "login_value": "hugo",
        "password": "VerySecurePassword123",
    })
    cookie_header = login_headers["Set-Cookie"]
    return cookie_header.split(";", 1)[0]  # e.g. "synth_web_session=..."


# ---------------------------------------------------------------------------
# Auth / session
# ---------------------------------------------------------------------------

def test_unauthenticated_request_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    status, _, payload = _invoke(app, method="POST", path="/synth/web-auth/connect-bitvavo", payload={
        "api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True,
    })
    assert status == 401
    assert not payload["ok"]
    assert len(calls) == 0


def test_missing_cookie_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    status, _, payload = _invoke(app, method="POST", path="/synth/web-auth/connect-bitvavo",
                                 payload={"api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True})
    assert status == 401
    assert len(calls) == 0


def test_invalid_session_cookie_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True},
        cookie=f"{SESSION_COOKIE_NAME}=not-a-real-session",
    )
    assert status == 401
    assert len(calls) == 0


def test_origin_validation_blocks_when_configured() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    conn = sqlite3.connect(":memory:")
    repo = SqliteWebsiteRegistrationRepository(conn)
    repo.create_schema()
    mailer = MemoryMailer(sent_messages=[])
    service = WebsiteRegistrationService(
        repository=repo, proof_provider=MockProofOfHumanProvider(),
        mailer=mailer, base_url="https://synth.example",
    )
    app = build_wsgi_app(service=service, allowed_origins={"https://synth.example"}, connect_bitvavo=mock_fn)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True},
        origin="https://evil.example",
    )
    assert status == 403
    assert len(calls) == 0


def test_endpoint_404_when_provisioning_not_configured() -> None:
    app, service, mailer, conn = _build_app(connect_bitvavo=None)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    assert status == 404


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

def test_oversized_request_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        content_length=200_000,
        raw_body=b"x" * 200_000,
    )
    assert status == 400
    assert len(calls) == 0


def test_malformed_json_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        raw_body=b"{not valid json",
        content_length=16,
    )
    assert status == 400
    assert len(calls) == 0


def test_non_object_json_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    body = b'["array", "not", "object"]'
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        raw_body=body, content_length=len(body),
    )
    assert status == 400
    assert len(calls) == 0


def test_missing_api_key_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_secret": "s", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    assert status == 400
    assert payload["error"]["code"] == "MISSING_API_KEY"
    assert len(calls) == 0


def test_missing_api_secret_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    assert status == 400
    assert payload["error"]["code"] == "MISSING_API_SECRET"
    assert len(calls) == 0


def test_missing_confirmation_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "api_secret": "s"},
        cookie=session_cookie,
    )
    assert status == 400
    assert payload["error"]["code"] == "WITHDRAWAL_CONFIRMATION_REQUIRED"
    assert len(calls) == 0


def test_false_confirmation_rejected() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": False},
        cookie=session_cookie,
    )
    assert status == 400
    assert payload["error"]["code"] == "WITHDRAWAL_CONFIRMATION_REQUIRED"
    assert len(calls) == 0


# ---------------------------------------------------------------------------
# Ownership isolation
# ---------------------------------------------------------------------------

def test_browser_profile_override_ignored_uses_session_identity() -> None:
    """Client-supplied profile_code in body must not affect the identity used."""
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={
            "api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True,
            "profile_code": "joost",  # attempted override
        },
        cookie=session_cookie,
    )
    assert status == 200
    assert len(calls) == 1
    # Identity used by provisioning must be from session (hugo), not from body
    assert calls[0]["identity"].profile_code == "hugo"


def test_browser_user_id_override_ignored() -> None:
    mock_fn, calls = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={
            "api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True,
            "app_user_id": 999, "app_profile_id": 999, "trading_account_id": 999,
        },
        cookie=session_cookie,
    )
    assert status == 200
    assert calls[0]["identity"].app_user_id != 999
    assert calls[0]["identity"].app_profile_id != 999


def test_success_landing_path_uses_authenticated_profile() -> None:
    mock_fn, _ = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    _, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    assert payload["landing_path"].startswith("/synth/accounts/hugo/")


# ---------------------------------------------------------------------------
# Success response
# ---------------------------------------------------------------------------

def test_success_response_shape() -> None:
    mock_fn, _ = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    assert status == 200
    assert payload["ok"] is True
    assert payload["profile_code"] == "hugo"
    assert payload["account_connection_state"] == "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED"
    assert payload["landing_path"] == "/synth/accounts/hugo/profit-plan.html"
    assert payload["refresh_pending"] is True


def test_response_never_contains_credentials() -> None:
    mock_fn, _ = _make_mock_connect_bitvavo(_SUCCESS_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    _, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "super-secret-api-key", "api_secret": "super-secret-api-secret", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    payload_str = json.dumps(payload)
    assert "super-secret-api-key" not in payload_str
    assert "super-secret-api-secret" not in payload_str


# ---------------------------------------------------------------------------
# Error responses
# ---------------------------------------------------------------------------

def test_invalid_credentials_returns_400() -> None:
    mock_fn, _ = _make_mock_connect_bitvavo(_INVALID_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "bad-key", "api_secret": "bad-secret", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    assert status == 400
    assert payload["error"]["code"] == "INVALID_CREDENTIALS"


def test_validation_unavailable_returns_503() -> None:
    mock_fn, _ = _make_mock_connect_bitvavo(_UNAVAILABLE_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "mock-unavailable-key", "api_secret": "s", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    assert status == 503
    assert payload["error"]["code"] == "VALIDATION_UNAVAILABLE"


def test_already_connected_returns_409() -> None:
    mock_fn, _ = _make_mock_connect_bitvavo(_ALREADY_CONNECTED_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    status, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    assert status == 409
    assert payload["error"]["code"] == "ACCOUNT_ALREADY_CONNECTED"
    assert "landing_path" in payload
    assert "credential" not in json.dumps(payload)


def test_already_connected_response_no_credential_metadata() -> None:
    mock_fn, _ = _make_mock_connect_bitvavo(_ALREADY_CONNECTED_RESULT)
    app, service, mailer, conn = _build_app(mock_fn)
    session_cookie = _register_and_login(app, service, mailer)
    _, _, payload = _invoke(
        app, method="POST", path="/synth/web-auth/connect-bitvavo",
        payload={"api_key": "k", "api_secret": "s", "withdrawal_disabled_confirmed": True},
        cookie=session_cookie,
    )
    payload_str = json.dumps(payload)
    for forbidden in ("fingerprint", "ciphertext", "encrypted", "api_key", "api_secret"):
        assert forbidden not in payload_str


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------

def test_no_broker_imports_in_web_controller() -> None:
    source = Path("src/web/web_auth_http_v1.py").read_text()
    assert "BitvavoClient" not in source
    assert "get_balance" not in source
    assert "place_order" not in source
    assert "cancel_order" not in source


if __name__ == "__main__":
    tests = [
        test_unauthenticated_request_rejected,
        test_missing_cookie_rejected,
        test_invalid_session_cookie_rejected,
        test_origin_validation_blocks_when_configured,
        test_endpoint_404_when_provisioning_not_configured,
        test_oversized_request_rejected,
        test_malformed_json_rejected,
        test_non_object_json_rejected,
        test_missing_api_key_rejected,
        test_missing_api_secret_rejected,
        test_missing_confirmation_rejected,
        test_false_confirmation_rejected,
        test_browser_profile_override_ignored_uses_session_identity,
        test_browser_user_id_override_ignored,
        test_success_landing_path_uses_authenticated_profile,
        test_success_response_shape,
        test_response_never_contains_credentials,
        test_invalid_credentials_returns_400,
        test_validation_unavailable_returns_503,
        test_already_connected_returns_409,
        test_already_connected_response_no_credential_metadata,
        test_no_broker_imports_in_web_controller,
    ]
    for t in tests:
        t()
    print("ok")
