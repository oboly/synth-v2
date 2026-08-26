"""Canonical DB-read-only evidence wrapper for bullish Breathline tracker v1.

Frozen scope for Issue #534:
- source: synth.obs_market_candle
- venue: bitvavo
- symbols: RENDER, TAO
- input interval: 4h
- tracker timestamp: canonical open_ts_utc serialized as CSV column ``ts``

The existing #417 tracker is imported and invoked unchanged. This module performs
SELECT-only source extraction, deterministic source serialization, provenance
binding, and research-artifact output only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from pymysql.cursors import SSDictCursor

from src.common.db import get_connection
from src.research.bullish_breathline_tracker_v1 import MODEL_VERSION as TRACKER_MODEL_VERSION
from src.research.run_bullish_breathline_tracker_v1 import run as run_tracker


RUNNER_NAME = "bullish_breathline_canonical_4h_v1"
RUNNER_VERSION = "1.0.0"
SOURCE_TABLE = "obs_market_candle"
VENUE = "bitvavo"
INTERVAL_CODE = "4h"
SYMBOLS = ("RENDER", "TAO")
EXPECTED_INTERVAL_SECONDS = 4 * 60 * 60
FETCH_BATCH_ROWS = 1000
DEFAULT_HEARTBEAT_SECONDS = 5.0
DEFAULT_OUT_ROOT = Path("data/research/bullish_breathline_canonical_4h_v1")
SOURCE_CHECKPOINT_FILENAME = "source_checkpoint.json"
RUN_MANIFEST_FILENAME = "run_manifest.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

TRACKER_SOURCE_FILES = (
    "src/research/bullish_breathline_tracker_v1.py",
    "src/research/run_bullish_breathline_tracker_v1.py",
)

SAFETY_MARKERS: dict[str, Any] = {
    "research_only": True,
    "market_only": True,
    "account_awareness": 0,
    "selection_engine_changes": 0,
    "decision_gate_changes": 0,
    "execution_planner_changes": 0,
    "executor_changes": 0,
    "broker_calls": 0,
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "live_trading_permission": 0,
    "db_writes": 0,
    "production_db_writes": 0,
    "production_schema_changes": 0,
    "runtime_activation": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}


@dataclass(frozen=True)
class AssetIdentity:
    asset_id: int
    symbol: str


@dataclass(frozen=True)
class GapRecord:
    previous_open_ts_utc: str
    current_open_ts_utc: str
    delta_seconds: float
    expected_seconds: int
    inferred_missing_candles: int | None


@dataclass(frozen=True)
class SourceExportResult:
    asset_id: int
    symbol: str
    source_csv: str
    source_row_count: int
    first_source_ts: str
    last_source_ts: str
    source_gap_count: int
    inferred_missing_candle_count: int
    gaps: tuple[GapRecord, ...]
    source_sha256: str


@dataclass
class RunControl:
    interrupted: bool = False
    interrupt_signal: str | None = None

    def request_interrupt(self, signal_name: str) -> None:
        if not self.interrupted:
            self.interrupted = True
            self.interrupt_signal = signal_name


class RunnerInterrupted(RuntimeError):
    """Internal clean-interruption sentinel; never rendered as a traceback by main()."""


def emit(status: str, message: str, **fields: Any) -> None:
    suffix = " ".join(f"{key}={fields[key]}" for key in sorted(fields))
    if suffix:
        print(f"{status} {message} {suffix}", flush=True)
    else:
        print(f"{status} {message}", flush=True)


@contextmanager
def phase(name: str, **fields: Any) -> Iterator[None]:
    started_at = time.monotonic()
    emit("PHASE_STARTED", name, **fields)
    try:
        yield
    finally:
        emit(
            "PHASE_FINISHED",
            name,
            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
            **fields,
        )


@contextmanager
def periodic_heartbeat(
    message: str,
    *,
    interval_seconds: float,
    **fields: Any,
) -> Iterator[None]:
    """Emit flushed heartbeats while a phase has no native progress callback."""
    interval = max(float(interval_seconds), 0.01)
    started_at = time.monotonic()
    stop_event = threading.Event()

    def _worker() -> None:
        while not stop_event.wait(interval):
            emit(
                "HEARTBEAT",
                message,
                elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
                **fields,
            )

    thread = threading.Thread(target=_worker, name=f"{RUNNER_NAME}-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=max(interval * 2.0, 0.1))


@contextmanager
def installed_signal_handlers(control: RunControl) -> Iterator[None]:
    previous = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }

    def _handle(signum: int, _frame: Any) -> None:
        signal_name = signal.Signals(signum).name
        control.request_interrupt(signal_name)
        emit("INTERRUPT_REQUESTED", RUNNER_NAME, signal=signal_name)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def utc_now() -> datetime:
    return datetime.now(UTC)


def default_run_id(now: datetime | None = None) -> str:
    value = (now or utc_now()).astimezone(UTC)
    return value.strftime("%Y%m%dT%H%M%SZ")


def validate_run_id(run_id: str) -> str:
    value = str(run_id).strip()
    if not value or not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError("run_id must match [A-Za-z0-9._-]+")
    return value


def normalize_utc(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def fmt_ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def as_decimal(value: Any, *, field_name: str, allow_zero: bool = False) -> Decimal:
    if value is None:
        raise ValueError(f"missing required candle field: {field_name}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal candle field: {field_name}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite candle field: {field_name}")
    if allow_zero:
        if result < 0:
            raise ValueError(f"negative candle field: {field_name}")
    elif result <= 0:
        raise ValueError(f"non-positive candle field: {field_name}")
    return result


def serialize_decimal(value: Decimal) -> str:
    return format(value, "f")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_output(args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    value = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or not value:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return value


def resolve_analysis_commit(root: Path) -> str:
    return git_output(["rev-parse", "HEAD"], cwd=root)


def resolve_tracker_source_commit(root: Path) -> str:
    return git_output(
        ["log", "-1", "--format=%H", "--", *TRACKER_SOURCE_FILES],
        cwd=root,
    )


def tracker_source_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative_path in TRACKER_SOURCE_FILES:
        path = root / relative_path
        if not path.is_file():
            raise RuntimeError(f"tracker source file missing: {relative_path}")
        hashes[relative_path] = sha256_file(path)
    return hashes


def begin_read_only_transaction(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("START TRANSACTION READ ONLY")


def resolve_asset_identity(conn: Any, symbol: str) -> AssetIdentity:
    requested = str(symbol).strip().upper()
    if requested not in SYMBOLS:
        raise ValueError(f"symbol outside frozen #534 scope: {requested}")
    started_at = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT asset_id, symbol
            FROM asset
            WHERE UPPER(symbol) = %s
            ORDER BY asset_id
            """,
            (requested,),
        )
        rows = cur.fetchall()
    emit(
        "QUERY_FINISHED",
        "resolve_asset_identity",
        symbol=requested,
        row_count=len(rows),
        elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
    )
    if len(rows) != 1:
        raise RuntimeError(
            f"expected exactly one canonical asset identity for {requested}, found {len(rows)}"
        )
    row = rows[0]
    canonical_symbol = str(row.get("symbol") or "").strip().upper()
    if canonical_symbol != requested:
        raise RuntimeError(
            f"canonical symbol mismatch requested={requested} observed={canonical_symbol or 'EMPTY'}"
        )
    return AssetIdentity(asset_id=int(row["asset_id"]), symbol=canonical_symbol)


