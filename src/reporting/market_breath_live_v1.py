from __future__ import annotations

from datetime import datetime
from typing import Any

from src.research.market_breath_classifier_v1 import (
    DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1,
    diagnose_market_breath_context_v1,
)
from src.research.run_market_breath_analysis_v1 import (
    INTERVAL_SECONDS,
    add_breadth_and_scores,
    build_base_observation,
    fetch_assets,
    fetch_candles,
    fmt_ts,
    latest_asof_ts,
    safe_return,
)


DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL_CODE = "4h"
DEFAULT_LOOKBACK_CANDLES = 120
BTC_SYMBOL = "BTC"

STATUS_AVAILABLE = "AVAILABLE"
STATUS_STALE = "STALE"
STATUS_UNAVAILABLE = "UNAVAILABLE"

FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE = "STALE"
FRESHNESS_UNAVAILABLE = "UNAVAILABLE"

TRAJECTORY_BY_PHASE = {
    "INHALE_ACCUMULATION": "BUILDING_TOWARD_EXPANSION",
    "HOLD_COMPRESSION": "COMPRESSION_WAITING_FOR_BREAK",
    "EXHALE_EXPANSION": "EXPANSION_ACTIVE",
    "OVERBREATH_EXTENSION": "EXTENSION_COOLDOWN_RISK",
    "COLLAPSE_RESET": "RESET_RECOVERY_WATCH",
    "NEUTRAL_TRANSITION": "TRANSITION_UNCLEAR",
    "INSUFFICIENT_DATA": "TRANSITION_UNCLEAR",
}


def trajectory_label_for_market_breath_phase(
    phase: str | None,
    *,
    availability_state: str | None = None,
) -> str:
    if availability_state in {STATUS_STALE, STATUS_UNAVAILABLE}:
        return "TRANSITION_UNCLEAR"
    return TRAJECTORY_BY_PHASE.get(str(phase or "").upper(), "TRANSITION_UNCLEAR")


def _source_ts(candles: list[Any]) -> datetime | None:
    if not candles:
        return None
    return candles[-1].close_ts_utc


def _raw_scores_from_row(row: dict[str, Any] | None) -> dict[str, float | None]:
    row = row or {}
    return {
        "compression": row.get("compression_score"),
        "expansion": row.get("expansion_score"),
        "momentum": row.get("momentum_score"),
        "reversal_pressure": row.get("reversal_pressure_score"),
        "relative_strength": row.get("relative_strength_score"),
    }


def _build_unavailable_payload(
    *,
    asof_ts: datetime,
    source_candle_ts: datetime | None,
    reason: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "availability_state": STATUS_UNAVAILABLE,
        "market_breath_phase": None,
        "market_breath_state": None,
        "market_breath_confidence": None,
        "raw_scores": _raw_scores_from_row(None),
        "closest_regime_context": None,
        "closest_regime_failed_conditions": [],
        "neutral_reason": None,
        "trajectory_label": "TRANSITION_UNCLEAR",
        "source_candle_ts_utc": fmt_ts(source_candle_ts) if source_candle_ts else None,
        "resolved_asof_ts_utc": fmt_ts(asof_ts),
        "freshness_label": FRESHNESS_UNAVAILABLE,
        "freshness_reason": reason,
        "warnings": warnings,
    }


def _build_stale_payload(
    *,
    asof_ts: datetime,
    source_candle_ts: datetime | None,
    reason: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "availability_state": STATUS_STALE,
        "market_breath_phase": None,
        "market_breath_state": None,
        "market_breath_confidence": None,
        "raw_scores": _raw_scores_from_row(None),
        "closest_regime_context": None,
        "closest_regime_failed_conditions": [],
        "neutral_reason": None,
        "trajectory_label": "TRANSITION_UNCLEAR",
        "source_candle_ts_utc": fmt_ts(source_candle_ts) if source_candle_ts else None,
        "resolved_asof_ts_utc": fmt_ts(asof_ts),
        "freshness_label": FRESHNESS_STALE,
        "freshness_reason": reason,
        "warnings": warnings,
    }


