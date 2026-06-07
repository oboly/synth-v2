from __future__ import annotations

import json
from datetime import timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs

from src.web.website_registration_v1 import (
    CheckAccessResult,
    LoginResult,
    OnboardingAccessResult,
    RegisterResult,
    ResendResult,
    VerifyResult,
    WebsiteRegistrationService,
)


SESSION_COOKIE_NAME = "synth_web_session"
SESSION_COOKIE_PATH = "/synth"
JSON_HEADERS = [("Content-Type", "application/json; charset=utf-8")]
MAX_REQUEST_BODY_BYTES = 64 * 1024  # 64 KiB


def _json_response(
    start_response: Callable[[str, list[tuple[str, str]]], None],
    *,
    status: HTTPStatus,
    payload: Mapping[str, Any],
    extra_headers: list[tuple[str, str]] | None = None,
) -> list[bytes]:
    headers = list(JSON_HEADERS)
    if extra_headers:
        headers.extend(extra_headers)
    start_response(f"{status.value} {status.phrase}", headers)
    return [json.dumps(payload, sort_keys=True).encode("utf-8")]


def _read_json_body(environ: Mapping[str, Any]) -> dict[str, Any]:
    try:
        length = int(str(environ.get("CONTENT_LENGTH") or "0"))
    except ValueError:
        length = 0
    if length > MAX_REQUEST_BODY_BYTES:
        raise ValueError("Request body too large")
    raw = environ["wsgi.input"].read(length) if length > 0 else b"{}"
    if not raw:
        return {}
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("JSON object body required")
    return decoded


def _cookie_headers(
    *,
    session_token: str,
    max_age_seconds: int,
    clear: bool = False,
) -> list[tuple[str, str]]:
    cookie = SimpleCookie()
    cookie[SESSION_COOKIE_NAME] = "" if clear else session_token
    cookie[SESSION_COOKIE_NAME]["path"] = SESSION_COOKIE_PATH
    cookie[SESSION_COOKIE_NAME]["httponly"] = True
    cookie[SESSION_COOKIE_NAME]["secure"] = True
    cookie[SESSION_COOKIE_NAME]["samesite"] = "Lax"
    cookie[SESSION_COOKIE_NAME]["max-age"] = 0 if clear else max_age_seconds
    return [("Set-Cookie", morsel.OutputString()) for morsel in cookie.values()]


def _get_cookie_value(environ: Mapping[str, Any], name: str) -> str | None:
    raw_cookie = str(environ.get("HTTP_COOKIE") or "")
    if not raw_cookie:
        return None
    cookie = SimpleCookie()
    cookie.load(raw_cookie)
    morsel = cookie.get(name)
    return morsel.value if morsel is not None else None


def _remote_ip(environ: Mapping[str, Any]) -> str | None:
    # Prefer X-Real-IP set by nginx from $remote_addr — overwritten by nginx, not client-spoofable.
    # X-Forwarded-For leftmost hop is client-controlled and must not be trusted for rate limiting.
    real_ip = str(environ.get("HTTP_X_REAL_IP") or "").strip()
    if real_ip:
        return real_ip
    remote = str(environ.get("REMOTE_ADDR") or "").strip()
    return remote or None


def _request_origin(environ: Mapping[str, Any]) -> str | None:
    origin = str(environ.get("HTTP_ORIGIN") or "").strip()
    return origin or None


def _result_payload(result: RegisterResult | VerifyResult | ResendResult | LoginResult | OnboardingAccessResult) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": bool(result.success)}
    if result.success:
        profile_code = getattr(result, "profile_code", None)
        if profile_code:
            payload["profile_code"] = profile_code
        onboarding_state = getattr(result, "onboarding_state", None)
        if onboarding_state:
            payload["onboarding_state"] = onboarding_state
    else:
        payload["error"] = {"code": str(result.error_code or "UNKNOWN_ERROR")}
    return payload


def _origin_allowed(origin: str | None, allowed_origins: set[str] | None) -> bool:
    """
    When allowed_origins is configured, require the request Origin header
    to match. Missing origin → blocked. Unknown origin → blocked.
    When allowed_origins is None (test/dev mode) → always allowed.
    """
    if allowed_origins is None:
        return True
    if not origin:
        return False
    return origin in allowed_origins


