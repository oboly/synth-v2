from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.market_data.native_short_fib_context_v1 import (
    DEFAULT_ROWS_CSV as DEFAULT_NATIVE_SHORT_ROWS,
    STATUS_AVAILABLE as NATIVE_SHORT_CONTEXT_AVAILABLE,
    load_native_short_context_rows,
)
from src.reporting.account_scoped_short_trader_dashboard_v1 import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_VENUE,
    classify_market_prices_by_market,
    default_page_paths,
    load_account_scoped_short_dashboard_context,
    public_page_href,
    validate_profile_slug,
)
from src.reporting.account_dashboard_profile_access_v1 import resolve_dashboard_profile_access
from src.reporting.dashboard_style_v1 import cockpit_nav
from src.reporting.manual_short_trader_dashboard_v1 import (
    BrokerOrderRow,
    LadderOrderRow,
    build_all_sections,
)
from src.reporting.manual_short_trader_profit_plan_v1 import (
    FibExtContext,
    ProfitPlanCard,
    ReentryContext,
    TargetHistoryCandle,
    build_json_snapshot,
    build_profit_plan_card,
    render_full_html,
)
from src.research.htf_fib_extension_confluence_v1 import (
    HtfSwingInput,
    build_htf_extension_map,
)
from src.research.htf_fib_reentry_ladder_v1 import (
    HtfReentryInput,
    build_fib_retrace_ladder,
)


DEFAULT_FIB_MAP_ROWS = Path("data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv")
REPORT_NAME = "run_manual_short_trader_profit_plan_v1"
REPORT_VERSION = "0.2"
TARGET_HISTORY_INTERVAL = "1h"


@dataclass(frozen=True)
class ZoneContextLoadResult:
    fib_ext_by_symbol: dict[str, FibExtContext]
    reentry_by_symbol: dict[str, ReentryContext]
    activation_ts_by_symbol: dict[str, datetime | None]
    input_status_by_symbol: dict[str, str]
    coverage_status_by_symbol: dict[str, str]
    display_state_by_symbol: dict[str, str]
    source_name: str
    source_missing: bool


@dataclass(frozen=True)
class MarketTargetHistory:
    high_since_activation: Decimal | None
    low_since_activation: Decimal | None
    candles_since_activation: tuple[TargetHistoryCandle, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render the Synth v2 Profit Plan for exactly one account profile. "
            "Read-only DB snapshots only. No broker reads, no broker writes, no order submission."
        )
    )
    parser.add_argument("--account-profile", required=True, metavar="PROFILE")
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Synth web root. Outputs are written under accounts/<profile>/profit-plan.html/json.",
    )
    parser.add_argument(
        "--output-html",
        default=None,
        metavar="PATH",
        help="Optional explicit HTML output path. Defaults to accounts/<profile>/profit-plan.html under output-root.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        metavar="PATH",
        help="Optional explicit JSON output path. Defaults to accounts/<profile>/profit-plan.json under output-root.",
    )
    parser.add_argument(
        "--monitor-href",
        default=None,
        metavar="HREF",
        help="Public browser href for the Open Orders Monitor page. Defaults to /synth/accounts/<profile>/open-orders-monitor.html.",
    )
    parser.add_argument(
        "--native-short-context-rows",
        default=str(DEFAULT_NATIVE_SHORT_ROWS),
        help="Canonical native SHORT context rows path. Native 4h+1h rows are preferred when available.",
    )
    parser.add_argument(
        "--fib-map-rows",
        default=str(DEFAULT_FIB_MAP_ROWS),
        help="Optional: path to fibo_target_map_rows_v1.csv for read-only zone context.",
    )
    parser.add_argument(
        "--swing-anchors",
        nargs="+",
        default=[],
        metavar="SYMBOL:LOW:HIGH",
        help="Optional manual HTF swing anchors overriding source context for named symbols.",
    )
    parser.add_argument(
        "--recent-lows",
        nargs="+",
        default=[],
        metavar="SYMBOL:PRICE",
        help="Optional manual recent low prices overriding source context for named symbols.",
    )
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def _parse_kv_list(items: list[str], n_parts: int) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items:
        parts = item.split(":", n_parts - 1)
        if len(parts) == n_parts:
            result[parts[0].upper()] = parts[1:]
    return result


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _parse_iso_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except Exception:
        return None


