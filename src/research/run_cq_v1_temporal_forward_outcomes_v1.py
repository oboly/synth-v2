from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.research.entry_quality_forward_validation_v1 import Candle, HorizonSpec, evaluate_all_horizons

RUNNER_NAME = "cq_v1_temporal_forward_outcomes_v1"
DEFAULT_CONTRACT = "config/research/cq_v1_temporal_forward_outcomes_v1.json"
PINNED_CONTRACT_SHA256 = "db91406c58c67f97e8df0783f975247ee508464db8f5013dc875bdcfcc028197"
PINNED_POPULATION_SHA256 = "61bab264b2921b93a25a22ec0d12cbc031ad0ef234fa989b2ea43c894bc263b4"
DEFAULT_OUTPUT_DIR = "data/research/cq_v1_temporal_forward_outcomes_v1"
OUTPUT_ROWS = "forward_outcomes.jsonl"
OUTPUT_SUMMARY = "summary.json"
OUTPUT_MANIFEST = "manifest.json"
HORIZON_MINUTES = (("1h", 60), ("4h", 240), ("24h", 1440))
WORKER_COUNT = 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Read-only forward labels for frozen CQ v1 temporal population")
    p.add_argument("--population", required=True)
    p.add_argument("--contract", default=DEFAULT_CONTRACT)
    p.add_argument("--venue", default="bitvavo")
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--asof-index", type=int, default=None, help="optional 1-based frozen as-of smoke bound")
    p.add_argument("--asset-id", type=int, default=None, help="optional single-asset smoke bound")
    p.add_argument("--horizon", choices=[item[0] for item in HORIZON_MINUTES], default=None)
    p.add_argument("--limit-observations", type=int, default=None)
    return p.parse_args(argv)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def canonical_json_sha256(payload: Any) -> str:
    raw = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_ts(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_contract(path: str = DEFAULT_CONTRACT) -> tuple[dict[str, Any], list[HorizonSpec]]:
    if path != DEFAULT_CONTRACT:
        raise ValueError(f"contract path must remain pinned to {DEFAULT_CONTRACT}")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if canonical_json_sha256(payload) != PINNED_CONTRACT_SHA256:
        raise ValueError("temporal forward outcome contract SHA256 mismatch")
    if payload.get("contract_version") != "1.0.0":
        raise ValueError("expected contract version 1.0.0")
    if payload.get("frozen_population", {}).get("population_sha256") != PINNED_POPULATION_SHA256:
        raise ValueError("frozen population SHA mismatch in contract")
    actual = [(str(item["label"]), int(item["minutes"])) for item in payload.get("horizons", [])]
    if actual != list(HORIZON_MINUTES):
        raise ValueError("frozen horizons must be exactly 1h,4h,24h")
    return payload, [HorizonSpec(label=label, delta=timedelta(minutes=minutes)) for label, minutes in actual]


def load_population(path: Path, contract: dict[str, Any]) -> list[dict[str, Any]]:
    actual_sha = _sha256_path(path)
    if actual_sha != PINNED_POPULATION_SHA256:
        raise ValueError(f"population SHA256 mismatch expected={PINNED_POPULATION_SHA256} actual={actual_sha}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    frozen = contract["frozen_population"]
    if len(rows) != int(frozen["row_count"]):
        raise ValueError("frozen population row count mismatch")
    ids = [str(row["observation_id"]) for row in rows]
    if len(ids) != len(set(ids)) or len(ids) != int(frozen["unique_observation_ids"]):
        raise ValueError("frozen population observation identity mismatch")
    asofs = sorted({parse_ts(row["asof_ts_utc"]) for row in rows})
    if len(asofs) != int(frozen["unique_asofs"]):
        raise ValueError("frozen population as-of count mismatch")
    if asofs[0] != parse_ts(frozen["first_asof_ts_utc"]) or asofs[-1] != parse_ts(frozen["last_asof_ts_utc"]):
        raise ValueError("frozen population as-of boundary mismatch")
    return rows


def select_population_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = rows
    if args.asof_index is not None:
        asofs = sorted({parse_ts(row["asof_ts_utc"]) for row in rows})
        if args.asof_index < 1 or args.asof_index > len(asofs):
            raise ValueError(f"--asof-index must be between 1 and {len(asofs)}")
        target = asofs[args.asof_index - 1]
        selected = [row for row in selected if parse_ts(row["asof_ts_utc"]) == target]
    if args.asset_id is not None:
        selected = [row for row in selected if int(row["asset_id"]) == args.asset_id]
    selected = sorted(selected, key=lambda row: (parse_ts(row["asof_ts_utc"]), int(row["asset_id"]), str(row["observation_id"])))
    if args.limit_observations is not None:
        if args.limit_observations < 1:
            raise ValueError("--limit-observations must be >= 1")
        selected = selected[: args.limit_observations]
    if not selected:
        raise ValueError("bounded population selection is empty")
    return selected


def _placeholders(values: list[int]) -> str:
    if not values:
        raise ValueError("asset scope must not be empty")
    return ",".join(["%s"] * len(values))


def fetch_candles_for_asof_assets(
    conn: Any,
    *,
    asset_ids: list[int],
    venue: str,
    observation_asof: datetime,
    max_horizon: timedelta,
) -> dict[int, list[Candle]]:
    ids = sorted(set(int(value) for value in asset_ids))
    marks = _placeholders(ids)
    horizon_end = observation_asof + max_horizon
    base_sql = f"""
    SELECT c.asset_id,c.close_ts_utc,c.close_price,c.high_price,c.low_price
    FROM obs_market_candle c
    JOIN (
      SELECT asset_id,MAX(close_ts_utc) max_ts
      FROM obs_market_candle
      WHERE venue=%s AND interval_code='15m' AND asset_id IN ({marks}) AND close_ts_utc <= %s
      GROUP BY asset_id
    ) x ON x.asset_id=c.asset_id AND x.max_ts=c.close_ts_utc
    WHERE c.venue=%s AND c.interval_code='15m'
    ORDER BY c.asset_id
    """
    future_sql = f"""
    SELECT asset_id,close_ts_utc,close_price,high_price,low_price
    FROM obs_market_candle
    WHERE venue=%s AND interval_code='15m' AND asset_id IN ({marks})
      AND close_ts_utc > %s AND close_ts_utc <= %s
    ORDER BY asset_id,close_ts_utc
    """
    coverage_sql = f"""
    SELECT c.asset_id,c.close_ts_utc,c.close_price,c.high_price,c.low_price
    FROM obs_market_candle c
    JOIN (
      SELECT asset_id,MIN(close_ts_utc) min_ts
      FROM obs_market_candle
      WHERE venue=%s AND interval_code='15m' AND asset_id IN ({marks}) AND close_ts_utc > %s
      GROUP BY asset_id
    ) x ON x.asset_id=c.asset_id AND x.min_ts=c.close_ts_utc
    WHERE c.venue=%s AND c.interval_code='15m'
    ORDER BY c.asset_id
    """
    started = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(base_sql, tuple([venue, *ids, observation_asof, venue]))
        base_rows = list(cur.fetchall())
        cur.execute(future_sql, tuple([venue, *ids, observation_asof, horizon_end]))
        future_rows = list(cur.fetchall())
        cur.execute(coverage_sql, tuple([venue, *ids, horizon_end, venue]))
        coverage_rows = list(cur.fetchall())
    print(
        f"QUERY phase=candles status=finished asof={observation_asof.isoformat()} assets={len(ids)} "
        f"base_rows={len(base_rows)} future_rows={len(future_rows)} coverage_rows={len(coverage_rows)} "
        f"elapsed_s={time.monotonic() - started:.3f}",
        flush=True,
    )
    grouped: dict[int, list[Candle]] = defaultdict(list)
    for raw in [*base_rows, *future_rows, *coverage_rows]:
        grouped[int(raw["asset_id"])].append(
            Candle(
                close_ts_utc=parse_ts(raw["close_ts_utc"]),
                close_price=Decimal(str(raw["close_price"])),
                high_price=Decimal(str(raw["high_price"])),
                low_price=Decimal(str(raw["low_price"])),
            )
        )
    return grouped


def build_outcome_rows(
    conn: Any,
    *,
    observations: list[dict[str, Any]],
    venue: str,
    horizons: list[HorizonSpec],
) -> list[dict[str, Any]]:
    by_asof: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        by_asof[parse_ts(row["asof_ts_utc"])].append(row)
    out: list[dict[str, Any]] = []
    max_horizon = max(item.delta for item in horizons)
    for asof in sorted(by_asof):
        scoped = by_asof[asof]
        candle_map = fetch_candles_for_asof_assets(
            conn,
            asset_ids=[int(row["asset_id"]) for row in scoped],
            venue=venue,
            observation_asof=asof,
            max_horizon=max_horizon,
        )
        for observation in scoped:
            observation_id = str(observation["observation_id"])
            outcomes = evaluate_all_horizons(
                observation_asof=asof,
                candles=candle_map.get(int(observation["asset_id"]), []),
                horizons=horizons,
            )
            for outcome in outcomes:
                identity = {
                    "observation_id": observation_id,
                    "horizon": outcome.horizon,
                    "contract_sha256": PINNED_CONTRACT_SHA256,
                    "population_sha256": PINNED_POPULATION_SHA256,
                }
                out.append(
                    {
                        "outcome_id": canonical_json_sha256(identity),
                        "observation_id": observation_id,
                        "asset_id": int(observation["asset_id"]),
                        "symbol": str(observation["symbol"]),
                        "venue": str(observation["venue"]),
                        "observation_asof_ts_utc": asof,
                        "split": str(observation["split"]),
                        "evidence_key": str(observation["evidence_key"]),
                        "cq_model_version": str(observation["cq_model_version"]),
                        "model_family_version": str(observation["model_family_version"]),
                        "trade_quality_score": observation.get("trade_quality_score"),
                        "selection_score": observation.get("selection_score"),
                        "cq_v0": observation.get("cq_v0"),
                        "target_outcome_status": "UNAVAILABLE_NO_CANONICAL_TARGET_PRICE",
                        "population_sha256": PINNED_POPULATION_SHA256,
                        "outcome_contract_sha256": PINNED_CONTRACT_SHA256,
                        **asdict(outcome),
                    }
                )
    ids = [row["outcome_id"] for row in out]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate temporal outcome identity")
    return out


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        tmp = Path(handle.name)
    os.replace(tmp, path)


def write_artifacts(output_dir: Path, rows: list[dict[str, Any]], *, observation_count: int) -> None:
    rows_path = output_dir / OUTPUT_ROWS
    rows_text = "".join(json.dumps(_jsonable(row), sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    _atomic_text(rows_path, rows_text)
    rows_sha = _sha256_path(rows_path)
    status_counts = Counter(f"{row['horizon']}:{row['status']}" for row in rows)
    summary = {
        "runner": RUNNER_NAME,
        "terminal_state": "FINISHED",
        "observation_count": observation_count,
        "outcome_row_count": len(rows),
        "unique_outcome_ids": len({row["outcome_id"] for row in rows}),
        "status_counts": dict(sorted(status_counts.items())),
        "population_sha256": PINNED_POPULATION_SHA256,
        "outcome_contract_sha256": PINNED_CONTRACT_SHA256,
        "outcomes_sha256": rows_sha,
        "db_writes": 0,
        "production_ranking_changes": 0,
    }
    summary_path = output_dir / OUTPUT_SUMMARY
    _atomic_text(summary_path, json.dumps(summary, sort_keys=True, indent=2) + "\n")
    manifest = {
        "runner": RUNNER_NAME,
        "issue": 684,
        "parent_issue": 568,
        "population_sha256": PINNED_POPULATION_SHA256,
        "outcome_contract_path": DEFAULT_CONTRACT,
        "outcome_contract_sha256": PINNED_CONTRACT_SHA256,
        "outcomes_file": OUTPUT_ROWS,
        "outcomes_sha256": rows_sha,
        "summary_sha256": _sha256_path(summary_path),
        "db_writes": 0,
        "broker_writes": 0,
        "production_ranking_changes": 0,
    }
    _atomic_text(output_dir / OUTPUT_MANIFEST, json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(
        f"ARTIFACTS outcomes={rows_path} rows={len(rows)} outcomes_sha256={rows_sha} db_writes=0",
        flush=True,
    )


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    print(
        f"STARTED runner={RUNNER_NAME} mode=research_read_only workers={WORKER_COUNT} venue={args.venue} "
        f"asof_index={args.asof_index} asset_id={args.asset_id} horizon={args.horizon} limit={args.limit_observations}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 account_awareness=0 db_writes=0 model_retuning=0 "
        "production_ranking_changes=0 decision_gate=none execution_planner=none executor=none "
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 runtime_activation=0",
        flush=True,
    )
    contract, horizons = load_contract(args.contract)
    population_path = Path(args.population)
    observations = select_population_rows(load_population(population_path, contract), args)
    if args.horizon is not None:
        horizons = [item for item in horizons if item.label == args.horizon]
    print(
        f"BOUND observations={len(observations)} unique_asofs={len({parse_ts(row['asof_ts_utc']) for row in observations})} "
        f"horizons={','.join(item.label for item in horizons)} population_sha256={PINNED_POPULATION_SHA256}",
        flush=True,
    )
    conn = get_db_connection()
    try:
        rows = build_outcome_rows(conn, observations=observations, venue=args.venue, horizons=horizons)
    finally:
        conn.rollback()
        conn.close()
    write_artifacts(Path(args.output_dir), rows, observation_count=len(observations))
    print(
        f"FINISHED runner={RUNNER_NAME} observations={len(observations)} outcome_rows={len(rows)} "
        f"db_writes=0 elapsed_s={time.monotonic() - started:.3f}",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
