from __future__ import annotations

import ast
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.web.website_registration_v1 import (
    DEFAULT_PROFILE_TIMEZONE,
    MemoryMailer,
    MockProofOfHumanProvider,
    PROFILE_ONBOARDING_NO_EXCHANGE,
    SqliteWebsiteRegistrationRepository,
    USER_STATUS_PENDING,
    WebsiteRegistrationService,
    build_proof_of_human_provider_from_env,
)


def _service() -> tuple[WebsiteRegistrationService, SqliteWebsiteRegistrationRepository, MemoryMailer]:
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
    return service, repo, mailer


def _extract_token(message: dict[str, str]) -> str:
    return message["verification_url"].split("token=", 1)[1]


def test_duplicate_email_rejected_safely() -> None:
    service, _, _ = _service()
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    first = service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=now,
    )
    second = service.register(
        email="hugo@example.com",
        profile_code="hugo2",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=now,
    )
    assert first.success is True
    assert second.success is False
    assert second.error_code == "EMAIL_ALREADY_RESERVED"


def test_duplicate_alias_rejected_safely() -> None:
    service, _, _ = _service()
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    first = service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=now,
    )
    second = service.register(
        email="hugo2@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=now,
    )
    assert first.success is True
    assert second.success is False
    assert second.error_code == "PROFILE_CODE_ALREADY_RESERVED"


def test_invalid_proof_of_human_rejected() -> None:
    service, _, _ = _service()
    result = service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="not-human",
    )
    assert result.success is False
    assert result.error_code == "INVALID_PROOF_OF_HUMAN"


def test_unverified_profile_cannot_log_in() -> None:
    service, _, _ = _service()
    service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
    )
    result = service.login(login_value="hugo@example.com", password="VerySecurePassword123")
    assert result.success is False
    # Returns INVALID_LOGIN (not PROFILE_NOT_VERIFIED) to prevent account enumeration.
    assert result.error_code == "INVALID_LOGIN"


def test_verification_token_is_single_use_and_expires() -> None:
    service, _, mailer = _service()
    start = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=start,
    )
    token = _extract_token(mailer.sent_messages[-1])
    first = service.verify_email(raw_token=token, now_utc=start + timedelta(hours=1))
    second = service.verify_email(raw_token=token, now_utc=start + timedelta(hours=1))
    assert first.success is True
    assert second.success is False
    assert second.error_code == "VERIFICATION_TOKEN_ALREADY_USED"

    service2, _, mailer2 = _service()
    service2.register(
        email="hugo2@example.com",
        profile_code="hugo2",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=start,
    )
    token2 = _extract_token(mailer2.sent_messages[-1])
    expired = service2.verify_email(raw_token=token2, now_utc=start + timedelta(hours=25))
    assert expired.success is False
    assert expired.error_code == "VERIFICATION_TOKEN_EXPIRED"


def test_resend_verification_is_rate_limited() -> None:
    service, _, mailer = _service()
    start = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=start,
    )
    rate_limited = service.resend_verification(
        login_value="hugo",
        now_utc=start + timedelta(minutes=5),
    )
    later = service.resend_verification(
        login_value="hugo",
        now_utc=start + timedelta(minutes=20),
    )
    assert rate_limited.success is False
    assert rate_limited.error_code == "VERIFICATION_RESEND_RATE_LIMITED"
    assert later.success is True
    assert len(mailer.sent_messages) == 2


def test_verified_hugo_receives_no_exchange_onboarding() -> None:
    service, repo, mailer = _service()
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    register = service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=now,
    )
    assert register.success is True
    token = _extract_token(mailer.sent_messages[-1])
    verify = service.verify_email(raw_token=token, now_utc=now + timedelta(minutes=5))
    assert verify.success is True
    login = service.login(
        login_value="hugo",
        password="VerySecurePassword123",
        now_utc=now + timedelta(minutes=6),
    )
    assert login.success is True
    assert login.profile_code == "hugo"
    assert login.onboarding_state == PROFILE_ONBOARDING_NO_EXCHANGE
    onboarding = service.get_onboarding_access(
        session_token=login.session_token or "",
        requested_profile_code="hugo",
        now_utc=now + timedelta(minutes=7),
    )
    assert onboarding.success is True
    assert onboarding.onboarding_state == PROFILE_ONBOARDING_NO_EXCHANGE
    user_row = repo.conn.execute("SELECT status FROM app_user").fetchone()
    assert user_row is not None
    assert user_row["status"] != USER_STATUS_PENDING