def _native_price_band(
    *,
    current_price: Decimal,
    breakout_gate: Decimal,
    ext_1_272: Decimal,
    ext_1_618: Decimal,
    ext_2_000: Decimal,
) -> str:
    if current_price < breakout_gate:
        return "BELOW_BREAKOUT_GATE"
    if current_price < ext_1_272:
        return "ABOVE_GATE_APPROACHING_1272"
    if current_price < ext_1_618:
        return "BETWEEN_1272_1618"
    if current_price < ext_2_000:
        return "BETWEEN_1618_2000"
    return "ABOVE_2000"


def _short_context_gap_from_row(row: dict[str, str] | None) -> tuple[str, str]:
    if row is None:
        return "FIB_MAP_SYMBOL_MISSING", "NO_NATIVE_SHORT_FIB_CONTEXT"
    target_status = str(row.get("target_status") or "").strip().upper()
    anchor_reason = str(row.get("anchor_reason") or "").strip().lower()
    if target_status == "MISSING_MARKET_DATA" or "no_market_candles" in anchor_reason or "symbol_not_found_in_asset_universe" in anchor_reason:
        return "MARKET_DATA_MISSING", "MARKET_DATA_MISSING"
    if target_status in {"INSUFFICIENT_SWING", "NOT_IMPLEMENTED"}:
        return "CONTEXT_INVALID_OR_STALE", "CONTEXT_INVALID_OR_STALE"
    return "LEGACY_1D_CONTEXT_ONLY", "NO_NATIVE_SHORT_FIB_CONTEXT"


def summarize_short_context_coverage(
    *,
    markets: list[str],
    coverage_status_by_symbol: dict[str, str],
) -> dict[str, int]:
    summary = {
        "NATIVE_SHORT_CONTEXT_AVAILABLE": 0,
        "INSUFFICIENT_4H_HISTORY": 0,
        "INSUFFICIENT_1H_HISTORY": 0,
        "LEGACY_1D_CONTEXT_ONLY": 0,
        "FIB_MAP_SYMBOL_MISSING": 0,
        "FIB_MAP_SOURCE_MISSING": 0,
        "MARKET_DATA_MISSING": 0,
        "CONTEXT_INVALID_OR_STALE": 0,
    }
    for market in markets:
        symbol = market.split("-")[0].upper()
        status = coverage_status_by_symbol.get(symbol, "CONTEXT_INVALID_OR_STALE")
        summary[status] = summary.get(status, 0) + 1
    return summary


def load_fib_map_rows(path: Path) -> tuple[dict[str, dict[str, str]], bool]:
    if not path.exists():
        return {}, True
    rows_by_symbol: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol:
                rows_by_symbol[symbol] = {str(key): str(value or "") for key, value in row.items()}
    return rows_by_symbol, False


def _build_fib_ext_context(
    *,
    symbol: str,
    interval_code: str,
    swing_low: Decimal,
    swing_high: Decimal,
    current_price: Decimal,
    local_reaction_price: Decimal,
    anchor_end_ts_utc: datetime | None,
) -> FibExtContext | None:
    try:
        ext_map = build_htf_extension_map(
            HtfSwingInput(
                symbol=symbol,
                interval_code=interval_code,
                swing_low=swing_low,
                swing_high=swing_high,
                current_price=current_price,
            )
        )
    except Exception as exc:
        print(f"[warn] fib ext map failed for {symbol}: {exc}", file=sys.stderr)
        return None
    target_by_label = {target.label: target.price for target in ext_map.targets}
    return FibExtContext(
        ext_1_272=target_by_label.get("ext_1_272", swing_high),
        ext_1_618=target_by_label.get("ext_1_618", swing_high),
        ext_2_000=target_by_label.get("ext_2_000", swing_high),
        breakout_gate=ext_map.breakout_gate,
        local_reaction_price=local_reaction_price,
        anchor_end_ts_utc=anchor_end_ts_utc,
        price_band=ext_map.price_band,
        ext_1_272_touched_and_rejected=ext_map.ext_1_272_touched_and_rejected,
        retesting_breakout_gate=ext_map.retesting_breakout_gate,
    )


