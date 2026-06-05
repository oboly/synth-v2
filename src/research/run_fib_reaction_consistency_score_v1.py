from __future__ import annotations

import argparse
import csv
import json
import signal
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any


REPORT_NAME = "fib_reaction_consistency_score_v1"
ALGORITHM_VERSION = "1.0"
ANALYSIS_VERSION = "1.0"
DEFAULT_INPUT_DIR = Path("data/research/multi_horizon_fib_backtest_v1")
DEFAULT_OUTPUT_DIR = Path("data/research/fib_reaction_consistency_score_v1")
DEFAULT_HEARTBEAT_SECONDS = 5.0
DEFAULT_MIN_VALID_SAMPLE_COUNT = 12
DEFAULT_MIN_STABILITY_BUCKET_SAMPLE = 12
UNKNOWN = "UNKNOWN"
STATUS_VALID = "VALID"
STATUS_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
TIER_SYMBOL_HORIZON_REGIME_BREATH = "SYMBOL_HORIZON_REGIME_BREATH"
TIER_SYMBOL_HORIZON_REGIME = "SYMBOL_HORIZON_REGIME"
TIER_SYMBOL_HORIZON = "SYMBOL_HORIZON"
TIER_HORIZON_BASELINE = "HORIZON_BASELINE"
REGIME_STABILITY_NEUTRAL = 0.5
BREATH_STABILITY_NEUTRAL = 0.5
REGIME_STABILITY_MAX_DEVIATION = 0.35
BREATH_STABILITY_MAX_DEVIATION = 0.35
WEIGHTS = {
    "touch_rate": 0.16,
    "reaction_success_rate": 0.34,
    "fakeout_rate_complement": 0.12,
    "invalidation_rate_complement": 0.18,
    "next_extension_hit_rate": 0.12,
    "regime_stability": 0.05,
    "breath_stability": 0.03,
}
FORBIDDEN_OUTPUT_FIELDS = {
    "fib_reaction_consistency_class",
    "quality_score",
    "confidence_score",
    "generic_quality_score",
}


@dataclass
class RunControl:
    interrupted: bool = False
    interrupt_signal: str | None = None

    def request_interrupt(self, signal_name: str) -> None:
        if self.interrupted:
            return
        self.interrupted = True
        self.interrupt_signal = signal_name


@dataclass
class AggregateCounts:
    sample_count: int = 0
    touch_count: int = 0
    reaction_success_count: int = 0
    fakeout_count: int = 0
    invalidation_count: int = 0
    next_extension_hit_count: int = 0

    def add_row(self, row: dict[str, str]) -> None:
        self.sample_count += 1
        self.touch_count += parse_int(row.get("touch_count"))
        self.reaction_success_count += parse_int(row.get("reaction_success_count"))
        self.fakeout_count += parse_int(row.get("fakeout_count"))
        self.invalidation_count += parse_int(row.get("invalidation_count"))
        self.next_extension_hit_count += parse_int(row.get("next_extension_hit_count"))

    def to_rates(self) -> dict[str, float]:
        if self.sample_count <= 0:
            return {
                "sample_count": 0,
                "touch_rate": 0.0,
                "reaction_success_rate": 0.0,
                "fakeout_rate": 0.0,
                "invalidation_rate": 0.0,
                "next_extension_hit_rate": 0.0,
            }
        count = float(self.sample_count)
        return {
            "sample_count": self.sample_count,
            "touch_rate": self.touch_count / count,
            "reaction_success_rate": self.reaction_success_count / count,
            "fakeout_rate": self.fakeout_count / count,
            "invalidation_rate": self.invalidation_count / count,
            "next_extension_hit_rate": self.next_extension_hit_count / count,
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Transparent fib reaction consistency scoring from research-only "
            "multi_horizon_fib_backtest_v1 outputs."
        )
    )
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--horizons", default=None)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--heartbeat-seconds", type=float, default=DEFAULT_HEARTBEAT_SECONDS)
    parser.add_argument("--min-valid-sample-count", type=int, default=DEFAULT_MIN_VALID_SAMPLE_COUNT)
    parser.add_argument("--min-stability-bucket-sample", type=int, default=DEFAULT_MIN_STABILITY_BUCKET_SAMPLE)
    return parser.parse_args(argv)


