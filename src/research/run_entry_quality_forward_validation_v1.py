from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from src.common.db import get_db_connection
from src.research.entry_quality_forward_validation_v1 import (
    Candle,
    HorizonSpec,
    evaluate_all_horizons,
)


RUNNER_NAME = "entry_quality_forward_validation_v1"
DEFAULT_REGISTRY = "config/research/entry_quality_forward_validation_v1.yaml"
DEFAULT_OUTPUT_DIR = Path("data/research/entry_quality_forward_validation_v1")
OUTPUT_ROWS = "forward_outcomes_v1.jsonl"
OUTPUT_SUMMARY = "summary_v1.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay-safe forward outcome labels for CQ shadow observations"
    )
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def parse_ts(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"Unsupported JSON type: {type(value).__name__}")


def load_registry(path: str) -> tuple[dict[str, Any], list[HorizonSpec]]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if raw.get("registry_version") != "1.0.0":
        raise ValueError("Expected frozen registry version 1.0.0")
    if raw.get("source", {}).get("candle_interval") != "15m":
        raise ValueError("Frozen v1 candle interval must be 15m")
    horizons = [
        HorizonSpec(label=str(item["label"]), delta=timedelta(minutes=int(item["minutes"])))
        for item in raw.get("horizons", [])
    ]
    if [(item.label, int(item.delta.total_seconds() // 60)) for item in horizons] != [
        ("1h", 60),
        ("4h", 240),
        ("24h", 1440),
    ]:
        raise ValueError("Frozen v1 horizons must be exactly 1h,4h,24h")
    return raw, horizons


def fetch_shadow_observations(
    conn,
    *,
    venue: str,
    asset_id: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    asset_filter = " AND s.asset_id = %s" if asset_id is not None else ""
    params: list[Any] = [venue]
    if asset_id is not None:
        params.append(asset_id)
    params.append(limit)
    sql = f"""
    SELECT
        s.shadow_id,
        s.asset_id,
        a.symbol,
        s.venue,
        s.asof_ts_utc,
        s.evidence_key,
        s.cq_model_version,
        s.trade_quality_score,
        s.selection_score,
        s.entry_quality_score,
        s.entry_quality_state,
        s.ppp_pct,
        s.ppp_kind,
        s.ppp_source_ref,
        s.entry_strength
    FROM research_entry_quality_shadow s
    JOIN asset a ON a.asset_id = s.asset_id
    WHERE s.venue = %s
      {asset_filter}
    ORDER BY s.asof_ts_utc, s.asset_id, s.shadow_id
    LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    if any(not isinstance(row, dict) for row in rows):
        raise TypeError("Expected dict cursor rows for CQ shadow observations")
    return list(rows)


def fetch_candles_for_observation(
    conn,
    *,
    asset_id: int,
    venue: str,
    observation_asof: datetime,
    max_horizon: timedelta,
) -> list[Candle]:
    base_sql = """
    SELECT close_ts_utc, close_price, high_price, low_price
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = '15m'
      AND close_ts_utc <= %s
    ORDER BY close_ts_utc DESC
    LIMIT 1
    """
    future_sql = """
    SELECT close_ts_utc, close_price, high_price, low_price
    FROM obs_market_candle
    WHERE asset_id = %s
      AND venue = %s
      AND interval_code = '15m'
      AND close_ts_utc > %s
      AND close_ts_utc <= %s
    ORDER BY close_ts_utc
    """
    horizon_end = observation_asof + max_horizon
    with conn.cursor() as cur:
        cur.execute(base_sql, (asset_id, venue, observation_asof))
        base = cur.fetchone()
        cur.execute(future_sql, (asset_id, venue, observation_asof, horizon_end))
        future = cur.fetchall()

    raw_rows = ([] if base is None else [base]) + list(future)
    candles: list[Candle] = []
    for raw in raw_rows:
        candles.append(
            Candle(
                close_ts_utc=parse_ts(raw["close_ts_utc"]),
                close_price=Decimal(str(raw["close_price"])),
                high_price=Decimal(str(raw["high_price"])),
                low_price=Decimal(str(raw["low_price"])),
            )
        )
    return candles


def build_rows(
    conn,
    *,
    observations: list[dict[str, Any]],
    venue: str,
    horizons: list[HorizonSpec],
) -> list[dict[str, Any]]:
    max_horizon = max((item.delta for item in horizons), default=timedelta(0))
    out: list[dict[str, Any]] = []
    for observation in observations:
        asof = parse_ts(observation["asof_ts_utc"])
        candles = fetch_candles_for_observation(
            conn,
            asset_id=int(observation["asset_id"]),
            venue=venue,
            observation_asof=asof,
            max_horizon=max_horizon,
        )
        outcomes = evaluate_all_horizons(
            observation_asof=asof,
            candles=candles,
            horizons=horizons,
        )
        for outcome in outcomes:
            out.append(
                {
                    "shadow_id": int(observation["shadow_id"]),
                    "asset_id": int(observation["asset_id"]),
                    "symbol": str(observation["symbol"]),
                    "venue": str(observation["venue"]),
                    "observation_asof_ts_utc": asof,
                    "evidence_key": str(observation["evidence_key"]),
                    "cq_model_version": str(observation["cq_model_version"]),
                    "ppp_pct": observation.get("ppp_pct"),
                    "ppp_kind": observation.get("ppp_kind"),
                    "ppp_source_ref": observation.get("ppp_source_ref"),
                    "trade_quality_score": observation.get("trade_quality_score"),
                    "selection_score": observation.get("selection_score"),
                    "cq_v0": observation.get("entry_quality_score"),
                    "cq_v0_state": observation.get("entry_quality_state"),
                    "entry_strength_v0": observation.get("entry_strength"),
                    "cq_v1": None,
                    "entry_strength_v1": None,
                    "target_outcome_status": "UNAVAILABLE_NO_CANONICAL_TARGET_PRICE",
                    **asdict(outcome),
                }
            )
    return out


def write_outputs(output_dir: Path, rows: list[dict[str, Any]], registry: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / OUTPUT_ROWS
    with rows_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=json_default) + "\n")

    status_counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['horizon']}:{row['status']}"
        status_counts[key] = status_counts.get(key, 0) + 1
    summary = {
        "runner": RUNNER_NAME,
        "registry_name": registry["registry_name"],
        "registry_version": registry["registry_version"],
        "row_count": len(rows),
        "observation_count": len({row["shadow_id"] for row in rows}),
        "status_counts": status_counts,
        "target_outcomes": "UNAVAILABLE_NO_CANONICAL_TARGET_PRICE",
        "production_ranking_changed": False,
    }
    (output_dir / OUTPUT_SUMMARY).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    print(f"STARTED runner={RUNNER_NAME} mode=research-read-only", flush=True)
    print(
        "SAFETY research_only=1 market_only=1 db_writes=0 production_ranking_changes=0 "
        "decision_gate=none execution_planner=none executor=none broker_writes=0 orders=0",
        flush=True,
    )
    conn = None
    try:
        registry, horizons = load_registry(args.registry)
        print("PHASE_START name=fetch_shadow_observations", flush=True)
        conn = get_db_connection()
        observations = fetch_shadow_observations(
            conn,
            venue=args.venue,
            asset_id=args.asset_id,
            limit=args.limit,
        )
        print(f"PHASE_END name=fetch_shadow_observations rows={len(observations)}", flush=True)

        print("PHASE_START name=label_forward_outcomes", flush=True)
        rows = build_rows(
            conn,
            observations=observations,
            venue=args.venue,
            horizons=horizons,
        )
        print(f"PHASE_END name=label_forward_outcomes rows={len(rows)}", flush=True)

        print(f"PHASE_START name=write_files output_dir={args.output_dir}", flush=True)
        write_outputs(Path(args.output_dir), rows, registry)
        print(f"PHASE_END name=write_files rows={len(rows)}", flush=True)
        print(
            f"FINISHED runner={RUNNER_NAME} observations={len(observations)} rows={len(rows)} "
            f"production_ranking_changed=0 elapsed_s={time.perf_counter() - started:.3f}",
            flush=True,
        )
        return 0
    except Exception as exc:
        print(
            f"FAILED runner={RUNNER_NAME} reason={type(exc).__name__}:{exc} db_writes=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
