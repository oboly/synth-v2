from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


VERSION = "0.1"
SOURCE_NAME = "breath_curve_partial_to_full_v1"


@dataclass(frozen=True)
class PolicyConfig:
    policy_name: str
    policy_version: str
    min_partial_score: Decimal
    checkpoints: tuple[str, ...]
    tp1_weight: Decimal
    tp2_weight: Decimal
    require_offset_match: bool
    cost_bps: Decimal


@dataclass(frozen=True)
class PolicyRow:
    symbol: str
    anchor_date: str
    checkpoint_ratio: str
    selected_partial_offset_days: Decimal | None
    selected_partial_score: Decimal
    selected_partial_shape: Decimal | None
    selected_partial_timing: Decimal | None
    selected_partial_coverage: Decimal | None
    selected_partial_due_markers: int | None
    selected_partial_observed_markers: int | None
    offset_matches_best_full: bool
    return_to_1000_pct: Decimal | None
    return_to_1272_pct: Decimal | None
    policy_return_pct: Decimal
    policy_state: str
    source_row: dict[str, str]


def dec(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default

    text = str(value).strip()
    if text == "" or text.lower() in {"none", "null", "nan"}:
        return default

    try:
        return Decimal(text)
    except InvalidOperation:
        return default


def int_or_none(value: Any) -> int | None:
    parsed = dec(value)
    if parsed is None:
        return None
    return int(parsed)


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def first_text(row: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def source_anchor_date(row: dict[str, str]) -> str:
    raw = first_text(
        row,
        (
            "anchor_date",
            "anchor",
            "anchor_ts",
            "anchor_ts_utc",
            "anchor_datetime",
            "cycle_anchor",
            "cycle_anchor_date",
        ),
    )

    if not raw:
        return ""

    # Accept YYYY-MM-DD, ISO datetime, or "YYYY-MM-DD HH:MM:SS".
    return raw.replace("T", " ").split(" ")[0]


def fmt(value: Decimal | None, places: int = 4) -> str:
    if value is None:
        return ""
    q = Decimal("1").scaleb(-places)
    return format(value.quantize(q), "f")


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def eligible(row: dict[str, str], config: PolicyConfig) -> tuple[bool, str]:
    checkpoint = str(row.get("checkpoint_ratio", "")).strip()
    if checkpoint not in config.checkpoints:
        return False, "CHECKPOINT_NOT_SELECTED"

    partial_score = dec(row.get("selected_partial_score"))
    if partial_score is None:
        return False, "MISSING_PARTIAL_SCORE"

    if partial_score < config.min_partial_score:
        return False, "PARTIAL_SCORE_BELOW_THRESHOLD"

    if config.require_offset_match and not truthy(row.get("offset_matches_best_full")):
        return False, "OFFSET_MATCH_REQUIRED"

    future_flag = row.get("future_target_is_future")
    if future_flag is not None and str(future_flag).strip() != "" and not truthy(future_flag):
        return False, "TARGET_NOT_FUTURE"

    if dec(row.get("return_to_1000_pct")) is None and dec(row.get("return_to_1272_pct")) is None:
        return False, "NO_RETURN_TARGET"

    return True, "ELIGIBLE"


def calc_policy_return(row: dict[str, str], config: PolicyConfig) -> Decimal:
    ret1000 = dec(row.get("return_to_1000_pct"))
    ret1272 = dec(row.get("return_to_1272_pct"))

    tp1_weight = config.tp1_weight
    tp2_weight = config.tp2_weight

    if ret1272 is None:
        tp1_weight = Decimal("1")
        tp2_weight = Decimal("0")

    if ret1000 is None:
        tp1_weight = Decimal("0")
        tp2_weight = Decimal("1")

    gross = Decimal("0")
    if ret1000 is not None:
        gross += tp1_weight * ret1000
    if ret1272 is not None:
        gross += tp2_weight * ret1272

    return gross - (config.cost_bps / Decimal("100"))


def run_policy(rows: list[dict[str, str]], config: PolicyConfig) -> list[PolicyRow]:
    out: list[PolicyRow] = []

    for row in rows:
        is_eligible, state = eligible(row, config)
        if not is_eligible:
            continue

        anchor_date = source_anchor_date(row)
        if not anchor_date:
            continue

        out.append(
            PolicyRow(
                symbol=str(row.get("symbol", "")).strip(),
                anchor_date=anchor_date,
                checkpoint_ratio=str(row.get("checkpoint_ratio", "")).strip(),
                selected_partial_offset_days=dec(row.get("selected_partial_offset_days")),
                selected_partial_score=dec(row.get("selected_partial_score"), Decimal("0")) or Decimal("0"),
                selected_partial_shape=dec(row.get("selected_partial_shape")),
                selected_partial_timing=dec(row.get("selected_partial_timing")),
                selected_partial_coverage=dec(row.get("selected_partial_coverage")),
                selected_partial_due_markers=int_or_none(row.get("selected_partial_due_markers")),
                selected_partial_observed_markers=int_or_none(row.get("selected_partial_observed_markers")),
                offset_matches_best_full=truthy(row.get("offset_matches_best_full")),
                return_to_1000_pct=dec(row.get("return_to_1000_pct")),
                return_to_1272_pct=dec(row.get("return_to_1272_pct")),
                policy_return_pct=calc_policy_return(row, config),
                policy_state=state,
                source_row=row,
            )
        )

    return out


def insert_run(
    conn: Any,
    *,
    config: PolicyConfig,
    source_path: str,
    rows_input: int,
    rows_written: int,
    notes: str | None,
) -> int:
    sql = """
    INSERT INTO research_breath_curve_policy_run (
        policy_name,
        policy_version,
        source_name,
        source_path,
        checkpoint_set,
        min_partial_score,
        tp1_weight,
        tp2_weight,
        cost_bps,
        require_offset_match,
        rows_input,
        rows_written,
        notes
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                config.policy_name,
                config.policy_version,
                SOURCE_NAME,
                source_path,
                ",".join(config.checkpoints),
                config.min_partial_score,
                config.tp1_weight,
                config.tp2_weight,
                config.cost_bps,
                1 if config.require_offset_match else 0,
                rows_input,
                rows_written,
                notes,
            ),
        )
        return int(cur.lastrowid)


def insert_results(conn: Any, *, run_id: int, rows: list[PolicyRow]) -> int:
    sql = """
    INSERT INTO research_breath_curve_policy_result (
        research_breath_curve_policy_run_id,
        symbol,
        anchor_date,
        checkpoint_ratio,
        selected_partial_offset_days,
        selected_partial_score,
        selected_partial_shape,
        selected_partial_timing,
        selected_partial_coverage,
        selected_partial_due_markers,
        selected_partial_observed_markers,
        offset_matches_best_full,
        return_to_1000_pct,
        return_to_1272_pct,
        policy_return_pct,
        policy_state,
        source_row_json
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """

    inserted = 0

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                sql,
                (
                    run_id,
                    row.symbol,
                    row.anchor_date,
                    row.checkpoint_ratio,
                    row.selected_partial_offset_days,
                    row.selected_partial_score,
                    row.selected_partial_shape,
                    row.selected_partial_timing,
                    row.selected_partial_coverage,
                    row.selected_partial_due_markers,
                    row.selected_partial_observed_markers,
                    1 if row.offset_matches_best_full else 0,
                    row.return_to_1000_pct,
                    row.return_to_1272_pct,
                    row.policy_return_pct,
                    row.policy_state,
                    json.dumps(row.source_row, sort_keys=True),
                ),
            )
            inserted += 1

    return inserted


def summarize(rows: list[PolicyRow]) -> dict[str, Decimal | int | None]:
    returns = [row.policy_return_pct for row in rows]

    if not returns:
        return {
            "rows": 0,
            "avg_return_pct": None,
            "median_return_pct": None,
            "positive_rate_pct": None,
            "best_return_pct": None,
            "worst_return_pct": None,
        }

    ordered = sorted(returns)
    n = len(ordered)

    if n % 2:
        median = ordered[n // 2]
    else:
        median = (ordered[n // 2 - 1] + ordered[n // 2]) / Decimal("2")

    positive = [x for x in returns if x > 0]

    return {
        "rows": len(rows),
        "avg_return_pct": sum(returns) / Decimal(str(len(returns))),
        "median_return_pct": median,
        "positive_rate_pct": Decimal(str(len(positive))) / Decimal(str(len(returns))) * Decimal("100"),
        "best_return_pct": max(returns),
        "worst_return_pct": min(returns),
    }


def print_summary(rows: list[PolicyRow]) -> None:
    summary = summarize(rows)

    print("--- summary ---")
    print(f"rows={summary['rows']}")
    print(f"avg_return_pct={fmt(summary['avg_return_pct'])}")
    print(f"median_return_pct={fmt(summary['median_return_pct'])}")
    print(f"positive_rate_pct={fmt(summary['positive_rate_pct'], 2)}")
    print(f"best_return_pct={fmt(summary['best_return_pct'])}")
    print(f"worst_return_pct={fmt(summary['worst_return_pct'])}")

    groups: dict[str, list[PolicyRow]] = {}
    for row in rows:
        groups.setdefault(row.symbol, []).append(row)

    print()
    print("--- by symbol ---")
    for symbol, symbol_rows in sorted(groups.items()):
        item = summarize(symbol_rows)
        print(
            f"symbol={symbol} "
            f"rows={item['rows']} "
            f"avg={fmt(item['avg_return_pct'])}% "
            f"positive={fmt(item['positive_rate_pct'], 2)}%"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DB-backed research-only breath curve policy backtest."
    )
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--policy-name", default="breath_curve_research_policy_v1")
    parser.add_argument("--policy-version", default=VERSION)
    parser.add_argument("--min-partial-score", default="0.70")
    parser.add_argument("--checkpoints", default="0.618")
    parser.add_argument("--tp1-weight", default="0.50")
    parser.add_argument("--tp2-weight", default="0.50")
    parser.add_argument("--cost-bps", default="20")
    parser.add_argument("--require-offset-match", action="store_true")
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--notes", default=None)
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(dotenv_path=".env", override=False)

    input_csv = Path(args.input_csv)
    if not input_csv.exists():
        print(f"FAIL: input CSV not found: {input_csv}")
        return 1

    config = PolicyConfig(
        policy_name=str(args.policy_name),
        policy_version=str(args.policy_version),
        min_partial_score=Decimal(str(args.min_partial_score)),
        checkpoints=tuple(x.strip() for x in str(args.checkpoints).split(",") if x.strip()),
        tp1_weight=Decimal(str(args.tp1_weight)),
        tp2_weight=Decimal(str(args.tp2_weight)),
        cost_bps=Decimal(str(args.cost_bps)),
        require_offset_match=bool(args.require_offset_match),
    )

    raw_rows = load_rows(input_csv)
    policy_rows = run_policy(raw_rows, config)

    run_id: int | None = None
    inserted = 0

    if args.write_db:
        conn = get_db_connection()
        try:
            run_id = insert_run(
                conn,
                config=config,
                source_path=str(input_csv),
                rows_input=len(raw_rows),
                rows_written=len(policy_rows),
                notes=args.notes,
            )
            inserted = insert_results(conn, run_id=run_id, rows=policy_rows)
            conn.commit()
        finally:
            conn.close()

    if args.output == "table":
        print(f"report=breath_curve_research_policy_db_backtest_v1 version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("broker_calls=0 broker_writes=0 order_submission=0 decision_gate=none execution_planner=none executor=none")
        print(f"input_csv={input_csv}")
        print(f"raw_rows={len(raw_rows)}")
        print(f"policy_rows={len(policy_rows)}")
        print(f"policy_name={config.policy_name}")
        print(f"checkpoints={','.join(config.checkpoints)}")
        print(f"min_partial_score={config.min_partial_score}")
        print(f"tp1_weight={config.tp1_weight} tp2_weight={config.tp2_weight}")
        print(f"cost_bps={config.cost_bps}")
        print(f"require_offset_match={config.require_offset_match}")
        print(f"write_db={args.write_db}")
        print(f"run_id={'' if run_id is None else run_id}")
        print()
        print_summary(policy_rows)
        print()
        print(
            f"[DONE] policy_rows={len(policy_rows)} "
            f"db_writes={1 + inserted if args.write_db else 0} "
            "broker_calls=0 broker_writes=0 order_submission=0"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