def validate_scope_row(row: dict[str, Any], identity: AssetIdentity) -> None:
    asset_id_raw = row.get("asset_id")
    if asset_id_raw is None:
        raise ValueError("missing required candle field: asset_id")
    observed_asset_id = int(asset_id_raw)
    observed_venue = str(row.get("venue") or "").strip()
    observed_interval = str(row.get("interval_code") or "").strip()
    if observed_asset_id != identity.asset_id:
        raise ValueError(
            f"unexpected asset_id in source row expected={identity.asset_id} observed={observed_asset_id}"
        )
    if observed_venue != VENUE:
        raise ValueError(f"unexpected venue in source row: {observed_venue or 'EMPTY'}")
    if observed_interval != INTERVAL_CODE:
        raise ValueError(f"unexpected interval_code in source row: {observed_interval or 'EMPTY'}")


def validate_ohlc(row: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal | None]:
    open_value = as_decimal(row.get("open_price"), field_name="open_price")
    high_value = as_decimal(row.get("high_price"), field_name="high_price")
    low_value = as_decimal(row.get("low_price"), field_name="low_price")
    close_value = as_decimal(row.get("close_price"), field_name="close_price")
    if high_value < max(open_value, low_value, close_value):
        raise ValueError("invalid OHLC: high_price below candle value")
    if low_value > min(open_value, high_value, close_value):
        raise ValueError("invalid OHLC: low_price above candle value")

    volume_raw = row.get("volume_base")
    volume = None
    if volume_raw is not None:
        volume = as_decimal(volume_raw, field_name="volume_base", allow_zero=True)
    return open_value, high_value, low_value, close_value, volume


