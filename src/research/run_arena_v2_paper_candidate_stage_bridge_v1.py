from __future__ import annotations

# Synth v2 - Arena V2 Paper Candidate Stage Bridge V1.
#
# LAYER:
# research / paper-candidate staging bridge
#
# BOUNDARY:
# Allowed:
# - read historical arena/eval rows
# - apply explicit market-only arena candidate filters
# - export paper candidate contract JSONL
# - validate ResearchPaperCandidateV1 payloads
#
# Forbidden:
# - account balances
# - live positions
# - open orders
# - execution plans
# - decision_gate writes
# - execution_intent writes
# - execution_plan writes
# - broker/order actions
# - live trading
#
# Purpose:
# Convert a validated arena-v2 research candidate into transport-safe
# paper_candidate_contract_v1 JSONL rows that can be handed to
# run_paper_candidate_stage_writer_v1.

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.paper_candidate_contract_v1 import (
    CONTRACT_VERSION,
    ResearchPaperCandidateV1,
    require_valid_candidate,
)


BT_DB = "synth_bt"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v2"
DEFAULT_POLICY_NAME = "swing_pullback_recovery_v5_24h_tactical"
DEFAULT_POLICY_VERSION = "arena_v2_bridge_v1"
DEFAULT_CANDIDATE_STATE = "RESEARCH_PROMOTION_CANDIDATE"


@dataclass(frozen=True)
class ColumnMap:
    timestamp_col: str
    source_id_col: str
    horizon_mode: str
    return_col: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export arena-v2/eval rows as paper_candidate_contract_v1 JSONL."
    )
    parser.add_argument("--database", default=BT_DB)
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--venue", default="bitvavo")

    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    parser.add_argument("--policy-version", default=DEFAULT_POLICY_VERSION)
    parser.add_argument("--candidate-state", default=DEFAULT_CANDIDATE_STATE)

    parser.add_argument("--hold-hours", type=int, default=24)
    parser.add_argument("--max-per-snapshot", type=int, default=1)
    parser.add_argument("--cooldown-hours", type=int, default=48)
    parser.add_argument("--rank-max", type=int, default=10)
    parser.add_argument("--btc-min", default="-0.02")
    parser.add_argument("--btc-max", default="0.00")
    parser.add_argument("--min-score", default="0.52")
    parser.add_argument("--score-notch-mode", choices=("exclude", "include"), default="exclude")

    parser.add_argument("--selection-state", default="WATCHLIST")
    parser.add_argument("--rotation-bucket", default="ROTATION_EARLY")
    parser.add_argument("--classification-code", default="PULLBACK_WATCH")
    parser.add_argument("--execution-regime-label", default="TREND_UP")
    parser.add_argument("--sleeve-fit-code", default="TACTICAL_PULSE")

    parser.add_argument("--limit-rows", type=int, default=None)
    parser.add_argument("--output", choices=("summary", "jsonl"), default="summary")
    parser.add_argument("--output-file", default=None)
    return parser.parse_args()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def table_name(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError(f"Unsafe table name: {value}")
    return value


def fetch_columns(*, database: str, eval_table: str) -> set[str]:
    safe_table = table_name(eval_table)
    with get_connection(database=database) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SHOW COLUMNS FROM {safe_table}")
            return {str(row["Field"]) for row in cur.fetchall() or []}


def first_existing(columns: set[str], names: list[str], *, required: bool = True) -> str | None:
    for name in names:
        if name in columns:
            return name
    if required:
        raise ValueError(f"None of these columns exist: {names}. Available: {sorted(columns)}")
    return None


def build_column_map(columns: set[str], hold_hours: int) -> ColumnMap:
    timestamp_col = str(first_existing(columns, ["replay_asof_ts_utc", "asof_ts_utc", "signal_ts_utc"]))

    source_id_col = str(
        first_existing(
            columns,
            [
                "replay_id",
                "source_replay_id",
                "bt_selection_v2_replay_id",
                "selection_replay_id",
                "eval_id",
                "id",
            ],
        )
    )

    if "simulated_horizon_hours" in columns and "simulated_net_return" in columns:
        return ColumnMap(
            timestamp_col=timestamp_col,
            source_id_col=source_id_col,
            horizon_mode="row",
            return_col="simulated_net_return",
        )

    return_col = str(
        first_existing(
            columns,
            [
                f"simulated_net_return_{hold_hours}h",
                f"net_return_{hold_hours}h",
                f"return_{hold_hours}h",
                f"ret_{hold_hours}h",
                f"future_return_{hold_hours}h",
                f"fwd_return_{hold_hours}h",
                f"return_h{hold_hours}",
                f"ret_h{hold_hours}",
            ],
        )
    )

    return ColumnMap(
        timestamp_col=timestamp_col,
        source_id_col=source_id_col,
        horizon_mode="column",
        return_col=return_col,
    )


def build_fetch_sql(
    *,
    eval_table: str,
    columns: set[str],
    column_map: ColumnMap,
    args: argparse.Namespace,
) -> tuple[str, dict[str, Any]]:
    safe_table = table_name(eval_table)

    required_columns = [
        "asset_id",
        "symbol",
        "venue",
        "priority_rank",
        "selection_score",
        "btc_prior_24h",
    ]
    for col in required_columns:
        if col not in columns:
            raise ValueError(f"Required column missing in {safe_table}: {col}")

    filters = [
        f"venue = %(venue)s",
        f"{column_map.timestamp_col} >= %(from_ts)s",
        f"{column_map.timestamp_col} < %(to_ts)s",
        "priority_rank IS NOT NULL",
        "priority_rank <= %(rank_max)s",
        "selection_score IS NOT NULL",
        "selection_score >= %(min_score)s",
        "btc_prior_24h IS NOT NULL",
        "btc_prior_24h >= %(btc_min)s",
        "btc_prior_24h <= %(btc_max)s",
    ]

    params: dict[str, Any] = {
        "venue": args.venue,
        "from_ts": parse_ts(args.from_ts),
        "to_ts": parse_ts(args.to_ts),
        "rank_max": int(args.rank_max),
        "min_score": Decimal(str(args.min_score)),
        "btc_min": Decimal(str(args.btc_min)),
        "btc_max": Decimal(str(args.btc_max)),
    }

    if column_map.horizon_mode == "row":
        filters.append("simulated_horizon_hours = %(hold_hours)s")
        filters.append("simulated_net_return IS NOT NULL")
        params["hold_hours"] = int(args.hold_hours)
    else:
        filters.append(f"{column_map.return_col} IS NOT NULL")

    optional_exact_filters = [
        ("selection_state", args.selection_state),
        ("rotation_bucket", args.rotation_bucket),
        ("classification_code", args.classification_code),
    ]

    for col, value in optional_exact_filters:
        if col in columns and value:
            filters.append(f"{col} = %({col})s")
            params[col] = value

    if args.score_notch_mode == "exclude":
        filters.append(
            "NOT (priority_rank BETWEEN 4 AND 6 "
            "AND selection_score >= 0.50 "
            "AND selection_score < 0.52)"
        )

    limit_sql = ""
    if args.limit_rows is not None:
        limit_sql = "LIMIT %(limit_rows)s"
        params["limit_rows"] = int(args.limit_rows)

    sql = f"""
        SELECT *
        FROM {safe_table}
        WHERE {" AND ".join(filters)}
        ORDER BY
            {column_map.timestamp_col} ASC,
            priority_rank ASC,
            selection_score DESC,
            asset_id ASC
        {limit_sql}
    """
    return sql, params


def fetch_candidate_source_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], ColumnMap, set[str]]:
    columns = fetch_columns(database=args.database, eval_table=args.eval_table)
    column_map = build_column_map(columns, int(args.hold_hours))
    sql, params = build_fetch_sql(
        eval_table=args.eval_table,
        columns=columns,
        column_map=column_map,
        args=args,
    )

    with get_connection(database=args.database) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []

    return list(rows), column_map, columns