def emit(status: str, message: str, **fields: Any) -> None:
    suffix = " ".join(f"{key}={fields[key]}" for key in sorted(fields))
    if suffix:
        print(f"{status} {message} {suffix}", flush=True)
    else:
        print(f"{status} {message}", flush=True)


@contextmanager
def phase(name: str, **fields: Any):
    started_at = time.monotonic()
    emit("PHASE_STARTED", name, **fields)
    try:
        yield
    finally:
        emit("PHASE_FINISHED", name, elapsed_seconds=f"{time.monotonic() - started_at:.2f}", **fields)


@contextmanager
def installed_signal_handlers(control: RunControl):
    previous = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }

    def _handle(signum: int, _frame: Any) -> None:
        name = signal.Signals(signum).name
        control.request_interrupt(name)
        emit("INTERRUPT_REQUESTED", "signal_received", signal=name)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def parse_symbols_arg(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {piece.strip().upper() for piece in str(value).split(",") if piece.strip()}


def parse_horizons_arg(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {piece.strip().upper() for piece in str(value).split(",") if piece.strip()}


def parse_int(value: Any) -> int:
    if value in (None, "", "None"):
        return 0
    return int(str(value))


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def quantize_float(value: float, places: int = 8) -> str:
    return f"{value:.{places}f}"


def build_requested_context_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        str(row.get("market_regime") or UNKNOWN).upper(),
        str(row.get("symbol_regime") or UNKNOWN).upper(),
        str(row.get("breath_phase") or UNKNOWN).upper(),
        str(row.get("breath_alignment") or UNKNOWN).upper(),
    )


def read_manifest(input_dir: Path) -> dict[str, Any]:
    manifest_path = input_dir / "manifest_v1.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing input manifest: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Input manifest must be a JSON object.")
    return payload


def aggregate_outcomes(
    *,
    outcomes_path: Path,
    wanted_symbols: set[str] | None,
    wanted_horizons: set[str] | None,
    heartbeat_seconds: float,
    control: RunControl,
) -> tuple[
    dict[tuple[str, ...], AggregateCounts],
    dict[tuple[str, ...], AggregateCounts],
    dict[tuple[str, ...], AggregateCounts],
    dict[tuple[str, ...], AggregateCounts],
    dict[tuple[str, ...], int],
]:
    if not outcomes_path.exists():
        raise FileNotFoundError(f"Missing fib outcomes input: {outcomes_path}")
    full_map: dict[tuple[str, ...], AggregateCounts] = defaultdict(AggregateCounts)
    regime_map: dict[tuple[str, ...], AggregateCounts] = defaultdict(AggregateCounts)
    base_map: dict[tuple[str, ...], AggregateCounts] = defaultdict(AggregateCounts)
    horizon_map: dict[tuple[str, ...], AggregateCounts] = defaultdict(AggregateCounts)
    requested_counts: dict[tuple[str, ...], int] = defaultdict(int)
    processed_rows = 0
    kept_rows = 0
    last_heartbeat = time.monotonic()
    started_at = time.monotonic()
    with outcomes_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            processed_rows += 1
            if control.interrupted:
                raise KeyboardInterrupt(control.interrupt_signal or "SIGINT")
            symbol = str(row.get("symbol") or "").upper()
            horizon = str(row.get("fib_trading_horizon") or "").upper()
            if wanted_symbols and symbol not in wanted_symbols:
                continue
            if wanted_horizons and horizon not in wanted_horizons:
                continue
            venue = str(row.get("venue") or "")
            quote = str(row.get("quote") or "")
            interval_code = str(row.get("interval_code") or "")
            interval_role = str(row.get("interval_role") or "")
            market_regime, symbol_regime, breath_phase, breath_alignment = build_requested_context_key(row)
            full_key = (
                symbol,
                venue,
                quote,
                horizon,
                interval_code,
                interval_role,
                market_regime,
                symbol_regime,
                breath_phase,
                breath_alignment,
            )
            regime_key = (
                symbol,
                venue,
                quote,
                horizon,
                interval_code,
                interval_role,
                market_regime,
                symbol_regime,
            )
            base_key = (symbol, venue, quote, horizon, interval_code, interval_role)
            horizon_key = (horizon, interval_code, interval_role)
            full_map[full_key].add_row(row)
            regime_map[regime_key].add_row(row)
            base_map[base_key].add_row(row)
            horizon_map[horizon_key].add_row(row)
            requested_counts[full_key] += 1
            kept_rows += 1
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_seconds:
                emit(
                    "HEARTBEAT",
                    "aggregate_outcomes",
                    elapsed_seconds=f"{now - started_at:.2f}",
                    processed_rows=processed_rows,
                    kept_rows=kept_rows,
                )
                last_heartbeat = now
    emit(
        "FILE_READ_COMPLETED",
        "fib_level_outcomes_v1.csv",
        elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
        processed_rows=processed_rows,
        kept_rows=kept_rows,
        full_bucket_count=len(full_map),
    )
    return full_map, regime_map, base_map, horizon_map, requested_counts


