from pathlib import Path


SQL = Path(
    "db/migrations/20260813_manual_execution_submission_leg_v1.sql"
).read_text(encoding="utf-8")


def test_schema_has_required_identity_and_state_columns() -> None:
    for fragment in (
        "submission_leg_id",
        "BIGINT UNSIGNED NOT NULL AUTO_INCREMENT",
        "manual_execution_executor_handoff_id",
        "manual_execution_plan_snapshot_id",
        "leg_index",
        "trading_account_id",
        "client_order_id",
        "operator_id",
        "immutable_price",
        "immutable_quantity",
        "submission_state",
        "broker_order_id",
        "broker_status",
        "attempt_started_ts_utc",
        "broker_ack_ts_utc",
        "last_reconciled_ts_utc",
        "safe_error_code",
        "created_ts_utc",
    ):
        assert fragment in SQL


def test_unique_constraints_cover_leg_and_client_order_id() -> None:
    assert "UNIQUE KEY uq_mesl_plan_leg (manual_execution_plan_snapshot_id, leg_index)" in SQL
    assert "UNIQUE KEY uq_mesl_client_order_id (client_order_id)" in SQL


def test_foreign_keys_cover_authoritative_parents() -> None:
    for parent in (
        "manual_execution_executor_handoff (manual_execution_executor_handoff_id)",
        "manual_execution_plan_snapshot (manual_execution_plan_snapshot_id)",
        "trading_account (trading_account_id)",
    ):
        assert f"REFERENCES {parent}" in SQL


def test_state_machine_check_constraint_has_all_states() -> None:
    for state in (
        "PREPARED", "SUBMISSION_UNCERTAIN", "SUBMITTED", "OPEN",
        "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "FAILED",
    ):
        assert state in SQL


def test_rows_are_identity_immutable_and_never_deleted() -> None:
    assert "BEFORE UPDATE ON manual_execution_submission_leg" in SQL
    assert "MANUAL_EXECUTION_SUBMISSION_LEG_IDENTITY_IS_IMMUTABLE" in SQL
    assert "BEFORE DELETE ON manual_execution_submission_leg" in SQL
    assert "MANUAL_EXECUTION_SUBMISSION_LEG_IS_IMMUTABLE" in SQL


def test_migration_documents_status_and_rollback() -> None:
    assert "CREATED BUT NOT APPLIED" in SQL
    assert "Rollback limitations:" in SQL
