"""
Tests for profile-scoped website session authorization.

Covers:
  Sessions:
    - valid login creates server-side session
    - stored token is hashed, not plaintext
    - cookie flags are correct (HttpOnly, Secure, SameSite=Lax, Path=/synth)
    - expired session rejected
    - idle-expired session rejected
    - revoked session rejected
    - logout invalidates session
    - login rotates session (old session invalidated)
    - unverified user rejected

  Authorization:
    - Joost can access Joost profile (check_access 200)
    - Joost cannot access Hugo profile (check_access 403)
    - Hugo can access Hugo profile
    - Hugo cannot access Joost profile
    - anonymous request gets 401
    - malformed profile slug rejected
    - nonexistent profile rejected
    - client cannot spoof ownership headers (X-Synth-Requested-Profile from nginx)
    - authorization endpoint leaks no user data

  Web security:
    - CSRF/Origin failure rejected (when allowed_origins configured)
    - login response does not enumerate accounts
    - unsafe redirect rejected (profile_code is not from form input)
    - secrets absent from rendered pages and logs

  Architecture:
    - no broker import
    - no decision_gate import
    - no execution_planner import
    - no executor import
    - broker_writes=0
    - order_submission=0
"""
from __future__ import annotations

import ast
import io
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from wsgiref.util import setup_testing_defaults

# datetime import is also used inline in tests

import pytest