def _weighted_mean_abs_deviation(
    items: list[tuple[int, float]],
    base_rate: float,
    max_deviation: float,
    neutral: float,
) -> float:
    if len(items) < 2:
        return neutral
    total_weight = sum(weight for weight, _ in items)
    if total_weight <= 0:
        return neutral
    weighted_diff = sum(weight * abs(rate - base_rate) for weight, rate in items) / total_weight
    return clamp01(1.0 - (weighted_diff / max_deviation))


def compute_stability_maps(
    *,
    base_map: dict[tuple[str, ...], AggregateCounts],
    regime_map: dict[tuple[str, ...], AggregateCounts],
    full_map: dict[tuple[str, ...], AggregateCounts],
    min_bucket_sample: int,
) -> tuple[dict[tuple[str, ...], float], dict[tuple[str, ...], float], dict[tuple[str, ...], int], dict[tuple[str, ...], int]]:
    regime_stability_map: dict[tuple[str, ...], float] = {}
    breath_stability_map: dict[tuple[str, ...], float] = {}
    regime_bucket_count_map: dict[tuple[str, ...], int] = {}
    breath_bucket_count_map: dict[tuple[str, ...], int] = {}

    regime_groups: dict[tuple[str, ...], list[tuple[int, float]]] = defaultdict(list)
    for key, counts in regime_map.items():
        if counts.sample_count < min_bucket_sample:
            continue
        base_key = key[:6]
        regime_groups[base_key].append((counts.sample_count, counts.to_rates()["reaction_success_rate"]))

    breath_groups: dict[tuple[str, ...], list[tuple[int, float]]] = defaultdict(list)
    for key, counts in full_map.items():
        if counts.sample_count < min_bucket_sample:
            continue
        base_key = key[:6]
        breath_pair = key[8:10]
        breath_groups[(base_key, breath_pair)].append((counts.sample_count, counts.to_rates()["reaction_success_rate"]))

    collapsed_breath_groups: dict[tuple[str, ...], list[tuple[int, float]]] = defaultdict(list)
    for (base_key, _breath_pair), items in breath_groups.items():
        total_sample = sum(sample for sample, _rate in items)
        if total_sample < min_bucket_sample:
            continue
        weighted_rate = sum(sample * rate for sample, rate in items) / total_sample
        collapsed_breath_groups[base_key].append((total_sample, weighted_rate))

    for base_key, counts in base_map.items():
        base_rate = counts.to_rates()["reaction_success_rate"]
        regime_items = regime_groups.get(base_key, [])
        breath_items = collapsed_breath_groups.get(base_key, [])
        regime_stability_map[base_key] = _weighted_mean_abs_deviation(
            regime_items,
            base_rate,
            REGIME_STABILITY_MAX_DEVIATION,
            REGIME_STABILITY_NEUTRAL,
        )
        breath_stability_map[base_key] = _weighted_mean_abs_deviation(
            breath_items,
            base_rate,
            BREATH_STABILITY_MAX_DEVIATION,
            BREATH_STABILITY_NEUTRAL,
        )
        regime_bucket_count_map[base_key] = len(regime_items)
        breath_bucket_count_map[base_key] = len(breath_items)
    return regime_stability_map, breath_stability_map, regime_bucket_count_map, breath_bucket_count_map


