"""Manual-invocation runner for one automatic-exit runtime cycle (Phase 4/5).

Loads the Phase 4A/4B persisted contracts, runs the exact
candidate -> decision_gate -> execution_planner path via
``src.exit_policy.automatic_exit_runtime_evidence_v1``, and optionally
records the DRY_RUN result to ``automatic_exit_evaluation_audit_v1`` via
``--commit-audit``. Every outcome (NO_ACTION, NON_ACTIONABLE, DENIED,
PLANNED) is a normal, successful run: only a genuine exception, an
already-held singleton lock, or SIGINT/SIGTERM produce a non-zero exit.

Runtime owner (Phase 4 scope): this is a manual-invocation runner only. No
systemd unit, timer, or production schedule is installed by this change.
Per docs/architecture/automatic_exit_policy_v1.md, the production
AUTOMATIC_EXIT_POLICY_RUNTIME host assignment remains a separate reviewed
decision; until that decision exists, this runner is invoked by hand on
devlap (or any host with equivalent DB read access) under the exact same
singleton-lock discipline production would use.

This runner never resolves broker credentials, never calls a broker, never
submits an order, and never enables LIVE trading.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=consumed_pure_contract_only
execution_planner=consumed_pure_contract_only
executor=none
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from src.exit_policy.automatic_exit_runtime_audit_writer_v1 import (
    write_automatic_exit_evaluation_audit_v1,
)
from src.exit_policy.automatic_exit_runtime_evidence_v1 import (
    AutomaticExitRuntimeEvidenceV1,
    build_automatic_exit_audit_payload_v1,
    run_automatic_exit_runtime_cycle_v1,
)
from src.exit_policy.automatic_exit_runtime_lock_v1 import (
    AutomaticExitRuntimeLockHeldError,
    acquire_singleton_lock,
    default_lock_path,
)
from src.exit_policy.automatic_exit_runtime_repository_v1 import (
    derive_position_reference,
    load_balance_snapshot_id,
    load_exit_profiles,
    load_latest_complete_account_state_snapshot,
    load_latest_market_price,
    load_open_order_conflict,
    load_planning_permissions,
    load_reservation_facts,
    load_trading_account_flags,
    load_venue_constraints,
    load_wallet_snapshot,
)


SAFETY_MARKERS: dict[str, Any] = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "consumed_pure_contract_only",
    "execution_planner": "consumed_pure_contract_only",
    "executor": "none",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run one deterministic automatic-exit DRY_RUN cycle: candidate -> decision_gate -> "
            "execution_planner, from persisted Phase 4A/4B evidence. No broker calls, no order "
            "submission, no LIVE trading."
        )
    )
    parser.add_argument("--trading-account-id", type=int, required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asset-id", type=int, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--quote-currency", default="EUR")
    parser.add_argument("--market", default=None, help="Defaults to SYMBOL-QUOTE_CURRENCY")
    parser.add_argument(
        "--evaluation-ts", default=None,
        help="ISO8601 UTC instant, e.g. 2026-08-15T12:00:00Z. Defaults to current UTC time.",
    )
    parser.add_argument(
        "--commit-audit", action="store_true",
        help="Persist the result to automatic_exit_evaluation_audit_v1. Default: read-only preview.",
    )
    parser.add_argument("--lock-dir", type=Path, default=Path("/tmp"))
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def _parse_evaluation_ts(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise SystemExit("--evaluation-ts must be timezone-aware (use a Z or +00:00 suffix)")
    return parsed.astimezone(timezone.utc)


def _emit(payload: dict[str, Any], output: str) -> None:
    if output == "json":
        print(json.dumps(payload, sort_keys=True, default=str), flush=True)
    else:
        print(" ".join(f"{key}={value}" for key, value in payload.items()), flush=True)


def _non_actionable_preview(reason: str, *, evaluation_ts_utc: datetime) -> dict[str, Any]:
    return {
        "candidate_state": "NON_ACTIONABLE",
        "candidate_reason_code": reason,
        "gate_state": None,
        "planner_state": "NOT_ATTEMPTED",
        "idempotency_key": None,
        "auditable": False,
        "evaluation_ts_utc": evaluation_ts_utc.isoformat(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    market = args.market or f"{args.symbol.strip().upper()}-{args.quote_currency.strip().upper()}"
    evaluation_ts_utc = _parse_evaluation_ts(args.evaluation_ts)
    started = time.monotonic()

    _emit(
        {
            "event": "STARTED",
            "runner": "run_automatic_exit_runtime_cycle_v1",
            "mode": "commit_audit" if args.commit_audit else "preview",
            "scope": f"{args.trading_account_id}/{args.venue}/{market}",
            "worker_count": 1,
            **SAFETY_MARKERS,
        },
        args.output,
    )

    lock_path = default_lock_path(
        trading_account_id=args.trading_account_id, venue=args.venue, asset_id=args.asset_id,
        market=market, lock_dir=args.lock_dir,
    )
    try:
        with acquire_singleton_lock(lock_path):
            return _run(args, market=market, evaluation_ts_utc=evaluation_ts_utc, started=started)
    except AutomaticExitRuntimeLockHeldError:
        _emit({"event": "FAILED", "reason": "LOCK_HELD", "lock_path": str(lock_path), **SAFETY_MARKERS}, args.output)
        return 75
    except KeyboardInterrupt:
        _emit({"event": "INTERRUPTED", "exit_status": 130, **SAFETY_MARKERS}, args.output)
        return 130


def _run(args: argparse.Namespace, *, market: str, evaluation_ts_utc: datetime, started: float) -> int:
    from src.common.db import get_db_connection

    conn = None
    try:
        conn = get_db_connection()
        phase = time.monotonic()

        account_state_snapshot = load_latest_complete_account_state_snapshot(
            conn, trading_account_id=args.trading_account_id, venue=args.venue,
        )
        if account_state_snapshot is None:
            conn.rollback()
            preview = _non_actionable_preview("MISSING_ACCOUNT_STATE_SNAPSHOT", evaluation_ts_utc=evaluation_ts_utc)
            _emit({"event": "FINISHED", "database_writes": 0, **preview, **SAFETY_MARKERS}, args.output)
            return 0

        wallet_snapshot = load_wallet_snapshot(
            conn, trading_account_id=args.trading_account_id, venue=args.venue, asset_id=args.asset_id,
            symbol=args.symbol, snapshot_ts_utc=account_state_snapshot.snapshot_ts_utc,
            source_name=account_state_snapshot.position_source_name,
        )
        if wallet_snapshot is None:
            conn.rollback()
            preview = _non_actionable_preview("MISSING_POSITION_ROW", evaluation_ts_utc=evaluation_ts_utc)
            _emit({"event": "FINISHED", "database_writes": 0, **preview, **SAFETY_MARKERS}, args.output)
            return 0

        balance_snapshot_id = load_balance_snapshot_id(
            conn, trading_account_id=args.trading_account_id, venue=args.venue,
            currency_code=args.quote_currency, snapshot_ts_utc=account_state_snapshot.snapshot_ts_utc,
            source_name=account_state_snapshot.balance_source_name,
        )
        if balance_snapshot_id is None:
            conn.rollback()
            preview = _non_actionable_preview("MISSING_BALANCE_ROW", evaluation_ts_utc=evaluation_ts_utc)
            _emit({"event": "FINISHED", "database_writes": 0, **preview, **SAFETY_MARKERS}, args.output)
            return 0

        account_flags = load_trading_account_flags(conn, trading_account_id=args.trading_account_id)
        if account_flags is None:
            conn.rollback()
            preview = _non_actionable_preview("MISSING_TRADING_ACCOUNT", evaluation_ts_utc=evaluation_ts_utc)
            _emit({"event": "FINISHED", "database_writes": 0, **preview, **SAFETY_MARKERS}, args.output)
            return 0
        account_enabled, live_trading_enabled, account_mode = account_flags

        price_fact = load_latest_market_price(
            conn, venue=args.venue, symbol=args.symbol, quote_currency=args.quote_currency,
        )
        if price_fact is None:
            conn.rollback()
            preview = _non_actionable_preview("MISSING_MARKET_PRICE", evaluation_ts_utc=evaluation_ts_utc)
            _emit({"event": "FINISHED", "database_writes": 0, **preview, **SAFETY_MARKERS}, args.output)
            return 0
        current_price, market_price_snapshot_id, price_observed_ts_utc = price_fact

        venue_constraints_result = load_venue_constraints(
            conn, venue=args.venue, market=market, now=evaluation_ts_utc,
        )
        if venue_constraints_result is None:
            conn.rollback()
            preview = _non_actionable_preview("MISSING_VENUE_CONSTRAINTS", evaluation_ts_utc=evaluation_ts_utc)
            _emit({"event": "FINISHED", "database_writes": 0, **preview, **SAFETY_MARKERS}, args.output)
            return 0
        venue_constraints, venue_constraint_id = venue_constraints_result

        blocking_conflict = load_open_order_conflict(
            conn, trading_account_id=args.trading_account_id, venue=args.venue, market=market,
            snapshot_ts_utc=account_state_snapshot.snapshot_ts_utc,
        )
        reservation_facts = load_reservation_facts(
            conn, trading_account_id=args.trading_account_id, venue=args.venue, asset_id=args.asset_id,
        )
        permissions = load_planning_permissions(conn, trading_account_id=args.trading_account_id)
        profiles = load_exit_profiles(conn, venue=args.venue, asset_id=args.asset_id, market=market)

        _emit(
            {
                "event": "PHASE_FINISHED",
                "phase": "load_evidence",
                "elapsed_ms": round((time.monotonic() - phase) * 1000),
                "database_writes": 0,
            },
            args.output,
        )

        evidence = AutomaticExitRuntimeEvidenceV1(
            trading_account_id=args.trading_account_id,
            venue=args.venue,
            asset_id=args.asset_id,
            symbol=args.symbol,
            market=market,
            position_reference=derive_position_reference(
                trading_account_id=args.trading_account_id, venue=args.venue, asset_id=args.asset_id,
                symbol=args.symbol,
            ),
            evaluation_ts_utc=evaluation_ts_utc,
            permissions=permissions,
            profiles=profiles,
            account_state_snapshot=account_state_snapshot,
            wallet_snapshot=wallet_snapshot,
            balance_snapshot_id=balance_snapshot_id,
            blocking_conflict=blocking_conflict,
            approved_not_submitted_reservation_base=reservation_facts.approved_not_submitted_reservation_base,
            reconciliation_pending_reservation_count=reservation_facts.reconciliation_pending_reservation_count,
            account_enabled=account_enabled,
            live_trading_enabled=live_trading_enabled,
            account_mode=account_mode,
            current_price=current_price,
            market_price_snapshot_id=market_price_snapshot_id,
            price_observed_ts_utc=price_observed_ts_utc,
            venue_constraints=venue_constraints,
            venue_constraint_id=venue_constraint_id,
        )

        result = run_automatic_exit_runtime_cycle_v1(evidence)

        database_writes = 0
        audit_id = None
        if result.auditable and args.commit_audit:
            payload = build_automatic_exit_audit_payload_v1(evidence, result)
            write_result = write_automatic_exit_evaluation_audit_v1(conn, payload=payload)
            conn.commit()
            database_writes = 1 if write_result.created else 0
            audit_id = write_result.automatic_exit_evaluation_audit_id
        else:
            conn.rollback()

        _emit(
            {
                "event": "FINISHED",
                "candidate_state": result.candidate_state,
                "candidate_reason_code": result.candidate_reason_code,
                "gate_state": result.gate_state,
                "gate_reason_code": result.gate_reason_code,
                "planner_state": result.planner_state,
                "planner_reason_code": result.planner_reason_code,
                "final_quantity_base": (
                    str(result.plan.final_quantity_base) if result.plan is not None else None
                ),
                "idempotency_key": result.idempotency_key,
                "auditable": result.auditable,
                "non_auditable_reason": result.non_auditable_reason,
                "automatic_exit_evaluation_audit_id": audit_id,
                "evaluation_ts_utc": result.evaluation_ts_utc.isoformat(),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "database_writes": database_writes,
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return 0
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        _emit(
            {
                "event": "FAILED",
                "error_type": type(exc).__name__,
                "detail": str(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "database_writes": 0,
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
