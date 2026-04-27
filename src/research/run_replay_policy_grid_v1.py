from __future__ import annotations

"""
Synth v2 - Replay Policy Grid V1.

LAYER:
research/backtest evaluation

BOUNDARY:
Allowed:
- read materialized replay eval rows
- test market-only policy combinations
- rank policy candidates by forward-return metrics

Forbidden:
- account state
- balances
- positions
- orders
- execution plans
- broker actions

Purpose:
Find robust market-only candidate policies across rank, BTC context,
rotation/classification/sleeve buckets, score buckets, and weak-symbol handling.
"""

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


BT_DB = "synth_bt"
DEFAULT_EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v1"

WEAK_SET = frozenset(
    {
        "HNT",
        "SOL",
        "XLM",
        "LTC",
        "ETH",
        "XRP",
        "CC",
        "NOT",
    }
)


@dataclass(frozen=True)
class EvalRow:
    symbol: str
    replay_asof_ts_utc: datetime
    selection_state: str
    selection_score: Decimal | None
    priority_rank: int | None
    btc_prior_24h: Decimal | None
    rotation_bucket: str | None
    classification_code: str | None
    sleeve_fit_code: str | None
    net_return_4h: Decimal | None
    gross_return_4h: Decimal | None
    net_return_24h: Decimal | None
    gross_return_24h: Decimal | None


@dataclass(frozen=True)
class PolicySpec:
    rule_id: str
    rank_name: str
    rank_min: int | None
    rank_max: int | None
    btc_name: str
    btc_min: Decimal | None
    btc_max: Decimal | None
    score_name: str
    score_min: Decimal | None
    score_max: Decimal | None
    weak_mode: str
    rotation_bucket: str
    classification_code: str
    sleeve_fit_code: str


@dataclass(frozen=True)
class PolicyResult:
    rule_id: str
    rank_name: str
    btc_name: str
    score_name: str
    weak_mode: str
    rotation_bucket: str
    classification_code: str
    sleeve_fit_code: str

    rows_total: int
    symbol_count: int
    day_count: int
    dominant_symbol: str | None
    dominant_symbol_share: Decimal | None

    rows_4h: int
    avg_net_4h: Decimal | None
    avg_gross_4h: Decimal | None
    winrate_4h: Decimal | None
    worst_net_4h: Decimal | None
    best_net_4h: Decimal | None

    rows_24h: int
    avg_net_24h: Decimal | None
    avg_gross_24h: Decimal | None
    winrate_24h: Decimal | None
    worst_net_24h: Decimal | None
    best_net_24h: Decimal | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run market-only replay policy grid evaluation."
    )
    parser.add_argument("--eval-table", default=DEFAULT_EVAL_TABLE)
    parser.add_argument("--selection-states", nargs="+", default=["WATCHLIST"])
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    parser.add_argument("--min-rows", type=int, default=25)
    parser.add_argument("--min-symbols", type=int, default=3)
    parser.add_argument("--max-dominant-symbol-share", default="0.50")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _fmt_decimal(value: Decimal | None, places: int = 6) -> str:
    if value is None:
        return ""
    return str(value.quantize(Decimal("1").scaleb(-places)))


def fetch_eval_rows(
    *,
    eval_table: str,
    selection_states: list[str],
    from_ts: str | None,
    to_ts: str | None,
) -> list[EvalRow]:
    if not selection_states:
        raise ValueError("selection_states may not be empty")

    placeholders = ",".join(["%s"] * len(selection_states))
    params: list[Any] = list(selection_states)
    time_filter_sql = ""

    if from_ts is not None:
        time_filter_sql += " AND replay_asof_ts_utc >= %s"
        params.append(from_ts)

    if to_ts is not None:
        time_filter_sql += " AND replay_asof_ts_utc < %s"
        params.append(to_ts)

    sql = f"""
    SELECT
        symbol,
        replay_asof_ts_utc,
        selection_state,
        selection_score,
        priority_rank,
        btc_prior_24h,
        rotation_bucket,
        classification_code,
        sleeve_fit_code,
        net_return_4h,
        gross_return_4h,
        net_return_24h,
        gross_return_24h
    FROM {eval_table}
    WHERE selection_state IN ({placeholders})
      {time_filter_sql}
    """

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[EvalRow] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")

        out.append(
            EvalRow(
                symbol=str(row["symbol"]),
                replay_asof_ts_utc=row["replay_asof_ts_utc"],
                selection_state=str(row["selection_state"]),
                selection_score=_to_decimal(row["selection_score"]),
                priority_rank=_to_int(row["priority_rank"]),
                btc_prior_24h=_to_decimal(row["btc_prior_24h"]),
                rotation_bucket=row["rotation_bucket"],
                classification_code=row["classification_code"],
                sleeve_fit_code=row["sleeve_fit_code"],
                net_return_4h=_to_decimal(row["net_return_4h"]),
                gross_return_4h=_to_decimal(row["gross_return_4h"]),
                net_return_24h=_to_decimal(row["net_return_24h"]),
                gross_return_24h=_to_decimal(row["gross_return_24h"]),
            )
        )

    return out