def build_wsgi_app(
    *,
    service: WebsiteRegistrationService,
    allowed_origins: set[str] | None = None,
) -> Callable[[Mapping[str, Any], Callable[..., Any]], list[bytes]]:
    """
    Build the WSGI application.

    allowed_origins: when not None, enforce Origin header validation on all
    state-changing POST routes. Set to {base_url} in production. None in tests.
    """
    session_max_age = int(service.session_ttl / timedelta(seconds=1))

    def application(environ: Mapping[str, Any], start_response: Callable[[str, list[tuple[str, str]]], None]) -> list[bytes]:
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        path = str(environ.get("PATH_INFO") or "")

        if method == "GET" and path == "/synth/web-auth/healthz":
            return _json_response(
                start_response,
                status=HTTPStatus.OK,
                payload={"ok": True, "service": "website_registration_v1", "status": "healthy"},
            )

        # nginx auth_request check-access endpoint (internal, GET)
        if method == "GET" and path == "/synth/web-auth/check-access":
            session_token = _get_cookie_value(environ, SESSION_COOKIE_NAME) or ""
            # Profile slug comes from nginx-set header (extracted from URI regex),
            # never from client-supplied X-Synth-Requested-Profile passthrough.
            # nginx must explicitly set this header from its own capture group.
            requested_profile = str(environ.get("HTTP_X_SYNTH_REQUESTED_PROFILE") or "").strip()
            result = service.check_access(
                session_token=session_token,
                requested_profile_code=requested_profile or None,
            )
            if result.success:
                start_response(
                    "200 OK",
                    [("X-Synth-Profile", result.profile_code or ""),
                     ("Content-Length", "0")],
                )
                return [b""]
            if result.http_status == 403:
                start_response("403 Forbidden", [("Content-Length", "0")])
                return [b""]
            start_response("401 Unauthorized", [("Content-Length", "0")])
            return [b""]

        if method != "POST" or not path.startswith("/synth/web-auth/"):
            return _json_response(
                start_response,
                status=HTTPStatus.NOT_FOUND,
                payload={"ok": False, "error": {"code": "NOT_FOUND"}},
            )

        # CSRF: Origin header validation for state-changing POST routes.
        # Skipped when allowed_origins is None (dev/test mode).
        origin = _request_origin(environ)
        if not _origin_allowed(origin, allowed_origins):
            return _json_response(
                start_response,
                status=HTTPStatus.FORBIDDEN,
                payload={"ok": False, "error": {"code": "ORIGIN_NOT_ALLOWED"}},
            )

        try:
            body = _read_json_body(environ)
        except Exception:
            return _json_response(
                start_response,
                status=HTTPStatus.BAD_REQUEST,
                payload={"ok": False, "error": {"code": "INVALID_JSON_BODY"}},
            )

        if path == "/synth/web-auth/register":
            result = service.register(
                email=str(body.get("email") or ""),
                profile_code=str(body.get("profile_code") or ""),
                password=str(body.get("password") or ""),
                proof_response=str(body.get("proof_response") or ""),
                remote_ip=_remote_ip(environ),
            )
            status = HTTPStatus.OK if result.success else HTTPStatus.BAD_REQUEST
            return _json_response(start_response, status=status, payload=_result_payload(result))

        if path == "/synth/web-auth/resend-verification":
            result = service.resend_verification(login_value=str(body.get("login_value") or ""))
            status = HTTPStatus.OK if result.success else HTTPStatus.TOO_MANY_REQUESTS
            return _json_response(start_response, status=status, payload=_result_payload(result))

        if path == "/synth/web-auth/verify-email":
            token = str(body.get("token") or "")
            if not token:
                query = parse_qs(str(environ.get("QUERY_STRING") or ""), keep_blank_values=False)
                token = str((query.get("token") or [""])[0])
            result = service.verify_email(raw_token=token)
            status = HTTPStatus.OK if result.success else HTTPStatus.BAD_REQUEST
            return _json_response(start_response, status=status, payload=_result_payload(result))

        if path == "/synth/web-auth/login":
            result = service.login(
                login_value=str(body.get("login_value") or ""),
                password=str(body.get("password") or ""),
                remote_ip=_remote_ip(environ),
            )
            headers: list[tuple[str, str]] = []
            if result.success and result.session_token:
                headers.extend(
                    _cookie_headers(
                        session_token=result.session_token,
                        max_age_seconds=session_max_age,
                    )
                )
            status = HTTPStatus.OK if result.success else HTTPStatus.UNAUTHORIZED
            return _json_response(
                start_response,
                status=status,
                payload=_result_payload(result),
                extra_headers=headers,
            )

        if path == "/synth/web-auth/logout":
            session_token = _get_cookie_value(environ, SESSION_COOKIE_NAME) or str(body.get("session_token") or "")
            if session_token:
                service.logout(session_token=session_token)
            return _json_response(
                start_response,
                status=HTTPStatus.OK,
                payload={"ok": True},
                extra_headers=_cookie_headers(session_token="", max_age_seconds=0, clear=True),
            )

        if path == "/synth/web-auth/onboarding-status":
            session_token = _get_cookie_value(environ, SESSION_COOKIE_NAME) or str(body.get("session_token") or "")
            result = service.get_onboarding_access(
                session_token=session_token,
                requested_profile_code=str(body.get("requested_profile_code") or ""),
            )
            status = HTTPStatus.OK if result.success else HTTPStatus.UNAUTHORIZED
            if result.error_code == "FORBIDDEN":
                status = HTTPStatus.FORBIDDEN
            return _json_response(start_response, status=status, payload=_result_payload(result))

        return _json_response(
            start_response,
            status=HTTPStatus.NOT_FOUND,
            payload={"ok": False, "error": {"code": "NOT_FOUND"}},
        )

    return application
