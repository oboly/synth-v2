import re
from pathlib import Path


MIGRATION = Path("db/migrations/20260815_shared_executor_substrate_v1.sql")


def migration_text() -> str:
    return MIGRATION.read_text()


def test_migration_is_additive_created_not_applied_pr1_scope() -> None:
    text = migration_text()
    assert "MIGRATION_STATE=CREATED_NOT_APPLIED" in text
    assert text.count("CREATE TABLE") == 2
    assert "CREATE TABLE executor_execution_handoff" in text
    assert "CREATE TABLE executor_execution_leg" in text
    assert "executor_live_authority" not in text
    assert "executor_kill_switch" not in text
    assert "ALTER TABLE manual_execution_" not in text
    assert "DROP TABLE" not in text


def test_migration_enforces_handoff_and_leg_uniqueness_and_no_delete() -> None:
    text = migration_text()
    assert "UNIQUE KEY uq_eeh_plan_ref (plan_source,plan_reference_id)" in text
    assert "UNIQUE KEY uq_eel_handoff_leg" in text
    assert "UNIQUE KEY uq_eel_client_order_id" in text
    assert "CREATE TRIGGER trg_eeh_no_delete" in text
    assert "CREATE TRIGGER trg_eel_no_delete" in text
    assert "operator_id BIGINT UNSIGNED NOT NULL" in text
    assert "OLD.operator_id <=> NEW.operator_id" in text


def test_reconciliation_required_is_a_pr1_dead_end() -> None:
    text = migration_text()
    assert "OLD.state='PREPARED' AND NEW.state='SUBMISSION_UNCERTAIN'" in text
    assert "OLD.state='SUBMISSION_UNCERTAIN'" in text
    assert "RECONCILIATION_REQUIRED" in text
    assert "OLD.state='RECONCILIATION_REQUIRED'" not in text
    assert "NEW.state='PREPARED'" not in text


def test_mariadb_identifiers_fit_the_64_character_limit() -> None:
    identifiers = re.findall(
        r"(?:CONSTRAINT|TRIGGER|KEY)\s+([A-Za-z0-9_]+)", migration_text()
    )
    assert identifiers
    assert all(len(identifier) <= 64 for identifier in identifiers)
