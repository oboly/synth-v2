from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Protocol


PROFILE_ONBOARDING_NO_EXCHANGE = "NO_EXCHANGE_ACCOUNT_CONNECTED"
USER_STATUS_PENDING = "PENDING_EMAIL_VERIFICATION"
USER_STATUS_ACTIVE = "ACTIVE"
ACCESS_ROLE_OWNER = "OWNER"
DEFAULT_PROFILE_TIMEZONE = "Europe/Amsterdam"
DEFAULT_VERIFICATION_TTL = timedelta(hours=24)
DEFAULT_SESSION_TTL = timedelta(days=14)
PROFILE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


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
    return "scrypt$16384$8$1$" + base64.urlsafe_b64encode(salt).decode("ascii") + "$" + base64.urlsafe_b64encode(digest).decode("ascii")


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


def build_proof_of_human_provider_from_env(env: Mapping[str, str]) -> ProofOfHumanProvider:
    mode = str(env.get("SYNTH_ENV", "")).strip().lower()
    provider = str(env.get("SYNTH_PROOF_PROVIDER", "")).strip().lower()
    if provider == "mock" and mode in {"dev", "test"}:
        return MockProofOfHumanProvider()
    if provider == "turnstile" and env.get("SYNTH_TURNSTILE_SECRET"):
        return DisabledProofOfHumanProvider(reason="TURNSTILE_PROVIDER_NOT_IMPLEMENTED_IN_FOUNDATION")
    return DisabledProofOfHumanProvider(reason="PROOF_PROVIDER_NOT_CONFIGURED")


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
class LoginResult:
    success: bool
    error_code: str | None = None
    session_token: str | None = None
    profile_code: str | None = None
    onboarding_state: str | None = None


@dataclass(frozen=True)
class OnboardingAccessResult:
    success: bool
    error_code: str | None = None
    profile_code: str | None = None
    onboarding_state: str | None = None


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
                rotated_from_session_id INTEGER NULL,
                invalidated_ts_utc TEXT NULL,
                last_seen_ts_utc TEXT NULL
            );
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
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO web_session (
                app_user_id,
                app_profile_id,
                session_hash,
                created_ts_utc,
                expires_ts_utc
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                app_user_id,
                app_profile_id,
                session_hash,
                _utc_text(created_ts_utc),
                _utc_text(expires_ts_utc),
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
                ws.created_ts_utc,
                ws.expires_ts_utc,
                ws.invalidated_ts_utc,
                ap.profile_code,
                ap.onboarding_state
            FROM web_session ws
            JOIN app_profile ap
              ON ap.app_profile_id = ws.app_profile_id
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


class WebsiteRegistrationService:
    def __init__(
        self,
        *,
        repository: SqliteWebsiteRegistrationRepository,
        proof_provider: ProofOfHumanProvider,
        mailer: Mailer,
        base_url: str,
        verification_ttl: timedelta = DEFAULT_VERIFICATION_TTL,
        session_ttl: timedelta = DEFAULT_SESSION_TTL,
        display_timezone: str = DEFAULT_PROFILE_TIMEZONE,
    ) -> None:
        self.repository = repository
        self.proof_provider = proof_provider
        self.mailer = mailer
        self.base_url = base_url.rstrip("/")
        self.verification_ttl = verification_ttl
        self.session_ttl = session_ttl
        self.display_timezone = display_timezone

    def register(
        self,
        *,
        email: str,
        profile_code: str,
        password: str,
        proof_response: str,
        now_utc: datetime | None = None,
    ) -> RegisterResult:
        now = now_utc or utc_now()
        proof = self.proof_provider.validate(response=proof_response)
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
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        expires = now + self.verification_ttl
        self.repository.store_verification_token(
            app_user_id=app_user_id,
            app_profile_id=app_profile_id,
            token_hash=token_hash,
            created_ts_utc=now,
            expires_ts_utc=expires,
        )
        self.mailer.send_verification_email(
            email=email_normalized,
            profile_code=normalized_profile,
            verification_url=f"{self.base_url}/synth/verify-result.html?token={raw_token}",
            expires_ts_utc=expires,
        )
        return RegisterResult(success=True, profile_code=normalized_profile)

    def verify_email(self, *, raw_token: str, now_utc: datetime | None = None) -> VerifyResult:
        now = now_utc or utc_now()
        row = self.repository.lookup_verification_token(_hash_token(raw_token))
        if row is None:
            return VerifyResult(success=False, error_code="INVALID_VERIFICATION_TOKEN")
        if row["used_ts_utc"] is not None:
            return VerifyResult(success=False, error_code="VERIFICATION_TOKEN_ALREADY_USED")
        expires = datetime.fromisoformat(str(row["expires_ts_utc"])).replace(tzinfo=UTC)
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
        now_utc: datetime | None = None,
    ) -> LoginResult:
        now = now_utc or utc_now()
        row = self.repository.find_user_for_login(login_value)
        if row is None:
            return LoginResult(success=False, error_code="INVALID_LOGIN")
        if str(row["status"]) != USER_STATUS_ACTIVE:
            return LoginResult(success=False, error_code="PROFILE_NOT_VERIFIED")
        if not verify_password(password, str(row["password_hash"])):
            return LoginResult(success=False, error_code="INVALID_LOGIN")
        raw_session = secrets.token_urlsafe(32)
        self.repository.create_session(
            app_user_id=int(row["app_user_id"]),
            app_profile_id=int(row["app_profile_id"]),
            session_hash=_hash_token(raw_session),
            created_ts_utc=now,
            expires_ts_utc=now + self.session_ttl,
        )
        return LoginResult(
            success=True,
            session_token=raw_session,
            profile_code=str(row["profile_code"]),
            onboarding_state=str(row["onboarding_state"]),
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
        if row is None:
            return OnboardingAccessResult(success=False, error_code="UNAUTHORIZED")
        if row["invalidated_ts_utc"] is not None:
            return OnboardingAccessResult(success=False, error_code="UNAUTHORIZED")
        expires = datetime.fromisoformat(str(row["expires_ts_utc"])).replace(tzinfo=UTC)
        if expires < now.astimezone(UTC):
            return OnboardingAccessResult(success=False, error_code="SESSION_EXPIRED")
        normalized_profile = normalize_profile_code(requested_profile_code)
        if str(row["profile_code"]) != normalized_profile:
            return OnboardingAccessResult(success=False, error_code="FORBIDDEN")
        return OnboardingAccessResult(
            success=True,
            profile_code=str(row["profile_code"]),
            onboarding_state=str(row["onboarding_state"]),
        )
