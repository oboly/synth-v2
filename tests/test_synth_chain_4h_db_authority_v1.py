from __future__ import annotations

import os
from pathlib import Path
import re

import pytest

from src.operations import run_synth_chain_4h_db_grant_preflight_v1 as runner
from src.operations.synth_chain_4h_db_authority_v1 import (
    EXPECTED_GRANT_IDENTITY,
    IDENTITY_HOST,
    IDENTITY_NAME,
    OPERATIONAL_DATABASE,
    REQUIRED_OBJECT_PRIVILEGES,
    SELECT,
    audit_grants,
    parse_grant_statement,
)


SQL_ARTIFACT = Path("db/dba/synth_chain_4h_writer_v1.sql")


def _grant(object_name: str, privileges: set[str] | frozenset[str]) -> str:
    rendered = ", ".join(sorted(privileges))
    return (
        f"GRANT {rendered} ON `{OPERATIONAL_DATABASE}`.`{object_name}` "
        f"TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`"
    )


def _exact_grants() -> list[str]:
    return [
        f"GRANT USAGE ON *.* TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`",
        *[
            _grant(object_name, privileges)
            for object_name, privileges in REQUIRED_OBJECT_PRIVILEGES.items()
        ],
    ]


def _audit(grants: list[str]):
    return audit_grants(
        grant_identity=EXPECTED_GRANT_IDENTITY,
        database_name=OPERATIONAL_DATABASE,
        grant_statements=grants,
    )


# Tables reachable from scripts/run_chain_4h.sh that are written with
# `INSERT ... ON DUPLICATE KEY UPDATE`. MariaDB requires SELECT on the target
# table for this statement form even when the UPDATE clause only assigns
# VALUES(); a missing SELECT fails at runtime with error 1143, as proven by
# the native_short_4h_chain devlap acceptance run. This is a fixed, manually
# reviewed list of proven upsert targets, not a general SQL scan.
REACHABLE_UPSERT_TARGETS = frozenset(
    {
        "advice_state",
        "asset_interval_quality",
        "execution_zone_context",
        "feat_candle",
        "fib_observation_v2",
        "native_short_scope_status_v1",
        "paper_advice_observation",
        "ranking_state",
        "selection_state",
        "signal_engine_state",
        "trade_setup_filter_observation",
        "trade_setup_policy_preview_observation",
        "zone_observation_v2",
    }
)


def test_reachable_upsert_targets_require_select() -> None:
    missing_select = sorted(
        object_name
        for object_name in REACHABLE_UPSERT_TARGETS
        if SELECT not in REQUIRED_OBJECT_PRIVILEGES.get(object_name, frozenset())
    )
    assert missing_select == [], (
        "INSERT ... ON DUPLICATE KEY UPDATE targets reachable from "
        f"scripts/run_chain_4h.sh must grant SELECT: {missing_select}"
    )


def test_exact_grant_set_is_accepted() -> None:
    audit = _audit(_exact_grants())
    assert audit.passed
    assert audit.missing == ()
    assert audit.unexpected == ()
    assert audit.violations == ()


def test_missing_required_select_is_rejected() -> None:
    grants = [
        grant
        for grant in _exact_grants()
        if "`.`market_price_snapshot`" not in grant
    ]
    audit = _audit(grants)
    assert not audit.passed
    assert "synth.market_price_snapshot:SELECT" in audit.missing


def test_missing_required_writer_privilege_is_rejected() -> None:
    grants = [
        grant
        for grant in _exact_grants()
        if "`.`strategy_runtime_snapshot`" not in grant
    ]
    audit = _audit(grants)
    assert not audit.passed
    assert "synth.strategy_runtime_snapshot:INSERT" in audit.missing


def test_all_privileges_is_rejected() -> None:
    audit = _audit(
        _exact_grants()
        + [
            (
                "GRANT ALL PRIVILEGES ON *.* "
                f"TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`"
            )
        ]
    )
    assert not audit.passed
    assert any("GLOBAL_AUTHORITY_FORBIDDEN" in item for item in audit.violations)


def test_schema_wildcard_is_rejected() -> None:
    audit = _audit(
        _exact_grants()
        + [
            (
                "GRANT SELECT ON `synth`.* "
                f"TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`"
            )
        ]
    )
    assert not audit.passed
    assert any("SCHEMA_WILDCARD_FORBIDDEN" in item for item in audit.violations)