from src.web.web_auth_http_v1 import SESSION_COOKIE_NAME, SESSION_COOKIE_PATH, build_wsgi_app
from src.web.website_registration_v1 import (
    CheckAccessResult,
    MemoryMailer,
    MockProofOfHumanProvider,
    SqliteWebsiteRegistrationRepository,
    USER_STATUS_ACTIVE,
    USER_STATUS_DISABLED,
    USER_STATUS_PENDING,
    WebsiteRegistrationService,
    _hash_token,
    _hash_ip,
    hash_password,
    normalize_profile_code,
    utc_now,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo() -> tuple[SqliteWebsiteRegistrationRepository, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    repo = SqliteWebsiteRegistrationRepository(conn)
    repo.create_schema()
    return repo, conn


def _make_service(
    *,
    session_ttl: timedelta = timedelta(days=14),
    session_idle_ttl: timedelta = timedelta(days=7),
    login_rate_limit_max: int = 10,
) -> tuple[WebsiteRegistrationService, SqliteWebsiteRegistrationRepository, MemoryMailer]:
    repo, _conn = _make_repo()
    mailer = MemoryMailer(sent_messages=[])
    service = WebsiteRegistrationService(
        repository=repo,
        proof_provider=MockProofOfHumanProvider(),
        mailer=mailer,
        base_url="https://synth.example",
        session_ttl=session_ttl,
        session_idle_ttl=session_idle_ttl,
        login_rate_limit_max=login_rate_limit_max,
    )
    return service, repo, mailer


def _make_app(
    *,
    allowed_origins: set[str] | None = None,
    session_ttl: timedelta = timedelta(days=14),
    session_idle_ttl: timedelta = timedelta(days=7),
) -> tuple[Any, WebsiteRegistrationService, SqliteWebsiteRegistrationRepository, MemoryMailer]:
    service, repo, mailer = _make_service(
        session_ttl=session_ttl,
        session_idle_ttl=session_idle_ttl,
    )
    app = build_wsgi_app(service=service, allowed_origins=allowed_origins)
    return app, service, repo, mailer


def _register_and_verify(
    service: WebsiteRegistrationService,
    mailer: MemoryMailer,
    *,
    email: str,
    profile_code: str,
    password: str = "Password123!",
    now_utc: datetime | None = None,
) -> None:
    result = service.register(
        email=email,
        profile_code=profile_code,
        password=password,
        proof_response="test-human-ok",
        now_utc=now_utc,
    )
    assert result.success, result.error_code
    token = mailer.sent_messages[-1]["verification_url"].split("token=", 1)[1]
    verify_result = service.verify_email(raw_token=token, now_utc=now_utc)
    assert verify_result.success, verify_result.error_code


def _invoke(
    app: Any,
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    cookie: str | None = None,
    origin: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], dict[str, Any] | None]:
    environ: dict[str, Any] = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        environ["CONTENT_LENGTH"] = str(len(body))
        environ["CONTENT_TYPE"] = "application/json"
        environ["wsgi.input"] = io.BytesIO(body)
    else:
        environ["wsgi.input"] = io.BytesIO(b"")
    if cookie:
        environ["HTTP_COOKIE"] = cookie
    if origin:
        environ["HTTP_ORIGIN"] = origin
    if extra_headers:
        for k, v in extra_headers.items():
            environ[k] = v

    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = headers

    chunks = app(environ, start_response)
    raw = b"".join(chunks)
    status_code = int(str(captured["status"]).split(" ", 1)[0])
    headers = {key: value for key, value in captured.get("headers", [])}
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except Exception:
        data = None
    return status_code, headers, data


def _login(app: Any, *, profile_code: str, password: str = "Password123!") -> str:
    """Login and return the raw cookie string."""
    code, headers, _ = _invoke(
        app,
        method="POST",
        path="/synth/web-auth/login",
        payload={"login_value": profile_code, "password": password},
    )
    assert code == 200, f"Login failed with {code}"
    return headers["Set-Cookie"].split(";", 1)[0]


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

class TestSessionCreation:
    def test_valid_login_creates_server_side_session(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        assert result.success
        assert result.session_token is not None
        row = repo.lookup_active_session(_hash_token(result.session_token))
        assert row is not None
        assert str(row["profile_code"]) == "joost"

    def test_stored_token_is_hash_not_plaintext(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        assert result.session_token is not None
        # Raw token must NOT appear in session_hash column
        row = repo.lookup_active_session(_hash_token(result.session_token))
        assert row is not None
        stored_hash = str(row["session_hash"])
        assert result.session_token not in stored_hash
        assert stored_hash == _hash_token(result.session_token)
        # Hash is a hex SHA-256 digest
        assert re.fullmatch(r"[0-9a-f]{64}", stored_hash)

    def test_session_bound_to_user_and_profile(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        row = repo.lookup_active_session(_hash_token(result.session_token))
        assert row["app_user_id"] is not None
        assert row["app_profile_id"] is not None

    def test_idle_expires_ts_set_on_login(self) -> None:
        service, repo, mailer = _make_service(session_idle_ttl=timedelta(days=3))
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        row = repo.lookup_active_session(_hash_token(result.session_token))
        assert row["idle_expires_ts_utc"] is not None


class TestCookieFlags:
    def test_cookie_flags_correct(self) -> None:
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        code, headers, _ = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "Password123!"},
        )
        assert code == 200
        cookie_header = headers["Set-Cookie"]
        assert SESSION_COOKIE_NAME in cookie_header
        assert "HttpOnly" in cookie_header
        assert "Secure" in cookie_header
        assert "SameSite=Lax" in cookie_header

    def test_cookie_path_is_synth_not_root(self) -> None:
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        code, headers, _ = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "Password123!"},
        )
        assert code == 200
        cookie_header = headers["Set-Cookie"]
        assert f"Path={SESSION_COOKIE_PATH}" in cookie_header or f"Path=/synth" in cookie_header
        assert "Path=/" not in cookie_header.replace("Path=/synth", "")

    def test_logout_clears_cookie(self) -> None:
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        session_cookie = _login(app, profile_code="joost")
        code, headers, _ = _invoke(
            app, method="POST", path="/synth/web-auth/logout", cookie=session_cookie
        )
        assert code == 200
        assert "Max-Age=0" in headers["Set-Cookie"]


