from pathlib import Path


def test_automatic_buy_runtime_migration_has_required_phase4_contracts() -> None:
    sql = Path("db/migrations/20260819_automatic_buy_runtime_v1.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS automatic_buy_runtime_input_v1" in sql
    assert "evaluation_ts_utc DATETIME(6) NOT NULL" in sql
    assert "UNIQUE KEY uq_automatic_buy_runtime_source_snapshot" in sql
    assert "CREATE TABLE IF NOT EXISTS automatic_buy_evaluation_audit_v1" in sql
    assert "UNIQUE KEY uq_automatic_buy_evaluation_idempotency" in sql
    assert "immutable plan JSON is audit-only" in sql
