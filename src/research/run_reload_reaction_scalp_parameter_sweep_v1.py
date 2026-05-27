from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any


REPORT_NAME = "reload_reaction_scalp_parameter_sweep_v1"
REPORT_VERSION = "1.0"
STRATEGY_CANDIDATE = "RELOAD_REACTION_SCALP_V1"
RETURN_LABEL = "POLICY_PROXY_RETURN"

DEFAULT_INPUT_ROWS = Path("data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl")
DEFAULT_FIBO_ROWS = Path("data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv")
DEFAULT_OUTPUT_DIR = Path("data/research/reload_reaction_scalp_parameter_sweep_v1")
DEFAULT_ACTION = "RELOAD_REVIEW"
DEFAULT_MIN_SAMPLES = 20
DEFAULT_MAX_EVENTS = 5000

ROWS_CSV = "reload_reaction_scalp_parameter_sweep_rows_v1.csv"
ROWS_JSONL = "reload_reaction_scalp_parameter_sweep_rows_v1.jsonl"
TOP_CANDIDATES_CSV = "reload_reaction_scalp_top_candidates_v1.csv"
REJECTED_CANDIDATES_CSV = "reload_reaction_scalp_rejected_candidates_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

RELOAD_ZONE_PARTS = ("entry_low", "entry_mid", "entry_high")
NEAR_ZONE_THRESHOLD_PCTS = (0.5, 1.0, 1.5, 2.0, 3.0)
TRIGGER_BASES = (
    "current_price_near_zone",
    "current_price_inside_zone",
    "current_price_above_entry_high_max_late",
)
MAX_LATE_DISTANCE_ABOVE_ZONE_PCTS = (0.25, 0.5, 1.0)
TARGET_MODES = ("local_reaction", "fib_1272_if_available", "fib_1618_if_available")
MAX_HOLD_HORIZONS = ("15m", "30m", "1h", "2h", "4h", "24h")
REQUIRE_APLUS_CONTEXT_OPTIONS = (False, True)

SAFETY = {
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "executor": "none",
    "live_trading": False,
    "research_only": True,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep reload-after-spike / reaction-zone reload parameters using lifecycle outcome rows "
            "(research-only, policy-proxy return, no execution path)."
        )
    )
    parser.add_argument("--input-rows", default=str(DEFAULT_INPUT_ROWS))
    parser.add_argument("--fibo-rows", default=str(DEFAULT_FIBO_ROWS))
    parser.add_argument("--action", default=DEFAULT_ACTION)
    parser.add_argument("--primary-bucket", default="ALL")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS)
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            row = json.loads(payload)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def average_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 6)