def _build_reentry_context(
    *,
    symbol: str,
    interval_code: str,
    swing_low: Decimal,
    swing_high: Decimal,
    current_price: Decimal,
    recent_low: Decimal | None,
) -> ReentryContext | None:
    try:
        ladder = build_fib_retrace_ladder(
            HtfReentryInput(
                symbol=symbol,
                interval_code=interval_code,
                swing_low=swing_low,
                swing_high=swing_high,
                current_price=current_price,
                recent_low_price=recent_low,
            )
        )
    except Exception as exc:
        print(f"[warn] reentry ladder failed for {symbol}: {exc}", file=sys.stderr)
        return None
    level_by_label = {row.label: row.price for row in ladder.levels}
    return ReentryContext(
        r382_price=level_by_label.get("retrace_0_382", swing_high),
        r500_price=level_by_label.get("retrace_0_500", swing_high),
        r618_price=level_by_label.get("retrace_0_618", swing_high),
        r786_price=level_by_label.get("retrace_0_786", swing_low),
        deepest_touched_label=ladder.deepest_touched_label,
        missed_main_rebuy_by_pct=ladder.missed_main_rebuy_by_pct,
    )


def load_zone_contexts(
    *,
    markets: list[str],
    prices: dict[str, Decimal],
    swing_anchors: dict[str, list[str]],
    recent_lows: dict[str, list[str]],
    native_short_rows_path: Path,
    fib_map_rows_path: Path,
) -> ZoneContextLoadResult:
    fib_rows_by_symbol, source_missing = load_fib_map_rows(fib_map_rows_path)
    native_rows_by_symbol, _native_source_missing = load_native_short_context_rows(native_short_rows_path)
    fib_ext_by_symbol: dict[str, FibExtContext] = {}
    reentry_by_symbol: dict[str, ReentryContext] = {}
    activation_ts_by_symbol: dict[str, datetime | None] = {}
    input_status_by_symbol: dict[str, str] = {}
    coverage_status_by_symbol: dict[str, str] = {}
    display_state_by_symbol: dict[str, str] = {}

    for market in markets:
        symbol = market.split("-")[0].upper()
        manual_anchor = swing_anchors.get(symbol)
        if manual_anchor is not None:
            swing_low = _parse_decimal(manual_anchor[0] if len(manual_anchor) > 0 else None)
            swing_high = _parse_decimal(manual_anchor[1] if len(manual_anchor) > 1 else None)
            current_price = prices.get(market)
            recent_low_parts = recent_lows.get(symbol)
            recent_low = _parse_decimal(recent_low_parts[0]) if recent_low_parts else None
            if swing_low is not None and swing_high is not None and current_price is not None:
                fib_ext = _build_fib_ext_context(
                    symbol=symbol,
                    interval_code="4h",
                    swing_low=swing_low,
                    swing_high=swing_high,
                    current_price=current_price,
                    local_reaction_price=swing_high,
                    anchor_end_ts_utc=None,
                )
                reentry = _build_reentry_context(
                    symbol=symbol,
                    interval_code="4h",
                    swing_low=swing_low,
                    swing_high=swing_high,
                    current_price=current_price,
                    recent_low=recent_low,
                )
                if fib_ext is not None:
                    fib_ext_by_symbol[symbol] = fib_ext
                if reentry is not None:
                    reentry_by_symbol[symbol] = reentry
                activation_ts_by_symbol[symbol] = None
                input_status_by_symbol[symbol] = (
                    "MANUAL_ZONE_CONTEXT_USED"
                    if fib_ext is not None or reentry is not None
                    else "MISSING_ZONE_CONTEXT"
                )
                coverage_status_by_symbol[symbol] = "CONTEXT_INVALID_OR_STALE"
                display_state_by_symbol[symbol] = "NO_NATIVE_SHORT_FIB_CONTEXT"
            else:
                input_status_by_symbol[symbol] = "MISSING_ZONE_CONTEXT"
                coverage_status_by_symbol[symbol] = "CONTEXT_INVALID_OR_STALE"
                display_state_by_symbol[symbol] = "NO_NATIVE_SHORT_FIB_CONTEXT"
            continue

        native_row = native_rows_by_symbol.get(symbol)
        native_reference_only = native_row is not None and native_row.context_status != NATIVE_SHORT_CONTEXT_AVAILABLE
        if native_row is not None:
            input_status_by_symbol[symbol] = native_row.context_status
            coverage_status_by_symbol[symbol] = native_row.context_status
            display_state_by_symbol[symbol] = (
                "HAS_NATIVE_SHORT_FIB_CONTEXT"
                if native_row.context_status == NATIVE_SHORT_CONTEXT_AVAILABLE
                else "NO_NATIVE_SHORT_FIB_CONTEXT"
            )
            activation_ts_by_symbol[symbol] = native_row.anchor_end_ts_utc
            if native_row.context_status == NATIVE_SHORT_CONTEXT_AVAILABLE:
                swing_low = native_row.anchor_low_price
                swing_high = native_row.anchor_high_price
                current_price = prices.get(market) or native_row.latest_primary_close_price
                if swing_low is not None and swing_high is not None and current_price is not None:
                    fib_ext_by_symbol[symbol] = FibExtContext(
                        local_reaction_price=swing_high,
                        anchor_end_ts_utc=native_row.anchor_end_ts_utc,
                        ext_1_272=native_row.ext_1_272_price or swing_high,
                        ext_1_618=native_row.ext_1_618_price or swing_high,
                        ext_2_000=native_row.ext_2_000_price or swing_high,
                        breakout_gate=native_row.breakout_gate_price or swing_high,
                        price_band=_native_price_band(
                            current_price=current_price,
                            breakout_gate=native_row.breakout_gate_price or swing_high,
                            ext_1_272=native_row.ext_1_272_price or swing_high,
                            ext_1_618=native_row.ext_1_618_price or swing_high,
                            ext_2_000=native_row.ext_2_000_price or swing_high,
                        ),
                        ext_1_272_touched_and_rejected=False,
                        retesting_breakout_gate=native_row.supporting_1h_state == "RETESTING_BREAKOUT_GATE",
                    )
                    reentry_by_symbol[symbol] = ReentryContext(
                        r382_price=native_row.reload_r382_price or swing_high,
                        r500_price=native_row.reload_r500_price or swing_high,
                        r618_price=native_row.reload_r618_price or swing_high,
                        r786_price=native_row.reload_r786_price or swing_low,
                        deepest_touched_label=None,
                        missed_main_rebuy_by_pct=None,
                    )
                continue
            # Partial native row (not AVAILABLE): retain 4h map values as reference-only
            # and skip legacy path. Legacy must not overwrite partial native context.
            if (
                native_row.ext_1_272_price is not None
                and native_row.ext_1_618_price is not None
                and native_row.ext_2_000_price is not None
                and native_row.breakout_gate_price is not None
            ):
                _partial_price = prices.get(market) or native_row.latest_primary_close_price
                if _partial_price is not None:
                    fib_ext_by_symbol[symbol] = FibExtContext(
                        local_reaction_price=native_row.anchor_high_price or native_row.breakout_gate_price,
                        anchor_end_ts_utc=native_row.anchor_end_ts_utc,
                        ext_1_272=native_row.ext_1_272_price,
                        ext_1_618=native_row.ext_1_618_price,
                        ext_2_000=native_row.ext_2_000_price,
                        breakout_gate=native_row.breakout_gate_price,
                        price_band=_native_price_band(
                            current_price=_partial_price,
                            breakout_gate=native_row.breakout_gate_price,
                            ext_1_272=native_row.ext_1_272_price,
                            ext_1_618=native_row.ext_1_618_price,
                            ext_2_000=native_row.ext_2_000_price,
                        ),
                        ext_1_272_touched_and_rejected=False,
                        retesting_breakout_gate=False,
                    )
            continue

        if source_missing:
            input_status_by_symbol[symbol] = "ZONE_SOURCE_MISSING"
            coverage_status_by_symbol[symbol] = "FIB_MAP_SOURCE_MISSING"
            display_state_by_symbol[symbol] = "NO_NATIVE_SHORT_FIB_CONTEXT"
            continue

        fib_row = fib_rows_by_symbol.get(symbol)
        if fib_row is None:
            if not native_reference_only:
                input_status_by_symbol[symbol] = "ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING"
                coverage_status_by_symbol[symbol] = "FIB_MAP_SYMBOL_MISSING"
                display_state_by_symbol[symbol] = "NO_NATIVE_SHORT_FIB_CONTEXT"
            continue

        legacy_coverage_status, legacy_display_state = _short_context_gap_from_row(fib_row)
        if not native_reference_only:
            coverage_status_by_symbol[symbol] = legacy_coverage_status
            display_state_by_symbol[symbol] = legacy_display_state

        activation_ts_by_symbol[symbol] = _parse_iso_ts(fib_row.get("anchor_end_ts"))
        swing_low = _parse_decimal(fib_row.get("swing_low_price"))
        swing_high = _parse_decimal(fib_row.get("local_reaction_price")) or _parse_decimal(fib_row.get("swing_high_price"))
        current_price = prices.get(market) or _parse_decimal(fib_row.get("current_price"))
        if swing_low is None or swing_high is None or current_price is None:
            if not native_reference_only:
                input_status_by_symbol[symbol] = "MISSING_ZONE_CONTEXT"
            if not native_reference_only and coverage_status_by_symbol[symbol] == "LEGACY_1D_CONTEXT_ONLY":
                coverage_status_by_symbol[symbol] = "CONTEXT_INVALID_OR_STALE"
                display_state_by_symbol[symbol] = "CONTEXT_INVALID_OR_STALE"
            continue

        fib_ext = _build_fib_ext_context(
            symbol=symbol,
            interval_code="1d",
            swing_low=swing_low,
            swing_high=swing_high,
            current_price=current_price,
            local_reaction_price=_parse_decimal(fib_row.get("local_reaction_price")) or swing_high,
            anchor_end_ts_utc=activation_ts_by_symbol[symbol],
        )
        reentry = _build_reentry_context(
            symbol=symbol,
            interval_code="1d",
            swing_low=swing_low,
            swing_high=swing_high,
            current_price=current_price,
            recent_low=None,
        )
        if fib_ext is not None:
            fib_ext_by_symbol[symbol] = fib_ext
        if reentry is not None:
            reentry_by_symbol[symbol] = reentry
        if not native_reference_only:
            input_status_by_symbol[symbol] = (
                "HAS_ZONE_CONTEXT"
                if fib_ext is not None or reentry is not None
                else "MISSING_ZONE_CONTEXT"
            )
        if (
            not native_reference_only
            and fib_ext is None
            and reentry is None
            and coverage_status_by_symbol[symbol] == "LEGACY_1D_CONTEXT_ONLY"
        ):
            coverage_status_by_symbol[symbol] = "CONTEXT_INVALID_OR_STALE"
            display_state_by_symbol[symbol] = "CONTEXT_INVALID_OR_STALE"

    return ZoneContextLoadResult(
        fib_ext_by_symbol=fib_ext_by_symbol,
        reentry_by_symbol=reentry_by_symbol,
        activation_ts_by_symbol=activation_ts_by_symbol,
        input_status_by_symbol=input_status_by_symbol,
        coverage_status_by_symbol=coverage_status_by_symbol,
        display_state_by_symbol=display_state_by_symbol,
        source_name="fibo_target_map_rows_v1.csv",
        source_missing=source_missing,
    )