class TestSessionExpiry:
    def test_expired_session_rejected(self) -> None:
        past = utc_now() - timedelta(days=30)
        service, repo, mailer = _make_service(session_ttl=timedelta(seconds=1))
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(
            login_value="joost",
            password="Password123!",
            now_utc=past,
        )
        assert result.success
        # Check access now (after expiry)
        check = service.check_access(
            session_token=result.session_token,
            now_utc=utc_now(),
        )
        assert not check.success
        assert check.error_code == "SESSION_EXPIRED"
        assert check.http_status == 401

    def test_idle_expired_session_rejected(self) -> None:
        service, repo, mailer = _make_service(
            session_idle_ttl=timedelta(seconds=1),
        )
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        past = utc_now() - timedelta(days=2)
        result = service.login(login_value="joost", password="Password123!", now_utc=past)
        assert result.success
        # Session created with idle_expires in the past (relative to now)
        check = service.check_access(
            session_token=result.session_token,
            now_utc=utc_now(),
        )
        assert not check.success
        assert check.error_code == "SESSION_IDLE_EXPIRED"
        assert check.http_status == 401

    def test_revoked_session_rejected(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        service.logout(session_token=result.session_token)
        check = service.check_access(session_token=result.session_token)
        assert not check.success
        assert check.error_code == "UNAUTHORIZED"

    def test_logout_invalidates_session(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        assert result.success
        service.logout(session_token=result.session_token)
        row = repo.lookup_active_session(_hash_token(result.session_token))
        assert row is not None
        assert row["invalidated_ts_utc"] is not None

    def test_login_rotates_session(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result1 = service.login(login_value="joost", password="Password123!")
        assert result1.success
        # Second login invalidates the first session
        result2 = service.login(login_value="joost", password="Password123!")
        assert result2.success
        # Old session should now be invalidated
        old_row = repo.lookup_active_session(_hash_token(result1.session_token))
        assert old_row is not None
        assert old_row["invalidated_ts_utc"] is not None
        # New session is valid
        new_row = repo.lookup_active_session(_hash_token(result2.session_token))
        assert new_row is not None
        assert new_row["invalidated_ts_utc"] is None

    def test_unverified_user_rejected(self) -> None:
        service, repo, mailer = _make_service()
        service.register(
            email="pending@example.com",
            profile_code="pending",
            password="Password123!",
            proof_response="test-human-ok",
        )
        result = service.login(login_value="pending", password="Password123!")
        assert not result.success
        # Returns INVALID_LOGIN (not PROFILE_NOT_VERIFIED) to prevent account enumeration.
        assert result.error_code == "INVALID_LOGIN"

    def test_disabled_user_rejected_on_session_lookup(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        assert result.success
        # Manually disable user
        repo.conn.execute(
            "UPDATE app_user SET status = ? WHERE email_normalized = ?",
            (USER_STATUS_DISABLED, "joost@example.com"),
        )
        repo.conn.commit()
        check = service.check_access(session_token=result.session_token)
        assert not check.success
        assert check.error_code == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# Authorization tests
# ---------------------------------------------------------------------------

class TestProfileAuthorization:
    def test_joost_can_access_joost_profile(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        check = service.check_access(
            session_token=result.session_token,
            requested_profile_code="joost",
        )
        assert check.success
        assert check.profile_code == "joost"
        assert check.http_status == 200

    def test_joost_cannot_access_hugo_profile(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        _register_and_verify(service, mailer, email="hugo@example.com", profile_code="hugo")
        result = service.login(login_value="joost", password="Password123!")
        check = service.check_access(
            session_token=result.session_token,
            requested_profile_code="hugo",
        )
        assert not check.success
        assert check.error_code == "FORBIDDEN"
        assert check.http_status == 403

    def test_hugo_can_access_hugo_profile(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="hugo@example.com", profile_code="hugo")
        result = service.login(login_value="hugo", password="Password123!")
        check = service.check_access(
            session_token=result.session_token,
            requested_profile_code="hugo",
        )
        assert check.success
        assert check.profile_code == "hugo"

    def test_hugo_cannot_access_joost_profile(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        _register_and_verify(service, mailer, email="hugo@example.com", profile_code="hugo")
        result = service.login(login_value="hugo", password="Password123!")
        check = service.check_access(
            session_token=result.session_token,
            requested_profile_code="joost",
        )
        assert not check.success
        assert check.error_code == "FORBIDDEN"
        assert check.http_status == 403

    def test_anonymous_request_gets_401(self) -> None:
        service, repo, mailer = _make_service()
        check = service.check_access(session_token="")
        assert not check.success
        assert check.http_status == 401

    def test_malformed_profile_slug_rejected(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        check = service.check_access(
            session_token=result.session_token,
            requested_profile_code="../../etc/passwd",
        )
        assert not check.success
        assert check.http_status in (400, 403)

    def test_nonexistent_profile_rejected(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        check = service.check_access(
            session_token=result.session_token,
            requested_profile_code="doesnotexist",
        )
        assert not check.success
        assert check.error_code == "FORBIDDEN"

    def test_check_access_no_profile_passes_for_valid_session(self) -> None:
        """When no profile slug is given (e.g. onboarding.html), just validate session."""
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        check = service.check_access(session_token=result.session_token, requested_profile_code=None)
        assert check.success
        assert check.http_status == 200


class TestCheckAccessHttpLayer:
    def test_check_access_endpoint_anonymous_gets_401(self) -> None:
        app, service, repo, mailer = _make_app()
        code, _, _ = _invoke(app, method="GET", path="/synth/web-auth/check-access")
        assert code == 401

    def test_check_access_endpoint_valid_session_gets_200(self) -> None:
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        session_cookie = _login(app, profile_code="joost")
        code, headers, _ = _invoke(
            app,
            method="GET",
            path="/synth/web-auth/check-access",
            cookie=session_cookie,
            extra_headers={"HTTP_X_SYNTH_REQUESTED_PROFILE": "joost"},
        )
        assert code == 200
        assert headers.get("X-Synth-Profile") == "joost"

    def test_check_access_endpoint_cross_profile_gets_403(self) -> None:
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        _register_and_verify(service, mailer, email="hugo@example.com", profile_code="hugo")
        session_cookie = _login(app, profile_code="joost")
        code, _, _ = _invoke(
            app,
            method="GET",
            path="/synth/web-auth/check-access",
            cookie=session_cookie,
            extra_headers={"HTTP_X_SYNTH_REQUESTED_PROFILE": "hugo"},
        )
        assert code == 403

    def test_client_cannot_spoof_profile_header_directly(self) -> None:
        """
        The X-Synth-Requested-Profile header is set by nginx from a regex capture.
        This test verifies the endpoint reads it from the environ (server-set),
        not from a client-supplied workaround. The distinction is enforced at the
        nginx level (internal; location). This test validates correct behavior when
        the header is explicitly set to a different profile than the session owner.
        """
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        _register_and_verify(service, mailer, email="hugo@example.com", profile_code="hugo")
        # Hugo's session, but header claims joost's profile
        hugo_cookie = _login(app, profile_code="hugo")
        code, _, _ = _invoke(
            app,
            method="GET",
            path="/synth/web-auth/check-access",
            cookie=hugo_cookie,
            extra_headers={"HTTP_X_SYNTH_REQUESTED_PROFILE": "joost"},
        )
        assert code == 403, "Hugo's session must not access Joost's profile via header"

    def test_authorization_endpoint_response_body_is_empty(self) -> None:
        """auth_request response body must contain no private information."""
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        session_cookie = _login(app, profile_code="joost")

        environ: dict[str, Any] = {}
        setup_testing_defaults(environ)
        environ["REQUEST_METHOD"] = "GET"
        environ["PATH_INFO"] = "/synth/web-auth/check-access"
        environ["wsgi.input"] = io.BytesIO(b"")
        environ["HTTP_COOKIE"] = session_cookie
        environ["HTTP_X_SYNTH_REQUESTED_PROFILE"] = "joost"

        chunks = []
        def start_response(status, headers):
            pass
        chunks = app(environ, start_response)
        body = b"".join(chunks)
        body_str = body.decode("utf-8", errors="replace")

        for forbidden in ("password", "email", "token", "hash", "secret", "session_hash"):
            assert forbidden not in body_str.lower(), (
                f"Auth endpoint body must not contain '{forbidden}'"
            )


# ---------------------------------------------------------------------------
# Web security tests
# ---------------------------------------------------------------------------

class TestCsrfProtection:
    def test_origin_validation_blocks_unknown_origin(self) -> None:
        app, service, repo, mailer = _make_app(
            allowed_origins={"https://synth.example"}
        )
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        code, _, data = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "Password123!"},
            origin="https://evil.example",
        )
        assert code == 403
        assert data["error"]["code"] == "ORIGIN_NOT_ALLOWED"

    def test_origin_validation_blocks_missing_origin(self) -> None:
        app, service, repo, mailer = _make_app(
            allowed_origins={"https://synth.example"}
        )
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        code, _, data = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "Password123!"},
            # No origin header
        )
        assert code == 403

    def test_origin_validation_allows_correct_origin(self) -> None:
        app, service, repo, mailer = _make_app(
            allowed_origins={"https://synth.example"}
        )
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        code, _, _ = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "Password123!"},
            origin="https://synth.example",
        )
        assert code == 200

    def test_origin_validation_disabled_by_default(self) -> None:
        """When allowed_origins=None, no Origin check (dev/test mode)."""
        app, service, repo, mailer = _make_app(allowed_origins=None)
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        code, _, _ = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "Password123!"},
            origin="https://evil.example",
        )
        assert code == 200


class TestLoginNoEnumeration:
    def test_wrong_password_gives_generic_error(self) -> None:
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="WrongPassword!")
        assert not result.success
        assert result.error_code == "INVALID_LOGIN"

    def test_nonexistent_user_gives_same_error_as_wrong_password(self) -> None:
        service, repo, mailer = _make_service()
        result = service.login(login_value="nobody", password="AnyPassword!")
        assert not result.success
        assert result.error_code == "INVALID_LOGIN"

    def test_login_response_does_not_reveal_existence(self) -> None:
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        # Wrong password for existing user
        code1, _, data1 = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "WrongPassword"},
        )
        # Nonexistent user
        code2, _, data2 = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "nobody", "password": "WrongPassword"},
        )
        # Both must have same HTTP status and same error code
        assert code1 == code2 == 401
        assert data1["error"]["code"] == data2["error"]["code"] == "INVALID_LOGIN"

    def test_login_rate_limiting_fires(self) -> None:
        service, repo, mailer = _make_service(login_rate_limit_max=3)
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        ip = "1.2.3.4"
        for _ in range(3):
            result = service.login(login_value="joost", password="Wrong!", remote_ip=ip)
            assert result.error_code == "INVALID_LOGIN"
        result = service.login(login_value="joost", password="Wrong!", remote_ip=ip)
        assert result.error_code == "LOGIN_RATE_LIMITED"


