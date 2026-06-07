from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any, Callable, Mapping, Protocol

import requests

from src.common.db import get_connection


PROFILE_ONBOARDING_NO_EXCHANGE = "NO_EXCHANGE_ACCOUNT_CONNECTED"
USER_STATUS_PENDING = "PENDING_EMAIL_VERIFICATION"
USER_STATUS_ACTIVE = "ACTIVE"
USER_STATUS_DISABLED = "DISABLED"
ACCESS_ROLE_OWNER = "OWNER"
DEFAULT_PROFILE_TIMEZONE = "Europe/Amsterdam"
DEFAULT_VERIFICATION_TTL = timedelta(hours=24)
DEFAULT_SESSION_TTL = timedelta(days=14)
DEFAULT_SESSION_IDLE_TTL = timedelta(days=7)
DEFAULT_VERIFICATION_RESEND_COOLDOWN = timedelta(minutes=15)
DEFAULT_LOGIN_RATE_LIMIT_WINDOW = timedelta(minutes=15)
DEFAULT_LOGIN_RATE_LIMIT_MAX = 10
PROFILE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
PRODUCTION_ENV_NAMES = {"prod", "production"}


def utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _as_utc_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value)).replace(tzinfo=UTC)


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_profile_code(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not PROFILE_CODE_RE.match(normalized):
        raise ValueError("INVALID_PROFILE_CODE")
    if ".." in normalized or "/" in normalized:
        raise ValueError("INVALID_PROFILE_CODE")
    return normalized


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _hash_ip(ip: str, pepper: str = "") -> str:
    # HMAC-SHA256 with deployment pepper prevents cross-system IP hash correlation
    # and precomputation over the small IPv4 address space.
    # When pepper="" the result is HMAC-SHA256("", ip) — still safer than plain SHA-256.
    return hmac.new(
        pepper.encode("utf-8"),
        str(ip or "").encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=64,
    )
    return (
        "scrypt$16384$8$1$"
        + base64.urlsafe_b64encode(salt).decode("ascii")
        + "$"
        + base64.urlsafe_b64encode(digest).decode("ascii")
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, n_text, r_text, p_text, salt_b64, digest_b64 = password_hash.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_text),
            r=int(r_text),
            p=int(p_text),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def is_production_env(env: Mapping[str, str]) -> bool:
    return str(env.get("SYNTH_ENV", "")).strip().lower() in PRODUCTION_ENV_NAMES


@dataclass(frozen=True)
class ProofValidationResult:
    valid: bool
    reason: str


class ProofOfHumanProvider(Protocol):
    def validate(self, *, response: str, remote_ip: str | None = None) -> ProofValidationResult:
        ...


class Mailer(Protocol):
    def send_verification_email(
        self,
        *,
        email: str,
        profile_code: str,
        verification_url: str,
        expires_ts_utc: datetime,
    ) -> None:
        ...


class WebsiteRegistrationRepository(Protocol):
    def email_exists(self, email_normalized: str) -> bool:
        ...

    def profile_exists(self, profile_code: str) -> bool:
        ...

    def create_pending_registration(
        self,
        *,
        email_normalized: str,
        password_hash_text: str,
        profile_code: str,
        display_timezone: str,
        created_ts_utc: datetime,
    ) -> tuple[int, int]:
        ...

    def store_verification_token(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
        token_hash: str,
        created_ts_utc: datetime,
        expires_ts_utc: datetime,
    ) -> None:
        ...

    def lookup_verification_token(self, token_hash: str) -> Mapping[str, object] | None:
        ...

    def lookup_pending_profile(self, login_value: str) -> Mapping[str, object] | None:
        ...

    def lookup_latest_verification_token(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
    ) -> Mapping[str, object] | None:
        ...

    def activate_verified_profile(
        self,
        *,
        email_verification_token_id: int,
        app_user_id: int,
        app_profile_id: int,
        verified_ts_utc: datetime,
    ) -> None:
        ...

    def find_user_for_login(self, login_value: str) -> Mapping[str, object] | None:
        ...

    def create_session(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
        session_hash: str,
        created_ts_utc: datetime,
        expires_ts_utc: datetime,
        idle_expires_ts_utc: datetime | None = None,
    ) -> None:
        ...

    def lookup_active_session(self, session_hash: str) -> Mapping[str, object] | None:
        ...

    def invalidate_session(self, session_hash: str, invalidated_ts_utc: datetime) -> None:
        ...

    def invalidate_active_sessions_for_user(
        self, app_user_id: int, invalidated_ts_utc: datetime
    ) -> None:
        ...

    def update_session_last_seen(
        self,
        session_hash: str,
        last_seen_ts: datetime,
        idle_expires_ts: datetime,
    ) -> None:
        ...

    def record_login_attempt(
        self, ip_hash: str, attempted_ts: datetime, success: bool
    ) -> None:
        ...

    def count_recent_login_failures(self, ip_hash: str, since_utc: datetime) -> int:
        ...

    def lookup_primary_account_link(self, app_profile_id: int) -> Mapping[str, object] | None:
        """
        Return primary active trading account link row for this profile, or None if unlinked.
        Used only to compute server-side landing_path at login. No broker calls.
        """
        ...


@dataclass(frozen=True)
class MockProofOfHumanProvider:
    accepted_response: str = "test-human-ok"

    def validate(self, *, response: str, remote_ip: str | None = None) -> ProofValidationResult:
        if response == self.accepted_response:
            return ProofValidationResult(valid=True, reason="OK")
        return ProofValidationResult(valid=False, reason="INVALID_PROOF_OF_HUMAN")


@dataclass(frozen=True)
class DisabledProofOfHumanProvider:
    reason: str

    def validate(self, *, response: str, remote_ip: str | None = None) -> ProofValidationResult:
        return ProofValidationResult(valid=False, reason=self.reason)


@dataclass(frozen=True)
class TurnstileProofOfHumanProvider:
    secret_key: str
    verify_url: str = TURNSTILE_VERIFY_URL
    timeout_seconds: int = 10

    def validate(self, *, response: str, remote_ip: str | None = None) -> ProofValidationResult:
        if not str(response or "").strip():
            return ProofValidationResult(valid=False, reason="INVALID_PROOF_OF_HUMAN")
        payload = {
            "secret": self.secret_key,
            "response": response,
        }
        if remote_ip:
            payload["remoteip"] = remote_ip
        try:
            verify_response = requests.post(
                self.verify_url,
                data=payload,
                timeout=self.timeout_seconds,
            )
            verify_response.raise_for_status()
            data = verify_response.json()
        except Exception:
            return ProofValidationResult(valid=False, reason="PROOF_PROVIDER_UNAVAILABLE")
        if bool(data.get("success")):
            return ProofValidationResult(valid=True, reason="OK")
        return ProofValidationResult(valid=False, reason="INVALID_PROOF_OF_HUMAN")


@dataclass
class MemoryMailer:
    sent_messages: list[dict[str, str]]

    def send_verification_email(
        self,
        *,
        email: str,
        profile_code: str,
        verification_url: str,
        expires_ts_utc: datetime,
    ) -> None:
        self.sent_messages.append(
            {
                "email": email,
                "profile_code": profile_code,
                "verification_url": verification_url,
                "expires_ts_utc": _utc_text(expires_ts_utc),
            }
        )


@dataclass(frozen=True)
class FileMailer:
    output_path: str

    def send_verification_email(
        self,
        *,
        email: str,
        profile_code: str,
        verification_url: str,
        expires_ts_utc: datetime,
    ) -> None:
        output = {
            "email": email,
            "profile_code": profile_code,
            "verification_url": verification_url,
            "expires_ts_utc": _utc_text(expires_ts_utc),
        }
        with open(self.output_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(output, sort_keys=True))
            handle.write("\n")


@dataclass(frozen=True)
class SmtpMailer:
    host: str
    port: int
    username: str | None
    password: str | None
    from_address: str
    use_tls: bool = True
    starttls: bool = True
    timeout_seconds: int = 15

    def send_verification_email(
        self,
        *,
        email: str,
        profile_code: str,
        verification_url: str,
        expires_ts_utc: datetime,
    ) -> None:
        message = EmailMessage()
        message["Subject"] = "Verify your SYNTH profile"
        message["From"] = self.from_address
        message["To"] = email
        message.set_content(
            "\n".join(
                [
                    f"Profile: {profile_code}",
                    "",
                    "Complete your SYNTH email verification with the link below:",
                    verification_url,
                    "",
                    f"Expires (UTC): {_utc_text(expires_ts_utc)}",
                ]
            )
        )
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as client:
            if self.starttls:
                client.starttls()
            if self.username:
                client.login(self.username, self.password or "")
            client.send_message(message)


def build_proof_of_human_provider_from_env(env: Mapping[str, str]) -> ProofOfHumanProvider:
    provider = str(env.get("SYNTH_PROOF_PROVIDER", "")).strip().lower()
    if provider == "mock":
        if is_production_env(env):
            return DisabledProofOfHumanProvider(reason="MOCK_PROOF_PROVIDER_FORBIDDEN")
        return MockProofOfHumanProvider()
    if provider == "turnstile":
        secret = str(env.get("SYNTH_TURNSTILE_SECRET", "")).strip()
        if not secret:
            return DisabledProofOfHumanProvider(reason="PROOF_PROVIDER_NOT_CONFIGURED")
        return TurnstileProofOfHumanProvider(secret_key=secret)
    return DisabledProofOfHumanProvider(reason="PROOF_PROVIDER_NOT_CONFIGURED")


def build_mailer_from_env(env: Mapping[str, str]) -> Mailer:
    mailer_mode = str(env.get("SYNTH_MAILER", "")).strip().lower()
    if mailer_mode == "memory":
        if is_production_env(env):
            raise ValueError("MEMORY_MAILER_FORBIDDEN")
        return MemoryMailer(sent_messages=[])
    if mailer_mode == "file":
        if is_production_env(env):
            raise ValueError("FILE_MAILER_FORBIDDEN")
        output_path = str(env.get("SYNTH_FILE_MAILER_PATH", "")).strip()
        if not output_path:
            raise ValueError("FILE_MAILER_PATH_REQUIRED")
        return FileMailer(output_path=output_path)
    host = str(env.get("SYNTH_SMTP_HOST", "")).strip()
    from_address = str(env.get("SYNTH_SMTP_FROM", "")).strip()
    if not host or not from_address:
        raise ValueError("SMTP_NOT_CONFIGURED")
    return SmtpMailer(
        host=host,
        port=int(str(env.get("SYNTH_SMTP_PORT", "587"))),
        username=str(env.get("SYNTH_SMTP_USER", "")).strip() or None,
        password=str(env.get("SYNTH_SMTP_PASSWORD", "")).strip() or None,
        from_address=from_address,
        use_tls=True,
        starttls=str(env.get("SYNTH_SMTP_STARTTLS", "1")).strip() not in {"0", "false", "False"},
    )


@dataclass(frozen=True)
class RegisterResult:
    success: bool
    error_code: str | None = None
    profile_code: str | None = None


@dataclass(frozen=True)
class VerifyResult:
    success: bool
    error_code: str | None = None
    profile_code: str | None = None


@dataclass(frozen=True)
class ResendResult:
    success: bool
    error_code: str | None = None
    profile_code: str | None = None


ACCOUNT_CONNECTION_NONE = "NO_EXCHANGE_ACCOUNT_CONNECTED"
ACCOUNT_CONNECTION_READ_ONLY = "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED"


@dataclass(frozen=True)
class LoginResult:
    success: bool
    error_code: str | None = None
    session_token: str | None = None
    profile_code: str | None = None
    onboarding_state: str | None = None
    landing_path: str | None = None
    account_connection_state: str | None = None


@dataclass(frozen=True)
class OnboardingAccessResult:
    success: bool
    error_code: str | None = None
    profile_code: str | None = None
    onboarding_state: str | None = None


@dataclass(frozen=True)
class CheckAccessResult:
    """Result from the nginx auth_request authorization check."""
    success: bool
    error_code: str | None = None
    profile_code: str | None = None
    # http_status: 200 = allowed, 401 = unauthenticated, 403 = forbidden
    http_status: int = 200


class SqliteWebsiteRegistrationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_user (
                app_user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_normalized TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                created_ts_utc TEXT NOT NULL,
                verified_ts_utc TEXT NULL,
                last_login_ts_utc TEXT NULL
            );
            CREATE TABLE IF NOT EXISTS app_profile (
                app_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_code TEXT NOT NULL UNIQUE,
                display_timezone TEXT NOT NULL,
                onboarding_state TEXT NOT NULL,
                created_ts_utc TEXT NOT NULL,
                activated_ts_utc TEXT NULL
            );
            CREATE TABLE IF NOT EXISTS app_user_profile_access (
                app_user_profile_access_id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_user_id INTEGER NOT NULL,
                app_profile_id INTEGER NOT NULL,
                access_role TEXT NOT NULL,
                created_ts_utc TEXT NOT NULL,
                UNIQUE(app_user_id, app_profile_id)
            );
            CREATE TABLE IF NOT EXISTS email_verification_token (
                email_verification_token_id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_user_id INTEGER NOT NULL,
                app_profile_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_ts_utc TEXT NOT NULL,
                expires_ts_utc TEXT NOT NULL,
                used_ts_utc TEXT NULL
            );
            CREATE TABLE IF NOT EXISTS web_session (
                web_session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_user_id INTEGER NOT NULL,
                app_profile_id INTEGER NOT NULL,
                session_hash TEXT NOT NULL UNIQUE,
                created_ts_utc TEXT NOT NULL,
                expires_ts_utc TEXT NOT NULL,
                idle_expires_ts_utc TEXT NULL,
                rotated_from_session_id INTEGER NULL,
                invalidated_ts_utc TEXT NULL,
                last_seen_ts_utc TEXT NULL
            );
            CREATE TABLE IF NOT EXISTS login_attempt (
                login_attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_hash TEXT NOT NULL,
                attempted_ts_utc TEXT NOT NULL,
                success INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_login_attempt_ip_ts
                ON login_attempt (ip_hash, attempted_ts_utc);
            """
        )
        self.conn.commit()

    def email_exists(self, email_normalized: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM app_user WHERE email_normalized = ?",
            (email_normalized,),
        ).fetchone()
        return row is not None

    def profile_exists(self, profile_code: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM app_profile WHERE profile_code = ?",
            (profile_code,),
        ).fetchone()
        return row is not None

    def create_pending_registration(
        self,
        *,
        email_normalized: str,
        password_hash_text: str,
        profile_code: str,
        display_timezone: str,
        created_ts_utc: datetime,
    ) -> tuple[int, int]:
        cursor = self.conn.execute(
            """
            INSERT INTO app_user (
                email_normalized,
                password_hash,
                status,
                created_ts_utc
            ) VALUES (?, ?, ?, ?)
            """,
            (
                email_normalized,
                password_hash_text,
                USER_STATUS_PENDING,
                _utc_text(created_ts_utc),
            ),
        )
        app_user_id = int(cursor.lastrowid)
        cursor = self.conn.execute(
            """
            INSERT INTO app_profile (
                profile_code,
                display_timezone,
                onboarding_state,
                created_ts_utc
            ) VALUES (?, ?, ?, ?)
            """,
            (
                profile_code,
                display_timezone,
                PROFILE_ONBOARDING_NO_EXCHANGE,
                _utc_text(created_ts_utc),
            ),
        )
        app_profile_id = int(cursor.lastrowid)
        self.conn.execute(
            """
            INSERT INTO app_user_profile_access (
                app_user_id,
                app_profile_id,
                access_role,
                created_ts_utc
            ) VALUES (?, ?, ?, ?)
            """,
            (
                app_user_id,
                app_profile_id,
                ACCESS_ROLE_OWNER,
                _utc_text(created_ts_utc),
            ),
        )
        self.conn.commit()
        return app_user_id, app_profile_id

    def store_verification_token(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
        token_hash: str,
        created_ts_utc: datetime,
        expires_ts_utc: datetime,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO email_verification_token (
                app_user_id,
                app_profile_id,
                token_hash,
                created_ts_utc,
                expires_ts_utc
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                app_user_id,
                app_profile_id,
                token_hash,
                _utc_text(created_ts_utc),
                _utc_text(expires_ts_utc),
            ),
        )
        self.conn.commit()

    def lookup_verification_token(self, token_hash: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT
                evt.email_verification_token_id,
                evt.app_user_id,
                evt.app_profile_id,
                evt.created_ts_utc,
                evt.expires_ts_utc,
                evt.used_ts_utc,
                ap.profile_code
            FROM email_verification_token evt
            JOIN app_profile ap
              ON ap.app_profile_id = evt.app_profile_id
            WHERE evt.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

    def lookup_pending_profile(self, login_value: str) -> sqlite3.Row | None:
        normalized_email = normalize_email(login_value)
        normalized_profile = str(login_value or "").strip().lower()
        return self.conn.execute(
            """
            SELECT
                au.app_user_id,
                au.email_normalized,
                au.status,
                ap.app_profile_id,
                ap.profile_code
            FROM app_user au
            JOIN app_user_profile_access aupa
              ON aupa.app_user_id = au.app_user_id
            JOIN app_profile ap
              ON ap.app_profile_id = aupa.app_profile_id
            WHERE (au.email_normalized = ? OR ap.profile_code = ?)
              AND au.status = ?
            ORDER BY au.app_user_id
            LIMIT 1
            """,
            (normalized_email, normalized_profile, USER_STATUS_PENDING),
        ).fetchone()

    def lookup_latest_verification_token(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
    ) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT created_ts_utc
            FROM email_verification_token
            WHERE app_user_id = ?
              AND app_profile_id = ?
            ORDER BY email_verification_token_id DESC
            LIMIT 1
            """,
            (app_user_id, app_profile_id),
        ).fetchone()

    def activate_verified_profile(
        self,
        *,
        email_verification_token_id: int,
        app_user_id: int,
        app_profile_id: int,
        verified_ts_utc: datetime,
    ) -> None:
        ts_text = _utc_text(verified_ts_utc)
        self.conn.execute(
            "UPDATE email_verification_token SET used_ts_utc = ? WHERE email_verification_token_id = ?",
            (ts_text, email_verification_token_id),
        )
        self.conn.execute(
            "UPDATE app_user SET status = ?, verified_ts_utc = ? WHERE app_user_id = ?",
            (USER_STATUS_ACTIVE, ts_text, app_user_id),
        )
        self.conn.execute(
            "UPDATE app_profile SET activated_ts_utc = ? WHERE app_profile_id = ?",
            (ts_text, app_profile_id),
        )
        self.conn.commit()

    def find_user_for_login(self, login_value: str) -> sqlite3.Row | None:
        normalized_email = normalize_email(login_value)
        normalized_profile = str(login_value or "").strip().lower()
        return self.conn.execute(
            """
            SELECT
                au.app_user_id,
                au.email_normalized,
                au.password_hash,
                au.status,
                ap.app_profile_id,
                ap.profile_code,
                ap.onboarding_state
            FROM app_user au
            JOIN app_user_profile_access aupa
              ON aupa.app_user_id = au.app_user_id
            JOIN app_profile ap
              ON ap.app_profile_id = aupa.app_profile_id
            WHERE au.email_normalized = ?
               OR ap.profile_code = ?
            ORDER BY au.app_user_id
            LIMIT 1
            """,
            (normalized_email, normalized_profile),
        ).fetchone()

    def create_session(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
        session_hash: str,
        created_ts_utc: datetime,
        expires_ts_utc: datetime,
        idle_expires_ts_utc: datetime | None = None,
    ) -> None:
        idle_text = _utc_text(idle_expires_ts_utc) if idle_expires_ts_utc else None
        self.conn.execute(
            """
            INSERT INTO web_session (
                app_user_id,
                app_profile_id,
                session_hash,
                created_ts_utc,
                expires_ts_utc,
                idle_expires_ts_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                app_user_id,
                app_profile_id,
                session_hash,
                _utc_text(created_ts_utc),
                _utc_text(expires_ts_utc),
                idle_text,
            ),
        )
        self.conn.execute(
            "UPDATE app_user SET last_login_ts_utc = ? WHERE app_user_id = ?",
            (_utc_text(created_ts_utc), app_user_id),
        )
        self.conn.commit()

    def lookup_active_session(self, session_hash: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT
                ws.web_session_id,
                ws.app_user_id,
                ws.app_profile_id,
                ws.session_hash,
                ws.created_ts_utc,
                ws.expires_ts_utc,
                ws.idle_expires_ts_utc,
                ws.invalidated_ts_utc,
                ws.last_seen_ts_utc,
                ap.profile_code,
                ap.onboarding_state,
                au.status AS user_status
            FROM web_session ws
            JOIN app_profile ap
              ON ap.app_profile_id = ws.app_profile_id
            JOIN app_user au
              ON au.app_user_id = ws.app_user_id
            WHERE ws.session_hash = ?
            """,
            (session_hash,),
        ).fetchone()

    def invalidate_session(self, session_hash: str, invalidated_ts_utc: datetime) -> None:
        self.conn.execute(
            "UPDATE web_session SET invalidated_ts_utc = ? WHERE session_hash = ? AND invalidated_ts_utc IS NULL",
            (_utc_text(invalidated_ts_utc), session_hash),
        )
        self.conn.commit()

    def invalidate_active_sessions_for_user(
        self, app_user_id: int, invalidated_ts_utc: datetime
    ) -> None:
        self.conn.execute(
            """
            UPDATE web_session
            SET invalidated_ts_utc = ?
            WHERE app_user_id = ?
              AND invalidated_ts_utc IS NULL
            """,
            (_utc_text(invalidated_ts_utc), app_user_id),
        )
        self.conn.commit()

    def update_session_last_seen(
        self,
        session_hash: str,
        last_seen_ts: datetime,
        idle_expires_ts: datetime,
    ) -> None:
        self.conn.execute(
            """
            UPDATE web_session
            SET last_seen_ts_utc = ?, idle_expires_ts_utc = ?
            WHERE session_hash = ?
              AND invalidated_ts_utc IS NULL
            """,
            (_utc_text(last_seen_ts), _utc_text(idle_expires_ts), session_hash),
        )
        self.conn.commit()

    def record_login_attempt(
        self, ip_hash: str, attempted_ts: datetime, success: bool
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO login_attempt (ip_hash, attempted_ts_utc, success)
            VALUES (?, ?, ?)
            """,
            (ip_hash, _utc_text(attempted_ts), 1 if success else 0),
        )
        self.conn.commit()

    def count_recent_login_failures(self, ip_hash: str, since_utc: datetime) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM login_attempt
            WHERE ip_hash = ?
              AND attempted_ts_utc >= ?
              AND success = 0
            """,
            (ip_hash, _utc_text(since_utc)),
        ).fetchone()
        return int(row["n"]) if row else 0

    def lookup_primary_account_link(self, app_profile_id: int) -> Mapping[str, object] | None:
        # app_profile_trading_account_link does not exist in the SQLite test schema.
        # All test profiles are treated as unlinked (landing → onboarding).
        return None


class MariaDbWebsiteRegistrationRepository:
    def __init__(self, connection_factory: Callable[[], Any] | None = None) -> None:
        self._connection_factory = connection_factory or get_connection

    def _with_conn(self, fn: Callable[[Any, Any], Any]) -> Any:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                result = fn(conn, cur)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def email_exists(self, email_normalized: str) -> bool:
        def _run(_conn: Any, cur: Any) -> bool:
            cur.execute("SELECT 1 FROM app_user WHERE email_normalized = %s", (email_normalized,))
            return cur.fetchone() is not None
        return bool(self._with_conn(_run))

    def profile_exists(self, profile_code: str) -> bool:
        def _run(_conn: Any, cur: Any) -> bool:
            cur.execute("SELECT 1 FROM app_profile WHERE profile_code = %s", (profile_code,))
            return cur.fetchone() is not None
        return bool(self._with_conn(_run))

    def create_pending_registration(
        self,
        *,
        email_normalized: str,
        password_hash_text: str,
        profile_code: str,
        display_timezone: str,
        created_ts_utc: datetime,
    ) -> tuple[int, int]:
        def _run(_conn: Any, cur: Any) -> tuple[int, int]:
            cur.execute(
                """
                INSERT INTO app_user (
                    email_normalized,
                    password_hash,
                    status,
                    created_ts_utc
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    email_normalized,
                    password_hash_text,
                    USER_STATUS_PENDING,
                    _utc_text(created_ts_utc),
                ),
            )
            app_user_id = int(cur.lastrowid)
            cur.execute(
                """
                INSERT INTO app_profile (
                    profile_code,
                    display_timezone,
                    onboarding_state,
                    created_ts_utc
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    profile_code,
                    display_timezone,
                    PROFILE_ONBOARDING_NO_EXCHANGE,
                    _utc_text(created_ts_utc),
                ),
            )
            app_profile_id = int(cur.lastrowid)
            cur.execute(
                """
                INSERT INTO app_user_profile_access (
                    app_user_id,
                    app_profile_id,
                    access_role,
                    created_ts_utc
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    app_user_id,
                    app_profile_id,
                    ACCESS_ROLE_OWNER,
                    _utc_text(created_ts_utc),
                ),
            )
            return app_user_id, app_profile_id
        return self._with_conn(_run)

    def store_verification_token(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
        token_hash: str,
        created_ts_utc: datetime,
        expires_ts_utc: datetime,
    ) -> None:
        def _run(_conn: Any, cur: Any) -> None:
            cur.execute(
                """
                INSERT INTO email_verification_token (
                    app_user_id,
                    app_profile_id,
                    token_hash,
                    created_ts_utc,
                    expires_ts_utc
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    app_user_id,
                    app_profile_id,
                    token_hash,
                    _utc_text(created_ts_utc),
                    _utc_text(expires_ts_utc),
                ),
            )
        self._with_conn(_run)

    def lookup_verification_token(self, token_hash: str) -> Mapping[str, object] | None:
        def _run(_conn: Any, cur: Any) -> Mapping[str, object] | None:
            cur.execute(
                """
                SELECT
                    evt.email_verification_token_id,
                    evt.app_user_id,
                    evt.app_profile_id,
                    evt.created_ts_utc,
                    evt.expires_ts_utc,
                    evt.used_ts_utc,
                    ap.profile_code
                FROM email_verification_token evt
                JOIN app_profile ap
                  ON ap.app_profile_id = evt.app_profile_id
                WHERE evt.token_hash = %s
                """,
                (token_hash,),
            )
            return cur.fetchone()
        return self._with_conn(_run)

    def lookup_pending_profile(self, login_value: str) -> Mapping[str, object] | None:
        normalized_email = normalize_email(login_value)
        normalized_profile = str(login_value or "").strip().lower()

        def _run(_conn: Any, cur: Any) -> Mapping[str, object] | None:
            cur.execute(
                """
                SELECT
                    au.app_user_id,
                    au.email_normalized,
                    au.status,
                    ap.app_profile_id,
                    ap.profile_code
                FROM app_user au
                JOIN app_user_profile_access aupa
                  ON aupa.app_user_id = au.app_user_id
                JOIN app_profile ap
                  ON ap.app_profile_id = aupa.app_profile_id
                WHERE (au.email_normalized = %s OR ap.profile_code = %s)
                  AND au.status = %s
                ORDER BY au.app_user_id
                LIMIT 1
                """,
                (normalized_email, normalized_profile, USER_STATUS_PENDING),
            )
            return cur.fetchone()
        return self._with_conn(_run)

    def lookup_latest_verification_token(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
    ) -> Mapping[str, object] | None:
        def _run(_conn: Any, cur: Any) -> Mapping[str, object] | None:
            cur.execute(
                """
                SELECT created_ts_utc
                FROM email_verification_token
                WHERE app_user_id = %s
                  AND app_profile_id = %s
                ORDER BY email_verification_token_id DESC
                LIMIT 1
                """,
                (app_user_id, app_profile_id),
            )
            return cur.fetchone()
        return self._with_conn(_run)

    def activate_verified_profile(
        self,
        *,
        email_verification_token_id: int,
        app_user_id: int,
        app_profile_id: int,
        verified_ts_utc: datetime,
    ) -> None:
        ts_text = _utc_text(verified_ts_utc)

        def _run(_conn: Any, cur: Any) -> None:
            cur.execute(
                "UPDATE email_verification_token SET used_ts_utc = %s WHERE email_verification_token_id = %s",
                (ts_text, email_verification_token_id),
            )
            cur.execute(
                "UPDATE app_user SET status = %s, verified_ts_utc = %s WHERE app_user_id = %s",
                (USER_STATUS_ACTIVE, ts_text, app_user_id),
            )
            cur.execute(
                "UPDATE app_profile SET activated_ts_utc = %s WHERE app_profile_id = %s",
                (ts_text, app_profile_id),
            )
        self._with_conn(_run)

    def find_user_for_login(self, login_value: str) -> Mapping[str, object] | None:
        normalized_email = normalize_email(login_value)
        normalized_profile = str(login_value or "").strip().lower()

        def _run(_conn: Any, cur: Any) -> Mapping[str, object] | None:
            cur.execute(
                """
                SELECT
                    au.app_user_id,
                    au.email_normalized,
                    au.password_hash,
                    au.status,
                    ap.app_profile_id,
                    ap.profile_code,
                    ap.onboarding_state
                FROM app_user au
                JOIN app_user_profile_access aupa
                  ON aupa.app_user_id = au.app_user_id
                JOIN app_profile ap
                  ON ap.app_profile_id = aupa.app_profile_id
                WHERE au.email_normalized = %s
                   OR ap.profile_code = %s
                ORDER BY au.app_user_id
                LIMIT 1
                """,
                (normalized_email, normalized_profile),
            )
            return cur.fetchone()
        return self._with_conn(_run)

    def create_session(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
        session_hash: str,
        created_ts_utc: datetime,
        expires_ts_utc: datetime,
        idle_expires_ts_utc: datetime | None = None,
    ) -> None:
        idle_text = _utc_text(idle_expires_ts_utc) if idle_expires_ts_utc else None

        def _run(_conn: Any, cur: Any) -> None:
            cur.execute(
                """
                INSERT INTO web_session (
                    app_user_id,
                    app_profile_id,
                    session_hash,
                    created_ts_utc,
                    expires_ts_utc,
                    idle_expires_ts_utc
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    app_user_id,
                    app_profile_id,
                    session_hash,
                    _utc_text(created_ts_utc),
                    _utc_text(expires_ts_utc),
                    idle_text,
                ),
            )
            cur.execute(
                "UPDATE app_user SET last_login_ts_utc = %s WHERE app_user_id = %s",
                (_utc_text(created_ts_utc), app_user_id),
            )
        self._with_conn(_run)

    def lookup_active_session(self, session_hash: str) -> Mapping[str, object] | None:
        def _run(_conn: Any, cur: Any) -> Mapping[str, object] | None:
            cur.execute(
                """
                SELECT
                    ws.web_session_id,
                    ws.app_user_id,
                    ws.app_profile_id,
                    ws.session_hash,
                    ws.created_ts_utc,
                    ws.expires_ts_utc,
                    ws.idle_expires_ts_utc,
                    ws.invalidated_ts_utc,
                    ws.last_seen_ts_utc,
                    ap.profile_code,
                    ap.onboarding_state,
                    au.status AS user_status
                FROM web_session ws
                JOIN app_profile ap
                  ON ap.app_profile_id = ws.app_profile_id
                JOIN app_user au
                  ON au.app_user_id = ws.app_user_id
                WHERE ws.session_hash = %s
                """,
                (session_hash,),
            )
            return cur.fetchone()
        return self._with_conn(_run)

    def invalidate_session(self, session_hash: str, invalidated_ts_utc: datetime) -> None:
        def _run(_conn: Any, cur: Any) -> None:
            cur.execute(
                "UPDATE web_session SET invalidated_ts_utc = %s WHERE session_hash = %s AND invalidated_ts_utc IS NULL",
                (_utc_text(invalidated_ts_utc), session_hash),
            )
        self._with_conn(_run)

    def invalidate_active_sessions_for_user(
        self, app_user_id: int, invalidated_ts_utc: datetime
    ) -> None:
        def _run(_conn: Any, cur: Any) -> None:
            cur.execute(
                """
                UPDATE web_session
                SET invalidated_ts_utc = %s
                WHERE app_user_id = %s
                  AND invalidated_ts_utc IS NULL
                """,
                (_utc_text(invalidated_ts_utc), app_user_id),
            )
        self._with_conn(_run)

    def update_session_last_seen(
        self,
        session_hash: str,
        last_seen_ts: datetime,
        idle_expires_ts: datetime,
    ) -> None:
        def _run(_conn: Any, cur: Any) -> None:
            cur.execute(
                """
                UPDATE web_session
                SET last_seen_ts_utc = %s, idle_expires_ts_utc = %s
                WHERE session_hash = %s
                  AND invalidated_ts_utc IS NULL
                """,
                (_utc_text(last_seen_ts), _utc_text(idle_expires_ts), session_hash),
            )
        self._with_conn(_run)

    def record_login_attempt(
        self, ip_hash: str, attempted_ts: datetime, success: bool
    ) -> None:
        def _run(_conn: Any, cur: Any) -> None:
            cur.execute(
                """
                INSERT INTO login_attempt (ip_hash, attempted_ts_utc, success)
                VALUES (%s, %s, %s)
                """,
                (ip_hash, _utc_text(attempted_ts), 1 if success else 0),
            )
        self._with_conn(_run)

    def count_recent_login_failures(self, ip_hash: str, since_utc: datetime) -> int:
        def _run(_conn: Any, cur: Any) -> int:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM login_attempt
                WHERE ip_hash = %s
                  AND attempted_ts_utc >= %s
                  AND success = 0
                """,
                (ip_hash, _utc_text(since_utc)),
            )
            row = cur.fetchone()
            return int(row["n"]) if row else 0
        return int(self._with_conn(_run))

    def lookup_primary_account_link(self, app_profile_id: int) -> Mapping[str, object] | None:
        def _run(_conn: Any, cur: Any) -> Mapping[str, object] | None:
            cur.execute(
                """
                SELECT
                    aptl.link_id,
                    aptl.trading_account_id,
                    aptl.link_status,
                    aptl.is_primary,
                    ta.account_code,
                    ta.venue
                FROM app_profile_trading_account_link aptl
                JOIN trading_account ta
                  ON ta.trading_account_id = aptl.trading_account_id
                WHERE aptl.app_profile_id = %s
                  AND aptl.link_status = 'ACTIVE'
                  AND aptl.is_primary = 1
                ORDER BY aptl.link_id
                LIMIT 2
                """,
                (app_profile_id,),
            )
            rows = cur.fetchall()
            if not rows:
                return None
            if len(rows) > 1:
                raise RuntimeError(
                    f"AMBIGUOUS_PRIMARY_LINK: app_profile_id={app_profile_id} "
                    f"has multiple primary active links"
                )
            return rows[0]
        return self._with_conn(_run)


def _row_get(row: Mapping[str, object], key: str, default: object = None) -> object:
    """sqlite3.Row does not support .get(); this provides a safe fallback."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _validate_session_row(
    row: Mapping[str, object] | None,
    now: datetime,
) -> str | None:
    """
    Validate session row fields. Returns error_code string if invalid, None if valid.
    Checks: exists, not revoked, absolute expiry, idle expiry, user status.
    """
    if row is None:
        return "UNAUTHORIZED"
    if row["invalidated_ts_utc"] is not None:
        return "UNAUTHORIZED"
    expires = _as_utc_datetime(row["expires_ts_utc"])
    if expires < now.astimezone(UTC):
        return "SESSION_EXPIRED"
    idle_raw = _row_get(row, "idle_expires_ts_utc")
    if idle_raw is not None:
        idle_expires = _as_utc_datetime(idle_raw)
        if idle_expires < now.astimezone(UTC):
            return "SESSION_IDLE_EXPIRED"
    user_status = str(_row_get(row, "user_status") or USER_STATUS_ACTIVE)
    if user_status != USER_STATUS_ACTIVE:
        return "UNAUTHORIZED"
    return None


class WebsiteRegistrationService:
    def __init__(
        self,
        *,
        repository: WebsiteRegistrationRepository,
        proof_provider: ProofOfHumanProvider,
        mailer: Mailer,
        base_url: str,
        verification_ttl: timedelta = DEFAULT_VERIFICATION_TTL,
        session_ttl: timedelta = DEFAULT_SESSION_TTL,
        session_idle_ttl: timedelta = DEFAULT_SESSION_IDLE_TTL,
        verification_resend_cooldown: timedelta = DEFAULT_VERIFICATION_RESEND_COOLDOWN,
        login_rate_limit_window: timedelta = DEFAULT_LOGIN_RATE_LIMIT_WINDOW,
        login_rate_limit_max: int = DEFAULT_LOGIN_RATE_LIMIT_MAX,
        display_timezone: str = DEFAULT_PROFILE_TIMEZONE,
        ip_hash_pepper: str = "",
    ) -> None:
        self.repository = repository
        self.proof_provider = proof_provider
        self.mailer = mailer
        self.base_url = base_url.rstrip("/")
        self.verification_ttl = verification_ttl
        self.session_ttl = session_ttl
        self.session_idle_ttl = session_idle_ttl
        self.verification_resend_cooldown = verification_resend_cooldown
        self.login_rate_limit_window = login_rate_limit_window
        self.login_rate_limit_max = login_rate_limit_max
        self.display_timezone = display_timezone
        self.ip_hash_pepper = ip_hash_pepper

    def register(
        self,
        *,
        email: str,
        profile_code: str,
        password: str,
        proof_response: str,
        remote_ip: str | None = None,
        now_utc: datetime | None = None,
    ) -> RegisterResult:
        now = now_utc or utc_now()
        proof = self.proof_provider.validate(response=proof_response, remote_ip=remote_ip)
        if not proof.valid:
            return RegisterResult(success=False, error_code=proof.reason)
        email_normalized = normalize_email(email)
        try:
            normalized_profile = normalize_profile_code(profile_code)
        except ValueError as exc:
            return RegisterResult(success=False, error_code=str(exc))
        if self.repository.email_exists(email_normalized):
            return RegisterResult(success=False, error_code="EMAIL_ALREADY_RESERVED")
        if self.repository.profile_exists(normalized_profile):
            return RegisterResult(success=False, error_code="PROFILE_CODE_ALREADY_RESERVED")
        app_user_id, app_profile_id = self.repository.create_pending_registration(
            email_normalized=email_normalized,
            password_hash_text=hash_password(password),
            profile_code=normalized_profile,
            display_timezone=self.display_timezone,
            created_ts_utc=now,
        )
        self._issue_verification_token(
            app_user_id=app_user_id,
            app_profile_id=app_profile_id,
            email=email_normalized,
            profile_code=normalized_profile,
            now_utc=now,
        )
        return RegisterResult(success=True, profile_code=normalized_profile)

    def _issue_verification_token(
        self,
        *,
        app_user_id: int,
        app_profile_id: int,
        email: str,
        profile_code: str,
        now_utc: datetime,
    ) -> None:
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        expires = now_utc + self.verification_ttl
        self.repository.store_verification_token(
            app_user_id=app_user_id,
            app_profile_id=app_profile_id,
            token_hash=token_hash,
            created_ts_utc=now_utc,
            expires_ts_utc=expires,
        )
        self.mailer.send_verification_email(
            email=email,
            profile_code=profile_code,
            verification_url=f"{self.base_url}/synth/verify-result.html?token={raw_token}",
            expires_ts_utc=expires,
        )

    def resend_verification(
        self,
        *,
        login_value: str,
        now_utc: datetime | None = None,
    ) -> ResendResult:
        now = now_utc or utc_now()
        row = self.repository.lookup_pending_profile(login_value)
        if row is None:
            return ResendResult(success=True)
        latest = self.repository.lookup_latest_verification_token(
            app_user_id=int(row["app_user_id"]),
            app_profile_id=int(row["app_profile_id"]),
        )
        if latest is not None:
            latest_created = _as_utc_datetime(latest["created_ts_utc"])
            if latest_created + self.verification_resend_cooldown > now.astimezone(UTC):
                return ResendResult(success=False, error_code="VERIFICATION_RESEND_RATE_LIMITED")
        self._issue_verification_token(
            app_user_id=int(row["app_user_id"]),
            app_profile_id=int(row["app_profile_id"]),
            email=str(row["email_normalized"]),
            profile_code=str(row["profile_code"]),
            now_utc=now,
        )
        return ResendResult(success=True, profile_code=str(row["profile_code"]))

    def verify_email(self, *, raw_token: str, now_utc: datetime | None = None) -> VerifyResult:
        now = now_utc or utc_now()
        row = self.repository.lookup_verification_token(_hash_token(raw_token))
        if row is None:
            return VerifyResult(success=False, error_code="INVALID_VERIFICATION_TOKEN")
        if row["used_ts_utc"] is not None:
            return VerifyResult(success=False, error_code="VERIFICATION_TOKEN_ALREADY_USED")
        expires = _as_utc_datetime(row["expires_ts_utc"])
        if expires < now.astimezone(UTC):
            return VerifyResult(success=False, error_code="VERIFICATION_TOKEN_EXPIRED")
        self.repository.activate_verified_profile(
            email_verification_token_id=int(row["email_verification_token_id"]),
            app_user_id=int(row["app_user_id"]),
            app_profile_id=int(row["app_profile_id"]),
            verified_ts_utc=now,
        )
        return VerifyResult(success=True, profile_code=str(row["profile_code"]))

    def login(
        self,
        *,
        login_value: str,
        password: str,
        remote_ip: str | None = None,
        now_utc: datetime | None = None,
    ) -> LoginResult:
        now = now_utc or utc_now()
        ip_hash = _hash_ip(remote_ip or "", self.ip_hash_pepper)
        rate_limit_since = (now - self.login_rate_limit_window).astimezone(UTC)
        if self.repository.count_recent_login_failures(ip_hash, rate_limit_since) >= self.login_rate_limit_max:
            return LoginResult(success=False, error_code="LOGIN_RATE_LIMITED")
        row = self.repository.find_user_for_login(login_value)
        if row is None:
            self.repository.record_login_attempt(ip_hash, now, success=False)
            return LoginResult(success=False, error_code="INVALID_LOGIN")
        if str(row["status"]) != USER_STATUS_ACTIVE:
            # Return same error as wrong password to prevent account enumeration.
            self.repository.record_login_attempt(ip_hash, now, success=False)
            return LoginResult(success=False, error_code="INVALID_LOGIN")
        if not verify_password(password, str(row["password_hash"])):
            self.repository.record_login_attempt(ip_hash, now, success=False)
            return LoginResult(success=False, error_code="INVALID_LOGIN")
        # Session rotation: invalidate all existing sessions for this user
        self.repository.invalidate_active_sessions_for_user(int(row["app_user_id"]), now)
        raw_session = secrets.token_urlsafe(32)
        self.repository.create_session(
            app_user_id=int(row["app_user_id"]),
            app_profile_id=int(row["app_profile_id"]),
            session_hash=_hash_token(raw_session),
            created_ts_utc=now,
            expires_ts_utc=now + self.session_ttl,
            idle_expires_ts_utc=now + self.session_idle_ttl,
        )
        self.repository.record_login_attempt(ip_hash, now, success=True)
        profile_code = str(row["profile_code"])
        # Compute server-side landing from explicit DB link. Never infer from profile name.
        try:
            link = self.repository.lookup_primary_account_link(int(row["app_profile_id"]))
        except RuntimeError:
            link = None  # Ambiguous: route to onboarding
        if link is not None:
            landing_path = f"/synth/accounts/{profile_code}/"
            account_connection_state = ACCOUNT_CONNECTION_READ_ONLY
        else:
            landing_path = "/synth/onboarding.html"
            account_connection_state = ACCOUNT_CONNECTION_NONE
        return LoginResult(
            success=True,
            session_token=raw_session,
            profile_code=profile_code,
            onboarding_state=str(row["onboarding_state"]),
            landing_path=landing_path,
            account_connection_state=account_connection_state,
        )

    def logout(self, *, session_token: str, now_utc: datetime | None = None) -> None:
        self.repository.invalidate_session(_hash_token(session_token), now_utc or utc_now())

    def get_onboarding_access(
        self,
        *,
        session_token: str,
        requested_profile_code: str,
        now_utc: datetime | None = None,
    ) -> OnboardingAccessResult:
        now = now_utc or utc_now()
        row = self.repository.lookup_active_session(_hash_token(session_token))
        error = _validate_session_row(row, now)
        if error:
            status = 401 if error != "FORBIDDEN" else 403
            return OnboardingAccessResult(success=False, error_code=error)
        try:
            normalized_profile = normalize_profile_code(requested_profile_code)
        except ValueError:
            return OnboardingAccessResult(success=False, error_code="FORBIDDEN")
        if str(row["profile_code"]) != normalized_profile:
            return OnboardingAccessResult(success=False, error_code="FORBIDDEN")
        return OnboardingAccessResult(
            success=True,
            profile_code=str(row["profile_code"]),
            onboarding_state=str(row["onboarding_state"]),
        )

    def check_access(
        self,
        *,
        session_token: str,
        requested_profile_code: str | None = None,
        now_utc: datetime | None = None,
    ) -> CheckAccessResult:
        """
        Authorization endpoint for nginx auth_request.

        Validates session, user status, idle expiry, and (when provided)
        profile ownership. Updates last_seen and extends idle expiry on
        successful access.

        The requested_profile_code MUST come from an nginx-controlled variable
        (URI regex capture group), never from a client-supplied header.
        """
        now = now_utc or utc_now()
        if not session_token:
            return CheckAccessResult(success=False, error_code="UNAUTHORIZED", http_status=401)
        session_hash = _hash_token(session_token)
        row = self.repository.lookup_active_session(session_hash)
        error = _validate_session_row(row, now)
        if error:
            http_status = 401
            return CheckAccessResult(success=False, error_code=error, http_status=http_status)
        # Validate profile ownership when a specific profile is requested
        if requested_profile_code:
            try:
                normalized_profile = normalize_profile_code(requested_profile_code)
            except ValueError:
                return CheckAccessResult(success=False, error_code="FORBIDDEN", http_status=403)
            if str(row["profile_code"]) != normalized_profile:
                return CheckAccessResult(success=False, error_code="FORBIDDEN", http_status=403)
        # Update session last_seen and extend idle expiry
        try:
            self.repository.update_session_last_seen(
                session_hash=session_hash,
                last_seen_ts=now,
                idle_expires_ts=now + self.session_idle_ttl,
            )
        except Exception:
            pass  # Non-fatal: access is still granted if update fails
        return CheckAccessResult(
            success=True,
            profile_code=str(row["profile_code"]),
            http_status=200,
        )
