"""
Static content checks for db/migrations/20260811_manual_execution_plan_snapshot_v1.sql
and the issue-#202 additions to
db/migrations/20260726_manual_execution_request_v1.sql, matching the pattern
in tests/test_manual_execution_round3_migration_v1.py — no real DB, string
assertions against the raw .sql file content only.
"""
from pathlib import Path


SNAPSHOT_SQL = Path(
    "db/migrations/20260811_manual_execution_plan_snapshot_v1.sql"
).read_text(encoding="utf-8")

REQUEST_SQL = Path(
    "db/migrations/20260726_manual_execution_request_v1.sql"
).read_text(encoding="utf-8")


def test_plan_snapshot_schema_has_required_identity_and_bindings() -> None:
    for fragment in (
        "manual_execution_plan_snapshot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT",
        "UNIQUE KEY uq_manual_execution_plan_snapshot_idempotency",
        "UNIQUE KEY uq_manual_execution_plan_snapshot_request",
        "UNIQUE KEY uq_manual_execution_plan_snapshot_approval",
        "ladder_profile_id",
        "ladder_profile_version",
        "anchor_reference_price",
        "anchor_ts_utc",
        "provenance_id",
        "approved_quantity_base",
        "legs_json",
        "plan_state",
    ):
        assert fragment in SNAPSHOT_SQL


def test_plan_snapshot_request_and_approval_relationship_is_unambiguous() -> None:
    """UNIQUE KEYs on both manual_execution_request_id and
    manual_execution_approval_id are what makes the request<->plan
    relationship 1:1 and unambiguous at the DB layer (see also the
    Python-level dedupe/mismatch tests in
    tests/test_manual_execution_plan_snapshot_v1.py)."""
    assert "UNIQUE KEY uq_manual_execution_plan_snapshot_request (manual_execution_request_id)" in SNAPSHOT_SQL
    assert "UNIQUE KEY uq_manual_execution_plan_snapshot_approval (manual_execution_approval_id)" in SNAPSHOT_SQL


def test_plan_snapshot_foreign_keys_cover_authoritative_parents() -> None:
    for parent in (
        "manual_execution_request (manual_execution_request_id)",
        "manual_execution_approval (manual_execution_approval_id)",
        "execution_ladder_profile (ladder_profile_id)",
        "execution_research_provenance (provenance_id)",
    ):
        assert f"REFERENCES {parent}" in SNAPSHOT_SQL


def test_plan_snapshot_rows_are_database_immutable() -> None:
    assert "BEFORE UPDATE ON manual_execution_plan_snapshot" in SNAPSHOT_SQL
    assert "BEFORE DELETE ON manual_execution_plan_snapshot" in SNAPSHOT_SQL
    assert "MANUAL_EXECUTION_PLAN_SNAPSHOT_IS_IMMUTABLE" in SNAPSHOT_SQL


def test_plan_snapshot_is_side_neutral_not_sell_only() -> None:
    """Issue #202 requires the request/snapshot model to support both BUY
    and SELL ladders; the side CHECK must therefore list both, not lock the
    table to SELL the way manual_execution_approval intentionally does."""
    assert "CHECK (side IN ('BUY', 'SELL'))" in SNAPSHOT_SQL
    assert "CHECK (side = 'SELL')" not in SNAPSHOT_SQL


def test_plan_snapshot_state_is_fixed_to_preview_only() -> None:
    """No executor lane exists yet; the CHECK constraint prevents any writer
    from inventing a submitted/filled state ahead of that separately
    authorized work."""
    assert "CHECK (plan_state = 'PREVIEW_ONLY')" in SNAPSHOT_SQL


def test_plan_snapshot_migration_documents_order_and_rollback() -> None:
    assert "-- Deployment order:" in SNAPSHOT_SQL
    assert "-- Rollback limitations:" in SNAPSHOT_SQL
    assert "CREATED BUT NOT APPLIED" in SNAPSHOT_SQL


def test_plan_snapshot_migration_requires_prerequisite_tables() -> None:
    for required_table in (
        "manual_execution_request",
        "manual_execution_approval",
        "execution_ladder_profile",
        "execution_research_provenance",
    ):
        assert f"table_name = '{required_table}'" in SNAPSHOT_SQL


def test_request_schema_has_ladder_profile_and_anchor_binding() -> None:
    for fragment in (
        "ladder_profile_id          BIGINT UNSIGNED DEFAULT NULL",
        "ladder_profile_version     INT            DEFAULT NULL",
        "anchor_reference_price     DECIMAL(20,10) DEFAULT NULL",
        "anchor_ts_utc              DATETIME(6)    DEFAULT NULL",
        "fk_manual_execution_request_ladder_profile",
        "chk_manual_execution_request_ladder_binding",
    ):
        assert fragment in REQUEST_SQL


def test_request_ladder_binding_check_is_all_or_nothing() -> None:
    assert "quantity_policy = 'LADDER_LEVELS'" in REQUEST_SQL
    assert "quantity_policy <> 'LADDER_LEVELS'" in REQUEST_SQL
