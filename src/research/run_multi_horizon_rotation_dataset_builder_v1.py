from __future__ import annotations

"""Read-only dataset builder for Issue #593 discovery/validation artifacts.

The runner derives the frozen 60/20/20 split from source availability only,
builds exactly one non-holdout phase per invocation, and never exposes a
final-holdout phase option.
"""

import argparse
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.research.multi_horizon_rotation_dataset_builder_v1 import (
    AssetCoverage,
    RotationV1PitIndex,
    RotationV1Point,
    comparable_horizon_return,
    derive_common_source_span,
    forward_response,
    split_manifest_payload,
)
from src.research.multi_horizon_rotation_replay_v1 import (
    CANDIDATE_SPECS,
    Candle,
    CandidateResult,
    evaluate_candidate,
)
from src.research.multi_horizon_rotation_validation_v1 import ensure_utc


RUNNER_NAME = "run_multi_horizon_rotation_dataset_builder_v1"
RUNNER_VERSION = "1.0.0"
ALLOWED_PHASES = ("discovery", "validation")
MAX_LOOKBACK = timedelta(hours=36)
MAX_FORWARD = timedelta(hours=24)
FORWARD_HORIZONS = {
    "forward_15m": timedelta(minutes=15),
    "forward_1h": timedelta(hours=1),
    "forward_4h": timedelta(hours=4),
    "forward_24h": timedelta(hours=24),
}
ROTATION_V1_MODEL_VERSION = "1.0"


def emit(message: str) -> None:
    print(message, flush=True)


def parse_ts(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat().replace("+00:00", "Z")
    raise TypeError(type(value).__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build #593 discovery/validation rows without holdout access")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--phase", required=True, choices=ALLOWED_PHASES)
    parser.add_argument("--output-dir", default="data/research/multi_horizon_rotation_validation_v1")
    return parser.parse_args(argv)


def fetch_asset_coverage(conn: Any, *, venue: str) -> list[AssetCoverage]:
    sql = """
    SELECT asset_id, MIN(close_ts_utc) AS first_close_ts, MAX(close_ts_utc) AS last_close_ts
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = '15m'
    GROUP BY asset_id
    ORDER BY asset_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue,))
        rows = cur.fetchall()
    return [
        AssetCoverage(
            asset_id=int(row["asset_id"]),
            first_close_ts=parse_ts(row["first_close_ts"]),
            last_close_ts=parse_ts(row["last_close_ts"]),
        )
        for row in rows
    ]


def fetch_rotation_v1_first_ts(conn: Any, *, venue: str) -> datetime:
    sql = """
    SELECT MIN(as_of_ts_utc) AS first_ts
    FROM market_rotation_pressure_snapshot_v1
    WHERE venue = %s AND model_version = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, ROTATION_V1_MODEL_VERSION))
        row = cur.fetchone()
    if not row or row.get("first_ts") is None:
        raise ValueError("Rotation V1 PIT history unavailable for venue")
    return parse_ts(row["first_ts"])


def fetch_rotation_v1_points(
    conn: Any,
    *,
    venue: str,
    through_ts: datetime,
) -> RotationV1PitIndex:
    sql = """
    SELECT o.asset_id, o.as_of_ts_utc, o.score_total, o.pressure_state
    FROM market_rotation_pressure_observation_v1 o
    JOIN market_rotation_pressure_snapshot_v1 s
      ON s.pressure_snapshot_id = o.pressure_snapshot_id
    WHERE s.venue = %s
      AND o.model_version = %s
      AND s.model_version = %s
      AND o.as_of_ts_utc <= %s
      AND s.as_of_ts_utc <= %s
    ORDER BY o.asset_id, o.as_of_ts_utc, o.pressure_obs_id
    """
    cutoff = ensure_utc(through_ts).replace(tzinfo=None)
    with conn.cursor() as cur:
        cur.execute(sql, (venue, ROTATION_V1_MODEL_VERSION, ROTATION_V1_MODEL_VERSION, cutoff, cutoff))
        rows = cur.fetchall()
    by_asset: dict[int, list[RotationV1Point]] = {}
    for row in rows:
        by_asset.setdefault(int(row["asset_id"]), []).append(
            RotationV1Point(
                asof_ts=parse_ts(row["as_of_ts_utc"]),
                score_total=float(row["score_total"]),
                pressure_state=str(row["pressure_state"]),
            )
        )
    return RotationV1PitIndex(by_asset)