def fetch_market_target_history_by_symbol(
    *,
    venue: str,
    activation_ts_by_symbol: dict[str, datetime | None],
    interval_code: str = TARGET_HISTORY_INTERVAL,
) -> dict[str, MarketTargetHistory]:
    symbols = sorted(symbol for symbol, activation_ts in activation_ts_by_symbol.items() if activation_ts is not None)
    if not symbols:
        return {}
    conn = get_connection()
    try:
        earliest_activation = min(activation_ts_by_symbol[symbol] for symbol in symbols if activation_ts_by_symbol[symbol] is not None)
        out: dict[str, MarketTargetHistory] = {}
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(symbols))
            cur.execute(
                f"""
                SELECT
                    a.symbol,
                    c.close_ts_utc,
                    c.high_price,
                    c.low_price
                FROM obs_market_candle c
                JOIN asset a
                  ON a.asset_id = c.asset_id
                WHERE c.venue = %s
                  AND c.interval_code = %s
                  AND a.symbol IN ({placeholders})
                  AND c.close_ts_utc >= %s
                ORDER BY a.symbol ASC, c.close_ts_utc ASC
                """,
                (venue, interval_code, *symbols, earliest_activation),
            )
            rows = list(cur.fetchall())
        grouped_rows: dict[str, list[TargetHistoryCandle]] = {symbol: [] for symbol in symbols}
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            close_ts = row.get("close_ts_utc")
            activation_ts = activation_ts_by_symbol.get(symbol)
            if not symbol or activation_ts is None or close_ts is None:
                continue
            close_ts_utc = close_ts.replace(tzinfo=UTC) if close_ts.tzinfo is None else close_ts.astimezone(UTC)
            if close_ts_utc < activation_ts:
                continue
            high_price = _parse_decimal(row.get("high_price"))
            low_price = _parse_decimal(row.get("low_price"))
            if high_price is None or low_price is None:
                continue
            grouped_rows[symbol].append(
                TargetHistoryCandle(
                    close_ts_utc=close_ts_utc,
                    high_price=high_price,
                    low_price=low_price,
                )
            )
        for symbol in symbols:
            candles = tuple(grouped_rows.get(symbol, []))
            highs = [candle.high_price for candle in candles]
            lows = [candle.low_price for candle in candles]
            out[symbol] = MarketTargetHistory(
                high_since_activation=max(highs) if highs else None,
                low_since_activation=min(lows) if lows else None,
                candles_since_activation=candles,
            )
        return out
    finally:
        conn.close()


