from __future__ import annotations

import csv
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from src.research.htf_fib_extension_confluence_v1 import HtfSwingInput, build_htf_extension_map
from src.research.htf_fib_reentry_ladder_v1 import HtfReentryInput, build_fib_retrace_ladder
from src.research.multi_horizon_fib_contract_v1 import (
    ALGORITHM_VERSION,
    ANALYSIS_VERSION,
    DEFAULT_FEE_BPS_PER_SIDE,
    DEFAULT_OVERLAP_CANDLES,
    DEFAULT_PIVOT_SPAN,
    DEFAULT_SUPPORT_LOOKAHEAD,
    EXTENSION_LEVELS,
    INTERVAL_ROLE_PRIMARY,
    INTERVAL_ROLE_SUPPORT,
    INTERVAL_TO_DELTA,
    PARAMETER_PROFILE_ID,
    Candle,
    ContextRow,
    FibCheckpoint,
    HorizonDefinition,
    SAFETY_MARKERS,
    STATUS_FAILED,
    STATUS_READY,
    STATUS_SKIPPED,
    UNKNOWN_CONTEXT,
    decimal_text,
    get_horizon_definition,
    iso_z,
    parse_iso_z,
    utc_now,
)


PROFILE_STATS_FIELDS = [
    "symbol",
    "venue",
    "quote",
    "fib_trading_horizon",
    "interval_code",
    "interval_role",
    "parent_horizon",
    "child_horizon",
    "fib_level",
    "sample_count",
    "touch_count",
    "touch_rate",
    "reaction_success_count",
    "reaction_success_rate",
    "fakeout_count",
    "fakeout_rate",
    "invalidation_count",
    "invalidation_rate",
    "next_extension_hit_count",
    "hit_rate",
    "avg_time_to_touch_candles",
    "median_time_to_touch_candles",
    "avg_time_to_next_extension_candles",
    "median_time_to_next_extension_candles",
    "avg_mfe_pct",
    "median_mfe_pct",
    "avg_mae_pct",
    "median_mae_pct",
    "gross_return_pct",
    "net_return_pct",
    "hold_return_pct",
    "excess_return_pct",
    "drawdown_pct",
    "drawdown_improvement_pct",
]

CONTEXT_PROFILE_STATS_FIELDS = [
    "symbol",
    "venue",
    "quote",
    "fib_trading_horizon",
    "market_regime",
    "symbol_regime",
    "breath_phase",
    "breath_alignment",
    "sample_count",
]


def _find_pivot_lows(candles: list[Candle], span: int) -> list[int]:
    result: list[int] = []
    for index in range(span, len(candles) - span):
        low = candles[index].low_price
        window = candles[index - span : index + span + 1]
        if all(low <= candle.low_price for candle in window):
            result.append(index)
    return result


def _find_pivot_highs(candles: list[Candle], span: int) -> list[int]:
    result: list[int] = []
    for index in range(span, len(candles) - span):
        high = candles[index].high_price
        window = candles[index - span : index + span + 1]
        if all(high >= candle.high_price for candle in window):
            result.append(index)
    return result


def _quant_pct(value: Decimal | None) -> str | None:
    return decimal_text(value, "0.00000001") if value is not None else None


def _safe_pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return (numerator / denominator) * Decimal("100")


def _extension_price(swing_low: Decimal, swing_high: Decimal, fib_level: Decimal) -> Decimal:
    return swing_low + (swing_high - swing_low) * fib_level


def build_active_fib_levels(
    *,
    symbol: str,
    interval_code: str,
    swing_low: Decimal,
    swing_high: Decimal,
    current_price: Decimal,
    recent_low: Decimal | None,
) -> dict[str, str]:
    extension_map = build_htf_extension_map(
        HtfSwingInput(
            symbol=symbol,
            interval_code=interval_code,
            swing_low=swing_low,
            swing_high=swing_high,
            current_price=current_price,
            prior_high_price=swing_high,
        )
    )
    reentry_ladder = build_fib_retrace_ladder(
        HtfReentryInput(
            symbol=symbol,
            interval_code=interval_code,
            swing_low=swing_low,
            swing_high=swing_high,
            current_price=current_price,
            recent_low_price=recent_low,
        )
    )
    levels: dict[str, str] = {}
    for target in extension_map.targets:
        levels[target.label] = decimal_text(target.price) or ""
    for fib_level in EXTENSION_LEVELS:
        label = f"ext_{str(fib_level).replace('.', '_')}"
        levels.setdefault(label, decimal_text(_extension_price(swing_low, swing_high, fib_level)) or "")
    for row in reentry_ladder.levels:
        levels[row.label] = decimal_text(row.price) or ""
    return levels


