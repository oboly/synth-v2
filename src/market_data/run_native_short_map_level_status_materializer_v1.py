from __future__ import annotations

"""Bounded runner for the native SHORT map-level status materializer.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

import argparse
import dataclasses
import json
import signal
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Callable

from src.common.db import get_connection
from src.market_data.native_short_map_level_status_materializer_v1 import (
    BLOCKED,
    GEOMETRY_INVALID,
    NO_CURRENT_MAP,
    PROJECTION_INVALID,
    PROJECTION_MISSING,
    MapLevelStatusMaterializationOutcome,
    materialize_native_short_map_level_status_for_scope,
)
from src.market_data.native_short_map_level_target_event_materializer_v1 import (
    materialize_native_short_map_level_target_events_for_scope,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_materializer_v1 import (
    NativeShortRunBuilder,
    _finalize_run,
    _insert_run,
)
from src.market_data.native_short_scope_status_v1 import NativeShortRunTerminalStatus
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceInspector,
    build_verified_process_provenance,
    inspect_running_repository_source,
)
from src.market_data.native_short_writer_provenance_v1 import (
    MANUAL_MAP_LEVEL_TRIGGER_TYPE,
    NativeShortWriterExecutionMode,
    NativeShortWriterProvenance,
    NativeShortWriterProvenanceError,
    validate_native_short_writer_provenance,
)
from src.operations.writer_capability_authorization_v1 import WriterMutationAuthorization


RUNNER_NAME = "run_native_short_map_level_status_materializer_v1"
RUNNER_VERSION = "0.1"
EXPECTED_LEVEL_ROW_COUNT = 3

SAFETY_MARKERS: dict[str, int | str] = {
    "broker_calls": 0,
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}


@dataclass(frozen=True)
class ScopeRunResult:
    venue: str
    symbol: str
    quote_currency: str
    fib_trading_horizon: str
    primary_interval: str
    supporting_interval: str
    status: str
    branch: str | None
    reason_code: str | None
    detail: str | None
    row_count: int
    current_map_id: int | None
    map_cycle_id: str | None
    level_status_as_of_utc: datetime | None
    rows_read: int = 0
    # `rows_written` keeps its pre-existing meaning unchanged: level-status
    # projection rows only. `status_rows_written` is an explicit alias of the
    # same value, added so downstream write-observability consumers never
    # have to guess which table a bare `rows_written` refers to once a second
    # write path (target events) exists on this same result.
    rows_written: int = 0
    status_rows_written: int = 0
    target_event_rows_written: int = 0
    rows_written_total: int = 0
    elapsed_ms: int = 0
    phase_elapsed_ms_by_name: dict[str, int] | None = None
    query_elapsed_ms_by_name: dict[str, int] | None = None
    target_event_coverage_eligible: bool | None = None
    target_event_skip_reason: str | None = None
    requested_target_event_watermark_utc: datetime | None = None
    persisted_target_event_coverage_cutoff_utc: datetime | None = None


@dataclass
class InterruptionController:
    """Signal state only; handlers never print or perform database work."""
    interruption_signal: str | None = None

    @property
    def requested(self) -> bool:
        return self.interruption_signal is not None

    @property
    def exit_code(self) -> int:
        return 130 if self.interruption_signal == "SIGINT" else 143

    def request(self, signum: int) -> None:
        if self.interruption_signal is None:
            self.interruption_signal = signal.Signals(signum).name

    def request_keyboard_interrupt(self) -> None:
        if self.interruption_signal is None:
            self.interruption_signal = "SIGINT"


def _elapsed_ms(start_monotonic: float, *, clock: Callable[[], float] = monotonic) -> int:
    return max(0, round((clock() - start_monotonic) * 1000))


def _record_elapsed(timings: dict[str, int], name: str, elapsed_ms: int) -> None:
    timings[name] = timings.get(name, 0) + elapsed_ms


def _required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise argparse.ArgumentTypeError("value must not be empty")
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically rebuild native SHORT map-level status rows for an "
            "explicit full market-data scope."
        )
    )
    parser.add_argument("--venue", required=True, type=_required_text)
    parser.add_argument(
        "--symbols",
        required=True,
        type=_required_text,
        help="Explicit comma-separated symbols, e.g. BTC or BTC,ETH.",
    )
    parser.add_argument("--quote-currency", required=True, type=_required_text)
    parser.add_argument("--fib-trading-horizon", required=True, type=_required_text)
    parser.add_argument("--primary-interval", required=True, type=_required_text)
    parser.add_argument("--supporting-interval", required=True, type=_required_text)
    parser.add_argument(
        "--execution-mode",
        required=True,
        choices=(NativeShortWriterExecutionMode.MANUAL.value,),
    )
    parser.add_argument("--repository-commit", required=True, type=_required_text)
    parser.add_argument("--trigger-ref", required=True, type=_required_text)
    parser.add_argument(
        "--output",
        choices=("jsonl", "summary"),
        default="jsonl",
        help="jsonl emits one deterministic machine-readable record per event/result.",
    )
    parser.add_argument(
        "--target-event-coverage-watermark-utc",
        default=None,
        type=_required_text,
        help=(
            "Optional explicit ISO-8601 UTC watermark (e.g. 2026-08-01T00:00:00+00:00). "
            "When supplied, appends immutable REACHED/PASSED target events (in the same "
            "transaction as the level-status rebuild) for maps published at or after this "
            "timestamp only. Omit to leave behavior byte-for-byte unchanged (no target-event "
            "read or write of any kind)."
        ),
    )
    return parser.parse_args(argv)


def parse_symbols(text: str) -> list[str]:
    symbols = sorted({part.strip().upper() for part in text.split(",") if part.strip()})
    if not symbols:
        raise ValueError("--symbols must contain at least one explicit symbol")
    return symbols


def utc_now() -> datetime:
    """Operational metadata clock; never used as materializer semantic time."""
    return datetime.now(UTC)


def _blocked_detail(reason_code: str | None) -> str:
    if reason_code == PROJECTION_MISSING:
        return "scope projection row missing; no level-status rows emitted"
    if reason_code == PROJECTION_INVALID:
        return "selected map missing or projection/map identity invalid; no level-status rows emitted"
    if reason_code == NO_CURRENT_MAP:
        return "selected map missing from scope projection; no level-status rows emitted"
    if reason_code == GEOMETRY_INVALID:
        return "selected map geometry invalid; no level-status rows emitted"
    return f"unsupported scope state blocks row emission: {reason_code or 'UNKNOWN'}"


def _result_from_outcome(outcome: MapLevelStatusMaterializationOutcome) -> ScopeRunResult:
    status = "materialized"
    detail = None
    reason_code = outcome.reason_code
    if outcome.branch == BLOCKED:
        status = "blocked"
        detail = _blocked_detail(reason_code)
    elif outcome.row_count != EXPECTED_LEVEL_ROW_COUNT:
        status = "failed"
        reason_code = "UNEXPECTED_ROW_COUNT"
        detail = (
            f"expected {EXPECTED_LEVEL_ROW_COUNT} level-status rows, "
            f"materializer reported {outcome.row_count}"
        )

    return ScopeRunResult(
        venue=outcome.key.venue,
        symbol=outcome.key.symbol,
        quote_currency=outcome.key.quote_currency,
        fib_trading_horizon=outcome.key.fib_trading_horizon,
        primary_interval=outcome.key.primary_interval,
        supporting_interval=outcome.key.supporting_interval,
        status=status,
        branch=outcome.branch,
        reason_code=reason_code,
        detail=detail,
        row_count=outcome.row_count,
        current_map_id=outcome.current_map_id,
        map_cycle_id=outcome.map_cycle_id,
        level_status_as_of_utc=outcome.level_status_as_of_utc,
    )


def _failed_result(key: NativeShortMapScopeKey, exc: Exception) -> ScopeRunResult:
    return ScopeRunResult(
        venue=key.venue,
        symbol=key.symbol,
        quote_currency=key.quote_currency,
        fib_trading_horizon=key.fib_trading_horizon,
        primary_interval=key.primary_interval,
        supporting_interval=key.supporting_interval,
        status="failed",
        branch=None,
        reason_code=type(exc).__name__,
        detail=str(exc),
        row_count=0,
        current_map_id=None,
        map_cycle_id=None,
        level_status_as_of_utc=None,
    )


def _interrupted_result(
    key: NativeShortMapScopeKey,
    *,
    elapsed_ms: int,
    phase_elapsed_ms_by_name: dict[str, int],
    query_elapsed_ms_by_name: dict[str, int],
) -> ScopeRunResult:
    return ScopeRunResult(
        venue=key.venue,
        symbol=key.symbol,
        quote_currency=key.quote_currency,
        fib_trading_horizon=key.fib_trading_horizon,
        primary_interval=key.primary_interval,
        supporting_interval=key.supporting_interval,
        status="interrupted",
        branch=None,
        reason_code="INTERRUPTED",
        detail="cooperative shutdown requested before symbol commit",
        row_count=0,
        current_map_id=None,
        map_cycle_id=None,
        level_status_as_of_utc=None,
        elapsed_ms=elapsed_ms,
        phase_elapsed_ms_by_name=phase_elapsed_ms_by_name,
        query_elapsed_ms_by_name=query_elapsed_ms_by_name,
    )


def run_scope(
    *,
    key: NativeShortMapScopeKey,
    operational_clock: Callable[[], datetime],
    provenance: NativeShortWriterProvenance,
    authorization: WriterMutationAuthorization,
    interruption: InterruptionController | None = None,
    monotonic_clock: Callable[[], float] = monotonic,
    target_event_coverage_watermark_utc: datetime | None = None,
) -> ScopeRunResult:
    """Rebuild level-status rows, then optionally append target events.

    ``target_event_coverage_watermark_utc`` is optional and defaults to
    ``None``. When ``None`` (the default, and every existing call site's
    behavior), this function is byte-for-byte identical to its prior
    behavior: no target-event table is read or written. Passing an explicit
    watermark is an opt-in activation decision (see
    docs/architecture/native_short_map_level_status_contract_v1.md, target
    lifecycle-history addendum) and only ever appends events for maps
    published at or after that watermark, in the same transaction as the
    level-status row rebuild.
    """
    validate_native_short_writer_provenance(provenance)
    interruption = interruption or InterruptionController()
    started_monotonic = monotonic_clock()
    phase_elapsed_ms_by_name: dict[str, int] = {}
    query_elapsed_ms_by_name: dict[str, int] = {}
    conn = None
    try:
        if interruption.requested:
            return _interrupted_result(
                key,
                elapsed_ms=_elapsed_ms(started_monotonic, clock=monotonic_clock),
                phase_elapsed_ms_by_name=phase_elapsed_ms_by_name,
                query_elapsed_ms_by_name=query_elapsed_ms_by_name,
            )
        conn = get_connection()
        conn.begin()
        if interruption.requested:
            rollback_started = monotonic_clock()
            conn.rollback()
            _record_elapsed(
                phase_elapsed_ms_by_name,
                "ROLLBACK_SYMBOL",
                _elapsed_ms(rollback_started, clock=monotonic_clock),
            )
            return _interrupted_result(
                key,
                elapsed_ms=_elapsed_ms(started_monotonic, clock=monotonic_clock),
                phase_elapsed_ms_by_name=phase_elapsed_ms_by_name,
                query_elapsed_ms_by_name=query_elapsed_ms_by_name,
            )

        # The materializer owns the bounded scope queries.  This runner records
        # the complete query/materialization phase without changing its semantics.
        materialize_started = monotonic_clock()
        outcome = materialize_native_short_map_level_status_for_scope(
            conn,
            key=key,
            operational_clock=operational_clock,
            provenance=provenance,
            authorization=authorization,
        )
        materialize_elapsed_ms = _elapsed_ms(materialize_started, clock=monotonic_clock)
        _record_elapsed(phase_elapsed_ms_by_name, "MATERIALIZE_LEVEL_STATUS", materialize_elapsed_ms)
        _record_elapsed(query_elapsed_ms_by_name, "MATERIALIZE_LEVEL_STATUS", materialize_elapsed_ms)

        if interruption.requested:
            rollback_started = monotonic_clock()
            conn.rollback()
            _record_elapsed(
                phase_elapsed_ms_by_name,
                "ROLLBACK_SYMBOL",
                _elapsed_ms(rollback_started, clock=monotonic_clock),
            )
            return _interrupted_result(
                key,
                elapsed_ms=_elapsed_ms(started_monotonic, clock=monotonic_clock),
                phase_elapsed_ms_by_name=phase_elapsed_ms_by_name,
                query_elapsed_ms_by_name=query_elapsed_ms_by_name,
            )

        result = _result_from_outcome(outcome)
        if result.status == "failed":
            rollback_started = monotonic_clock()
            conn.rollback()
            _record_elapsed(
                phase_elapsed_ms_by_name,
                "ROLLBACK_SYMBOL",
                _elapsed_ms(rollback_started, clock=monotonic_clock),
            )
        else:
            # A blocked materialization deliberately deletes stale scope rows,
            # so its bounded cleanup must commit even though the CLI exits 1.
            if interruption.requested:
                rollback_started = monotonic_clock()
                conn.rollback()
                _record_elapsed(
                    phase_elapsed_ms_by_name,
                    "ROLLBACK_SYMBOL",
                    _elapsed_ms(rollback_started, clock=monotonic_clock),
                )
                return _interrupted_result(
                    key,
                    elapsed_ms=_elapsed_ms(started_monotonic, clock=monotonic_clock),
                    phase_elapsed_ms_by_name=phase_elapsed_ms_by_name,
                    query_elapsed_ms_by_name=query_elapsed_ms_by_name,
                )
            if result.status == "materialized" and target_event_coverage_watermark_utc is not None:
                target_event_started = monotonic_clock()
                target_event_outcome = materialize_native_short_map_level_target_events_for_scope(
                    conn,
                    key=key,
                    target_event_coverage_watermark_utc=target_event_coverage_watermark_utc,
                    provenance=provenance,
                    authorization=authorization,
                )
                _record_elapsed(
                    phase_elapsed_ms_by_name,
                    "MATERIALIZE_TARGET_EVENTS",
                    _elapsed_ms(target_event_started, clock=monotonic_clock),
                )
                result = dataclasses.replace(
                    result,
                    target_event_coverage_eligible=target_event_outcome.coverage_eligible,
                    target_event_skip_reason=target_event_outcome.skip_reason,
                    target_event_rows_written=target_event_outcome.events_appended,
                    requested_target_event_watermark_utc=target_event_outcome.requested_watermark_utc,
                    persisted_target_event_coverage_cutoff_utc=(
                        target_event_outcome.persisted_coverage_cutoff_utc
                    ),
                )
            commit_started = monotonic_clock()
            conn.commit()
            _record_elapsed(
                phase_elapsed_ms_by_name,
                "COMMIT_SYMBOL",
                _elapsed_ms(commit_started, clock=monotonic_clock),
            )
        status_rows_written = result.row_count if result.status == "materialized" else 0
        return dataclasses.replace(
            result,
            rows_written=status_rows_written,
            status_rows_written=status_rows_written,
            rows_written_total=status_rows_written + result.target_event_rows_written,
            elapsed_ms=_elapsed_ms(started_monotonic, clock=monotonic_clock),
            phase_elapsed_ms_by_name=phase_elapsed_ms_by_name,
            query_elapsed_ms_by_name=query_elapsed_ms_by_name,
        )
    except KeyboardInterrupt:
        interruption.request_keyboard_interrupt()
        if conn is not None:
            rollback_started = monotonic_clock()
            conn.rollback()
            _record_elapsed(
                phase_elapsed_ms_by_name,
                "ROLLBACK_SYMBOL",
                _elapsed_ms(rollback_started, clock=monotonic_clock),
            )
        return _interrupted_result(
            key,
            elapsed_ms=_elapsed_ms(started_monotonic, clock=monotonic_clock),
            phase_elapsed_ms_by_name=phase_elapsed_ms_by_name,
            query_elapsed_ms_by_name=query_elapsed_ms_by_name,
        )
    except Exception as exc:
        if conn is not None:
            rollback_started = monotonic_clock()
            conn.rollback()
            _record_elapsed(
                phase_elapsed_ms_by_name,
                "ROLLBACK_SYMBOL",
                _elapsed_ms(rollback_started, clock=monotonic_clock),
            )
        return dataclasses.replace(
            _failed_result(key, exc),
            elapsed_ms=_elapsed_ms(started_monotonic, clock=monotonic_clock),
            phase_elapsed_ms_by_name=phase_elapsed_ms_by_name,
            query_elapsed_ms_by_name=query_elapsed_ms_by_name,
        )
    finally:
        if conn is not None:
            conn.close()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, default=_json_default))
    sys.stdout.flush()


def _scope_payload(args: argparse.Namespace, symbols: list[str]) -> dict[str, Any]:
    return {
        "venue": args.venue,
        "symbols": symbols,
        "quote_currency": args.quote_currency,
        "fib_trading_horizon": args.fib_trading_horizon,
        "primary_interval": args.primary_interval,
        "supporting_interval": args.supporting_interval,
    }


def _emit_started(args: argparse.Namespace, symbols: list[str]) -> None:
    scope = _scope_payload(args, symbols)
    if args.output == "jsonl":
        _emit_json(
            {
                "event": "STARTED",
                "runner": RUNNER_NAME,
                "runner_version": RUNNER_VERSION,
                **scope,
                **SAFETY_MARKERS,
            }
        )
        return

    print(f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION}")
    print(
        f"venue={args.venue} symbols={','.join(symbols)} "
        f"quote_currency={args.quote_currency} "
        f"fib_trading_horizon={args.fib_trading_horizon} "
        f"primary_interval={args.primary_interval} "
        f"supporting_interval={args.supporting_interval}"
    )
    for marker, value in SAFETY_MARKERS.items():
        print(f"{marker}={value}")
    sys.stdout.flush()


def _emit_result(result: ScopeRunResult, output: str) -> None:
    if output == "jsonl":
        _emit_json({"event": "RESULT", "runner": RUNNER_NAME, **asdict(result)})
        return

    reason = f" reason={result.reason_code}" if result.reason_code else ""
    detail = f" detail={result.detail}" if result.detail else ""
    print(
        f"{result.status.upper()} symbol={result.symbol} branch={result.branch} "
        f"rows={result.row_count}{reason}{detail}"
    )
    sys.stdout.flush()


def _sum_named_timings(results: list[ScopeRunResult], attribute: str) -> dict[str, int]:
    total: dict[str, int] = {}
    for result in results:
        for name, elapsed_ms in (getattr(result, attribute) or {}).items():
            _record_elapsed(total, name, elapsed_ms)
    return dict(sorted(total.items()))


def _emit_heartbeat(
    *,
    output: str,
    current_symbol: str | None,
    symbol_index: int,
    symbols_total: int,
    symbols_completed: int,
    current_phase: str,
    phase_elapsed_ms: int,
    total_elapsed_ms: int,
    rows_read: int,
    rows_written: int,
    status_rows_written: int | None = None,
    target_event_rows_written: int | None = None,
    rows_written_total: int | None = None,
) -> None:
    payload = {
        "event": "HEARTBEAT",
        "runner": RUNNER_NAME,
        "current_symbol": current_symbol,
        "symbol_index": symbol_index,
        "symbols_total": symbols_total,
        "symbols_completed": symbols_completed,
        "current_phase": current_phase,
        "phase_elapsed_ms": phase_elapsed_ms,
        "total_elapsed_ms": total_elapsed_ms,
        "rows_read": rows_read,
        # Compatibility field: status-only rows written, meaning unchanged.
        "rows_written": rows_written,
        # Explicit aggregate counters (P2 write-observability fix): a target
        # event write must never silently disappear from run-level output.
        "status_rows_written": status_rows_written if status_rows_written is not None else rows_written,
        "target_event_rows_written": target_event_rows_written or 0,
        "rows_written_total": (
            rows_written_total if rows_written_total is not None else rows_written
        ),
    }
    if output == "jsonl":
        _emit_json(payload)
        return
    print(
        "HEARTBEAT "
        + " ".join(f"{key}={value}" for key, value in payload.items() if key not in {"event", "runner"})
    )
    sys.stdout.flush()


def _emit_terminal(
    *,
    results: list[ScopeRunResult],
    output: str,
    symbols_requested: int,
    interruption: InterruptionController,
    total_elapsed_ms: int,
) -> None:
    materialized = sum(result.status == "materialized" for result in results)
    blocked = sum(result.status == "blocked" for result in results)
    failed = sum(result.status == "failed" for result in results)
    interrupted = interruption.requested
    status = "INTERRUPTED" if interrupted else ("SUCCESS" if blocked == 0 and failed == 0 else "FAILED")
    event = "INTERRUPTED" if interrupted else ("FINISHED" if status == "SUCCESS" else "FAILED")
    rows_read = sum(result.rows_read for result in results)
    # Compatibility: `rows_written` keeps its pre-existing status-only
    # meaning. The explicit aggregate counters below are additive and must
    # never be inferred by a consumer from `rows_written` alone, since a
    # target-event write must never silently disappear from run-level output.
    rows_written = sum(result.rows_written for result in results)
    status_rows_written = sum(result.status_rows_written for result in results)
    target_event_rows_written = sum(result.target_event_rows_written for result in results)
    rows_written_total = sum(result.rows_written_total for result in results)
    payload = {
        "event": event,
        "status": status,
        "runner": RUNNER_NAME,
        "requested": symbols_requested,
        "symbols_requested": symbols_requested,
        "symbols_completed": materialized,
        "symbols_remaining": symbols_requested - materialized,
        "materialized": materialized,
        "blocked": blocked,
        "failed": failed,
        "interrupted": interrupted,
        "interruption_signal": interruption.interruption_signal,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "status_rows_written": status_rows_written,
        "target_event_rows_written": target_event_rows_written,
        "rows_written_total": rows_written_total,
        "elapsed_ms": total_elapsed_ms,
        "phase_elapsed_ms_by_name": _sum_named_timings(results, "phase_elapsed_ms_by_name"),
        "query_elapsed_ms_by_name": _sum_named_timings(results, "query_elapsed_ms_by_name"),
        "per_symbol_elapsed_ms": {
            result.symbol: result.elapsed_ms
            for result in results
        },
        **SAFETY_MARKERS,
    }
    if output == "jsonl":
        _emit_json(payload)
        return
    print(
        f"{event} runner={RUNNER_NAME} status={status} requested={symbols_requested} "
        f"materialized={materialized} blocked={blocked} failed={failed} elapsed_ms={total_elapsed_ms}"
    )
    sys.stdout.flush()


def _install_signal_handlers(controller: InterruptionController) -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def request_shutdown(signum: int, _frame: Any) -> None:
        controller.request(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_shutdown)
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _start_writer_run(
    provenance: NativeShortWriterProvenance,
    *,
    requested_scope_count: int,
    authorization: Any = None,
) -> tuple[NativeShortRunBuilder, int]:
    builder = NativeShortRunBuilder(
        provenance=provenance,
        contract_version="native_short_map_level_status_v1",
        started_at_utc=utc_now(),
        requested_scope_count=requested_scope_count,
    )
    conn = get_connection()
    try:
        conn.begin()
        run_id = _insert_run(conn, builder.started_record(), authorization=authorization)
        conn.commit()
        return builder, run_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish_writer_run(
    builder: NativeShortRunBuilder,
    run_id: int,
    *,
    terminal_status: NativeShortRunTerminalStatus,
    authorization: Any = None,
) -> None:
    conn = get_connection()
    try:
        conn.begin()
        _finalize_run(
            conn,
            run_id,
            builder.finish(finished_at_utc=utc_now(), terminal_status=terminal_status),
            authorization=authorization,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(
    argv: list[str] | None = None,
    *,
    inspect_repository_source: NativeShortRepositorySourceInspector = (
        inspect_running_repository_source
    ),
) -> int:
    args = parse_args(argv)
    try:
        symbols = parse_symbols(args.symbols)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    target_event_coverage_watermark_utc: datetime | None = None
    if args.target_event_coverage_watermark_utc is not None:
        try:
            parsed_watermark = datetime.fromisoformat(args.target_event_coverage_watermark_utc)
        except ValueError as exc:
            print(
                f"ERROR: invalid --target-event-coverage-watermark-utc: {exc}",
                file=sys.stderr,
            )
            return 2
        if parsed_watermark.tzinfo is None:
            print(
                "ERROR: --target-event-coverage-watermark-utc must be timezone-aware UTC",
                file=sys.stderr,
            )
            return 2
        target_event_coverage_watermark_utc = parsed_watermark.astimezone(UTC)

    try:
        provenance = build_verified_process_provenance(
            writer_entrypoint="src.market_data.run_native_short_map_level_status_materializer_v1",
            runner_name=RUNNER_NAME,
            runner_version=RUNNER_VERSION,
            execution_mode=args.execution_mode,
            repository_commit_sha=args.repository_commit,
            trigger_type=MANUAL_MAP_LEVEL_TRIGGER_TYPE,
            trigger_ref=args.trigger_ref,
            inspect_repository_source=inspect_repository_source,
        )
    except NativeShortWriterProvenanceError as exc:
        print(f"INVALID_PROVENANCE runner={RUNNER_NAME} detail={exc}", file=sys.stderr)
        return 2

    from src.operations.writer_capability_authorization_v1 import (
        require_capability_write_authorization,
    )

    # Authorize before creating the initial run row. Never create a partial run
    # record and authorize later. The shared guard still validates the registry
    # unit binding; the optional cross-check argument is omitted here.
    writer_authorization = require_capability_write_authorization(
        "native_short_4h_chain",
    )

    controller = InterruptionController()
    run_builder, run_id = _start_writer_run(
        provenance, requested_scope_count=len(symbols), authorization=writer_authorization
    )
    previous_signal_handlers = _install_signal_handlers(controller)
    started_monotonic = monotonic()
    _emit_started(args, symbols)
    results: list[ScopeRunResult] = []
    try:
        for index, symbol in enumerate(symbols, start=1):
            if controller.requested:
                break
            _emit_heartbeat(
                output=args.output,
                current_symbol=symbol,
                symbol_index=index,
                symbols_total=len(symbols),
                symbols_completed=sum(result.status == "materialized" for result in results),
                current_phase="BEFORE_SYMBOL",
                phase_elapsed_ms=0,
                total_elapsed_ms=_elapsed_ms(started_monotonic),
                rows_read=sum(result.rows_read for result in results),
                rows_written=sum(result.rows_written for result in results),
                status_rows_written=sum(result.status_rows_written for result in results),
                target_event_rows_written=sum(result.target_event_rows_written for result in results),
                rows_written_total=sum(result.rows_written_total for result in results),
            )
            key = NativeShortMapScopeKey(
                venue=args.venue,
                symbol=symbol,
                quote_currency=args.quote_currency,
                fib_trading_horizon=args.fib_trading_horizon,
                primary_interval=args.primary_interval,
                supporting_interval=args.supporting_interval,
            )
            result = run_scope(
                key=key,
                operational_clock=utc_now,
                provenance=provenance,
                authorization=writer_authorization,
                interruption=controller,
                target_event_coverage_watermark_utc=target_event_coverage_watermark_utc,
            )
            results.append(result)
            run_builder.record_scope_outcome(failed=result.status in {"blocked", "failed"})
            _emit_result(result, args.output)
            _emit_heartbeat(
                output=args.output,
                current_symbol=symbol,
                symbol_index=index,
                symbols_total=len(symbols),
                symbols_completed=sum(item.status == "materialized" for item in results),
                current_phase="SYMBOL_COMPLETED" if result.status == "materialized" else result.status.upper(),
                phase_elapsed_ms=result.elapsed_ms,
                total_elapsed_ms=_elapsed_ms(started_monotonic),
                rows_read=sum(item.rows_read for item in results),
                rows_written=sum(item.rows_written for item in results),
                status_rows_written=sum(item.status_rows_written for item in results),
                target_event_rows_written=sum(item.target_event_rows_written for item in results),
                rows_written_total=sum(item.rows_written_total for item in results),
            )
            if result.status != "materialized" and result.status != "interrupted":
                print(
                    f"{result.status.upper()} {symbol}: "
                    f"{result.reason_code or 'UNKNOWN'}: {result.detail or ''}",
                    file=sys.stderr,
                )
            if controller.requested:
                break
    except KeyboardInterrupt:
        controller.request_keyboard_interrupt()
    finally:
        terminal_status = (
            NativeShortRunTerminalStatus.INTERRUPTED
            if controller.requested
            else (
                NativeShortRunTerminalStatus.FINISHED
                if all(result.status == "materialized" for result in results)
                else NativeShortRunTerminalStatus.FAILED
            )
        )
        _finish_writer_run(
            run_builder, run_id, terminal_status=terminal_status,
            authorization=writer_authorization,
        )
        _emit_terminal(
            results=results,
            output=args.output,
            symbols_requested=len(symbols),
            interruption=controller,
            total_elapsed_ms=_elapsed_ms(started_monotonic),
        )
        _restore_signal_handlers(previous_signal_handlers)

    if controller.requested:
        return controller.exit_code
    return 0 if all(result.status == "materialized" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