def build_score_row(
    *,
    symbol: str,
    venue: str,
    quote: str,
    fib_trading_horizon: str,
    interval_code: str,
    interval_role: str,
    requested_context: tuple[str, str, str, str],
    resolved_context: tuple[str, str, str, str],
    requested_sample_count: int,
    resolved_counts: AggregateCounts,
    resolved_context_tier: str,
    min_valid_sample_count: int,
    regime_stability: float,
    breath_stability: float,
    regime_bucket_count: int,
    breath_bucket_count: int,
) -> dict[str, Any]:
    rates = resolved_counts.to_rates()
    status = STATUS_VALID if resolved_counts.sample_count >= min_valid_sample_count else STATUS_INSUFFICIENT_SAMPLE
    if status == STATUS_VALID:
        raw_score = (
            WEIGHTS["touch_rate"] * rates["touch_rate"]
            + WEIGHTS["reaction_success_rate"] * rates["reaction_success_rate"]
            + WEIGHTS["fakeout_rate_complement"] * (1.0 - rates["fakeout_rate"])
            + WEIGHTS["invalidation_rate_complement"] * (1.0 - rates["invalidation_rate"])
            + WEIGHTS["next_extension_hit_rate"] * rates["next_extension_hit_rate"]
            + WEIGHTS["regime_stability"] * regime_stability
            + WEIGHTS["breath_stability"] * breath_stability
        )
        score_value: float | None = clamp01(raw_score) * 100.0
    else:
        score_value = None
    row = {
        "symbol": symbol,
        "venue": venue,
        "quote": quote,
        "fib_trading_horizon": fib_trading_horizon,
        "interval_code": interval_code,
        "interval_role": interval_role,
        "market_regime": requested_context[0],
        "symbol_regime": requested_context[1],
        "breath_phase": requested_context[2],
        "breath_alignment": requested_context[3],
        "resolved_market_regime": resolved_context[0],
        "resolved_symbol_regime": resolved_context[1],
        "resolved_breath_phase": resolved_context[2],
        "resolved_breath_alignment": resolved_context[3],
        "resolved_context_tier": resolved_context_tier,
        "requested_sample_count": requested_sample_count,
        "sample_count": resolved_counts.sample_count,
        "touch_rate": quantize_float(rates["touch_rate"]),
        "reaction_success_rate": quantize_float(rates["reaction_success_rate"]),
        "fakeout_rate": quantize_float(rates["fakeout_rate"]),
        "invalidation_rate": quantize_float(rates["invalidation_rate"]),
        "next_extension_hit_rate": quantize_float(rates["next_extension_hit_rate"]),
        "regime_stability": quantize_float(regime_stability),
        "breath_stability": quantize_float(breath_stability),
        "regime_bucket_count_used": regime_bucket_count,
        "breath_bucket_count_used": breath_bucket_count,
        "weight_touch_rate": quantize_float(WEIGHTS["touch_rate"]),
        "weight_reaction_success_rate": quantize_float(WEIGHTS["reaction_success_rate"]),
        "weight_fakeout_rate_complement": quantize_float(WEIGHTS["fakeout_rate_complement"]),
        "weight_invalidation_rate_complement": quantize_float(WEIGHTS["invalidation_rate_complement"]),
        "weight_next_extension_hit_rate": quantize_float(WEIGHTS["next_extension_hit_rate"]),
        "weight_regime_stability": quantize_float(WEIGHTS["regime_stability"]),
        "weight_breath_stability": quantize_float(WEIGHTS["breath_stability"]),
        "fib_reaction_consistency_score": "" if score_value is None else quantize_float(score_value, places=6),
        "fib_reaction_consistency_status": status,
    }
    forbidden = FORBIDDEN_OUTPUT_FIELDS.intersection(row.keys())
    if forbidden:
        raise RuntimeError(f"Forbidden output fields present: {sorted(forbidden)}")
    return row


