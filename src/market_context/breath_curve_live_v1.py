from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence

from src.research.breath_curve_template_matcher_v1 import Candle, parse_offsets
from src.research.run_breath_curve_phase_calibration_v2 import nearest_band
from src.research.run_breath_curve_template_partial_v1 import PartialResult, partial_match


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
DEFAULT_ANCHOR_SEARCH_DAYS = 56
DEFAULT_PHASE_BANDS = tuple(parse_offsets("-10.5,-9,-7,-5,-3,0,3,5,7,9,10.5"))
DEFAULT_PHASE_BAND_WIDTH_DAYS = 1.0


@dataclass(frozen=True)
class BreathCurveLiveCandle:
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class BreathCurveResolvedCandidate:
    anchor_ts_utc: datetime
    partial_result: PartialResult
    phase_offset_band: str
    current_marker: dict[str, Any]
    next_marker: dict[str, Any]


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


def _to_research_candles(candles: Sequence[BreathCurveLiveCandle]) -> list[Candle]:
    out: list[Candle] = []
    for idx, candle in enumerate(candles, start=1):
        out.append(
            Candle(
                ts=_as_utc(candle.close_ts_utc),
                open=float(candle.open_price),
                high=float(candle.high_price),
                low=float(candle.low_price),
                close=float(candle.close_price),
                volume=float(idx),
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


def _candidate_anchor_ts(
    candles: Sequence[BreathCurveLiveCandle],
    *,
    source_candle_ts_utc: datetime,
) -> list[datetime]:
    lower_bound = _as_utc(source_candle_ts_utc) - timedelta(days=DEFAULT_ANCHOR_SEARCH_DAYS)
    return [
        _as_utc(candle.close_ts_utc)
        for candle in candles
        if lower_bound <= _as_utc(candle.close_ts_utc) <= _as_utc(source_candle_ts_utc)
    ]


def _progression_markers(partial: PartialResult) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    due_markers = [marker for marker in partial.markers if marker.get("status") != "FUTURE"]
    matched_due = [marker for marker in due_markers if marker.get("matched")]
    current_marker = matched_due[-1] if matched_due else None
    next_marker = next((marker for marker in partial.markers if marker.get("status") == "FUTURE"), None)
    return current_marker, next_marker


def _resolve_candidate(
    *,
    symbol: str,
    candles: Sequence[BreathCurveLiveCandle],
    source_candle_ts_utc: datetime,
) -> BreathCurveResolvedCandidate | None:
    research_candles = _to_research_candles(candles)
    best_candidate: BreathCurveResolvedCandidate | None = None
    best_rank: tuple[float, int, float, float] | None = None

    for anchor_ts in _candidate_anchor_ts(candles, source_candle_ts_utc=source_candle_ts_utc):
        per_anchor: list[tuple[float, int, float, float, PartialResult, dict[str, Any], dict[str, Any]]] = []
        for offset_days in DEFAULT_PHASE_BANDS:
            partial = partial_match(
                candles=research_candles,
                symbol=symbol,
                venue="live",
                interval_code="1d",
                anchor=anchor_ts,
                as_of=source_candle_ts_utc,
                cycle_days=DEFAULT_CYCLE_DAYS,
                offset_days=offset_days,
                tolerance_hours=DEFAULT_TOLERANCE_HOURS,
                min_due_markers=DEFAULT_MIN_DUE_MARKERS,
                required_ratio=None,
            )
            current_marker, next_marker = _progression_markers(partial)
            if current_marker is None or next_marker is None:
                continue
            per_anchor.append(
                (
                    float(partial.partial_match_score),
                    int(partial.observed_marker_count),
                    float(current_marker.get("ratio") or 0.0),
                    -abs(float(offset_days)),
                    partial,
                    current_marker,
                    next_marker,
                )
            )

        if not per_anchor:
            continue

        per_anchor.sort(reverse=True, key=lambda item: item[:4])
        score, observed_count, current_ratio, abs_offset_rank, partial, current_marker, next_marker = per_anchor[0]
        if score < DEFAULT_MIN_PARTIAL_SCORE:
            continue

        rank = (score, observed_count, current_ratio, abs_offset_rank)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_candidate = BreathCurveResolvedCandidate(
                anchor_ts_utc=anchor_ts,
                partial_result=partial,
                phase_offset_band=nearest_band(
                    partial.phase_offset_days,
                    list(DEFAULT_PHASE_BANDS),
                    DEFAULT_PHASE_BAND_WIDTH_DAYS,
                ),
                current_marker=current_marker,
                next_marker=next_marker,
            )

    return best_candidate


def _lead_lag_vs_btc(
    *,
    symbol_candidate: BreathCurveResolvedCandidate | None,
    btc_candidate: BreathCurveResolvedCandidate | None,
) -> dict[str, Any] | None:
    if symbol_candidate is None or btc_candidate is None:
        return None

    delta_days = round(
        float(symbol_candidate.partial_result.phase_offset_days)
        - float(btc_candidate.partial_result.phase_offset_days),
        4,
    )
    if abs(delta_days) <= DEFAULT_PHASE_BAND_WIDTH_DAYS:
        relation = "IN_SYNC"
    elif delta_days > 0:
        relation = "AHEAD_OF_BTC"
    else:
        relation = "BEHIND_BTC"

    return {
        "relation": relation,
        "delta_days": delta_days,
        "btc_phase_offset_days": round(float(btc_candidate.partial_result.phase_offset_days), 4),
        "btc_phase_offset_band": btc_candidate.phase_offset_band,
    }


def _build_unavailable_payload(
    *,
    requested_as_of_ts_utc: datetime,
    source_candle_ts_utc: datetime | None,
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
        "data_coverage": data_coverage,
        "warnings": warnings,
    }


def _build_available_payload(
    *,
    requested_as_of_ts_utc: datetime,
    source_candle_ts_utc: datetime,
    candidate: BreathCurveResolvedCandidate,
    data_coverage: dict[str, Any],
    lead_lag_vs_btc: dict[str, Any] | None,
    warnings: list[str],
) -> dict[str, Any]:
    current_code = str(candidate.current_marker.get("code") or "").upper()
    next_code = str(candidate.next_marker.get("code") or "").upper()
    return {
        "availability_state": STATUS_AVAILABLE,
        "as_of_ts_utc": fmt_ts(requested_as_of_ts_utc),
        "source_candle_ts_utc": fmt_ts(source_candle_ts_utc),
        "freshness_label": FRESHNESS_FRESH,
        "phase_marker": current_code or None,
        "phase_offset_days": round(float(candidate.partial_result.phase_offset_days), 4),
        "phase_offset_band": candidate.phase_offset_band,
        "template_match_score": round(float(candidate.partial_result.partial_match_score), 4),
        "current_checkpoint": current_code or None,
        "next_checkpoint": next_code or None,
        "next_target_expected_ts_utc": candidate.next_marker.get("expected_ts_utc"),
        "next_target_is_future": True,
        "lead_lag_vs_btc": lead_lag_vs_btc,
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
    symbols_with_btc = list(dict.fromkeys([*requested_symbols, btc_symbol]))
    closed_by_symbol = {
        symbol: _sorted_closed_candles(candles_by_symbol.get(symbol, ()), as_of_ts_utc=requested_as_of)
        for symbol in symbols_with_btc
    }
    source_ts_by_symbol = {
        symbol: (_as_utc(closed[-1].close_ts_utc) if closed else None)
        for symbol, closed in closed_by_symbol.items()
    }
    candidate_by_symbol = {
        symbol: (
            _resolve_candidate(
                symbol=symbol,
                candles=closed_by_symbol[symbol],
                source_candle_ts_utc=source_ts,
            )
            if source_ts is not None and len(closed_by_symbol[symbol]) >= DEFAULT_MIN_REQUIRED_CANDLES
            else None
        )
        for symbol, source_ts in source_ts_by_symbol.items()
    }
    btc_candidate = candidate_by_symbol.get(btc_symbol)

    output: dict[str, dict[str, Any]] = {}
    for symbol in requested_symbols:
        closed = closed_by_symbol.get(symbol, [])
        source_ts = source_ts_by_symbol.get(symbol)
        coverage = _data_coverage(closed)
        freshness_label, freshness_reason = _freshness_state(
            requested_as_of_ts_utc=requested_as_of,
            source_candle_ts_utc=source_ts,
        )
        warnings: list[str] = []

        if source_ts is None:
            warnings.append("SOURCE_CANDLE_UNAVAILABLE")
            output[symbol] = _build_unavailable_payload(
                requested_as_of_ts_utc=requested_as_of,
                source_candle_ts_utc=None,
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
                data_coverage=coverage,
                warnings=warnings,
                freshness_label=FRESHNESS_UNAVAILABLE,
            )
            continue

        candidate = candidate_by_symbol.get(symbol)
        if candidate is None:
            warnings.append("ANCHOR_NOT_RESOLVED")
            output[symbol] = _build_unavailable_payload(
                requested_as_of_ts_utc=requested_as_of,
                source_candle_ts_utc=source_ts,
                data_coverage=coverage,
                warnings=warnings,
                freshness_label=FRESHNESS_UNAVAILABLE,
            )
            continue

        lead_lag_vs_btc = _lead_lag_vs_btc(
            symbol_candidate=candidate,
            btc_candidate=btc_candidate if symbol != btc_symbol else candidate,
        )
        if symbol != btc_symbol and lead_lag_vs_btc is None:
            warnings.append("BTC_RELATION_UNAVAILABLE")

        output[symbol] = _build_available_payload(
            requested_as_of_ts_utc=requested_as_of,
            source_candle_ts_utc=source_ts,
            candidate=candidate,
            data_coverage=coverage,
            lead_lag_vs_btc=lead_lag_vs_btc,
            warnings=warnings,
        )

    return output