def _detect_swings(candles: list[Candle], pivot_span: int) -> list[dict[str, Any]]:
    lows = _find_pivot_lows(candles, pivot_span)
    highs = _find_pivot_highs(candles, pivot_span)
    swings: list[dict[str, Any]] = []
    for high_idx in highs:
        prior_lows = [low_idx for low_idx in lows if low_idx < high_idx]
        if not prior_lows:
            continue
        low_idx = prior_lows[-1]
        swing_low = candles[low_idx].low_price
        swing_high = candles[high_idx].high_price
        if swing_high <= swing_low or swing_low <= 0:
            continue
        swings.append(
            {
                "low_idx": low_idx,
                "high_idx": high_idx,
                "low_ts": candles[low_idx].close_ts_utc,
                "high_ts": candles[high_idx].close_ts_utc,
                "swing_low": swing_low,
                "swing_high": swing_high,
                "leg_size": swing_high - swing_low,
            }
        )
    deduped: dict[str, dict[str, Any]] = {}
    for swing in swings:
        deduped[iso_z(swing["high_ts"]) or ""] = swing
    return [deduped[key] for key in sorted(deduped)]


def _nearest_context(
    symbol: str,
    sample_ts: datetime,
    context_rows_by_symbol: dict[str, list[ContextRow]],
) -> ContextRow:
    rows = context_rows_by_symbol.get(symbol.upper(), [])
    if not rows:
        return ContextRow(symbol=symbol.upper(), sample_ts_utc=sample_ts)
    exact = [row for row in rows if row.sample_ts_utc <= sample_ts]
    if exact:
        return exact[-1]
    return rows[0]


def _scan_level_outcome(
    candles: list[Candle],
    start_idx: int,
    level_price: Decimal,
    invalidation_price: Decimal,
    next_extension_price: Decimal | None,
    direction: str,
) -> dict[str, Any]:
    window = candles[start_idx + 1 :]
    touch_offset: int | None = None
    next_ext_offset: int | None = None
    touched = False
    invalidated = False
    fakeout = False
    reaction_success = False
    mfe = Decimal("0")
    mae = Decimal("0")
    gross_return = Decimal("0")
    hold_return = Decimal("0")
    start_price = candles[start_idx].close_price
    for offset, candle in enumerate(window, start=1):
        touched_now = candle.low_price <= level_price <= candle.high_price
        if touched_now and touch_offset is None:
            touch_offset = offset
            touched = True
        if touched:
            favorable = _safe_pct(candle.high_price - level_price, level_price)
            adverse = _safe_pct(level_price - candle.low_price, level_price)
            mfe = max(mfe, favorable)
            mae = max(mae, adverse)
            if candle.low_price <= invalidation_price:
                invalidated = True
            if candle.close_price > start_price:
                reaction_success = True
                gross_return = max(gross_return, _safe_pct(candle.close_price - level_price, level_price))
            if next_extension_price is not None and candle.high_price >= next_extension_price and next_ext_offset is None:
                next_ext_offset = offset
        hold_return = _safe_pct(candle.close_price - start_price, start_price)
    if touched and not reaction_success and invalidated:
        fakeout = True
    return {
        "direction": direction,
        "touched": touched,
        "touch_count": int(touched),
        "reaction_success_count": int(reaction_success),
        "fakeout_count": int(fakeout),
        "invalidation_count": int(invalidated),
        "next_extension_hit_count": int(next_ext_offset is not None),
        "time_to_touch_candles": touch_offset,
        "time_to_next_extension_candles": next_ext_offset,
        "mfe_pct": _quant_pct(mfe),
        "mae_pct": _quant_pct(mae),
        "gross_return_pct": _quant_pct(gross_return),
        "hold_return_pct": _quant_pct(hold_return),
    }


