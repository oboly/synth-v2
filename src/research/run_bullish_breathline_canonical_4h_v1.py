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
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

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
DEFAULT_OUT_ROOT = Path("data/research/bullish_breathline_canonical_4h_v1")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

TRACKER_SOURCE_FILES = (
    "src/research/bullish_breathline_tracker_v1.py",
    "src/research/run_bullish_breathline_tracker_v1.py",
)


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
    observed_asset_id = int(row.get("asset_id"))
    observed_venue = str(row.get("venue") or "").strip().lower()
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

    try:
        with conn.cursor() as cur, csv_path.open("w", encoding="utf-8", newline="") as handle:
            cur.execute(sql, (identity.asset_id, VENUE, INTERVAL_CODE))
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("ts", "open", "high", "low", "close", "volume"))

            while True:
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
    except Exception:
        csv_path.unlink(missing_ok=True)
        raise

    if row_count == 0 or first_ts is None or last_ts is None:
        csv_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"empty canonical history for symbol={identity.symbol} venue={VENUE} interval={INTERVAL_CODE}"
        )

    return SourceExportResult(
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


def require_tracker_artifacts(tracker_dir: Path) -> dict[str, dict[str, str]]:
    required = ("cycle_ledger.jsonl", "latest_cycles.json", "summary.json")
    result: dict[str, dict[str, str]] = {}
    for filename in required:
        path = tracker_dir / filename
        if not path.is_file():
            raise RuntimeError(f"expected tracker artifact missing: {path}")
        result[filename] = {
            "path": str(path),
            "sha256": sha256_file(path),
        }
    return result


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(
    *,
    out_root: Path,
    run_id: str,
    cli_args: list[str],
) -> dict[str, Any]:
    frozen_run_id = validate_run_id(run_id)
    run_dir = out_root / frozen_run_id
    if run_dir.exists():
        raise FileExistsError(f"immutable run directory already exists: {run_dir}")

    root = repo_root()
    analysis_commit_sha = resolve_analysis_commit(root)
    tracker_source_commit_sha = resolve_tracker_source_commit(root)
    source_hashes = tracker_source_hashes(root)
    run_ts = utc_now()

    conn = get_connection()
    created_run_dir = False
    try:
        begin_read_only_transaction(conn)
        identities = [resolve_asset_identity(conn, symbol) for symbol in SYMBOLS]

        run_dir.mkdir(parents=True, exist_ok=False)
        created_run_dir = True
        assets_manifest: list[dict[str, Any]] = []

        for identity in identities:
            asset_dir = run_dir / identity.symbol
            source_csv = asset_dir / "source" / "canonical_candles.csv"
            tracker_dir = asset_dir / "tracker"

            source = export_source_candles(conn, identity=identity, csv_path=source_csv)
            tracker_summary = run_tracker(
                csv_path=source_csv,
                symbol=identity.symbol,
                out_dir=tracker_dir,
            )
            tracker_artifacts = require_tracker_artifacts(tracker_dir)

            source_payload = asdict(source)
            source_payload["gaps"] = [asdict(gap) for gap in source.gaps]
            assets_manifest.append(
                {
                    **source_payload,
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
            "analysis_commit_sha": analysis_commit_sha,
            "tracker_source_commit_sha": tracker_source_commit_sha,
            "tracker_model_version": TRACKER_MODEL_VERSION,
            "tracker_source_sha256": source_hashes,
            "cli": [
                sys.executable,
                "-m",
                "src.research.run_bullish_breathline_canonical_4h_v1",
                *cli_args,
            ],
            "assets": assets_manifest,
            "safety": {
                "selection_engine_changes": 0,
                "decision_gate_changes": 0,
                "execution_planner_changes": 0,
                "executor_changes": 0,
                "broker_calls": 0,
                "broker_writes": 0,
                "order_submission": 0,
                "live_trading_permission": 0,
                "production_db_writes": 0,
                "production_schema_changes": 0,
                "runtime_activation": 0,
            },
        }
        write_json(run_dir / "run_manifest.json", manifest)
        return manifest
    except Exception:
        if created_run_dir:
            shutil.rmtree(run_dir, ignore_errors=True)
        raise
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


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
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_args)
    manifest = run(
        out_root=args.out_root,
        run_id=args.run_id or default_run_id(),
        cli_args=raw_args,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
