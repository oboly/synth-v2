from pathlib import Path


SQL = Path(
    "db/migrations/20260726_manual_execution_atomic_approval_v1.sql"
).read_text(encoding="utf-8")


def test_approval_schema_has_required_identity_and_bindings() -> None:
    for fragment in (
        "manual_execution_approval_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT",
        "UNIQUE KEY uq_manual_execution_approval_idempotency",
        "UNIQUE KEY uq_manual_execution_approval_request",
        "UNIQUE KEY uq_manual_execution_approval_reservation",
        "approved_quantity_base",
        "wallet_snapshot_id",
        "wallet_snapshot_version_ts_utc",
        "reservation_id",
        "approved_ts_utc",
        "expires_ts_utc",
        "approval_state",
        "provenance_id",
    ):
        assert fragment in SQL


def test_approval_foreign_keys_cover_authoritative_parents() -> None:
    for parent in (
        "manual_execution_request (manual_execution_request_id)",
        "account_position_snapshot (account_position_snapshot_id)",
        "execution_sell_reservation (reservation_id)",
        "execution_research_provenance (provenance_id)",
    ):
        assert f"REFERENCES {parent}" in SQL
    assert "fk_execution_sell_reservation_manual_request_v1" in SQL
    assert "fk_manual_execution_request_provenance_v1" in SQL


def test_approval_rows_are_database_immutable_and_expiring() -> None:
    assert "BEFORE UPDATE ON manual_execution_approval" in SQL
    assert "BEFORE DELETE ON manual_execution_approval" in SQL
    assert "MANUAL_EXECUTION_APPROVAL_IS_IMMUTABLE" in SQL
    assert "CHECK (expires_ts_utc > approved_ts_utc)" in SQL
    assert "CHECK (approved_quantity_base > 0)" in SQL


def test_migration_documents_order_compatibility_and_rollback() -> None:
    assert "-- Deployment order:" in SQL
    assert "-- Compatibility window:" in SQL
    assert "-- Rollback limitations:" in SQL
    assert "CREATED BUT NOT APPLIED" in SQL
