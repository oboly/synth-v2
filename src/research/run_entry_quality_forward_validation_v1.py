from __future__ import annotations

import argparse
import json
import signal
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
OUTPUT_CHECKPOINT = "checkpoint_v1.json"
HEARTBEAT_EVERY_OBSERVATIONS = 25

_STOP_REQUESTED = False
_STOP_SIGNAL: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay-safe forward outcome labels for CQ shadow observations"
    )
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--resume", action="store_true")
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


def _signal_handler(signum: int, _frame: Any) -> None:
    global _STOP_REQUESTED, _STOP_SIGNAL
    _STOP_REQUESTED = True
    try:
        _STOP_SIGNAL = signal.Signals(signum).name
    except ValueError:
        _STOP_SIGNAL = str(signum)


def _install_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[int(sig)] = signal.getsignal(sig)
        signal.signal(sig, _signal_handler)
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _checkpoint_path(output_dir: Path) -> Path:
    return output_dir / OUTPUT_CHECKPOINT


def load_checkpoint(output_dir: Path) -> dict[str, Any] | None:
    path = _checkpoint_path(output_dir)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("runner") != RUNNER_NAME:
        raise ValueError("Checkpoint runner mismatch")
    return raw


def write_checkpoint(
    output_dir: Path,
    *,
    registry: dict[str, Any],
    last_shadow_id: int | None,
    observations_completed: int,
    rows_written: int,
    terminal_state: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "runner": RUNNER_NAME,
        "registry_name": registry["registry_name"],
        "registry_version": registry["registry_version"],
        "last_shadow_id": last_shadow_id,
        "observations_completed": observations_completed,
        "rows_written": rows_written,
        "terminal_state": terminal_state,
        "updated_ts_utc": datetime.now(UTC),
    }
    _checkpoint_path(output_dir).write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def fetch_shadow_observations(
    conn,
    *,
    venue: str,
    asset_id: int | None,
    limit: int,
    after_shadow_id: int | None = None,
) -> list[dict[str, Any]]:
    filters = ["s.venue = %s"]
    params: list[Any] = [venue]
    if asset_id is not None:
        filters.append("s.asset_id = %s")
        params.append(asset_id)
    if after_shadow_id is not None:
        filters.append("s.shadow_id > %s")
        params.append(after_shadow_id)
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
    WHERE {' AND '.join(filters)}
    ORDER BY s.shadow_id
    LIMIT %s
    """
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    print(
        f"QUERY_END name=fetch_shadow_observations rows={len(rows)} elapsed_s={time.perf_counter() - started:.3f}",
        flush=True,
    )
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
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(base_sql, (asset_id, venue, observation_asof))
        base = cur.fetchone()
        cur.execute(future_sql, (asset_id, venue, observation_asof, horizon_end))
        future = cur.fetchall()
    print(
        f"QUERY_END name=fetch_candles asset_id={asset_id} future_rows={len(future)} "
        f"elapsed_s={time.perf_counter() - started:.3f}",
        flush=True,
    )

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


def build_rows_for_observation(
    conn,
    *,
    observation: dict[str, Any],
    venue: str,
    horizons: list[HorizonSpec],
) -> list[dict[str, Any]]:
    max_horizon = max((item.delta for item in horizons), default=timedelta(0))
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
    out: list[dict[str, Any]] = []
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


def _append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=json_default) + "\n")


def _read_existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_summary(output_dir: Path, rows: list[dict[str, Any]], registry: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    status_counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['horizon']}:{row['status']}"
        status_counts[key] = status_counts.get(key, 0) + 1
    summary = {
        "runner": RUNNER_NAME,
        "registry_name": registry["registry_name"],
        "registry_version": registry["registry_version"],
        "row_count": len(rows),
        "observation_count": len({int(row["shadow_id"]) for row in rows}),
        "status_counts": status_counts,
        "target_outcomes": "UNAVAILABLE_NO_CANONICAL_TARGET_PRICE",
        "production_ranking_changed": False,
    }
    (output_dir / OUTPUT_SUMMARY).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> int:
    global _STOP_REQUESTED, _STOP_SIGNAL
    _STOP_REQUESTED = False
    _STOP_SIGNAL = None
    started = time.perf_counter()
    previous_handlers = _install_signal_handlers()
    output_dir = Path(args.output_dir)
    rows_path = output_dir / OUTPUT_ROWS
    print(f"STARTED runner={RUNNER_NAME} mode=research-read-only", flush=True)
    print(
        "SAFETY research_only=1 market_only=1 db_writes=0 production_ranking_changes=0 "
        "decision_gate=none execution_planner=none executor=none broker_writes=0 orders=0",
        flush=True,
    )
    conn = None
    observations_completed = 0
    rows_written = 0
    last_shadow_id: int | None = None
    try:
        registry, horizons = load_registry(args.registry)
        checkpoint = load_checkpoint(output_dir) if args.resume else None
        after_shadow_id = None
        if checkpoint is not None:
            if checkpoint.get("registry_version") != registry["registry_version"]:
                raise ValueError("Checkpoint registry version mismatch")
            after_shadow_id = checkpoint.get("last_shadow_id")
            print(
                f"RESUME checkpoint={_checkpoint_path(output_dir)} after_shadow_id={after_shadow_id}",
                flush=True,
            )
        elif rows_path.exists():
            rows_path.unlink()

        conn = get_db_connection()
        print("PHASE_START name=fetch_shadow_observations", flush=True)
        phase_started = time.perf_counter()
        observations = fetch_shadow_observations(
            conn,
            venue=args.venue,
            asset_id=args.asset_id,
            limit=args.limit,
            after_shadow_id=(None if after_shadow_id is None else int(after_shadow_id)),
        )
        print(
            f"PHASE_END name=fetch_shadow_observations rows={len(observations)} "
            f"elapsed_s={time.perf_counter() - phase_started:.3f}",
            flush=True,
        )

        print("PHASE_START name=label_forward_outcomes", flush=True)
        phase_started = time.perf_counter()
        for observation in observations:
            if _STOP_REQUESTED:
                break
            per_observation = build_rows_for_observation(
                conn,
                observation=observation,
                venue=args.venue,
                horizons=horizons,
            )
            _append_rows(rows_path, per_observation)
            observations_completed += 1
            rows_written += len(per_observation)
            last_shadow_id = int(observation["shadow_id"])
            write_checkpoint(
                output_dir,
                registry=registry,
                last_shadow_id=last_shadow_id,
                observations_completed=observations_completed,
                rows_written=rows_written,
                terminal_state="RUNNING",
            )
            if observations_completed % HEARTBEAT_EVERY_OBSERVATIONS == 0:
                print(
                    f"HEARTBEAT phase=label_forward_outcomes observations_completed={observations_completed} "
                    f"rows_written={rows_written} last_shadow_id={last_shadow_id} "
                    f"elapsed_s={time.perf_counter() - phase_started:.3f}",
                    flush=True,
                )
        print(
            f"PHASE_END name=label_forward_outcomes observations_completed={observations_completed} "
            f"rows_written={rows_written} elapsed_s={time.perf_counter() - phase_started:.3f}",
            flush=True,
        )

        all_rows = _read_existing_rows(rows_path)
        print(f"PHASE_START name=write_summary output_dir={args.output_dir}", flush=True)
        phase_started = time.perf_counter()
        write_summary(output_dir, all_rows, registry)
        print(
            f"PHASE_END name=write_summary rows={len(all_rows)} "
            f"elapsed_s={time.perf_counter() - phase_started:.3f}",
            flush=True,
        )

        if _STOP_REQUESTED:
            write_checkpoint(
                output_dir,
                registry=registry,
                last_shadow_id=last_shadow_id,
                observations_completed=observations_completed,
                rows_written=rows_written,
                terminal_state="INTERRUPTED",
            )
            print(
                f"INTERRUPTED runner={RUNNER_NAME} signal={_STOP_SIGNAL} "
                f"observations_completed={observations_completed} rows_written={rows_written} "
                f"checkpoint={_checkpoint_path(output_dir)} elapsed_s={time.perf_counter() - started:.3f}",
                flush=True,
            )
            return 130

        write_checkpoint(
            output_dir,
            registry=registry,
            last_shadow_id=last_shadow_id,
            observations_completed=observations_completed,
            rows_written=rows_written,
            terminal_state="FINISHED",
        )
        print(
            f"FINISHED runner={RUNNER_NAME} observations={observations_completed} rows={len(all_rows)} "
            f"production_ranking_changed=0 elapsed_s={time.perf_counter() - started:.3f}",
            flush=True,
        )
        return 0
    except Exception as exc:
        print(
            f"FAILED runner={RUNNER_NAME} reason={type(exc).__name__}:{exc} db_writes=0 "
            f"checkpoint={_checkpoint_path(output_dir)} elapsed_s={time.perf_counter() - started:.3f}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
        _restore_signal_handlers(previous_handlers)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
