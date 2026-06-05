from __future__ import annotations

import io
import json
import sqlite3
from typing import Any
from wsgiref.util import setup_testing_defaults

from src.web.web_auth_http_v1 import SESSION_COOKIE_NAME, build_wsgi_app
from src.web.website_registration_v1 import (
    MemoryMailer,
    MockProofOfHumanProvider,
    SqliteWebsiteRegistrationRepository,
    WebsiteRegistrationService,
)


def _build_app() -> tuple[Any, MemoryMailer, sqlite3.Connection]:
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
    return build_wsgi_app(service=service), mailer, conn


def _invoke(
    app: Any,
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    cookie: str | None = None,
) -> tuple[int, dict[str, str], dict[str, Any]]:
    environ: dict[str, Any] = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    body = json.dumps(payload or {}).encode("utf-8")
    environ["CONTENT_LENGTH"] = str(len(body))
    environ["CONTENT_TYPE"] = "application/json"
    environ["wsgi.input"] = io.BytesIO(body)
    if cookie:
        environ["HTTP_COOKIE"] = cookie

    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers

    chunks = app(environ, start_response)
    text = b"".join(chunks).decode("utf-8")
    status_code = int(str(captured["status"]).split(" ", 1)[0])
    headers = {key: value for key, value in captured["headers"]}
    return status_code, headers, json.loads(text)


def _extract_token(mailer: MemoryMailer) -> str:
    return mailer.sent_messages[-1]["verification_url"].split("token=", 1)[1]


def test_registration_http_flow() -> None:
    app, mailer, conn = _build_app()
    status_code, _headers, payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/register",
        payload={
            "email": "hugo@example.com",
            "profile_code": "hugo",
            "password": "VerySecurePassword123",
            "proof_response": "test-human-ok",
        },
    )
    assert status_code == 200
    assert payload["ok"] is True
    assert mailer.sent_messages[-1]["verification_url"].startswith("https://synth.example/synth/verify-result.html?token=")

    token = _extract_token(mailer)
    verify_code, _, verify_payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/verify-email",
        payload={"token": token},
    )
    assert verify_code == 200
    assert verify_payload["ok"] is True

    login_code, login_headers, login_payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/login",
        payload={"login_value": "hugo", "password": "VerySecurePassword123"},
    )
    assert login_code == 200
    assert login_payload["ok"] is True
    set_cookie_header = login_headers["Set-Cookie"]
    session_cookie = set_cookie_header.split(";", 1)[0]
    assert SESSION_COOKIE_NAME in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "Secure" in set_cookie_header
    assert "SameSite=Lax" in set_cookie_header

    onboarding_code, _, onboarding_payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/onboarding-status",
        payload={"requested_profile_code": "hugo"},
        cookie=session_cookie,
    )
    assert onboarding_code == 200
    assert onboarding_payload["ok"] is True
    assert onboarding_payload["onboarding_state"] == "NO_EXCHANGE_ACCOUNT_CONNECTED"

    forbidden_code, _, forbidden_payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/onboarding-status",
        payload={"requested_profile_code": "joost"},
        cookie=session_cookie,
    )
    assert forbidden_code == 403
    assert forbidden_payload["error"]["code"] == "FORBIDDEN"

    logout_code, logout_headers, logout_payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/logout",
        cookie=session_cookie,
    )
    assert logout_code == 200
    assert logout_payload["ok"] is True
    assert "Max-Age=0" in logout_headers["Set-Cookie"]

    anonymous_code, _, anonymous_payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/onboarding-status",
        payload={"requested_profile_code": "hugo"},
        cookie=session_cookie,
    )
    assert anonymous_code == 401
    assert anonymous_payload["error"]["code"] == "UNAUTHORIZED"

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert "trading_account" not in tables
    assert "credential" not in tables


def test_invalid_proof_and_reused_verification_fail_closed() -> None:
    app, mailer, _conn = _build_app()
    bad_code, _, bad_payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/register",
        payload={
            "email": "hugo@example.com",
            "profile_code": "hugo",
            "password": "VerySecurePassword123",
            "proof_response": "not-human",
        },
    )
    assert bad_code == 400
    assert bad_payload["error"]["code"] == "INVALID_PROOF_OF_HUMAN"

    _invoke(
        app,
        method="POST",
        path="/synth/web-auth/register",
        payload={
            "email": "hugo@example.com",
            "profile_code": "hugo",
            "password": "VerySecurePassword123",
            "proof_response": "test-human-ok",
        },
    )
    token = _extract_token(mailer)
    first_code, _, first_payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/verify-email",
        payload={"token": token},
    )
    second_code, _, second_payload = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/verify-email",
        payload={"token": token},
    )
    assert first_code == 200
    assert first_payload["ok"] is True
    assert second_code == 400
    assert second_payload["error"]["code"] == "VERIFICATION_TOKEN_ALREADY_USED"


def test_health_endpoint_contains_no_secrets() -> None:
    app, _mailer, _conn = _build_app()
    status_code, _headers, payload = _invoke(
        app,
        method="GET",
        path="/synth/web-auth/healthz",
    )
    assert status_code == 200
    assert payload == {"ok": True, "service": "website_registration_v1", "status": "healthy"}
    serialized = json.dumps(payload, sort_keys=True)
    assert "password" not in serialized.lower()
    assert "token" not in serialized.lower()
    assert "secret" not in serialized.lower()


def main() -> None:
    test_registration_http_flow()
    test_invalid_proof_and_reused_verification_fail_closed()
    test_health_endpoint_contains_no_secrets()
    print("ok")


if __name__ == "__main__":
    main()
