from __future__ import annotations

import argparse
import csv
import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "fib_wave_sequence_visual_preview_v1"
REPORT_VERSION = "0.1"
SOURCE_TABLE = "obs_market_candle"

DEFAULT_VENUE = "bitvavo"
DEFAULT_SYMBOL = "BTC"
DEFAULT_INTERVAL = "1d"
DEFAULT_LOOKBACK_CANDLES = 900
DEFAULT_DETECTOR = "zigzag_percent"
DEFAULT_SWING_WINDOW = 10
DEFAULT_ZIGZAG_PERCENT = 20.0
DEFAULT_MAJOR_FILTER = "none"
DEFAULT_MIN_LEG_VS_PREVIOUS_RATIO = 0.0
DEFAULT_MIN_LEG_DURATION_CANDLES = 0
DEFAULT_STRUCTURAL_FILTER = "none"
DEFAULT_SEQUENCE_MODE = "latest"
DEFAULT_SEQUENCE_LENGTH = 9
DEFAULT_ANCHOR_REFINEMENT = "none"
DEFAULT_CANDIDATE_SCAN = "none"
DEFAULT_CANDIDATE_SCAN_LENGTH = 9
DEFAULT_CANDIDATE_TOP_N = 10
DEFAULT_OUTPUT_HTML = "/tmp/fib_wave_sequence_BTC_1d.html"

SVG_WIDTH = 1120
SVG_HEIGHT = 360
SVG_PAD_LEFT = 64
SVG_PAD_RIGHT = 24
SVG_PAD_TOP = 22
SVG_PAD_BOTTOM = 44

WAVE_NAMES = ["W1", "W2", "W3", "W4", "W5", "A", "B", "C"]
FIBO_REFERENCES = [0.236, 0.382, 0.500, 0.618, 0.786, 1.000, 1.272, 1.414, 1.618, 2.000, 2.618, 3.618, 4.236]


@dataclass(frozen=True)
class AssetRef:
    asset_id: int
    symbol: str


@dataclass(frozen=True)
class Candle:
    candle_index: int
    open_ts_utc: datetime
    close_ts_utc: datetime
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float


@dataclass(frozen=True)
class Pivot:
    candle_index: int
    pivot_kind: str
    ts_utc: datetime
    price: float


@dataclass(frozen=True)
class SequenceCandidate:
    sequence_id: int
    start_index: int
    end_index: int
    pivots: list[Pivot]
    has_complete_sequence: bool


@dataclass(frozen=True)
class RefinedAnchor:
    raw_pivot: Pivot
    refined_pivot: Pivot
    changed: bool


@dataclass(frozen=True)
class PivotDiagnosticRow:
    pivot_index: int
    source_layer: str
    ts_utc: str
    type: str
    price: str
    previous_pivot_index: str
    previous_type: str
    previous_price: str
    move_from_previous_abs: str
    move_from_previous_pct: str
    direction_from_previous: str
    structural_note: str


@dataclass(frozen=True)
class CandidateScanRow:
    candidate_rank: int
    start_index: int
    end_index: int
    candidate_length: int
    p0_ts: str
    p0_price: str
    p0_type: str
    basis_direction: str
    wave2_vs_wave1: float | None
    wave3_vs_wave1: float | None
    wave4_vs_wave3: float | None
    wave5_vs_wave1: float | None
    wave5_vs_wave3: float | None
    b_vs_a: float | None
    c_vs_a: float | None
    fibo_magnet_score: float | None
    fibo_magnet_hit_count: int
    fibo_magnet_ratio_count: int
    elliott_shape_score: float
    combined_candidate_score: float | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render a static visual preview of the latest candidate P0-P8 wave sequence "
            "from public candles only (research-only, candidate labels only, no targets)."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
    parser.add_argument(
        "--detector",
        choices=("local_pivot_window", "zigzag_percent"),
        default=DEFAULT_DETECTOR,
    )
    parser.add_argument("--swing-window", type=int, default=DEFAULT_SWING_WINDOW)
    parser.add_argument("--zigzag-percent", type=float, default=DEFAULT_ZIGZAG_PERCENT)
    parser.add_argument(
        "--major-filter",
        choices=("none", "relative_move", "duration", "relative_move_and_duration"),
        default=DEFAULT_MAJOR_FILTER,
    )
    parser.add_argument(
        "--structural-filter",
        choices=("none", "strict_progression"),
        default=DEFAULT_STRUCTURAL_FILTER,
    )
    parser.add_argument(
        "--min-leg-vs-previous-ratio",
        type=float,
        default=DEFAULT_MIN_LEG_VS_PREVIOUS_RATIO,
    )
    parser.add_argument(
        "--min-leg-duration-candles",
        type=int,
        default=DEFAULT_MIN_LEG_DURATION_CANDLES,
    )
    parser.add_argument(
        "--sequence-mode",
        choices=("latest", "start-index", "all"),
        default=DEFAULT_SEQUENCE_MODE,
    )
    parser.add_argument("--sequence-start-index", type=int, default=None)
    parser.add_argument("--sequence-length", type=int, default=DEFAULT_SEQUENCE_LENGTH)
    parser.add_argument(
        "--anchor-refinement",
        choices=("none", "segment_extreme"),
        default=DEFAULT_ANCHOR_REFINEMENT,
    )
    parser.add_argument(
        "--candidate-scan",
        choices=("none", "all-starts"),
        default=DEFAULT_CANDIDATE_SCAN,
    )
    parser.add_argument(
        "--candidate-scan-length",
        type=int,
        default=DEFAULT_CANDIDATE_SCAN_LENGTH,
    )
    parser.add_argument(
        "--candidate-top-n",
        type=int,
        default=DEFAULT_CANDIDATE_TOP_N,
    )
    parser.add_argument("--write-pivot-diagnostics", default=None)
    parser.add_argument("--output-html", default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def fmt_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.10f}"


