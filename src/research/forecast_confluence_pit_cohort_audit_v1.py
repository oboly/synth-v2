"""Read-only deterministic identity audit for forecast confluence PIT replay."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from src.common.db import get_connection
from src.research.forecast_confluence_pit_replay_v1 import (
    HORIZONS,
    VERSION,
    assess,
    fetch_candles,
    fetch_rows,
    outcome_with_exclusion,
    parse_ts,
)

AUDIT_VERSION = "forecast_confluence_pit_cohort_audit/v1"
AUDIT_FILENAME = "cohort_determinism_audit_v1.json"
MANIFEST_FILENAME = "cohort_determinism_audit_manifest_v1.json"
FORECAST_LEDGER_FILENAME = "forecast_identity_ledger_v1.jsonl"
BASELINE_LEDGER_FILENAME = "baseline_outcome_identity_ledger_v1.jsonl"
ENRICHED_LEDGER_FILENAME = "enriched_outcome_identity_ledger_v1.jsonl"


def iso_z(value: datetime) -> str:
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(row, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
        for row in rows
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def forecast_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "forecast_as_of_utc": iso_z(row["asof_ts_utc"]),
        "map_id": row["map_id"],
        "market": row["market"],
        "venue": row["venue"],
    }


def endpoint_close_ts(row: dict[str, Any], candles: list[dict[str, Any]], horizon_hours: int) -> datetime | None:
    due = row["asof_ts_utc"] + next(h for h in HORIZONS if int(h.total_seconds() / 3600) == horizon_hours)
    endpoint = next((c for c in candles if c["close_ts_utc"] == due), None)
    return None if endpoint is None else endpoint["close_ts_utc"]


def build_identity_ledgers(
    rows: list[dict[str, Any]], candles_by_market: dict[str, list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, dict[str, int]]]:
    unique_rows = {tuple(forecast_identity(row).values()): row for row in rows}
    ordered_rows = [unique_rows[key] for key in sorted(unique_rows)]
    forecasts = [forecast_identity(row) for row in ordered_rows]
    outcomes: dict[str, list[dict[str, Any]]] = {"baseline": [], "enriched": []}
    exclusions: dict[str, Counter[str]] = {"baseline": Counter(), "enriched": Counter()}

    for row in ordered_rows:
        identity = forecast_identity(row)
        candles = candles_by_market[row["market"]]
        for mode in outcomes:
            assessment = assess(row, enriched=mode == "enriched")
            for horizon in HORIZONS:
                horizon_hours = int(horizon.total_seconds() / 3600)
                result, exclusion_reason = outcome_with_exclusion(row, assessment, candles, horizon)
                if result is None:
                    exclusions[mode][exclusion_reason or "other"] += 1
                    continue
                close_ts = endpoint_close_ts(row, candles, horizon_hours)
                if close_ts is None:
                    raise RuntimeError("outcome was present without an endpoint close timestamp")
                outcomes[mode].append(
                    {
                        **identity,
                        "endpoint_close_ts_utc": iso_z(close_ts),
                        "horizon_hours": horizon_hours,
                        "mode": mode,
                    }
                )

    for mode in outcomes:
        outcomes[mode].sort(
            key=lambda item: (
                item["venue"], item["market"], item["forecast_as_of_utc"], item["map_id"],
                item["mode"], item["horizon_hours"], item["endpoint_close_ts_utc"],
            )
        )
    return forecasts, outcomes, {
        mode: dict(sorted(exclusions[mode].items()))
        for mode in outcomes
    }


def fetch_pipeline_stage_counts(conn: Any, *, start: datetime, end: datetime, venue: str) -> dict[str, int]:
    sql = """
    WITH raw AS (
      SELECT map_id, symbol, venue, asof_ts_utc, interval_code, map_status
      FROM canonical_fib_zone_map_v1
      WHERE asof_ts_utc >= %s AND asof_ts_utc < %s
    ), venue_rows AS (SELECT * FROM raw WHERE venue=%s),
    interval_rows AS (SELECT * FROM venue_rows WHERE interval_code='4h'),
    fib_status AS (SELECT * FROM interval_rows WHERE map_status IN ('FRESH','FALLBACK','EMERGENCY_REBUILT')),
    asset_rows AS (
      SELECT f.* FROM fib_status f JOIN asset a ON BINARY a.symbol=BINARY f.symbol
    ), same_ts_signal AS (
      SELECT f.* FROM asset_rows f JOIN asset a ON BINARY a.symbol=BINARY f.symbol
      JOIN signal_engine_state s ON s.asset_id=a.asset_id AND BINARY s.venue=BINARY f.venue
        AND s.interval_code='4h' AND s.signal_ts_utc=f.asof_ts_utc
    )
    SELECT
      (SELECT COUNT(*) FROM raw) AS raw_count,
      (SELECT COUNT(*) FROM venue_rows) AS venue_count,
      (SELECT COUNT(*) FROM interval_rows) AS interval_count,
      (SELECT COUNT(*) FROM fib_status) AS fib_status_count,
      (SELECT COUNT(*) FROM asset_rows) AS asset_count,
      (SELECT COUNT(*) FROM same_ts_signal) AS same_ts_signal_count,
      (SELECT COUNT(DISTINCT CONCAT_WS('|', venue, symbol, asof_ts_utc, map_id)) FROM same_ts_signal) AS dedup_count
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start, end, venue))
        row = cur.fetchone()
    counts = {
        "raw": int(row["raw_count"]), "venue": int(row["venue_count"]),
        "interval": int(row["interval_count"]), "fib_status": int(row["fib_status_count"]),
        "asset": int(row["asset_count"]), "same_ts_signal": int(row["same_ts_signal_count"]),
        "dedup": int(row["dedup_count"]),
    }
    counts["final"] = counts["dedup"]
    return counts