def resolve_context_candidate(
    *,
    symbol: str,
    venue: str,
    quote: str,
    fib_trading_horizon: str,
    interval_code: str,
    interval_role: str,
    requested_context: tuple[str, str, str, str],
    full_map: dict[tuple[str, ...], AggregateCounts],
    regime_map: dict[tuple[str, ...], AggregateCounts],
    base_map: dict[tuple[str, ...], AggregateCounts],
    horizon_map: dict[tuple[str, ...], AggregateCounts],
    min_valid_sample_count: int,
) -> tuple[AggregateCounts, str, tuple[str, str, str, str]]:
    full_key = (
        symbol,
        venue,
        quote,
        fib_trading_horizon,
        interval_code,
        interval_role,
        requested_context[0],
        requested_context[1],
        requested_context[2],
        requested_context[3],
    )
    regime_key = (
        symbol,
        venue,
        quote,
        fib_trading_horizon,
        interval_code,
        interval_role,
        requested_context[0],
        requested_context[1],
    )
    base_key = (symbol, venue, quote, fib_trading_horizon, interval_code, interval_role)
    horizon_key = (fib_trading_horizon, interval_code, interval_role)
    candidates: list[tuple[AggregateCounts | None, str, tuple[str, str, str, str]]] = [
        (full_map.get(full_key), TIER_SYMBOL_HORIZON_REGIME_BREATH, requested_context),
        (
            regime_map.get(regime_key),
            TIER_SYMBOL_HORIZON_REGIME,
            (requested_context[0], requested_context[1], UNKNOWN, UNKNOWN),
        ),
        (base_map.get(base_key), TIER_SYMBOL_HORIZON, (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN)),
        (horizon_map.get(horizon_key), TIER_HORIZON_BASELINE, (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN)),
    ]
    best_fallback: AggregateCounts | None = None
    best_tier = TIER_HORIZON_BASELINE
    best_context = (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN)
    for counts, tier, resolved_context in candidates:
        if counts is None:
            continue
        if best_fallback is None:
            best_fallback = counts
            best_tier = tier
            best_context = resolved_context
        if counts.sample_count >= min_valid_sample_count:
            return counts, tier, resolved_context
    if best_fallback is None:
        return AggregateCounts(), best_tier, best_context
    return best_fallback, best_tier, best_context


def build_rows(
    *,
    full_map: dict[tuple[str, ...], AggregateCounts],
    regime_map: dict[tuple[str, ...], AggregateCounts],
    base_map: dict[tuple[str, ...], AggregateCounts],
    horizon_map: dict[tuple[str, ...], AggregateCounts],
    requested_counts: dict[tuple[str, ...], int],
    min_valid_sample_count: int,
    min_stability_bucket_sample: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    regime_stability_map, breath_stability_map, regime_bucket_counts, breath_bucket_counts = compute_stability_maps(
        base_map=base_map,
        regime_map=regime_map,
        full_map=full_map,
        min_bucket_sample=min_stability_bucket_sample,
    )
    rows: list[dict[str, Any]] = []
    for base_key in sorted(base_map):
        symbol, venue, quote, horizon, interval_code, interval_role = base_key
        requested_context = (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN)
        counts = base_map[base_key]
        rows.append(
            build_score_row(
                symbol=symbol,
                venue=venue,
                quote=quote,
                fib_trading_horizon=horizon,
                interval_code=interval_code,
                interval_role=interval_role,
                requested_context=requested_context,
                resolved_context=requested_context,
                requested_sample_count=counts.sample_count,
                resolved_counts=counts,
                resolved_context_tier=TIER_SYMBOL_HORIZON,
                min_valid_sample_count=min_valid_sample_count,
                regime_stability=regime_stability_map.get(base_key, REGIME_STABILITY_NEUTRAL),
                breath_stability=breath_stability_map.get(base_key, BREATH_STABILITY_NEUTRAL),
                regime_bucket_count=regime_bucket_counts.get(base_key, 0),
                breath_bucket_count=breath_bucket_counts.get(base_key, 0),
            )
        )
    context_rows: list[dict[str, Any]] = []
    for full_key in sorted(full_map):
        symbol, venue, quote, horizon, interval_code, interval_role = full_key[:6]
        requested_context = full_key[6:10]
        resolved_counts, resolved_tier, resolved_context = resolve_context_candidate(
            symbol=symbol,
            venue=venue,
            quote=quote,
            fib_trading_horizon=horizon,
            interval_code=interval_code,
            interval_role=interval_role,
            requested_context=requested_context,
            full_map=full_map,
            regime_map=regime_map,
            base_map=base_map,
            horizon_map=horizon_map,
            min_valid_sample_count=min_valid_sample_count,
        )
        base_key = full_key[:6]
        context_rows.append(
            build_score_row(
                symbol=symbol,
                venue=venue,
                quote=quote,
                fib_trading_horizon=horizon,
                interval_code=interval_code,
                interval_role=interval_role,
                requested_context=requested_context,
                resolved_context=resolved_context,
                requested_sample_count=requested_counts.get(full_key, 0),
                resolved_counts=resolved_counts,
                resolved_context_tier=resolved_tier,
                min_valid_sample_count=min_valid_sample_count,
                regime_stability=regime_stability_map.get(base_key, REGIME_STABILITY_NEUTRAL),
                breath_stability=breath_stability_map.get(base_key, BREATH_STABILITY_NEUTRAL),
                regime_bucket_count=regime_bucket_counts.get(base_key, 0),
                breath_bucket_count=breath_bucket_counts.get(base_key, 0),
            )
        )
    return rows, context_rows


def percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, int((len(sorted_values) - 1) * fraction)))
    return sorted_values[index]