def build_cards(
    markets: list[str],
    prices: dict[str, Decimal],
    price_status_by_market: dict[str, str],
    price_age_min_by_market: dict[str, Decimal | None],
    input_status_by_symbol: dict[str, str],
    coverage_status_by_symbol: dict[str, str],
    display_state_by_symbol: dict[str, str],
    fib_ext_by_symbol: dict[str, FibExtContext],
    reentry_by_symbol: dict[str, ReentryContext],
    history_by_symbol: dict[str, MarketTargetHistory],
    orders_by_symbol: dict[str, tuple[tuple[LadderOrderRow, ...], tuple[LadderOrderRow, ...]]],
) -> list[ProfitPlanCard]:
    cards: list[ProfitPlanCard] = []
    for market in markets:
        symbol = market.split("-")[0].upper()
        current = prices.get(market)
        buy_orders, sell_orders = orders_by_symbol.get(symbol, ((), ()))
        history = history_by_symbol.get(symbol)
        cards.append(
            build_profit_plan_card(
                symbol=symbol,
                market=market,
                current_price=current,
                fib_trading_horizon="SHORT",
                short_context_input_status=input_status_by_symbol.get(symbol, "MISSING_ZONE_CONTEXT"),
                short_context_coverage_status=coverage_status_by_symbol.get(symbol, "CONTEXT_INVALID_OR_STALE"),
                short_context_display_state=display_state_by_symbol.get(symbol, "NO_NATIVE_SHORT_FIB_CONTEXT"),
                current_price_status=price_status_by_market.get(market),
                current_price_age_min=price_age_min_by_market.get(market),
                fib_ext=fib_ext_by_symbol.get(symbol),
                reentry=reentry_by_symbol.get(symbol),
                buy_orders=buy_orders,
                sell_orders=sell_orders,
                history_high_since_activation=None if history is None else history.high_since_activation,
                history_low_since_activation=None if history is None else history.low_since_activation,
                history_candles_since_activation=() if history is None else history.candles_since_activation,
            )
        )
    return cards