def test_forbidden_table_privilege_is_rejected() -> None:
    audit = _audit(
        _exact_grants()
        + [
            (
                "GRANT SELECT ON `synth`.`trading_account_balance_snapshot` "
                f"TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`"
            )
        ]
    )
    assert not audit.passed
    assert any("FORBIDDEN_OBJECT_AUTHORITY" in item for item in audit.violations)
    assert "synth.trading_account_balance_snapshot:SELECT" in audit.unexpected


def test_actual_execution_layer_privilege_is_rejected() -> None:
    audit = _audit(
        _exact_grants()
        + [
            (
                "GRANT SELECT, INSERT ON `synth`.`execution_plan` "
                f"TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`"
            )
        ]
    )
    assert not audit.passed
    assert any("FORBIDDEN_OBJECT_AUTHORITY" in item for item in audit.violations)
    assert "synth.execution_plan:INSERT" in audit.unexpected
    assert "synth.execution_plan:SELECT" in audit.unexpected


def test_unexpected_administrative_privilege_is_rejected() -> None:
    audit = _audit(
        _exact_grants()
        + [f"GRANT PROCESS ON *.* TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`"]
    )
    assert not audit.passed
    assert any("GLOBAL_AUTHORITY_FORBIDDEN" in item for item in audit.violations)


def test_execution_zone_context_is_semantically_allowed() -> None:
    assert REQUIRED_OBJECT_PRIVILEGES["execution_zone_context"] == {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    }
    audit = _audit(_exact_grants())
    assert audit.passed


def test_dba_artifact_grants_exact_contract_without_plaintext_password() -> None:
    text = SQL_ARTIFACT.read_text(encoding="utf-8")
    statements = re.findall(r"^GRANT\s+.*?;", text, flags=re.MULTILINE | re.DOTALL)
    parsed = [parse_grant_statement(statement.rstrip(";")) for statement in statements]
    actual = {
        grant.object_name: grant.privileges
        for grant in parsed
        if grant.database == OPERATIONAL_DATABASE
    }

    assert actual == REQUIRED_OBJECT_PRIVILEGES
    assert "`synth`.*" not in text
    assert "GRANT ALL PRIVILEGES" not in text
    assert "QUOTE(@synth_chain_4h_writer_password)" in text
    assert "MYSQL_PWD" not in text
    assert f"TO 'synth'@" not in text
    assert text.count(f"'{IDENTITY_NAME}'@'{IDENTITY_HOST}'") >= 1


def test_candidate_config_uses_only_dedicated_namespace(tmp_path: Path) -> None:
    secret = tmp_path / "chain-password"
    secret.write_text("not-printed-secret\n", encoding="utf-8")
    secret.chmod(0o640)
    config = runner.load_candidate_config(
        {
            runner.BINDING_PROFILE_ENV: "synth_chain_4h",
            runner.ENV_HOST: "candidate-db.internal",
            runner.ENV_PORT: "3307",
            runner.ENV_USER: IDENTITY_NAME,
            runner.ENV_DATABASE: OPERATIONAL_DATABASE,
            runner.ENV_PASSWORD_FILE: str(secret),
            "DB_USER": "broad-synth-must-not-be-used",
            "DB_PASSWORD": "broad-secret-must-not-be-used",
        },
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    assert config.host == "candidate-db.internal"
    assert config.port == 3307
    assert config.user == IDENTITY_NAME
    assert config.password == "not-printed-secret"
    assert config.password_file == str(secret)


class _FakeCursor:
    def __init__(self, grants: list[str]) -> None:
        self.grants = grants
        self.commands: list[str] = []
        self.current = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql: str) -> None:
        self.current = " ".join(sql.split())
        self.commands.append(self.current)

    def fetchone(self):
        assert self.current.startswith("SELECT USER()")
        return {
            "authenticated_identity": f"{IDENTITY_NAME}@192.168.1.10",
            "grant_identity": EXPECTED_GRANT_IDENTITY,
            "database_name": OPERATIONAL_DATABASE,
        }

    def fetchall(self):
        assert self.current == "SHOW GRANTS"
        return [
            {f"Grants for {EXPECTED_GRANT_IDENTITY}": grant}
            for grant in self.grants
        ]