def test_exact_profile_access_and_cross_profile_denial() -> None:
    service, _, mailer = _service()
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=now,
    )
    token = _extract_token(mailer.sent_messages[-1])
    service.verify_email(raw_token=token, now_utc=now + timedelta(minutes=1))
    login = service.login(login_value="hugo", password="VerySecurePassword123", now_utc=now + timedelta(minutes=2))
    allowed = service.get_onboarding_access(
        session_token=login.session_token or "",
        requested_profile_code="hugo",
        now_utc=now + timedelta(minutes=3),
    )
    forbidden = service.get_onboarding_access(
        session_token=login.session_token or "",
        requested_profile_code="joost",
        now_utc=now + timedelta(minutes=3),
    )
    anonymous = service.get_onboarding_access(
        session_token="missing",
        requested_profile_code="hugo",
        now_utc=now + timedelta(minutes=3),
    )
    assert allowed.success is True
    assert forbidden.success is False
    assert forbidden.error_code == "FORBIDDEN"
    assert anonymous.success is False
    assert anonymous.error_code == "UNAUTHORIZED"


def test_logout_invalidates_session() -> None:
    service, _, mailer = _service()
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
        now_utc=now,
    )
    token = _extract_token(mailer.sent_messages[-1])
    service.verify_email(raw_token=token, now_utc=now + timedelta(minutes=1))
    login = service.login(login_value="hugo", password="VerySecurePassword123", now_utc=now + timedelta(minutes=2))
    service.logout(session_token=login.session_token or "", now_utc=now + timedelta(minutes=3))
    result = service.get_onboarding_access(
        session_token=login.session_token or "",
        requested_profile_code="hugo",
        now_utc=now + timedelta(minutes=4),
    )
    assert result.success is False
    assert result.error_code == "UNAUTHORIZED"


def test_no_trading_account_or_credential_is_created() -> None:
    service, repo, _ = _service()
    service.register(
        email="hugo@example.com",
        profile_code="hugo",
        password="VerySecurePassword123",
        proof_response="test-human-ok",
    )
    tables = {
        row["name"]
        for row in repo.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert "trading_account" not in tables
    assert "credential" not in tables
    source = Path("src/web/website_registration_v1.py").read_text(encoding="utf-8")
    assert "trading_account" not in source
    assert "BITVAVO_API_KEY" not in source
    assert "BITVAVO_API_SECRET" not in source


def test_mock_provider_allowed_only_in_test_mode() -> None:
    provider = build_proof_of_human_provider_from_env(
        {
            "SYNTH_ENV": "test",
            "SYNTH_PROOF_PROVIDER": "mock",
        }
    )
    assert provider.validate(response="test-human-ok").valid is True
    prod_provider = build_proof_of_human_provider_from_env(
        {
            "SYNTH_ENV": "production",
            "SYNTH_PROOF_PROVIDER": "mock",
        }
    )
    result = prod_provider.validate(response="test-human-ok")
    assert result.valid is False
    assert result.reason == "MOCK_PROOF_PROVIDER_FORBIDDEN"


def test_source_has_no_broker_or_execution_imports() -> None:
    source = Path("src/web/website_registration_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    for module_name in imported_modules:
        assert "decision_gate" not in module_name
        assert "execution_planner" not in module_name
        assert "executor" not in module_name
        assert "bitvavo" not in module_name
    assert DEFAULT_PROFILE_TIMEZONE == "Europe/Amsterdam"


def main() -> None:
    test_duplicate_email_rejected_safely()
    test_duplicate_alias_rejected_safely()
    test_invalid_proof_of_human_rejected()
    test_unverified_profile_cannot_log_in()
    test_verification_token_is_single_use_and_expires()
    test_resend_verification_is_rate_limited()
    test_verified_hugo_receives_no_exchange_onboarding()
    test_exact_profile_access_and_cross_profile_denial()
    test_logout_invalidates_session()
    test_no_trading_account_or_credential_is_created()
    test_mock_provider_allowed_only_in_test_mode()
    test_source_has_no_broker_or_execution_imports()
    print("ok")


if __name__ == "__main__":
    main()