def _build_series_rows(
    *,
    symbol: str,
    venue: str,
    quote: str,
    horizon: HorizonDefinition,
    interval_code: str,
    interval_role: str,
    candles: list[Candle],
    context_rows_by_symbol: dict[str, list[ContextRow]],
    pivot_span: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    if len(candles) < pivot_span * 2 + 1:
        return [], [], [], None
    swings = _detect_swings(candles, pivot_span)
    if not swings:
        return [], [], [], None
    swing_events: list[dict[str, Any]] = []
    fib_outcomes: list[dict[str, Any]] = []
    active_swing_rows: list[dict[str, Any]] = []
    for swing_index, swing in enumerate(swings, start=1):
        current_price = candles[swing["high_idx"]].close_price
        next_extension_price = _extension_price(swing["swing_low"], swing["swing_high"], Decimal("1.618"))
        active_levels = build_active_fib_levels(
            symbol=symbol,
            interval_code=interval_code,
            swing_low=swing["swing_low"],
            swing_high=swing["swing_high"],
            current_price=current_price,
            recent_low=candles[swing["high_idx"]].low_price,
        )
        event_id = f"{symbol}|{horizon.fib_trading_horizon}|{interval_role}|{interval_code}|{iso_z(swing['high_ts'])}"
        context = _nearest_context(symbol, swing["high_ts"], context_rows_by_symbol)
        swing_events.append(
            {
                "event_id": event_id,
                "symbol": symbol,
                "venue": venue,
                "quote": quote,
                "fib_trading_horizon": horizon.fib_trading_horizon,
                "interval_code": interval_code,
                "interval_role": interval_role,
                "parent_horizon": horizon.parent_horizon or "",
                "child_horizon": horizon.child_horizon or "",
                "swing_id": f"{symbol}-{horizon.fib_trading_horizon}-{swing_index}",
                "swing_low_ts": iso_z(swing["low_ts"]),
                "swing_high_ts": iso_z(swing["high_ts"]),
                "swing_low": decimal_text(swing["swing_low"]),
                "swing_high": decimal_text(swing["swing_high"]),
                "market_regime": context.market_regime or UNKNOWN_CONTEXT,
                "symbol_regime": context.symbol_regime or UNKNOWN_CONTEXT,
                "breath_phase": context.breath_phase or UNKNOWN_CONTEXT,
                "breath_alignment": context.breath_alignment or UNKNOWN_CONTEXT,
            }
        )
        for fib_level in EXTENSION_LEVELS:
            level_price = _extension_price(swing["swing_low"], swing["swing_high"], fib_level)
            outcome = _scan_level_outcome(
                candles=candles,
                start_idx=swing["high_idx"],
                level_price=level_price,
                invalidation_price=swing["swing_low"],
                next_extension_price=None,
                direction="EXTENSION",
            )
            fib_outcomes.append(
                {
                    "event_id": event_id,
                    "symbol": symbol,
                    "venue": venue,
                    "quote": quote,
                    "fib_trading_horizon": horizon.fib_trading_horizon,
                    "interval_code": interval_code,
                    "interval_role": interval_role,
                    "parent_horizon": horizon.parent_horizon or "",
                    "child_horizon": horizon.child_horizon or "",
                    "fib_family": "EXTENSION",
                    "fib_level": str(fib_level),
                    "fib_price": decimal_text(level_price),
                    "market_regime": context.market_regime or UNKNOWN_CONTEXT,
                    "symbol_regime": context.symbol_regime or UNKNOWN_CONTEXT,
                    "breath_phase": context.breath_phase or UNKNOWN_CONTEXT,
                    "breath_alignment": context.breath_alignment or UNKNOWN_CONTEXT,
                    **outcome,
                }
            )
        for fib_level in (Decimal("0.382"), Decimal("0.500"), Decimal("0.618"), Decimal("0.786")):
            level_price = swing["swing_high"] - swing["leg_size"] * fib_level
            outcome = _scan_level_outcome(
                candles=candles,
                start_idx=swing["high_idx"],
                level_price=level_price,
                invalidation_price=swing["swing_low"],
                next_extension_price=next_extension_price,
                direction="RETRACE",
            )
            fib_outcomes.append(
                {
                    "event_id": event_id,
                    "symbol": symbol,
                    "venue": venue,
                    "quote": quote,
                    "fib_trading_horizon": horizon.fib_trading_horizon,
                    "interval_code": interval_code,
                    "interval_role": interval_role,
                    "parent_horizon": horizon.parent_horizon or "",
                    "child_horizon": horizon.child_horizon or "",
                    "fib_family": "RETRACE",
                    "fib_level": str(fib_level),
                    "fib_price": decimal_text(level_price),
                    "market_regime": context.market_regime or UNKNOWN_CONTEXT,
                    "symbol_regime": context.symbol_regime or UNKNOWN_CONTEXT,
                    "breath_phase": context.breath_phase or UNKNOWN_CONTEXT,
                    "breath_alignment": context.breath_alignment or UNKNOWN_CONTEXT,
                    **outcome,
                }
            )
        active_swing_rows.append(
            {
                "symbol": symbol,
                "venue": venue,
                "quote": quote,
                "fib_trading_horizon": horizon.fib_trading_horizon,
                "interval_code": interval_code,
                "interval_role": interval_role,
                "parent_horizon": horizon.parent_horizon or "",
                "child_horizon": horizon.child_horizon or "",
                "active_swing_id": f"{symbol}-{horizon.fib_trading_horizon}-{swing_index}",
                "active_swing_low": decimal_text(swing["swing_low"]),
                "active_swing_high": decimal_text(swing["swing_high"]),
                "active_swing_low_ts": iso_z(swing["low_ts"]),
                "active_swing_high_ts": iso_z(swing["high_ts"]),
                "active_swing_state": "COMPLETED",
                "active_fib_levels": json.dumps(active_levels, sort_keys=True),
            }
        )
    return swing_events, fib_outcomes, active_swing_rows[-1:], swings[-1]


def _merge_rows(existing: list[dict[str, Any]], new_rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in existing:
        key = tuple(str(row.get(field) or "") for field in key_fields)
        merged[key] = row
    for row in new_rows:
        key = tuple(str(row.get(field) or "") for field in key_fields)
        merged[key] = row
    return [merged[key] for key in sorted(merged)]


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def _profile_stats_rows(rows: list[dict[str, Any]], fee_bps_per_side: Decimal) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row["symbol"]),
            str(row["venue"]),
            str(row["quote"]),
            str(row["fib_trading_horizon"]),
            str(row["interval_code"]),
            str(row["interval_role"]),
            str(row.get("parent_horizon") or ""),
            str(row.get("child_horizon") or ""),
            str(row["fib_level"]),
        )
        grouped[key].append(row)
    result: list[dict[str, Any]] = []
    roundtrip_fee_pct = fee_bps_per_side * Decimal("2") / Decimal("100")
    for key in sorted(grouped):
        items = grouped[key]
        count = len(items)
        touch_count = sum(int(row["touch_count"]) for row in items)
        reaction_success_count = sum(int(row["reaction_success_count"]) for row in items)
        fakeout_count = sum(int(row["fakeout_count"]) for row in items)
        invalidation_count = sum(int(row["invalidation_count"]) for row in items)
        next_extension_hit_count = sum(int(row["next_extension_hit_count"]) for row in items)
        touch_times = [int(row["time_to_touch_candles"]) for row in items if row.get("time_to_touch_candles") not in (None, "", "None")]
        next_times = [int(row["time_to_next_extension_candles"]) for row in items if row.get("time_to_next_extension_candles") not in (None, "", "None")]
        mfes = [Decimal(str(row["mfe_pct"])) for row in items if row.get("mfe_pct")]
        maes = [Decimal(str(row["mae_pct"])) for row in items if row.get("mae_pct")]
        gross_returns = [Decimal(str(row["gross_return_pct"])) for row in items if row.get("gross_return_pct")]
        hold_returns = [Decimal(str(row["hold_return_pct"])) for row in items if row.get("hold_return_pct")]
        avg_gross = sum(gross_returns, Decimal("0")) / Decimal(len(gross_returns)) if gross_returns else Decimal("0")
        avg_hold = sum(hold_returns, Decimal("0")) / Decimal(len(hold_returns)) if hold_returns else Decimal("0")
        net_return = avg_gross - roundtrip_fee_pct
        result.append(
            {
                "symbol": key[0],
                "venue": key[1],
                "quote": key[2],
                "fib_trading_horizon": key[3],
                "interval_code": key[4],
                "interval_role": key[5],
                "parent_horizon": key[6],
                "child_horizon": key[7],
                "fib_level": key[8],
                "sample_count": count,
                "touch_count": touch_count,
                "touch_rate": _quant_pct(Decimal(touch_count) / Decimal(count) if count else Decimal("0")),
                "reaction_success_count": reaction_success_count,
                "reaction_success_rate": _quant_pct(Decimal(reaction_success_count) / Decimal(count) if count else Decimal("0")),
                "fakeout_count": fakeout_count,
                "fakeout_rate": _quant_pct(Decimal(fakeout_count) / Decimal(count) if count else Decimal("0")),
                "invalidation_count": invalidation_count,
                "invalidation_rate": _quant_pct(Decimal(invalidation_count) / Decimal(count) if count else Decimal("0")),
                "next_extension_hit_count": next_extension_hit_count,
                "hit_rate": _quant_pct(Decimal(next_extension_hit_count) / Decimal(count) if count else Decimal("0")),
                "avg_time_to_touch_candles": round(sum(touch_times) / len(touch_times), 4) if touch_times else "",
                "median_time_to_touch_candles": median(touch_times) if touch_times else "",
                "avg_time_to_next_extension_candles": round(sum(next_times) / len(next_times), 4) if next_times else "",
                "median_time_to_next_extension_candles": median(next_times) if next_times else "",
                "avg_mfe_pct": _quant_pct(sum(mfes, Decimal("0")) / Decimal(len(mfes)) if mfes else Decimal("0")),
                "median_mfe_pct": _quant_pct(Decimal(str(median(mfes))) if mfes else Decimal("0")),
                "avg_mae_pct": _quant_pct(sum(maes, Decimal("0")) / Decimal(len(maes)) if maes else Decimal("0")),
                "median_mae_pct": _quant_pct(Decimal(str(median(maes))) if maes else Decimal("0")),
                "gross_return_pct": _quant_pct(avg_gross),
                "net_return_pct": _quant_pct(net_return),
                "hold_return_pct": _quant_pct(avg_hold),
                "excess_return_pct": _quant_pct(net_return - avg_hold),
                "drawdown_pct": _quant_pct(max(maes) if maes else Decimal("0")),
                "drawdown_improvement_pct": _quant_pct(avg_hold - (max(maes) if maes else Decimal("0"))),
            }
        )
    return result


