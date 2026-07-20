"""Direct low-level mutation-helper authorization, path policy, literal-UTC and
1h/1d persisted-candle freshness gates. These reproduce bypasses that a fresh
review flagged and prove each now fails closed before any SQL/commit/artifact.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.operations import validate_writer_capability_ownership_v1 as validator
from src.operations.persisted_market_candle_freshness_v1 import (
    classify_persisted_candle_boundary,
)
from src.operations.writer_capability_authorization_v1 import (
    AuthorizationDenied,
    ExecutionMode,
    _utc_literal_to_datetime,
    load_and_validate_acceptance_permit,
    load_and_validate_authorization,
    verify_writer_execution_authorization,
)
from tests.writer_auth_support import make_test_authorization

from src.etl.bitvavo.etl_bitvavo_candles import upsert_candles
from src.market_data.market_price_snapshot_v1 import insert_market_price_snapshots
from src.market_data.native_short_fib_context_snapshot_v1 import publish_snapshot
from src.market_data.native_short_map_materializer_v1 import materialize_scope_symbol
from src.market_data.native_short_scope_status_materializer_v1 import (
    run_native_short_scope_status_materializer,
)

REPO = Path.cwd()
AUTH_SCHEMA = REPO / "deploy/ownership/writer_capability_authorization_v1.schema.json"
ACCEPT_SCHEMA = REPO / "deploy/ownership/writer_capability_acceptance_permit_v1.schema.json"


# ---------------------------------------------------------------------------
# Fakes that record whether any SQL / commit ever happened.
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, *a: object, **k: object) -> None:
        self._log.append("execute")

    def executemany(self, *a: object, **k: object) -> None:
        self._log.append("executemany")


class _FakeConn:
    def __init__(self) -> None:
        self.log: list[str] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.log)

    def begin(self) -> None:
        self.log.append("begin")

    def commit(self) -> None:
        self.log.append("commit")

    def rollback(self) -> None:
        self.log.append("rollback")


# ---------------------------------------------------------------------------
# Direct helper denial (no wrapper, no CLI).
# ---------------------------------------------------------------------------

def test_direct_candle_upsert_without_authorization_denied() -> None:
    conn = _FakeConn()
    with pytest.raises(AuthorizationDenied):
        upsert_candles(conn, [object()])  # no authorization
    assert conn.log == []  # no execute/executemany/commit


def test_direct_market_price_persistence_without_authorization_denied() -> None:
    conn = _FakeConn()
    with pytest.raises(AuthorizationDenied):
        insert_market_price_snapshots(conn, [object()])  # type: ignore[list-item]
    assert conn.log == []


def test_direct_scope_materializer_without_authorization_denied() -> None:
    conn = _FakeConn()
    with pytest.raises(AuthorizationDenied):
        run_native_short_scope_status_materializer(
            conn,
            scopes=[],
            as_of_utc=datetime.now(UTC),
            provenance=None,  # type: ignore[arg-type]
            operational_clock=lambda: datetime.now(UTC),
            fetch_context_row=lambda *a, **k: None,
            fetch_existing_maps=lambda *a, **k: [],
            fetch_existing_generation_events=lambda *a, **k: [],
            fetch_existing_lifecycle_events=lambda *a, **k: [],
            fetch_primary_candle_close_timestamps=lambda *a, **k: [],
            fetch_supporting_candle_close_timestamps=lambda *a, **k: [],
        )
    assert conn.log == []


def test_direct_map_materializer_write_without_authorization_denied() -> None:
    conn = _FakeConn()
    with pytest.raises(AuthorizationDenied):
        materialize_scope_symbol(
            conn,
            scope_support=None,  # type: ignore[arg-type]
            context_row=None,  # type: ignore[arg-type]
            now_utc=datetime.now(UTC),
            write=True,
            provenance=None,  # type: ignore[arg-type]
        )
    assert conn.log == []


def test_direct_canonical_publication_without_authorization_denied(tmp_path: Path) -> None:
    out = tmp_path / "pub"
    out.mkdir()
    with pytest.raises(AuthorizationDenied):
        publish_snapshot(
            None,  # type: ignore[arg-type]
            output_dir=out,
            generated_ts_utc=datetime.now(UTC),
            publication_ts_utc=datetime.now(UTC),
        )
    assert list(out.iterdir()) == []  # no temp/canonical file created


def test_wrong_capability_context_denied() -> None:
    conn = _FakeConn()
    wrong = make_test_authorization("public_price_snapshot")
    with pytest.raises(AuthorizationDenied):
        upsert_candles(conn, [object()], authorization=wrong)
    assert conn.log == []


def test_acceptance_context_accepted_for_matching_mutation() -> None:
    conn = _FakeConn()
    ctx = make_test_authorization("public_candle_freshness")
    assert ctx.execution_mode is ExecutionMode.ACCEPTANCE
    # Empty rows: accepted (no denial), and no SQL is executed for an empty batch.
    assert upsert_candles(conn, [], authorization=ctx) == 0
    assert conn.log == []


# ---------------------------------------------------------------------------
# Literal-Z UTC only.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "2026-07-20T00:00:00+01:00",
    "2026-07-20T00:00:00-05:00",
    "2026-07-20T00:00:00",  # timezone-less
    "2026-07-20 00:00:00Z",
])
def test_parser_rejects_non_literal_z(value: str) -> None:
    assert _utc_literal_to_datetime(value) is None


def test_parser_accepts_literal_z() -> None:
    assert _utc_literal_to_datetime("2026-07-20T00:00:00Z") is not None
    assert _utc_literal_to_datetime("2026-07-20T00:00:00.5Z") is not None


@pytest.mark.parametrize("value", [
    "2026-07-20T00:00:00+01:00",
    "2026-07-20T00:00:00-05:00",
    "2026-07-20T00:00:00",
])
def test_authorization_schema_rejects_offset_timestamp(tmp_path: Path, value: str) -> None:
    auth = {
        "authorization_version": "writer_capability_runtime_authorization_v1",
        "authorization_id": "auth-0001",
        "authorized_at_utc": value,
        "purpose": "PRODUCTION",
        "capability_id": "public_price_snapshot",
        "capability_identity": "public-price-snapshot-writer",
        "service": "synth-market-price-snapshot-writer.service",
        "systemd_unit": "synth-market-price-snapshot-writer.service",
        "authorized_host": "devlap",
        "authorized_commit": "a" * 40,
        "production_authorization_status": "AUTHORIZED",
        "runtime_lifecycle": "AUTHORIZED_INACTIVE",
        "decision_evidence": "docs/x.md#d",
    }
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(auth), encoding="utf-8")
    assert not load_and_validate_authorization(path, AUTH_SCHEMA).ok


def test_acceptance_schema_rejects_offset_timestamp(tmp_path: Path) -> None:
    permit = {
        "permit_version": "writer_capability_acceptance_permit_v1",
        "permit_id": "permit-0001",
        "issued_at_utc": "2026-07-20T00:00:00+02:00",
        "expiry_utc": "2099-07-20T00:00:00Z",
        "purpose": "ACCEPTANCE",
        "capability_id": "public_price_snapshot",
        "capability_identity": "public-price-snapshot-writer",
        "acceptance_host": "devlap",
        "authorized_commit": "a" * 40,
        "approval_reference": "ref",
    }
    path = tmp_path / "permit.json"
    path.write_text(json.dumps(permit), encoding="utf-8")
    assert not load_and_validate_acceptance_permit(path, ACCEPT_SCHEMA).ok


def test_semantic_validator_rejects_offset_observed_timestamp() -> None:
    registry = json.loads((REPO / "deploy/ownership/writer_capability_ownership_v1.json").read_text())
    rp = next(c for c in registry["capabilities"] if c["capability_id"] == "market_rotation_pressure")
    rp["observed_runtime_state"][0]["observed_at_utc"] = "2026-07-14T18:56:00+01:00"
    errors = validator.validate_registry_payload(registry, repo_root=REPO).errors
    assert any("observed_at_utc must be RFC3339" in e for e in errors)


def test_acceptance_permit_schema_has_no_max_invocations() -> None:
    schema = json.loads(ACCEPT_SCHEMA.read_text(encoding="utf-8"))
    assert "max_invocations" not in schema["properties"]
    assert "max_invocations" not in schema["required"]


# ---------------------------------------------------------------------------
# Path policy.
# ---------------------------------------------------------------------------

def test_production_authorization_symlink_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=REPO,
        authorization_path=link,
    )
    assert not decision.allowed
    assert any("must not be a symlink" in r for r in decision.reasons)


def test_production_authorization_group_world_writable_rejected(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    os.chmod(auth, 0o666)
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.PRODUCTION,
        repo_root=REPO,
        checkout_path=REPO,
        authorization_path=auth,
    )
    assert not decision.allowed
    assert any("group/world writable" in r for r in decision.reasons)


def test_acceptance_permit_outside_allowed_root_rejected(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "permit.json"
    outside.write_text("{}", encoding="utf-8")
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=REPO,
        acceptance_permit_path=outside,
        acceptance_permit_root=allowed,
    )
    assert not decision.allowed
    assert any("must live under" in r for r in decision.reasons)


def test_acceptance_permit_symlink_rejected(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    real = allowed / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = allowed / "link.json"
    link.symlink_to(real)
    decision = verify_writer_execution_authorization(
        capability_id="public_price_snapshot",
        mode=ExecutionMode.ACCEPTANCE,
        repo_root=REPO,
        checkout_path=REPO,
        acceptance_permit_path=link,
        acceptance_permit_root=allowed,
    )
    assert not decision.allowed
    assert any("must not be a symlink" in r for r in decision.reasons)


# ---------------------------------------------------------------------------
# 1h/1d persisted-candle freshness gates.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("script", ["scripts/run_chain_1h.sh", "scripts/run_chain_1d.sh"])
def test_chain_has_readonly_freshness_gate_before_features(script: str) -> None:
    text = Path(script).read_text(encoding="utf-8")
    assert "src.operations.run_persisted_market_candle_freshness_v1" in text
    assert "src.etl.bitvavo.run_candles_etl" not in text  # not a writer
    gate_idx = text.index("run_persisted_market_candle_freshness_v1")
    feat_idx = text.index("src.features.run_feat_candle")
    assert gate_idx < feat_idx  # gate precedes any write-capable stage


def _row(latest: datetime | None, count: int) -> dict:
    return {"latest_close_ts_utc": latest, "expected_close_row_count": count}


def test_freshness_fresh_missing_stale_outcomes() -> None:
    expected = datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC)
    assert classify_persisted_candle_boundary(_row(expected, 1), expected_close_ts_utc=expected).is_fresh
    # missing (no query result / no persisted candles)
    assert not classify_persisted_candle_boundary(None, expected_close_ts_utc=expected).is_fresh
    assert not classify_persisted_candle_boundary(_row(None, 0), expected_close_ts_utc=expected).is_fresh
    # stale (expected close not persisted yet)
    stale = classify_persisted_candle_boundary(
        _row(expected - timedelta(hours=1), 0), expected_close_ts_utc=expected
    )
    assert not stale.is_fresh


def test_freshness_runner_fails_closed_on_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.operations.run_persisted_market_candle_freshness_v1 as runner

    def boom() -> object:
        raise RuntimeError("db down")

    monkeypatch.setattr(runner, "get_connection", boom)
    monkeypatch.setattr(
        "sys.argv",
        ["run", "--venue", "bitvavo", "--interval", "1h", "--expected-close-ts", "2026-07-20T00:00:00Z"],
    )
    assert runner.main() == 1  # fail closed


def test_run_chain_1h_1d_registered_as_zero_public_writers() -> None:
    registry = json.loads((REPO / "deploy/ownership/writer_capability_ownership_v1.json").read_text())
    assert set(registry["market_only_processing_chains_with_zero_public_writers"]) == {
        "scripts/run_chain_1h.sh", "scripts/run_chain_1d.sh",
    }
    assert validator.validate_registry_payload(registry, repo_root=REPO).ok
