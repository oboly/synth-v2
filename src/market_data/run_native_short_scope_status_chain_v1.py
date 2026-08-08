from __future__ import annotations

"""Runtime adapter for the canonical native SHORT scope-status chain.

The bounded orchestrator owns this order for every selected scope:

    map evaluation -> scope-status projection -> map-level status projection

Only current, explicitly SUPPORTED market-data scopes are selected.  An
optional explicit symbol list narrows that persisted scope universe for a
bounded operator smoke run.

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
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Sequence

from src.common.db import get_connection
from src.market_data.native_short_fib_context_v1 import (
    STATUS_SYMBOL_MISSING,
    Candle,
    NativeShortContextRow,
    build_native_short_context_row,
)
from src.market_data.native_short_map_lifecycle_v1 import (
    DEFAULT_FIB_TRADING_HORIZON,
    DEFAULT_PRIMARY_INTERVAL,
    DEFAULT_QUOTE_CURRENCY,
    DEFAULT_SUPPORTING_INTERVAL,
    NativeShortMapScopeKey,
)
from src.market_data import native_short_map_materializer_v1 as map_materializer
from src.market_data.native_short_scope_status_materializer_v1 import (
    CONTRACT_VERSION,
    NativeShortMapLevelStatusBlockedError,
    NativeShortRunBuilder,
    ScopeChainOutcome,
    _finalize_run,
    _insert_run,
    evaluate_and_project_scope,
)
from src.market_data.native_short_scope_status_v1 import (
    NativeShortMaterializerRunRecord,
    NativeShortRunTerminalStatus,
)
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceInspector,
    build_verified_process_provenance,
    inspect_running_repository_source,
)
from src.market_data.native_short_writer_provenance_v1 import (
    CHAIN_TRIGGER_TYPE,
    NativeShortWriterExecutionMode,
    NativeShortWriterProvenance,
    NativeShortWriterProvenanceError,
    validate_native_short_writer_provenance,
)
from src.market_data.native_short_writer_commit_fence_v1 import (
    capture_writer_commit_fences,
    revalidate_writer_commit_fences,
)


RUNNER_NAME = "run_native_short_scope_status_chain_v1"
RUNNER_VERSION = "0.1"
RUNTIME_MODE = "market_data_write"
WORKER_COUNT = 1
TRIGGER_TYPE = CHAIN_TRIGGER_TYPE
EXPECTED_LEVEL_ROWS_PER_OBSERVED_SCOPE = 3
PRIMARY_LOOKBACK = timedelta(days=60)
SUPPORTING_LOOKBACK = timedelta(days=21)
HEARTBEAT_INTERVAL_SECONDS = 15.0
MAX_FAILURE_DETAIL_LENGTH = 2000

# Per-scope terminal outcome vocabulary for one bounded chain run. These are
# orchestration-result labels only; they are never persisted as a run
# terminal_status (that column's CHECK constraint owns its own vocabulary).
SCOPE_STATUS_SUCCEEDED = "SUCCEEDED"
SCOPE_STATUS_SKIPPED_NOT_SUPPORTED = "SKIPPED_NOT_SUPPORTED"
# A supported scope that has never published any map and is therefore in its
# expected, transient first-map bootstrap state (Issue #298). Its own
# transaction still commits normally, it is not a failure, and it never stops
# evaluation of unrelated scopes ordered after it.
SCOPE_STATUS_BOOTSTRAP_PENDING = "BOOTSTRAP_PENDING"
SCOPE_STATUS_BLOCKED = "BLOCKED"
SCOPE_STATUS_UNEXPECTED_FAILED = "UNEXPECTED_FAILED"

# Explicit reviewed orchestration policy after a per-scope terminal failure.
FAILURE_POLICY = "continue_on_unexpected_stop_on_blocked"
TRANSACTION_BOUNDARY = "exact_scope"
UNEXPECTED_FAILURE_REASON_CODE = "SCOPE_ISOLATION_UNEXPECTED_FAILURE"

SAFETY_MARKERS: dict[str, int | str] = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}


class RuntimeScopeConfigurationError(RuntimeError):
    pass


class RuntimeScopeEvaluationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandleBundle:
    primary: tuple[Candle, ...]
    supporting: tuple[Candle, ...]


@dataclass(frozen=True)
class ScopeChainResult:
    """Attributable terminal evidence for exactly one canonical scope."""

    key: NativeShortMapScopeKey
    status: str
    detail: str | None = None


@dataclass(frozen=True)
class RuntimeResult:
    run: NativeShortMaterializerRunRecord
    selected_scope_count: int
    candle_rows_read: int
    elapsed_ms: int
    scope_results: tuple[ScopeChainResult, ...] = ()

    @property
    def map_level_status_row_count(self) -> int:
        return (self.run.observed_scope_count or 0) * EXPECTED_LEVEL_ROWS_PER_OBSERVED_SCOPE


def _required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise argparse.ArgumentTypeError("value must not be empty")
    return normalized


def _parse_as_of_utc(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--as-of-utc must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--as-of-utc must include a UTC offset")
    return parsed.astimezone(UTC)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the canonical native SHORT map evaluation, scope-status, and "
            "map-level status chain for persisted SUPPORTED scopes."
        )
    )
    parser.add_argument("--venue", required=True, type=_required_text)
    parser.add_argument(
        "--symbols",
        default="",
        help=(
            "Optional comma-separated restriction for bounded smoke runs. "
            "Omit to use the exact persisted SUPPORTED scope universe."
        ),
    )
    parser.add_argument(
        "--quote-currency",
        required=True,
        choices=(DEFAULT_QUOTE_CURRENCY,),
    )
    parser.add_argument(
        "--fib-trading-horizon",
        required=True,
        choices=(DEFAULT_FIB_TRADING_HORIZON,),
    )
    parser.add_argument(
        "--primary-interval",
        required=True,
        choices=(DEFAULT_PRIMARY_INTERVAL,),
    )
    parser.add_argument(
        "--supporting-interval",
        required=True,
        choices=(DEFAULT_SUPPORTING_INTERVAL,),
    )
    parser.add_argument("--as-of-utc", type=_parse_as_of_utc)
    parser.add_argument(
        "--execution-mode",
        required=True,
        choices=(
            NativeShortWriterExecutionMode.CHAIN.value,
            NativeShortWriterExecutionMode.MANUAL.value,
        ),
    )
    parser.add_argument("--writer-entrypoint", required=True, type=_required_text)
    parser.add_argument("--repository-commit", required=True, type=_required_text)
    parser.add_argument("--trigger-type", required=True, type=_required_text)
    parser.add_argument("--trigger-ref", required=True, type=_required_text)
    parser.add_argument("--allowed-untracked-path")
    parser.add_argument("--output", choices=("jsonl", "summary"), default="summary")
    return parser.parse_args(argv)


def parse_symbols(value: str) -> list[str]:
    return sorted({part.strip().upper() for part in value.split(",") if part.strip()})


def utc_now() -> datetime:
    return datetime.now(UTC)


def fetch_supported_scope_keys(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
    fib_trading_horizon: str,
    primary_interval: str,
    supporting_interval: str,
    symbols: Sequence[str],
) -> list[NativeShortMapScopeKey]:
    symbol_filter = ""
    params: list[str] = [
        venue,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
    ]
    if symbols:
        symbol_filter = f" AND symbol IN ({','.join(['%s'] * len(symbols))})"
        params.extend(symbols)
    sql = f"""
    SELECT venue, symbol, quote_currency, fib_trading_horizon,
           primary_interval, supporting_interval
    FROM native_short_map_scope_v1
    WHERE scope_support_state = 'SUPPORTED'
      AND venue = %s
      AND quote_currency = %s
      AND fib_trading_horizon = %s
      AND primary_interval = %s
      AND supporting_interval = %s
      {symbol_filter}
    ORDER BY venue, symbol, quote_currency, fib_trading_horizon,
             primary_interval, supporting_interval
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = list(cur.fetchall())

    keys = [
        NativeShortMapScopeKey(
            venue=str(row["venue"]),
            symbol=str(row["symbol"]).upper(),
            quote_currency=str(row["quote_currency"]),
            fib_trading_horizon=str(row["fib_trading_horizon"]),
            primary_interval=str(row["primary_interval"]),
            supporting_interval=str(row["supporting_interval"]),
        )
        for row in rows
    ]
    if symbols:
        found = {key.symbol for key in keys}
        missing = sorted(set(symbols) - found)
        if missing:
            raise RuntimeScopeConfigurationError(
                "EXPLICIT_SUPPORTED_SCOPE_MISSING symbols=" + ",".join(missing)
            )
    if not keys:
        raise RuntimeScopeConfigurationError("NO_SUPPORTED_NATIVE_SHORT_SCOPES")
    return keys


