from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.research.cq_v1_temporal_population_v1 import (
    DEFAULT_SELECTION_CONFIG,
    build_asof_population,
    canonical_json_sha256,
    load_temporal_contract,
    summarize_population,
)
from src.research.cq_v1_temporal_sampling_v1 import derive_asofs
from src.selection.selection_engine_v2 import load_selection_config

RUNNER_NAME = "cq_v1_temporal_population_v1"
DEFAULT_OUTPUT_DIR = "data/research/cq_v1_temporal_population_v1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build frozen 45-date PIT CQ v1 temporal population")
    p.add_argument("--venue", default="bitvavo")
    p.add_argument("--selection-config", default=DEFAULT_SELECTION_CONFIG)
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return p.parse_args(argv)


def _safe_output_dir(raw: str) -> Path:
    root = Path("data/research").resolve()
    path = Path(raw).resolve()
    if path != root and root not in path.parents:
        raise ValueError("output path must remain under data/research/")
    return path


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(type(value).__name__)


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, sort_keys=True, indent=2, default=_json_default) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(data)
        tmp = Path(handle.name)
    os.replace(tmp, path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        for row in rows:
            line = (json.dumps(row, sort_keys=True, separators=(",", ":"), default=_json_default) + "\n").encode("utf-8")
            hasher.update(line)
            handle.write(line)
    os.replace(tmp, path)
    return hasher.hexdigest()


def run(args: argparse.Namespace) -> int:
    print(f"STARTED runner={RUNNER_NAME} venue={args.venue}", flush=True)
    print(
        "SAFETY research_only=1 market_only=1 account_awareness=0 outcomes_read=0 db_writes=0 "
        "model_retuning=0 production_ranking_changes=0 decision_gate=none execution_planner=none "
        "executor=none broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 runtime_activation=0",
        flush=True,
    )
    out_dir = _safe_output_dir(args.output_dir)
    contract = load_temporal_contract()
    asofs = derive_asofs(contract)
    if len(asofs) != 45:
        raise RuntimeError("frozen temporal contract did not derive exactly 45 as-ofs")
    contract_sha = canonical_json_sha256(contract)
    config = load_selection_config(args.selection_config)

    conn = None
    try:
        conn = get_db_connection()
        rows: list[dict[str, Any]] = []
        for index, asof in enumerate(asofs, start=1):
            asof_rows = build_asof_population(
                conn,
                contract=contract,
                asof_ts_utc=asof,
                venue=args.venue,
                selection_config=config,
            )
            rows.extend(asof_rows)
            print(f"ASOF index={index}/45 ts={asof.isoformat()} rows={len(asof_rows)}", flush=True)

        unique_asofs = {row["asof_ts_utc"] for row in rows}
        if unique_asofs != {asof.isoformat() for asof in asofs}:
            raise RuntimeError("population does not contain exactly the frozen 45 as-of timestamps")
        observation_ids = [str(row["observation_id"]) for row in rows]
        if len(observation_ids) != len(set(observation_ids)):
            raise RuntimeError("duplicate temporal observation identity")

        population_path = out_dir / "population.jsonl"
        population_sha = _write_jsonl(population_path, rows)
        summary = summarize_population(rows)
        summary.update({
            "runner": RUNNER_NAME,
            "venue": args.venue,
            "contract_sha256": contract_sha,
            "population_sha256": population_sha,
            "expected_unique_asof_count": 45,
            "forward_outcomes_read": 0,
            "db_writes": 0,
        })
        _atomic_json(out_dir / "summary.json", summary)
        manifest = {
            "runner": RUNNER_NAME,
            "issue": 651,
            "parent_issue": 568,
            "contract_path": "config/research/cq_v1_temporal_sampling_v1.json",
            "contract_sha256": contract_sha,
            "selection_config_path": args.selection_config,
            "population_file": population_path.name,
            "population_sha256": population_sha,
            "summary_sha256": hashlib.sha256((out_dir / "summary.json").read_bytes()).hexdigest(),
            "outcomes_read": 0,
            "database_writes": 0,
        }
        _atomic_json(out_dir / "manifest.json", manifest)
        print(
            f"FINISHED runner={RUNNER_NAME} rows={summary['row_count']} unique_assets={summary['unique_asset_count']} "
            f"unique_asofs={summary['unique_asof_count']} population_sha256={population_sha}",
            flush=True,
        )
        return 0
    except Exception as exc:
        print(f"FAILED runner={RUNNER_NAME} error={type(exc).__name__}:{exc}", flush=True)
        raise
    finally:
        if conn is not None:
            conn.close()


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
