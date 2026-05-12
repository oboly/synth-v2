from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection
from src.research.breath_curve_template_matcher_v1 import (
    Candle,
    MarkerMatch,
    load_db,
    match,
    parse_dt,
    parse_offsets,
)
from src.research.run_breath_curve_template_partial_v1 import partial_match


REPORT_NAME = "breath_curve_random_anchor_baseline_v2"
VERSION = "0.1"

DEFAULT_SYMBOLS = "BTC,ETH,TAO,RENDER,FIL,HBAR,XLM,PEPE"
DEFAULT_REAL_POLICY_NAMES = (
    "breath_curve_research_policy_0618_v1,"
    "breath_curve_research_policy_0786_extension_v1,"
    "breath_curve_research_policy_0618_offset_match_v1,"
    "breath_curve_research_policy_0786_offset_match_v1"
)

POLICY_LABELS = {
    ("0.618", False): "0618_all",
    ("0.618", True): "0618_offset_match",
    ("0.786", False): "0786_all",
    ("0.786", True): "0786_offset_match",
}


@dataclass(frozen=True)
class RandomOutcome:
    symbol: str
    anchor_date: str
    checkpoint_ratio: str
    selected_partial_offset_days: float | None
    selected_partial_score: float | None
    selected_partial_shape: float | None
    selected_partial_timing: float | None
    selected_partial_coverage: float | None
    selected_partial_due_markers: int | None
    selected_partial_observed_markers: int | None
    offset_matches_best_full: bool
    return_to_1000_pct: float | None
    return_to_1272_pct: float | None
    policy_return_pct: float | None
    hold_to_1000_pct: float | None
    hold_to_1272_pct: float | None
    eligible_all: bool
    eligible_offset_match: bool
    exclusion_reason: str


def parse_csv_list(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def date_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).date().isoformat()


def expected_ts(anchor: datetime, cycle_days: float, ratio: float, offset_days: float) -> datetime:
    return anchor + timedelta(days=(cycle_days * ratio) + offset_days)


def marker_by_code(markers: list[MarkerMatch], code: str) -> MarkerMatch | None:
    for marker in markers:
        if marker.code == code:
            return marker
    return None


def last_close_at_or_before(candles: list[Candle], ts: datetime) -> float | None:
    prior = [c for c in candles if c.ts <= ts]
    if not prior:
        return None
    return prior[-1].close


def pct_return(from_price: float | None, to_price: float | None) -> float | None:
    if from_price is None or to_price is None or from_price == 0:
        return None
    return round(((to_price / from_price) - 1.0) * 100.0, 4)


def calc_policy_return(
    ret1000: float | None,
    ret1272: float | None,
    tp1_weight: float,
    tp2_weight: float,
    cost_bps: float,
) -> float | None:
    if ret1000 is None and ret1272 is None:
        return None

    w1 = tp1_weight
    w2 = tp2_weight

    if ret1272 is None:
        w1 = 1.0
        w2 = 0.0

    if ret1000 is None:
        w1 = 0.0
        w2 = 1.0

    gross = 0.0
    if ret1000 is not None:
        gross += w1 * ret1000
    if ret1272 is not None:
        gross += w2 * ret1272

    return round(gross - (cost_bps / 100.0), 4)


def fmt(value: Any, places: int = 4) -> str:
    if value is None:
        return ""

    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal("1").scaleb(-places)
    text = format(dec.quantize(q), "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(no rows)")
        return

    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def numeric_values(values: list[float | None]) -> list[float]:
    return [float(x) for x in values if x is not None]


def positive_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(1 for x in values if x > 0.0) / len(values) * 100.0, 4)


def avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def med(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 4)


def metric_from_returns(
    total_count: int,
    selected_returns: list[float | None],
    hold1000_returns: list[float | None],
    hold1272_returns: list[float | None],
) -> dict[str, Any]:
    policy_values = numeric_values(selected_returns)
    hold1000_values = numeric_values(hold1000_returns)
    hold1272_values = numeric_values(hold1272_returns)

    return {
        "total_count": total_count,
        "eligible_count": len(policy_values),
        "selection_rate_pct": round((len(policy_values) / total_count * 100.0), 4) if total_count else None,
        "avg_policy_return_pct": avg(policy_values),
        "median_policy_return_pct": med(policy_values),
        "positive_rate_pct": positive_rate(policy_values),
        "best_policy_return_pct": max(policy_values) if policy_values else None,
        "worst_policy_return_pct": min(policy_values) if policy_values else None,
        "avg_hold_to_1000_pct": avg(hold1000_values),
        "avg_hold_to_1272_pct": avg(hold1272_values),
        "policy_minus_hold_1000_pct": round(avg(policy_values) - avg(hold1000_values), 4) if policy_values and hold1000_values else None,
        "policy_minus_hold_1272_pct": round(avg(policy_values) - avg(hold1272_values), 4) if policy_values and hold1272_values else None,
    }