def _context_profile_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], int] = defaultdict(int)
    for row in rows:
        grouped[
            (
                str(row["symbol"]),
                str(row["venue"]),
                str(row["quote"]),
                str(row["fib_trading_horizon"]),
                str(row.get("market_regime") or UNKNOWN_CONTEXT),
                str(row.get("symbol_regime") or UNKNOWN_CONTEXT),
                str(row.get("breath_phase") or UNKNOWN_CONTEXT),
                str(row.get("breath_alignment") or UNKNOWN_CONTEXT),
            )
        ] += 1
    return [
        {
            "symbol": key[0],
            "venue": key[1],
            "quote": key[2],
            "fib_trading_horizon": key[3],
            "market_regime": key[4],
            "symbol_regime": key[5],
            "breath_phase": key[6],
            "breath_alignment": key[7],
            "sample_count": count,
        }
        for key, count in sorted(grouped.items())
    ]


def _validate_checkpoint(checkpoint: FibCheckpoint, *, mode: str) -> None:
    if mode == "rebuild":
        return
    if checkpoint.analysis_version != ANALYSIS_VERSION or checkpoint.algorithm_version != ALGORITHM_VERSION:
        raise RuntimeError("Checkpoint version mismatch requires rebuild.")


def _checkpoint_path(output_dir: Path, symbol: str, horizon: str) -> Path:
    return output_dir / "checkpoints" / f"{symbol}_{horizon}_checkpoint_v1.json"


