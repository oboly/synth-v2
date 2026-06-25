from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence

from src.market_context.breath_curve_core_v1 import (
    CORE_VERSION,
    Candle,
    PartialResult,
    nearest_band,
    partial_match,
)
from src.market_context.breath_curve_epoch_v1 import (
    VALIDATION_HOLDOUT,
    resolve_global_epoch_anchor,
    validation_state_for_anchor,
)


STATUS_AVAILABLE = "AVAILABLE"
STATUS_STALE = "STALE"
STATUS_UNAVAILABLE = "UNAVAILABLE"

FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE = "STALE"
FRESHNESS_UNAVAILABLE = "UNAVAILABLE"

BTC_SYMBOL = "BTC"
DEFAULT_CYCLE_DAYS = 21.0
DEFAULT_TOLERANCE_HOURS = 36.0
DEFAULT_MIN_DUE_MARKERS = 3
DEFAULT_MIN_PARTIAL_SCORE = 0.70
DEFAULT_LOOKBACK_CANDLES = 120
DEFAULT_MIN_REQUIRED_CANDLES = 35
DEFAULT_STALE_AFTER = timedelta(hours=48)
BACKTEST_OFFSET_DAYS = (-10.5, -7.0, -5.0, -3.0, 0.0, 3.0, 5.0, 7.0, 10.5)
BACKTEST_PHASE_BAND_WIDTH_DAYS = 1.0
FUTURE_TARGET_RATIO = 1.0
ANCHOR_SOURCE = "fixed_global_epoch_v1"
RESOLVER_NAME = "fixed_global_epoch_v1"
RESOLVER_VERSION = CORE_VERSION


@dataclass(frozen=True)
class BreathCurveLiveCandle:
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal



def fmt_ts(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _sorted_closed_candles(
    candles: Sequence[BreathCurveLiveCandle],
    *,
    as_of_ts_utc: datetime,
) -> list[BreathCurveLiveCandle]:
    as_of = _as_utc(as_of_ts_utc)
    return sorted(
        [c for c in candles if _as_utc(c.close_ts_utc) <= as_of],
        key=lambda c: _as_utc(c.close_ts_utc),
    )


def _to_market_candles(candles: Sequence[BreathCurveLiveCandle]) -> list[Candle]:
    out: list[Candle] = []
    for candle in candles:
        out.append(
            Candle(
                ts=_as_utc(candle.close_ts_utc),
                open=float(candle.open_price),
                high=float(candle.high_price),
                low=float(candle.low_price),
                close=float(candle.close_price),
            )
        )
    return out


def _freshness_state(
    *,
    requested_as_of_ts_utc: datetime,
    source_candle_ts_utc: datetime | None,
) -> tuple[str, str]:
    if source_candle_ts_utc is None:
        return FRESHNESS_UNAVAILABLE, "source_candle_unavailable"

    lag = _as_utc(requested_as_of_ts_utc) - _as_utc(source_candle_ts_utc)
    if lag > DEFAULT_STALE_AFTER:
        return FRESHNESS_STALE, "source_candle_stale"
    return FRESHNESS_FRESH, "closed_daily_candle"


def _data_coverage(closed_candles: Sequence[BreathCurveLiveCandle]) -> dict[str, Any]:
    count = len(closed_candles)
    ratio = min(float(count) / float(DEFAULT_LOOKBACK_CANDLES), 1.0)
    return {
        "closed_candle_count": count,
        "lookback_candles": DEFAULT_LOOKBACK_CANDLES,
        "required_min_candles": DEFAULT_MIN_REQUIRED_CANDLES,
        "coverage_ratio": round(ratio, 4),
    }



def _progression_markers(partial: PartialResult) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    due_markers = [marker for marker in partial.markers if marker.get("status") != "FUTURE"]
    matched_due = [marker for marker in due_markers if marker.get("matched")]
    current_marker = matched_due[-1] if matched_due else None
    next_marker = next((marker for marker in partial.markers if marker.get("status") == "FUTURE"), None)
    return current_marker, next_marker


def _select_offset(
    candles: list[Candle],
    symbol: str,
    anchor: datetime,
    as_of: datetime,
) -> PartialResult | None:
    """
    Backtest offset rule (backtest_breath_curve_partial_to_full_v1 lines 287-320):
    rank = (score if MAIN_PULSE_TP_HIGH still future else 0.0, score) descending.
    Always returns the top-ranked PartialResult; no score threshold applied here.
    """
    ranked: list[tuple[float, float, PartialResult]] = []
    for offset_days in BACKTEST_OFFSET_DAYS:
        pr = partial_match(
            candles=candles,
            symbol=symbol,
            venue="live",
            interval_code="1d",
            anchor=anchor,
            as_of=as_of,
            cycle_days=DEFAULT_CYCLE_DAYS,
            offset_days=offset_days,
            tolerance_hours=DEFAULT_TOLERANCE_HOURS,
            min_due_markers=DEFAULT_MIN_DUE_MARKERS,
            required_ratio=None,
        )
        target_ts = anchor + timedelta(days=DEFAULT_CYCLE_DAYS * FUTURE_TARGET_RATIO + offset_days)
        ranking_score = pr.partial_match_score if target_ts > as_of else 0.0
        ranked.append((ranking_score, pr.partial_match_score, pr))

    ranked.sort(reverse=True, key=lambda x: (x[0], x[1]))
    _, _, best_pr = ranked[0]
    return best_pr


def _lead_lag_vs_btc(
    *,
    symbol_pr: PartialResult | None,
    btc_pr: PartialResult | None,
) -> dict[str, Any] | None:
    if symbol_pr is None or btc_pr is None:
        return None

    delta_days = round(
        float(symbol_pr.phase_offset_days) - float(btc_pr.phase_offset_days),
        4,
    )
    if abs(delta_days) <= BACKTEST_PHASE_BAND_WIDTH_DAYS:
        relation = "IN_SYNC"
    elif delta_days > 0:
        relation = "AHEAD_OF_BTC"
    else:
        relation = "BEHIND_BTC"

    return {
        "relation": relation,
        "delta_days": delta_days,
        "btc_phase_offset_days": round(float(btc_pr.phase_offset_days), 4),
        "btc_phase_offset_band": nearest_band(
            btc_pr.phase_offset_days, list(BACKTEST_OFFSET_DAYS), BACKTEST_PHASE_BAND_WIDTH_DAYS
        ),
    }


def _build_unavailable_payload(
    *,
    requested_as_of_ts_utc: datetime,
    source_candle_ts_utc: datetime | None,
    epoch_anchor_ts: datetime,
    epoch_index: int,
    data_coverage: dict[str, Any],
    warnings: list[str],
    freshness_label: str,
    availability_state: str = STATUS_UNAVAILABLE,
) -> dict[str, Any]:
    return {
        "availability_state": availability_state,
        "as_of_ts_utc": fmt_ts(requested_as_of_ts_utc),
        "source_candle_ts_utc": fmt_ts(source_candle_ts_utc),
        "freshness_label": freshness_label,
        "phase_marker": None,
        "phase_offset_days": None,
        "phase_offset_band": None,
        "template_match_score": None,
        "current_checkpoint": None,
        "next_checkpoint": None,
        "next_target_expected_ts_utc": None,
        "next_target_is_future": False,
        "lead_lag_vs_btc": None,
        "anchor_ts_utc": fmt_ts(epoch_anchor_ts),
        "anchor_source": ANCHOR_SOURCE,
        "epoch_index": epoch_index,
        "validation_state": validation_state_for_anchor(epoch_anchor_ts),
        "resolver_name": RESOLVER_NAME,
        "resolver_version": RESOLVER_VERSION,
        "data_coverage": data_coverage,
        "warnings": warnings,
    }


def _build_available_payload(
    *,
    requested_as_of_ts_utc: datetime,
    source_candle_ts_utc: datetime,
    epoch_anchor_ts: datetime,
    epoch_index: int,
    selected_pr: PartialResult,
    current_marker: dict[str, Any],
    next_marker: dict[str, Any],
    data_coverage: dict[str, Any],
    lead_lag_vs_btc: dict[str, Any] | None,
    warnings: list[str],
) -> dict[str, Any]:
    current_code = str(current_marker.get("code") or "").upper()
    next_code = str(next_marker.get("code") or "").upper()
    return {
        "availability_state": STATUS_AVAILABLE,
        "as_of_ts_utc": fmt_ts(requested_as_of_ts_utc),
        "source_candle_ts_utc": fmt_ts(source_candle_ts_utc),
        "freshness_label": FRESHNESS_FRESH,
        "phase_marker": current_code or None,
        "phase_offset_days": round(float(selected_pr.phase_offset_days), 4),
        "phase_offset_band": nearest_band(
            selected_pr.phase_offset_days, list(BACKTEST_OFFSET_DAYS), BACKTEST_PHASE_BAND_WIDTH_DAYS
        ),
        "template_match_score": round(float(selected_pr.partial_match_score), 4),
        "current_checkpoint": current_code or None,
        "next_checkpoint": next_code or None,
        "next_target_expected_ts_utc": next_marker.get("expected_ts_utc"),
        "next_target_is_future": True,
        "lead_lag_vs_btc": lead_lag_vs_btc,
        "anchor_ts_utc": fmt_ts(epoch_anchor_ts),
        "anchor_source": ANCHOR_SOURCE,
        "epoch_index": epoch_index,
        "validation_state": validation_state_for_anchor(epoch_anchor_ts),
        "resolver_name": RESOLVER_NAME,
        "resolver_version": RESOLVER_VERSION,
        "data_coverage": data_coverage,
        "warnings": warnings,
    }


def build_breath_curve_live_by_symbol(
    *,
    candles_by_symbol: Mapping[str, Sequence[BreathCurveLiveCandle]],
    as_of_ts_utc: datetime,
    symbols: Sequence[str] | None = None,
    btc_symbol: str = BTC_SYMBOL,
) -> dict[str, dict[str, Any]]:
    requested_symbols = [symbol.strip().upper() for symbol in (symbols or candles_by_symbol.keys()) if symbol.strip()]
    if not requested_symbols:
        return {}

    requested_as_of = _as_utc(as_of_ts_utc)
    epoch_anchor_ts, epoch_index = resolve_global_epoch_anchor(requested_as_of)

    symbols_with_btc = list(dict.fromkeys([*requested_symbols, btc_symbol]))
    closed_by_symbol = {
        symbol: _sorted_closed_candles(candles_by_symbol.get(symbol, ()), as_of_ts_utc=requested_as_of)
        for symbol in symbols_with_btc
    }
    source_ts_by_symbol = {
        symbol: (_as_utc(closed[-1].close_ts_utc) if closed else None)
        for symbol, closed in closed_by_symbol.items()
    }

    btc_pr: PartialResult | None = None
    btc_closed = closed_by_symbol.get(btc_symbol, [])
    btc_source_ts = source_ts_by_symbol.get(btc_symbol)
    if btc_source_ts is not None and len(btc_closed) >= DEFAULT_MIN_REQUIRED_CANDLES:
        btc_freshness, _ = _freshness_state(
            requested_as_of_ts_utc=requested_as_of,
            source_candle_ts_utc=btc_source_ts,
        )
        if btc_freshness == FRESHNESS_FRESH:
            btc_pr = _select_offset(
                _to_market_candles(btc_closed), btc_symbol, epoch_anchor_ts, requested_as_of
            )

    output: dict[str, dict[str, Any]] = {}
    for symbol in requested_symbols:
        closed = closed_by_symbol.get(symbol, [])
        source_ts = source_ts_by_symbol.get(symbol)
        coverage = _data_coverage(closed)
        freshness_label, _ = _freshness_state(
            requested_as_of_ts_utc=requested_as_of,
            source_candle_ts_utc=source_ts,
        )
        warnings: list[str] = []

        if source_ts is None:
            warnings.append("SOURCE_CANDLE_UNAVAILABLE")
            output[symbol] = _build_unavailable_payload(
                requested_as_of_ts_utc=requested_as_of,
                source_candle_ts_utc=None,
                epoch_anchor_ts=epoch_anchor_ts,
                epoch_index=epoch_index,
                data_coverage=coverage,
                warnings=warnings,
                freshness_label=FRESHNESS_UNAVAILABLE,
            )
            continue

        if freshness_label == FRESHNESS_STALE:
            warnings.append("SOURCE_CANDLE_STALE")
            output[symbol] = _build_unavailable_payload(
                requested_as_of_ts_utc=requested_as_of,
                source_candle_ts_utc=source_ts,
                epoch_anchor_ts=epoch_anchor_ts,
                epoch_index=epoch_index,
                data_coverage=coverage,
                warnings=warnings,
                freshness_label=FRESHNESS_STALE,
                availability_state=STATUS_STALE,
            )
            continue

        if len(closed) < DEFAULT_MIN_REQUIRED_CANDLES:
            warnings.append("INSUFFICIENT_CLOSED_DAILY_CANDLES")
            output[symbol] = _build_unavailable_payload(
                requested_as_of_ts_utc=requested_as_of,
                source_candle_ts_utc=source_ts,
                epoch_anchor_ts=epoch_anchor_ts,
                epoch_index=epoch_index,
                data_coverage=coverage,
                warnings=warnings,
                freshness_label=FRESHNESS_UNAVAILABLE,
            )
            continue

        selected_pr = _select_offset(
            _to_market_candles(closed), symbol, epoch_anchor_ts, requested_as_of
        )
        if selected_pr is None:
            warnings.append("OFFSET_SCORE_BELOW_THRESHOLD")
            output[symbol] = _build_unavailable_payload(
                requested_as_of_ts_utc=requested_as_of,
                source_candle_ts_utc=source_ts,
                epoch_anchor_ts=epoch_anchor_ts,
                epoch_index=epoch_index,
                data_coverage=coverage,
                warnings=warnings,
                freshness_label=FRESHNESS_UNAVAILABLE,
            )
            continue

        current_marker, next_marker = _progression_markers(selected_pr)
        if current_marker is None or next_marker is None:
            warnings.append("PROGRESSION_MARKERS_UNAVAILABLE")
            output[symbol] = _build_unavailable_payload(
                requested_as_of_ts_utc=requested_as_of,
                source_candle_ts_utc=source_ts,
                epoch_anchor_ts=epoch_anchor_ts,
                epoch_index=epoch_index,
                data_coverage=coverage,
                warnings=warnings,
                freshness_label=FRESHNESS_UNAVAILABLE,
            )
            continue

        if validation_state_for_anchor(epoch_anchor_ts) == VALIDATION_HOLDOUT:
            warnings.append(VALIDATION_HOLDOUT)

        this_btc_pr = btc_pr if symbol != btc_symbol else selected_pr
        lead_lag = _lead_lag_vs_btc(symbol_pr=selected_pr, btc_pr=this_btc_pr)
        if symbol != btc_symbol and lead_lag is None:
            warnings.append("BTC_RELATION_UNAVAILABLE")

        output[symbol] = _build_available_payload(
            requested_as_of_ts_utc=requested_as_of,
            source_candle_ts_utc=source_ts,
            epoch_anchor_ts=epoch_anchor_ts,
            epoch_index=epoch_index,
            selected_pr=selected_pr,
            current_marker=current_marker,
            next_marker=next_marker,
            data_coverage=coverage,
            lead_lag_vs_btc=lead_lag,
            warnings=warnings,
        )

    return output