def fetch_candles_for_asof(
    conn: Any,
    *,
    venue: str,
    asof_ts: datetime,
    phase_end: datetime,
) -> tuple[dict[int, list[Candle]], dict[int, dict[datetime, Decimal]], int]:
    start = ensure_utc(asof_ts) - MAX_LOOKBACK
    latest_needed = min(ensure_utc(asof_ts) + MAX_FORWARD, ensure_utc(phase_end) - timedelta(minutes=15))
    sql = """
    SELECT asset_id, close_ts_utc, close_price, volume_base
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = '15m'
      AND close_ts_utc >= %s
      AND close_ts_utc <= %s
    ORDER BY asset_id, close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, start.replace(tzinfo=None), latest_needed.replace(tzinfo=None)))
        rows = cur.fetchall()

    replay: dict[int, list[Candle]] = {}
    closes: dict[int, dict[datetime, Decimal]] = {}
    asof = ensure_utc(asof_ts)
    for row in rows:
        asset_id = int(row["asset_id"])
        ts = parse_ts(row["close_ts_utc"])
        close = Decimal(str(row["close_price"]))
        closes.setdefault(asset_id, {})[ts] = close
        if ts <= asof:
            replay.setdefault(asset_id, []).append(
                Candle(
                    close_ts_utc=ts,
                    close_price=close,
                    volume_base=Decimal(str(row["volume_base"])),
                )
            )
    return replay, closes, len(rows)


def asof_grid(start: datetime, end: datetime) -> list[datetime]:
    out: list[datetime] = []
    current = ensure_utc(start)
    stop = ensure_utc(end)
    while current < stop:
        out.append(current)
        current += timedelta(minutes=15)
    return out


def build_validation_row(
    *,
    result: CandidateResult,
    close_by_ts: dict[datetime, Decimal],
    spec_by_id: dict[str, Any],
    pit_index: RotationV1PitIndex,
    phase_end: datetime,
) -> dict[str, Any]:
    spec = spec_by_id[result.candidate_id]
    pit = pit_index.latest_at_or_before(asset_id=result.asset_id, asof_ts=result.asof_ts)
    row = {
        "venue": result.venue,
        "asset_id": result.asset_id,
        "asof_ts": result.asof_ts,
        "candidate_id": result.candidate_id,
        "candidate_model_id": result.model_id,
        "candidate_model_version": result.model_version,
        "candidate_effective_horizon": result.effective_horizon,
        "candidate_score": None if result.rotation_score is None else float(result.rotation_score),
        "candidate_data_quality": result.data_quality,
        "candidate_reason": result.reason,
        "candidate_cohort_size": result.cohort_size,
        "b0_score": None if pit is None else pit.score_total,
        "b0_pressure_state": None if pit is None else pit.pressure_state,
        "b0_model_version": ROTATION_V1_MODEL_VERSION,
        "b1_return": comparable_horizon_return(
            close_by_ts=close_by_ts,
            asof_ts=result.asof_ts,
            spec=spec,
        ),
        "b2_status": "UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE",
    }
    for field, horizon in FORWARD_HORIZONS.items():
        row[field] = forward_response(
            close_by_ts=close_by_ts,
            asof_ts=result.asof_ts,
            horizon=horizon,
            phase_end=phase_end,
        )
    return row


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=json_default) + "\n")
        handle.flush()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(dotenv_path=".env", override=False)
    started = time.perf_counter()
    emit(
        f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION} mode=research-read-only "
        f"venue={args.venue} phase={args.phase} workers=1 final_holdout_access=DENY"
    )
    emit(
        "SAFETY research_only=1 market_only=1 database_reads=1 database_writes=0 account_awareness=0 "
        "decision_gate=none execution_planner=none executor=none broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0"
    )
    conn = None
    try:
        conn = get_db_connection()

        emit("PHASE_STARTED name=derive_source_span")
        phase_started = time.perf_counter()
        coverage = fetch_asset_coverage(conn, venue=args.venue)
        rotation_first = fetch_rotation_v1_first_ts(conn, venue=args.venue)
        span = derive_common_source_span(coverage=coverage, rotation_v1_first_ts=rotation_first)
        manifest = split_manifest_payload(span)
        split = manifest["splits"][args.phase]
        phase_start = parse_ts(split["start"])
        phase_end = parse_ts(split["end"])
        emit(
            f"PHASE_FINISHED name=derive_source_span coverage_assets={len(coverage)} "
            f"source_start={span.start.isoformat()} source_end={span.end.isoformat()} "
            f"phase_start={phase_start.isoformat()} phase_end={phase_end.isoformat()} "
            f"elapsed_s={time.perf_counter() - phase_started:.3f}"
        )

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "split_manifest_v1.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        emit("PHASE_STARTED name=load_rotation_v1_pit")
        phase_started = time.perf_counter()
        pit_index = fetch_rotation_v1_points(conn, venue=args.venue, through_ts=phase_end)
        emit(f"PHASE_FINISHED name=load_rotation_v1_pit elapsed_s={time.perf_counter() - phase_started:.3f}")

        emit(f"PHASE_STARTED name=build_{args.phase}_artifact")
        phase_started = time.perf_counter()
        output_rows: list[dict[str, Any]] = []
        spec_by_id = {spec.candidate_id: spec for spec in CANDIDATE_SPECS}
        query_rows = 0
        for index, asof in enumerate(asof_grid(phase_start, phase_end), start=1):
            replay_candles, close_maps, fetched = fetch_candles_for_asof(
                conn,
                venue=args.venue,
                asof_ts=asof,
                phase_end=phase_end,
            )
            query_rows += fetched
            for spec in CANDIDATE_SPECS:
                results = evaluate_candidate(
                    candles_by_asset=replay_candles,
                    asof_ts=asof,
                    spec=spec,
                    venue=args.venue,
                )
                for result in results:
                    output_rows.append(
                        build_validation_row(
                            result=result,
                            close_by_ts=close_maps.get(result.asset_id, {}),
                            spec_by_id=spec_by_id,
                            pit_index=pit_index,
                            phase_end=phase_end,
                        )
                    )
            if index % 96 == 0:
                emit(
                    f"HEARTBEAT phase={args.phase} asofs_completed={index} rows_built={len(output_rows)} "
                    f"source_rows_read={query_rows} elapsed_s={time.perf_counter() - phase_started:.3f}"
                )

        artifact_path = output_dir / f"{args.phase}_rows_v1.jsonl"
        write_jsonl(artifact_path, output_rows)
        summary = {
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "venue": args.venue,
            "phase": args.phase,
            "row_count": len(output_rows),
            "asof_count": len(asof_grid(phase_start, phase_end)),
            "source_rows_read": query_rows,
            "final_holdout_access": "DENY",
            "b2_status": "UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE",
            "database_writes": 0,
        }
        (output_dir / f"{args.phase}_summary_v1.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        emit(
            f"PHASE_FINISHED name=build_{args.phase}_artifact rows={len(output_rows)} "
            f"source_rows_read={query_rows} elapsed_s={time.perf_counter() - phase_started:.3f}"
        )
        emit(
            f"FINISHED runner={RUNNER_NAME} result=PASS phase={args.phase} rows={len(output_rows)} "
            f"final_holdout_access=DENY database_writes=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 0
    except KeyboardInterrupt:
        emit(
            f"INTERRUPTED runner={RUNNER_NAME} final_holdout_access=DENY database_writes=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 130
    except Exception as exc:
        emit(
            f"FAILED runner={RUNNER_NAME} error={exc.__class__.__name__}:{exc} "
            f"final_holdout_access=DENY database_writes=0 elapsed_s={time.perf_counter() - started:.3f}"
        )
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
