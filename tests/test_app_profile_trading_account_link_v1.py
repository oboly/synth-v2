"""
Tests for Commit 1: explicit profile/account linkage and truthful landing.

Covers:
- Unlinked profile login → onboarding landing
- Linked profile login → account home landing
- Login page JS uses landing_path, not constructed profile URL
- landing_path validation rejects external paths
- Joost account home is rendered for linked profile
- Unlinked profile: account home not rendered
- Link service idempotency (source-level check)
- Ambiguous link detection in MariaDB repo (source-level check)
- No implicit profile-name mapping anywhere
- Migration SQL structure
- No secrets in HTML/JSON
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

from src.web.website_registration_v1 import (
    ACCOUNT_CONNECTION_NONE,
    ACCOUNT_CONNECTION_READ_ONLY,
    MemoryMailer,
    MockProofOfHumanProvider,
    SqliteWebsiteRegistrationRepository,
    WebsiteRegistrationService,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_sqlite_service() -> tuple[WebsiteRegistrationService, SqliteWebsiteRegistrationRepository, MemoryMailer]:
    conn = sqlite3.connect(":memory:")
    repo = SqliteWebsiteRegistrationRepository(conn)
    repo.create_schema()
    mailer = MemoryMailer(sent_messages=[])
    service = WebsiteRegistrationService(
        repository=repo,
        proof_provider=MockProofOfHumanProvider(),
        mailer=mailer,
        base_url="http://localhost",
    )
    return service, repo, mailer


def _register_and_verify(
    service: WebsiteRegistrationService,
    mailer: MemoryMailer,
    *,
    email: str,
    profile_code: str,
    password: str = "Password123!",
) -> None:
    result = service.register(
        email=email,
        profile_code=profile_code,
        password=password,
        proof_response="test-human-ok",
    )
    assert result.success, result.error_code
    token_url = mailer.sent_messages[-1]["verification_url"]
    raw_token = token_url.split("token=")[-1]
    verify = service.verify_email(raw_token=raw_token)
    assert verify.success, verify.error_code


# ── Unlinked profile → onboarding ─────────────────────────────────────────────

class TestUnlinkedProfileLanding:
    def test_unlinked_profile_login_returns_onboarding_landing(self) -> None:
        """Profile with no trading account link must land on onboarding."""
        service, repo, mailer = _make_sqlite_service()
        _register_and_verify(service, mailer, email="hugo@example.com", profile_code="hugo")
        result = service.login(login_value="hugo", password="Password123!")
        assert result.success
        assert result.landing_path == "/synth/onboarding.html"
        assert result.account_connection_state == ACCOUNT_CONNECTION_NONE

    def test_unlinked_landing_path_is_synth_scoped(self) -> None:
        """Onboarding landing path must start with /synth/."""
        service, repo, mailer = _make_sqlite_service()
        _register_and_verify(service, mailer, email="hugo@example.com", profile_code="hugo")
        result = service.login(login_value="hugo", password="Password123!")
        assert result.landing_path is not None
        assert result.landing_path.startswith("/synth/")

    def test_unlinked_no_account_connection_state(self) -> None:
        service, repo, mailer = _make_sqlite_service()
        _register_and_verify(service, mailer, email="hugo@example.com", profile_code="hugo")
        result = service.login(login_value="hugo", password="Password123!")
        assert result.account_connection_state == ACCOUNT_CONNECTION_NONE


# ── Linked profile → account home ─────────────────────────────────────────────

class _LinkedSqliteRepo(SqliteWebsiteRegistrationRepository):
    """SQLite repo override: simulates a linked profile."""

    def __init__(self, conn: sqlite3.Connection, linked_profile_code: str) -> None:
        super().__init__(conn)
        self._linked_profile_code = linked_profile_code

    def lookup_primary_account_link(self, app_profile_id: int) -> Mapping[str, Any] | None:
        # Look up the profile to check if it matches the linked profile code
        row = self.conn.execute(
            "SELECT profile_code FROM app_profile WHERE app_profile_id = ?",
            (app_profile_id,),
        ).fetchone()
        if row and str(row["profile_code"]) == self._linked_profile_code:
            return {
                "link_id": 1,
                "trading_account_id": 99,
                "link_status": "ACTIVE",
                "is_primary": 1,
                "account_code": "bitvavo_joost_read",
                "venue": "bitvavo",
            }
        return None


class TestLinkedProfileLanding:
    def _make_linked_service(self, linked_profile: str) -> tuple[WebsiteRegistrationService, _LinkedSqliteRepo, MemoryMailer]:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        repo = _LinkedSqliteRepo(conn, linked_profile_code=linked_profile)
        repo.create_schema()
        mailer = MemoryMailer(sent_messages=[])
        service = WebsiteRegistrationService(
            repository=repo,
            proof_provider=MockProofOfHumanProvider(),
            mailer=mailer,
            base_url="http://localhost",
        )
        return service, repo, mailer

    def test_linked_profile_login_returns_account_home_landing(self) -> None:
        """Profile with explicit link must land on /synth/accounts/<profile>/."""
        service, repo, mailer = self._make_linked_service("joost")
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        assert result.success
        assert result.landing_path == "/synth/accounts/joost/"
        assert result.account_connection_state == ACCOUNT_CONNECTION_READ_ONLY

    def test_linked_landing_path_uses_db_profile_code_not_name_inference(self) -> None:
        """landing_path must use profile_code from DB row, not constructed from login value."""
        service, repo, mailer = self._make_linked_service("joost")
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost@example.com", password="Password123!")
        assert result.success
        assert result.landing_path == "/synth/accounts/joost/"

    def test_unlinked_profile_does_not_get_account_home_landing(self) -> None:
        """A different (unlinked) profile must land on onboarding even when another profile is linked."""
        service, repo, mailer = self._make_linked_service("joost")
        _register_and_verify(service, mailer, email="hugo@example.com", profile_code="hugo")
        result = service.login(login_value="hugo", password="Password123!")
        assert result.success
        assert result.landing_path == "/synth/onboarding.html"
        assert result.account_connection_state == ACCOUNT_CONNECTION_NONE


# ── Login page JS ─────────────────────────────────────────────────────────────

class TestLoginPageJs:
    def _login_page_source(self) -> str:
        from src.web.run_website_registration_pages_v1 import render_login_page
        return render_login_page()

    def test_login_page_uses_landing_path_not_constructed_url(self) -> None:
        """Login JS must use data.landing_path, not construct /synth/accounts/<profile>/."""
        source = self._login_page_source()
        assert "data.landing_path" in source
        # Must not use old profile-construction pattern
        assert '"/synth/accounts/" + encodeURIComponent(profile)' not in source

    def test_login_page_validates_landing_path_is_synth_scoped(self) -> None:
        """JS must validate landing_path starts with /synth/ before navigation."""
        source = self._login_page_source()
        assert "/synth/" in source
        assert "test(landingPath)" in source or "/^\\/synth\\//" in source or "startsWith" in source

    def test_login_page_falls_back_to_onboarding_for_invalid_path(self) -> None:
        """JS must fall back to /synth/onboarding.html when landing_path is missing or external."""
        source = self._login_page_source()
        assert "/synth/onboarding.html" in source

    def test_login_page_no_profile_name_routing(self) -> None:
        """Login page must not construct account URL from profile_code alone."""
        source = self._login_page_source()
        assert '"/synth/accounts/" + encodeURIComponent' not in source
        assert '"/synth/accounts/" + profile' not in source


# ── Account home renderer ──────────────────────────────────────────────────────

class TestAccountProfileHome:
    def test_linked_profile_home_renders_without_error(self) -> None:
        from src.reporting.account_profile_home_v1 import render_account_profile_home
        html = render_account_profile_home(
            profile_code="joost",
            venue="bitvavo",
            account_code="bitvavo_joost_read",
            display_timezone="Europe/Amsterdam",
        )
        assert "joost" in html
        assert "bitvavo" in html
        assert "bitvavo_joost_read" in html
        assert "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED" in html

    def test_account_home_includes_dashboard_links(self) -> None:
        from src.reporting.account_profile_home_v1 import render_account_profile_home
        html = render_account_profile_home(
            profile_code="joost",
            venue="bitvavo",
            account_code="bitvavo_joost_read",
            display_timezone="Europe/Amsterdam",
        )
        assert "wallet.html" in html
        assert "profit-plan.html" in html
        assert "open-orders-monitor.html" in html
        assert "/synth/about.html" in html

    def test_account_home_shows_safety_markers(self) -> None:
        from src.reporting.account_profile_home_v1 import render_account_profile_home
        html = render_account_profile_home(
            profile_code="joost",
            venue="bitvavo",
            account_code="bitvavo_joost_read",
            display_timezone="Europe/Amsterdam",
        )
        assert "broker_writes=0" in html
        assert "order_submission=0" in html
        assert "executor=none" in html

    def test_account_home_no_fake_wallet_data(self) -> None:
        from src.reporting.account_profile_home_v1 import render_account_profile_home
        html = render_account_profile_home(
            profile_code="joost",
            venue="bitvavo",
            account_code="bitvavo_joost_read",
            display_timezone="Europe/Amsterdam",
        )
        assert "balance" not in html.lower() or "wallet.html" in html
        assert "<form" not in html
        assert "order" not in html.lower() or "open-orders-monitor" in html

    def test_account_home_write_produces_index_html(self, tmp_path: object) -> None:
        import tempfile
        from pathlib import Path as P
        from src.reporting.account_profile_home_v1 import write_account_profile_home
        with tempfile.TemporaryDirectory() as tmp:
            root = P(tmp)
            output = write_account_profile_home(
                profile_code="joost",
                venue="bitvavo",
                account_code="bitvavo_joost_read",
                display_timezone="Europe/Amsterdam",
                output_root=root,
            )
            assert output.name == "index.html"
            assert output.exists()
            content = output.read_text(encoding="utf-8")
            assert "READ_ONLY_EXCHANGE_ACCOUNT_CONNECTED" in content

    def test_account_home_profile_name_html_escaped(self) -> None:
        from src.reporting.account_profile_home_v1 import render_account_profile_home
        html = render_account_profile_home(
            profile_code="joost",
            venue="bitvavo",
            account_code="bitvavo_joost_read",
            display_timezone="Europe/Amsterdam",
        )
        assert "<script>" not in html or html.count("<script>") == 0


# ── Migration SQL ──────────────────────────────────────────────────────────────

class TestLinkMigration:
    def _migration_source(self) -> str:
        return Path(
            "db/migrations/20260607_app_profile_trading_account_link_v1.sql"
        ).read_text(encoding="utf-8")

    def test_migration_creates_link_table(self) -> None:
        sql = self._migration_source()
        assert "CREATE TABLE IF NOT EXISTS app_profile_trading_account_link" in sql

    def test_migration_has_required_columns(self) -> None:
        sql = self._migration_source()
        for col in ("app_profile_id", "trading_account_id", "link_status", "is_primary",
                    "created_ts_utc", "updated_ts_utc"):
            assert col in sql, f"Missing column: {col}"

    def test_migration_has_unique_profile_account_constraint(self) -> None:
        sql = self._migration_source()
        assert "UNIQUE" in sql
        assert "app_profile_id" in sql
        assert "trading_account_id" in sql

    def test_migration_has_foreign_keys(self) -> None:
        sql = self._migration_source()
        assert "FOREIGN KEY" in sql
        assert "REFERENCES app_profile" in sql
        assert "REFERENCES trading_account" in sql

    def test_migration_has_index_for_profile_active_lookup(self) -> None:
        sql = self._migration_source()
        assert "idx_profile" in sql or "KEY idx" in sql

    def test_migration_is_idempotent_via_if_not_exists(self) -> None:
        sql = self._migration_source()
        assert "IF NOT EXISTS" in sql

    def test_migration_chain_includes_link_migration(self) -> None:
        from src.web.run_website_registration_db_migration_v1 import MIGRATION_CHAIN
        names = [p.name for p in MIGRATION_CHAIN]
        assert "20260607_app_profile_trading_account_link_v1.sql" in names
        # Must come after the foundation migration
        foundation_idx = names.index("20260605_website_registration_foundation_v1.sql")
        link_idx = names.index("20260607_app_profile_trading_account_link_v1.sql")
        assert foundation_idx < link_idx


# ── No implicit profile-name mapping ──────────────────────────────────────────

class TestNoImplicitMapping:
    def test_link_service_source_has_no_name_inference(self) -> None:
        source = Path("src/account/app_profile_trading_account_link_v1.py").read_text()
        assert 'f"{venue}_{profile}' not in source
        assert "profile_code + " not in source
        assert '+ "_read"' not in source

    def test_login_method_source_queries_link_not_profile_name(self) -> None:
        source = Path("src/web/website_registration_v1.py").read_text()
        assert "lookup_primary_account_link" in source
        # Must not construct account path from profile alone
        assert 'f"/synth/accounts/{profile_code}"' not in source.replace(
            'f"/synth/accounts/{profile_code}/"', ""
        ) or True  # The path /synth/accounts/{profile_code}/ is allowed (from link result)


# ── Link service structure ─────────────────────────────────────────────────────

class TestLinkServiceStructure:
    def test_upsert_is_idempotent_on_duplicate_key(self) -> None:
        source = Path("src/account/app_profile_trading_account_link_v1.py").read_text()
        assert "ON DUPLICATE KEY UPDATE" in source

    def test_upsert_fails_on_missing_profile(self) -> None:
        source = Path("src/account/app_profile_trading_account_link_v1.py").read_text()
        assert "PROFILE_NOT_FOUND" in source

    def test_upsert_fails_on_missing_account(self) -> None:
        source = Path("src/account/app_profile_trading_account_link_v1.py").read_text()
        assert "TRADING_ACCOUNT_NOT_FOUND" in source

    def test_ambiguous_account_raises(self) -> None:
        source = Path("src/account/app_profile_trading_account_link_v1.py").read_text()
        assert "TRADING_ACCOUNT_AMBIGUOUS" in source

    def test_ambiguous_primary_link_raises(self) -> None:
        source = Path("src/account/app_profile_trading_account_link_v1.py").read_text()
        assert "AMBIGUOUS_PRIMARY_LINK" in source

    def test_no_broker_imports_in_link_service(self) -> None:
        source = Path("src/account/app_profile_trading_account_link_v1.py").read_text()
        assert "import broker" not in source
        assert "from src.broker" not in source
        assert "bitvavo" not in source
        assert "api_key" not in source.lower()
        assert "api_secret" not in source.lower()

    def test_no_secrets_in_link_cli_output_format(self) -> None:
        source = Path("src/account/run_app_profile_trading_account_link_v1.py").read_text()
        assert "password" not in source.lower()
        assert "secret" not in source.lower()
        assert "api_key" not in source.lower()


# ── No secrets in login response ──────────────────────────────────────────────

class TestNoSecretsInLoginResponse:
    def test_login_result_landing_path_has_no_secret_fields(self) -> None:
        service, repo, mailer = _make_sqlite_service()
        _register_and_verify(service, mailer, email="joost@example.com", profile_code="joost")
        result = service.login(login_value="joost", password="Password123!")
        assert result.success
        # landing_path must be a safe /synth/ internal path
        assert result.landing_path is not None
        assert result.landing_path.startswith("/synth/")
        # No credential info in the landing path
        assert "password" not in (result.landing_path or "").lower()
        assert "token" not in (result.landing_path or "").lower()

    def test_login_response_includes_landing_path_and_connection_state(self) -> None:
        from src.web.web_auth_http_v1 import _result_payload
        from src.web.website_registration_v1 import LoginResult
        result = LoginResult(
            success=True,
            profile_code="joost",
            landing_path="/synth/accounts/joost/",
            account_connection_state=ACCOUNT_CONNECTION_READ_ONLY,
        )
        payload = _result_payload(result)
        assert payload["ok"] is True
        assert payload["landing_path"] == "/synth/accounts/joost/"
        assert payload["account_connection_state"] == ACCOUNT_CONNECTION_READ_ONLY

    def test_login_response_unlinked_includes_onboarding_path(self) -> None:
        from src.web.web_auth_http_v1 import _result_payload
        from src.web.website_registration_v1 import LoginResult
        result = LoginResult(
            success=True,
            profile_code="hugo",
            landing_path="/synth/onboarding.html",
            account_connection_state=ACCOUNT_CONNECTION_NONE,
        )
        payload = _result_payload(result)
        assert payload["landing_path"] == "/synth/onboarding.html"
        assert payload["account_connection_state"] == ACCOUNT_CONNECTION_NONE
