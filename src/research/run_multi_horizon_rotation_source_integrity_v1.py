from __future__ import annotations

"""Read-only source-content integrity gate for Issue #593 final holdout.

This runner never builds or evaluates final-holdout candidate rows. It freezes or
verifies deterministic SHA-256 fingerprints of the canonical market sources that
a later holdout-only builder is allowed to read.
"""

import argparse
import hashlib
import json
import os
import tempfile
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.research.multi_horizon_rotation_validation_v1 import ensure_utc


RUNNER_NAME = "run_multi_horizon_rotation_source_integrity_v1"
RUNNER_VERSION = "1.0.0"
ROTATION_V1_MODEL_VERSION = "1.0"
FETCH_BATCH_SIZE = 5000
MAX_LOOKBACK = timedelta(hours=36)


def emit(message: str) -> None:
    print(message, flush=True)


def parse_ts(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def canonical_scalar(value: Any) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return format(Decimal(str(value)), "f")
    return str(value)


def canonical_row_bytes(row: dict[str, Any], fields: tuple[str, ...]) -> bytes:
    payload = [canonical_scalar(row.get(field)) for field in fields]
    return (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def hash_rows(rows: Iterable[dict[str, Any]], fields: tuple[str, ...]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        digest.update(canonical_row_bytes(row, fields))
        count += 1
    return digest.hexdigest(), count


def _stream_cursor_hash(cur: Any, fields: tuple[str, ...], *, batch_size: int) -> tuple[str, int]:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    digest = hashlib.sha256()
    count = 0
    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        for row in rows:
            digest.update(canonical_row_bytes(row, fields))
            count += 1
    return digest.hexdigest(), count


def fingerprint_candles(
    conn: Any,
    *,
    venue: str,
    source_start: datetime,
    source_end: datetime,
    batch_size: int = FETCH_BATCH_SIZE,
) -> dict[str, object]:
    read_start = ensure_utc(source_start) - MAX_LOOKBACK
    read_end = ensure_utc(source_end)
    fields = ("asset_id", "close_ts_utc", "close_price", "volume_base")
    sql = """
    SELECT asset_id, close_ts_utc, close_price, volume_base
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = '15m'
      AND close_ts_utc >= %s
      AND close_ts_utc < %s
    ORDER BY asset_id, close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                venue,
                read_start.replace(tzinfo=None),
                read_end.replace(tzinfo=None),
            ),
        )
        sha256, row_count = _stream_cursor_hash(cur, fields, batch_size=batch_size)
    return {
        "source": "obs_market_candle",
        "venue": venue,
        "interval_code": "15m",
        "read_start": canonical_scalar(read_start),
        "read_end_exclusive": canonical_scalar(read_end),
        "ordering": ["asset_id", "close_ts_utc"],
        "fields": list(fields),
        "row_count": row_count,
        "sha256": sha256,
    }


def fingerprint_rotation_v1(
    conn: Any,
    *,
    venue: str,
    source_end: datetime,
    batch_size: int = FETCH_BATCH_SIZE,
) -> dict[str, object]:
    read_end = ensure_utc(source_end)
    fields = (
        "pressure_obs_id",
        "pressure_snapshot_id",
        "asset_id",
        "as_of_ts_utc",
        "score_total",
        "pressure_state",
        "observation_model_version",
        "snapshot_as_of_ts_utc",
        "snapshot_model_version",
    )
    sql = """
    SELECT
        o.pressure_obs_id,
        o.pressure_snapshot_id,
        o.asset_id,
        o.as_of_ts_utc,
        o.score_total,
        o.pressure_state,
        o.model_version AS observation_model_version,
        s.as_of_ts_utc AS snapshot_as_of_ts_utc,
        s.model_version AS snapshot_model_version
    FROM market_rotation_pressure_observation_v1 o
    JOIN market_rotation_pressure_snapshot_v1 s
      ON s.pressure_snapshot_id = o.pressure_snapshot_id
    WHERE s.venue = %s
      AND o.model_version = %s
      AND s.model_version = %s
      AND o.as_of_ts_utc < %s
      AND s.as_of_ts_utc < %s
    ORDER BY o.asset_id, o.as_of_ts_utc, o.pressure_obs_id
    """
    cutoff = read_end.replace(tzinfo=None)
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                venue,
                ROTATION_V1_MODEL_VERSION,
                ROTATION_V1_MODEL_VERSION,
                cutoff,
                cutoff,
            ),
        )
        sha256, row_count = _stream_cursor_hash(cur, fields, batch_size=batch_size)
    return {
        "source": "market_rotation_pressure_observation_v1+snapshot_v1",
        "venue": venue,
        "model_version": ROTATION_V1_MODEL_VERSION,
        "read_end_exclusive": canonical_scalar(read_end),
        "ordering": ["asset_id", "as_of_ts_utc", "pressure_obs_id"],
        "fields": list(fields),
        "row_count": row_count,
        "sha256": sha256,
    }


def manifest_sha256(manifest: dict[str, object]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_split_manifest(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("split manifest must be a JSON object")
    if raw.get("final_holdout_inspected") is not False:
        raise ValueError("source integrity gate requires final_holdout_inspected=false")
    if not isinstance(raw.get("source_span"), dict):
        raise ValueError("split manifest missing source_span")
    if not isinstance(raw.get("splits"), dict) or "final_holdout" not in raw["splits"]:
        raise ValueError("split manifest missing final_holdout split")
    return raw


def build_integrity_payload(
    conn: Any,
    *,
    venue: str,
    split_manifest: dict[str, object],
    batch_size: int = FETCH_BATCH_SIZE,
) -> dict[str, object]:
    if split_manifest.get("venue") != venue:
        raise ValueError("venue does not match frozen split manifest")
    source_span = split_manifest["source_span"]
    assert isinstance(source_span, dict)
    source_start = parse_ts(source_span["start"])
    source_end = parse_ts(source_span["end"])
    candles = fingerprint_candles(
        conn,
        venue=venue,
        source_start=source_start,
        source_end=source_end,
        batch_size=batch_size,
    )
    rotation_v1 = fingerprint_rotation_v1(
        conn,
        venue=venue,
        source_end=source_end,
        batch_size=batch_size,
    )
    composite_material = {
        "split_manifest_sha256": manifest_sha256(split_manifest),
        "candles_sha256": candles["sha256"],
        "rotation_v1_sha256": rotation_v1["sha256"],
    }
    composite = hashlib.sha256(
        json.dumps(composite_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "integrity_version": "1.0.0",
        "issue": 593,
        "venue": venue,
        "split_manifest_sha256": composite_material["split_manifest_sha256"],
        "source_span": {
            "start": canonical_scalar(source_start),
            "end_exclusive": canonical_scalar(source_end),
        },
        "candles": candles,
        "rotation_v1": rotation_v1,
        "composite_sha256": composite,
        "final_holdout_outcomes_inspected": False,
        "safety": {
            "research_only": 1,
            "market_only": 1,
            "database_reads": 1,
            "database_writes": 0,
            "account_awareness": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
        },
    }


def persist_write_once(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path = Path(temp_name)
        try:
            os.link(temp_path, path)
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != payload:
                raise ValueError("source integrity fingerprint differs from frozen write-once artifact")
            return "VERIFIED_EXISTING"
        return "FROZEN"
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass


def verify_existing(path: Path, payload: dict[str, object]) -> None:
    if not path.exists():
        raise ValueError("source integrity artifact missing; freeze before verify")
    existing = json.loads(path.read_text(encoding="utf-8"))
    if existing != payload:
        raise ValueError("canonical source content drifted from frozen integrity artifact")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="#593 read-only canonical source-content integrity freeze/verify gate"
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--split-manifest", required=True)
    parser.add_argument("--output-json", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--verify", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=".env", override=False)
    started = time.perf_counter()
    mode = "freeze" if args.freeze else "verify"
    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} mode={mode} "
        f"venue={args.venue} workers=1 final_holdout_outcomes_inspected=0"
    )
    emit(
        "SAFETY research_only=1 market_only=1 database_reads=1 database_writes=0 account_awareness=0 "
        "decision_gate=none execution_planner=none executor=none broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0 final_holdout_outcomes_inspected=0"
    )
    conn = None
    try:
        split_manifest = load_split_manifest(Path(args.split_manifest))
        conn = get_db_connection()
        emit("PHASE_STARTED name=fingerprint_canonical_sources")
        phase_started = time.perf_counter()
        payload = build_integrity_payload(conn, venue=args.venue, split_manifest=split_manifest)
        emit(
            "PHASE_FINISHED name=fingerprint_canonical_sources "
            f"candle_rows={payload['candles']['row_count']} rotation_rows={payload['rotation_v1']['row_count']} "
            f"elapsed_s={time.perf_counter() - phase_started:.3f}"
        )
        output_path = Path(args.output_json)
        if args.freeze:
            state = persist_write_once(output_path, payload)
        else:
            verify_existing(output_path, payload)
            state = "VERIFIED"
        emit(
            f"FINISHED runner={RUNNER_NAME} result=PASS state={state} "
            f"composite_sha256={payload['composite_sha256']} final_holdout_outcomes_inspected=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except Exception as exc:
        emit(
            f"FAILED runner={RUNNER_NAME} error={exc.__class__.__name__}:{exc} "
            f"final_holdout_outcomes_inspected=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