def build_distribution_rows(rows: list[dict[str, Any]], *, scope: str) -> list[dict[str, Any]]:
    components = [
        "sample_count",
        "touch_rate",
        "reaction_success_rate",
        "fakeout_rate",
        "invalidation_rate",
        "next_extension_hit_rate",
        "regime_stability",
        "breath_stability",
        "fib_reaction_consistency_score",
    ]
    result: list[dict[str, Any]] = []
    for component in components:
        values: list[float] = []
        for row in rows:
            raw = row.get(component)
            if raw in ("", None):
                continue
            values.append(float(raw))
        values.sort()
        if not values:
            continue
        result.append(
            {
                "row_scope": scope,
                "component_name": component,
                "row_count": len(values),
                "min_value": quantize_float(values[0], places=6),
                "p10_value": quantize_float(percentile(values, 0.10), places=6),
                "p25_value": quantize_float(percentile(values, 0.25), places=6),
                "p50_value": quantize_float(percentile(values, 0.50), places=6),
                "p75_value": quantize_float(percentile(values, 0.75), places=6),
                "p90_value": quantize_float(percentile(values, 0.90), places=6),
                "max_value": quantize_float(values[-1], places=6),
                "mean_value": quantize_float(fmean(values), places=6),
                "component_weight": quantize_float(WEIGHTS.get(component, 0.0), places=6),
            }
        )
    return result


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_manifest(
    *,
    input_dir: Path,
    input_manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    distribution_rows: list[dict[str, Any]],
    min_valid_sample_count: int,
    min_stability_bucket_sample: int,
) -> dict[str, Any]:
    valid_count = sum(1 for row in rows if row["fib_reaction_consistency_status"] == STATUS_VALID)
    valid_context_count = sum(1 for row in context_rows if row["fib_reaction_consistency_status"] == STATUS_VALID)
    return {
        "report_name": REPORT_NAME,
        "analysis_version": ANALYSIS_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "input_dir": str(input_dir),
        "input_report_name": input_manifest.get("report_name"),
        "input_analysis_version": input_manifest.get("analysis_version"),
        "input_algorithm_version": input_manifest.get("algorithm_version"),
        "symbols": input_manifest.get("symbols", []),
        "horizons": input_manifest.get("horizons", []),
        "row_counts": {
            "fib_reaction_consistency_rows": len(rows),
            "fib_reaction_consistency_context_rows": len(context_rows),
            "score_component_distribution_rows": len(distribution_rows),
        },
        "valid_counts": {
            "fib_reaction_consistency_rows": valid_count,
            "fib_reaction_consistency_context_rows": valid_context_count,
        },
        "min_valid_sample_count": min_valid_sample_count,
        "min_stability_bucket_sample": min_stability_bucket_sample,
        "score_formula": {
            "score_range": "0..100",
            "status_values": [STATUS_VALID, STATUS_INSUFFICIENT_SAMPLE],
            "formula": (
                "100 * (0.16*touch_rate + 0.34*reaction_success_rate + "
                "0.12*(1-fakeout_rate) + 0.18*(1-invalidation_rate) + "
                "0.12*next_extension_hit_rate + 0.05*regime_stability + "
                "0.03*breath_stability)"
            ),
            "weights": WEIGHTS,
            "regime_stability_max_deviation": REGIME_STABILITY_MAX_DEVIATION,
            "breath_stability_max_deviation": BREATH_STABILITY_MAX_DEVIATION,
            "regime_stability_neutral": REGIME_STABILITY_NEUTRAL,
            "breath_stability_neutral": BREATH_STABILITY_NEUTRAL,
            "fallback_tiers": [
                TIER_SYMBOL_HORIZON_REGIME_BREATH,
                TIER_SYMBOL_HORIZON_REGIME,
                TIER_SYMBOL_HORIZON,
                TIER_HORIZON_BASELINE,
            ],
        },
        "safety_markers": input_manifest.get("safety_markers", {}),
    }


