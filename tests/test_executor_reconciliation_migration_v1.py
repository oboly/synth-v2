from pathlib import Path


MIGRATION = Path("db/migrations/20260815_executor_reconciliation_evidence_v1.sql")


def test_pr2_migration_is_additive_and_not_applied() -> None:
    text = MIGRATION.read_text()
    assert "MIGRATION_STATE=CREATED_NOT_APPLIED" in text
    assert "ALTER TABLE executor_execution_leg" in text
    assert "broker_raw_status" in text
    assert "restatement_reason" in text
    assert "last_reconciled_ts_utc" in text
    assert "CREATE TABLE" not in text
    assert "executor_live_authority" not in text
    assert "executor_kill_switch" not in text
    assert "manual_execution_" not in text


def test_reconciliation_required_can_only_resolve_authoritative_state() -> None:
    text = MIGRATION.read_text()
    assert "OLD.state='RECONCILIATION_REQUIRED'" in text
    assert "('ACTIVE','PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED','REJECTED')" in text
    assert "OLD.state='RECONCILIATION_REQUIRED' AND NEW.state='PREPARED'" not in text