def _load_checkpoint(output_dir: Path, symbol: str, horizon: str) -> FibCheckpoint | None:
    path = _checkpoint_path(output_dir, symbol, horizon)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return FibCheckpoint.from_dict(payload)


def _write_checkpoint(output_dir: Path, checkpoint: FibCheckpoint) -> None:
    path = _checkpoint_path(output_dir, checkpoint.symbol, checkpoint.fib_trading_horizon)
    _write_json(path, checkpoint.to_dict())


def _window_candles_for_incremental(candles: list[Candle], checkpoint: FibCheckpoint | None, overlap_candles: int) -> list[Candle]:
    if checkpoint is None or checkpoint.last_processed_primary_close_ts is None:
        return candles
    last_ts = parse_iso_z(checkpoint.last_processed_primary_close_ts)
    if last_ts is None:
        return candles
    index = next((idx for idx, candle in enumerate(candles) if candle.close_ts_utc > last_ts), len(candles))
    start = max(0, index - overlap_candles)
    return candles[start:]


def _compute_task(task: dict[str, Any]) -> dict[str, Any]:
    symbol = task["symbol"]
    venue = task["venue"]
    quote = task["quote"]
    horizon = task["horizon"]
    primary_candles = task["primary_candles"]
    support_candles = task["support_candles"]
    context_rows_by_symbol = task["context_rows_by_symbol"]
    pivot_span = task["pivot_span"]
    primary_events, primary_outcomes, primary_active, primary_last = _build_series_rows(
        symbol=symbol,
        venue=venue,
        quote=quote,
        horizon=horizon,
        interval_code=horizon.primary_interval,
        interval_role=INTERVAL_ROLE_PRIMARY,
        candles=primary_candles,
        context_rows_by_symbol=context_rows_by_symbol,
        pivot_span=pivot_span,
    )
    support_events: list[dict[str, Any]] = []
    support_outcomes: list[dict[str, Any]] = []
    support_active: list[dict[str, Any]] = []
    support_last: dict[str, Any] | None = None
    for support_interval in horizon.supporting_intervals:
        rows = support_candles.get(support_interval, [])
        if rows:
            ev, out, active, last = _build_series_rows(
                symbol=symbol,
                venue=venue,
                quote=quote,
                horizon=horizon,
                interval_code=support_interval,
                interval_role=INTERVAL_ROLE_SUPPORT,
                candles=rows,
                context_rows_by_symbol=context_rows_by_symbol,
                pivot_span=pivot_span,
            )
            support_events.extend(ev)
            support_outcomes.extend(out)
            support_active.extend(active)
            support_last = last or support_last
    return {
        "symbol": symbol,
        "horizon": horizon.fib_trading_horizon,
        "primary_events": primary_events,
        "primary_outcomes": primary_outcomes,
        "primary_active": primary_active,
        "primary_last": primary_last,
        "support_events": support_events,
        "support_outcomes": support_outcomes,
        "support_active": support_active,
        "support_last": support_last,
    }


