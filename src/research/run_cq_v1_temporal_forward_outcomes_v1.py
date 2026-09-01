from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
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
OUTPUT_CHECKPOINT = "checkpoint.json"
CHECKPOINT_VERSION = "1.0.0"
HORIZON_MINUTES = (("1h", 60), ("4h", 240), ("24h", 1440))
WORKER_COUNT = 1


class _Interrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"signal={signum}")
        self.signum = signum


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
    p.add_argument("--resume", action="store_true")
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
        if str(row["venue"]) != venue:
            raise ValueError(f"population venue mismatch observation={row['venue']} requested={venue}")
        by_asof[parse_ts(row["asof_ts_utc"])].append(row)
    if len(by_asof) != 1:
        raise ValueError("build_outcome_rows requires exactly one as-of batch")
    asof = next(iter(by_asof))
    scoped = by_asof[asof]
    max_horizon = max(item.delta for item in horizons)
    candle_map = fetch_candles_for_asof_assets(
        conn,
        asset_ids=[int(row["asset_id"]) for row in scoped],
        venue=venue,
        observation_asof=asof,
        max_horizon=max_horizon,
    )
    out: list[dict[str, Any]] = []
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


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(_jsonable(payload), sort_keys=True, indent=2) + "\n")


def artifact_paths(output_dir: Path) -> tuple[Path, Path, Path, Path]:
    return (
        output_dir / OUTPUT_ROWS,
        output_dir / OUTPUT_SUMMARY,
        output_dir / OUTPUT_MANIFEST,
        output_dir / OUTPUT_CHECKPOINT,
    )


def _scope_identity(args: argparse.Namespace, *, asof_total: int) -> dict[str, Any]:
    return {
        "runner": RUNNER_NAME,
        "checkpoint_version": CHECKPOINT_VERSION,
        "venue": args.venue,
        "population_sha256": PINNED_POPULATION_SHA256,
        "outcome_contract_sha256": PINNED_CONTRACT_SHA256,
        "asof_index": args.asof_index,
        "asset_id": args.asset_id,
        "horizon": args.horizon,
        "limit_observations": args.limit_observations,
        "asof_total": asof_total,
    }


def _validate_checkpoint(checkpoint: dict[str, Any], identity: dict[str, Any]) -> None:
    for key, expected in identity.items():
        if checkpoint.get(key) != expected:
            raise ValueError(
                f"resume identity mismatch for {key}: checkpoint={checkpoint.get(key)!r} expected={expected!r}"
            )


def _row_line(row: dict[str, Any]) -> bytes:
    return (json.dumps(_jsonable(row), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _load_checkpointed_rows(path: Path, rows_written: int) -> list[dict[str, Any]]:
    if rows_written < 0:
        raise ValueError("checkpoint outcome_rows_written must be non-negative")
    if rows_written == 0:
        if path.exists():
            path.write_bytes(b"")
        return []
    if not path.exists():
        raise ValueError("checkpoint rows require forward_outcomes.jsonl")
    raw_lines = path.read_bytes().splitlines()
    if len(raw_lines) < rows_written:
        raise ValueError("forward_outcomes.jsonl shorter than checkpoint rows")
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_lines[:rows_written], start=1):
        try:
            row = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"malformed checkpointed outcome row {index}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"checkpointed outcome row {index} is not an object")
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        for row in rows:
            handle.write(_row_line(row))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return rows


def _append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        for row in rows:
            handle.write(_row_line(row))
        handle.flush()
        os.fsync(handle.fileno())


def _prepare_output(
    output_dir: Path,
    *,
    args: argparse.Namespace,
    asof_total: int,
) -> tuple[dict[str, Any], int, int]:
    rows_path, summary_path, manifest_path, checkpoint_path = artifact_paths(output_dir)
    identity = _scope_identity(args, asof_total=asof_total)
    if args.resume:
        if not output_dir.exists() or not checkpoint_path.exists():
            raise ValueError("--resume requires existing output directory and checkpoint.json")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(checkpoint, dict):
            raise ValueError("checkpoint must be a JSON object")
        _validate_checkpoint(checkpoint, identity)
        completed = int(checkpoint.get("asofs_completed", 0))
        rows_written = int(checkpoint.get("outcome_rows_written", 0))
        if completed < 0 or completed > asof_total:
            raise ValueError("invalid checkpoint asofs_completed")
        if checkpoint.get("terminal_state") == "FINISHED":
            if not rows_path.exists() or not summary_path.exists() or not manifest_path.exists():
                raise ValueError("FINISHED checkpoint missing immutable artifacts")
            expected_sha = checkpoint.get("outcomes_sha256")
            if expected_sha != _sha256_path(rows_path):
                raise ValueError("FINISHED outcome SHA256 mismatch")
            return checkpoint, completed, rows_written
        if summary_path.exists() or manifest_path.exists():
            raise ValueError("non-finished checkpoint must not have final summary/manifest")
        _load_checkpointed_rows(rows_path, rows_written)
        return checkpoint, completed, rows_written
    if output_dir.exists():
        raise ValueError(f"immutable outcome output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    checkpoint = {
        **identity,
        "terminal_state": "RUNNING",
        "resumable": 1,
        "asofs_completed": 0,
        "outcome_rows_written": 0,
        "last_asof_ts_utc": None,
        "db_writes": 0,
    }
    _atomic_json(checkpoint_path, checkpoint)
    return checkpoint, 0, 0


def _write_terminal_checkpoint(
    output_dir: Path,
    *,
    identity: dict[str, Any],
    terminal_state: str,
    asofs_completed: int,
    outcome_rows_written: int,
    last_asof_ts_utc: str | None,
    signal_number: int | None = None,
) -> None:
    payload = {
        **identity,
        "terminal_state": terminal_state,
        "resumable": 1,
        "asofs_completed": asofs_completed,
        "outcome_rows_written": outcome_rows_written,
        "last_asof_ts_utc": last_asof_ts_utc,
        "db_writes": 0,
    }
    if signal_number is not None:
        payload["signal"] = signal_number
    _atomic_json(output_dir / OUTPUT_CHECKPOINT, payload)


def _has_durable_checkpoint(output_dir: Path) -> bool:
    checkpoint_path = output_dir / OUTPUT_CHECKPOINT
    if not checkpoint_path.exists():
        return False
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(checkpoint, dict)
        and checkpoint.get("runner") == RUNNER_NAME
        and checkpoint.get("checkpoint_version") == CHECKPOINT_VERSION
        and checkpoint.get("terminal_state") in {"RUNNING", "INTERRUPTED", "FAILED", "FINISHED"}
        and type(checkpoint.get("resumable")) is int
        and checkpoint["resumable"] in (0, 1)
        and type(checkpoint.get("asofs_completed")) is int
        and checkpoint["asofs_completed"] >= 0
        and type(checkpoint.get("outcome_rows_written")) is int
        and checkpoint["outcome_rows_written"] >= 0
        and checkpoint.get("db_writes") == 0
    )