def run_score(
    *,
    input_dir: Path,
    output_dir: Path,
    symbols: set[str] | None,
    horizons: set[str] | None,
    heartbeat_seconds: float,
    min_valid_sample_count: int,
    min_stability_bucket_sample: int,
    write_files: bool,
    control: RunControl,
) -> dict[str, Any]:
    with phase("inspect_input_manifest"):
        input_manifest = read_manifest(input_dir)
    with phase("aggregate_outcomes"):
        full_map, regime_map, base_map, horizon_map, requested_counts = aggregate_outcomes(
            outcomes_path=input_dir / "fib_level_outcomes_v1.csv",
            wanted_symbols=symbols,
            wanted_horizons=horizons,
            heartbeat_seconds=heartbeat_seconds,
            control=control,
        )
    with phase("build_score_rows"):
        rows, context_rows = build_rows(
            full_map=full_map,
            regime_map=regime_map,
            base_map=base_map,
            horizon_map=horizon_map,
            requested_counts=requested_counts,
            min_valid_sample_count=min_valid_sample_count,
            min_stability_bucket_sample=min_stability_bucket_sample,
        )
    with phase("build_component_distributions"):
        distribution_rows = build_distribution_rows(rows, scope="rows")
        distribution_rows.extend(build_distribution_rows(context_rows, scope="context_rows"))
    manifest = build_manifest(
        input_dir=input_dir,
        input_manifest=input_manifest,
        rows=rows,
        context_rows=context_rows,
        distribution_rows=distribution_rows,
        min_valid_sample_count=min_valid_sample_count,
        min_stability_bucket_sample=min_stability_bucket_sample,
    )
    if write_files:
        with phase("write_outputs", output_dir=str(output_dir)):
            write_csv(output_dir / "fib_reaction_consistency_rows_v1.csv", rows)
            write_csv(output_dir / "fib_reaction_consistency_context_rows_v1.csv", context_rows)
            write_csv(output_dir / "score_component_distribution_v1.csv", distribution_rows)
            (output_dir / "manifest_v1.json").parent.mkdir(parents=True, exist_ok=True)
            (output_dir / "manifest_v1.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
    return {
        "rows": rows,
        "context_rows": context_rows,
        "distribution_rows": distribution_rows,
        "manifest": manifest,
    }


def main(argv: list[str] | None = None) -> int:
    started_at = time.monotonic()
    args = parse_args(argv)
    symbols = parse_symbols_arg(args.symbols)
    horizons = parse_horizons_arg(args.horizons)
    control = RunControl()
    emit(
        "STARTED",
        "run_fib_reaction_consistency_score_v1",
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        scope=",".join(sorted(symbols)) if symbols else "ALL_SYMBOLS",
        horizons=",".join(sorted(horizons)) if horizons else "ALL_HORIZONS",
        workers=1,
        broker_calls=0,
        broker_writes=0,
        order_submission=0,
        decision_gate="none",
        execution_planner="none",
        executor="none",
    )
    try:
        with installed_signal_handlers(control):
            result = run_score(
                input_dir=Path(args.input_dir),
                output_dir=Path(args.output_dir),
                symbols=symbols,
                horizons=horizons,
                heartbeat_seconds=args.heartbeat_seconds,
                min_valid_sample_count=args.min_valid_sample_count,
                min_stability_bucket_sample=args.min_stability_bucket_sample,
                write_files=args.write_files,
                control=control,
            )
    except KeyboardInterrupt:
        emit(
            "INTERRUPTED",
            "run_fib_reaction_consistency_score_v1",
            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
            signal=control.interrupt_signal or "SIGINT",
        )
        return 130
    except Exception as exc:
        emit(
            "FAILED",
            "run_fib_reaction_consistency_score_v1",
            elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
            error=f"{exc.__class__.__name__}:{exc}",
        )
        return 1

    manifest = result["manifest"]
    if args.output == "json":
        print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(f"rows={manifest['row_counts']['fib_reaction_consistency_rows']}")
        print(f"context_rows={manifest['row_counts']['fib_reaction_consistency_context_rows']}")
        print(f"distribution_rows={manifest['row_counts']['score_component_distribution_rows']}")
        print(f"valid_rows={manifest['valid_counts']['fib_reaction_consistency_rows']}")
        print(f"valid_context_rows={manifest['valid_counts']['fib_reaction_consistency_context_rows']}")
        print("broker_writes=0 order_submission=0 executor=none db_writes=0")
    emit(
        "FINISHED",
        "run_fib_reaction_consistency_score_v1",
        elapsed_seconds=f"{time.monotonic() - started_at:.2f}",
        broker_writes=0,
        order_submission=0,
        executor="none",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
