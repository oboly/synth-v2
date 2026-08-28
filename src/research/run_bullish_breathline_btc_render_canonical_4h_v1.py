"""Canonical DB-read-only BTC/RENDER evidence wrapper for Breathline Issue #418.

This runner produces independent #417 tracker ledgers for BTC and RENDER before
any cross-symbol relationship analysis is allowed.

It deliberately reuses the validated canonical 4h extraction primitives from
Issue #534 while owning its own frozen scope, checkpoint and provenance.

Research-only, market-only, account-agnostic. No relationship classification is
performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.breathline_btc_alt_relationship_registry_v1_0_0_frozen import (
    ALT_SYMBOL,
    REFERENCE_SYMBOL,
    REGISTRY_VERSION,
)
from src.research.bullish_breathline_tracker_v1 import MODEL_VERSION as TRACKER_MODEL_VERSION
from src.research.run_bullish_breathline_tracker_v1 import run as run_tracker
from src.research.run_bullish_breathline_canonical_4h_v1 import (
    DEFAULT_HEARTBEAT_SECONDS,
    FETCH_BATCH_ROWS,
    INTERVAL_CODE,
    SOURCE_TABLE,
    TRANSACTION_ISOLATION_SQL,
    TRANSACTION_START_SQL,
    VENUE,
    AssetIdentity,
    RunControl,
    RunnerInterrupted,
    SourceExportResult,
    begin_read_only_transaction,
    collect_tracker_artifacts,
    default_run_id,
    emit,
    export_source_candles,
    fmt_ts,
    installed_signal_handlers,
    periodic_heartbeat,
    phase,
    prepare_tracker_output_dir,
    repo_root,
    resolve_analysis_commit,
    resolve_tracker_source_commit,
    sha256_file,
    source_result_payload,
    tracker_source_hashes,
    utc_now,
    validate_run_id,
    write_json,
)


RUNNER_NAME = "bullish_breathline_btc_render_canonical_4h_v1"
RUNNER_VERSION = "1.0.3"
ORIGINAL_RELATIONSHIP_REGISTRY_COMMIT_SHA = "ec9254a9d2bbb4f30f0d61e160ea035e193adfb4"
FROZEN_RELATIONSHIP_REGISTRY_SOURCE_FILE = (
    "src/research/breathline_btc_alt_relationship_registry_v1_0_0_frozen.py"
)
EXPECTED_FROZEN_RELATIONSHIP_REGISTRY_SHA256 = (
    "baa1ff2093ed7d130944595babb67d1f696d1bd36296e442970d3c14dfc8656f"
)
SYMBOLS = (REFERENCE_SYMBOL, ALT_SYMBOL)
EXPECTED_INTERVAL_SECONDS = 4 * 60 * 60
DEFAULT_OUT_ROOT = Path("data/research/bullish_breathline_btc_render_canonical_4h_v1")
SOURCE_CHECKPOINT_FILENAME = "source_checkpoint.json"
RUN_MANIFEST_FILENAME = "run_manifest.json"

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
    "relationship_analysis": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}


def runner_source_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def registry_source_sha256() -> str:
    """Verify and hash the immutable vendored v1.0.0 preregistration snapshot."""
    snapshot = repo_root() / FROZEN_RELATIONSHIP_REGISTRY_SOURCE_FILE
    if not snapshot.is_file():
        raise RuntimeError(f"frozen relationship registry snapshot missing: {snapshot}")
    observed = sha256_file(snapshot)
    if observed != EXPECTED_FROZEN_RELATIONSHIP_REGISTRY_SHA256:
        raise RuntimeError(
            "frozen relationship registry snapshot hash mismatch: "
            f"expected={EXPECTED_FROZEN_RELATIONSHIP_REGISTRY_SHA256} observed={observed}"
        )
    return observed


def resolve_asset_identity(conn: Any, symbol: str) -> AssetIdentity:
    requested = str(symbol).strip().upper()
    if requested not in SYMBOLS:
        raise ValueError(f"symbol outside frozen #418 independent-ledger scope: {requested}")
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


def source_result_from_payload(payload: dict[str, Any], *, expected_csv: Path) -> SourceExportResult:
    from src.research.run_bullish_breathline_canonical_4h_v1 import GapRecord

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


def write_source_checkpoint(
    run_dir: Path,
    *,
    run_id: str,
    analysis_commit_sha: str,
    runner_hash: str,
    registry_hash: str,
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
        "relationship_registry_version": REGISTRY_VERSION,
        "relationship_registry_original_commit_sha": ORIGINAL_RELATIONSHIP_REGISTRY_COMMIT_SHA,
        "relationship_registry_snapshot_source_file": FROZEN_RELATIONSHIP_REGISTRY_SOURCE_FILE,
        "relationship_registry_expected_sha256": EXPECTED_FROZEN_RELATIONSHIP_REGISTRY_SHA256,
        "analysis_commit_sha": analysis_commit_sha,
        "runner_source_sha256": runner_hash,
        "registry_source_sha256": registry_hash,
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
    runner_hash: str,
    registry_hash: str,
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
        "relationship_registry_version": REGISTRY_VERSION,
        "relationship_registry_original_commit_sha": ORIGINAL_RELATIONSHIP_REGISTRY_COMMIT_SHA,
        "relationship_registry_snapshot_source_file": FROZEN_RELATIONSHIP_REGISTRY_SOURCE_FILE,
        "relationship_registry_expected_sha256": EXPECTED_FROZEN_RELATIONSHIP_REGISTRY_SHA256,
        "analysis_commit_sha": analysis_commit_sha,
        "runner_source_sha256": runner_hash,
        "registry_source_sha256": registry_hash,
        "tracker_source_commit_sha": tracker_source_commit_sha,
        "tracker_source_sha256": tracker_source_sha256,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(f"source checkpoint provenance mismatch: {key}")

    rows = payload.get("assets")
    if not isinstance(rows, list) or len(rows) != len(SYMBOLS):
        raise RuntimeError("source checkpoint asset set is invalid")
    row_by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict)
    }
    if set(row_by_symbol) != set(SYMBOLS):
        raise RuntimeError("source checkpoint symbols do not match frozen #418 scope")

    identities: list[AssetIdentity] = []
    source_by_symbol: dict[str, SourceExportResult] = {}
    for symbol in SYMBOLS:
        expected_csv = run_dir / symbol / "source" / "canonical_candles.csv"
        source = source_result_from_payload(row_by_symbol[symbol], expected_csv=expected_csv)
        if source.symbol != symbol:
            raise RuntimeError(f"source checkpoint symbol mismatch: {symbol}")
        if not expected_csv.is_file():
            raise RuntimeError(f"checkpoint source artifact missing: {expected_csv}")
        if sha256_file(expected_csv) != source.source_sha256:
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
    runner_hash = runner_source_sha256()
    registry_hash = registry_source_sha256()
    tracker_source_commit_sha = resolve_tracker_source_commit(root)
    source_hashes = tracker_source_hashes(root)
    run_ts = utc_now()

    if (run_dir / RUN_MANIFEST_FILENAME).exists():
        raise FileExistsError(f"completed immutable run already exists: {run_dir}")
    if run_dir.exists() and not resume:
        raise FileExistsError(f"run directory already exists; use --resume or a new run id: {run_dir}")

    resumed_from_source_checkpoint = False
    checkpoint_path: Path | None = None

    if run_dir.exists() and resume and (run_dir / SOURCE_CHECKPOINT_FILENAME).is_file():
        with phase("load_source_checkpoint", run_id=frozen_run_id):
            identities, source_by_symbol, checkpoint_path = load_source_checkpoint(
                run_dir,
                run_id=frozen_run_id,
                analysis_commit_sha=analysis_commit_sha,
                runner_hash=runner_hash,
                registry_hash=registry_hash,
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
                source_by_symbol: dict[str, SourceExportResult] = {}
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
            runner_hash=runner_hash,
            registry_hash=registry_hash,
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
            "relationship_analysis_performed": False,
            "relationship_registry_version": REGISTRY_VERSION,
            "relationship_registry_original_commit_sha": ORIGINAL_RELATIONSHIP_REGISTRY_COMMIT_SHA,
            "relationship_registry_snapshot_source_file": FROZEN_RELATIONSHIP_REGISTRY_SOURCE_FILE,
            "relationship_registry_expected_sha256": EXPECTED_FROZEN_RELATIONSHIP_REGISTRY_SHA256,
            "source_table": SOURCE_TABLE,
            "venue": VENUE,
            "symbols": list(SYMBOLS),
            "interval_code": INTERVAL_CODE,
            "input_interval_is_cycle_duration": False,
            "expected_interval_seconds": EXPECTED_INTERVAL_SECONDS,
            "fetch_batch_rows": FETCH_BATCH_ROWS,
            "db_transaction_isolation": TRANSACTION_ISOLATION_SQL,
            "db_transaction": TRANSACTION_START_SQL,
            "analysis_commit_sha": analysis_commit_sha,
            "runner_source_sha256": runner_hash,
            "registry_source_sha256": registry_hash,
            "tracker_source_commit_sha": tracker_source_commit_sha,
            "tracker_model_version": TRACKER_MODEL_VERSION,
            "tracker_source_sha256": source_hashes,
            "source_checkpoint_path": None if checkpoint_path is None else str(checkpoint_path),
            "source_checkpoint_sha256": None if checkpoint_path is None else sha256_file(checkpoint_path),
            "resumed_from_source_checkpoint": resumed_from_source_checkpoint,
            "cli": [
                sys.executable,
                "-m",
                "src.research.run_bullish_breathline_btc_render_canonical_4h_v1",
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
        if checkpoint_path is None or not checkpoint_path.is_file():
            shutil.rmtree(run_dir, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="Root for immutable #418 independent BTC/RENDER research runs",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Immutable run identifier. Defaults to current UTC timestamp.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from an intact source checkpoint for the same exact provenance.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=DEFAULT_HEARTBEAT_SECONDS,
        help="Progress heartbeat interval for extraction/tracker phases.",
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
            relationship_analysis=SAFETY_MARKERS["relationship_analysis"],
            decision_gate=SAFETY_MARKERS["decision_gate"],
            execution_planner=SAFETY_MARKERS["execution_planner"],
            executor=SAFETY_MARKERS["executor"],
            **fields,
        )

    emit(
        "STARTED",
        RUNNER_NAME,
        mode="independent_canonical_db_to_tracker",
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
                emit(
                    "INFO",
                    "asset_summary",
                    symbol=asset["symbol"],
                    source_rows=asset["source_row_count"],
                    gaps=asset["source_gap_count"],
                    cycles=asset["tracker_summary"].get("cycle_count", 0),
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