def _finalize(
    output_dir: Path,
    *,
    identity: dict[str, Any],
    observation_count: int,
    asofs_completed: int,
    outcome_rows_written: int,
    last_asof_ts_utc: str | None,
) -> str:
    rows_path, summary_path, manifest_path, checkpoint_path = artifact_paths(output_dir)
    rows = _load_checkpointed_rows(rows_path, outcome_rows_written)
    ids = [str(row["outcome_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate temporal outcome identity in final artifact")
    outcomes_sha = _sha256_path(rows_path)
    status_counts = Counter(f"{row['horizon']}:{row['status']}" for row in rows)
    summary = {
        "runner": RUNNER_NAME,
        "terminal_state": "FINISHED",
        "observation_count": observation_count,
        "outcome_row_count": len(rows),
        "unique_outcome_ids": len(set(ids)),
        "status_counts": dict(sorted(status_counts.items())),
        "population_sha256": PINNED_POPULATION_SHA256,
        "outcome_contract_sha256": PINNED_CONTRACT_SHA256,
        "outcomes_sha256": outcomes_sha,
        "db_writes": 0,
        "production_ranking_changes": 0,
    }
    _atomic_json(summary_path, summary)
    manifest = {
        "runner": RUNNER_NAME,
        "issue": 684,
        "parent_issue": 568,
        "population_sha256": PINNED_POPULATION_SHA256,
        "outcome_contract_path": DEFAULT_CONTRACT,
        "outcome_contract_sha256": PINNED_CONTRACT_SHA256,
        "outcomes_file": OUTPUT_ROWS,
        "outcomes_sha256": outcomes_sha,
        "summary_sha256": _sha256_path(summary_path),
        "db_writes": 0,
        "broker_writes": 0,
        "production_ranking_changes": 0,
    }
    _atomic_json(manifest_path, manifest)
    checkpoint = {
        **identity,
        "terminal_state": "FINISHED",
        "resumable": 0,
        "asofs_completed": asofs_completed,
        "outcome_rows_written": outcome_rows_written,
        "last_asof_ts_utc": last_asof_ts_utc,
        "outcomes_sha256": outcomes_sha,
        "db_writes": 0,
    }
    _atomic_json(checkpoint_path, checkpoint)
    return outcomes_sha


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    mode = "RESUME" if args.resume else "FRESH"
    print(
        f"STARTED runner={RUNNER_NAME} mode={mode} research_read_only=1 workers={WORKER_COUNT} venue={args.venue} "
        f"asof_index={args.asof_index} asset_id={args.asset_id} horizon={args.horizon} limit={args.limit_observations}",
        flush=True,
    )
    print(
        "SAFETY research_only=1 market_only=1 account_awareness=0 db_writes=0 model_retuning=0 "
        "production_ranking_changes=0 decision_gate=none execution_planner=none executor=none "
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 runtime_activation=0",
        flush=True,
    )
    output_dir = Path(args.output_dir)
    conn = None
    previous_handlers: dict[int, Any] = {}
    asofs_completed = 0
    outcome_rows_written = 0
    last_asof_ts_utc: str | None = None
    identity: dict[str, Any] | None = None
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda sig, _frame: (_ for _ in ()).throw(_Interrupted(sig)))
        contract, horizons = load_contract(args.contract)
        observations = select_population_rows(load_population(Path(args.population), contract), args)
        if args.horizon is not None:
            horizons = [item for item in horizons if item.label == args.horizon]
        grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            grouped[parse_ts(row["asof_ts_utc"])].append(row)
        asofs = sorted(grouped)
        identity = _scope_identity(args, asof_total=len(asofs))
        checkpoint, asofs_completed, outcome_rows_written = _prepare_output(
            output_dir, args=args, asof_total=len(asofs)
        )
        last_asof_ts_utc = checkpoint.get("last_asof_ts_utc")
        if checkpoint.get("terminal_state") == "FINISHED":
            print(
                f"FINISHED runner={RUNNER_NAME} resume_noop=1 observations={len(observations)} "
                f"outcome_rows={outcome_rows_written} outcomes_sha256={checkpoint.get('outcomes_sha256')} "
                f"db_writes=0 elapsed_s={time.monotonic() - started:.3f}",
                flush=True,
            )
            return 0
        print(
            f"BOUND observations={len(observations)} unique_asofs={len(asofs)} horizons={','.join(item.label for item in horizons)} "
            f"resume_from_asof={asofs_completed} population_sha256={PINNED_POPULATION_SHA256}",
            flush=True,
        )
        conn = get_db_connection()
        rows_path = output_dir / OUTPUT_ROWS
        for zero_index in range(asofs_completed, len(asofs)):
            asof = asofs[zero_index]
            scoped = sorted(grouped[asof], key=lambda row: (int(row["asset_id"]), str(row["observation_id"])))
            print(
                f"QUERY phase=outcome_labels status=started index={zero_index + 1}/{len(asofs)} asof={asof.isoformat()} "
                f"observations={len(scoped)}",
                flush=True,
            )
            rows = build_outcome_rows(conn, observations=scoped, venue=args.venue, horizons=horizons)
            _append_rows(rows_path, rows)
            outcome_rows_written += len(rows)
            asofs_completed = zero_index + 1
            last_asof_ts_utc = asof.isoformat()
            _write_terminal_checkpoint(
                output_dir,
                identity=identity,
                terminal_state="RUNNING",
                asofs_completed=asofs_completed,
                outcome_rows_written=outcome_rows_written,
                last_asof_ts_utc=last_asof_ts_utc,
            )
            print(
                f"ASOF index={asofs_completed}/{len(asofs)} asof={asof.isoformat()} rows={len(rows)} "
                f"total_rows={outcome_rows_written}",
                flush=True,
            )
        outcomes_sha = _finalize(
            output_dir,
            identity=identity,
            observation_count=len(observations),
            asofs_completed=asofs_completed,
            outcome_rows_written=outcome_rows_written,
            last_asof_ts_utc=last_asof_ts_utc,
        )
        print(
            f"FINISHED runner={RUNNER_NAME} observations={len(observations)} outcome_rows={outcome_rows_written} "
            f"outcomes_sha256={outcomes_sha} db_writes=0 elapsed_s={time.monotonic() - started:.3f}",
            flush=True,
        )
        return 0
    except _Interrupted as exc:
        resumable = _has_durable_checkpoint(output_dir)
        if resumable and identity is not None:
            _write_terminal_checkpoint(
                output_dir,
                identity=identity,
                terminal_state="INTERRUPTED",
                asofs_completed=asofs_completed,
                outcome_rows_written=outcome_rows_written,
                last_asof_ts_utc=last_asof_ts_utc,
                signal_number=exc.signum,
            )
        print(
            f"INTERRUPTED runner={RUNNER_NAME} signal={exc.signum} resumable={int(resumable)} asofs_completed={asofs_completed} "
            f"outcome_rows={outcome_rows_written} db_writes=0 elapsed_s={time.monotonic() - started:.3f}",
            flush=True,
        )
        return 130
    except Exception as exc:
        resumable = _has_durable_checkpoint(output_dir)
        if resumable and identity is not None:
            _write_terminal_checkpoint(
                output_dir,
                identity=identity,
                terminal_state="FAILED",
                asofs_completed=asofs_completed,
                outcome_rows_written=outcome_rows_written,
                last_asof_ts_utc=last_asof_ts_utc,
            )
        print(
            f"FAILED runner={RUNNER_NAME} error={type(exc).__name__}:{exc} resumable={int(resumable)} "
            f"asofs_completed={asofs_completed} outcome_rows={outcome_rows_written} db_writes=0 "
            f"elapsed_s={time.monotonic() - started:.3f}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