def _fetch_candles(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    interval_code: str,
    since_utc: datetime,
    as_of_utc: datetime,
) -> tuple[Candle, ...]:
    sql = """
    SELECT c.close_ts_utc, c.open_price, c.high_price, c.low_price, c.close_price
    FROM obs_market_candle c
    JOIN asset a ON a.asset_id = c.asset_id
    WHERE c.venue = %s
      AND c.interval_code = %s
      AND a.symbol = %s
      AND c.close_ts_utc >= %s
      AND c.close_ts_utc <= %s
    ORDER BY c.close_ts_utc ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (key.venue, interval_code, key.symbol, since_utc, as_of_utc))
        rows = list(cur.fetchall())
    return tuple(
        Candle(
            close_ts_utc=_as_utc(row["close_ts_utc"]),
            open_price=Decimal(str(row["open_price"])),
            high_price=Decimal(str(row["high_price"])),
            low_price=Decimal(str(row["low_price"])),
            close_price=Decimal(str(row["close_price"])),
        )
        for row in rows
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class RuntimeMarketData:
    def __init__(
        self,
        conn: Any,
        *,
        query_progress: Callable[[NativeShortMapScopeKey, str, int, int], None] | None = None,
    ) -> None:
        self._conn = conn
        self._query_progress = query_progress
        self._bundles: dict[NativeShortMapScopeKey, CandleBundle] = {}
        self.rows_read = 0

    def bundle(self, key: NativeShortMapScopeKey, as_of_utc: datetime) -> CandleBundle:
        if key not in self._bundles:
            primary_started = time.monotonic()
            primary = _fetch_candles(
                self._conn,
                key=key,
                interval_code=key.primary_interval,
                since_utc=as_of_utc - PRIMARY_LOOKBACK,
                as_of_utc=as_of_utc,
            )
            if self._query_progress is not None:
                self._query_progress(
                    key,
                    key.primary_interval,
                    len(primary),
                    _elapsed_ms(primary_started),
                )
            supporting_started = time.monotonic()
            supporting = _fetch_candles(
                self._conn,
                key=key,
                interval_code=key.supporting_interval,
                since_utc=as_of_utc - SUPPORTING_LOOKBACK,
                as_of_utc=as_of_utc,
            )
            if self._query_progress is not None:
                self._query_progress(
                    key,
                    key.supporting_interval,
                    len(supporting),
                    _elapsed_ms(supporting_started),
                )
            self._bundles[key] = CandleBundle(primary=primary, supporting=supporting)
            self.rows_read += len(primary) + len(supporting)
        return self._bundles[key]

    def context_row(
        self,
        key: NativeShortMapScopeKey,
        as_of_utc: datetime,
    ) -> NativeShortContextRow:
        bundle = self.bundle(key, as_of_utc)
        row = build_native_short_context_row(
            symbol=key.symbol,
            venue=key.venue,
            primary_candles=list(bundle.primary),
            support_candles=list(bundle.supporting),
            now_utc=as_of_utc,
        )
        if not bundle.primary and not bundle.supporting:
            row = dataclasses.replace(row, context_status=STATUS_SYMBOL_MISSING)
        return row

    def primary_timestamps(
        self,
        key: NativeShortMapScopeKey,
        as_of_utc: datetime,
    ) -> list[datetime]:
        return [candle.close_ts_utc for candle in self.bundle(key, as_of_utc).primary]

    def supporting_timestamps(
        self,
        key: NativeShortMapScopeKey,
        as_of_utc: datetime,
    ) -> list[datetime]:
        return [candle.close_ts_utc for candle in self.bundle(key, as_of_utc).supporting]


def _elapsed_ms(start_monotonic: float) -> int:
    return max(0, round((time.monotonic() - start_monotonic) * 1000))


class _HeartbeatEmitter:
    """Background periodic progress reporter for one long-running phase.

    A single scope evaluation is itself an uninterruptible blocking call, so
    heartbeat progress is emitted from a daemon thread on a fixed interval
    rather than only from loop iterations (per-scope SCOPE_RESULT events
    already provide the loop-iteration granularity). Tests exercise the
    callback directly rather than waiting on real elapsed time.
    """

    def __init__(self, *, interval_seconds: float, callback: Callable[[], None]) -> None:
        self._interval_seconds = interval_seconds
        self._callback = callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            self._callback()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)


def execute_runtime(
    *,
    venue: str,
    symbols: Sequence[str],
    quote_currency: str,
    fib_trading_horizon: str,
    primary_interval: str,
    supporting_interval: str,
    as_of_utc: datetime,
    provenance: NativeShortWriterProvenance,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> RuntimeResult:
    # Independent mandatory authorization boundary immediately before the
    # bounded materialization/publication transaction. This guards direct calls
    # to execute_runtime as well as invocations routed through main().
    from src.operations.writer_capability_authorization_v1 import (
        require_capability_write_authorization,
    )

    writer_authorization = require_capability_write_authorization(
        "native_short_4h_chain",
        service="synth-chain-4h.service",
    )
    validate_native_short_writer_provenance(provenance)
    def _report(event: str, *, phase: str | None = None, **fields: Any) -> None:
        if progress is None:
            return
        payload: dict[str, Any] = {"event": event, "runner": RUNNER_NAME}
        if phase is not None:
            payload["phase"] = phase
        payload.update(fields)
        progress(payload)

    started = time.monotonic()
    conn = get_connection()

    # Exactly one transaction is ever open at a time; this flag lets the outer
    # BaseException handler roll back only a genuinely in-flight transaction
    # instead of blind-rolling-back an already-closed one.
    transaction_open = False

    def _begin() -> None:
        nonlocal transaction_open
        conn.begin()
        transaction_open = True

    def _commit() -> None:
        nonlocal transaction_open
        conn.commit()
        transaction_open = False

    def _rollback() -> None:
        nonlocal transaction_open
        conn.rollback()
        transaction_open = False

    run_id: int | None = None
    builder: NativeShortRunBuilder | None = None
    run_finalized = False
    failure: BaseException | None = None
    try:
        _begin()
        fetch_scopes_started = time.monotonic()
        _report("PHASE_START", phase="FETCH_SUPPORTED_SCOPES")
        scopes = fetch_supported_scope_keys(
            conn,
            venue=venue,
            quote_currency=quote_currency,
            fib_trading_horizon=fib_trading_horizon,
            primary_interval=primary_interval,
            supporting_interval=supporting_interval,
            symbols=symbols,
        )
        writer_commit_fences = capture_writer_commit_fences(conn, scopes)
        _report(
            "PHASE_END",
            phase="FETCH_SUPPORTED_SCOPES",
            phase_elapsed_ms=_elapsed_ms(fetch_scopes_started),
            elapsed_ms=_elapsed_ms(started),
            selected_scope_count=len(scopes),
        )
        # Scope selection and fence capture are the only work in the setup
        # transaction: no scope evaluation write shares a transaction with it.
        _commit()

        def _report_candle_query(
            key: NativeShortMapScopeKey,
            interval_code: str,
            rows_read: int,
            query_elapsed_ms: int,
        ) -> None:
            _report(
                "QUERY",
                phase="FETCH_CANDLES",
                scope=f"{key.venue}:{key.symbol}",
                interval=interval_code,
                rows_read=rows_read,
                query_elapsed_ms=query_elapsed_ms,
                elapsed_ms=_elapsed_ms(started),
            )

        market_data = RuntimeMarketData(conn, query_progress=_report_candle_query)

        # The run row is committed up front and owned by this process alone
        # (run_uuid == provenance.invocation_uuid is UNIQUE, so exactly one row
        # per invocation exists no matter how many scope transactions follow).
        builder = NativeShortRunBuilder(
            provenance=provenance,
            contract_version=CONTRACT_VERSION,
            started_at_utc=utc_now(),
            requested_scope_count=len(scopes),
        )
        _begin()
        run_id = _insert_run(conn, builder.started_record(), authorization=writer_authorization)
        _commit()

        orchestrator_started = time.monotonic()
        _report("PHASE_START", phase="ORCHESTRATOR_RUN", selected_scope_count=len(scopes))
        heartbeat: _HeartbeatEmitter | None = None
        if progress is not None:
            heartbeat = _HeartbeatEmitter(
                interval_seconds=HEARTBEAT_INTERVAL_SECONDS,
                callback=lambda: _report(
                    "HEARTBEAT",
                    phase="ORCHESTRATOR_RUN",
                    selected_scope_count=len(scopes),
                    candle_rows_read=market_data.rows_read,
                    phase_elapsed_ms=_elapsed_ms(orchestrator_started),
                    elapsed_ms=_elapsed_ms(started),
                ),
            )
            heartbeat.start()
        scope_results: list[ScopeChainResult] = []
        try:
            # One failure domain per exact canonical scope, evaluated in the
            # deterministic order fetch_supported_scope_keys already returns.
            # Each scope owns its own transaction, so an unexpected failure in
            # scope N can never roll back the committed work of scopes 1..N-1.
            for key in scopes:
                scope_started = time.monotonic()
                scope_label = f"{key.venue}:{key.symbol}"
                _begin()
                try:
                    outcome: ScopeChainOutcome = evaluate_and_project_scope(
                        conn,
                        key=key,
                        run_id=run_id,
                        as_of_utc=as_of_utc,
                        provenance=provenance,
                        operational_clock=utc_now,
                        fetch_context_row=market_data.context_row,
                        fetch_existing_maps=map_materializer._fetch_maps_for_scope,
                        fetch_existing_generation_events=(
                            map_materializer._fetch_generation_events_for_scope
                        ),
                        fetch_existing_lifecycle_events=(
                            map_materializer._fetch_lifecycle_events_for_map_ids
                        ),
                        fetch_primary_candle_close_timestamps=market_data.primary_timestamps,
                        fetch_supporting_candle_close_timestamps=market_data.supporting_timestamps,
                        authorization=writer_authorization,
                    )
                    revalidate_writer_commit_fences(
                        conn,
                        [fence for fence in writer_commit_fences if fence.key == key],
                    )
                    _commit()
                except NativeShortMapLevelStatusBlockedError as exc:
                    # Explicit, already-designed domain-blocked contract. Only
                    # this scope's transaction is discarded; every earlier
                    # scope is already committed and untouched. Blocked stays a
                    # hard stop for the run: no further scope is attempted.
                    _rollback()
                    builder.record_scope_outcome(failed=True)
                    scope_results.append(
                        ScopeChainResult(
                            key=key,
                            status=SCOPE_STATUS_BLOCKED,
                            detail=str(exc)[:MAX_FAILURE_DETAIL_LENGTH],
                        )
                    )
                    _report(
                        "SCOPE_RESULT",
                        phase="ORCHESTRATOR_RUN",
                        scope=scope_label,
                        status=SCOPE_STATUS_BLOCKED,
                        elapsed_ms=_elapsed_ms(scope_started),
                    )
                    break
                except Exception as exc:
                    # Unexpected (bug, DB error, chain integrity violation).
                    # Discard exactly this scope's writes and continue: one
                    # symbol's crash must not suppress unrelated scopes.
                    _rollback()
                    builder.record_scope_outcome(failed=True)
                    scope_results.append(
                        ScopeChainResult(
                            key=key,
                            status=SCOPE_STATUS_UNEXPECTED_FAILED,
                            detail=f"{type(exc).__name__}: {exc}"[:MAX_FAILURE_DETAIL_LENGTH],
                        )
                    )
                    _report(
                        "SCOPE_RESULT",
                        phase="ORCHESTRATOR_RUN",
                        scope=scope_label,
                        status=SCOPE_STATUS_UNEXPECTED_FAILED,
                        elapsed_ms=_elapsed_ms(scope_started),
                    )
                    continue
                except BaseException:
                    # SIGINT/SIGTERM-triggered KeyboardInterrupt: discard the
                    # in-flight scope and abort the loop entirely rather than
                    # continuing to further scopes.
                    _rollback()
                    raise

                if not outcome.skipped_not_supported:
                    builder.record_scope_outcome(
                        published_map=outcome.published_map,
                        lifecycle_event_appended=outcome.lifecycle_event_appended,
                        failed=outcome.failed,
                    )
                if outcome.skipped_not_supported:
                    scope_status = SCOPE_STATUS_SKIPPED_NOT_SUPPORTED
                elif outcome.bootstrap_pending:
                    # Expected first-map bootstrap state: committed above like
                    # any other success, recorded as its own attributable
                    # status rather than misreported as normal success, and
                    # deliberately not a failure -- the loop continues to the
                    # next scope.
                    scope_status = SCOPE_STATUS_BOOTSTRAP_PENDING
                else:
                    scope_status = SCOPE_STATUS_SUCCEEDED
                scope_results.append(ScopeChainResult(key=key, status=scope_status))
                _report(
                    "SCOPE_RESULT",
                    phase="ORCHESTRATOR_RUN",
                    scope=scope_label,
                    status=scope_status,
                    elapsed_ms=_elapsed_ms(scope_started),
                )
        finally:
            if heartbeat is not None:
                heartbeat.stop()

        run = _finalize_chain_run(
            conn,
            run_id=run_id,
            builder=builder,
            scope_results=scope_results,
            finished_at_utc=utc_now(),
            authorization=writer_authorization,
            begin=_begin,
            commit=_commit,
        )
        run_finalized = True

        _report(
            "PHASE_END",
            phase="ORCHESTRATOR_RUN",
            phase_elapsed_ms=_elapsed_ms(orchestrator_started),
            elapsed_ms=_elapsed_ms(started),
            observed_scopes=run.observed_scope_count,
            published_maps=run.published_map_count,
            lifecycle_events=run.lifecycle_event_count,
            failed_scopes=run.failed_scope_count,
            candle_rows_read=market_data.rows_read,
        )
        if run.failed_scope_count:
            failure = RuntimeScopeEvaluationError(
                f"FAILED_SCOPES count={run.failed_scope_count} run_uuid={run.run_uuid}"
            )
        result = RuntimeResult(
            run=run,
            selected_scope_count=len(scopes),
            candle_rows_read=market_data.rows_read,
            elapsed_ms=_elapsed_ms(started),
            scope_results=tuple(scope_results),
        )
    except BaseException:
        # BaseException (not just Exception) so a SIGINT/SIGTERM-triggered
        # KeyboardInterrupt arriving mid-transaction also rolls back instead
        # of leaving an open transaction for conn.close() to handle
        # implicitly.
        if transaction_open:
            try:
                _rollback()
            except Exception:
                pass
        # The run row is now committed before any scope work, so an interrupted
        # run leaves attributable terminal evidence instead of no row at all.
        # Strictly best effort: a failure here must never mask the original
        # interruption/exception.
        if run_id is not None and builder is not None and not run_finalized:
            try:
                interrupted_record = builder.finish(
                    finished_at_utc=utc_now(),
                    terminal_status=NativeShortRunTerminalStatus.INTERRUPTED,
                )
                _begin()
                _finalize_run(conn, run_id, interrupted_record, authorization=writer_authorization)
                _commit()
            except BaseException:
                try:
                    if transaction_open:
                        _rollback()
                except Exception:
                    pass
        raise
    finally:
        conn.close()

    if failure is not None:
        raise failure
    return result


def _finalize_chain_run(
    conn: Any,
    *,
    run_id: int,
    builder: NativeShortRunBuilder,
    scope_results: Sequence[ScopeChainResult],
    finished_at_utc: datetime,
    authorization: Any,
    begin: Callable[[], None],
    commit: Callable[[], None],
) -> NativeShortMaterializerRunRecord:
    """Terminalize the run row in its own short transaction.

    Not defensive by design: a terminalization conflict means a second
    finalizer genuinely raced this one, which must fail loud rather than be
    silently swallowed.
    """
    blocked = [item for item in scope_results if item.status == SCOPE_STATUS_BLOCKED]
    unexpected = [
        item for item in scope_results if item.status == SCOPE_STATUS_UNEXPECTED_FAILED
    ]
    if blocked:
        # Preserve the pre-existing blocked failure shape exactly.
        record = builder.finish(
            finished_at_utc=finished_at_utc,
            terminal_status=NativeShortRunTerminalStatus.FAILED,
            failure_reason_code=NativeShortMapLevelStatusBlockedError.__name__,
            failure_detail=(blocked[0].detail or "")[:MAX_FAILURE_DETAIL_LENGTH],
        )
    elif unexpected:
        detail = "; ".join(
            f"{item.key.venue}:{item.key.symbol} {item.detail}" for item in unexpected
        )
        record = builder.finish(
            finished_at_utc=finished_at_utc,
            terminal_status=NativeShortRunTerminalStatus.FAILED,
            failure_reason_code=UNEXPECTED_FAILURE_REASON_CODE,
            failure_detail=detail[:MAX_FAILURE_DETAIL_LENGTH],
        )
    else:
        # Per-scope soft-degrade evidence (already persisted as observations)
        # still terminalizes FINISHED, exactly as before.
        record = builder.finish(finished_at_utc=finished_at_utc)
    begin()
    _finalize_run(conn, run_id, record, authorization=authorization)
    commit()
    return record


def _emit(payload: dict[str, Any], output: str) -> None:
    if output == "jsonl":
        print(json.dumps(payload, sort_keys=True, default=str), flush=True)
        return
    print(" ".join(f"{key}={value}" for key, value in payload.items()), flush=True)


def _handle_sigterm(signum: int, frame: Any) -> None:
    # SIGTERM has no default Python exception; converting it into the same
    # KeyboardInterrupt path SIGINT already uses gives the runner one clean,
    # already-tested interruption/rollback path for both signals.
    raise KeyboardInterrupt("SIGTERM")


def _install_sigterm_handler() -> Any:
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handle_sigterm)
    return previous


def _restore_sigterm_handler(previous: Any) -> None:
    signal.signal(signal.SIGTERM, previous)


def _interruption_signal_name(exc: BaseException) -> str:
    return str(exc) or "SIGINT"


def main(
    argv: Sequence[str] | None = None,
    *,
    inspect_repository_source: NativeShortRepositorySourceInspector = (
        inspect_running_repository_source
    ),
) -> int:
    args = parse_args(argv)

    # Mandatory authorization boundary: the native SHORT 4h chain owns public
    # market-state materialization/publication. A direct Python invocation must
    # not bypass ownership authorization. Wrapper guards are defense in depth.
    from src.operations.writer_capability_authorization_v1 import (
        require_capability_write_authorization,
    )

    allowed_untracked = {args.allowed_untracked_path} if args.allowed_untracked_path else None
    require_capability_write_authorization(
        "native_short_4h_chain",
        service="synth-chain-4h.service",
        allowed_untracked_paths=allowed_untracked,
    )

    try:
        provenance = build_verified_process_provenance(
            writer_entrypoint=args.writer_entrypoint,
            runner_name=RUNNER_NAME,
            runner_version=RUNNER_VERSION,
            execution_mode=args.execution_mode,
            repository_commit_sha=args.repository_commit,
            trigger_type=args.trigger_type,
            trigger_ref=args.trigger_ref,
            allowed_untracked_path=args.allowed_untracked_path,
            inspect_repository_source=inspect_repository_source,
        )
    except NativeShortWriterProvenanceError as exc:
        print(f"INVALID_PROVENANCE runner={RUNNER_NAME} detail={exc}", file=sys.stderr, flush=True)
        return 2
    symbols = parse_symbols(args.symbols)
    as_of_utc = args.as_of_utc or utc_now()
    scope_mode = "EXPLICIT_SYMBOLS" if symbols else "PERSISTED_SUPPORTED_SCOPES"
    started_payload: dict[str, Any] = {
        "event": "STARTED",
        "runner": RUNNER_NAME,
        "version": RUNNER_VERSION,
        "mode": RUNTIME_MODE,
        "worker_count": WORKER_COUNT,
        "scope_mode": scope_mode,
        "venue": args.venue,
        "symbols": ",".join(symbols) if symbols else "SUPPORTED",
        "quote_currency": args.quote_currency,
        "fib_trading_horizon": args.fib_trading_horizon,
        "primary_interval": args.primary_interval,
        "supporting_interval": args.supporting_interval,
        "as_of_utc": as_of_utc.isoformat(),
        **SAFETY_MARKERS,
    }
    _emit(started_payload, args.output)
    started = time.monotonic()
    previous_sigterm_handler = _install_sigterm_handler()
    try:
        try:
            result = execute_runtime(
                venue=args.venue,
                symbols=symbols,
                quote_currency=args.quote_currency,
                fib_trading_horizon=args.fib_trading_horizon,
                primary_interval=args.primary_interval,
                supporting_interval=args.supporting_interval,
                as_of_utc=as_of_utc,
                provenance=provenance,
                progress=lambda payload: _emit(payload, args.output),
            )
        except KeyboardInterrupt as exc:
            interruption_signal = _interruption_signal_name(exc)
            exit_status = 143 if interruption_signal == "SIGTERM" else 130
            _emit(
                {
                    "event": "INTERRUPTED",
                    "runner": RUNNER_NAME,
                    "signal": interruption_signal,
                    "exit_status": exit_status,
                    "elapsed_ms": _elapsed_ms(started),
                    **SAFETY_MARKERS,
                },
                args.output,
            )
            return exit_status
        except Exception as exc:
            _emit(
                {
                    "event": "FAILED",
                    "runner": RUNNER_NAME,
                    "exit_status": 1,
                    "reason_code": type(exc).__name__,
                    "detail": str(exc)[:500],
                    "elapsed_ms": _elapsed_ms(started),
                    **SAFETY_MARKERS,
                },
                args.output,
            )
            return 1

        _emit(
            {
                "event": "FINISHED",
                "runner": RUNNER_NAME,
                "exit_status": 0,
                "run_uuid": result.run.run_uuid,
                "selected_scopes": result.selected_scope_count,
                "observed_scopes": result.run.observed_scope_count,
                "published_maps": result.run.published_map_count,
                "lifecycle_events": result.run.lifecycle_event_count,
                "failed_scopes": result.run.failed_scope_count,
                "map_level_status_rows": result.map_level_status_row_count,
                "candle_rows_read": result.candle_rows_read,
                "elapsed_ms": result.elapsed_ms,
                **SAFETY_MARKERS,
            },
            args.output,
        )
        return 0
    finally:
        _restore_sigterm_handler(previous_sigterm_handler)


if __name__ == "__main__":
    raise SystemExit(main())