def print_summary(*, context, cards: list[ProfitPlanCard], output_html: Path, output_json: Path) -> None:
    print(f"report={REPORT_NAME}")
    print(f"version={REPORT_VERSION}")
    print(f"profile={context.profile}")
    print(f"account_code={context.account_code}")
    print(f"trading_account_id={context.trading_account_id}")
    print(f"venue={context.venue}")
    print(f"market_count={len(context.markets)}")
    print(f"open_order_count={len(context.orders)}")
    print(f"html_output={output_html}")
    print(f"json_output={output_json}")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("decision_gate=none")
    print("execution_planner=none")
    print("executor=none")
    coverage_summary = summarize_short_context_coverage(
        markets=list(context.markets),
        coverage_status_by_symbol={card.symbol: card.short_context_coverage_status for card in cards},
    )
    print("short_context_bridge=native_short_context_v1+legacy_1d_reference_fallback")
    print(
        "short_context_coverage="
        + " ; ".join(f"{key}:{coverage_summary.get(key, 0)}" for key in (
            "NATIVE_SHORT_CONTEXT_AVAILABLE",
            "INSUFFICIENT_4H_HISTORY",
            "INSUFFICIENT_1H_HISTORY",
            "LEGACY_1D_CONTEXT_ONLY",
            "FIB_MAP_SYMBOL_MISSING",
            "FIB_MAP_SOURCE_MISSING",
            "MARKET_DATA_MISSING",
            "CONTEXT_INVALID_OR_STALE",
        ))
    )
    relevant = [card for card in cards if card.is_relevant]
    print(f"relevant={len(relevant)}/{len(cards)}")
    for card in cards:
        rel_flag = "RELEVANT" if card.is_relevant else "filtered"
        print(
            f"{card.symbol}: scenario={card.scenario_type}"
            f" action={card.action_label}"
            f" primary_state={card.primary_state}"
            f" short_context={card.short_context_coverage_status}"
            f" [{rel_flag}]"
        )