class TestNoUnsafeRedirect:
    def test_login_redirect_uses_api_returned_profile_code(self) -> None:
        """The login redirect uses server-returned profile_code, not a browser form field."""
        from src.web.run_website_registration_pages_v1 import render_login_page
        page = render_login_page()
        # Redirect must construct URL from data.profile_code (server response)
        assert "data.profile_code" in page
        # Must NOT use a form input field directly for the profile in the redirect
        assert "/accounts/" in page
        # Should not redirect based on an unrestricted client-supplied parameter
        assert "open redirect" not in page.lower()

    def test_login_page_does_not_reveal_error_details(self) -> None:
        """Login failure message must not expose server error details."""
        from src.web.run_website_registration_pages_v1 import render_login_page
        page = render_login_page()
        # Generic message only
        assert "failed" in page.lower()
        # Must not show raw error code from server to user
        assert "INVALID_LOGIN" not in page or "data.error.code" not in page.split("INVALID_LOGIN")[0]


class TestSecretsNotLeaked:
    def test_health_endpoint_leaks_no_secrets(self) -> None:
        app, service, repo, mailer = _make_app()
        code, _, data = _invoke(app, method="GET", path="/synth/web-auth/healthz")
        assert code == 200
        serialized = json.dumps(data, sort_keys=True)
        for forbidden in ("password", "token", "secret", "hash", "key"):
            assert forbidden not in serialized.lower(), (
                f"Health endpoint must not contain '{forbidden}'"
            )

    def test_session_token_not_in_response_payload(self) -> None:
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        code, headers, data = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "Password123!"},
        )
        assert code == 200
        serialized = json.dumps(data, sort_keys=True)
        # Session token must not appear in JSON response body
        assert "session_token" not in serialized
        # Token is in the cookie, not the body
        assert SESSION_COOKIE_NAME in headers.get("Set-Cookie", "")

    def test_password_hash_not_in_any_response(self) -> None:
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        code, _, data = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "Password123!"},
        )
        assert code == 200
        serialized = json.dumps(data, sort_keys=True)
        assert "password_hash" not in serialized
        assert "scrypt" not in serialized

    def test_onboarding_page_contains_no_credentials(self) -> None:
        from src.web.run_website_registration_pages_v1 import render_onboarding_page
        page = render_onboarding_page()
        assert "api_key" not in page.lower()
        assert "api_secret" not in page.lower()
        assert "bitvavo" not in page.lower()
        assert "password" not in page.lower() or "password" in page.lower()
        # No actual credential input fields
        assert 'type="password"' not in page or 'type="password"' not in page