def row_timestamp(row: dict[str, Any], column_map: ColumnMap) -> datetime:
    value = row[column_map.timestamp_col]
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return parse_ts(str(value))


def apply_snapshot_and_cooldown(
    rows: list[dict[str, Any]],
    *,
    column_map: ColumnMap,
    max_per_snapshot: int,
    cooldown_hours: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    snapshot_counts: dict[datetime, int] = {}
    last_symbol_ts: dict[str, datetime] = {}
    cooldown = timedelta(hours=int(cooldown_hours))

    for row in rows:
        ts = row_timestamp(row, column_map)
        symbol = str(row["symbol"])

        if snapshot_counts.get(ts, 0) >= int(max_per_snapshot):
            continue

        previous_ts = last_symbol_ts.get(symbol)
        if previous_ts is not None and ts < previous_ts + cooldown:
            continue

        selected.append(row)
        snapshot_counts[ts] = snapshot_counts.get(ts, 0) + 1
        last_symbol_ts[symbol] = ts

    return selected


def value_or_default(row: dict[str, Any], key: str, default: Any) -> Any:
    value = row.get(key)
    if value is None:
        return default
    return value


def simulated_return(row: dict[str, Any], column_map: ColumnMap) -> Decimal | None:
    return parse_decimal(row.get(column_map.return_col))


def source_replay_id(row: dict[str, Any], column_map: ColumnMap) -> int:
    value = row.get(column_map.source_id_col)
    if value is None:
        raise ValueError(f"Missing source id column value: {column_map.source_id_col}")
    return int(value)


def build_notes(args: argparse.Namespace) -> str:
    return (
        "arena_v2_bridge_v1; "
        f"hold_hours={args.hold_hours}; "
        f"max_per_snapshot={args.max_per_snapshot}; "
        f"cooldown_hours={args.cooldown_hours}; "
        f"rank_max={args.rank_max}; "
        f"btc_prior_24h={args.btc_min}..{args.btc_max}; "
        f"min_score={args.min_score}; "
        f"score_notch_mode={args.score_notch_mode}; "
        "paper_only=true"
    )


def row_to_candidate(
    row: dict[str, Any],
    *,
    args: argparse.Namespace,
    column_map: ColumnMap,
) -> ResearchPaperCandidateV1:
    candidate = ResearchPaperCandidateV1(
        contract_version=CONTRACT_VERSION,
        policy_name=str(args.policy_name),
        policy_version=str(args.policy_version),
        candidate_state=str(args.candidate_state),
        asset_id=int(row["asset_id"]),
        symbol=str(row["symbol"]),
        venue=str(row["venue"]),
        asof_ts_utc=row_timestamp(row, column_map),
        selection_state=str(value_or_default(row, "selection_state", args.selection_state)),
        priority_rank=int(row["priority_rank"]),
        selection_score=parse_decimal(row.get("selection_score")),
        btc_prior_24h=parse_decimal(row.get("btc_prior_24h")),
        rotation_bucket=str(value_or_default(row, "rotation_bucket", args.rotation_bucket)),
        classification_code=str(value_or_default(row, "classification_code", args.classification_code)),
        execution_regime_label=str(value_or_default(row, "execution_regime_label", args.execution_regime_label)),
        sleeve_fit_code=str(args.sleeve_fit_code),
        simulated_horizon_hours=int(args.hold_hours),
        simulated_net_return=simulated_return(row, column_map),
        source_table=str(args.eval_table),
        source_replay_id=source_replay_id(row, column_map),
        notes=build_notes(args),
    )
    require_valid_candidate(candidate)
    return candidate


def build_candidates(
    rows: list[dict[str, Any]],
    *,
    args: argparse.Namespace,
    column_map: ColumnMap,
) -> list[ResearchPaperCandidateV1]:
    selected_rows = apply_snapshot_and_cooldown(
        rows,
        column_map=column_map,
        max_per_snapshot=int(args.max_per_snapshot),
        cooldown_hours=int(args.cooldown_hours),
    )
    return [row_to_candidate(row, args=args, column_map=column_map) for row in selected_rows]


def candidate_to_json(candidate: ResearchPaperCandidateV1) -> str:
    return json.dumps(candidate.to_transport_dict(), sort_keys=True, separators=(",", ":"))


def print_summary(
    *,
    args: argparse.Namespace,
    raw_rows: list[dict[str, Any]],
    candidates: list[ResearchPaperCandidateV1],
    column_map: ColumnMap,
) -> None:
    symbols = sorted({row.symbol for row in candidates})
    first_ts = min((row.asof_ts_utc for row in candidates), default=None)
    last_ts = max((row.asof_ts_utc for row in candidates), default=None)

    print("Arena V2 paper-candidate stage bridge")
    print(f"database: {args.database}")
    print(f"eval_table: {args.eval_table}")
    print(f"policy_name: {args.policy_name}")
    print(f"policy_version: {args.policy_version}")
    print(f"candidate_state: {args.candidate_state}")
    print(f"venue: {args.venue}")
    print(f"window: [{args.from_ts}, {args.to_ts})")
    print(f"hold_hours: {args.hold_hours}")
    print(f"source_timestamp_col: {column_map.timestamp_col}")
    print(f"source_id_col: {column_map.source_id_col}")
    print(f"horizon_mode: {column_map.horizon_mode}")
    print(f"return_col: {column_map.return_col}")
    print(f"raw_rows: {len(raw_rows)}")
    print(f"exported_candidates: {len(candidates)}")
    print(f"symbols: {len(symbols)}")
    print(f"first_ts: {first_ts}")
    print(f"last_ts: {last_ts}")

    if symbols:
        print()
        print("symbols:")
        print(", ".join(symbols[:80]))

    if candidates:
        print()
        print("sample:")
        for candidate in candidates[:10]:
            print(candidate.to_transport_dict())


def write_jsonl(candidates: list[ResearchPaperCandidateV1], output_file: str | None) -> None:
    lines = [candidate_to_json(candidate) for candidate in candidates]

    if output_file:
        Path(output_file).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return

    for line in lines:
        print(line)


def main() -> int:
    args = parse_args()
    raw_rows, column_map, _columns = fetch_candidate_source_rows(args)
    candidates = build_candidates(raw_rows, args=args, column_map=column_map)

    if args.output == "jsonl":
        write_jsonl(candidates, args.output_file)
        if args.output_file:
            print_summary(args=args, raw_rows=raw_rows, candidates=candidates, column_map=column_map)
        return 0

    print_summary(args=args, raw_rows=raw_rows, candidates=candidates, column_map=column_map)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