def build_artifacts(
    *, rows: list[dict[str, Any]], candles_by_market: dict[str, list[dict[str, Any]],],
    pipeline_stage_counts: dict[str, int], start: datetime, end: datetime, venue: str,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    forecasts, outcomes, exclusions = build_identity_ledgers(rows, candles_by_market)
    ledgers = {
        FORECAST_LEDGER_FILENAME: canonical_jsonl_bytes(forecasts),
        BASELINE_LEDGER_FILENAME: canonical_jsonl_bytes(outcomes["baseline"]),
        ENRICHED_LEDGER_FILENAME: canonical_jsonl_bytes(outcomes["enriched"]),
    }
    audit = {
        "audit_version": AUDIT_VERSION,
        "baseline_outcome_count": len(outcomes["baseline"]),
        "baseline_outcome_identity_ledger_sha256": sha256(ledgers[BASELINE_LEDGER_FILENAME]),
        "end_ts": iso_z(end),
        "enriched_outcome_count": len(outcomes["enriched"]),
        "enriched_outcome_identity_ledger_sha256": sha256(ledgers[ENRICHED_LEDGER_FILENAME]),
        "exclusion_reason_counts": exclusions,
        "forecast_count": len(forecasts),
        "forecast_identity_contract": ["venue", "market", "forecast_as_of_utc", "map_id"],
        "forecast_identity_ledger_sha256": sha256(ledgers[FORECAST_LEDGER_FILENAME]),
        "outcome_identity_contract": ["forecast identity", "mode", "horizon_hours", "endpoint_close_ts_utc"],
        "pipeline_stage_counts": pipeline_stage_counts,
        "replay_version": VERSION,
        "start_ts": iso_z(start),
        "venue": venue,
    }
    files = {**ledgers, AUDIT_FILENAME: canonical_json_bytes(audit)}
    return files, audit


def write_artifacts(*, output_dir: Path, files: dict[str, bytes], audit: dict[str, Any], created_from_commit: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (output_dir / filename).write_bytes(content)
    manifest = {
        "canonical_audit_path": AUDIT_FILENAME,
        "canonical_audit_sha256": sha256(files[AUDIT_FILENAME]),
        "created_from_commit": created_from_commit,
        "generated_at_utc": iso_z(datetime.now(UTC)),
        "ledger_paths": {
            "baseline_outcome": BASELINE_LEDGER_FILENAME,
            "enriched_outcome": ENRICHED_LEDGER_FILENAME,
            "forecast": FORECAST_LEDGER_FILENAME,
        },
        "replay_version": audit["replay_version"],
    }
    (output_dir / MANIFEST_FILENAME).write_bytes(canonical_json_bytes(manifest))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only deterministic forecast confluence cohort audit")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--created-from-commit", required=True)
    args = parser.parse_args(argv)
    start, end = parse_ts(args.start), parse_ts(args.end)
    started = monotonic()
    print(f"STARTED runner=forecast_confluence_pit_cohort_audit_v1 mode=read_only venue={args.venue} workers=1", flush=True)
    conn = get_connection()
    try:
        print("PHASE_START fetch_pipeline_counts", flush=True)
        counts = fetch_pipeline_stage_counts(conn, start=start, end=end, venue=args.venue)
        print(f"PHASE_END fetch_pipeline_counts elapsed_seconds={monotonic() - started:.3f}", flush=True)
        print("PHASE_START fetch_replay_inputs", flush=True)
        rows = fetch_rows(conn, start=start, end=end, venue=args.venue)
        candles = fetch_candles(conn, rows, args.venue)
        print(f"PHASE_END fetch_replay_inputs rows={len(rows)} elapsed_seconds={monotonic() - started:.3f}", flush=True)
        files, audit = build_artifacts(rows=rows, candles_by_market=candles, pipeline_stage_counts=counts, start=start, end=end, venue=args.venue)
        write_artifacts(output_dir=args.output_dir, files=files, audit=audit, created_from_commit=args.created_from_commit)
        print(f"FINISHED forecast_count={audit['forecast_count']} baseline_outcomes={audit['baseline_outcome_count']} enriched_outcomes={audit['enriched_outcome_count']}", flush=True)
    finally:
        conn.rollback()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