def parse_symbols_arg(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {piece.strip().upper() for piece in str(value).split(",") if piece.strip()}


def point_in_time_fibo_available(fibo_rows: list[dict[str, str]]) -> tuple[bool, str]:
    if not fibo_rows:
        return False, "fibo_rows_missing"
    return False, "latest_symbol_level_fibo_map_not_point_in_time_safe"


def load_events(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(Path(args.input_rows))
    fibo_rows = read_csv_rows(Path(args.fibo_rows)) if Path(args.fibo_rows).exists() else []
    fibo_safe, fibo_reason = point_in_time_fibo_available(fibo_rows)
    symbols_filter = parse_symbols_arg(args.symbols)
    selected: list[dict[str, Any]] = []
    skip_counts: Counter[str] = Counter()
    for row in rows[-int(args.max_events):]:
        if str(row.get("position_lifecycle_action") or "").upper() != str(args.action).upper():
            skip_counts["action_mismatch"] += 1
            continue
        if args.primary_bucket != "ALL" and str(row.get("reason_bucket") or "").upper() != str(args.primary_bucket).upper():
            skip_counts["primary_bucket_mismatch"] += 1
            continue
        if symbols_filter and str(row.get("symbol") or "").upper() not in symbols_filter:
            skip_counts["symbol_mismatch"] += 1
            continue
        if as_float(row.get("current_price")) is None:
            skip_counts["missing_current_price"] += 1
            continue
        if as_float(row.get("entry_zone_low")) is None or as_float(row.get("entry_zone_high")) is None:
            skip_counts["missing_entry_zone"] += 1
            continue
        if str(row.get("leg_direction") or "").upper() not in {"UP", ""}:
            skip_counts["non_up_leg"] += 1
            continue
        if "MISSING_PRICE" in " ".join(str(item) for item in (row.get("missing_inputs") or [])):
            skip_counts["missing_price_input"] += 1
            continue
        selected.append(row)
    meta = {
        "events_loaded": len(rows),
        "events_eligible": len(selected),
        "events_skipped_by_reason": dict(sorted(skip_counts.items())),
        "fibo_target_map_present": bool(fibo_rows),
        "fibo_target_modes_point_in_time_safe": fibo_safe,
        "fibo_target_guard_reason": fibo_reason,
    }
    return selected, meta


def zone_levels(row: dict[str, Any]) -> tuple[float, float, float]:
    low = as_float(row.get("entry_zone_low")) or 0.0
    high = as_float(row.get("entry_zone_high")) or 0.0
    lo = min(low, high)
    hi = max(low, high)
    return lo, (lo + hi) / 2.0, hi


def pct_distance(reference: float | None, target: float | None) -> float | None:
    if reference is None or target is None or reference <= 0:
        return None
    return abs((reference / target) - 1.0) * 100.0


def current_inside_zone(row: dict[str, Any]) -> bool:
    current = as_float(row.get("current_price"))
    low = as_float(row.get("entry_zone_low"))
    high = as_float(row.get("entry_zone_high"))
    if current is None or low is None or high is None:
        return False
    lo = min(low, high)
    hi = max(low, high)
    return lo <= current <= hi


def current_above_entry_high_pct(row: dict[str, Any]) -> float | None:
    current = as_float(row.get("current_price"))
    high = as_float(row.get("entry_zone_high"))
    low = as_float(row.get("entry_zone_low"))
    if current is None or high is None or low is None:
        return None
    zone_high = max(low, high)
    if current < zone_high or zone_high <= 0:
        return None
    return ((current / zone_high) - 1.0) * 100.0


def local_reaction_target_price(row: dict[str, Any]) -> float | None:
    current = as_float(row.get("current_price"))
    target_low = as_float(row.get("tp_zone_low"))
    target_high = as_float(row.get("tp_zone_high"))
    candidates = [value for value in [target_low, target_high] if value is not None and current is not None and value > current]
    if not candidates:
        return None
    return min(candidates)


def evaluate_trigger(
    row: dict[str, Any],
    *,
    reload_zone_part: str,
    near_zone_threshold_pct: float,
    trigger_basis: str,
    max_late_distance_above_zone_pct: float,
    require_aplus_context: bool,
) -> tuple[bool, str]:
    if require_aplus_context and str(row.get("reason_bucket") or "").upper() != "APLUS_CONTEXT":
        return False, "require_aplus_context_not_met"
    low, mid, high = zone_levels(row)
    current = as_float(row.get("current_price"))
    if current is None:
        return False, "missing_current_price"
    part_value = {"entry_low": low, "entry_mid": mid, "entry_high": high}[reload_zone_part]
    if trigger_basis == "current_price_near_zone":
        distance = pct_distance(current, part_value)
        return bool(distance is not None and distance <= near_zone_threshold_pct), "near_zone_distance_check"
    if trigger_basis == "current_price_inside_zone":
        return current_inside_zone(row), "inside_zone_check"
    if trigger_basis == "current_price_above_entry_high_max_late":
        above_pct = current_above_entry_high_pct(row)
        return bool(above_pct is not None and above_pct <= max_late_distance_above_zone_pct), "late_above_zone_check"
    return False, "unknown_trigger_basis"


def target_return_pct(row: dict[str, Any], target_mode: str, fib_guard_safe: bool) -> tuple[float | None, str]:
    current = as_float(row.get("current_price"))
    if current is None or current <= 0:
        return None, "missing_current_price"
    if target_mode == "local_reaction":
        target_price = local_reaction_target_price(row)
        if target_price is None:
            return None, "missing_local_reaction_target"
        return ((target_price / current) - 1.0) * 100.0, "local_reaction_target"
    if target_mode in {"fib_1272_if_available", "fib_1618_if_available"}:
        if not fib_guard_safe:
            return None, "fibo_target_not_point_in_time_safe"
        return None, "fibo_target_mode_not_implemented"
    return None, "unknown_target_mode"


def forward_return_for_horizon(row: dict[str, Any], horizon: str) -> float | None:
    returns = row.get("forward_returns") or {}
    return as_float(returns.get(horizon))


def complete_horizon(row: dict[str, Any], horizon: str) -> bool:
    return bool((row.get("sample_completeness_flags") or {}).get(f"complete_{horizon}"))


def policy_proxy_return(
    *,
    row: dict[str, Any],
    horizon: str,
    target_return: float | None,
) -> tuple[float | None, bool]:
    if not complete_horizon(row, horizon):
        return None, False
    hold_return = forward_return_for_horizon(row, horizon)
    if hold_return is None:
        return None, False
    mfe = as_float(row.get("max_favorable_excursion_pct"))
    if target_return is not None and target_return > 0 and mfe is not None and mfe >= target_return:
        return round(target_return, 6), True
    return round(hold_return, 6), False


def evaluate_parameter_set(
    events: list[dict[str, Any]],
    params: dict[str, Any],
    *,
    fib_guard_safe: bool,
    min_samples: int,
) -> dict[str, Any]:
    strategy_returns: list[float] = []
    hold_returns: list[float] = []
    mfes: list[float] = []
    maes: list[float] = []
    missed: list[float] = []
    hold_drawdowns: list[float] = []
    strategy_drawdowns: list[float] = []
    symbol_counts: Counter[str] = Counter()
    eligible_count = 0
    target_hit_count = 0
    evaluation_status = "OK"
    skip_reasons: Counter[str] = Counter()

    for row in events:
        triggered, trigger_reason = evaluate_trigger(
            row,
            reload_zone_part=params["reload_zone_part"],
            near_zone_threshold_pct=params["near_zone_threshold_pct"],
            trigger_basis=params["trigger_basis"],
            max_late_distance_above_zone_pct=params["max_late_distance_above_zone_pct"],
            require_aplus_context=params["require_aplus_context"],
        )
        if not triggered:
            skip_reasons[trigger_reason] += 1
            continue
        target_return, target_reason = target_return_pct(row, params["target_mode"], fib_guard_safe)
        if target_reason == "fibo_target_not_point_in_time_safe":
            evaluation_status = "SKIPPED_FIB_TARGET_NOT_POINT_IN_TIME_SAFE"
            skip_reasons[target_reason] += 1
            continue
        if target_return is None:
            skip_reasons[target_reason] += 1
            continue
        strategy_return, target_hit = policy_proxy_return(row=row, horizon=params["max_hold_horizon"], target_return=target_return)
        hold_return = forward_return_for_horizon(row, params["max_hold_horizon"])
        if strategy_return is None or hold_return is None:
            skip_reasons["incomplete_horizon"] += 1
            continue
        eligible_count += 1
        if target_hit:
            target_hit_count += 1
        strategy_returns.append(strategy_return)
        hold_returns.append(hold_return)
        mfe = as_float(row.get("max_favorable_excursion_pct"))
        mae = as_float(row.get("max_adverse_excursion_pct"))
        if mfe is not None:
            mfes.append(mfe)
            missed.append(max(0.0, mfe - strategy_return))
        if mae is not None:
            maes.append(mae)
        hold_drawdown = max(0.0, -(hold_return or 0.0))
        strategy_drawdown = 0.0 if target_hit else hold_drawdown
        hold_drawdowns.append(hold_drawdown)
        strategy_drawdowns.append(strategy_drawdown)
        symbol_counts[str(row.get("symbol") or "")] += 1

    sample_count = len(strategy_returns)
    top_symbol_count = max(symbol_counts.values()) if symbol_counts else 0
    top_symbol_concentration_pct = None if sample_count == 0 else round((top_symbol_count / sample_count) * 100.0, 6)
    overfit_risk = bool(top_symbol_concentration_pct is not None and top_symbol_concentration_pct > 30.0)
    excess_values = [strategy - hold for strategy, hold in zip(strategy_returns, hold_returns, strict=True)]
    drawdown_improvement_values = [hold - strategy for hold, strategy in zip(hold_drawdowns, strategy_drawdowns, strict=True)]
    wins = [value for value in strategy_returns if value > 0]

    if sample_count == 0 and evaluation_status == "OK":
        evaluation_status = "NO_ELIGIBLE_EVENTS"
    elif sample_count < min_samples and evaluation_status == "OK":
        evaluation_status = "INSUFFICIENT_SAMPLE"
    elif average_or_none(excess_values) is not None and average_or_none(excess_values) < 0 and evaluation_status == "OK":
        evaluation_status = "NEGATIVE_EXCESS_RETURN"

    return {
        "strategy_candidate": STRATEGY_CANDIDATE,
        "return_metric_label": RETURN_LABEL,
        "evaluation_status": evaluation_status,
        **params,
        "sample_count": sample_count,
        "events_eligible": eligible_count,
        "target_hit_count": target_hit_count,
        "avg_strategy_return_pct": average_or_none(strategy_returns),
        "median_strategy_return_pct": median_or_none(strategy_returns),
        "avg_hold_return_pct": average_or_none(hold_returns),
        "median_hold_return_pct": median_or_none(hold_returns),
        "excess_return_vs_hold_pct": average_or_none(excess_values),
        "winrate_pct": None if sample_count == 0 else round((len(wins) / sample_count) * 100.0, 6),
        "avg_mfe_pct": average_or_none(mfes),
        "avg_mae_pct": average_or_none(maes),
        "avg_opportunity_missed_pct": average_or_none(missed),
        "max_drawdown_proxy_pct": None if not strategy_drawdowns else round(max(strategy_drawdowns), 6),
        "avg_drawdown_improvement_vs_hold_pct": average_or_none(drawdown_improvement_values),
        "symbol_count": len(symbol_counts),
        "top_symbol": "" if not symbol_counts else symbol_counts.most_common(1)[0][0],
        "top_symbol_concentration_pct": top_symbol_concentration_pct,
        "overfit_risk_flag": overfit_risk,
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "policy_proxy_notes": (
            "Target exit is a POLICY_PROXY_RETURN: if target_return_pct <= max_favorable_excursion_pct, "
            "the sweep assumes target hit within horizon; otherwise it falls back to same-horizon close return."
        ),
    }


def top_rows(rows: list[dict[str, Any]], field: str, *, min_samples: int, reverse: bool = True, limit: int = 15) -> list[dict[str, Any]]:
    filtered = [
        row for row in rows
        if int(row.get("sample_count") or 0) >= int(min_samples)
        and as_float(row.get(field)) is not None
    ]
    return sorted(
        filtered,
        key=lambda row: (as_float(row.get(field)) or 0.0, int(row.get("sample_count") or 0)),
        reverse=reverse,
    )[:limit]


def summarize(rows: list[dict[str, Any]], meta: dict[str, Any], args: argparse.Namespace, paths: dict[str, Path]) -> dict[str, Any]:
    top_excess = top_rows(rows, "excess_return_vs_hold_pct", min_samples=args.min_samples, reverse=True)
    top_drawdown = top_rows(rows, "avg_drawdown_improvement_vs_hold_pct", min_samples=args.min_samples, reverse=True)
    rejected = [
        row for row in rows
        if int(row.get("sample_count") or 0) >= int(args.min_samples)
        and as_float(row.get("excess_return_vs_hold_pct")) is not None
        and as_float(row.get("excess_return_vs_hold_pct")) < 0
    ]
    summary = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "strategy_candidate": STRATEGY_CANDIDATE,
        "return_metric_label": RETURN_LABEL,
        "events_loaded": meta["events_loaded"],
        "events_eligible": meta["events_eligible"],
        "parameter_sets_tested": len(rows),
        "top_excess_return_candidates": top_excess,
        "top_drawdown_improvement_candidates": top_drawdown,
        "rejected_variants_negative_excess": sorted(
            rejected,
            key=lambda row: (as_float(row.get("excess_return_vs_hold_pct")) or 0.0, int(row.get("sample_count") or 0)),
        )[:15],
        "fibo_target_map_present": meta["fibo_target_map_present"],
        "fibo_target_modes_point_in_time_safe": meta["fibo_target_modes_point_in_time_safe"],
        "fibo_target_guard_reason": meta["fibo_target_guard_reason"],
        "events_skipped_by_reason": meta["events_skipped_by_reason"],
        "parameters": {
            "action": args.action,
            "primary_bucket": args.primary_bucket,
            "symbols": sorted(parse_symbols_arg(args.symbols) or []),
            "max_events": int(args.max_events),
            "min_samples": int(args.min_samples),
        },
        "files": {key: str(value) for key, value in paths.items()},
        **SAFETY,
    }
    return summary


def print_summary(summary: dict[str, Any], output_mode: str) -> None:
    if output_mode == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
        return
    print(f"report={summary['report']} version={summary['version']}")
    print(
        f"events_loaded={summary['events_loaded']} events_eligible={summary['events_eligible']} "
        f"parameter_sets_tested={summary['parameter_sets_tested']} strategy_candidate={summary['strategy_candidate']}"
    )
    print(
        "top_excess_return "
        + " ; ".join(
            f"{row['target_mode']}|{row['max_hold_horizon']}|{row['trigger_basis']}:{row['excess_return_vs_hold_pct']}"
            for row in summary["top_excess_return_candidates"][:15]
        )
    )
    print(
        "top_drawdown_improvement "
        + " ; ".join(
            f"{row['target_mode']}|{row['max_hold_horizon']}|{row['trigger_basis']}:{row['avg_drawdown_improvement_vs_hold_pct']}"
            for row in summary["top_drawdown_improvement_candidates"][:15]
        )
    )
    print(
        "rejected_negative_excess "
        + " ; ".join(
            f"{row['target_mode']}|{row['max_hold_horizon']}|{row['trigger_basis']}:{row['excess_return_vs_hold_pct']}"
            for row in summary["rejected_variants_negative_excess"][:15]
        )
    )
    print(
        "safety "
        "broker_calls=0 broker_writes=0 order_submission=0 executor=none live_trading=false research_only=true"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_events <= 0:
        raise ValueError("--max-events must be greater than zero")
    if args.min_samples <= 0:
        raise ValueError("--min-samples must be greater than zero")

    events, meta = load_events(args)
    parameter_rows: list[dict[str, Any]] = []
    for reload_zone_part, near_zone_threshold_pct, trigger_basis, max_late_distance_above_zone_pct, target_mode, max_hold_horizon, require_aplus_context in itertools.product(
        RELOAD_ZONE_PARTS,
        NEAR_ZONE_THRESHOLD_PCTS,
        TRIGGER_BASES,
        MAX_LATE_DISTANCE_ABOVE_ZONE_PCTS,
        TARGET_MODES,
        MAX_HOLD_HORIZONS,
        REQUIRE_APLUS_CONTEXT_OPTIONS,
    ):
        parameter_rows.append(
            evaluate_parameter_set(
                events,
                {
                    "reload_zone_part": reload_zone_part,
                    "near_zone_threshold_pct": near_zone_threshold_pct,
                    "trigger_basis": trigger_basis,
                    "max_late_distance_above_zone_pct": max_late_distance_above_zone_pct,
                    "target_mode": target_mode,
                    "max_hold_horizon": max_hold_horizon,
                    "require_aplus_context": require_aplus_context,
                },
                fib_guard_safe=bool(meta["fibo_target_modes_point_in_time_safe"]),
                min_samples=int(args.min_samples),
            )
        )

    output_dir = Path(args.output_dir)
    paths = {
        "rows_csv": output_dir / ROWS_CSV,
        "rows_jsonl": output_dir / ROWS_JSONL,
        "top_candidates_csv": output_dir / TOP_CANDIDATES_CSV,
        "rejected_candidates_csv": output_dir / REJECTED_CANDIDATES_CSV,
        "manifest_json": output_dir / MANIFEST_JSON,
    }
    summary = summarize(parameter_rows, meta, args, paths)

    if args.write_files:
        write_csv(paths["rows_csv"], parameter_rows)
        write_jsonl(paths["rows_jsonl"], parameter_rows)
        write_csv(paths["top_candidates_csv"], summary["top_excess_return_candidates"])
        write_csv(paths["rejected_candidates_csv"], summary["rejected_variants_negative_excess"])
        write_json(paths["manifest_json"], summary)

    print_summary(summary, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
