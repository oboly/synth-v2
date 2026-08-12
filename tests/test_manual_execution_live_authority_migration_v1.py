from pathlib import Path


SQL = Path(
    "db/migrations/20260814_manual_execution_live_authority_v1.sql"
).read_text(encoding="utf-8")


def test_schema_has_required_identity_columns() -> None:
    for fragment in (
        "manual_execution_live_authority_id",
        "manual_execution_executor_handoff_id",
        "manual_execution_request_id",
        "manual_execution_approval_id",
        "manual_execution_plan_snapshot_id",
        "trading_account_id",
        "venue",
        "executor_identity",
        "runtime_owner",
        "executor_credential_binding_id",
        "authorized_by",
        "authorized_ts_utc",
        "created_ts_utc",
    ):
        assert fragment in SQL


def test_one_authority_row_per_handoff() -> None:
    assert "UNIQUE KEY uq_mela_handoff (manual_execution_executor_handoff_id)" in SQL


def test_foreign_keys_cover_authoritative_parents() -> None:
    for parent in (
        "manual_execution_executor_handoff (manual_execution_executor_handoff_id)",
        "manual_execution_request (manual_execution_request_id)",
        "manual_execution_approval (manual_execution_approval_id)",
        "manual_execution_plan_snapshot (manual_execution_plan_snapshot_id)",
        "trading_account (trading_account_id)",
        "executor_credential_binding (executor_credential_binding_id)",
    ):
        assert f"REFERENCES {parent}" in SQL


def test_rows_are_immutable_and_never_deleted() -> None:
    assert "BEFORE UPDATE ON manual_execution_live_authority" in SQL
    assert "MANUAL_EXECUTION_LIVE_AUTHORITY_IS_IMMUTABLE" in SQL
    assert "BEFORE DELETE ON manual_execution_live_authority" in SQL


def test_migration_is_additive_and_documents_two_layer_contract() -> None:
    assert "CREATED BUT NOT APPLIED" in SQL
    assert "Additive only" in SQL
    assert "does not modify manual_execution_executor_handoff" in SQL
    assert "Rollback limitations:" in SQL
