from __future__ import annotations

"""Read-only executable runner for the frozen #310 MA/volume validation."""

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.common.db import get_db_connection
from src.research.ma_volume_frozen_validation_v1 import (
    CANDLE_HOURS,
    CANDLE_INTERVAL,
    DEFAULT_CONTRACT,
    PINNED_CONTRACT_SHA256,
    PINNED_OUTCOMES_SHA256,
    PINNED_POPULATION_SHA256,
    attach_outcome,
    build_candidate_observation,
    canonical_json_sha256,
    load_contract,
    load_outcomes,
    load_population,
    parse_ts,
    select_population_rows,
    sha256_path,
    validate_outcome_coverage,
)
from src.research.ma_volume_incremental_validation_v1 import evaluate_incremental_features
from src.research.ma_volume_candidate_features_v1 import (
    MODEL_ID as CANDIDATE_MODEL_ID,
    MODEL_VERSION as CANDIDATE_MODEL_VERSION,
)

RUNNER_NAME = "ma_volume_frozen_validation_run_v1"
DEFAULT_OUTPUT_DIR = "data/research/ma_volume_frozen_validation_v1"
ASSET_BATCH_SIZE = 200


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only frozen #310 MA/volume validation run")
    parser.add_argument("--population", required=True, help="frozen #661 observations.jsonl")
    parser.add_argument("--outcomes", required=True, help="frozen #684 forward_outcomes.jsonl")
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--asof-index", type=int, default=None, help="1-based smoke bound")
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit-observations", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if value is None:
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def fetch_unique_market_map(conn: Any, *, venue: str, asset_ids: Iterable[int]) -> dict[int, str]:
    ids = sorted(set(int(asset_id) for asset_id in asset_ids))
    result: dict[int, str] = {}
    for start in range(0, len(ids), ASSET_BATCH_SIZE):
        batch = ids[start : start + ASSET_BATCH_SIZE]
        placeholders = ",".join(["%s"] * len(batch))
        sql = f"""
        SELECT base_asset_id AS asset_id, market
        FROM venue_market
        WHERE venue=%s AND is_tradeable=1 AND base_asset_id IN ({placeholders})
        ORDER BY base_asset_id, market
        """
        with conn.cursor() as cur:
            cur.execute(sql, (venue, *batch))
            rows = cur.fetchall()
        grouped: dict[int, list[str]] = defaultdict(list)
        for row in rows:
            grouped[int(row["asset_id"])].append(str(row["market"]))
        for asset_id in batch:
            markets = grouped.get(asset_id, [])
            if len(markets) == 1:
                result[asset_id] = markets[0]
    return result


def fetch_candles_for_asof(
    conn: Any,
    *,
    venue: str,
    asof_ts_utc: datetime,
    asset_ids: Iterable[int],
    market_by_asset: dict[int, str],
    query_history_bars: int,
) -> dict[int, pd.DataFrame]:
    ids = sorted(set(int(asset_id) for asset_id in asset_ids if int(asset_id) in market_by_asset))
    if not ids:
        return {}
    if query_history_bars < 1:
        raise ValueError("query_history_bars must be positive")
    start_ts = asof_ts_utc - timedelta(hours=CANDLE_HOURS * query_history_bars)
    rows_by_asset: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for start in range(0, len(ids), ASSET_BATCH_SIZE):
        batch = ids[start : start + ASSET_BATCH_SIZE]
        placeholders = ",".join(["%s"] * len(batch))
        sql = f"""
        SELECT asset_id, close_ts_utc, open_price, high_price, low_price, close_price, volume_base
        FROM obs_market_candle
        WHERE venue=%s
          AND interval_code=%s
          AND close_ts_utc>%s
          AND close_ts_utc<=%s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id, close_ts_utc
        """
        params = (
            venue,
            CANDLE_INTERVAL,
            start_ts.replace(tzinfo=None),
            asof_ts_utc.replace(tzinfo=None),
            *batch,
        )
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        for row in rows:
            asset_id = int(row["asset_id"])
            close_ts = parse_ts(row["close_ts_utc"])
            rows_by_asset[asset_id].append(
                {
                    "market": market_by_asset[asset_id],
                    "interval": CANDLE_INTERVAL,
                    "start_ts": close_ts - timedelta(hours=CANDLE_HOURS),
                    "end_ts": close_ts,
                    "open": row["open_price"],
                    "high": row["high_price"],
                    "low": row["low_price"],
                    "close": row["close_price"],
                    "volume": row["volume_base"],
                    "is_final": True,
                }
            )
    return {asset_id: pd.DataFrame(rows) for asset_id, rows in rows_by_asset.items()}


def row_line(row: dict[str, Any]) -> str:
    return json.dumps(jsonable(row), sort_keys=True, separators=(",", ":")) + "\n"


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(jsonable(payload), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row_line(row))
        handle.flush()


def write_or_verify_jsonl(path: Path, rows: Iterable[dict[str, Any]], *, resume: bool) -> None:
    expected = "".join(row_line(row) for row in rows)
    if path.exists():
        if not resume or path.read_text(encoding="utf-8") != expected:
            raise ValueError(f"immutable artifact mismatch: {path}")
        return
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(expected, encoding="utf-8")
    tmp.replace(path)


