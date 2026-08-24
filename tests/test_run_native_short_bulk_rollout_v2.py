from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from src.market_data import run_native_short_bulk_rollout_v2 as cli
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceState,
)
from tests.test_native_short_scope_administration_transaction_v1 import (
    _FakeConn,
    _bulk_rollout_report_for,
)


_BASE_ARGS = [
    "--actor-type", "HUMAN_OPERATOR",
    "--actor-id", "operator-1",
    "--trigger-type", "MANUAL_CLI",
    "--reason", "explicit review",
    "--request-source", "cli-test",
    "--repository-commit", "a" * 40,
    "--requested-at-utc", "2026-07-18T10:00:00Z",
]


def _clean_source() -> NativeShortRepositorySourceState:
    return NativeShortRepositorySourceState(head_sha="a" * 40, status_porcelain="")


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    *,
    conn: _FakeConn | None,
    report_symbols: tuple[str, ...] = ("BTC",),
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    import src.common.db as dbmod
    from src.market_data import native_short_scope_administration_transaction_v1 as txn

    def _report(as_of_utc: datetime) -> Any:
        return _combined_report(as_of_utc, report_symbols)

    monkeypatch.setattr(cli, "_load_report", lambda conn, *, as_of_utc: _report(as_of_utc))
    # The FakeConn's default empty state has no writer-provenance/admin-
    # operation rows, so the real evaluate_current_global_blockers would
    # report every blocker active; bypass it here the same way the
    # single-scope CLI's own tests do, since this CLI's own audit-guard
    # behavior (not the transaction layer's blocker evaluation) is what's
    # under test.
    monkeypatch.setattr(txn, "evaluate_current_global_blockers", lambda conn: ((), {}))
    if conn is not None:
        monkeypatch.setattr(dbmod, "get_connection", lambda: conn)
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    code = cli.main(argv, inspect_repository_source=_clean_source)
    monkeypatch.undo()
    stdout_docs = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    stderr_docs = [json.loads(x) for x in err.getvalue().splitlines() if x.strip()]
    return code, stdout_docs, stderr_docs


def _combined_report(as_of_utc: datetime, symbols: tuple[str, ...]) -> Any:
    from src.market_data.native_short_multi_asset_audit_v1 import AuditReport

    reports = [_bulk_rollout_report_for(symbol, as_of_utc=as_of_utc) for symbol in symbols]
    if not reports:
        return _bulk_rollout_report_for("NONE", as_of_utc=as_of_utc)
    results = tuple(r for report in reports for r in report.results)
    base = reports[0]
    return AuditReport(
        as_of_utc=as_of_utc,
        results=results,
        proposed_sequential_queue=base.proposed_sequential_queue,
        counts=base.counts,
        writer_run_count=base.writer_run_count,
        attributable_writer_run_count=base.attributable_writer_run_count,
        legacy_unattributed_writer_run_count=base.legacy_unattributed_writer_run_count,
        invalid_provenance_writer_run_count=base.invalid_provenance_writer_run_count,
        provenance_audit_run_found=base.provenance_audit_run_found,
        provenance_audit_run_attributed=base.provenance_audit_run_attributed,
        provenance_contract_implemented=base.provenance_contract_implemented,
        attributable_production_run_observed=base.attributable_production_run_observed,
        operational_acceptance_completed=base.operational_acceptance_completed,
        writer_provenance_blocker_active=base.writer_provenance_blocker_active,
        global_blocker_codes=base.global_blocker_codes,
    )


def test_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0


def test_dry_run_reports_started_before_audit_and_one_result_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    code, stdout_docs, stderr_docs = _run_cli(monkeypatch, _BASE_ARGS, conn=conn)
    assert code == 0
    assert len(stdout_docs) == 1
    result = stdout_docs[0]
    assert result["event"] == "RESULT"
    assert result["mode"] == "DRY_RUN"
    assert result["all_succeeded"] is True
    assert result["production_db_writes"] == 0
    for marker in ("broker_private_calls", "broker_writes", "order_submission", "live_orders"):
        assert marker in result

    # Observability: STARTED must be emitted before the (potentially long)
    # audit phase finishes -- not only before the mutation.
    events = [doc["event"] for doc in stderr_docs]
    assert events[0] == "STARTED"
    assert "AUDIT_FINISHED" in events
    assert events.index("STARTED") < events.index("AUDIT_FINISHED")
    assert "FINISHED" in events
    assert conn.commit_count == 0


def test_dry_run_with_no_ready_scopes_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    code, stdout_docs, _ = _run_cli(monkeypatch, _BASE_ARGS, conn=conn, report_symbols=())
    assert code == 0
    assert stdout_docs[0]["completed"] == []
    assert stdout_docs[0]["all_succeeded"] is True


def test_write_requires_authorization_and_is_denied_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    def _deny(capability_id: str, **kwargs: Any) -> Any:
        raise authmod.AuthorizationDenied(
            capability_id, authmod.ExecutionMode.READ_ONLY, ["not authorized"]
        )

    monkeypatch.setattr(authmod, "enforce_capability_write_authorization", _deny)
    conn = _FakeConn()
    code, stdout_docs, _ = _run_cli(monkeypatch, [*_BASE_ARGS, "--write"], conn=conn)
    assert code == 3
    assert stdout_docs[0]["event"] == "FAILED"
    assert stdout_docs[0]["reason_code"] == "WRITER_AUTHORIZATION_DENIED"
    assert conn.commit_count == 0


def test_write_rejects_dirty_repository_source(monkeypatch: pytest.MonkeyPatch) -> None:
    def _dirty() -> NativeShortRepositorySourceState:
        return NativeShortRepositorySourceState(head_sha="a" * 40, status_porcelain=" M src/foo.py")

    import src.common.db as dbmod

    monkeypatch.setattr(
        cli, "_load_report", lambda conn, *, as_of_utc: _combined_report(as_of_utc, ("BTC",))
    )
    conn = _FakeConn()
    monkeypatch.setattr(dbmod, "get_connection", lambda: conn)
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    code = cli.main([*_BASE_ARGS, "--write"], inspect_repository_source=_dirty)
    monkeypatch.undo()
    stdout_docs = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    assert code == 2
    assert stdout_docs[0]["reason_code"] == "INVALID_REPOSITORY_SOURCE"
    assert conn.commit_count == 0


def test_invalid_metadata_is_rejected_before_any_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _unexpected_audit(conn: Any, *, as_of_utc: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("audit must not run for a validation failure")

    monkeypatch.setattr(cli, "_load_report", _unexpected_audit)
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    code = cli.main([*_BASE_ARGS, "--metadata", "not-json"], inspect_repository_source=_clean_source)
    monkeypatch.undo()
    stdout_docs = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    assert code == 2
    assert stdout_docs[0]["reason_code"] == "INVALID_REQUEST"
    assert called is False