def fmt_number(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def fetch_asset(conn: Any, *, symbol: str) -> AssetRef:
    sql = """
        SELECT asset_id, symbol
        FROM asset
        WHERE UPPER(symbol) = UPPER(%s)
          AND is_enabled = 1
        ORDER BY asset_id ASC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (symbol,))
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Enabled asset not found for symbol={symbol}")
    return AssetRef(asset_id=int(row["asset_id"]), symbol=str(row["symbol"]).upper())


def fetch_recent_candles(
    conn: Any,
    *,
    asset: AssetRef,
    venue: str,
    interval_code: str,
    lookback_candles: int,
) -> list[Candle]:
    sql = """
        SELECT
            open_ts_utc,
            close_ts_utc,
            open_price,
            close_price,
            high_price,
            low_price,
            COALESCE(volume_quote_eur, volume_base, 0) AS volume
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND asset_id = %s
        ORDER BY close_ts_utc DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, asset.asset_id, lookback_candles))
        rows = list(cur.fetchall())

    candles: list[Candle] = []
    for idx, row in enumerate(reversed(rows)):
        open_ts = row["open_ts_utc"]
        close_ts = row["close_ts_utc"]
        if open_ts.tzinfo is None:
            open_ts = open_ts.replace(tzinfo=UTC)
        else:
            open_ts = open_ts.astimezone(UTC)
        if close_ts.tzinfo is None:
            close_ts = close_ts.replace(tzinfo=UTC)
        else:
            close_ts = close_ts.astimezone(UTC)
        candles.append(
            Candle(
                candle_index=idx,
                open_ts_utc=open_ts,
                close_ts_utc=close_ts,
                open_price=float(row["open_price"]),
                close_price=float(row["close_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                volume=float(row["volume"]),
            )
        )
    return candles


def start_of_utc_week(value: datetime) -> datetime:
    normalized = value.astimezone(UTC)
    week_start_date = (normalized - timedelta(days=normalized.weekday())).date()
    return datetime(
        week_start_date.year,
        week_start_date.month,
        week_start_date.day,
        tzinfo=UTC,
    )


def aggregate_daily_to_weekly(
    daily_candles: list[Candle],
    *,
    min_daily_candles_per_week: int = 3,
) -> list[Candle]:
    if not daily_candles:
        return []

    grouped: list[list[Candle]] = []
    current_group: list[Candle] = []
    current_week_start: datetime | None = None

    for candle in daily_candles:
        week_start = start_of_utc_week(candle.close_ts_utc)
        if current_week_start is None or week_start != current_week_start:
            if current_group:
                grouped.append(current_group)
            current_group = [candle]
            current_week_start = week_start
        else:
            current_group.append(candle)
    if current_group:
        grouped.append(current_group)

    weekly: list[Candle] = []
    for group in grouped:
        if len(group) < min_daily_candles_per_week:
            continue
        first = group[0]
        last = group[-1]
        weekly.append(
            Candle(
                candle_index=len(weekly),
                open_ts_utc=first.open_ts_utc,
                close_ts_utc=last.close_ts_utc,
                open_price=first.open_price,
                close_price=last.close_price,
                high_price=max(candle.high_price for candle in group),
                low_price=min(candle.low_price for candle in group),
                volume=sum(candle.volume for candle in group),
            )
        )
    return weekly


def compress_same_type_pivots(pivots: list[Pivot]) -> list[Pivot]:
    compressed: list[Pivot] = []
    for pivot in pivots:
        if not compressed:
            compressed.append(pivot)
            continue
        previous = compressed[-1]
        if pivot.pivot_kind != previous.pivot_kind:
            compressed.append(pivot)
            continue
        if pivot.pivot_kind == "HIGH":
            if pivot.price > previous.price:
                compressed[-1] = pivot
        else:
            if pivot.price < previous.price:
                compressed[-1] = pivot
    return compressed


def detect_local_pivots(candles: list[Candle], window: int) -> list[Pivot]:
    if len(candles) < (window * 2) + 1:
        return []
    pivots: list[Pivot] = []
    for idx in range(window, len(candles) - window):
        current = candles[idx]
        window_slice = candles[idx - window : idx + window + 1]
        highs = [candle.high_price for candle in window_slice]
        lows = [candle.low_price for candle in window_slice]
        is_high = current.high_price == max(highs) and highs.count(current.high_price) == 1
        is_low = current.low_price == min(lows) and lows.count(current.low_price) == 1
        if is_high:
            pivots.append(
                Pivot(
                    candle_index=current.candle_index,
                    pivot_kind="HIGH",
                    ts_utc=current.close_ts_utc,
                    price=current.high_price,
                )
            )
        if is_low:
            pivots.append(
                Pivot(
                    candle_index=current.candle_index,
                    pivot_kind="LOW",
                    ts_utc=current.close_ts_utc,
                    price=current.low_price,
                )
            )
    pivots.sort(key=lambda item: (item.candle_index, 0 if item.pivot_kind == "LOW" else 1))
    return compress_same_type_pivots(pivots)


def detect_zigzag_percent(candles: list[Candle], percent_threshold: float) -> list[Pivot]:
    if len(candles) < 2:
        return []
    threshold_ratio = percent_threshold / 100.0
    start = candles[0]
    candidate = Pivot(
        candle_index=start.candle_index,
        pivot_kind="SEED",
        ts_utc=start.close_ts_utc,
        price=start.close_price,
    )
    trend: str | None = None
    extreme = candidate
    pivots: list[Pivot] = []

    for candle in candles[1:]:
        price = candle.close_price
        if trend is None:
            if price >= candidate.price * (1.0 + threshold_ratio):
                pivots.append(
                    Pivot(
                        candle_index=candidate.candle_index,
                        pivot_kind="LOW",
                        ts_utc=candidate.ts_utc,
                        price=candidate.price,
                    )
                )
                trend = "UP"
                extreme = Pivot(candle.candle_index, "HIGH", candle.close_ts_utc, price)
            elif price <= candidate.price * (1.0 - threshold_ratio):
                pivots.append(
                    Pivot(
                        candle_index=candidate.candle_index,
                        pivot_kind="HIGH",
                        ts_utc=candidate.ts_utc,
                        price=candidate.price,
                    )
                )
                trend = "DOWN"
                extreme = Pivot(candle.candle_index, "LOW", candle.close_ts_utc, price)
            continue

        if trend == "UP":
            if price > extreme.price:
                extreme = Pivot(candle.candle_index, "HIGH", candle.close_ts_utc, price)
                continue
            if price <= extreme.price * (1.0 - threshold_ratio):
                pivots.append(extreme)
                trend = "DOWN"
                extreme = Pivot(candle.candle_index, "LOW", candle.close_ts_utc, price)
            continue

        if price < extreme.price:
            extreme = Pivot(candle.candle_index, "LOW", candle.close_ts_utc, price)
            continue
        if price >= extreme.price * (1.0 + threshold_ratio):
            pivots.append(extreme)
            trend = "UP"
            extreme = Pivot(candle.candle_index, "HIGH", candle.close_ts_utc, price)

    return compress_same_type_pivots(pivots)


def basis_direction(sequence: list[Pivot]) -> str:
    if len(sequence) < 2:
        return ""
    return "UP" if sequence[1].price > sequence[0].price else "DOWN"


def select_sequence_latest(pivots: list[Pivot], sequence_length: int) -> SequenceCandidate:
    if not pivots:
        return SequenceCandidate(0, 0, -1, [], False)
    if len(pivots) >= sequence_length:
        start_index = len(pivots) - sequence_length
    else:
        start_index = 0
    selected = pivots[start_index : start_index + sequence_length]
    return SequenceCandidate(
        sequence_id=0,
        start_index=start_index,
        end_index=start_index + len(selected) - 1,
        pivots=selected,
        has_complete_sequence=len(selected) == sequence_length,
    )


def select_sequence_start_index(
    pivots: list[Pivot],
    *,
    sequence_start_index: int,
    sequence_length: int,
) -> SequenceCandidate:
    if not pivots:
        return SequenceCandidate(0, sequence_start_index, sequence_start_index - 1, [], False)
    if sequence_start_index >= len(pivots):
        return SequenceCandidate(0, sequence_start_index, len(pivots) - 1, [], False)
    selected = pivots[sequence_start_index : sequence_start_index + sequence_length]
    return SequenceCandidate(
        sequence_id=0,
        start_index=sequence_start_index,
        end_index=sequence_start_index + len(selected) - 1,
        pivots=selected,
        has_complete_sequence=len(selected) == sequence_length,
    )


def build_sequence_candidates(pivots: list[Pivot], sequence_length: int) -> list[SequenceCandidate]:
    if not pivots:
        return []
    if len(pivots) < sequence_length:
        return [
            SequenceCandidate(
                sequence_id=0,
                start_index=0,
                end_index=len(pivots) - 1,
                pivots=list(pivots),
                has_complete_sequence=False,
            )
        ]
    candidates: list[SequenceCandidate] = []
    for start_index in range(0, len(pivots) - sequence_length + 1):
        selected = pivots[start_index : start_index + sequence_length]
        candidates.append(
            SequenceCandidate(
                sequence_id=len(candidates),
                start_index=start_index,
                end_index=start_index + len(selected) - 1,
                pivots=selected,
                has_complete_sequence=len(selected) == sequence_length,
            )
        )
    return candidates


def more_extreme_pivot(first: Pivot, second: Pivot) -> Pivot:
    if first.pivot_kind != second.pivot_kind:
        raise ValueError("Cannot compare pivots of different types")
    if first.pivot_kind == "HIGH":
        return second if second.price > first.price else first
    return second if second.price < first.price else first


def build_major_pivots(
    raw_pivots: list[Pivot],
    *,
    major_filter: str,
    min_leg_vs_previous_ratio: float,
    min_leg_duration_candles: int,
) -> list[Pivot]:
    if not raw_pivots:
        return []
    if major_filter == "none":
        return list(raw_pivots)

    accepted: list[Pivot] = [raw_pivots[0]]
    previous_major_leg_abs: float | None = None

    for candidate in raw_pivots[1:]:
        previous = accepted[-1]
        if candidate.pivot_kind == previous.pivot_kind:
            accepted[-1] = more_extreme_pivot(previous, candidate)
            continue

        candidate_leg_abs = abs(candidate.price - previous.price)
        candidate_leg_duration = candidate.candle_index - previous.candle_index

        passes_move = (
            previous_major_leg_abs is None
            or candidate_leg_abs >= previous_major_leg_abs * min_leg_vs_previous_ratio
        )
        passes_duration = candidate_leg_duration >= min_leg_duration_candles

        if major_filter == "relative_move":
            should_accept = passes_move
        elif major_filter == "duration":
            should_accept = passes_duration
        elif major_filter == "relative_move_and_duration":
            should_accept = passes_move and passes_duration
        else:
            raise ValueError(f"Unsupported major_filter={major_filter}")

        if should_accept:
            accepted.append(candidate)
            previous_major_leg_abs = candidate_leg_abs

    return compress_same_type_pivots(accepted)


def segment_extreme_pivot(
    candles: list[Candle],
    *,
    start_ts_utc: datetime,
    finish_ts_utc: datetime,
    pivot_kind: str,
) -> Pivot | None:
    segment = [
        candle
        for candle in candles
        if start_ts_utc <= candle.close_ts_utc <= finish_ts_utc
    ]
    if not segment:
        return None
    if pivot_kind == "HIGH":
        selected = max(segment, key=lambda candle: (candle.high_price, candle.close_ts_utc))
        return Pivot(
            candle_index=selected.candle_index,
            pivot_kind="HIGH",
            ts_utc=selected.close_ts_utc,
            price=selected.high_price,
        )
    selected = min(segment, key=lambda candle: (candle.low_price, candle.close_ts_utc))
    return Pivot(
        candle_index=selected.candle_index,
        pivot_kind="LOW",
        ts_utc=selected.close_ts_utc,
        price=selected.low_price,
    )


def refine_selected_sequence(
    candles: list[Candle],
    sequence: list[Pivot],
    *,
    anchor_refinement: str,
) -> list[RefinedAnchor]:
    if not sequence:
        return []
    refined: list[RefinedAnchor] = [
        RefinedAnchor(raw_pivot=sequence[0], refined_pivot=sequence[0], changed=False)
    ]
    if anchor_refinement == "none":
        for pivot in sequence[1:]:
            refined.append(RefinedAnchor(raw_pivot=pivot, refined_pivot=pivot, changed=False))
        return refined
    if anchor_refinement != "segment_extreme":
        raise ValueError(f"Unsupported anchor_refinement={anchor_refinement}")

    for index in range(1, len(sequence)):
        previous_raw = sequence[index - 1]
        current_raw = sequence[index]
        candidate = segment_extreme_pivot(
            candles,
            start_ts_utc=previous_raw.ts_utc,
            finish_ts_utc=current_raw.ts_utc,
            pivot_kind=current_raw.pivot_kind,
        )
        refined_pivot = candidate if candidate is not None else current_raw
        refined.append(
            RefinedAnchor(
                raw_pivot=current_raw,
                refined_pivot=refined_pivot,
                changed=(
                    refined_pivot.ts_utc != current_raw.ts_utc
                    or refined_pivot.price != current_raw.price
                ),
            )
        )
    return refined


def move_abs(sequence: list[Pivot], start_idx: int, finish_idx: int) -> float | None:
    if len(sequence) <= finish_idx:
        return None
    return abs(sequence[finish_idx].price - sequence[start_idx].price)


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def direction_between(previous: Pivot, current: Pivot) -> str:
    if current.price > previous.price:
        return "UP"
    if current.price < previous.price:
        return "DOWN"
    return "FLAT"


def structural_note(previous: Pivot | None, current: Pivot) -> str:
    if previous is None:
        return "FIRST_PIVOT"
    if previous.pivot_kind == current.pivot_kind:
        return "SAME_TYPE_AS_PREVIOUS"
    move_abs = abs(current.price - previous.price)
    if move_abs <= 0:
        return "ZERO_OR_INVALID_MOVE"
    if current.pivot_kind == "LOW" and current.price > previous.price:
        return "LOW_ABOVE_PREVIOUS_HIGH"
    if current.pivot_kind == "HIGH" and current.price < previous.price:
        return "HIGH_BELOW_PREVIOUS_LOW"
    return "OK"


def build_pivot_diagnostic_rows(
    *,
    raw_pivots: list[Pivot],
    structural_pivots: list[Pivot],
    major_pivots: list[Pivot],
    selected_sequence: list[Pivot],
) -> list[PivotDiagnosticRow]:
    rows: list[PivotDiagnosticRow] = []

    def append_rows(pivots: list[Pivot], source_layer: str) -> None:
        previous: Pivot | None = None
        for index, pivot in enumerate(pivots):
            move_abs = abs(pivot.price - previous.price) if previous is not None else None
            move_pct = None
            if previous is not None and previous.price != 0:
                move_pct = (abs(pivot.price - previous.price) / abs(previous.price)) * 100.0
            rows.append(
                PivotDiagnosticRow(
                    pivot_index=index,
                    source_layer=source_layer,
                    ts_utc=fmt_ts(pivot.ts_utc),
                    type=pivot.pivot_kind,
                    price=fmt_price(pivot.price),
                    previous_pivot_index="" if previous is None else str(index - 1),
                    previous_type="" if previous is None else previous.pivot_kind,
                    previous_price="" if previous is None else fmt_price(previous.price),
                    move_from_previous_abs=fmt_number(move_abs, digits=10),
                    move_from_previous_pct=fmt_number(move_pct),
                    direction_from_previous="" if previous is None else direction_between(previous, pivot),
                    structural_note=structural_note(previous, pivot),
                )
            )
            previous = pivot

    append_rows(raw_pivots, "RAW")
    append_rows(structural_pivots, "STRUCTURAL")
    append_rows(major_pivots, "MAJOR")
    append_rows(selected_sequence, "SELECTED")
    return rows


def build_structural_pivots(
    raw_pivots: list[Pivot],
    *,
    structural_filter: str,
) -> list[Pivot]:
    if not raw_pivots:
        return []
    if structural_filter == "none":
        return list(raw_pivots)
    if structural_filter != "strict_progression":
        raise ValueError(f"Unsupported structural_filter={structural_filter}")

    accepted: list[Pivot] = [raw_pivots[0]]
    for candidate in raw_pivots[1:]:
        note = structural_note(accepted[-1], candidate)
        if note in {"SAME_TYPE_AS_PREVIOUS", "ZERO_OR_INVALID_MOVE"}:
            continue
        accepted.append(candidate)
    return accepted


def structural_warning_count(pivots: list[Pivot]) -> int:
    if not pivots:
        return 0
    previous: Pivot | None = None
    count = 0
    for pivot in pivots:
        note = structural_note(previous, pivot)
        if note in {"LOW_ABOVE_PREVIOUS_HIGH", "HIGH_BELOW_PREVIOUS_LOW"}:
            count += 1
        previous = pivot
    return count


def x_for_index(candle_index: int, total: int) -> float:
    usable = SVG_WIDTH - SVG_PAD_LEFT - SVG_PAD_RIGHT
    if total <= 1:
        return float(SVG_PAD_LEFT)
    return SVG_PAD_LEFT + (usable * candle_index / (total - 1))


def y_for_price(price: float, min_price: float, max_price: float) -> float:
    usable = SVG_HEIGHT - SVG_PAD_TOP - SVG_PAD_BOTTOM
    if max_price <= min_price:
        return SVG_PAD_TOP + (usable / 2.0)
    return SVG_PAD_TOP + ((max_price - price) / (max_price - min_price)) * usable


def chart_svg(
    candles: list[Candle],
    raw_pivots: list[Pivot],
    structural_pivots: list[Pivot],
    major_pivots: list[Pivot],
    refined_anchors: list[RefinedAnchor],
    sequence: list[Pivot],
) -> str:
    prices = [candle.close_price for candle in candles] + [pivot.price for pivot in raw_pivots]
    min_price = min(prices)
    max_price = max(prices)

    close_points = " ".join(
        f"{x_for_index(candle.candle_index, len(candles)):.2f},{y_for_price(candle.close_price, min_price, max_price):.2f}"
        for candle in candles
    )
    pivot_line_points = " ".join(
        f"{x_for_index(pivot.candle_index, len(candles)):.2f},{y_for_price(pivot.price, min_price, max_price):.2f}"
        for pivot in raw_pivots
    )
    structural_line_points = " ".join(
        f"{x_for_index(pivot.candle_index, len(candles)):.2f},{y_for_price(pivot.price, min_price, max_price):.2f}"
        for pivot in structural_pivots
    )
    major_line_points = " ".join(
        f"{x_for_index(pivot.candle_index, len(candles)):.2f},{y_for_price(pivot.price, min_price, max_price):.2f}"
        for pivot in major_pivots
    )
    sequence_points = " ".join(
        f"{x_for_index(pivot.candle_index, len(candles)):.2f},{y_for_price(pivot.price, min_price, max_price):.2f}"
        for pivot in sequence
    )

    raw_markers: list[str] = []
    for pivot in raw_pivots:
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        color = "#c4513d" if pivot.pivot_kind == "HIGH" else "#23845a"
        raw_markers.append(
            f"<circle cx='{x:.2f}' cy='{y:.2f}' r='2.8' fill='{color}' fill-opacity='0.55' stroke='none'></circle>"
        )
    structural_markers: list[str] = []
    for pivot in structural_pivots:
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        color = "#8a6a44"
        structural_markers.append(
            f"<circle cx='{x:.2f}' cy='{y:.2f}' r='4.2' fill='{color}' fill-opacity='0.8' stroke='#ffffff' stroke-width='1.0'></circle>"
        )
    major_markers: list[str] = []
    for pivot in major_pivots:
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        color = "#c4513d" if pivot.pivot_kind == "HIGH" else "#23845a"
        major_markers.append(
            f"<circle cx='{x:.2f}' cy='{y:.2f}' r='5.2' fill='{color}' stroke='#ffffff' stroke-width='1.3'></circle>"
        )
    refined_markers: list[str] = []
    for anchor in refined_anchors:
        x = x_for_index(anchor.refined_pivot.candle_index, len(candles))
        y = y_for_price(anchor.refined_pivot.price, min_price, max_price)
        refined_markers.append(
            f"<circle cx='{x:.2f}' cy='{y:.2f}' r='6.4' fill='none' stroke='#111111' stroke-width='1.6'></circle>"
        )

    p_labels: list[str] = []
    pivot_index_labels: list[str] = []
    wave_labels: list[str] = []
    for pivot_index, pivot in enumerate(major_pivots):
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        y_offset = -24 if pivot.pivot_kind == "HIGH" else 30
        pivot_index_labels.append(
            f"<text x='{x:.2f}' y='{y + y_offset:.2f}' class='index-label'>#{pivot_index}</text>"
        )
    for idx, pivot in enumerate(sequence):
        x = x_for_index(pivot.candle_index, len(candles))
        y = y_for_price(pivot.price, min_price, max_price)
        y_offset = -14 if pivot.pivot_kind == "HIGH" else 20
        p_labels.append(
            f"<text x='{x:.2f}' y='{y + y_offset:.2f}' class='p-label'>P{idx}</text>"
        )
        if idx < len(sequence) - 1:
            next_pivot = sequence[idx + 1]
            next_x = x_for_index(next_pivot.candle_index, len(candles))
            next_y = y_for_price(next_pivot.price, min_price, max_price)
            mx = (x + next_x) / 2.0
            my = (y + next_y) / 2.0 - 8.0
            wave_labels.append(
                f"<text x='{mx:.2f}' y='{my:.2f}' class='wave-label'>{WAVE_NAMES[idx]}</text>"
            )

    axis_labels = [
        (max_price, y_for_price(max_price, min_price, max_price)),
        ((max_price + min_price) / 2.0, y_for_price((max_price + min_price) / 2.0, min_price, max_price)),
        (min_price, y_for_price(min_price, min_price, max_price)),
    ]

    return f"""
<svg viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" class="chart" role="img" aria-label="Wave sequence preview">
  <rect x="0" y="0" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="#fffdfa"></rect>
  <line x1="{SVG_PAD_LEFT}" y1="{SVG_HEIGHT - SVG_PAD_BOTTOM}" x2="{SVG_WIDTH - SVG_PAD_RIGHT}" y2="{SVG_HEIGHT - SVG_PAD_BOTTOM}" class="axis"></line>
  <line x1="{SVG_PAD_LEFT}" y1="{SVG_PAD_TOP}" x2="{SVG_PAD_LEFT}" y2="{SVG_HEIGHT - SVG_PAD_BOTTOM}" class="axis"></line>
  <polyline points="{close_points}" class="close-line"></polyline>
  <polyline points="{pivot_line_points}" class="raw-pivot-line"></polyline>
  <polyline points="{structural_line_points}" class="structural-pivot-line"></polyline>
  <polyline points="{major_line_points}" class="major-pivot-line"></polyline>
  <polyline points="{sequence_points}" class="sequence-line"></polyline>
  {''.join(raw_markers)}
  {''.join(structural_markers)}
  {''.join(major_markers)}
  {''.join(refined_markers)}
  {''.join(pivot_index_labels)}
  {''.join(p_labels)}
  {''.join(wave_labels)}
  {''.join(f"<text x='8' y='{y:.2f}' class='axis-label'>{esc(fmt_price(price))}</text>" for price, y in axis_labels)}
</svg>
"""


def detector_params(args: argparse.Namespace) -> str:
    if args.detector == "local_pivot_window":
        return f"swing_window={args.swing_window} source=high_low"
    return f"zigzag_percent={args.zigzag_percent:g} source=close"


def sequence_metrics(sequence: list[Pivot]) -> dict[str, float | None]:
    wave1 = move_abs(sequence, 0, 1)
    wave2 = move_abs(sequence, 1, 2)
    wave3 = move_abs(sequence, 2, 3)
    wave4 = move_abs(sequence, 3, 4)
    wave5 = move_abs(sequence, 4, 5)
    wave_a = move_abs(sequence, 5, 6)
    wave_b = move_abs(sequence, 6, 7)
    wave_c = move_abs(sequence, 7, 8)
    return {
        "wave1_move_abs": wave1,
        "wave2_move_abs": wave2,
        "wave3_move_abs": wave3,
        "wave4_move_abs": wave4,
        "wave5_move_abs": wave5,
        "waveA_move_abs": wave_a,
        "waveB_move_abs": wave_b,
        "waveC_move_abs": wave_c,
        "wave2_vs_wave1": ratio(wave2, wave1) if len(sequence) >= 3 else None,
        "wave3_vs_wave1": ratio(wave3, wave1) if len(sequence) >= 4 else None,
        "wave4_vs_wave3": ratio(wave4, wave3) if len(sequence) >= 5 else None,
        "wave5_vs_wave1": ratio(wave5, wave1) if len(sequence) >= 6 else None,
        "wave5_vs_wave3": ratio(wave5, wave3) if len(sequence) >= 6 else None,
        "waveB_vs_waveA": ratio(wave_b, wave_a) if len(sequence) >= 8 else None,
        "waveC_vs_waveA": ratio(wave_c, wave_a) if len(sequence) >= 9 else None,
    }


def fibo_magnet_score(metrics: dict[str, float | None]) -> tuple[float | None, int, int]:
    ratios = [
        metrics.get("wave2_vs_wave1"),
        metrics.get("wave3_vs_wave1"),
        metrics.get("wave4_vs_wave3"),
        metrics.get("wave5_vs_wave1"),
        metrics.get("wave5_vs_wave3"),
        metrics.get("waveB_vs_waveA"),
        metrics.get("waveC_vs_waveA"),
    ]
    deltas: list[float] = []
    hit_count = 0
    for value in ratios:
        if value is None:
            continue
        nearest = min(FIBO_REFERENCES, key=lambda reference: abs(value - reference))
        delta = abs(value - nearest)
        deltas.append(delta)
        if delta <= 0.05:
            hit_count += 1
    if not deltas:
        return None, 0, 0
    return sum(deltas) / len(deltas), hit_count, len(deltas)


def elliott_shape_score(sequence: list[Pivot], metrics: dict[str, float | None]) -> float:
    score = 0.0
    if len(sequence) < 4:
        score -= 2.0
    if metrics.get("wave2_vs_wave1") is None:
        score -= 1.0
    if metrics.get("wave3_vs_wave1") is None:
        score -= 1.0
    wave2_vs_wave1 = metrics.get("wave2_vs_wave1")
    if wave2_vs_wave1 is not None and (wave2_vs_wave1 < 0.236 or wave2_vs_wave1 > 0.90):
        score -= 1.0
    wave3_vs_wave1 = metrics.get("wave3_vs_wave1")
    if wave3_vs_wave1 is not None and wave3_vs_wave1 < 1.0:
        score -= 1.0
    wave4_vs_wave3 = metrics.get("wave4_vs_wave3")
    if wave4_vs_wave3 is not None and wave4_vs_wave3 > 0.786:
        score -= 1.0
    if len(sequence) >= 6:
        wave1 = metrics.get("wave1_move_abs")
        wave3 = metrics.get("wave3_move_abs")
        wave5 = metrics.get("wave5_move_abs")
        if wave1 is not None and wave3 is not None and wave5 is not None:
            if wave3 <= wave1 and wave3 <= wave5:
                score -= 2.0
    return score


def build_candidate_scan_rows(
    *,
    candles: list[Candle],
    major_pivots: list[Pivot],
    anchor_refinement: str,
    candidate_scan: str,
    candidate_scan_length: int,
) -> list[CandidateScanRow]:
    if candidate_scan == "none" or not major_pivots:
        return []
    if candidate_scan != "all-starts":
        raise ValueError(f"Unsupported candidate_scan={candidate_scan}")

    rows: list[CandidateScanRow] = []
    for start_index in range(len(major_pivots)):
        selected = major_pivots[start_index : start_index + candidate_scan_length]
        if len(selected) < 4:
            continue
        refined = refine_selected_sequence(
            candles,
            selected,
            anchor_refinement=anchor_refinement,
        )
        sequence = [anchor.refined_pivot for anchor in refined]
        metrics = sequence_metrics(sequence)
        magnet_score, hit_count, ratio_count = fibo_magnet_score(metrics)
        shape_score = elliott_shape_score(sequence, metrics)
        combined_score = None if magnet_score is None else shape_score - magnet_score
        rows.append(
            CandidateScanRow(
                candidate_rank=0,
                start_index=start_index,
                end_index=start_index + len(sequence) - 1,
                candidate_length=len(sequence),
                p0_ts=fmt_ts(sequence[0].ts_utc),
                p0_price=fmt_price(sequence[0].price),
                p0_type=sequence[0].pivot_kind,
                basis_direction=basis_direction(sequence),
                wave2_vs_wave1=metrics.get("wave2_vs_wave1"),
                wave3_vs_wave1=metrics.get("wave3_vs_wave1"),
                wave4_vs_wave3=metrics.get("wave4_vs_wave3"),
                wave5_vs_wave1=metrics.get("wave5_vs_wave1"),
                wave5_vs_wave3=metrics.get("wave5_vs_wave3"),
                b_vs_a=metrics.get("waveB_vs_waveA"),
                c_vs_a=metrics.get("waveC_vs_waveA"),
                fibo_magnet_score=magnet_score,
                fibo_magnet_hit_count=hit_count,
                fibo_magnet_ratio_count=ratio_count,
                elliott_shape_score=shape_score,
                combined_candidate_score=combined_score,
            )
        )

    sorted_rows = sorted(
        rows,
        key=lambda row: (
            -(row.combined_candidate_score if row.combined_candidate_score is not None else -999999.0),
            row.fibo_magnet_score if row.fibo_magnet_score is not None else 999999.0,
            -row.candidate_length,
            row.start_index,
        ),
    )
    ranked: list[CandidateScanRow] = []
    for rank, row in enumerate(sorted_rows, start=1):
        ranked.append(
            CandidateScanRow(
                candidate_rank=rank,
                start_index=row.start_index,
                end_index=row.end_index,
                candidate_length=row.candidate_length,
                p0_ts=row.p0_ts,
                p0_price=row.p0_price,
                p0_type=row.p0_type,
                basis_direction=row.basis_direction,
                wave2_vs_wave1=row.wave2_vs_wave1,
                wave3_vs_wave1=row.wave3_vs_wave1,
                wave4_vs_wave3=row.wave4_vs_wave3,
                wave5_vs_wave1=row.wave5_vs_wave1,
                wave5_vs_wave3=row.wave5_vs_wave3,
                b_vs_a=row.b_vs_a,
                c_vs_a=row.c_vs_a,
                fibo_magnet_score=row.fibo_magnet_score,
                fibo_magnet_hit_count=row.fibo_magnet_hit_count,
                fibo_magnet_ratio_count=row.fibo_magnet_ratio_count,
                elliott_shape_score=row.elliott_shape_score,
                combined_candidate_score=row.combined_candidate_score,
            )
        )
    return ranked


def detail_table(
    *,
    symbol: str,
    interval: str,
    detector: str,
    detector_params_value: str,
    lookback_candles: int,
    raw_pivots: list[Pivot],
    structural_pivots: list[Pivot],
    major_pivots: list[Pivot],
    structural_filter: str,
    major_filter: str,
    min_leg_vs_previous_ratio: float,
    min_leg_duration_candles: int,
    sequence_mode: str,
    sequence_start_index: int | None,
    sequence_length: int,
    anchor_refinement: str,
    refined_anchors: list[RefinedAnchor],
    sequence: list[Pivot],
) -> str:
    rows: list[tuple[str, str]] = [
        ("symbol", symbol),
        ("interval", interval),
        ("detector", detector),
        ("detector_params", detector_params_value),
        ("lookback_candles", str(lookback_candles)),
        ("raw_pivot_count", str(len(raw_pivots))),
        ("structural_filtered_pivot_count", str(len(structural_pivots))),
        ("removed_structural_pivot_count", str(max(0, len(raw_pivots) - len(structural_pivots)))),
        ("major_pivot_count", str(len(major_pivots))),
        ("removed_minor_pivot_count", str(max(0, len(structural_pivots) - len(major_pivots)))),
        ("structural_filter", structural_filter),
        ("major_filter", major_filter),
        ("min_leg_vs_previous_ratio", fmt_number(min_leg_vs_previous_ratio)),
        ("min_leg_duration_candles", str(min_leg_duration_candles)),
        ("sequence_mode", sequence_mode),
        ("sequence_start_index", "" if sequence_start_index is None else str(sequence_start_index)),
        ("sequence_length", str(sequence_length)),
        ("selected_sequence_length", str(len(sequence))),
        ("anchor_refinement", anchor_refinement),
        ("refined_anchor_changed_count", str(sum(1 for anchor in refined_anchors if anchor.changed))),
        ("pivot_count", str(len(major_pivots))),
        ("has_complete_sequence", "1" if len(sequence) == sequence_length else "0"),
    ]
    for idx in range(sequence_length):
        pivot = sequence[idx] if len(sequence) > idx else None
        refined = refined_anchors[idx] if len(refined_anchors) > idx else None
        raw_pivot = refined.raw_pivot if refined else None
        rows.append((f"P{idx} major_pivot_index", str(major_pivots.index(raw_pivot)) if raw_pivot in major_pivots else ""))
        rows.append((f"P{idx} raw_ts", fmt_ts(raw_pivot.ts_utc) if raw_pivot else ""))
        rows.append((f"P{idx} raw_price", fmt_price(raw_pivot.price) if raw_pivot else ""))
        rows.append((f"P{idx} raw_type", raw_pivot.pivot_kind if raw_pivot else ""))
        rows.append((f"P{idx} refined_ts", fmt_ts(pivot.ts_utc) if pivot else ""))
        rows.append((f"P{idx} refined_price", fmt_price(pivot.price) if pivot else ""))
        rows.append((f"P{idx} refined_type", pivot.pivot_kind if pivot else ""))
        rows.append((f"P{idx} refined_changed", "1" if refined and refined.changed else "0"))

    metrics = sequence_metrics(sequence) if len(sequence) >= 2 else {}
    for key in (
        "wave1_move_abs",
        "wave2_move_abs",
        "wave3_move_abs",
        "wave4_move_abs",
        "wave5_move_abs",
        "waveA_move_abs",
        "waveB_move_abs",
        "waveC_move_abs",
        "wave2_vs_wave1",
        "wave3_vs_wave1",
        "wave4_vs_wave3",
        "wave5_vs_wave1",
        "wave5_vs_wave3",
        "waveB_vs_waveA",
        "waveC_vs_waveA",
    ):
        rows.append((key, fmt_number(metrics.get(key))))

    return "".join(f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>" for key, value in rows)


def render_html(
    *,
    venue: str,
    symbol: str,
    interval: str,
    detector: str,
    detector_params_value: str,
    lookback_candles: int,
    source_interval: str,
    aggregated_interval: str,
    candles: list[Candle],
    raw_pivots: list[Pivot],
    structural_pivots: list[Pivot],
    major_pivots: list[Pivot],
    structural_filter: str,
    major_filter: str,
    min_leg_vs_previous_ratio: float,
    min_leg_duration_candles: int,
    sequence_mode: str,
    sequence_start_index: int | None,
    sequence_length: int,
    sequence_candidates: list[SequenceCandidate],
    anchor_refinement: str,
    candidate_scan: str,
    candidate_scan_length: int,
    candidate_top_n: int,
    candidate_scan_rows: list[CandidateScanRow],
    refined_anchors: list[RefinedAnchor],
    pivot_diagnostics: list[PivotDiagnosticRow],
    sequence: list[Pivot],
) -> str:
    generated_at_utc = fmt_ts(datetime.now(UTC))
    rolling_table_html = ""
    if sequence_mode == "all":
        rolling_rows: list[str] = []
        for candidate in sequence_candidates:
            metrics = sequence_metrics(candidate.pivots) if len(candidate.pivots) >= 2 else {}
            rolling_rows.append(
                "<tr>"
                f"<td>{candidate.sequence_id}</td>"
                f"<td>{candidate.start_index}</td>"
                f"<td>{candidate.end_index}</td>"
                f"<td>{esc(fmt_ts(candidate.pivots[0].ts_utc) if candidate.pivots else '')}</td>"
                f"<td>{esc(fmt_ts(candidate.pivots[-1].ts_utc) if candidate.pivots else '')}</td>"
                f"<td>{len(candidate.pivots)}</td>"
                f"<td>{1 if candidate.has_complete_sequence else 0}</td>"
                f"<td>{esc(basis_direction(candidate.pivots))}</td>"
                f"<td>{esc(fmt_number(metrics.get('wave2_vs_wave1')))}</td>"
                f"<td>{esc(fmt_number(metrics.get('wave3_vs_wave1')))}</td>"
                f"<td>{esc(fmt_number(metrics.get('wave4_vs_wave3')))}</td>"
                f"<td>{esc(fmt_number(metrics.get('wave5_vs_wave1')))}</td>"
                f"<td>{esc(fmt_number(metrics.get('wave5_vs_wave3')))}</td>"
                f"<td>{esc(fmt_number(metrics.get('waveB_vs_waveA')))}</td>"
                f"<td>{esc(fmt_number(metrics.get('waveC_vs_waveA')))}</td>"
                "</tr>"
            )
        rolling_table_html = f"""
      <h2>Rolling Sequence Candidates</h2>
      <table class="detail-table all-seq-table">
        <thead>
          <tr>
            <th>sequence_id</th><th>start_index</th><th>end_index</th><th>start_ts</th><th>end_ts</th><th>length</th><th>has_complete_sequence</th><th>basis_direction</th><th>wave2_vs_wave1</th><th>wave3_vs_wave1</th><th>wave4_vs_wave3</th><th>wave5_vs_wave1</th><th>wave5_vs_wave3</th><th>waveB_vs_waveA</th><th>waveC_vs_waveA</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rolling_rows)}
        </tbody>
      </table>
"""
    candidate_scan_html = ""
    if candidate_scan == "all-starts":
        top_rows = candidate_scan_rows[:candidate_top_n]
        candidate_rows_html = "".join(
            "<tr>"
            f"<td>{row.candidate_rank}</td>"
            f"<td>{row.start_index}</td>"
            f"<td>{row.end_index}</td>"
            f"<td>{row.candidate_length}</td>"
            f"<td>{esc(row.p0_ts)}</td>"
            f"<td>{esc(row.p0_price)}</td>"
            f"<td>{esc(row.p0_type)}</td>"
            f"<td>{esc(row.basis_direction)}</td>"
            f"<td>{esc(fmt_number(row.wave2_vs_wave1))}</td>"
            f"<td>{esc(fmt_number(row.wave3_vs_wave1))}</td>"
            f"<td>{esc(fmt_number(row.wave4_vs_wave3))}</td>"
            f"<td>{esc(fmt_number(row.wave5_vs_wave1))}</td>"
            f"<td>{esc(fmt_number(row.wave5_vs_wave3))}</td>"
            f"<td>{esc(fmt_number(row.b_vs_a))}</td>"
            f"<td>{esc(fmt_number(row.c_vs_a))}</td>"
            f"<td>{esc(fmt_number(row.fibo_magnet_score))}</td>"
            f"<td>{row.fibo_magnet_hit_count}</td>"
            f"<td>{row.fibo_magnet_ratio_count}</td>"
            f"<td>{esc(fmt_number(row.elliott_shape_score))}</td>"
            f"<td>{esc(fmt_number(row.combined_candidate_score))}</td>"
            "</tr>"
            for row in top_rows
        )
        candidate_scan_html = f"""
      <h2>Wave Start Candidate Scan</h2>
      <p class="foot">Candidate ranking is research-only and does not auto-select anchors. candidate_scan={esc(candidate_scan)} candidate_scan_length={candidate_scan_length} candidate_top_n={candidate_top_n} candidate_count={len(candidate_scan_rows)}</p>
      <table class="detail-table all-seq-table">
        <thead>
          <tr>
            <th>candidate_rank</th><th>start_index</th><th>end_index</th><th>candidate_length</th><th>P0_ts</th><th>P0_price</th><th>P0_type</th><th>basis_direction</th><th>wave2_vs_wave1</th><th>wave3_vs_wave1</th><th>wave4_vs_wave3</th><th>wave5_vs_wave1</th><th>wave5_vs_wave3</th><th>B_vs_A</th><th>C_vs_A</th><th>fibo_magnet_score</th><th>fibo_magnet_hit_count</th><th>fibo_magnet_ratio_count</th><th>elliott_shape_score</th><th>combined_candidate_score</th>
          </tr>
        </thead>
        <tbody>
          {candidate_rows_html}
        </tbody>
      </table>
"""
    pivot_diag_rows = "".join(
        "<tr>"
        f"<td>{row.pivot_index}</td>"
        f"<td>{esc(row.source_layer)}</td>"
        f"<td>{esc(row.ts_utc)}</td>"
        f"<td>{esc(row.type)}</td>"
        f"<td>{esc(row.price)}</td>"
        f"<td>{esc(row.previous_pivot_index)}</td>"
        f"<td>{esc(row.previous_type)}</td>"
        f"<td>{esc(row.previous_price)}</td>"
        f"<td>{esc(row.move_from_previous_abs)}</td>"
        f"<td>{esc(row.move_from_previous_pct)}</td>"
        f"<td>{esc(row.direction_from_previous)}</td>"
        f"<td>{esc(row.structural_note)}</td>"
        "</tr>"
        for row in pivot_diagnostics
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fib Wave Sequence {esc(symbol)} {esc(interval)}</title>
  <style>
    :root {{
      --bg: #f5efe7;
      --paper: #fffdf9;
      --ink: #1f1d1a;
      --muted: #6f675d;
      --line: #d8cec2;
      --close: #2b3442;
      --raw-pivot: #b9a48a;
      --structural-pivot: #8a6a44;
      --major-pivot: #8a6a44;
      --sequence: #d14d41;
      --axis: #b7aa9a;
      --table-head: #f0e6d9;
      --wave: #915c2e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 28px;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(145,92,46,0.10), transparent 24%),
        linear-gradient(180deg, #f8f3eb 0%, var(--bg) 100%);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
    }}
    .hero, .panel {{
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: 0 14px 40px rgba(31, 29, 26, 0.06);
    }}
    .hero {{
      padding: 20px 22px;
      margin-bottom: 18px;
    }}
    .panel {{
      padding: 18px;
    }}
    h1, h2 {{
      margin: 0;
      font-family: "IBM Plex Serif", "Georgia", serif;
      font-weight: 600;
    }}
    .hero p {{
      margin: 10px 0 0;
      color: var(--muted);
    }}
    .chart {{
      width: 100%;
      height: auto;
      display: block;
      background: #fffdfa;
      border: 1px solid var(--line);
    }}
    .axis {{
      stroke: var(--axis);
      stroke-width: 1;
    }}
    .axis-label {{
      fill: var(--muted);
      font-size: 12px;
      font-family: "IBM Plex Mono", monospace;
    }}
    .close-line {{
      fill: none;
      stroke: var(--close);
      stroke-width: 1.8;
    }}
    .raw-pivot-line {{
      fill: none;
      stroke: var(--raw-pivot);
      stroke-width: 1.5;
      stroke-dasharray: 5 4;
    }}
    .major-pivot-line {{
      fill: none;
      stroke: var(--major-pivot);
      stroke-width: 1.8;
    }}
    .structural-pivot-line {{
      fill: none;
      stroke: var(--structural-pivot);
      stroke-width: 1.4;
      stroke-dasharray: 3 3;
    }}
    .sequence-line {{
      fill: none;
      stroke: var(--sequence);
      stroke-width: 3.0;
    }}
    .p-label {{
      fill: var(--sequence);
      font-size: 13px;
      font-weight: 700;
      text-anchor: middle;
      font-family: "IBM Plex Mono", monospace;
    }}
    .wave-label {{
      fill: var(--wave);
      font-size: 12px;
      font-weight: 700;
      text-anchor: middle;
      font-family: "IBM Plex Mono", monospace;
    }}
    .index-label {{
      fill: var(--muted);
      font-size: 11px;
      text-anchor: middle;
      font-family: "IBM Plex Mono", monospace;
    }}
    .detail-table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 14px;
    }}
    .detail-table th,
    .detail-table td {{
      border: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    .detail-table th {{
      width: 280px;
      background: var(--table-head);
      font-family: "IBM Plex Mono", monospace;
      font-weight: 600;
    }}
    .foot {{
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Fib Wave Sequence Visual Preview V1</h1>
      <p>venue={esc(venue)} symbol={esc(symbol)} interval={esc(interval)} source_interval={esc(source_interval)} aggregated_interval={esc(aggregated_interval)} detector={esc(detector)} rows={len(candles)} raw_pivot_count={len(raw_pivots)} structural_filtered_pivot_count={len(structural_pivots)} major_pivot_count={len(major_pivots)} generated_at_utc={esc(generated_at_utc)}</p>
      <p>Candidate labels only. This does not claim a correct Elliott count. No targets. No fib-level tests. No DB writes.</p>
    </section>
    <section class="panel">
      <h2>Selected Candidate Sequence</h2>
      <p class="foot">Source table: {esc(SOURCE_TABLE)}. Source interval: {esc(source_interval)}. Aggregated interval: {esc(aggregated_interval)}. Detector params: {esc(detector_params_value)}. Structural filter: {esc(structural_filter)}. Major filter: {esc(major_filter)}. Sequence mode: {esc(sequence_mode)}. Anchor refinement: {esc(anchor_refinement)}.</p>
      {chart_svg(candles, raw_pivots, structural_pivots, major_pivots, refined_anchors, sequence)}
      <table class="detail-table">
        <tbody>
          {detail_table(symbol=symbol, interval=interval, detector=detector, detector_params_value=detector_params_value, lookback_candles=lookback_candles, raw_pivots=raw_pivots, structural_pivots=structural_pivots, major_pivots=major_pivots, structural_filter=structural_filter, major_filter=major_filter, min_leg_vs_previous_ratio=min_leg_vs_previous_ratio, min_leg_duration_candles=min_leg_duration_candles, sequence_mode=sequence_mode, sequence_start_index=sequence_start_index, sequence_length=sequence_length, anchor_refinement=anchor_refinement, refined_anchors=refined_anchors, sequence=sequence)}
        </tbody>
      </table>
      <div class="foot">Raw pivots are shown with smaller markers. Structural pivots and major pivots are shown with larger markers. Refined anchors are shown with dark outlined markers. P0-P8 and W1/W2/W3/W4/W5/A/B/C remain candidate visual labels only for inspection.</div>
      {rolling_table_html}
      {candidate_scan_html}
      <h2>Pivot Diagnostics</h2>
      <table class="detail-table all-seq-table">
        <thead>
          <tr>
            <th>pivot_index</th><th>source_layer</th><th>ts_utc</th><th>type</th><th>price</th><th>previous_pivot_index</th><th>previous_type</th><th>previous_price</th><th>move_from_previous_abs</th><th>move_from_previous_pct</th><th>direction_from_previous</th><th>structural_note</th>
          </tr>
        </thead>
        <tbody>
          {pivot_diag_rows}
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""


def build_summary(
    *,
    symbol: str,
    interval: str,
    detector: str,
    rows: int,
    source_interval: str,
    aggregated_interval: str,
    aggregated_rows: int,
    raw_pivot_count: int,
    structural_filtered_pivot_count: int,
    major_pivot_count: int,
    structural_filter: str,
    structural_warning_count_value: int,
    sequence_mode: str,
    sequence_start_index: int | None,
    sequence_length: int,
    anchor_refinement: str,
    candidate_scan: str,
    candidate_scan_length: int,
    candidate_scan_rows: list[CandidateScanRow],
    refined_anchor_changed_count: int,
    selected_sequence: list[Pivot],
    has_complete_sequence: bool,
    output_html: Path,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "symbol": symbol,
        "interval": interval,
        "source_interval": source_interval,
        "aggregated_interval": aggregated_interval,
        "detector": detector,
        "structural_filter": structural_filter,
        "sequence_mode": sequence_mode,
        "sequence_start_index": sequence_start_index,
        "sequence_length": sequence_length,
        "anchor_refinement": anchor_refinement,
        "candidate_scan": candidate_scan,
        "candidate_scan_length": candidate_scan_length,
        "rows": rows,
        "aggregated_rows": aggregated_rows,
        "pivot_count": major_pivot_count,
        "raw_pivot_count": raw_pivot_count,
        "structural_filtered_pivot_count": structural_filtered_pivot_count,
        "removed_structural_pivot_count": max(0, raw_pivot_count - structural_filtered_pivot_count),
        "structural_warning_count": structural_warning_count_value,
        "major_pivot_count": major_pivot_count,
        "removed_minor_pivot_count": max(0, structural_filtered_pivot_count - major_pivot_count),
        "selected_sequence_length": len(selected_sequence),
        "candidate_count": len(candidate_scan_rows),
        "candidate_top_start_index": candidate_scan_rows[0].start_index if candidate_scan_rows else "",
        "candidate_top_combined_score": (
            fmt_number(candidate_scan_rows[0].combined_candidate_score)
            if candidate_scan_rows and candidate_scan_rows[0].combined_candidate_score is not None
            else ""
        ),
        "refined_anchor_changed_count": refined_anchor_changed_count,
        "has_complete_sequence": 1 if has_complete_sequence else 0,
        "selected_sequence_start_ts_utc": fmt_ts(selected_sequence[0].ts_utc) if selected_sequence else "",
        "selected_sequence_end_ts_utc": fmt_ts(selected_sequence[-1].ts_utc) if selected_sequence else "",
        "output_html": str(output_html),
        "db_writes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor": "none",
        "account_awareness": 0,
    }


def print_summary(summary: dict[str, Any]) -> None:
    for key in (
        "report",
        "version",
        "symbol",
        "interval",
        "source_interval",
        "aggregated_interval",
        "detector",
        "structural_filter",
        "sequence_mode",
        "sequence_start_index",
        "sequence_length",
        "anchor_refinement",
        "candidate_scan",
        "candidate_scan_length",
        "rows",
        "aggregated_rows",
        "pivot_count",
        "raw_pivot_count",
        "structural_filtered_pivot_count",
        "removed_structural_pivot_count",
        "structural_warning_count",
        "major_pivot_count",
        "removed_minor_pivot_count",
        "selected_sequence_length",
        "candidate_count",
        "candidate_top_start_index",
        "candidate_top_combined_score",
        "refined_anchor_changed_count",
        "has_complete_sequence",
        "selected_sequence_start_ts_utc",
        "selected_sequence_end_ts_utc",
        "output_html",
        "db_writes",
        "broker_private_calls",
        "broker_writes",
        "order_submission",
        "decision_gate_changes",
        "execution_planner_changes",
        "executor",
        "account_awareness",
    ):
        print(f"{key}={summary[key]}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.lookback_candles <= 0:
        raise ValueError("--lookback-candles must be > 0")
    if args.detector == "local_pivot_window" and args.swing_window <= 0:
        raise ValueError("--swing-window must be > 0")
    if args.detector == "zigzag_percent" and args.zigzag_percent <= 0:
        raise ValueError("--zigzag-percent must be > 0")
    if args.min_leg_vs_previous_ratio < 0:
        raise ValueError("--min-leg-vs-previous-ratio must be >= 0")
    if args.min_leg_duration_candles < 0:
        raise ValueError("--min-leg-duration-candles must be >= 0")
    if args.sequence_length <= 0:
        raise ValueError("--sequence-length must be > 0")
    if args.candidate_scan_length <= 0:
        raise ValueError("--candidate-scan-length must be > 0")
    if args.candidate_top_n <= 0:
        raise ValueError("--candidate-top-n must be > 0")
    if args.sequence_mode == "start-index" and args.sequence_start_index is None:
        raise ValueError("--sequence-start-index is required when --sequence-mode start-index")
    if args.sequence_start_index is not None and args.sequence_start_index < 0:
        raise ValueError("--sequence-start-index must be >= 0")

    source_interval = args.interval
    aggregated_interval = args.interval
    fetch_interval = args.interval
    fetch_lookback_candles = args.lookback_candles
    if args.interval == "1w":
        source_interval = "1d"
        aggregated_interval = "1w"
        fetch_interval = "1d"
        fetch_lookback_candles = max(args.lookback_candles * 8, args.lookback_candles)

    conn = get_connection()
    try:
        asset = fetch_asset(conn, symbol=args.symbol)
        candles = fetch_recent_candles(
            conn,
            asset=asset,
            venue=args.venue,
            interval_code=fetch_interval,
            lookback_candles=fetch_lookback_candles,
        )
    finally:
        conn.close()

    if not candles:
        raise ValueError(
            f"No candles found for venue={args.venue} symbol={asset.symbol} interval={fetch_interval}"
        )

    if args.interval == "1w":
        candles = aggregate_daily_to_weekly(candles)
        if args.lookback_candles > 0 and len(candles) > args.lookback_candles:
            candles = candles[-args.lookback_candles :]
            candles = [
                Candle(
                    candle_index=index,
                    open_ts_utc=candle.open_ts_utc,
                    close_ts_utc=candle.close_ts_utc,
                    open_price=candle.open_price,
                    close_price=candle.close_price,
                    high_price=candle.high_price,
                    low_price=candle.low_price,
                    volume=candle.volume,
                )
                for index, candle in enumerate(candles)
            ]
        if not candles:
            raise ValueError(
                f"No aggregated weekly candles available for venue={args.venue} symbol={asset.symbol}"
            )

    if args.detector == "local_pivot_window":
        raw_pivots = detect_local_pivots(candles, args.swing_window)
    else:
        raw_pivots = detect_zigzag_percent(candles, args.zigzag_percent)

    structural_pivots = build_structural_pivots(
        raw_pivots,
        structural_filter=args.structural_filter,
    )
    major_pivots = build_major_pivots(
        structural_pivots,
        major_filter=args.major_filter,
        min_leg_vs_previous_ratio=args.min_leg_vs_previous_ratio,
        min_leg_duration_candles=args.min_leg_duration_candles,
    )
    sequence_candidates = build_sequence_candidates(major_pivots, args.sequence_length)
    if args.sequence_mode == "latest":
        selected_candidate = select_sequence_latest(major_pivots, args.sequence_length)
    elif args.sequence_mode == "start-index":
        selected_candidate = select_sequence_start_index(
            major_pivots,
            sequence_start_index=args.sequence_start_index or 0,
            sequence_length=args.sequence_length,
        )
    else:
        selected_candidate = select_sequence_latest(major_pivots, args.sequence_length)
    refined_anchors = refine_selected_sequence(
        candles,
        selected_candidate.pivots,
        anchor_refinement=args.anchor_refinement,
    )
    sequence = [anchor.refined_pivot for anchor in refined_anchors]
    candidate_scan_rows = build_candidate_scan_rows(
        candles=candles,
        major_pivots=major_pivots,
        anchor_refinement=args.anchor_refinement,
        candidate_scan=args.candidate_scan,
        candidate_scan_length=args.candidate_scan_length,
    )
    pivot_diagnostics = build_pivot_diagnostic_rows(
        raw_pivots=raw_pivots,
        structural_pivots=structural_pivots,
        major_pivots=major_pivots,
        selected_sequence=sequence,
    )
    if args.write_pivot_diagnostics:
        write_csv(
            Path(args.write_pivot_diagnostics),
            [row.__dict__ for row in pivot_diagnostics],
        )
    output_html = Path(args.output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        render_html(
            venue=args.venue,
            symbol=asset.symbol,
            interval=args.interval,
            detector=args.detector,
            detector_params_value=detector_params(args),
            lookback_candles=args.lookback_candles,
            source_interval=source_interval,
            aggregated_interval=aggregated_interval,
            candles=candles,
            raw_pivots=raw_pivots,
            structural_pivots=structural_pivots,
            major_pivots=major_pivots,
            structural_filter=args.structural_filter,
            major_filter=args.major_filter,
            min_leg_vs_previous_ratio=args.min_leg_vs_previous_ratio,
            min_leg_duration_candles=args.min_leg_duration_candles,
            sequence_mode=args.sequence_mode,
            sequence_start_index=args.sequence_start_index,
            sequence_length=args.sequence_length,
            sequence_candidates=sequence_candidates,
            anchor_refinement=args.anchor_refinement,
            candidate_scan=args.candidate_scan,
            candidate_scan_length=args.candidate_scan_length,
            candidate_top_n=args.candidate_top_n,
            candidate_scan_rows=candidate_scan_rows,
            refined_anchors=refined_anchors,
            pivot_diagnostics=pivot_diagnostics,
            sequence=sequence,
        ),
        encoding="utf-8",
    )

    summary = build_summary(
        symbol=asset.symbol,
        interval=args.interval,
        source_interval=source_interval,
        aggregated_interval=aggregated_interval,
        detector=args.detector,
        structural_filter=args.structural_filter,
        structural_warning_count_value=structural_warning_count(structural_pivots),
        sequence_mode=args.sequence_mode,
        sequence_start_index=args.sequence_start_index,
        sequence_length=args.sequence_length,
        anchor_refinement=args.anchor_refinement,
        candidate_scan=args.candidate_scan,
        candidate_scan_length=args.candidate_scan_length,
        candidate_scan_rows=candidate_scan_rows,
        rows=len(candles),
        aggregated_rows=len(candles) if args.interval == "1w" else len(candles),
        raw_pivot_count=len(raw_pivots),
        structural_filtered_pivot_count=len(structural_pivots),
        major_pivot_count=len(major_pivots),
        refined_anchor_changed_count=sum(1 for anchor in refined_anchors if anchor.changed),
        selected_sequence=sequence,
        has_complete_sequence=selected_candidate.has_complete_sequence,
        output_html=output_html,
    )
    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=False))
    else:
        print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