def fetch_real_policy_rows(conn: Any, policy_names: list[str]) -> list[dict[str, Any]]:
    if not policy_names:
        return []

    placeholders = ",".join(["%s"] * len(policy_names))

    sql = f"""
    SELECT
        r.policy_name,
        r.checkpoint_set,
        r.require_offset_match,
        x.symbol,
        x.anchor_date,
        x.checkpoint_ratio,
        x.offset_matches_best_full,
        x.return_to_1000_pct,
        x.return_to_1272_pct,
        x.policy_return_pct
    FROM research_breath_curve_policy_run r
    JOIN (
        SELECT
            policy_name,
            MAX(research_breath_curve_policy_run_id) AS latest_run_id
        FROM research_breath_curve_policy_run
        WHERE policy_name IN ({placeholders})
        GROUP BY policy_name
    ) latest
      ON latest.latest_run_id = r.research_breath_curve_policy_run_id
    JOIN research_breath_curve_policy_result x
      ON x.research_breath_curve_policy_run_id = r.research_breath_curve_policy_run_id
    ORDER BY
        r.policy_name,
        x.symbol,
        x.anchor_date,
        x.checkpoint_ratio
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, policy_names)
        return list(cur.fetchall())


def real_policy_label(row: dict[str, Any]) -> str:
    checkpoint = fmt(row["checkpoint_ratio"], 3)
    require_offset = bool(row["require_offset_match"])
    key = (checkpoint, require_offset)
    return POLICY_LABELS.get(key, f"{checkpoint}_{int(require_offset)}")


def summarize_real_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        grouped.setdefault(real_policy_label(row), []).append(row)

    out: dict[str, dict[str, Any]] = {}

    for label, group in grouped.items():
        out[label] = metric_from_returns(
            total_count=len(group),
            selected_returns=[float(row["policy_return_pct"]) for row in group],
            hold1000_returns=[float(row["return_to_1000_pct"]) if row["return_to_1000_pct"] is not None else None for row in group],
            hold1272_returns=[float(row["return_to_1272_pct"]) if row["return_to_1272_pct"] is not None else None for row in group],
        )

    return out


def real_anchor_dates_by_symbol(rows: list[dict[str, Any]]) -> dict[str, set[datetime]]:
    out: dict[str, set[datetime]] = {}

    for row in rows:
        symbol = str(row["symbol"])
        anchor_date = row["anchor_date"]

        if isinstance(anchor_date, datetime):
            dt = anchor_date.replace(tzinfo=timezone.utc)
        else:
            dt = parse_dt(str(anchor_date))

        out.setdefault(symbol, set()).add(dt)

    return out


def is_near_real_anchor(candidate: datetime, real_anchors: set[datetime], exclude_days: int) -> bool:
    for real_anchor in real_anchors:
        delta_days = abs((candidate.date() - real_anchor.date()).days)
        if delta_days <= exclude_days:
            return True
    return False


def candidate_anchors_from_candles(
    candles: list[Candle],
    start: datetime,
    end: datetime,
    earliest_required: datetime,
    latest_required: datetime,
    real_anchors: set[datetime],
    exclude_real_anchor_days: int,
) -> list[datetime]:
    out: list[datetime] = []

    seen_dates: set[str] = set()

    for candle in candles:
        if not (start <= candle.ts <= end):
            continue

        key = date_key(candle.ts)
        if key in seen_dates:
            continue
        seen_dates.add(key)

        if candle.ts < earliest_required:
            continue

        if candle.ts > latest_required:
            continue

        if is_near_real_anchor(candle.ts, real_anchors, exclude_real_anchor_days):
            continue

        out.append(candle.ts)

    return out


def evaluate_random_anchor(
    *,
    candles: list[Candle],
    symbol: str,
    venue: str,
    interval_code: str,
    anchor: datetime,
    checkpoint: float,
    cycle_days: float,
    offsets: list[float],
    tolerance_hours: float,
    min_due_markers: int,
    min_partial_score: float,
    future_target_ratio: float,
    tp1_weight: float,
    tp2_weight: float,
    cost_bps: float,
) -> RandomOutcome:
    as_of = expected_ts(anchor, cycle_days, checkpoint, 0.0)
    partial_candles = [c for c in candles if c.ts <= as_of]

    if len(partial_candles) < 3:
        return RandomOutcome(
            symbol=symbol,
            anchor_date=date_key(anchor),
            checkpoint_ratio=fmt(checkpoint, 3),
            selected_partial_offset_days=None,
            selected_partial_score=None,
            selected_partial_shape=None,
            selected_partial_timing=None,
            selected_partial_coverage=None,
            selected_partial_due_markers=None,
            selected_partial_observed_markers=None,
            offset_matches_best_full=False,
            return_to_1000_pct=None,
            return_to_1272_pct=None,
            policy_return_pct=None,
            hold_to_1000_pct=None,
            hold_to_1272_pct=None,
            eligible_all=False,
            eligible_offset_match=False,
            exclusion_reason="INSUFFICIENT_PARTIAL_CANDLES",
        )

    full_results = [
        match(
            candles=candles,
            symbol=symbol,
            venue=venue,
            interval_code=interval_code,
            anchor=anchor,
            cycle_days=cycle_days,
            offset_days=offset,
            tolerance_hours=tolerance_hours,
        )
        for offset in offsets
    ]

    best_full = max(full_results, key=lambda result: result.template_match_score)
    full_by_offset = {result.phase_offset_days: result for result in full_results}

    ranked_candidates: list[tuple[float, float, float, Any, bool]] = []

    for offset in offsets:
        pr = partial_match(
            candles=partial_candles,
            symbol=symbol,
            venue=venue,
            interval_code=interval_code,
            anchor=anchor,
            as_of=as_of,
            cycle_days=cycle_days,
            offset_days=offset,
            tolerance_hours=tolerance_hours,
            min_due_markers=min_due_markers,
            required_ratio=checkpoint,
        )

        target_ts = expected_ts(anchor, cycle_days, future_target_ratio, offset)
        target_is_future = target_ts > as_of
        ranking_score = pr.partial_match_score if target_is_future else 0.0
        ranked_candidates.append((ranking_score, pr.partial_match_score, offset, pr, target_is_future))

    ranked_candidates.sort(reverse=True, key=lambda item: (item[0], item[1], item[2]))

    selected_ranking_score, _, selected_offset, selected_partial, selected_target_is_future = ranked_candidates[0]
    selected_full = full_by_offset[selected_offset]

    marker1000 = marker_by_code(selected_full.markers, "MAIN_PULSE_TP_HIGH")
    marker1272 = marker_by_code(selected_full.markers, "OVERSHOOT_EXTENSION_TP")
    as_of_close = last_close_at_or_before(candles, as_of)

    ret1000 = pct_return(
        as_of_close,
        marker1000.observed_price if marker1000 and marker1000.matched else None,
    )
    ret1272 = pct_return(
        as_of_close,
        marker1272.observed_price if marker1272 and marker1272.matched else None,
    )

    policy_return = calc_policy_return(
        ret1000,
        ret1272,
        tp1_weight,
        tp2_weight,
        cost_bps,
    )

    offset_match = selected_offset == best_full.phase_offset_days

    eligible_all = (
        selected_target_is_future
        and selected_partial.partial_match_score >= min_partial_score
        and policy_return is not None
    )
    eligible_offset_match = eligible_all and offset_match

    exclusion_reason = "ELIGIBLE"
    if not selected_target_is_future:
        exclusion_reason = "TARGET_NOT_FUTURE"
    elif selected_partial.partial_match_score < min_partial_score:
        exclusion_reason = "PARTIAL_SCORE_BELOW_THRESHOLD"
    elif policy_return is None:
        exclusion_reason = "NO_RETURN_TARGET"
    elif not offset_match:
        exclusion_reason = "ELIGIBLE_ALL_ONLY_OFFSET_NOT_MATCHED"

    return RandomOutcome(
        symbol=symbol,
        anchor_date=date_key(anchor),
        checkpoint_ratio=fmt(checkpoint, 3),
        selected_partial_offset_days=selected_offset,
        selected_partial_score=selected_partial.partial_match_score,
        selected_partial_shape=selected_partial.partial_shape_score,
        selected_partial_timing=selected_partial.partial_timing_score,
        selected_partial_coverage=selected_partial.marker_coverage_score,
        selected_partial_due_markers=selected_partial.due_marker_count,
        selected_partial_observed_markers=selected_partial.observed_marker_count,
        offset_matches_best_full=offset_match,
        return_to_1000_pct=ret1000,
        return_to_1272_pct=ret1272,
        policy_return_pct=policy_return,
        hold_to_1000_pct=ret1000,
        hold_to_1272_pct=ret1272,
        eligible_all=eligible_all,
        eligible_offset_match=eligible_offset_match,
        exclusion_reason=exclusion_reason,
    )


def summarize_random_outcomes(outcomes: list[RandomOutcome]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[RandomOutcome]] = {}

    for outcome in outcomes:
        grouped.setdefault(f"{outcome.checkpoint_ratio}_all", []).append(outcome)
        grouped.setdefault(f"{outcome.checkpoint_ratio}_offset_match", []).append(outcome)

    result: dict[str, dict[str, Any]] = {}

    for label, group in grouped.items():
        if label.endswith("_offset_match"):
            selected = [x for x in group if x.eligible_offset_match]
        else:
            selected = [x for x in group if x.eligible_all]

        result[label] = metric_from_returns(
            total_count=len(group),
            selected_returns=[x.policy_return_pct for x in selected],
            hold1000_returns=[x.hold_to_1000_pct for x in selected],
            hold1272_returns=[x.hold_to_1272_pct for x in selected],
        )

    return result


def summarize_random_by_symbol(outcomes: list[RandomOutcome]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[RandomOutcome]] = {}

    for outcome in outcomes:
        buckets.setdefault((outcome.symbol, f"{outcome.checkpoint_ratio}_all"), []).append(outcome)
        buckets.setdefault((outcome.symbol, f"{outcome.checkpoint_ratio}_offset_match"), []).append(outcome)

    rows: list[dict[str, Any]] = []

    for (symbol, label), group in sorted(buckets.items()):
        if label.endswith("_offset_match"):
            selected = [x for x in group if x.eligible_offset_match]
        else:
            selected = [x for x in group if x.eligible_all]

        metrics = metric_from_returns(
            total_count=len(group),
            selected_returns=[x.policy_return_pct for x in selected],
            hold1000_returns=[x.hold_to_1000_pct for x in selected],
            hold1272_returns=[x.hold_to_1272_pct for x in selected],
        )

        rows.append(
            {
                "symbol": symbol,
                "bucket": label,
                **metrics,
            }
        )

    return rows


def write_random_samples_csv(path: Path, outcomes: list[RandomOutcome]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "symbol",
        "anchor_date",
        "checkpoint_ratio",
        "selected_partial_offset_days",
        "selected_partial_score",
        "selected_partial_shape",
        "selected_partial_timing",
        "selected_partial_coverage",
        "selected_partial_due_markers",
        "selected_partial_observed_markers",
        "offset_matches_best_full",
        "return_to_1000_pct",
        "return_to_1272_pct",
        "policy_return_pct",
        "hold_to_1000_pct",
        "hold_to_1272_pct",
        "eligible_all",
        "eligible_offset_match",
        "exclusion_reason",
    ]

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()

        for outcome in outcomes:
            writer.writerow({field: getattr(outcome, field) for field in fields})


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        return

    fields = sorted({key for row in rows for key in row.keys()})

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def comparison_rows(real_metrics: dict[str, dict[str, Any]], random_metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    label_map = {
        "0618_all": "0.618_all",
        "0618_offset_match": "0.618_offset_match",
        "0786_all": "0.786_all",
        "0786_offset_match": "0.786_offset_match",
    }

    out: list[dict[str, Any]] = []

    for real_label, random_label in label_map.items():
        real = real_metrics.get(real_label, {})
        rnd = random_metrics.get(random_label, {})

        real_avg = real.get("avg_policy_return_pct")
        random_avg = rnd.get("avg_policy_return_pct")

        out.append(
            {
                "bucket": real_label,
                "real_rows": real.get("eligible_count"),
                "random_candidates": rnd.get("total_count"),
                "random_eligible": rnd.get("eligible_count"),
                "random_selection_rate_pct": rnd.get("selection_rate_pct"),
                "real_avg_policy_return_pct": real_avg,
                "random_avg_policy_return_pct": random_avg,
                "real_minus_random_pct": round(real_avg - random_avg, 4) if real_avg is not None and random_avg is not None else None,
                "real_positive_rate_pct": real.get("positive_rate_pct"),
                "random_positive_rate_pct": rnd.get("positive_rate_pct"),
                "real_worst_policy_return_pct": real.get("worst_policy_return_pct"),
                "random_worst_policy_return_pct": rnd.get("worst_policy_return_pct"),
                "real_policy_minus_hold_1000_pct": real.get("policy_minus_hold_1000_pct"),
                "random_policy_minus_hold_1000_pct": rnd.get("policy_minus_hold_1000_pct"),
                "real_policy_minus_hold_1272_pct": real.get("policy_minus_hold_1272_pct"),
                "random_policy_minus_hold_1272_pct": rnd.get("policy_minus_hold_1272_pct"),
            }
        )

    return out


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    symbols = parse_csv_list(args.symbols)
    checkpoints = [float(x) for x in parse_csv_list(args.checkpoints)]
    offsets = parse_offsets(args.offsets)
    policy_names = parse_csv_list(args.real_policy_names)

    start_dt = parse_dt(args.start_date)
    end_dt = parse_dt(args.end_date)

    conn = get_db_connection()

    try:
        real_rows = fetch_real_policy_rows(conn, policy_names)
    finally:
        conn.close()

    real_metrics = summarize_real_rows(real_rows)
    real_anchors = real_anchor_dates_by_symbol(real_rows)

    outcomes: list[RandomOutcome] = []

    for symbol in symbols:
        query_start = start_dt + timedelta(days=min(offsets)) - timedelta(hours=args.tolerance_hours + 48)
        query_end = end_dt + timedelta(days=args.cycle_days * 1.272 + max(offsets)) + timedelta(hours=args.tolerance_hours + 48)

        candles = load_db(
            symbol=symbol,
            asset_id=None,
            venue=args.venue,
            interval_code=args.interval_code,
            start=query_start,
            end=query_end,
        )

        if len(candles) < 10:
            print(f"WARN symbol={symbol} insufficient candles={len(candles)}")
            continue

        earliest_required = candles[0].ts - timedelta(days=min(offsets)) + timedelta(hours=args.tolerance_hours + 48)
        latest_required = candles[-1].ts - timedelta(days=args.cycle_days * 1.272 + max(offsets)) - timedelta(hours=args.tolerance_hours + 48)

        candidates = candidate_anchors_from_candles(
            candles=candles,
            start=start_dt,
            end=end_dt,
            earliest_required=earliest_required,
            latest_required=latest_required,
            real_anchors=real_anchors.get(symbol, set()),
            exclude_real_anchor_days=args.exclude_real_anchor_days,
        )

        rng = random.Random(f"{args.seed}:{symbol}")
        rng.shuffle(candidates)
        selected_anchors = sorted(candidates[: args.samples_per_symbol])

        print(
            f"symbol={symbol} candidates={len(candidates)} sampled={len(selected_anchors)} "
            f"real_anchor_exclusion_days={args.exclude_real_anchor_days}"
        )

        for anchor in selected_anchors:
            for checkpoint in checkpoints:
                outcomes.append(
                    evaluate_random_anchor(
                        candles=candles,
                        symbol=symbol,
                        venue=args.venue,
                        interval_code=args.interval_code,
                        anchor=anchor,
                        checkpoint=checkpoint,
                        cycle_days=args.cycle_days,
                        offsets=offsets,
                        tolerance_hours=args.tolerance_hours,
                        min_due_markers=args.min_due_markers,
                        min_partial_score=args.min_partial_score,
                        future_target_ratio=args.future_target_ratio,
                        tp1_weight=args.tp1_weight,
                        tp2_weight=args.tp2_weight,
                        cost_bps=args.cost_bps,
                    )
                )

    random_metrics = summarize_random_outcomes(outcomes)
    comparisons = comparison_rows(real_metrics, random_metrics)
    symbol_rows = summarize_random_by_symbol(outcomes)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir)
    sample_path = out_dir / f"breath_curve_random_anchor_baseline_v2_samples_{stamp}.csv"
    summary_path = out_dir / f"breath_curve_random_anchor_baseline_v2_summary_{stamp}.csv"
    symbol_path = out_dir / f"breath_curve_random_anchor_baseline_v2_symbol_buckets_{stamp}.csv"

    write_random_samples_csv(sample_path, outcomes)
    write_summary_csv(summary_path, comparisons)
    write_summary_csv(symbol_path, symbol_rows)

    if args.output == "table":
        print("")
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("runtime_layer_touch=none")
        print(f"symbols={','.join(symbols)}")
        print(f"window={args.start_date}..{args.end_date}")
        print(f"samples_per_symbol={args.samples_per_symbol}")
        print(f"seed={args.seed}")
        print(f"checkpoints={','.join(fmt(x, 3) for x in checkpoints)}")
        print(f"exclude_real_anchor_days={args.exclude_real_anchor_days}")
        print("")
        print("--- real vs random baseline ---")
        print_table(
            [
                "bucket",
                "real_rows",
                "rand_total",
                "rand_elig",
                "rand_sel",
                "real_avg",
                "rand_avg",
                "real-rand",
                "real_pos",
                "rand_pos",
                "real_worst",
                "rand_worst",
                "real-h1000",
                "rand-h1000",
                "real-h1272",
                "rand-h1272",
            ],
            [
                [
                    str(row["bucket"]),
                    str(row["real_rows"]),
                    str(row["random_candidates"]),
                    str(row["random_eligible"]),
                    fmt(row["random_selection_rate_pct"], 2),
                    fmt(row["real_avg_policy_return_pct"]),
                    fmt(row["random_avg_policy_return_pct"]),
                    fmt(row["real_minus_random_pct"]),
                    fmt(row["real_positive_rate_pct"], 2),
                    fmt(row["random_positive_rate_pct"], 2),
                    fmt(row["real_worst_policy_return_pct"]),
                    fmt(row["random_worst_policy_return_pct"]),
                    fmt(row["real_policy_minus_hold_1000_pct"]),
                    fmt(row["random_policy_minus_hold_1000_pct"]),
                    fmt(row["real_policy_minus_hold_1272_pct"]),
                    fmt(row["random_policy_minus_hold_1272_pct"]),
                ]
                for row in comparisons
            ],
        )

        print("")
        print("--- random per-symbol buckets ---")
        print_table(
            [
                "symbol",
                "bucket",
                "total",
                "eligible",
                "sel_rate",
                "avg",
                "median",
                "pos",
                "best",
                "worst",
                "hold1000",
                "hold1272",
            ],
            [
                [
                    str(row["symbol"]),
                    str(row["bucket"]),
                    str(row["total_count"]),
                    str(row["eligible_count"]),
                    fmt(row["selection_rate_pct"], 2),
                    fmt(row["avg_policy_return_pct"]),
                    fmt(row["median_policy_return_pct"]),
                    fmt(row["positive_rate_pct"], 2),
                    fmt(row["best_policy_return_pct"]),
                    fmt(row["worst_policy_return_pct"]),
                    fmt(row["avg_hold_to_1000_pct"]),
                    fmt(row["avg_hold_to_1272_pct"]),
                ]
                for row in symbol_rows
            ],
        )

        print("")
        print(f"wrote_samples_csv={sample_path}")
        print(f"wrote_summary_csv={summary_path}")
        print(f"wrote_symbol_buckets_csv={symbol_path}")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only Breath Curve same-symbol random-anchor baseline v2."
    )
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--start-date", default="2026-03-01")
    parser.add_argument("--end-date", default="2026-04-12")
    parser.add_argument("--checkpoints", default="0.618,0.786")
    parser.add_argument("--samples-per-symbol", type=int, default=100)
    parser.add_argument("--seed", type=int, default=260512)
    parser.add_argument("--exclude-real-anchor-days", type=int, default=3)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--cycle-days", type=float, default=21.0)
    parser.add_argument("--offsets", default="-10.5,-7,-5,-3,0,3,5,7,10.5")
    parser.add_argument("--tolerance-hours", type=float, default=36.0)
    parser.add_argument("--min-due-markers", type=int, default=3)
    parser.add_argument("--min-partial-score", type=float, default=0.70)
    parser.add_argument("--future-target-ratio", type=float, default=1.000)
    parser.add_argument("--tp1-weight", type=float, default=0.50)
    parser.add_argument("--tp2-weight", type=float, default=0.50)
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--real-policy-names", default=DEFAULT_REAL_POLICY_NAMES)
    parser.add_argument("--out-dir", default="data/research/breath_curve_random_anchor_baseline_v2")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