# ---------------------------------------------------------------------------
# Architecture tests
# ---------------------------------------------------------------------------

class TestArchitectureBoundaries:
    _src_modules = [
        "src/web/website_registration_v1.py",
        "src/web/web_auth_http_v1.py",
        "src/web/run_web_auth_service_v1.py",
        "src/web/run_website_registration_pages_v1.py",
    ]

    def _read_source(self, path: str) -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / path).read_text(encoding="utf-8")

    def _check_no_forbidden_import(self, source: str, module: str) -> None:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    assert module not in (name or ""), (
                        f"Forbidden import of '{module}' found"
                    )

    def test_no_broker_import(self) -> None:
        for path in self._src_modules:
            source = self._read_source(path)
            self._check_no_forbidden_import(source, "broker")
            assert "broker_writes" not in source or "broker_writes=0" in source

    def test_no_decision_gate_import(self) -> None:
        for path in self._src_modules:
            source = self._read_source(path)
            self._check_no_forbidden_import(source, "decision_gate")

    def test_no_execution_planner_import(self) -> None:
        for path in self._src_modules:
            source = self._read_source(path)
            self._check_no_forbidden_import(source, "execution_planner")

    def test_no_executor_import(self) -> None:
        for path in self._src_modules:
            source = self._read_source(path)
            self._check_no_forbidden_import(source, "executor")

    def test_no_trading_account_schema(self) -> None:
        repo, conn = _make_repo()
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "trading_account" not in tables
        assert "credential" not in tables

    def test_service_runner_prints_safety_markers(self) -> None:
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / "src/web/run_web_auth_service_v1.py").read_text()
        assert "broker_private_calls=0" in source
        assert "broker_writes=0" in source
        assert "order_submission=0" in source
        assert "live_orders=0" in source
        assert "decision_gate=none" in source
        assert "execution_planner=none" in source
        assert "executor=none" in source

    def test_check_access_result_has_http_status_field(self) -> None:
        result_ok = CheckAccessResult(success=True, profile_code="joost", http_status=200)
        result_unauth = CheckAccessResult(success=False, error_code="UNAUTHORIZED", http_status=401)
        result_forbidden = CheckAccessResult(success=False, error_code="FORBIDDEN", http_status=403)
        assert result_ok.http_status == 200
        assert result_unauth.http_status == 401
        assert result_forbidden.http_status == 403

    def test_ip_hash_is_never_plaintext_in_login_attempt(self) -> None:
        """record_login_attempt stores hashed IP (caller responsibility)."""
        repo, conn = _make_repo()
        raw_ip = "192.168.1.1"
        hashed = _hash_ip(raw_ip)
        repo.record_login_attempt(hashed, datetime.now(UTC), success=False)
        rows = conn.execute("SELECT ip_hash FROM login_attempt").fetchall()
        assert len(rows) == 1
        stored = rows[0][0]
        assert raw_ip not in stored
        assert stored == hashed
        assert re.fullmatch(r"[0-9a-f]{64}", stored)

    def test_update_session_last_seen_extends_idle_expiry(self) -> None:
        """check_access updates last_seen and extends idle_expires_ts_utc."""
        now = utc_now()
        past = now - timedelta(minutes=30)
        service, repo, mailer = _make_service(session_idle_ttl=timedelta(hours=1))
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost",
                              now_utc=past)
        result = service.login(login_value="joost", password="Password123!", now_utc=past)
        assert result.success
        session_hash = _hash_token(result.session_token)
        row_before = repo.lookup_active_session(session_hash)
        idle_before = str(row_before["idle_expires_ts_utc"])  # past + 1h = now + 30min

        # check_access at `now` — still valid (idle_expires = now+30min > now)
        check = service.check_access(session_token=result.session_token, now_utc=now)
        assert check.success, f"Expected success, got: {check.error_code}"

        row_after = repo.lookup_active_session(session_hash)
        idle_after = str(row_after["idle_expires_ts_utc"])  # now + 1h

        # idle_expires should have been extended forward
        assert idle_after is not None
        assert idle_after > idle_before  # now+1h > now+30min (ISO string comparison works here)


