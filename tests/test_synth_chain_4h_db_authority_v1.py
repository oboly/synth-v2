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