def build_policy_specs(rows: list[EvalRow]) -> list[PolicySpec]:
    rank_ranges = [
        ("rank_1_3", 1, 3),
        ("rank_4_10", 4, 10),
        ("rank_4_8", 4, 8),
        ("rank_5_10", 5, 10),
        ("rank_6_15", 6, 15),
        ("rank_1_10", 1, 10),
        ("rank_1_20", 1, 20),
        ("rank_11_20", 11, 20),
    ]

    btc_ranges = [
        ("btc_minus_1p5_to_plus_1p5", Decimal("-0.015"), Decimal("0.015")),
        ("btc_minus_3_to_zero", Decimal("-0.030"), Decimal("0.000")),
        ("btc_minus_1p5_to_zero", Decimal("-0.015"), Decimal("0.000")),
        ("btc_zero_to_plus_1p5", Decimal("0.000"), Decimal("0.015")),
        ("btc_minus_1_to_plus_1", Decimal("-0.010"), Decimal("0.010")),
        ("btc_minus_0p5_to_plus_1p5", Decimal("-0.005"), Decimal("0.015")),
        ("btc_below_plus_1p5", None, Decimal("0.015")),
        ("btc_above_minus_1p5", Decimal("-0.015"), None),
    ]

    score_ranges = [
        ("score_any", None, None),
        ("score_lt_0p5000", None, Decimal("0.50000000")),
        ("score_0p5000_0p5040", Decimal("0.50000000"), Decimal("0.50400000")),
        ("score_0p5040_0p5100", Decimal("0.50400000"), Decimal("0.51000000")),
        ("score_0p5100_0p5200", Decimal("0.51000000"), Decimal("0.52000000")),
        ("score_ge_0p5200", Decimal("0.52000000"), None),
    ]

    weak_modes = ["include_weak", "exclude_weak"]

    ranking_tuples = {
        (
            row.rotation_bucket or "MISSING",
            row.classification_code or "MISSING",
            row.sleeve_fit_code or "MISSING",
        )
        for row in rows
        if row.rotation_bucket is not None
        and row.classification_code is not None
        and row.sleeve_fit_code is not None
    }

    ranking_filters = [
        ("ANY", "ANY", "ANY"),
        *sorted(ranking_tuples),
    ]

    specs: list[PolicySpec] = []
    idx = 1

    for rank_name, rank_min, rank_max in rank_ranges:
        for btc_name, btc_min, btc_max in btc_ranges:
            for score_name, score_min, score_max in score_ranges:
                for weak_mode in weak_modes:
                    for rotation_bucket, classification_code, sleeve_fit_code in ranking_filters:
                        specs.append(
                            PolicySpec(
                                rule_id=f"P{idx:05d}",
                                rank_name=rank_name,
                                rank_min=rank_min,
                                rank_max=rank_max,
                                btc_name=btc_name,
                                btc_min=btc_min,
                                btc_max=btc_max,
                                score_name=score_name,
                                score_min=score_min,
                                score_max=score_max,
                                weak_mode=weak_mode,
                                rotation_bucket=rotation_bucket,
                                classification_code=classification_code,
                                sleeve_fit_code=sleeve_fit_code,
                            )
                        )
                        idx += 1

    return specs


def row_matches_policy(row: EvalRow, policy: PolicySpec) -> bool:
    if row.priority_rank is None:
        return False

    if policy.rank_min is not None and row.priority_rank < policy.rank_min:
        return False

    if policy.rank_max is not None and row.priority_rank > policy.rank_max:
        return False

    if row.btc_prior_24h is None:
        return False

    if policy.btc_min is not None and row.btc_prior_24h < policy.btc_min:
        return False

    if policy.btc_max is not None and row.btc_prior_24h > policy.btc_max:
        return False

    if row.selection_score is None:
        return False

    if policy.score_min is not None and row.selection_score < policy.score_min:
        return False

    if policy.score_max is not None and row.selection_score >= policy.score_max:
        return False

    if policy.weak_mode == "exclude_weak" and row.symbol in WEAK_SET:
        return False

    if policy.rotation_bucket != "ANY" and row.rotation_bucket != policy.rotation_bucket:
        return False

    if policy.classification_code != "ANY" and row.classification_code != policy.classification_code:
        return False

    if policy.sleeve_fit_code != "ANY" and row.sleeve_fit_code != policy.sleeve_fit_code:
        return False

    return True