def run_multi_horizon_backtest(
    *,
    mode: str,
    output_dir: Path,
    symbol_inputs: list[dict[str, Any]],
    horizons: list[str],
    venue: str,
    quote: str,
    workers: int,
    fee_bps_per_side: Decimal = DEFAULT_FEE_BPS_PER_SIDE,
    overlap_candles: int = DEFAULT_OVERLAP_CANDLES,
    pivot_span: int = DEFAULT_PIVOT_SPAN,
    write_files: bool = False,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    tasks: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    for symbol_payload in sorted(symbol_inputs, key=lambda item: str(item["symbol"])):
        symbol = str(symbol_payload["symbol"]).upper()
        candles_by_interval: dict[str, list[Candle]] = symbol_payload["candles_by_interval"]
        context_rows_by_symbol = {symbol: symbol_payload.get("context_rows", [])}
        for horizon_name in horizons:
            horizon = get_horizon_definition(horizon_name)
            checkpoint = None if mode == "rebuild" else _load_checkpoint(output_dir, symbol, horizon_name)
            if checkpoint is not None:
                _validate_checkpoint(checkpoint, mode=mode)
            primary_all = candles_by_interval.get(horizon.primary_interval, [])
            support_all = {interval: candles_by_interval.get(interval, []) for interval in horizon.supporting_intervals}
            if not primary_all:
                coverage_rows.append(
                    {
                        "symbol": symbol,
                        "venue": venue,
                        "quote": quote,
                        "fib_trading_horizon": horizon_name,
                        "primary_interval": horizon.primary_interval,
                        "coverage_status": STATUS_SKIPPED,
                        "skip_reason": "MISSING_PRIMARY_INTERVAL_HISTORY",
                    }
                )
                continue
            missing_support = [interval for interval, rows in support_all.items() if not rows]
            coverage_rows.append(
                {
                    "symbol": symbol,
                    "venue": venue,
                    "quote": quote,
                    "fib_trading_horizon": horizon_name,
                    "primary_interval": horizon.primary_interval,
                    "coverage_status": STATUS_READY if not missing_support else STATUS_SKIPPED,
                    "skip_reason": "" if not missing_support else f"MISSING_SUPPORT_INTERVAL_HISTORY:{','.join(missing_support)}",
                }
            )
            primary_candles = primary_all if mode in ("bootstrap", "rebuild") else _window_candles_for_incremental(primary_all, checkpoint, overlap_candles)
            support_candles = {
                interval: rows if mode in ("bootstrap", "rebuild") else _window_candles_for_incremental(rows, checkpoint, overlap_candles)
                for interval, rows in support_all.items()
                if rows
            }
            tasks.append(
                {
                    "symbol": symbol,
                    "venue": venue,
                    "quote": quote,
                    "horizon": horizon,
                    "primary_candles": primary_candles,
                    "support_candles": support_candles,
                    "context_rows_by_symbol": context_rows_by_symbol,
                    "pivot_span": pivot_span,
                }
            )
    started_at = utc_now()
    task_results: list[dict[str, Any]] = []
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(_compute_task, task): (
                    str(task["symbol"]),
                    str(task["horizon"].fib_trading_horizon),
                )
                for task in tasks
            }
            for future in as_completed(future_map):
                symbol, horizon_name = future_map[future]
                try:
                    task_results.append(future.result())
                except Exception as exc:
                    failure_rows.append(
                        {
                            "symbol": symbol,
                            "fib_trading_horizon": horizon_name,
                            "status": STATUS_FAILED,
                            "failure_reason": str(exc),
                        }
                    )
    else:
        for task in tasks:
            try:
                task_results.append(_compute_task(task))
            except Exception as exc:
                failure_rows.append(
                    {
                        "symbol": str(task["symbol"]),
                        "fib_trading_horizon": str(task["horizon"].fib_trading_horizon),
                        "status": STATUS_FAILED,
                        "failure_reason": str(exc),
                    }
                )
    task_results = sorted(task_results, key=lambda row: (row["symbol"], row["horizon"]))
    swing_events_path = output_dir / "swing_events_v1.csv"
    fib_outcomes_path = output_dir / "fib_level_outcomes_v1.csv"
    active_rows_path = output_dir / "active_swing_rows_v1.csv"
    existing_events = [] if mode == "rebuild" else _read_csv_rows(swing_events_path)
    existing_outcomes = [] if mode == "rebuild" else _read_csv_rows(fib_outcomes_path)
    existing_active = [] if mode == "rebuild" else _read_csv_rows(active_rows_path)
    new_events: list[dict[str, Any]] = []
    new_outcomes: list[dict[str, Any]] = []
    new_active: list[dict[str, Any]] = []
    checkpoint_index: list[dict[str, Any]] = []
    total = len(task_results)
    for index, result in enumerate(task_results, start=1):
        symbol = result["symbol"]
        horizon_name = result["horizon"]
        horizon = get_horizon_definition(horizon_name)
        new_events.extend(result["primary_events"])
        new_events.extend(result["support_events"])
        new_outcomes.extend(result["primary_outcomes"])
        new_outcomes.extend(result["support_outcomes"])
        new_active.extend(result["primary_active"])
        new_active.extend(result["support_active"])
        primary_last = result["primary_last"]
        support_last = result["support_last"]
        last_primary_ts = None if primary_last is None else iso_z(primary_last["high_ts"])
        last_support_ts = None if support_last is None else iso_z(support_last["high_ts"])
        levels = {} if primary_last is None else build_active_fib_levels(
            symbol=symbol,
            interval_code=horizon.primary_interval,
            swing_low=primary_last["swing_low"],
            swing_high=primary_last["swing_high"],
            current_price=primary_last["swing_high"],
            recent_low=primary_last["swing_low"],
        )
        checkpoint = FibCheckpoint(
            symbol=symbol,
            venue=venue,
            quote=quote,
            fib_trading_horizon=horizon_name,
            primary_interval=horizon.primary_interval,
            supporting_intervals=list(horizon.supporting_intervals),
            analysis_version=ANALYSIS_VERSION,
            algorithm_version=ALGORITHM_VERSION,
            parameter_profile_id=PARAMETER_PROFILE_ID,
            last_processed_primary_close_ts=last_primary_ts,
            last_processed_support_close_ts=last_support_ts,
            last_confirmed_pivot_ts=last_primary_ts,
            active_swing_id=None if primary_last is None else f"{symbol}-{horizon_name}-{len(result['primary_events'])}",
            active_swing_low=None if primary_last is None else decimal_text(primary_last["swing_low"]),
            active_swing_high=None if primary_last is None else decimal_text(primary_last["swing_high"]),
            active_swing_low_ts=None if primary_last is None else iso_z(primary_last["low_ts"]),
            active_swing_high_ts=None if primary_last is None else iso_z(primary_last["high_ts"]),
            active_swing_state="COMPLETED" if primary_last is not None else None,
            active_fib_levels=levels,
            completed_swing_count=len(result["primary_events"]),
            overlap_candles=overlap_candles,
            updated_ts=iso_z(utc_now()) or "",
            source_refs={"mode": mode, "symbol": symbol, "fib_trading_horizon": horizon_name},
        )
        _write_checkpoint(output_dir, checkpoint)
        checkpoint_index.append(
            {
                "symbol": symbol,
                "fib_trading_horizon": horizon_name,
                "checkpoint_path": str(_checkpoint_path(output_dir, symbol, horizon_name)),
            }
        )
        print(
            f"completed={index}/{total} symbol={symbol} horizon={horizon_name} "
            f"elapsed_seconds={(utc_now() - started_at).total_seconds():.2f} "
            f"skipped={sum(1 for row in coverage_rows if row['coverage_status'] != STATUS_READY)} "
            f"failed={len(failure_rows)}"
        )
    merged_events = _merge_rows(existing_events, new_events, ("event_id",))
    merged_outcomes = _merge_rows(existing_outcomes, new_outcomes, ("event_id", "fib_family", "fib_level"))
    merged_active = _merge_rows(existing_active, new_active, ("symbol", "fib_trading_horizon", "interval_code", "interval_role"))
    profile_stats = _profile_stats_rows(merged_outcomes, fee_bps_per_side)
    context_profile_stats = _context_profile_rows(merged_outcomes)
    manifest = {
        "report_name": "multi_horizon_fib_backtest_v1",
        "analysis_version": ANALYSIS_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "parameter_profile_id": PARAMETER_PROFILE_ID,
        "mode": mode,
        "workers": workers,
        "fee_bps_per_side": str(fee_bps_per_side),
        "horizons": horizons,
        "symbols": [str(item["symbol"]).upper() for item in symbol_inputs],
        "row_counts": {
            "swing_events": len(merged_events),
            "active_swing_rows": len(merged_active),
            "fib_level_outcomes": len(merged_outcomes),
            "profile_stats": len(profile_stats),
            "context_profile_stats": len(context_profile_stats),
            "coverage_summary": len(coverage_rows),
            "failure_skip_summary": len(failure_rows),
        },
        "safety_markers": SAFETY_MARKERS,
    }
    if write_files:
        _write_csv(swing_events_path, merged_events)
        _write_jsonl(output_dir / "swing_events_v1.jsonl", merged_events)
        _write_csv(active_rows_path, merged_active)
        _write_csv(fib_outcomes_path, merged_outcomes)
        _write_csv(output_dir / "profile_stats_v1.csv", profile_stats)
        _write_csv(output_dir / "context_profile_stats_v1.csv", context_profile_stats)
        _write_json(output_dir / "checkpoint_index_v1.json", {"checkpoints": checkpoint_index})
        _write_csv(output_dir / "coverage_summary_v1.csv", coverage_rows)
        _write_csv(output_dir / "failure_skip_summary_v1.csv", failure_rows)
        _write_json(output_dir / "manifest_v1.json", manifest)
    return {
        "manifest": manifest,
        "swing_events": merged_events,
        "active_swing_rows": merged_active,
        "fib_level_outcomes": merged_outcomes,
        "profile_stats": profile_stats,
        "context_profile_stats": context_profile_stats,
        "coverage_summary": coverage_rows,
        "failure_skip_summary": failure_rows,
        "checkpoints": checkpoint_index,
    }