def main() -> int:
    writer_instance_id = str(uuid.uuid4())
    snapshot_render_id = str(uuid.uuid4())
    args = parse_args()
    try:
        validate_profile_slug(args.account_profile)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    try:
        access = resolve_dashboard_profile_access(
            account_profile=args.account_profile,
            venue=args.venue,
        )
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    output_root = Path(args.output_root)
    default_html, default_json = default_page_paths(
        output_root=output_root,
        profile=args.account_profile,
        page_stem="profit-plan",
    )
    output_html = Path(args.output_html) if args.output_html else default_html
    output_json = Path(args.output_json) if args.output_json else default_json

    try:
        context = load_account_scoped_short_dashboard_context(
            profile=args.account_profile,
            account_code=access.trading_account_stable_ref,
            venue=args.venue,
        )
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[error] account scope load failed: {exc}", file=sys.stderr)
        return 1

    price_display_by_market = classify_market_prices_by_market(context=context)
    prices = {
        market: display.safe_price
        for market, display in price_display_by_market.items()
        if display.safe_price is not None
    }
    sections = build_all_sections(
        list(context.orders),
        list(context.balances),
        prices,
        price_status_by_market={market: display.status for market, display in price_display_by_market.items()},
        price_age_min_by_market={market: display.age_min for market, display in price_display_by_market.items()},
    )
    orders_by_symbol: dict[str, tuple[tuple[LadderOrderRow, ...], tuple[LadderOrderRow, ...]]] = {
        section.symbol: (section.buy_orders, section.sell_orders)
        for section in sections
    }

    zone_contexts = load_zone_contexts(
        markets=list(context.markets),
        prices=prices,
        swing_anchors=_parse_kv_list(args.swing_anchors, 3),
        recent_lows=_parse_kv_list(args.recent_lows, 2),
        native_short_rows_path=Path(args.native_short_context_rows),
        fib_map_rows_path=Path(args.fib_map_rows),
    )
    history_by_symbol = fetch_market_target_history_by_symbol(
        venue=args.venue,
        activation_ts_by_symbol=zone_contexts.activation_ts_by_symbol,
    )
    monitor_link = args.monitor_href or public_page_href(
        profile=args.account_profile,
        page_stem="open-orders-monitor",
    )
    cards = build_cards(
        list(context.markets),
        prices,
        {market: display.status for market, display in price_display_by_market.items()},
        {market: display.age_min for market, display in price_display_by_market.items()},
        zone_contexts.input_status_by_symbol,
        zone_contexts.coverage_status_by_symbol,
        zone_contexts.display_state_by_symbol,
        zone_contexts.fib_ext_by_symbol,
        zone_contexts.reentry_by_symbol,
        history_by_symbol,
        orders_by_symbol,
    )

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    html_content = render_full_html(
        cards,
        broker_mode="db_snapshot",
        monitor_link=monitor_link,
        nav_html=cockpit_nav(account_profile=args.account_profile).strip(),
        storage_scope=args.account_profile,
        render_id=snapshot_render_id,
        writer_instance_id=writer_instance_id,
    )
    json_content = json.dumps(
        build_json_snapshot(
            cards,
            broker_mode="db_snapshot",
            writer_instance_id=writer_instance_id,
            render_id=snapshot_render_id,
        ),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )

    # Atomic publication: write to temp then os.replace to avoid partial reads.
    html_dir = str(output_html.parent)
    json_dir = str(output_json.parent)
    with tempfile.NamedTemporaryFile("w", dir=html_dir, suffix=".tmp", delete=False, encoding="utf-8") as tf:
        tf.write(html_content)
        tmp_html = tf.name
    os.replace(tmp_html, output_html)

    with tempfile.NamedTemporaryFile("w", dir=json_dir, suffix=".tmp", delete=False, encoding="utf-8") as tf:
        tf.write(json_content)
        tmp_json = tf.name
    os.replace(tmp_json, output_json)

    if args.output == "summary":
        print_summary(
            context=context,
            cards=cards,
            output_html=output_html,
            output_json=output_json,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
