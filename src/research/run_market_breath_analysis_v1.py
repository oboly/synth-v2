from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "market_breath_analysis_v1"
VERSION = "0.1"

PHASES = [
    "INHALE_ACCUMULATION",
    "HOLD_COMPRESSION",
    "EXHALE_EXPANSION",
    "OVERBREATH_EXTENSION",
    "COLLAPSE_RESET",
    "NEUTRAL_TRANSITION",
    "INSUFFICIENT_DATA",
]

STATES = ["EARLY", "FORMING", "CONFIRMED", "LATE", "RESET", "UNKNOWN"]

INTERVAL_SECONDS = {
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}

OUTPUT_ROWS = "market_breath_observations_v1.jsonl"
OUTPUT_SUMMARY = "market_breath_summary_v1.json"


@dataclass(frozen=True)
class Asset:
    asset_id: int
    symbol: str


@dataclass(frozen=True)
class Candle:
    asset_id: int
    close_ts_utc: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build latest Market Breath V1 observations from Synth market candles "
            "(research-only, market-only, account-agnostic)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--lookback-candles", type=int, default=120)
    parser.add_argument("--asof-ts", default=None)
    parser.add_argument("--output-dir", default="data/research/market_breath_analysis_v1")
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    return parser.parse_args(argv)


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC).replace(tzinfo=None)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def fmt_ts(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def f(value: Any) -> float:
    return float(value) if value is not None else 0.0


def round_or_none(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def signed_clamp(value: float) -> float:
    return max(-100.0, min(100.0, value))


def safe_return(candles: list[Candle], periods: int) -> float | None:
    if len(candles) <= periods:
        return None
    old = candles[-periods - 1].close_price
    new = candles[-1].close_price
    if old <= 0:
        return None
    return (new / old - 1.0) * 100.0


def latest_asof_ts(conn, venue: str, interval_code: str) -> datetime:
    sql = """
        SELECT MAX(close_ts_utc) AS max_close_ts_utc
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code))
        row = cur.fetchone()
    if not row or row["max_close_ts_utc"] is None:
        raise RuntimeError(f"No candles found for venue={venue} interval={interval_code}")
    return row["max_close_ts_utc"]


def fetch_assets(conn) -> list[Asset]:
    sql = """
        SELECT asset_id, symbol
        FROM asset
        WHERE is_enabled = 1
          AND is_tradeable = 1
        ORDER BY asset_id
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [Asset(asset_id=int(r["asset_id"]), symbol=str(r["symbol"]).upper()) for r in rows]


def fetch_candles(
    conn,
    *,
    assets: list[Asset],
    venue: str,
    interval_code: str,
    asof_ts: datetime,
    lookback_candles: int,
) -> dict[int, list[Candle]]:
    if not assets:
        return {}

    interval_seconds = INTERVAL_SECONDS.get(interval_code, 4 * 60 * 60)
    window_start = asof_ts - timedelta(seconds=interval_seconds * lookback_candles * 4)
    asset_ids = [a.asset_id for a in assets]
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT
            asset_id,
            close_ts_utc,
            open_price,
            high_price,
            low_price,
            close_price
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc > %s
          AND close_ts_utc <= %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, interval_code, window_start, asof_ts, *asset_ids]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    grouped: dict[int, list[Candle]] = defaultdict(list)
    for row in rows:
        grouped[int(row["asset_id"])].append(
            Candle(
                asset_id=int(row["asset_id"]),
                close_ts_utc=row["close_ts_utc"],
                open_price=f(row["open_price"]),
                high_price=f(row["high_price"]),
                low_price=f(row["low_price"]),
                close_price=f(row["close_price"]),
            )
        )

    return {asset_id: candles[-lookback_candles:] for asset_id, candles in grouped.items()}


def range_pct(candle: Candle) -> float:
    if candle.close_price <= 0:
        return 0.0
    return (candle.high_price - candle.low_price) / candle.close_price * 100.0


def true_range_pct(candles: list[Candle], idx: int) -> float:
    candle = candles[idx]
    if candle.close_price <= 0:
        return 0.0
    if idx == 0:
        true_range = candle.high_price - candle.low_price
    else:
        prev_close = candles[idx - 1].close_price
        true_range = max(
            candle.high_price - candle.low_price,
            abs(candle.high_price - prev_close),
            abs(candle.low_price - prev_close),
        )
    return true_range / candle.close_price * 100.0


def score_low_vs_baseline(current: float, baseline: float) -> float:
    if baseline <= 0:
        return 50.0
    return clamp((1.0 - current / baseline) * 100.0)


def score_high_vs_baseline(current: float, baseline: float) -> float:
    if baseline <= 0:
        return 50.0
    return clamp((current / baseline - 1.0) * 100.0)


def momentum_score(r3: float | None, r6: float | None, r12: float | None) -> float:
    vals = [v for v in [r3, r6, r12] if v is not None]
    if not vals:
        return 0.0
    weighted = (0.35 * (r3 or 0.0)) + (0.40 * (r6 or 0.0)) + (0.25 * (r12 or 0.0))
    consistency = sum(1 for v in vals if v > 0) - sum(1 for v in vals if v < 0)
    return signed_clamp(weighted * 8.0 + consistency * 8.0)


def reversal_pressure_score(
    *,
    r1: float | None,
    r3: float | None,
    r6: float | None,
    r12: float | None,
    expansion_score: float,
    current_range_pct: float,
    median_range_pct: float,
) -> float:
    prior_positive = (r6 or 0.0) > 3.0 or (r12 or 0.0) > 5.0
    short_turn = (r1 or 0.0) < 0.0 or (r3 or 0.0) < 0.0
    range_expands = median_range_pct > 0 and current_range_pct > median_range_pct * 1.25
    score = 0.0
    if prior_positive and short_turn:
        score += 45.0
    if expansion_score >= 60.0 and short_turn:
        score += 25.0
    if range_expands and short_turn:
        score += 20.0
    if (r1 or 0.0) < -3.0:
        score += 10.0
    return clamp(score)


def relative_strength_score(r6: float | None, r12: float | None, btc_r6: float | None, btc_r12: float | None) -> float:
    if r6 is None and r12 is None:
        return 0.0
    spread6 = (r6 or 0.0) - (btc_r6 or 0.0)
    spread12 = (r12 or 0.0) - (btc_r12 or 0.0)
    return signed_clamp((0.55 * spread6 + 0.45 * spread12) * 10.0)


def btc_alignment_score(r6: float | None, r12: float | None, btc_r6: float | None, btc_r12: float | None) -> float:
    asset_direction = (r6 or 0.0) + 0.5 * (r12 or 0.0)
    btc_direction = (btc_r6 or 0.0) + 0.5 * (btc_r12 or 0.0)
    if abs(asset_direction) < 0.1 or abs(btc_direction) < 0.1:
        return 0.0
    if asset_direction * btc_direction > 0:
        return clamp(abs(asset_direction) * 8.0, 0.0, 100.0)
    return -clamp(abs(asset_direction - btc_direction) * 6.0, 0.0, 100.0)


def phase_and_state(
    *,
    compression: float,
    expansion: float,
    momentum: float,
    reversal_pressure: float,
    relative_strength: float,
) -> tuple[str, str]:
    if momentum < -25.0 and reversal_pressure >= 45.0:
        return "COLLAPSE_RESET", "RESET"
    if expansion >= 65.0 and momentum >= 55.0 and reversal_pressure >= 45.0:
        return "OVERBREATH_EXTENSION", "LATE"
    if expansion >= 55.0 and momentum > 20.0 and relative_strength > 0.0:
        state = "CONFIRMED" if expansion >= 70.0 and momentum >= 35.0 else "FORMING"
        return "EXHALE_EXPANSION", state
    if compression >= 60.0 and expansion < 35.0 and abs(momentum) <= 20.0:
        state = "CONFIRMED" if compression >= 75.0 else "FORMING"
        return "HOLD_COMPRESSION", state
    if compression >= 45.0 and 5.0 <= momentum <= 35.0 and relative_strength > 0.0:
        state = "FORMING" if momentum < 20.0 else "CONFIRMED"
        return "INHALE_ACCUMULATION", state
    return "NEUTRAL_TRANSITION", "UNKNOWN"


def breath_score(
    *,
    compression: float,
    expansion: float,
    momentum: float,
    reversal_pressure: float,
    relative_strength: float,
    btc_alignment: float,
    breadth_alignment: float | None,
) -> float:
    breadth = breadth_alignment if breadth_alignment is not None else 0.0
    raw = (
        50.0
        + expansion * 0.18
        + compression * 0.08
        + momentum * 0.22
        + relative_strength * 0.16
        + btc_alignment * 0.08
        + breadth * 0.08
        - reversal_pressure * 0.16
    )
    return clamp(raw)


def confidence(valid_count: int, lookback_candles: int, invalid_reason: str | None) -> float:
    if invalid_reason:
        return 0.0
    coverage = valid_count / max(lookback_candles, 1)
    return round(clamp(coverage * 100.0), 6)


def build_base_observation(
    *,
    asset: Asset,
    candles: list[Candle],
    venue: str,
    interval_code: str,
    lookback_candles: int,
    asof_ts: datetime,
    btc_r6: float | None,
    btc_r12: float | None,
) -> dict[str, Any]:
    min_required = max(24, 13)
    invalid_reason: str | None = None
    if len(candles) < min_required:
        invalid_reason = f"insufficient_candles:{len(candles)}<{min_required}"

    if invalid_reason:
        return {
            "venue": venue,
            "interval_code": interval_code,
            "asset_id": asset.asset_id,
            "symbol": asset.symbol,
            "asof_ts_utc": fmt_ts(asof_ts),
            "lookback_candles": lookback_candles,
            "close_price": None,
            "return_1": None,
            "return_3": None,
            "return_6": None,
            "return_12": None,
            "atr_pct_proxy": None,
            "range_pct": None,
            "compression_score": None,
            "expansion_score": None,
            "momentum_score": None,
            "reversal_pressure_score": None,
            "relative_strength_score": None,
            "btc_alignment_score": None,
            "breadth_alignment_score": None,
            "market_breath_phase": "INSUFFICIENT_DATA",
            "market_breath_state": "UNKNOWN",
            "market_breath_score": None,
            "market_breath_confidence": 0.0,
            "invalid_reason": invalid_reason,
        }

    r1 = safe_return(candles, 1)
    r3 = safe_return(candles, 3)
    r6 = safe_return(candles, 6)
    r12 = safe_return(candles, 12)
    ranges = [range_pct(c) for c in candles[-30:]]
    current_range = range_pct(candles[-1])
    median_range = median(ranges) if ranges else current_range
    atr_series = [true_range_pct(candles, i) for i in range(max(0, len(candles) - 14), len(candles))]
    atr_proxy = sum(atr_series) / len(atr_series) if atr_series else current_range
    atr_baseline_series = [true_range_pct(candles, i) for i in range(max(0, len(candles) - 60), len(candles))]
    atr_median = median(atr_baseline_series) if atr_baseline_series else atr_proxy

    compression = clamp(0.55 * score_low_vs_baseline(current_range, median_range) + 0.45 * score_low_vs_baseline(atr_proxy, atr_median))
    return_baseline = median([abs(safe_return(candles[: i + 1], 3) or 0.0) for i in range(12, len(candles))]) or 0.01
    expansion = clamp(0.45 * score_high_vs_baseline(current_range, median_range) + 0.35 * score_high_vs_baseline(abs(r3 or 0.0), return_baseline) + 0.20 * score_high_vs_baseline(atr_proxy, atr_median))
    momentum = momentum_score(r3, r6, r12)
    reversal = reversal_pressure_score(
        r1=r1,
        r3=r3,
        r6=r6,
        r12=r12,
        expansion_score=expansion,
        current_range_pct=current_range,
        median_range_pct=median_range,
    )
    relative = relative_strength_score(r6, r12, btc_r6, btc_r12)
    btc_align = btc_alignment_score(r6, r12, btc_r6, btc_r12)
    phase, state = phase_and_state(
        compression=compression,
        expansion=expansion,
        momentum=momentum,
        reversal_pressure=reversal,
        relative_strength=relative,
    )

    return {
        "venue": venue,
        "interval_code": interval_code,
        "asset_id": asset.asset_id,
        "symbol": asset.symbol,
        "asof_ts_utc": fmt_ts(asof_ts),
        "lookback_candles": lookback_candles,
        "close_price": round_or_none(candles[-1].close_price, 10),
        "return_1": round_or_none(r1),
        "return_3": round_or_none(r3),
        "return_6": round_or_none(r6),
        "return_12": round_or_none(r12),
        "atr_pct_proxy": round_or_none(atr_proxy),
        "range_pct": round_or_none(current_range),
        "compression_score": round_or_none(compression),
        "expansion_score": round_or_none(expansion),
        "momentum_score": round_or_none(momentum),
        "reversal_pressure_score": round_or_none(reversal),
        "relative_strength_score": round_or_none(relative),
        "btc_alignment_score": round_or_none(btc_align),
        "breadth_alignment_score": None,
        "market_breath_phase": phase,
        "market_breath_state": state,
        "market_breath_score": None,
        "market_breath_confidence": None,
        "invalid_reason": None,
    }


def add_breadth_and_scores(rows: list[dict[str, Any]], lookback_candles: int) -> list[dict[str, Any]]:
    valid_returns = [r["return_6"] for r in rows if r.get("return_6") is not None]
    positive_ratio = sum(1 for r in valid_returns if r > 0) / len(valid_returns) if valid_returns else None
    breadth_direction = 0
    if positive_ratio is not None:
        if positive_ratio >= 0.55:
            breadth_direction = 1
        elif positive_ratio <= 0.45:
            breadth_direction = -1

    out: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        if row["market_breath_phase"] == "INSUFFICIENT_DATA":
            out.append(row)
            continue
        r6 = row.get("return_6") or 0.0
        asset_direction = 1 if r6 > 0 else -1 if r6 < 0 else 0
        if breadth_direction == 0 or asset_direction == 0:
            breadth_score = 0.0
        elif asset_direction == breadth_direction:
            breadth_score = clamp(abs(r6) * 8.0)
        else:
            breadth_score = -clamp(abs(r6) * 8.0)

        row["breadth_alignment_score"] = round_or_none(breadth_score)
        row["market_breath_score"] = round_or_none(
            breath_score(
                compression=row["compression_score"] or 0.0,
                expansion=row["expansion_score"] or 0.0,
                momentum=row["momentum_score"] or 0.0,
                reversal_pressure=row["reversal_pressure_score"] or 0.0,
                relative_strength=row["relative_strength_score"] or 0.0,
                btc_alignment=row["btc_alignment_score"] or 0.0,
                breadth_alignment=breadth_score,
            )
        )
        row["market_breath_confidence"] = confidence(lookback_candles, lookback_candles, row.get("invalid_reason"))
        out.append(row)
    return out


def top_phase(rows: list[dict[str, Any]], phase: str, top_n: int = 8) -> list[dict[str, Any]]:
    candidates = [r for r in rows if r["market_breath_phase"] == phase and r.get("market_breath_score") is not None]
    candidates.sort(key=lambda r: (r["market_breath_score"], r.get("relative_strength_score") or 0.0), reverse=True)
    return [
        {
            "symbol": r["symbol"],
            "asset_id": r["asset_id"],
            "market_breath_score": r["market_breath_score"],
            "market_breath_state": r["market_breath_state"],
            "return_6": r["return_6"],
            "return_12": r["return_12"],
            "relative_strength_score": r["relative_strength_score"],
        }
        for r in candidates[:top_n]
    ]


def build_summary(
    rows: list[dict[str, Any]],
    *,
    venue: str,
    interval_code: str,
    asof_ts: datetime,
    output_paths: dict[str, str],
    wrote_files: bool,
) -> dict[str, Any]:
    phase_counts = dict(Counter(r["market_breath_phase"] for r in rows))
    state_counts = dict(Counter(r["market_breath_state"] for r in rows))
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "scope": "research-only market-only account-agnostic",
        "venue": venue,
        "interval_code": interval_code,
        "asof_ts_utc": fmt_ts(asof_ts),
        "assets_processed": len(rows),
        "observations_written": len(rows) if wrote_files else 0,
        "phase_counts": {phase: phase_counts.get(phase, 0) for phase in PHASES},
        "state_counts": {state: state_counts.get(state, 0) for state in STATES},
        "top_exhale_expansion": top_phase(rows, "EXHALE_EXPANSION"),
        "top_inhale_accumulation": top_phase(rows, "INHALE_ACCUMULATION"),
        "top_hold_compression": top_phase(rows, "HOLD_COMPRESSION"),
        "top_overbreath_extension": top_phase(rows, "OVERBREATH_EXTENSION"),
        "top_collapse_reset": top_phase(rows, "COLLAPSE_RESET"),
        "insufficient_data_count": phase_counts.get("INSUFFICIENT_DATA", 0),
        "limitations": [
            "V1 uses deterministic OHLCV proxies only; no ML and no outcome labels.",
            "No future candles are used; all candles are close_ts_utc <= asof_ts_utc.",
            "Scores are research measurements, not trading advice or runtime signals.",
            "Thresholds require outcome validation before any feature-candidate promotion.",
        ],
        "runtime_promotion_allowed": False,
        "feature_candidate_promotion_allowed": False,
        "output_paths": output_paths,
        "wrote_files": wrote_files,
        "safety_markers": {
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "db_writes": 0,
            "selection_engine_changes": 0,
            "advice_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def render_table(summary: dict[str, Any]) -> str:
    lines = [
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only market-only account-agnostic",
        "input=obs_market_candle asset no_aplus no_external_labels",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none",
        f"venue={summary['venue']} interval={summary['interval_code']} asof_ts_utc={summary['asof_ts_utc']}",
        f"assets_processed={summary['assets_processed']} observations_written={summary['observations_written']}",
        "",
        "--- phase counts ---",
    ]
    for phase, count in summary["phase_counts"].items():
        lines.append(f"  {phase}={count}")
    lines += ["", "--- top inhale accumulation ---"]
    lines.extend(render_top(summary["top_inhale_accumulation"]))
    lines += ["", "--- top hold compression ---"]
    lines.extend(render_top(summary["top_hold_compression"]))
    lines += ["", "--- top exhale expansion ---"]
    lines.extend(render_top(summary["top_exhale_expansion"]))
    lines += ["", "--- top overbreath extension ---"]
    lines.extend(render_top(summary["top_overbreath_extension"]))
    lines += ["", "--- top collapse reset ---"]
    lines.extend(render_top(summary["top_collapse_reset"]))
    lines.append("")
    lines.append(f"wrote_files={summary['wrote_files']}")
    if summary["wrote_files"]:
        for key, value in summary["output_paths"].items():
            lines.append(f"  {key}={value}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def render_top(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["  (none)"]
    return [
        (
            f"  {r['symbol']} score={r['market_breath_score']} state={r['market_breath_state']} "
            f"r6={r['return_6']} r12={r['return_12']} rs={r['relative_strength_score']}"
        )
        for r in rows
    ]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.interval not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval for V1: {args.interval}")
    if args.lookback_candles < 24:
        raise ValueError("--lookback-candles must be >= 24 for V1")

    out_dir = Path(args.output_dir)
    output_paths = {
        "observations_jsonl": str(out_dir / OUTPUT_ROWS),
        "summary_json": str(out_dir / OUTPUT_SUMMARY),
    }

    conn = get_connection()
    try:
        asof_ts = parse_ts(args.asof_ts) if args.asof_ts else latest_asof_ts(conn, args.venue, args.interval)
        assets = fetch_assets(conn)
        candles_by_asset = fetch_candles(
            conn,
            assets=assets,
            venue=args.venue,
            interval_code=args.interval,
            asof_ts=asof_ts,
            lookback_candles=args.lookback_candles,
        )
        conn.rollback()
    finally:
        conn.close()

    btc_asset = next((a for a in assets if a.symbol == "BTC"), None)
    btc_candles = candles_by_asset.get(btc_asset.asset_id, []) if btc_asset else []
    btc_r6 = safe_return(btc_candles, 6) if btc_candles else None
    btc_r12 = safe_return(btc_candles, 12) if btc_candles else None

    base_rows = [
        build_base_observation(
            asset=asset,
            candles=candles_by_asset.get(asset.asset_id, []),
            venue=args.venue,
            interval_code=args.interval,
            lookback_candles=args.lookback_candles,
            asof_ts=asof_ts,
            btc_r6=btc_r6,
            btc_r12=btc_r12,
        )
        for asset in assets
    ]
    rows = add_breadth_and_scores(base_rows, args.lookback_candles)
    summary = build_summary(
        rows,
        venue=args.venue,
        interval_code=args.interval,
        asof_ts=asof_ts,
        output_paths=output_paths,
        wrote_files=bool(args.write_files),
    )

    if args.write_files:
        write_jsonl(Path(output_paths["observations_jsonl"]), rows)
        write_json(Path(output_paths["summary_json"]), summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