def build_market_breath_live_by_symbol(
    conn: Any,
    *,
    venue: str = DEFAULT_VENUE,
    interval_code: str = DEFAULT_INTERVAL_CODE,
    lookback_candles: int = DEFAULT_LOOKBACK_CANDLES,
    symbols: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    symbol_filter = {symbol.strip().upper() for symbol in (symbols or []) if symbol.strip()}
    resolved_asof = latest_asof_ts(conn, venue, interval_code)
    allowed_symbols = set(symbol_filter)
    if allowed_symbols:
        allowed_symbols.add(BTC_SYMBOL)
    assets = [asset for asset in fetch_assets(conn) if not allowed_symbols or asset.symbol in allowed_symbols]
    candles_by_asset = fetch_candles(
        conn,
        assets=assets,
        venue=venue,
        interval_code=interval_code,
        asof_ts=resolved_asof,
        lookback_candles=lookback_candles,
    )
    asset_by_symbol = {asset.symbol: asset for asset in assets}
    btc_asset = asset_by_symbol.get(BTC_SYMBOL)
    btc_candles = candles_by_asset.get(btc_asset.asset_id, []) if btc_asset is not None else []
    btc_source_ts = _source_ts(btc_candles)
    btc_r6 = safe_return(btc_candles, 6) if btc_candles else None
    btc_r12 = safe_return(btc_candles, 12) if btc_candles else None
    interval_seconds = INTERVAL_SECONDS.get(interval_code, 4 * 60 * 60)

    rows: list[dict[str, Any]] = []
    source_ts_by_symbol: dict[str, datetime | None] = {}
    for asset in assets:
        candles = candles_by_asset.get(asset.asset_id, [])
        source_ts_by_symbol[asset.symbol] = _source_ts(candles)
        rows.append(
            build_base_observation(
                asset=asset,
                candles=candles,
                venue=venue,
                interval_code=interval_code,
                lookback_candles=lookback_candles,
                asof_ts=resolved_asof,
                btc_r6=btc_r6,
                btc_r12=btc_r12,
            )
        )

    scored_rows = add_breadth_and_scores(rows, lookback_candles)
    output: dict[str, dict[str, Any]] = {}
    btc_missing = btc_asset is None or not btc_candles
    btc_stale = btc_source_ts is not None and btc_source_ts < resolved_asof

    for row in scored_rows:
        symbol = str(row.get("symbol") or "").upper()
        source_ts = source_ts_by_symbol.get(symbol)
        warnings: list[str] = []

        if btc_missing:
            warnings.append("BTC_REFERENCE_UNAVAILABLE")
            output[symbol] = _build_unavailable_payload(
                asof_ts=resolved_asof,
                source_candle_ts=source_ts,
                reason="btc_reference_unavailable",
                warnings=warnings,
            )
            continue
        if btc_stale:
            warnings.append("BTC_REFERENCE_STALE")
            output[symbol] = _build_stale_payload(
                asof_ts=resolved_asof,
                source_candle_ts=source_ts,
                reason="btc_reference_stale",
                warnings=warnings,
            )
            continue
        invalid_reason = row.get("invalid_reason")
        if invalid_reason:
            warnings.append(str(invalid_reason))
            output[symbol] = _build_unavailable_payload(
                asof_ts=resolved_asof,
                source_candle_ts=source_ts,
                reason=str(invalid_reason),
                warnings=warnings,
            )
            continue
        if source_ts is None:
            warnings.append("SOURCE_CANDLE_UNAVAILABLE")
            output[symbol] = _build_unavailable_payload(
                asof_ts=resolved_asof,
                source_candle_ts=None,
                reason="source_candle_unavailable",
                warnings=warnings,
            )
            continue
        lag_seconds = (resolved_asof - source_ts).total_seconds()
        if lag_seconds >= interval_seconds:
            warnings.append("SOURCE_CANDLE_STALE")
            output[symbol] = _build_stale_payload(
                asof_ts=resolved_asof,
                source_candle_ts=source_ts,
                reason="source_candle_stale",
                warnings=warnings,
            )
            continue

        phase = row.get("market_breath_phase")
        state = row.get("market_breath_state")
        confidence = row.get("market_breath_confidence")
        diagnostics = diagnose_market_breath_context_v1(
            compression=float(row.get("compression_score") or 0.0),
            expansion=float(row.get("expansion_score") or 0.0),
            momentum=float(row.get("momentum_score") or 0.0),
            reversal_pressure=float(row.get("reversal_pressure_score") or 0.0),
            relative_strength=float(row.get("relative_strength_score") or 0.0),
            profile=DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1,
        )
        output[symbol] = {
            "availability_state": STATUS_AVAILABLE,
            "market_breath_phase": phase,
            "market_breath_state": state,
            "market_breath_confidence": confidence,
            "raw_scores": _raw_scores_from_row(row),
            "closest_regime_context": diagnostics["closest_regime_context"],
            "closest_regime_failed_conditions": diagnostics["closest_regime_failed_conditions"],
            "neutral_reason": diagnostics["neutral_reason"],
            "trajectory_label": trajectory_label_for_market_breath_phase(
                str(phase or ""),
                availability_state=STATUS_AVAILABLE,
            ),
            "source_candle_ts_utc": fmt_ts(source_ts),
            "resolved_asof_ts_utc": fmt_ts(resolved_asof),
            "freshness_label": FRESHNESS_FRESH,
            "freshness_reason": "current_interval_candle",
            "warnings": warnings,
        }

    if symbol_filter:
        for symbol in symbol_filter:
            output.setdefault(
                symbol,
                _build_unavailable_payload(
                    asof_ts=resolved_asof,
                    source_candle_ts=None,
                    reason="symbol_not_tradeable_or_missing",
                    warnings=["SYMBOL_NOT_TRADEABLE_OR_MISSING"],
                ),
            )
        return {symbol: output[symbol] for symbol in symbol_filter}
    return output