def write_or_verify_json(path: Path, payload: dict[str, Any], *, resume: bool) -> None:
    expected = json.dumps(jsonable(payload), sort_keys=True, indent=2) + "\n"
    if path.exists():
        if not resume or path.read_text(encoding="utf-8") != expected:
            raise ValueError(f"immutable artifact mismatch: {path}")
        return
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(expected, encoding="utf-8")
    tmp.replace(path)


def load_checkpointed_rows(path: Path, rows_written: int) -> list[dict[str, Any]]:
    if rows_written < 0:
        raise ValueError("checkpoint candidate_rows_written must be non-negative")
    if rows_written == 0:
        if path.exists():
            path.write_text("", encoding="utf-8")
        return []
    if not path.exists():
        raise ValueError("checkpoint rows require candidate_observations.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < rows_written:
        raise ValueError("candidate_observations.jsonl shorter than checkpoint")
    rows = [json.loads(line) for line in lines[:rows_written]]
    path.write_text("".join(row_line(row) for row in rows), encoding="utf-8")
    return rows


def scope_identity(
    args: argparse.Namespace,
    *,
    selected: list[dict[str, Any]],
    asofs: list[datetime],
) -> dict[str, Any]:
    return {
        "runner": RUNNER_NAME,
        "contract_sha256": PINNED_CONTRACT_SHA256,
        "population_sha256": PINNED_POPULATION_SHA256,
        "outcomes_sha256": PINNED_OUTCOMES_SHA256,
        "venue": args.venue,
        "asof_index": args.asof_index,
        "asset_id": args.asset_id,
        "limit_observations": args.limit_observations,
        "selected_observations": len(selected),
        "selected_asofs": len(asofs),
        "selected_observation_ids_sha256": canonical_json_sha256(
            [str(row["observation_id"]) for row in selected]
        ),
    }


def prepare_output(
    output_dir: Path,
    *,
    args: argparse.Namespace,
    identity: dict[str, Any],
    candidate_filename: str,
) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
    candidate_path = output_dir / candidate_filename
    checkpoint_path = output_dir / "checkpoint.json"
    manifest_path = output_dir / "manifest.json"
    if args.resume:
        if not output_dir.exists() or not checkpoint_path.exists():
            raise ValueError("--resume requires existing output directory and checkpoint.json")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        for key, expected in identity.items():
            if checkpoint.get(key) != expected:
                raise ValueError(f"resume identity mismatch for {key}")
        completed = int(checkpoint.get("asofs_completed", 0))
        rows_written = int(checkpoint.get("candidate_rows_written", 0))
        if checkpoint.get("terminal_state") == "FINISHED" and not manifest_path.exists():
            raise ValueError("FINISHED checkpoint missing manifest.json")
        return checkpoint, completed, load_checkpointed_rows(candidate_path, rows_written)

    if output_dir.exists():
        raise ValueError(f"immutable output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    candidate_path.write_text("", encoding="utf-8")
    checkpoint = {
        **identity,
        "terminal_state": "RUNNING",
        "asofs_completed": 0,
        "candidate_rows_written": 0,
        "last_asof_ts_utc": None,
        "db_writes": 0,
    }
    atomic_json(checkpoint_path, checkpoint)
    return checkpoint, 0, []


def checkpoint_after_asof(
    output_dir: Path,
    *,
    identity: dict[str, Any],
    asofs_completed: int,
    candidate_rows_written: int,
    last_asof_ts_utc: datetime,
) -> None:
    atomic_json(
        output_dir / "checkpoint.json",
        {
            **identity,
            "terminal_state": "RUNNING",
            "asofs_completed": asofs_completed,
            "candidate_rows_written": candidate_rows_written,
            "last_asof_ts_utc": last_asof_ts_utc,
            "db_writes": 0,
        },
    )


def is_full_run(args: argparse.Namespace, selected_count: int, contract: dict[str, Any]) -> bool:
    return (
        args.asof_index is None
        and args.asset_id is None
        and args.limit_observations is None
        and selected_count == int(contract["source_population"]["row_count"])
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(Path(args.contract))
    population_path = Path(args.population)
    outcomes_path = Path(args.outcomes)
    population = load_population(population_path, contract)
    outcomes = load_outcomes(outcomes_path, contract)
    horizons = tuple(str(value) for value in contract["source_outcomes"]["horizons"])
    validate_outcome_coverage(population, outcomes, horizons)
    selected = select_population_rows(
        population,
        asof_index=args.asof_index,
        asset_id=args.asset_id,
        limit_observations=args.limit_observations,
    )

    asof_groups: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        if str(row["venue"]) != args.venue:
            raise ValueError("selected observation venue mismatch")
        asof_groups[parse_ts(row["asof_ts_utc"])].append(row)
    ordered_asofs = sorted(asof_groups)

    output_dir = Path(args.output_dir)
    identity = scope_identity(args, selected=selected, asofs=ordered_asofs)
    candidate_filename = str(contract["output"]["candidate_rows"])
    checkpoint, completed_asofs, candidate_rows = prepare_output(
        output_dir,
        args=args,
        identity=identity,
        candidate_filename=candidate_filename,
    )
    if checkpoint.get("terminal_state") == "FINISHED":
        return json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    if completed_asofs < 0 or completed_asofs > len(ordered_asofs):
        raise ValueError("invalid checkpoint asofs_completed")

    candidate_path = output_dir / candidate_filename
    conn = get_db_connection()
    try:
        market_by_asset = fetch_unique_market_map(
            conn,
            venue=args.venue,
            asset_ids=[int(row["asset_id"]) for row in selected],
        )
        for asof_index, asof in enumerate(ordered_asofs[completed_asofs:], start=completed_asofs + 1):
            observations = asof_groups[asof]
            candle_by_asset = fetch_candles_for_asof(
                conn,
                venue=args.venue,
                asof_ts_utc=asof,
                asset_ids=[int(row["asset_id"]) for row in observations],
                market_by_asset=market_by_asset,
                query_history_bars=int(contract["feature_contract"]["query_history_bars"]),
            )
            new_rows = [
                build_candidate_observation(
                    observation,
                    candle_frame=candle_by_asset.get(int(observation["asset_id"])),
                    market=market_by_asset.get(int(observation["asset_id"])),
                    contract=contract,
                )
                for observation in sorted(observations, key=lambda row: int(row["asset_id"]))
            ]
            append_jsonl(candidate_path, new_rows)
            candidate_rows.extend(new_rows)
            checkpoint_after_asof(
                output_dir,
                identity=identity,
                asofs_completed=asof_index,
                candidate_rows_written=len(candidate_rows),
                last_asof_ts_utc=asof,
            )
    finally:
        conn.close()

    if len(candidate_rows) != len(selected):
        raise ValueError(f"candidate row count mismatch expected={len(selected)} actual={len(candidate_rows)}")

    reports: dict[str, Any] = {}
    full_run = is_full_run(args, len(selected), contract)
    for horizon in horizons:
        validation_rows = [
            attach_outcome(row, horizon=horizon, outcome_by_key=outcomes, contract=contract)
            for row in candidate_rows
        ]
        validation_path = output_dir / f"validation_rows_{horizon}.jsonl"
        write_or_verify_jsonl(validation_path, validation_rows, resume=args.resume)
        if full_run:
            report = evaluate_incremental_features(
                pd.DataFrame(validation_rows),
                candidate_columns=tuple(contract["feature_contract"]["candidate_columns"]),
                baseline_columns=tuple(contract["baseline_contract"]["columns"]),
                outcome_column="forward_return_pct",
                split_column="split",
            )
            report_payload: dict[str, Any] = {"status": "COMPLETE", **asdict(report)}
        else:
            report_payload = {
                "status": "BOUNDED_SMOKE_NO_DVH_EVALUATION",
                "reason": "full frozen population required before split-complete evaluation",
            }
        report_path = output_dir / f"{contract['output']['report_prefix']}{horizon}.json"
        write_or_verify_json(report_path, report_payload, resume=args.resume)
        reports[horizon] = report_payload

    status_counts = Counter(str(row["candidate_status"]) for row in candidate_rows)
    manifest = {
        "runner": RUNNER_NAME,
        "contract_sha256": PINNED_CONTRACT_SHA256,
        "population_sha256": PINNED_POPULATION_SHA256,
        "outcomes_sha256": PINNED_OUTCOMES_SHA256,
        "candidate_rows_sha256": sha256_path(candidate_path),
        "validation_rows_sha256": {
            horizon: sha256_path(output_dir / f"validation_rows_{horizon}.jsonl")
            for horizon in horizons
        },
        "selected_observations": len(selected),
        "selected_asofs": len(asof_groups),
        "candidate_status_counts": dict(sorted(status_counts.items())),
        "candidate_model_id": CANDIDATE_MODEL_ID,
        "candidate_model_version": CANDIDATE_MODEL_VERSION,
        "baseline_identity": contract["baseline_contract"]["identity"],
        "baseline_columns": contract["baseline_contract"]["columns"],
        "candidate_columns": contract["feature_contract"]["candidate_columns"],
        "horizons": list(horizons),
        "full_frozen_run": int(full_run),
        "reports": reports,
        "db_writes": 0,
        "production_ranking_changes": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor_changes": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "live_activation": 0,
    }
    manifest_path = output_dir / str(contract["output"]["manifest"])
    write_or_verify_json(manifest_path, manifest, resume=args.resume)
    atomic_json(
        output_dir / "checkpoint.json",
        {
            **identity,
            "terminal_state": "FINISHED",
            "asofs_completed": len(ordered_asofs),
            "candidate_rows_written": len(candidate_rows),
            "last_asof_ts_utc": ordered_asofs[-1],
            "candidate_rows_sha256": manifest["candidate_rows_sha256"],
            "db_writes": 0,
        },
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    manifest = run(parse_args(argv))
    print(json.dumps(jsonable(manifest), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