class _FakeConnection:
    def __init__(self, grants: list[str]) -> None:
        self.cursor_instance = _FakeCursor(grants)
        self.rollback_count = 0
        self.close_count = 0
        self.commit_count = 0

    def cursor(self):
        return self.cursor_instance

    def rollback(self) -> None:
        self.rollback_count += 1

    def commit(self) -> None:
        self.commit_count += 1

    def close(self) -> None:
        self.close_count += 1


def _candidate_config() -> runner.CandidateDatabaseConfig:
    return runner.CandidateDatabaseConfig(
        host="candidate-db.internal",
        port=3306,
        user=IDENTITY_NAME,
        password="not-printed-secret",
        database=OPERATIONAL_DATABASE,
    )


def test_preflight_executes_only_read_only_commands_and_rolls_back() -> None:
    connection = _FakeConnection(_exact_grants())
    captured_kwargs = {}

    def connect(**kwargs):
        captured_kwargs.update(kwargs)
        return connection

    result = runner.run_preflight(_candidate_config(), connect=connect)

    assert result.audit.passed
    assert connection.cursor_instance.commands == list(runner.READ_ONLY_SQL)
    assert connection.rollback_count == 1
    assert connection.commit_count == 0
    assert connection.close_count == 1
    assert captured_kwargs["autocommit"] is False

    mutating_tokens = ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "GRANT ", "REVOKE ")
    assert not any(
        command.upper().startswith(mutating_tokens)
        for command in connection.cursor_instance.commands
    )


def test_connection_failure_redacts_connection_details_and_secrets() -> None:
    config = _candidate_config()
    sensitive_values = (config.host, config.user, config.password, config.database)

    def connect(**kwargs):
        raise RuntimeError(
            "dsn=mysql://synth_chain_4h_writer:not-printed-secret@"
            "candidate-db.internal/synth token=fingerprint-123"
        )

    with pytest.raises(runner.PreflightConnectionError) as exc_info:
        runner.run_preflight(config, connect=connect)

    rendered = str(exc_info.value)
    assert rendered == "DATABASE_CONNECTION_FAILED error_type=RuntimeError"
    assert all(value not in rendered for value in sensitive_values)
    assert "fingerprint-123" not in rendered


# ---------------------------------------------------------------------------
# native_short_map_level_target_event_{v1,coverage_v1}: regression coverage
# for the gap that caused a production MariaDB error 1142 on gurkdb
# (SELECT denied on native_short_map_level_target_event_coverage_v1), traced
# to the terminal-transition hook in native_short_scope_status_materializer_v1
# that runs unconditionally on every genuine COMPLETED lifecycle transition.
# See docs/ops/synth_chain_4h_db_grant_contract_v1.md for the full trace.
# ---------------------------------------------------------------------------

TARGET_EVENT_COVERAGE_TABLE = "native_short_map_level_target_event_coverage_v1"
TARGET_EVENT_TABLE = "native_short_map_level_target_event_v1"
TARGET_EVENT_VIEW = "native_short_map_level_target_event_current_state_v1"

EXPECTED_REQUIRED_OBJECT_COUNT = 37


def test_target_event_tables_are_part_of_canonical_required_object_set() -> None:
    assert REQUIRED_OBJECT_PRIVILEGES[TARGET_EVENT_COVERAGE_TABLE] == {"SELECT"}
    assert REQUIRED_OBJECT_PRIVILEGES[TARGET_EVENT_TABLE] == {"SELECT", "INSERT"}


def test_required_objects_count_matches_canonical_manifest() -> None:
    assert len(REQUIRED_OBJECT_PRIVILEGES) == EXPECTED_REQUIRED_OBJECT_COUNT


def test_grant_preflight_fails_when_target_event_coverage_select_absent() -> None:
    grants = [
        grant
        for grant in _exact_grants()
        if f"`.`{TARGET_EVENT_COVERAGE_TABLE}`" not in grant
    ]
    audit = _audit(grants)
    assert not audit.passed
    assert f"synth.{TARGET_EVENT_COVERAGE_TABLE}:SELECT" in audit.missing