def _avg(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(str(len(values)))


def _winrate(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    wins = sum(1 for value in values if value > 0)
    return Decimal(str(wins)) / Decimal(str(len(values)))


def evaluate_policy(policy: PolicySpec, rows: list[EvalRow]) -> PolicyResult | None:
    matched = [row for row in rows if row_matches_policy(row, policy)]
    if not matched:
        return None

    rows_4h = [row for row in matched if row.net_return_4h is not None]
    rows_24h = [row for row in matched if row.net_return_24h is not None]

    net_4h = [row.net_return_4h for row in rows_4h if row.net_return_4h is not None]
    gross_4h = [row.gross_return_4h for row in rows_4h if row.gross_return_4h is not None]
    net_24h = [row.net_return_24h for row in rows_24h if row.net_return_24h is not None]
    gross_24h = [row.gross_return_24h for row in rows_24h if row.gross_return_24h is not None]

    symbol_counts = Counter(row.symbol for row in rows_24h or rows_4h or matched)
    dominant_symbol = None
    dominant_symbol_share = None

    if symbol_counts:
        dominant_symbol, dominant_count = symbol_counts.most_common(1)[0]
        denominator = len(rows_24h or rows_4h or matched)
        dominant_symbol_share = Decimal(str(dominant_count)) / Decimal(str(denominator))

    return PolicyResult(
        rule_id=policy.rule_id,
        rank_name=policy.rank_name,
        btc_name=policy.btc_name,
        score_name=policy.score_name,
        weak_mode=policy.weak_mode,
        rotation_bucket=policy.rotation_bucket,
        classification_code=policy.classification_code,
        sleeve_fit_code=policy.sleeve_fit_code,
        rows_total=len(matched),
        symbol_count=len(symbol_counts),
        day_count=len({row.replay_asof_ts_utc.date() for row in matched}),
        dominant_symbol=dominant_symbol,
        dominant_symbol_share=dominant_symbol_share,
        rows_4h=len(net_4h),
        avg_net_4h=_avg(net_4h),
        avg_gross_4h=_avg(gross_4h),
        winrate_4h=_winrate(net_4h),
        worst_net_4h=min(net_4h) if net_4h else None,
        best_net_4h=max(net_4h) if net_4h else None,
        rows_24h=len(net_24h),
        avg_net_24h=_avg(net_24h),
        avg_gross_24h=_avg(gross_24h),
        winrate_24h=_winrate(net_24h),
        worst_net_24h=min(net_24h) if net_24h else None,
        best_net_24h=max(net_24h) if net_24h else None,
    )


def accepted_results(
    results: list[PolicyResult],
    *,
    min_rows: int,
    min_symbols: int,
    max_dominant_symbol_share: Decimal,
    horizon: str,
) -> list[PolicyResult]:
    out: list[PolicyResult] = []

    for result in results:
        rows_horizon = result.rows_24h if horizon == "24h" else result.rows_4h

        if rows_horizon < min_rows:
            continue

        if result.symbol_count < min_symbols:
            continue

        if (
            result.dominant_symbol_share is not None
            and result.dominant_symbol_share > max_dominant_symbol_share
        ):
            continue

        out.append(result)

    return out


def sort_results(results: list[PolicyResult], *, horizon: str) -> list[PolicyResult]:
    if horizon == "24h":
        return sorted(
            results,
            key=lambda row: (
                row.avg_net_24h if row.avg_net_24h is not None else Decimal("-999"),
                row.winrate_24h if row.winrate_24h is not None else Decimal("-1"),
                Decimal(str(row.rows_24h)),
            ),
            reverse=True,
        )

    return sorted(
        results,
        key=lambda row: (
            row.avg_net_4h if row.avg_net_4h is not None else Decimal("-999"),
            row.winrate_4h if row.winrate_4h is not None else Decimal("-1"),
            Decimal(str(row.rows_4h)),
        ),
        reverse=True,
    )


def robust_both_results(
    results: list[PolicyResult],
    *,
    min_rows: int,
    min_symbols: int,
    max_dominant_symbol_share: Decimal,
) -> list[PolicyResult]:
    out = [
        row
        for row in results
        if row.rows_4h >= min_rows
        and row.rows_24h >= min_rows
        and row.symbol_count >= min_symbols
        and (
            row.dominant_symbol_share is None
            or row.dominant_symbol_share <= max_dominant_symbol_share
        )
        and row.avg_net_4h is not None
        and row.avg_net_24h is not None
        and row.avg_net_4h > 0
        and row.avg_net_24h > 0
    ]

    return sorted(
        out,
        key=lambda row: (
            row.avg_net_24h + row.avg_net_4h,
            row.winrate_24h or Decimal("0"),
            row.winrate_4h or Decimal("0"),
        ),
        reverse=True,
    )


def print_results(title: str, rows: list[PolicyResult], *, top: int) -> None:
    print()
    print(f"=== {title} ===")

    if not rows:
        print("(no rows)")
        return

    headers = [
        "rule_id",
        "rank",
        "btc",
        "score",
        "weak",
        "rotation",
        "class",
        "sleeve",
        "rows4",
        "net4",
        "wr4",
        "rows24",
        "net24",
        "wr24",
        "sym",
        "dom",
        "dom_share",
    ]

    printable: list[list[str]] = []
    for row in rows[:top]:
        printable.append(
            [
                row.rule_id,
                row.rank_name,
                row.btc_name,
                row.score_name,
                row.weak_mode,
                row.rotation_bucket,
                row.classification_code,
                row.sleeve_fit_code,
                str(row.rows_4h),
                _fmt_decimal(row.avg_net_4h),
                _fmt_decimal(row.winrate_4h, places=4),
                str(row.rows_24h),
                _fmt_decimal(row.avg_net_24h),
                _fmt_decimal(row.winrate_24h, places=4),
                str(row.symbol_count),
                "" if row.dominant_symbol is None else row.dominant_symbol,
                _fmt_decimal(row.dominant_symbol_share, places=4),
            ]
        )

    widths = [len(header) for header in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))
    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()

    min_rows = int(args.min_rows)
    min_symbols = int(args.min_symbols)
    top = int(args.top)
    max_dominant_symbol_share = Decimal(str(args.max_dominant_symbol_share))

    rows = fetch_eval_rows(
        eval_table=str(args.eval_table),
        selection_states=[str(item) for item in args.selection_states],
        from_ts=None if args.from_ts is None else str(args.from_ts),
        to_ts=None if args.to_ts is None else str(args.to_ts),
    )

    policies = build_policy_specs(rows)

    results: list[PolicyResult] = []
    for policy in policies:
        evaluated = evaluate_policy(policy, rows)
        if evaluated is not None:
            results.append(evaluated)

    top_24h = sort_results(
        accepted_results(
            results,
            min_rows=min_rows,
            min_symbols=min_symbols,
            max_dominant_symbol_share=max_dominant_symbol_share,
            horizon="24h",
        ),
        horizon="24h",
    )

    top_4h = sort_results(
        accepted_results(
            results,
            min_rows=min_rows,
            min_symbols=min_symbols,
            max_dominant_symbol_share=max_dominant_symbol_share,
            horizon="4h",
        ),
        horizon="4h",
    )

    robust_both = robust_both_results(
        results,
        min_rows=min_rows,
        min_symbols=min_symbols,
        max_dominant_symbol_share=max_dominant_symbol_share,
    )

    payload = {
        "input": {
            "eval_table": str(args.eval_table),
            "selection_states": args.selection_states,
            "from_ts": args.from_ts,
            "to_ts": args.to_ts,
            "rows_loaded": len(rows),
            "policies_evaluated": len(results),
            "min_rows": min_rows,
            "min_symbols": min_symbols,
            "max_dominant_symbol_share": str(max_dominant_symbol_share),
        },
        "top_24h": [asdict(row) for row in top_24h[:top]],
        "top_4h": [asdict(row) for row in top_4h[:top]],
        "robust_both": [asdict(row) for row in robust_both[:top]],
    }

    if args.output == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    print("Replay policy grid")
    print(f"rows_loaded={len(rows)}")
    print(f"from_ts={args.from_ts}")
    print(f"to_ts={args.to_ts}")
    print(f"policies_evaluated={len(results)}")
    print(f"min_rows={min_rows}")
    print(f"min_symbols={min_symbols}")
    print(f"max_dominant_symbol_share={max_dominant_symbol_share}")

    print_results("TOP 24H POLICIES", top_24h, top=top)
    print_results("TOP 4H POLICIES", top_4h, top=top)
    print_results("ROBUST BOTH HORIZONS", robust_both, top=top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