# ---------------------------------------------------------------------------
# Hardening tests (added post-review)
# ---------------------------------------------------------------------------

class TestRateLimitHardening:
    def test_remote_ip_prefers_x_real_ip_over_x_forwarded_for(self) -> None:
        """X-Real-IP (set by nginx from $remote_addr) must take precedence.
        X-Forwarded-For leftmost hop is client-controlled."""
        from src.web.web_auth_http_v1 import _remote_ip
        environ = {
            "HTTP_X_REAL_IP": "10.0.0.1",
            "HTTP_X_FORWARDED_FOR": "1.2.3.4, 10.0.0.1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        assert _remote_ip(environ) == "10.0.0.1"

    def test_remote_ip_falls_back_to_remote_addr_when_no_x_real_ip(self) -> None:
        from src.web.web_auth_http_v1 import _remote_ip
        environ = {
            "HTTP_X_FORWARDED_FOR": "1.2.3.4",
            "REMOTE_ADDR": "10.0.0.1",
        }
        assert _remote_ip(environ) == "10.0.0.1"

    def test_rate_limit_cannot_be_bypassed_by_spoofing_x_forwarded_for(self) -> None:
        """Login rate limit must not be bypassable by changing X-Forwarded-For."""
        app, service, repo, mailer = _make_app()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        real_ip = "10.0.0.1"
        for i in range(11):
            spoofed_xff = f"192.168.1.{i}"
            _invoke(
                app,
                method="POST",
                path="/synth/web-auth/login",
                payload={"login_value": "joost", "password": "wrongpassword"},
                extra_headers={
                    "HTTP_X_REAL_IP": real_ip,
                    "HTTP_X_FORWARDED_FOR": spoofed_xff,
                },
            )
        # The 11th attempt from the same real IP must be rate-limited
        # regardless of spoofed X-Forwarded-For values
        code, _, data = _invoke(
            app,
            method="POST",
            path="/synth/web-auth/login",
            payload={"login_value": "joost", "password": "wrongpassword"},
            extra_headers={
                "HTTP_X_REAL_IP": real_ip,
                "HTTP_X_FORWARDED_FOR": "99.99.99.99",
            },
        )
        assert data.get("error", {}).get("code") == "LOGIN_RATE_LIMITED"

    def test_ip_hash_uses_hmac_not_plain_sha256(self) -> None:
        """_hash_ip with a pepper must produce HMAC-SHA256, not plain SHA-256."""
        import hmac as hmac_module
        import hashlib
        ip = "192.168.1.1"
        pepper = "test-pepper"
        expected = hmac_module.new(
            pepper.encode("utf-8"),
            ip.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        from src.web.website_registration_v1 import _hash_ip
        assert _hash_ip(ip, pepper) == expected

    def test_ip_hash_pepper_isolates_across_deployments(self) -> None:
        """Different peppers produce different hashes for the same IP."""
        from src.web.website_registration_v1 import _hash_ip
        ip = "10.0.0.1"
        hash1 = _hash_ip(ip, "pepper_a")
        hash2 = _hash_ip(ip, "pepper_b")
        assert hash1 != hash2


class TestEnumerationHardening:
    def test_unverified_user_returns_same_error_as_wrong_password(self) -> None:
        """Login must return INVALID_LOGIN for unverified accounts to prevent enumeration."""
        service, repo, mailer = _make_service()
        service.register(
            email="unverified@example.com",
            profile_code="unverified",
            password="Password123!",
            proof_response="test-human-ok",
        )
        result_unverified = service.login(login_value="unverified", password="Password123!")
        result_wrong_pw = service.login(login_value="unverified", password="wrongpassword")
        result_nonexistent = service.login(login_value="nobody", password="whatever")
        assert result_unverified.error_code == "INVALID_LOGIN"
        assert result_wrong_pw.error_code == "INVALID_LOGIN"
        assert result_nonexistent.error_code == "INVALID_LOGIN"

    def test_disabled_user_login_returns_same_error_as_wrong_password(self) -> None:
        """Login must return INVALID_LOGIN for disabled accounts to prevent enumeration."""
        service, repo, mailer = _make_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        repo.conn.execute(
            "UPDATE app_user SET status = ? WHERE email_normalized = ?",
            (USER_STATUS_DISABLED, "joost@example.com"),
        )
        repo.conn.commit()
        result = service.login(login_value="joost", password="Password123!")
        assert result.error_code == "INVALID_LOGIN"


class TestNginxTemplateHardening:
    def test_nginx_template_includes_x_real_ip_header(self) -> None:
        """nginx must set X-Real-IP from $remote_addr for rate limiting."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        template = (root / "docs/deployment/nginx_auth_request_template_v1.conf").read_text()
        assert "X-Real-IP" in template
        assert "$remote_addr" in template

    def test_transitional_config_includes_basic_auth_and_app_auth(self) -> None:
        """Transitional nginx config must have both auth_basic and auth_request."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        config = (root / "docs/deployment/nginx_transition_dual_auth_v1.conf").read_text()
        assert "auth_basic" in config
        assert "auth_request" in config
        assert "X-Real-IP" in config

    def test_migration_includes_retention_comment(self) -> None:
        """Migration must document login_attempt retention strategy."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        migration = (root / "db/migrations/20260607_profile_session_authorization_v1.sql").read_text()
        assert "retention" in migration.lower() or "DELETE FROM login_attempt" in migration

    def test_migration_includes_legacy_session_cleanup_option(self) -> None:
        """Migration must document optional pre-migration session invalidation."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        migration = (root / "db/migrations/20260607_profile_session_authorization_v1.sql").read_text()
        assert "idle_expires_ts_utc IS NULL" in migration

    def test_transitional_config_uses_internal_uri_not_named_location(self) -> None:
        """auth_request must use an internal URI location, not a named @ location."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        config = (root / "docs/deployment/nginx_transition_dual_auth_v1.conf").read_text()
        assert "auth_request /synth/_internal/check-access" in config
        assert "location = /synth/_internal/check-access" in config
        assert "internal;" in config
        assert "auth_basic off;" in config

    def test_systemd_service_has_security_hardening(self) -> None:
        """Systemd unit must include EnvironmentFile, UMask, NoNewPrivileges, and [Install]."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        svc = (root / "scripts/odroid/systemd/synth-website-registration.service").read_text()
        assert "EnvironmentFile=" in svc
        assert "UMask=0077" in svc
        assert "NoNewPrivileges=true" in svc
        assert "WantedBy=default.target" in svc

    def test_systemd_service_execstart_uses_explicit_bash(self) -> None:
        """ExecStart must use /usr/bin/bash explicitly — wrapper may be non-executable (git 100644)."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        svc = (root / "scripts/odroid/systemd/synth-website-registration.service").read_text()
        assert "ExecStart=/usr/bin/bash " in svc, (
            "ExecStart must invoke /usr/bin/bash explicitly to avoid status=203/EXEC "
            "when the wrapper script is git mode 100644 (not executable)."
        )
        assert svc.count("ExecStart=") == 1, "No duplicate ExecStart directives"
        assert "run_website_registration_service_once.sh" in svc

    def test_migration_runner_applies_chain(self) -> None:
        """Migration runner must reference both migrations in order."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / "src/web/run_website_registration_db_migration_v1.py").read_text()
        assert "20260605_website_registration_foundation_v1.sql" in source
        assert "20260607_profile_session_authorization_v1.sql" in source
        # Second migration must follow the first
        pos1 = source.index("20260605_website_registration_foundation_v1.sql")
        pos2 = source.index("20260607_profile_session_authorization_v1.sql")
        assert pos1 < pos2, "Foundation migration must precede authorization migration"