def gap_record(previous_ts: datetime, current_ts: datetime) -> GapRecord | None:
    delta_seconds = (current_ts - previous_ts).total_seconds()
    if delta_seconds == EXPECTED_INTERVAL_SECONDS:
        return None
    inferred_missing: int | None = None
    if (
        delta_seconds > EXPECTED_INTERVAL_SECONDS
        and delta_seconds.is_integer()
        and int(delta_seconds) % EXPECTED_INTERVAL_SECONDS == 0
    ):
        inferred_missing = int(delta_seconds) // EXPECTED_INTERVAL_SECONDS - 1
    return GapRecord(
        previous_open_ts_utc=fmt_ts(previous_ts),
        current_open_ts_utc=fmt_ts(current_ts),
        delta_seconds=delta_seconds,
        expected_seconds=EXPECTED_INTERVAL_SECONDS,
        inferred_missing_candles=inferred_missing,
    )


def export_source_candles(
    conn: Any,
    *,
    identity: AssetIdentity,
    csv_path: Path,
    control: RunControl | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
) -> SourceExportResult:
    """Stream one frozen-scope source history to deterministic tracker CSV."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    sql = """
        SELECT
            asset_id,
            venue,
            interval_code,
            open_ts_utc,
            close_ts_utc,
            open_price,
            high_price,
            low_price,
            close_price,
            volume_base
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
        ORDER BY open_ts_utc ASC
    """

    row_count = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    previous_ts: datetime | None = None
    gaps: list[GapRecord] = []
    started_at = time.monotonic()
    next_heartbeat_at = started_at + max(float(heartbeat_seconds), 0.01)

    try:
        with conn.cursor(SSDictCursor) as cur, csv_path.open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            cur.execute(sql, (identity.asset_id, VENUE, INTERVAL_CODE))
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("ts", "open", "high", "low", "close", "volume"))

            while True:
                if control is not None and control.interrupted:
                    raise RunnerInterrupted(control.interrupt_signal or "INTERRUPTED")
                rows = cur.fetchmany(FETCH_BATCH_ROWS)
                if not rows:
                    break
                for row in rows:
                    validate_scope_row(row, identity)
                    open_ts = normalize_utc(row.get("open_ts_utc"), field_name="open_ts_utc")
                    close_ts = normalize_utc(row.get("close_ts_utc"), field_name="close_ts_utc")
                    if close_ts - open_ts != timedelta(seconds=EXPECTED_INTERVAL_SECONDS):
                        raise ValueError(
                            "invalid canonical candle span: close_ts_utc must equal open_ts_utc + 4h"
                        )

                    if previous_ts is not None:
                        if open_ts == previous_ts:
                            raise ValueError(f"duplicate candle timestamp: {fmt_ts(open_ts)}")
                        if open_ts < previous_ts:
                            raise ValueError(
                                f"non-monotonic candle timestamp: previous={fmt_ts(previous_ts)} current={fmt_ts(open_ts)}"
                            )
                        observed_gap = gap_record(previous_ts, open_ts)
                        if observed_gap is not None:
                            gaps.append(observed_gap)

                    open_value, high_value, low_value, close_value, volume = validate_ohlc(row)
                    writer.writerow(
                        (
                            fmt_ts(open_ts),
                            serialize_decimal(open_value),
                            serialize_decimal(high_value),
                            serialize_decimal(low_value),
                            serialize_decimal(close_value),
                            "" if volume is None else serialize_decimal(volume),
                        )
                    )
                    row_count += 1
                    first_ts = first_ts or open_ts
                    last_ts = open_ts
                    previous_ts = open_ts

                now = time.monotonic()
                if now >= next_heartbeat_at:
                    emit(
                        "HEARTBEAT",
                        "source_export",
                        symbol=identity.symbol,
                        row_count=row_count,
                        elapsed_seconds=f"{now - started_at:.2f}",
                    )
                    next_heartbeat_at = now + max(float(heartbeat_seconds), 0.01)
    except RunnerInterrupted:
        csv_path.unlink(missing_ok=True)
        emit(
            "QUERY_INTERRUPTED",
            "source_export",
            symbol=identity.symbol,
            row_count=row_count,
            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
        )
        raise
    except Exception:
        csv_path.unlink(missing_ok=True)
        emit(
            "QUERY_FAILED",
            "source_export",
            symbol=identity.symbol,
            row_count=row_count,
            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
        )
        raise

    emit(
        "QUERY_FINISHED",
        "source_export",
        symbol=identity.symbol,
        row_count=row_count,
        elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
    )
    if row_count == 0 or first_ts is None or last_ts is None:
        csv_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"empty canonical history for symbol={identity.symbol} venue={VENUE} interval={INTERVAL_CODE}"
        )

    result = SourceExportResult(
        asset_id=identity.asset_id,
        symbol=identity.symbol,
        source_csv=str(csv_path),
        source_row_count=row_count,
        first_source_ts=fmt_ts(first_ts),
        last_source_ts=fmt_ts(last_ts),
        source_gap_count=len(gaps),
        inferred_missing_candle_count=sum(
            gap.inferred_missing_candles or 0 for gap in gaps
        ),
        gaps=tuple(gaps),
        source_sha256=sha256_file(csv_path),
    )
    emit(
        "CHECKPOINT",
        "source_csv",
        symbol=identity.symbol,
        row_count=result.source_row_count,
        gap_count=result.source_gap_count,
        sha256=result.source_sha256,
        path=result.source_csv,
    )
    return result


def source_result_payload(source: SourceExportResult) -> dict[str, Any]:
    payload = asdict(source)
    payload["gaps"] = [asdict(gap) for gap in source.gaps]
    return payload


def source_result_from_payload(payload: dict[str, Any], *, expected_csv: Path) -> SourceExportResult:
    gaps = tuple(GapRecord(**dict(item)) for item in payload.get("gaps") or [])
    return SourceExportResult(
        asset_id=int(payload["asset_id"]),
        symbol=str(payload["symbol"]),
        source_csv=str(expected_csv),
        source_row_count=int(payload["source_row_count"]),
        first_source_ts=str(payload["first_source_ts"]),
        last_source_ts=str(payload["last_source_ts"]),
        source_gap_count=int(payload["source_gap_count"]),
        inferred_missing_candle_count=int(payload["inferred_missing_candle_count"]),
        gaps=gaps,
        source_sha256=str(payload["source_sha256"]),
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_source_checkpoint(
    run_dir: Path,
    *,
    run_id: str,
    analysis_commit_sha: str,
    tracker_source_commit_sha: str,
    tracker_source_sha256: dict[str, str],
    source_by_symbol: dict[str, SourceExportResult],
) -> Path:
    checkpoint_path = run_dir / SOURCE_CHECKPOINT_FILENAME
    payload = {
        "runner_name": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "checkpoint": "source_complete",
        "checkpoint_ts_utc": fmt_ts(utc_now()),
        "run_id": run_id,
        "source_table": SOURCE_TABLE,
        "venue": VENUE,
        "symbols": list(SYMBOLS),
        "interval_code": INTERVAL_CODE,
        "analysis_commit_sha": analysis_commit_sha,
        "tracker_source_commit_sha": tracker_source_commit_sha,
        "tracker_source_sha256": tracker_source_sha256,
        "assets": [source_result_payload(source_by_symbol[symbol]) for symbol in SYMBOLS],
    }
    write_json(checkpoint_path, payload)
    emit(
        "CHECKPOINT",
        "source_phase",
        path=str(checkpoint_path),
        sha256=sha256_file(checkpoint_path),
        asset_count=len(SYMBOLS),
    )
    return checkpoint_path


def load_source_checkpoint(
    run_dir: Path,
    *,
    run_id: str,
    analysis_commit_sha: str,
    tracker_source_commit_sha: str,
    tracker_source_sha256: dict[str, str],
) -> tuple[list[AssetIdentity], dict[str, SourceExportResult], Path]:
    checkpoint_path = run_dir / SOURCE_CHECKPOINT_FILENAME
    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"source checkpoint missing: {checkpoint_path}")
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    expected = {
        "runner_name": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "checkpoint": "source_complete",
        "run_id": run_id,
        "source_table": SOURCE_TABLE,
        "venue": VENUE,
        "symbols": list(SYMBOLS),
        "interval_code": INTERVAL_CODE,
        "analysis_commit_sha": analysis_commit_sha,
        "tracker_source_commit_sha": tracker_source_commit_sha,
        "tracker_source_sha256": tracker_source_sha256,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(f"source checkpoint provenance mismatch: {key}")

    rows = payload.get("assets")
    if not isinstance(rows, list) or len(rows) != len(SYMBOLS):
        raise RuntimeError("source checkpoint asset set is invalid")
    row_by_symbol = {str(row.get("symbol") or "").upper(): row for row in rows if isinstance(row, dict)}
    if set(row_by_symbol) != set(SYMBOLS):
        raise RuntimeError("source checkpoint symbols do not match frozen #534 scope")

    identities: list[AssetIdentity] = []
    source_by_symbol: dict[str, SourceExportResult] = {}
    for symbol in SYMBOLS:
        expected_csv = run_dir / symbol / "source" / "canonical_candles.csv"
        source = source_result_from_payload(row_by_symbol[symbol], expected_csv=expected_csv)
        if source.symbol != symbol:
            raise RuntimeError(f"source checkpoint symbol mismatch: {symbol}")
        if not expected_csv.is_file():
            raise RuntimeError(f"checkpoint source artifact missing: {expected_csv}")
        observed_hash = sha256_file(expected_csv)
        if observed_hash != source.source_sha256:
            raise RuntimeError(f"checkpoint source artifact hash mismatch: {symbol}")
        identities.append(AssetIdentity(asset_id=source.asset_id, symbol=symbol))
        source_by_symbol[symbol] = source

    emit(
        "CHECKPOINT_LOADED",
        "source_phase",
        path=str(checkpoint_path),
        sha256=sha256_file(checkpoint_path),
        asset_count=len(identities),
    )
    return identities, source_by_symbol, checkpoint_path


def collect_tracker_artifacts(
    tracker_dir: Path,
    *,
    cycle_count: int,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for filename in ("latest_cycles.json", "summary.json"):
        path = tracker_dir / filename
        if not path.is_file():
            raise RuntimeError(f"expected tracker artifact missing: {path}")
        result[filename] = {
            "path": str(path),
            "present": True,
            "sha256": sha256_file(path),
        }

    ledger_path = tracker_dir / "cycle_ledger.jsonl"
    if ledger_path.is_file():
        result["cycle_ledger.jsonl"] = {
            "path": str(ledger_path),
            "present": True,
            "sha256": sha256_file(ledger_path),
        }
    elif cycle_count == 0:
        result["cycle_ledger.jsonl"] = {
            "path": str(ledger_path),
            "present": False,
            "sha256": None,
            "reason": "existing #417 append_cycle_ledger emits no file when cycle_count=0",
        }
    else:
        raise RuntimeError(f"expected tracker artifact missing: {ledger_path}")
    return result


def prepare_tracker_output_dir(tracker_dir: Path) -> None:
    """Discard derived tracker output before deterministic recomputation."""
    if tracker_dir.exists():
        shutil.rmtree(tracker_dir)
        emit("INFO", "reset_tracker_output", path=str(tracker_dir))


def run(
    *,
    out_root: Path,
    run_id: str,
    cli_args: list[str],
    resume: bool = False,
    control: RunControl | None = None,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
) -> dict[str, Any]:
    frozen_run_id = validate_run_id(run_id)
    run_dir = out_root / frozen_run_id
    control = control or RunControl()

    root = repo_root()
    analysis_commit_sha = resolve_analysis_commit(root)
    tracker_source_commit_sha = resolve_tracker_source_commit(root)
    source_hashes = tracker_source_hashes(root)
    run_ts = utc_now()

    if (run_dir / RUN_MANIFEST_FILENAME).exists():
        raise FileExistsError(f"completed immutable run already exists: {run_dir}")
    if run_dir.exists() and not resume:
        raise FileExistsError(f"run directory already exists; use --resume or a new run id: {run_dir}")

    resumed_from_source_checkpoint = False
    checkpoint_path: Path | None = None
    identities: list[AssetIdentity]
    source_by_symbol: dict[str, SourceExportResult]

    if run_dir.exists() and resume and (run_dir / SOURCE_CHECKPOINT_FILENAME).is_file():
        with phase("load_source_checkpoint", run_id=frozen_run_id):
            identities, source_by_symbol, checkpoint_path = load_source_checkpoint(
                run_dir,
                run_id=frozen_run_id,
                analysis_commit_sha=analysis_commit_sha,
                tracker_source_commit_sha=tracker_source_commit_sha,
                tracker_source_sha256=source_hashes,
            )
        resumed_from_source_checkpoint = True
    else:
        if run_dir.exists() and resume:
            emit("INFO", "restart_incomplete_source_phase", run_id=frozen_run_id, path=str(run_dir))
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=False)
        conn: Any | None = get_connection()
        try:
            with phase("source_snapshot", venue=VENUE, interval=INTERVAL_CODE, asset_count=len(SYMBOLS)):
                begin_read_only_transaction(conn)
                identities = [resolve_asset_identity(conn, symbol) for symbol in SYMBOLS]
                source_by_symbol = {}
                for identity in identities:
                    if control.interrupted:
                        raise RunnerInterrupted(control.interrupt_signal or "INTERRUPTED")
                    with phase("source_export", symbol=identity.symbol):
                        source_csv = run_dir / identity.symbol / "source" / "canonical_candles.csv"
                        source_by_symbol[identity.symbol] = export_source_candles(
                            conn,
                            identity=identity,
                            csv_path=source_csv,
                            control=control,
                            heartbeat_seconds=heartbeat_seconds,
                        )
        except Exception:
            raise
        finally:
            if conn is not None:
                try:
                    conn.rollback()
                finally:
                    conn.close()
        if control.interrupted:
            raise RunnerInterrupted(control.interrupt_signal or "INTERRUPTED")
        checkpoint_path = write_source_checkpoint(
            run_dir,
            run_id=frozen_run_id,
            analysis_commit_sha=analysis_commit_sha,
            tracker_source_commit_sha=tracker_source_commit_sha,
            tracker_source_sha256=source_hashes,
            source_by_symbol=source_by_symbol,
        )

    assets_manifest: list[dict[str, Any]] = []
    try:
        for identity in identities:
            if control.interrupted:
                raise RunnerInterrupted(control.interrupt_signal or "INTERRUPTED")
            source = source_by_symbol[identity.symbol]
            source_csv = Path(source.source_csv)
            tracker_dir = run_dir / identity.symbol / "tracker"
            prepare_tracker_output_dir(tracker_dir)
            with phase("tracker", symbol=identity.symbol):
                with periodic_heartbeat(
                    "tracker",
                    interval_seconds=heartbeat_seconds,
                    symbol=identity.symbol,
                ):
                    tracker_summary = run_tracker(
                        csv_path=source_csv,
                        symbol=identity.symbol,
                        out_dir=tracker_dir,
                    )
            cycle_count = int(tracker_summary.get("cycle_count") or 0)
            tracker_artifacts = collect_tracker_artifacts(
                tracker_dir,
                cycle_count=cycle_count,
            )
            emit(
                "CHECKPOINT",
                "tracker_outputs",
                symbol=identity.symbol,
                cycle_count=cycle_count,
                output_dir=str(tracker_dir),
            )
            if control.interrupted:
                raise RunnerInterrupted(control.interrupt_signal or "INTERRUPTED")

            assets_manifest.append(
                {
                    **source_result_payload(source),
                    "venue": VENUE,
                    "interval_code": INTERVAL_CODE,
                    "source_table": SOURCE_TABLE,
                    "timestamp_semantics": (
                        "obs_market_candle.open_ts_utc serialized unchanged in meaning as tracker CSV column 'ts'"
                    ),
                    "volume_semantics": (
                        "obs_market_candle.volume_base serialized as tracker CSV column 'volume'; blank only when canonical source is NULL"
                    ),
                    "tracker_output_dir": str(tracker_dir),
                    "tracker_artifacts": tracker_artifacts,
                    "tracker_summary": tracker_summary,
                }
            )

        manifest: dict[str, Any] = {
            "runner_name": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "run_id": frozen_run_id,
            "run_ts_utc": fmt_ts(run_ts),
            "research_only": True,
            "market_only": True,
            "account_awareness": 0,
            "source_table": SOURCE_TABLE,
            "venue": VENUE,
            "symbols": list(SYMBOLS),
            "interval_code": INTERVAL_CODE,
            "input_interval_is_cycle_duration": False,
            "expected_interval_seconds": EXPECTED_INTERVAL_SECONDS,
            "fetch_batch_rows": FETCH_BATCH_ROWS,
            "db_transaction": "START TRANSACTION READ ONLY",
            "analysis_commit_sha": analysis_commit_sha,
            "tracker_source_commit_sha": tracker_source_commit_sha,
            "tracker_model_version": TRACKER_MODEL_VERSION,
            "tracker_source_sha256": source_hashes,
            "source_checkpoint_path": None if checkpoint_path is None else str(checkpoint_path),
            "source_checkpoint_sha256": None if checkpoint_path is None else sha256_file(checkpoint_path),
            "resumed_from_source_checkpoint": resumed_from_source_checkpoint,
            "cli": [
                sys.executable,
                "-m",
                "src.research.run_bullish_breathline_canonical_4h_v1",
                *cli_args,
            ],
            "assets": assets_manifest,
            "safety": dict(SAFETY_MARKERS),
        }
        manifest_path = run_dir / RUN_MANIFEST_FILENAME
        write_json(manifest_path, manifest)
        emit(
            "CHECKPOINT",
            "run_manifest",
            path=str(manifest_path),
            sha256=sha256_file(manifest_path),
            asset_count=len(assets_manifest),
        )
        return manifest
    except RunnerInterrupted:
        raise
    except Exception:
        # A complete source checkpoint is intentionally retained so a tracker-phase
        # failure can be inspected or safely retried with --resume on the same code.
        if checkpoint_path is None or not checkpoint_path.is_file():
            shutil.rmtree(run_dir, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="Root for immutable versioned #534 research runs",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Immutable run identifier. Defaults to current UTC timestamp.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from an intact source checkpoint for the same exact code provenance.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=DEFAULT_HEARTBEAT_SECONDS,
        help="Progress heartbeat interval for long extraction/tracker phases.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_args)
    frozen_run_id = validate_run_id(args.run_id or default_run_id())
    control = RunControl()
    started_at = time.monotonic()
    terminal_emitted = False

    def terminal(status: str, **fields: Any) -> None:
        nonlocal terminal_emitted
        if terminal_emitted:
            raise RuntimeError("terminal lifecycle status already emitted")
        terminal_emitted = True
        emit(
            status,
            RUNNER_NAME,
            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
            run_id=frozen_run_id,
            broker_private_calls=SAFETY_MARKERS["broker_private_calls"],
            broker_writes=SAFETY_MARKERS["broker_writes"],
            order_submission=SAFETY_MARKERS["order_submission"],
            live_orders=SAFETY_MARKERS["live_orders"],
            decision_gate=SAFETY_MARKERS["decision_gate"],
            execution_planner=SAFETY_MARKERS["execution_planner"],
            executor=SAFETY_MARKERS["executor"],
            **fields,
        )

    emit(
        "STARTED",
        RUNNER_NAME,
        mode="canonical_db_to_tracker",
        scope=f"{VENUE}:{INTERVAL_CODE}:{','.join(SYMBOLS)}",
        workers=1,
        run_id=frozen_run_id,
        resume=bool(args.resume),
    )

    try:
        with installed_signal_handlers(control):
            manifest = run(
                out_root=args.out_root,
                run_id=frozen_run_id,
                cli_args=raw_args,
                resume=bool(args.resume),
                control=control,
                heartbeat_seconds=max(float(args.heartbeat_seconds), 0.01),
            )
            if control.interrupted:
                raise RunnerInterrupted(control.interrupt_signal or "INTERRUPTED")
            for asset in manifest["assets"]:
                tracker_summary = asset["tracker_summary"]
                emit(
                    "INFO",
                    "asset_summary",
                    symbol=asset["symbol"],
                    source_rows=asset["source_row_count"],
                    gaps=asset["source_gap_count"],
                    cycles=tracker_summary.get("cycle_count", 0),
                )
            terminal(
                "FINISHED",
                asset_count=len(manifest["assets"]),
                output_dir=str(args.out_root / frozen_run_id),
            )
            return 0
    except RunnerInterrupted:
        terminal("INTERRUPTED", signal=control.interrupt_signal or "requested")
        return 130
    except KeyboardInterrupt:
        control.request_interrupt("SIGINT")
        terminal("INTERRUPTED", signal="SIGINT")
        return 130
    except Exception as exc:
        terminal("FAILED", error_type=type(exc).__name__, error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