def test_grant_preflight_fails_when_target_event_table_privileges_absent() -> None:
    grants = [
        grant for grant in _exact_grants() if f"`.`{TARGET_EVENT_TABLE}`" not in grant
    ]
    audit = _audit(grants)
    assert not audit.passed
    assert f"synth.{TARGET_EVENT_TABLE}:SELECT" in audit.missing
    assert f"synth.{TARGET_EVENT_TABLE}:INSERT" in audit.missing


def test_grant_preflight_passes_with_complete_minimum_grants_via_run_preflight() -> None:
    """End-to-end via the real ``run_preflight`` entrypoint (not just
    ``audit_grants`` directly), proving the complete canonical grant set --
    including the two new target-event objects -- is accepted as PASS."""
    connection = _FakeConnection(_exact_grants())

    def connect(**kwargs):
        return connection

    result = runner.run_preflight(_candidate_config(), connect=connect)
    assert result.audit.passed
    assert result.audit.missing == ()
    assert result.audit.unexpected == ()


def test_target_event_coverage_insert_beyond_select_is_rejected_as_unexpected() -> None:
    """The coverage table must stay SELECT-only: the automated chain
    entrypoint never supplies a non-None watermark, so INSERT is not
    reachable under this identity and must not be granted."""
    grants = [
        grant
        for grant in _exact_grants()
        if f"`.`{TARGET_EVENT_COVERAGE_TABLE}`" not in grant
    ] + [
        (
            "GRANT SELECT, INSERT ON `synth`.`native_short_map_level_target_event_coverage_v1` "
            f"TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`"
        )
    ]
    audit = _audit(grants)
    assert not audit.passed
    assert f"synth.{TARGET_EVENT_COVERAGE_TABLE}:INSERT" in audit.unexpected


def test_target_event_table_update_beyond_insert_select_is_rejected_as_unexpected() -> None:
    """Both target-event tables are append-only by design (no code path ever
    issues UPDATE/DELETE); a grant beyond SELECT/INSERT must be flagged."""
    grants = [
        grant for grant in _exact_grants() if f"`.`{TARGET_EVENT_TABLE}`" not in grant
    ] + [
        (
            "GRANT SELECT, INSERT, UPDATE ON `synth`.`native_short_map_level_target_event_v1` "
            f"TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`"
        )
    ]
    audit = _audit(grants)
    assert not audit.passed
    assert f"synth.{TARGET_EVENT_TABLE}:UPDATE" in audit.unexpected


def test_target_event_reporting_view_is_not_granted() -> None:
    """native_short_map_level_target_event_current_state_v1 is not referenced
    by any runtime code path today and must stay ungranted -- granting it
    would be exactly the blind over-grant this contract exists to avoid."""
    assert TARGET_EVENT_VIEW not in REQUIRED_OBJECT_PRIVILEGES
    audit = _audit(
        _exact_grants()
        + [
            (
                f"GRANT SELECT ON `synth`.`{TARGET_EVENT_VIEW}` "
                f"TO `{IDENTITY_NAME}`@`{IDENTITY_HOST}`"
            )
        ]
    )
    assert not audit.passed
    assert f"synth.{TARGET_EVENT_VIEW}:SELECT" in audit.unexpected


def test_target_event_tables_are_not_forbidden_or_account_execution_authority() -> None:
    """No account, broker, decision_gate, execution_planner, executor, or
    reporting authority is introduced by this change -- the two new objects
    must not appear in the semantic deny-list, and the exact accepted grant
    set for this identity must still contain zero forbidden-authority
    objects overall."""
    from src.operations.synth_chain_4h_db_authority_v1 import FORBIDDEN_AUTHORITY_OBJECTS

    assert TARGET_EVENT_COVERAGE_TABLE not in FORBIDDEN_AUTHORITY_OBJECTS
    assert TARGET_EVENT_TABLE not in FORBIDDEN_AUTHORITY_OBJECTS
    audit = _audit(_exact_grants())
    assert audit.passed
    assert not any("FORBIDDEN_OBJECT_AUTHORITY" in item for item in audit.violations)
    assert not any("ADMINISTRATIVE_AUTHORITY_FORBIDDEN" in item for item in audit.violations)
