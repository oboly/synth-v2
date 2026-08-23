from __future__ import annotations

import argparse
import csv
import dataclasses
import html
import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from src.common.db import get_connection
from src.market_context.breath_curve_live_v1 import (
    BTC_SYMBOL,
    BreathCurveLiveCandle,
    build_breath_curve_live_by_symbol,
)
from src.market_context.market_context_builder_v1 import (
    MarketContextCandle,
    build_market_context_by_symbol,
)
from src.market_data.native_short_fib_context_v1 import (
    DEFAULT_ROWS_CSV as DEFAULT_NATIVE_SHORT_ROWS,
    FRESHNESS_FRESH as NATIVE_SHORT_CONTEXT_FRESH,
    STATUS_AVAILABLE as NATIVE_SHORT_CONTEXT_AVAILABLE,
    load_native_short_context_rows,
)
from src.market_data.canonical_fib_zone_map_v1 import (
    AVAILABLE_STATES as CANONICAL_FIB_MAP_AVAILABLE_STATES,
    DEFAULT_STALE_AFTER as CANONICAL_FIB_MAP_STALE_AFTER,
    fetch_latest_production_rows as fetch_canonical_fib_map_rows,
)
from src.reporting.account_scoped_short_trader_dashboard_v1 import (
    AccountPlanPolicy,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_VENUE,
    classify_market_prices_by_market,
    default_page_paths,
    load_account_scoped_short_dashboard_context,
    public_page_href,
    validate_profile_slug,
)
from src.reporting.account_dashboard_profile_access_v1 import resolve_dashboard_profile_access
from src.reporting.account_wallet_dashboard_v1 import classify_wallet_freshness
from src.reporting.dashboard_style_v1 import cockpit_nav
from src.reporting.manual_short_trader_dashboard_v1 import (
    BrokerOrderRow,
    LadderOrderRow,
    build_all_sections,
)
from src.market_rules.price_tick_normalization_v1 import (
    load_tick_rules_from_db,
    resolve_tick_rule,
)
from src.market_data.fib_navigation_map_v1 import (
    DIRECTION_BULLISH,
    MAP_STATE_EXHAUSTED,
    MAP_STATE_NO_DATA,
    MAP_STATE_STALE,
    FibNavCandle,
    FibNavigationMap,
    PriorMapMeta,
    build_fib_navigation_map,
    build_fib_navigation_map_from_anchor,
)
from src.reporting.manual_short_trader_profit_plan_v1 import (
    CARD_MODE_ACCOUNT_ORDER_ONLY,
    CARD_MODE_ACCOUNT_PLAN_ENABLED,
    CARD_MODE_MARKET_SELECTED,
    CARD_MODE_POSITION_HELD,
    CARD_MODE_WATCH_ONLY_ROTATION,
    VISIBILITY_NATIVE_ATTENTION,
    VISIBILITY_CANONICAL_NAVIGATION_REFERENCE,
    VISIBILITY_CONTEXT_UNAVAILABLE,
    PLANNING_SOURCE_CANONICAL_4H_NAVIGATION,
    PLANNING_SOURCE_LEGACY_REFERENCE,
    PLANNING_SOURCE_MANUAL_REFERENCE,
    PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
    PLANNING_SOURCE_NATIVE_SHORT_TRANSIENT_REFERENCE,
    CardEvidence,
    FibExtContext,
    FibNavContext,
    PlanningProvenance,
    ProfitPlanCard,
    ReentryContext,
    TargetHistoryCandle,
    apply_card_deltas,
    apply_fib_coverage_classification,
    apply_portfolio_account_evidence,
    apply_price_tick_normalization,
    build_json_snapshot,
    build_profit_plan_card,
    make_planning_provenance,
    render_full_html,
)
from src.reporting.market_rotation_pressure_dashboard_v1 import (
    MODEL_VERSION as ROTATION_MODEL_VERSION,
)
from src.reporting.market_rotation_profit_plan_projection_v1 import (
    build_rotation_projection,
)
from src.reporting.run_market_rotation_pressure_dashboard_v1 import (
    check_schema_ready as check_rotation_schema_ready,
    fetch_pressure_history as fetch_rotation_pressure_history,
    fetch_latest_snapshot as fetch_latest_rotation_snapshot,
    fetch_snapshot_observations as fetch_rotation_snapshot_observations,
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
_MARKET_CONTEXT_INTERVAL = "4h"
_MARKET_CONTEXT_LOOKBACK_DAYS = 90
_BREATH_CURVE_INTERVAL = "1d"
_BREATH_CURVE_LOOKBACK_DAYS = 140
_DEFAULT_NATIVE_SHORT_CONTEXT_UNION_RELATIVE = Path(
    "_runtime/native_short_context_union_v1/native_short_fib_context_rows_v1.csv"
)


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
    native_source_missing: bool = False
    prior_map_meta_by_symbol: dict[str, PriorMapMeta] = field(default_factory=dict)
    evidence_by_symbol: dict[str, CardEvidence] = field(default_factory=dict)
    planning_provenance_by_symbol: dict[str, PlanningProvenance] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketTargetHistory:
    high_since_activation: Decimal | None
    low_since_activation: Decimal | None
    candles_since_activation: tuple[TargetHistoryCandle, ...]


_OUTPUT_MODE = 0o644


def atomic_text_write(content: str, dest: Path) -> None:
    """
    Write content to dest atomically with mode 0644.

    Steps: write to same-directory temp → flush → fsync → fchmod 0644 →
    os.replace (atomic rename) → fsync parent directory.

    NamedTemporaryFile defaults to mode 0600; fchmod before replace ensures
    the final file is always readable by the web server (www-data).
    Cleans up the temp file on any exception before replace.
    """
    dest_dir = str(dest.parent)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=dest_dir, suffix=".tmp", delete=False, encoding="utf-8"
        ) as tf:
            tmp_path = tf.name
            tf.write(content)
            tf.flush()
            os.fsync(tf.fileno())
            os.fchmod(tf.fileno(), _OUTPUT_MODE)
        os.replace(tmp_path, dest)
        tmp_path = None  # replace succeeded; nothing to clean up
        # Fsync the directory so the rename is durable.
        dir_fd = os.open(dest_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def portfolio_member_markets_for_rendered_account(
    *,
    account_asset_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    trading_account_id: int,
) -> set[str]:
    """Return portfolio-member markets for exactly one rendered account."""
    return {
        str(row.get("market") or "").upper()
        for row in account_asset_rows
        if int(row.get("trading_account_id") or 0) == trading_account_id
        and bool(row.get("is_portfolio_member"))
    }


def held_amount_and_value_by_symbol(
    *,
    balances: list[Any],
    prices: dict[str, Decimal],
    quote_currency: str = "EUR",
) -> tuple[dict[str, Decimal], dict[str, Decimal | None]]:
    """Held amount and EUR value per symbol from the account balance snapshot.

    Held amount = available + in_order (total on-account quantity). EUR value
    is None (never fabricated) when no current price snapshot exists for the
    market — the caller renders that as DATA_UNAVAILABLE, not zero.
    """
    amount_by_symbol: dict[str, Decimal] = {}
    eur_value_by_symbol: dict[str, Decimal | None] = {}
    for row in balances:
        symbol = str(getattr(row, "symbol", "") or "").upper()
        if not symbol or symbol == quote_currency:
            continue
        total = (getattr(row, "available", None) or Decimal("0")) + (getattr(row, "in_order", None) or Decimal("0"))
        if total <= 0:
            continue
        amount_by_symbol[symbol] = total
        price = prices.get(f"{symbol}-{quote_currency}")
        eur_value_by_symbol[symbol] = (total * price) if price is not None else None
    return amount_by_symbol, eur_value_by_symbol


def fetch_latest_cost_basis_by_symbol(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
) -> dict[str, Decimal]:
    """Read-only latest average_entry_price_eur per symbol from
    account_position_snapshot. Symbols absent from the returned dict have no
    persisted cost basis (currently unpopulated by the position snapshot
    writer) — callers must render DATA_UNAVAILABLE, never fabricate zero."""
    sql = """
    WITH latest_position AS (
        SELECT trading_account_id, MAX(snapshot_ts_utc) AS snapshot_ts_utc
        FROM account_position_snapshot
        WHERE trading_account_id = %s AND venue = %s
        GROUP BY trading_account_id
    )
    SELECT p.symbol, p.average_entry_price_eur
    FROM account_position_snapshot p
    JOIN latest_position lp
      ON lp.trading_account_id = p.trading_account_id
     AND lp.snapshot_ts_utc = p.snapshot_ts_utc
    WHERE p.venue = %s
      AND p.trading_account_id = %s
      AND p.average_entry_price_eur IS NOT NULL
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (trading_account_id, venue, venue, trading_account_id))
            rows = list(cur.fetchall())
    except Exception:
        return {}
    out: dict[str, Decimal] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        value = _parse_decimal(row.get("average_entry_price_eur"))
        if symbol and value is not None:
            out[symbol] = value
    return out


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
        "--quote-currency",
        default="EUR",
        help="Quote currency used to read canonical_fib_zone_map_latest_v1 (read-only).",
    )
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
        default=None,
        help="Canonical native SHORT context rows path. Native 4h+1h rows are preferred when available.",
    )
    parser.add_argument(
        "--native-short-snapshot-status",
        choices=("loaded", "missing", "invalid", "unverified"),
        default="unverified",
        help="Manifest-validation status supplied by the persisted-snapshot render owner.",
    )
    parser.add_argument(
        "--native-short-snapshot-id",
        default=None,
        help="Validated canonical native SHORT snapshot identity supplied by the render owner.",
    )
    parser.add_argument(
        "--previous-json",
        default=None,
        metavar="PATH",
        help="Optional explicit previous canonical Profit Plan JSON snapshot for deterministic card deltas.",
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


def _fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "DATA_UNAVAILABLE"
    value_utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value_utc.isoformat().replace("+00:00", "Z")


def _fmt_dec(value: Decimal | None) -> str:
    return "DATA_UNAVAILABLE" if value is None else format(value, "f")


def _fmt_unavailable(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "DATA_UNAVAILABLE"


def _map_age_min(*, anchor_end_ts_utc: datetime | None, now_utc: datetime) -> str:
    if anchor_end_ts_utc is None:
        return "DATA_UNAVAILABLE"
    anchor = anchor_end_ts_utc.replace(tzinfo=UTC) if anchor_end_ts_utc.tzinfo is None else anchor_end_ts_utc.astimezone(UTC)
    minutes = (now_utc - anchor).total_seconds() / 60
    return f"{max(minutes, 0):.1f}"


def _latest_ts(*values: datetime | None) -> datetime | None:
    present = [
        value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value.astimezone(UTC)
        for value in values
        if value is not None
    ]
    return max(present) if present else None


def _native_row_is_canonical(native_row: Any, *, snapshot_verified: bool) -> bool:
    """True only when the row's own contract state AND the transport-layer
    snapshot validation both agree the context is canonical native SHORT truth.

    ``snapshot_verified`` reflects the render owner's validate_published_snapshot()
    result (--native-short-snapshot-status loaded), i.e. schema/digest/identity
    validation of the canonical snapshot root. The row's own context_status and
    context_freshness_status are the existing native SHORT contract fields.
    Both signals must hold or the row stays non-canonical/transient.
    """
    return (
        snapshot_verified
        and native_row.context_status == NATIVE_SHORT_CONTEXT_AVAILABLE
        and native_row.context_freshness_status == NATIVE_SHORT_CONTEXT_FRESH
    )


def _evidence_from_native_row(
    native_row: Any,
    *,
    now_utc: datetime,
    snapshot_verified: bool = False,
    snapshot_id: str | None = None,
) -> CardEvidence:
    latest_context_ts = _latest_ts(
        native_row.latest_primary_close_ts_utc,
        native_row.latest_support_close_ts_utc,
    )
    is_canonical = _native_row_is_canonical(native_row, snapshot_verified=snapshot_verified)
    if is_canonical:
        # Backed by a validated canonical snapshot root (schema/digest/identity
        # confirmed) plus a passing per-row native SHORT contract: map identity
        # and cycle id are canonical, not bridge reference-only metadata.
        native_map_id = _fmt_unavailable(f"{snapshot_id}:{native_row.symbol}:{native_row.map_cycle_id}")
        native_map_status = "AVAILABLE"
        selected_map_reason = _fmt_unavailable(native_row.selection_reason)
        selected_map_tier = _fmt_unavailable(native_row.current_map_status)
    else:
        # Native scope-status projection is not proven canonical (snapshot not
        # verified loaded, row not AVAILABLE, or row not FRESH); stays
        # DATA_UNAVAILABLE so account-specific repair actions fail closed.
        native_map_id = "DATA_UNAVAILABLE"
        native_map_status = "DATA_UNAVAILABLE"
        selected_map_reason = f"TRANSIENT_NON_CANONICAL_REFERENCE: {_fmt_unavailable(native_row.selection_reason)}"
        selected_map_tier = "TRANSIENT_NON_CANONICAL_REFERENCE"
    return CardEvidence(
        map_cycle_id=_fmt_unavailable(native_row.map_cycle_id),
        native_map_id=native_map_id,
        native_map_status=native_map_status,
        selected_map_reason=selected_map_reason,
        selected_map_tier=selected_map_tier,
        lifecycle_state="DATA_UNAVAILABLE",
        rollover_state="DATA_UNAVAILABLE",
        previous_map_cycle_id="DATA_UNAVAILABLE",
        previous_map_lifecycle_state="DATA_UNAVAILABLE",
        # Account/order snapshot freshness (Lane A) is not yet plumbed; kept
        # DATA_UNAVAILABLE so placeholder account panels cannot enable FIX LADDER.
        account_order_snapshot_status="DATA_UNAVAILABLE",
        # Per-authority wallet/position evidence (Lane A) is not yet plumbed either;
        # kept independently DATA_UNAVAILABLE for the P1 evidence-card normalization.
        wallet_snapshot_status="DATA_UNAVAILABLE",
        position_snapshot_status="DATA_UNAVAILABLE",
        map_age_min=_map_age_min(anchor_end_ts_utc=native_row.anchor_end_ts_utc, now_utc=now_utc),
        anchor_start_ts_utc=_fmt_ts(native_row.anchor_start_ts_utc),
        anchor_end_ts_utc=_fmt_ts(native_row.anchor_end_ts_utc),
        anchor_low_price=_fmt_dec(native_row.anchor_low_price),
        anchor_high_price=_fmt_dec(native_row.anchor_high_price),
        context_ts_utc=_fmt_ts(latest_context_ts),
        update_ts_utc=_fmt_ts(latest_context_ts),
        # Truthful passthrough of the row's own canonical
        # native_short_fib_context_v1 field; not re-derived or inferred here.
        native_context_freshness_status=_fmt_unavailable(native_row.context_freshness_status),
    )


def _load_previous_json_snapshot(path_text: str | None) -> dict[str, Any] | None:
    if not path_text:
        return None
    path = Path(path_text)
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("--previous-json must contain a JSON object")
    return payload


def _resolve_native_short_context_rows_path(
    *,
    output_root: Path,
    native_short_context_rows_arg: str | None,
) -> Path:
    if native_short_context_rows_arg:
        return Path(native_short_context_rows_arg)
    union_path = output_root / _DEFAULT_NATIVE_SHORT_CONTEXT_UNION_RELATIVE
    if union_path.exists():
        return union_path
    return Path(DEFAULT_NATIVE_SHORT_ROWS)


def _symbols_from_markets(markets: list[str]) -> list[str]:
    return sorted({market.split("-")[0].upper() for market in markets if market})


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


def _canonical_row_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return _parse_iso_ts(value)


CANONICAL_4H_CONTEXT_AVAILABLE = "CANONICAL_4H_CONTEXT_AVAILABLE"


def _canonical_fib_row_status(
    row: dict[str, Any] | None,
    *,
    now_utc: datetime,
    stale_after: timedelta,
) -> str:
    """Classify a canonical_fib_zone_map_latest_v1 row: ABSENT | AVAILABLE | STALE | UNAVAILABLE.

    ABSENT means no row was published for this symbol -- callers may fall back
    to the legacy 1d source. AVAILABLE/STALE/UNAVAILABLE are explicit terminal
    classifications for a row that does exist; they must never be reported as
    FIB_MAP_SYMBOL_MISSING.
    """
    if row is None:
        return "ABSENT"
    map_status = str(row.get("map_status") or "").strip().upper()
    if map_status not in CANONICAL_FIB_MAP_AVAILABLE_STATES:
        return "UNAVAILABLE"
    asof_ts = _canonical_row_ts(row.get("asof_ts_utc"))
    if asof_ts is None:
        return "UNAVAILABLE"
    if now_utc - asof_ts > stale_after:
        return "STALE"
    return "AVAILABLE"


def _build_zone_context_from_canonical_row(
    row: dict[str, Any],
    *,
    current_price: Decimal | None,
) -> tuple[FibExtContext, ReentryContext] | None:
    """Map a canonical_fib_zone_map_latest_v1 row onto FibExtContext/ReentryContext.

    Retracement levels r382/r618/r786 are not stored as individual columns;
    they are reconstructed from entry_zone_low/high and
    support_reaction_zone_low/high using current_leg (UP/DOWN), the same
    min/max convention the canonical writer used to build those bounds.
    """
    current_leg = str(row.get("current_leg") or "").strip().upper()
    if current_leg not in {"UP", "DOWN"}:
        return None
    try:
        anchor_low = _parse_decimal(row.get("anchor_low_price"))
        anchor_high = _parse_decimal(row.get("anchor_high_price"))
        target_t1 = _parse_decimal(row.get("target_t1"))
        target_t2 = _parse_decimal(row.get("target_t2"))
        target_extension = _parse_decimal(row.get("target_extension"))
        entry_zone_low = _parse_decimal(row.get("entry_zone_low"))
        entry_zone_high = _parse_decimal(row.get("entry_zone_high"))
        entry_zone_mid = _parse_decimal(row.get("entry_zone_mid"))
        support_low = _parse_decimal(row.get("support_reaction_zone_low"))
        support_high = _parse_decimal(row.get("support_reaction_zone_high"))
        reference_price = _parse_decimal(row.get("reference_price"))
    except Exception:
        return None
    required = (
        anchor_low, anchor_high, target_t1, target_t2, target_extension,
        entry_zone_low, entry_zone_high, entry_zone_mid, support_low, support_high,
    )
    if any(value is None for value in required):
        return None
    price = current_price if current_price is not None else (reference_price or anchor_high)
    if price is None:
        return None
    if current_leg == "UP":
        breakout_gate = anchor_high
        r382, r618, r786 = entry_zone_high, entry_zone_low, support_low
    else:
        breakout_gate = anchor_low
        r382, r618, r786 = entry_zone_low, entry_zone_high, support_high
    fib_ext = FibExtContext(
        local_reaction_price=breakout_gate,
        anchor_end_ts_utc=_canonical_row_ts(row.get("asof_ts_utc")),
        ext_1_272=target_t1,
        ext_1_618=target_t2,
        ext_2_000=target_extension,
        breakout_gate=breakout_gate,
        price_band=_native_price_band(
            current_price=price,
            breakout_gate=breakout_gate,
            ext_1_272=target_t1,
            ext_1_618=target_t2,
            ext_2_000=target_extension,
        ),
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=False,
    )
    reentry = ReentryContext(
        r382_price=r382,
        r500_price=entry_zone_mid,
        r618_price=r618,
        r786_price=r786,
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )
    return fib_ext, reentry


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
        CANONICAL_4H_CONTEXT_AVAILABLE: 0,
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


def load_native_short_scope_state_by_symbol(rows_path: Path) -> dict[str, str]:
    """Read-only per-symbol native SHORT scope_support_state (Issue #489).

    Same source file as ``load_native_short_context_rows`` -- the row
    provenance columns carry ``scope_support_state`` (SUPPORTED /
    NOT_APPLICABLE, per
    ``src.market_data.native_short_scope_status_v1.NativeShortScopeSupportEventState``)
    independent of whether the row's lifecycle ``context_status`` is
    AVAILABLE. A symbol absent from the file classifies as UNKNOWN, never
    fabricated as SUPPORTED or NOT_APPLICABLE.
    """
    scope_state_by_symbol: dict[str, str] = {}
    if not rows_path.is_file():
        return scope_state_by_symbol
    try:
        with rows_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol") or "").strip().upper()
                state = str(row.get("scope_support_state") or "").strip().upper()
                if symbol and state in {"SUPPORTED", "NOT_APPLICABLE"}:
                    scope_state_by_symbol[symbol] = state
    except (OSError, UnicodeError, csv.Error):
        return {}
    return scope_state_by_symbol


def summarize_native_short_snapshot_evidence(
    *,
    markets: list[str],
    rows_path: Path,
    canonical_status: str,
    snapshot_id: str | None,
    canonical_supported_symbols: "frozenset[str] | set[str] | None" = None,
) -> dict[str, Any]:
    market_symbols = sorted({market.split("-", 1)[0].upper() for market in markets})
    status = canonical_status
    rows_by_symbol: dict[str, dict[str, str]] = {}
    if not rows_path.is_file():
        status = "missing" if status != "invalid" else status
    else:
        try:
            with rows_path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    symbol = str(row.get("symbol") or "").strip().upper()
                    if symbol:
                        rows_by_symbol[symbol] = {str(key): str(value or "") for key, value in row.items()}
        except (OSError, UnicodeError, csv.Error):
            status = "invalid"
            rows_by_symbol = {}

    supported_symbols = [
        symbol
        for symbol in market_symbols
        if rows_by_symbol.get(symbol, {}).get("scope_support_state", "").upper() == "SUPPORTED"
    ]
    available_symbols = [
        symbol
        for symbol in market_symbols
        if rows_by_symbol.get(symbol, {}).get("context_status", "").upper()
        == NATIVE_SHORT_CONTEXT_AVAILABLE
    ]
    stale_supported_symbols = [
        symbol
        for symbol in supported_symbols
        if rows_by_symbol[symbol].get("context_freshness_status", "").upper() == "STALE"
    ]
    # Issue #223: a symbol covered by the read-only canonical 4h navigation bridge
    # (CANONICAL_MARKET_CONTEXT) is a distinct, explicitly non-native coverage class.
    # It must never be reported as native-unsupported/unavailable alongside symbols
    # with no context of any kind.
    canonical_symbols = sorted(set(canonical_supported_symbols or ()) & set(market_symbols))
    unavailable_symbols = [
        symbol
        for symbol in market_symbols
        if (symbol not in supported_symbols or symbol not in available_symbols)
        and symbol not in canonical_symbols
    ]
    return {
        "canonical_snapshot_status": status,
        "native_short_snapshot_id": snapshot_id if status == "loaded" else None,
        "native_context_available_count": len(available_symbols),
        "native_context_supported_count": len(supported_symbols),
        "native_context_total_count": len(market_symbols),
        "supported_context_stale_count": len(stale_supported_symbols),
        "supported_context_stale_markets": stale_supported_symbols,
        "unsupported_or_unavailable_count": len(unavailable_symbols),
        "unsupported_or_unavailable_markets": unavailable_symbols,
        "canonical_navigation_supported_count": len(canonical_symbols),
        "canonical_navigation_supported_markets": canonical_symbols,
    }


def native_short_snapshot_banner(evidence: Mapping[str, Any]) -> str:
    status = str(evidence["canonical_snapshot_status"])
    if status in {"missing", "invalid"}:
        return (
            "<div class='pipeline-warn'>Canonical native SHORT snapshot missing or invalid. "
            "Persisted native context was not loaded; no candle-pipeline cause is inferred.</div>"
        )
    if status == "unverified":
        return (
            "<div class='pipeline-warn'>Native SHORT rows were not verified through the canonical manifest. "
            "Snapshot authority status is unavailable.</div>"
        )

    available = int(evidence["native_context_available_count"])
    supported = int(evidence["native_context_supported_count"])
    total = int(evidence["native_context_total_count"])
    stale = int(evidence["supported_context_stale_count"])
    unavailable = list(evidence["unsupported_or_unavailable_markets"])
    canonical_count = int(evidence.get("canonical_navigation_supported_count", 0))
    details = [
        "Canonical native SHORT snapshot loaded.",
        f"Available {available} / supported {supported} / total {total} native lifecycle contexts.",
        f"Canonical 4h navigation coverage: {canonical_count} contexts (read-only, non-native).",
    ]
    if stale:
        details.append(f"Supported context stale: {stale}.")
    if unavailable:
        details.append(
            "Unsupported/unavailable markets: "
            + ", ".join(html.escape(symbol) for symbol in unavailable)
            + "."
        )
    return "<div class='pipeline-warn'>" + " ".join(details) + "</div>"


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


def _build_prior_map_meta_from_native_row(
    native_row: "Any",
    now_utc: datetime,
) -> PriorMapMeta | None:
    """Extract anchor data from a MAP_COMPLETED native row into PriorMapMeta."""
    anchor_low = native_row.anchor_low_price
    anchor_high = native_row.anchor_high_price
    if anchor_low is None or anchor_high is None or anchor_high <= anchor_low or anchor_low <= 0:
        return None
    ext_candidates = [
        p for p in (
            native_row.ext_1_272_price,
            native_row.ext_1_618_price,
            native_row.ext_2_000_price,
        )
        if p is not None
    ]
    top_ext = max(ext_candidates) if ext_candidates else anchor_low + (anchor_high - anchor_low) * Decimal("2")
    candle_ts = native_row.anchor_end_ts_utc or now_utc
    return PriorMapMeta(
        map_state=MAP_STATE_EXHAUSTED,
        anchor_low=anchor_low,
        anchor_high=anchor_high,
        direction=DIRECTION_BULLISH,
        top_extension_price=top_ext,
        candle_ts_utc=candle_ts,
    )


def _candles_to_fib_nav(candles: tuple) -> list[FibNavCandle]:
    """Convert TargetHistoryCandle → FibNavCandle. Synthesize open/close as (high+low)/2; volume=0.

    TargetHistoryCandle only carries high_price and low_price (no open/close/volume).
    The midpoint approximation is sufficient for pivot detection; volume-based triggers
    are disabled because volume=0 never passes the expansion ratio check.
    Runner currently uses 1h candles (TARGET_HISTORY_INTERVAL="1h"). 15m candles are
    not yet fetched; pivot quality improves if a 15m feed is added later.
    """
    result: list[FibNavCandle] = []
    for c in candles:
        mid = (c.high_price + c.low_price) / Decimal("2")
        result.append(FibNavCandle(
            close_ts_utc=c.close_ts_utc,
            open_price=mid,
            high_price=c.high_price,
            low_price=c.low_price,
            close_price=mid,
            volume=Decimal("0"),
        ))
    return result


def _nav_context_from_map(nav_map: FibNavigationMap, current_price: Decimal) -> FibNavContext:
    nav_sell = tuple(sorted(lvl.price for lvl in nav_map.extension_levels if lvl.price > current_price))
    nav_buy = tuple(sorted(
        (lvl.price for lvl in nav_map.retracement_levels if lvl.price < current_price),
        reverse=True,
    ))
    r1000 = next((lvl.price for lvl in nav_map.retracement_levels if lvl.label == "r_1000"), None)
    return FibNavContext(
        nav_sell_levels=nav_sell,
        nav_buy_levels=nav_buy,
        nav_invalidation=r1000,
        map_state=nav_map.map_state,
        rebuild_trigger=nav_map.rebuild_trigger,
        anchor_low=nav_map.anchor_low,
        anchor_high=nav_map.anchor_high,
        direction=nav_map.direction,
    )


def _build_nav_context_from_candle_set(
    *,
    fib_nav_candles: list[FibNavCandle],
    current_price: Decimal,
    prior: PriorMapMeta,
    now_utc: datetime,
) -> FibNavContext | None:
    """Primary: candle-driven swing detection. Fallback: anchor-only rebuild.

    Candle-driven path (build_fib_navigation_map) detects a fresh swing from
    history candles and returns EMERGENCY_REBUILT when the prior map is EXHAUSTED.
    Anchor fallback is used only when candles are too few or stale.
    """
    # Primary: candle-driven pivot detection
    nav_map: FibNavigationMap | None = None
    try:
        nav_map = build_fib_navigation_map(
            candles=fib_nav_candles,
            current_price=current_price,
            now_utc=now_utc,
            prior=prior,
            direction=prior.direction,
        )
    except Exception:
        pass

    if (
        nav_map is not None
        and nav_map.map_state not in {MAP_STATE_NO_DATA, MAP_STATE_STALE}
        and nav_map.extension_levels
    ):
        return _nav_context_from_map(nav_map, current_price)

    # Fallback: anchor-only rebuild when candles are insufficient or stale
    try:
        anchor_map = build_fib_navigation_map_from_anchor(
            anchor_low=prior.anchor_low,
            anchor_high=prior.anchor_high,
            current_price=current_price,
            direction=prior.direction,
            prior_map_state=prior.map_state,
            computed_at_utc=now_utc,
        )
    except Exception:
        return None
    if not anchor_map.extension_levels:
        return None
    return _nav_context_from_map(anchor_map, current_price)


def load_zone_contexts(
    *,
    markets: list[str],
    prices: dict[str, Decimal],
    swing_anchors: dict[str, list[str]],
    recent_lows: dict[str, list[str]],
    native_short_rows_path: Path,
    fib_map_rows_path: Path,
    now_utc: datetime | None = None,
    native_short_snapshot_status: str = "unverified",
    native_short_snapshot_id: str | None = None,
    canonical_fib_rows_by_symbol: dict[str, dict[str, Any]] | None = None,
    canonical_fib_stale_after: timedelta = CANONICAL_FIB_MAP_STALE_AFTER,
) -> ZoneContextLoadResult:
    _now = now_utc or datetime.now(UTC)
    snapshot_verified = native_short_snapshot_status == "loaded" and bool(native_short_snapshot_id)
    canonical_fib_rows_by_symbol = canonical_fib_rows_by_symbol or {}
    fib_rows_by_symbol, source_missing = load_fib_map_rows(fib_map_rows_path)
    native_rows_by_symbol, native_source_missing = load_native_short_context_rows(native_short_rows_path)
    fib_ext_by_symbol: dict[str, FibExtContext] = {}
    reentry_by_symbol: dict[str, ReentryContext] = {}
    activation_ts_by_symbol: dict[str, datetime | None] = {}
    input_status_by_symbol: dict[str, str] = {}
    coverage_status_by_symbol: dict[str, str] = {}
    display_state_by_symbol: dict[str, str] = {}
    prior_map_meta_by_symbol: dict[str, PriorMapMeta] = {}
    evidence_by_symbol: dict[str, CardEvidence] = {}
    # Per-symbol Planning PPP source attribution (Issue #457). load_zone_contexts()
    # is the only layer that sees which authority actually produced each of
    # entry (reentry) vs target (fib_ext) -- component sources are tracked here
    # and combined into PlanningProvenance once the loop completes.
    entry_source_by_symbol: dict[str, str] = {}
    target_source_by_symbol: dict[str, str] = {}
    source_map_id_by_symbol: dict[str, str] = {}
    source_map_cycle_id_by_symbol: dict[str, str] = {}
    source_as_of_by_symbol: dict[str, str] = {}

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
                    target_source_by_symbol[symbol] = PLANNING_SOURCE_MANUAL_REFERENCE
                if reentry is not None:
                    reentry_by_symbol[symbol] = reentry
                    entry_source_by_symbol[symbol] = PLANNING_SOURCE_MANUAL_REFERENCE
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
            row_is_canonical = _native_row_is_canonical(native_row, snapshot_verified=snapshot_verified)
            evidence_by_symbol[symbol] = _evidence_from_native_row(
                native_row,
                now_utc=_now,
                snapshot_verified=snapshot_verified,
                snapshot_id=native_short_snapshot_id,
            )
            if native_row.context_status != NATIVE_SHORT_CONTEXT_AVAILABLE:
                input_status_by_symbol[symbol] = native_row.context_status
            elif row_is_canonical:
                input_status_by_symbol[symbol] = NATIVE_SHORT_CONTEXT_AVAILABLE
            else:
                input_status_by_symbol[symbol] = "TRANSIENT_NON_CANONICAL_CONTEXT_AVAILABLE"
            coverage_status_by_symbol[symbol] = input_status_by_symbol[symbol]
            if native_row.context_status != NATIVE_SHORT_CONTEXT_AVAILABLE:
                display_state_by_symbol[symbol] = "NO_NATIVE_SHORT_FIB_CONTEXT"
            elif row_is_canonical:
                display_state_by_symbol[symbol] = "HAS_NATIVE_SHORT_FIB_CONTEXT"
            else:
                display_state_by_symbol[symbol] = "TRANSIENT_NON_CANONICAL_SHORT_CONTEXT"
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
                    _native_planning_source = (
                        PLANNING_SOURCE_NATIVE_SHORT_CANONICAL
                        if row_is_canonical
                        else PLANNING_SOURCE_NATIVE_SHORT_TRANSIENT_REFERENCE
                    )
                    entry_source_by_symbol[symbol] = _native_planning_source
                    target_source_by_symbol[symbol] = _native_planning_source
                    source_map_id_by_symbol[symbol] = evidence_by_symbol[symbol].native_map_id
                    source_map_cycle_id_by_symbol[symbol] = evidence_by_symbol[symbol].map_cycle_id
                    source_as_of_by_symbol[symbol] = evidence_by_symbol[symbol].context_ts_utc
                    # When the primary map is exhausted (all targets passed), record anchor
                    # metadata so build_cards() can attempt a candle-driven rebuild.
                    # active_target_levels==() signals MAP_COMPLETED in the native context lifecycle.
                    if not native_row.active_target_levels:
                        prior_meta = _build_prior_map_meta_from_native_row(native_row, _now)
                        if prior_meta is not None:
                            prior_map_meta_by_symbol[symbol] = prior_meta
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
                    # Partial/non-AVAILABLE native rows are never proven canonical
                    # (row_is_canonical requires context_status == AVAILABLE).
                    target_source_by_symbol[symbol] = PLANNING_SOURCE_NATIVE_SHORT_TRANSIENT_REFERENCE
                    source_map_id_by_symbol[symbol] = evidence_by_symbol[symbol].native_map_id
                    source_map_cycle_id_by_symbol[symbol] = evidence_by_symbol[symbol].map_cycle_id
                    source_as_of_by_symbol[symbol] = evidence_by_symbol[symbol].context_ts_utc
            # Planning-PPP fallback (Issue #238): a present-but-non-AVAILABLE native
            # row is authoritative for native SHORT lifecycle display, but it must
            # not block a read-only canonical 4h reference for portfolio planning
            # PPP. Fill in whichever of fib_ext/reentry the native partial row did
            # not already provide, from the market-only canonical 4h map. Native
            # lifecycle input/coverage/display status is untouched — this only
            # adds numeric reference levels for planning-PPP computation.
            if symbol not in fib_ext_by_symbol or symbol not in reentry_by_symbol:
                _fallback_row = canonical_fib_rows_by_symbol.get(symbol)
                _fallback_status = _canonical_fib_row_status(
                    _fallback_row, now_utc=_now, stale_after=canonical_fib_stale_after
                )
                if _fallback_status == "AVAILABLE":
                    _fallback_price = prices.get(market)
                    _fallback_built = _build_zone_context_from_canonical_row(
                        _fallback_row, current_price=_fallback_price
                    )
                    if _fallback_built is not None:
                        _fallback_fib_ext, _fallback_reentry = _fallback_built
                        _fallback_as_of = _fmt_unavailable((_fallback_row or {}).get("asof_ts_utc"))
                        if symbol not in fib_ext_by_symbol:
                            fib_ext_by_symbol[symbol] = _fallback_fib_ext
                            target_source_by_symbol[symbol] = PLANNING_SOURCE_CANONICAL_4H_NAVIGATION
                            source_as_of_by_symbol[symbol] = _fallback_as_of
                        if symbol not in reentry_by_symbol:
                            reentry_by_symbol[symbol] = _fallback_reentry
                            entry_source_by_symbol[symbol] = PLANNING_SOURCE_CANONICAL_4H_NAVIGATION
                            source_as_of_by_symbol[symbol] = _fallback_as_of
            continue

        canonical_row = canonical_fib_rows_by_symbol.get(symbol)
        canonical_status = _canonical_fib_row_status(
            canonical_row, now_utc=_now, stale_after=canonical_fib_stale_after
        )
        if canonical_status == "AVAILABLE":
            current_price = prices.get(market)
            built = _build_zone_context_from_canonical_row(canonical_row, current_price=current_price)
            if built is not None:
                fib_ext, reentry = built
                fib_ext_by_symbol[symbol] = fib_ext
                reentry_by_symbol[symbol] = reentry
                target_source_by_symbol[symbol] = PLANNING_SOURCE_CANONICAL_4H_NAVIGATION
                entry_source_by_symbol[symbol] = PLANNING_SOURCE_CANONICAL_4H_NAVIGATION
                source_as_of_by_symbol[symbol] = _fmt_unavailable((canonical_row or {}).get("asof_ts_utc"))
                activation_ts_by_symbol[symbol] = fib_ext.anchor_end_ts_utc
                input_status_by_symbol[symbol] = CANONICAL_4H_CONTEXT_AVAILABLE
                coverage_status_by_symbol[symbol] = CANONICAL_4H_CONTEXT_AVAILABLE
                display_state_by_symbol[symbol] = "NO_NATIVE_SHORT_FIB_CONTEXT"
                continue
            canonical_status = "UNAVAILABLE"
        if canonical_status in {"STALE", "UNAVAILABLE"}:
            input_status_by_symbol[symbol] = (
                "CANONICAL_4H_CONTEXT_STALE" if canonical_status == "STALE" else "CANONICAL_4H_CONTEXT_UNAVAILABLE"
            )
            coverage_status_by_symbol[symbol] = "CONTEXT_INVALID_OR_STALE"
            display_state_by_symbol[symbol] = "CONTEXT_INVALID_OR_STALE"
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
            target_source_by_symbol[symbol] = PLANNING_SOURCE_LEGACY_REFERENCE
        if reentry is not None:
            reentry_by_symbol[symbol] = reentry
            entry_source_by_symbol[symbol] = PLANNING_SOURCE_LEGACY_REFERENCE
        if fib_ext is not None or reentry is not None:
            source_as_of_by_symbol[symbol] = _fmt_unavailable(fib_row.get("anchor_end_ts"))
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

    planning_provenance_by_symbol: dict[str, PlanningProvenance] = {}
    for symbol in set(entry_source_by_symbol) | set(target_source_by_symbol):
        planning_provenance_by_symbol[symbol] = make_planning_provenance(
            entry_source=entry_source_by_symbol.get(symbol, "DATA_UNAVAILABLE"),
            target_source=target_source_by_symbol.get(symbol, "DATA_UNAVAILABLE"),
            source_map_id=source_map_id_by_symbol.get(symbol, "DATA_UNAVAILABLE"),
            source_map_cycle_id=source_map_cycle_id_by_symbol.get(symbol, "DATA_UNAVAILABLE"),
            source_as_of_ts_utc=source_as_of_by_symbol.get(symbol, "DATA_UNAVAILABLE"),
        )

    return ZoneContextLoadResult(
        fib_ext_by_symbol=fib_ext_by_symbol,
        reentry_by_symbol=reentry_by_symbol,
        activation_ts_by_symbol=activation_ts_by_symbol,
        input_status_by_symbol=input_status_by_symbol,
        coverage_status_by_symbol=coverage_status_by_symbol,
        display_state_by_symbol=display_state_by_symbol,
        source_name="fibo_target_map_rows_v1.csv",
        source_missing=source_missing,
        native_source_missing=native_source_missing,
        prior_map_meta_by_symbol=prior_map_meta_by_symbol,
        evidence_by_symbol=evidence_by_symbol,
        planning_provenance_by_symbol=planning_provenance_by_symbol,
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


def _fetch_market_context_candles_by_symbol(
    *,
    venue: str,
    symbols: list[str],
    now_utc: datetime,
) -> dict[str, list[MarketContextCandle]]:
    if not symbols:
        return {}
    since_utc = now_utc - timedelta(days=_MARKET_CONTEXT_LOOKBACK_DAYS)
    conn = get_connection()
    try:
        out: dict[str, list[MarketContextCandle]] = {symbol: [] for symbol in symbols}
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(symbols))
            cur.execute(
                f"""
                SELECT
                    a.symbol,
                    c.close_ts_utc,
                    c.open_price,
                    c.high_price,
                    c.low_price,
                    c.close_price
                FROM obs_market_candle c
                JOIN asset a
                  ON a.asset_id = c.asset_id
                WHERE c.venue = %s
                  AND c.interval_code = %s
                  AND a.symbol IN ({placeholders})
                  AND c.close_ts_utc >= %s
                ORDER BY a.symbol ASC, c.close_ts_utc ASC
                """,
                (venue, _MARKET_CONTEXT_INTERVAL, *symbols, since_utc),
            )
            rows = list(cur.fetchall())
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            if symbol not in out:
                continue
            close_ts = row.get("close_ts_utc")
            if close_ts is None:
                continue
            close_ts_utc = close_ts.replace(tzinfo=UTC) if close_ts.tzinfo is None else close_ts.astimezone(UTC)
            open_price = _parse_decimal(row.get("open_price"))
            high_price = _parse_decimal(row.get("high_price"))
            low_price = _parse_decimal(row.get("low_price"))
            close_price = _parse_decimal(row.get("close_price"))
            if open_price is None or high_price is None or low_price is None or close_price is None:
                continue
            out[symbol].append(
                MarketContextCandle(
                    close_ts_utc=close_ts_utc,
                    open_price=open_price,
                    high_price=high_price,
                    low_price=low_price,
                    close_price=close_price,
                )
            )
        return out
    finally:
        conn.close()


def _fetch_breath_curve_candles_by_symbol(
    *,
    venue: str,
    symbols: list[str],
    now_utc: datetime,
) -> dict[str, list[BreathCurveLiveCandle]]:
    if not symbols:
        return {}
    scoped_symbols = sorted(set([*symbols, BTC_SYMBOL]))
    since_utc = now_utc - timedelta(days=_BREATH_CURVE_LOOKBACK_DAYS)
    conn = get_connection()
    try:
        out: dict[str, list[BreathCurveLiveCandle]] = {symbol: [] for symbol in scoped_symbols}
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(scoped_symbols))
            cur.execute(
                f"""
                SELECT
                    a.symbol,
                    c.close_ts_utc,
                    c.open_price,
                    c.high_price,
                    c.low_price,
                    c.close_price
                FROM obs_market_candle c
                JOIN asset a
                  ON a.asset_id = c.asset_id
                WHERE c.venue = %s
                  AND c.interval_code = %s
                  AND a.symbol IN ({placeholders})
                  AND c.close_ts_utc >= %s
                  AND c.close_ts_utc <= %s
                ORDER BY a.symbol ASC, c.close_ts_utc ASC
                """,
                (venue, _BREATH_CURVE_INTERVAL, *scoped_symbols, since_utc, now_utc),
            )
            rows = list(cur.fetchall())
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            if symbol not in out:
                continue
            close_ts = row.get("close_ts_utc")
            if close_ts is None:
                continue
            close_ts_utc = close_ts.replace(tzinfo=UTC) if close_ts.tzinfo is None else close_ts.astimezone(UTC)
            open_price = _parse_decimal(row.get("open_price"))
            high_price = _parse_decimal(row.get("high_price"))
            low_price = _parse_decimal(row.get("low_price"))
            close_price = _parse_decimal(row.get("close_price"))
            if open_price is None or high_price is None or low_price is None or close_price is None:
                continue
            out[symbol].append(
                BreathCurveLiveCandle(
                    close_ts_utc=close_ts_utc,
                    open_price=open_price,
                    high_price=high_price,
                    low_price=low_price,
                    close_price=close_price,
                )
            )
        return out
    finally:
        conn.close()


def _derive_presentation_mode(
    market: str,
    reasons: frozenset[str],
    account_plan_policy: AccountPlanPolicy | None = None,
) -> str:
    """Derive the card presentation mode from market inclusion provenance.

    Priority: POSITION_HELD > OPEN_ORDER > ACCOUNT_PLAN_ENABLED > WATCH_ONLY_ROTATION > MARKET_SELECTED.
    """
    if "POSITION_HELD" in reasons:
        return CARD_MODE_POSITION_HELD
    if "OPEN_ORDER" in reasons:
        return CARD_MODE_ACCOUNT_ORDER_ONLY
    policy = account_plan_policy or AccountPlanPolicy()
    if (
        not policy.is_hidden
        and (
            policy.is_candidate_enabled
            or policy.is_order_proposal_enabled
            or policy.source == "MANUAL_ADD"
        )
    ):
        return CARD_MODE_ACCOUNT_PLAN_ENABLED
    if "CORE_SENSOR" in reasons:
        return CARD_MODE_WATCH_ONLY_ROTATION
    return CARD_MODE_MARKET_SELECTED


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
    prior_map_meta_by_symbol: dict[str, PriorMapMeta] | None = None,
    now_utc: datetime | None = None,
    inclusion_reasons_by_market: Mapping[str, frozenset[str]] | None = None,
    account_plan_policy_by_market: Mapping[str, AccountPlanPolicy] | None = None,
    breath_curve_by_symbol: Mapping[str, dict[str, Any]] | None = None,
    evidence_by_symbol: Mapping[str, CardEvidence] | None = None,
    price_ts_by_market: Mapping[str, datetime | None] | None = None,
    order_snapshot_ts_utc: datetime | None = None,
    planning_provenance_by_symbol: Mapping[str, PlanningProvenance] | None = None,
) -> list[ProfitPlanCard]:
    _prior = prior_map_meta_by_symbol or {}
    _now = now_utc or datetime.now(UTC)
    cards: list[ProfitPlanCard] = []
    for market in markets:
        symbol = market.split("-")[0].upper()
        current = prices.get(market)
        buy_orders, sell_orders = orders_by_symbol.get(symbol, ((), ()))
        history = history_by_symbol.get(symbol)
        base_evidence = (evidence_by_symbol or {}).get(symbol, CardEvidence())
        card_evidence = dataclasses.replace(
            base_evidence,
            price_ts_utc=_fmt_ts((price_ts_by_market or {}).get(market)),
            price_freshness_state=price_status_by_market.get(market, "DATA_UNAVAILABLE"),
            order_snapshot_ts_utc=_fmt_ts(order_snapshot_ts_utc),
            order_coverage_ts_utc=_fmt_ts(order_snapshot_ts_utc),
            generation_ts_utc=_fmt_ts(_now),
        )

        # Candle-driven nav rebuild: primary path uses history candles to detect a fresh
        # swing (build_fib_navigation_map); anchor-only fallback when candles are
        # insufficient or stale. Only triggered when prior map is MAP_COMPLETED.
        nav_context: FibNavContext | None = None
        prior_meta = _prior.get(symbol)
        if prior_meta is not None and current is not None:
            fib_nav_candles = _candles_to_fib_nav(
                history.candles_since_activation if history is not None else ()
            )
            nav_context = _build_nav_context_from_candle_set(
                fib_nav_candles=fib_nav_candles,
                current_price=current,
                prior=prior_meta,
                now_utc=_now,
            )

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
                fib_nav_context=nav_context,
                presentation_mode=_derive_presentation_mode(
                    market,
                    reasons=(inclusion_reasons_by_market or {}).get(market, frozenset()),
                    account_plan_policy=(account_plan_policy_by_market or {}).get(market),
                ),
                breath_curve=(breath_curve_by_symbol or {}).get(symbol),
                evidence=card_evidence,
                planning_provenance=(planning_provenance_by_symbol or {}).get(symbol),
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
    print(
        "short_context_bridge=native_short_context_v1"
        "+canonical_fib_zone_map_latest_v1+legacy_1d_reference_fallback"
    )
    print(
        "short_context_coverage="
        + " ; ".join(f"{key}:{coverage_summary.get(key, 0)}" for key in (
            "NATIVE_SHORT_CONTEXT_AVAILABLE",
            "INSUFFICIENT_4H_HISTORY",
            "INSUFFICIENT_1H_HISTORY",
            CANONICAL_4H_CONTEXT_AVAILABLE,
            "LEGACY_1D_CONTEXT_ONLY",
            "FIB_MAP_SYMBOL_MISSING",
            "FIB_MAP_SOURCE_MISSING",
            "MARKET_DATA_MISSING",
            "CONTEXT_INVALID_OR_STALE",
        ))
    )
    # Issue #212: is_relevant (attention/actionability) and visibility_class
    # (default-view grouping) are separate concerns. A card can be fully
    # present in the rendered view (all cards always are) while being
    # non-actionable -- that combination must be labeled by its
    # visibility_class, never reported as "filtered". visibility_class is a
    # three-way, mutually-exclusive partition of every card, so the three
    # counts below always sum to len(cards).
    total = len(cards)
    _SUMMARY_LABEL_BY_VISIBILITY = {
        VISIBILITY_NATIVE_ATTENTION: "RELEVANT",
        VISIBILITY_CANONICAL_NAVIGATION_REFERENCE: "CANONICAL_NAV",
        VISIBILITY_CONTEXT_UNAVAILABLE: "CONTEXT_UNAVAILABLE",
    }
    attention_count = sum(1 for card in cards if card.visibility_class == VISIBILITY_NATIVE_ATTENTION)
    canonical_navigation_count = sum(1 for card in cards if card.visibility_class == VISIBILITY_CANONICAL_NAVIGATION_REFERENCE)
    context_unavailable_count = sum(1 for card in cards if card.visibility_class == VISIBILITY_CONTEXT_UNAVAILABLE)
    print(f"attention={attention_count}/{total}")
    print(f"canonical_navigation={canonical_navigation_count}/{total}")
    print(f"context_unavailable={context_unavailable_count}/{total}")
    for card in cards:
        summary_label = _SUMMARY_LABEL_BY_VISIBILITY.get(card.visibility_class, "CONTEXT_UNAVAILABLE")
        print(
            f"{card.symbol}: scenario={card.scenario_type}"
            f" action={card.action_label}"
            f" primary_state={card.primary_state}"
            f" short_context={card.short_context_coverage_status}"
            f" visibility={card.visibility_class}"
            f" is_relevant={card.is_relevant}"
            f" [{summary_label}]"
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
    native_short_rows_path = _resolve_native_short_context_rows_path(
        output_root=output_root,
        native_short_context_rows_arg=args.native_short_context_rows,
    )
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
    price_ts_by_market = {
        market: (
            context.market_price_by_symbol.get(market.split("-", 1)[0].upper()).source_ts_utc
            if context.market_price_by_symbol.get(market.split("-", 1)[0].upper()) is not None
            else None
        )
        for market in context.markets
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

    # Read-only enrichment: canonical_fib_zone_map_latest_v1 covers the full
    # market-only universe, unlike the 4-row native-short snapshot. Any read
    # failure degrades to an empty map (falls back to the legacy 1d path /
    # explicit missing classification) rather than blocking the render.
    # broker_private_calls=0 — canonical_fib_zone_map_latest_v1 is market-only.
    # Issue #489: explicit, separately-resolved canonical 4h DB fetch health
    # -- the only truthful source for FIB_MAP_SOURCE_UNAVAILABLE
    # classification. Must never be inferred from the legacy 1d CSV's
    # FIB_MAP_SOURCE_MISSING status (load_fib_map_rows()'s source_missing),
    # which describes a different, independently-failing source.
    canonical_fib_source_available = True
    try:
        _canonical_fib_conn = get_connection()
        try:
            canonical_fib_rows_by_symbol = fetch_canonical_fib_map_rows(
                _canonical_fib_conn,
                venue=args.venue,
                quote_currency=args.quote_currency,
                interval_code=_MARKET_CONTEXT_INTERVAL,
            )
        finally:
            _canonical_fib_conn.close()
    except Exception as exc:
        print(f"[warn] canonical fib zone map read failed: {exc}", file=sys.stderr)
        canonical_fib_rows_by_symbol = {}
        canonical_fib_source_available = False

    zone_contexts = load_zone_contexts(
        markets=list(context.markets),
        prices=prices,
        swing_anchors=_parse_kv_list(args.swing_anchors, 3),
        recent_lows=_parse_kv_list(args.recent_lows, 2),
        native_short_rows_path=native_short_rows_path,
        fib_map_rows_path=Path(args.fib_map_rows),
        native_short_snapshot_status=getattr(args, "native_short_snapshot_status", "unverified"),
        native_short_snapshot_id=getattr(args, "native_short_snapshot_id", None),
        canonical_fib_rows_by_symbol=canonical_fib_rows_by_symbol,
    )
    history_by_symbol = fetch_market_target_history_by_symbol(
        venue=args.venue,
        activation_ts_by_symbol=zone_contexts.activation_ts_by_symbol,
    )
    now_utc = datetime.now(UTC)
    _mc_symbols = _symbols_from_markets(list(context.markets))
    _mc_candles = _fetch_market_context_candles_by_symbol(
        venue=args.venue,
        symbols=_mc_symbols,
        now_utc=now_utc,
    )
    market_context_by_symbol = build_market_context_by_symbol(
        candles_by_symbol=_mc_candles,
        now_utc=now_utc,
    )
    _breath_curve_candles = _fetch_breath_curve_candles_by_symbol(
        venue=args.venue,
        symbols=_mc_symbols,
        now_utc=now_utc,
    )
    breath_curve_by_symbol = build_breath_curve_live_by_symbol(
        candles_by_symbol=_breath_curve_candles,
        as_of_ts_utc=now_utc,
        symbols=_mc_symbols,
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
        prior_map_meta_by_symbol=zone_contexts.prior_map_meta_by_symbol,
        inclusion_reasons_by_market=context.market_inclusion_reasons_by_market,
        account_plan_policy_by_market=context.account_plan_policy_by_market,
        breath_curve_by_symbol=breath_curve_by_symbol,
        evidence_by_symbol=zone_contexts.evidence_by_symbol,
        price_ts_by_market=price_ts_by_market,
        order_snapshot_ts_utc=context.latest_order_snapshot_ts_utc,
        planning_provenance_by_symbol=zone_contexts.planning_provenance_by_symbol,
    )

    # Portfolio composition (Issue #238): compose held amount / EUR value / cost
    # basis onto held-token cards from the already-loaded account-scoped context.
    # Read-only DB reads only — broker_private_calls=0, broker_writes=0.
    held_amount_by_symbol, held_eur_value_by_symbol = held_amount_and_value_by_symbol(
        balances=list(context.balances),
        prices=prices,
        quote_currency=getattr(args, "quote_currency", "EUR"),
    )
    try:
        _cost_basis_conn = get_connection()
        try:
            cost_basis_by_symbol = fetch_latest_cost_basis_by_symbol(
                _cost_basis_conn,
                trading_account_id=context.trading_account_id,
                venue=args.venue,
            )
        finally:
            _cost_basis_conn.close()
    except Exception as exc:
        print(f"[warn] cost basis read failed: {exc}", file=sys.stderr)
        cost_basis_by_symbol = {}
    balance_freshness_status = classify_wallet_freshness(
        context.latest_balance_snapshot_ts_utc,
        now_utc=now_utc,
    )
    # Account portfolio membership is scoped to the rendered account by the
    # account_asset query in load_account_scoped_short_dashboard_context().
    # Keep the defensive row-account check here so another account's row can
    # never become a badge if context construction changes.
    portfolio_asset_markets = portfolio_member_markets_for_rendered_account(
        account_asset_rows=context.account_asset_rows,
        trading_account_id=context.trading_account_id,
    )
    # COHORT_PUBLISHED is the internal publication-cohort reason.
    market_selected_markets = {
        market
        for market, reasons in context.market_inclusion_reasons_by_market.items()
        if "COHORT_PUBLISHED" in reasons
    }
    core_sensor_markets = {
        market
        for market, reasons in context.market_inclusion_reasons_by_market.items()
        if "CORE_SENSOR" in reasons
    }
    cards = apply_portfolio_account_evidence(
        cards,
        held_amount_by_symbol=held_amount_by_symbol,
        held_eur_value_by_symbol=held_eur_value_by_symbol,
        cost_basis_by_symbol=cost_basis_by_symbol,
        balance_freshness_status=balance_freshness_status,
        portfolio_asset_markets=portfolio_asset_markets,
        market_selected_markets=market_selected_markets,
        core_sensor_markets=core_sensor_markets,
    )

    # Issue #489: truthful per-symbol Fib coverage classification. Read-only
    # composition over the overlay facts apply_portfolio_account_evidence()
    # just attached (is_market_selected/is_core_sensor/is_wallet_held/
    # is_portfolio_asset) plus open-order presence and native SHORT scope
    # state -- must run after apply_portfolio_account_evidence().
    native_short_scope_state_by_symbol = load_native_short_scope_state_by_symbol(native_short_rows_path)
    cards = apply_fib_coverage_classification(
        cards,
        open_order_count_by_market=context.open_order_count_by_market,
        native_short_scope_state_by_symbol=native_short_scope_state_by_symbol,
        canonical_fib_source_available=canonical_fib_source_available,
    )

    # Load market tick rules from DB and apply price normalization to all cards.
    # DB is the preferred source; static fallback covers markets with no synced row.
    # broker_private_calls=0 — venue_market is public market metadata.
    try:
        _tick_conn = get_connection()
        try:
            tick_rules_by_market = load_tick_rules_from_db(
                _tick_conn,
                venue=args.venue,
                markets=list(context.markets),
            )
        finally:
            _tick_conn.close()
    except Exception:
        tick_rules_by_market = {}

    cards, normalization_audit = apply_price_tick_normalization(
        cards,
        tick_rules_by_market=tick_rules_by_market,
        venue=args.venue,
    )

    try:
        previous_snapshot = _load_previous_json_snapshot(getattr(args, "previous_json", None))
    except Exception as exc:
        print(f"[error] previous JSON snapshot load failed: {exc}", file=sys.stderr)
        return 1
    cards = apply_card_deltas(cards, previous_snapshot=previous_snapshot)

    # Snapshot evidence is descriptive only. Absence of persisted native context
    # does not identify a candle-ETL cause.
    native_context_count = sum(
        1 for s in zone_contexts.coverage_status_by_symbol.values()
        if s == "NATIVE_SHORT_CONTEXT_AVAILABLE"
    )
    canonical_navigation_symbols = {
        symbol
        for symbol, status in zone_contexts.coverage_status_by_symbol.items()
        if status == CANONICAL_4H_CONTEXT_AVAILABLE
    }
    snapshot_evidence = summarize_native_short_snapshot_evidence(
        markets=list(context.markets),
        rows_path=native_short_rows_path,
        canonical_status=getattr(args, "native_short_snapshot_status", "unverified"),
        snapshot_id=getattr(args, "native_short_snapshot_id", None),
        canonical_supported_symbols=canonical_navigation_symbols,
    )
    pipeline_health: dict[str, object] = {
        "native_source_missing": zone_contexts.native_source_missing,
        **snapshot_evidence,
        "native_context_globally_unavailable": (
            zone_contexts.native_source_missing or native_context_count == 0
        ),
        "pipeline_status": (
            "canonical_snapshot_missing_or_invalid"
            if snapshot_evidence["canonical_snapshot_status"] in {"missing", "invalid"}
            else (
                "supported_context_stale"
                if snapshot_evidence["supported_context_stale_count"]
                else (
                    "loaded" if snapshot_evidence["canonical_snapshot_status"] == "loaded"
                    else "unverified"
                )
            )
        ),
        "blocking_reasons": (
            ["CANONICAL_NATIVE_SHORT_SNAPSHOT_MISSING_OR_INVALID"]
            if snapshot_evidence["canonical_snapshot_status"] in {"missing", "invalid"}
            else (
                ["SUPPORTED_NATIVE_SHORT_CONTEXT_STALE"]
                if snapshot_evidence["supported_context_stale_count"]
                else ([] if native_context_count > 0 else ["NATIVE_SHORT_CONTEXT_UNAVAILABLE"])
            )
        ),
    }
    pipeline_banner_html = native_short_snapshot_banner(snapshot_evidence)

    # Read-only enrichment (Issue #255): market_rotation_pressure_v1 is a
    # separately-owned, market-only, account-agnostic engine. Profit Plan only
    # reads its already-persisted latest snapshot + observation rows -- never
    # recomputes score/direction/evidence-lights/breadth/rank/confirmation.
    # Any DB/schema/parsing failure degrades to an unavailable projection
    # rather than blocking the render (fail-closed, never fabricated).
    # broker_private_calls=0 -- rotation pressure tables are market-only.
    try:
        _rotation_conn = get_connection()
        try:
            _rotation_missing = check_rotation_schema_ready(_rotation_conn)
            if _rotation_missing:
                raise RuntimeError(f"rotation schema not ready: missing={_rotation_missing}")
            rotation_header_row = fetch_latest_rotation_snapshot(
                _rotation_conn, venue=args.venue, model_version=ROTATION_MODEL_VERSION
            )
            rotation_history_rows = fetch_rotation_pressure_history(
                _rotation_conn, venue=args.venue, model_version=ROTATION_MODEL_VERSION
            )
            rotation_observation_rows = (
                fetch_rotation_snapshot_observations(
                    _rotation_conn,
                    pressure_snapshot_id=int(rotation_header_row["pressure_snapshot_id"]),
                )
                if rotation_header_row is not None
                else []
            )
        finally:
            _rotation_conn.close()
    except Exception as exc:
        print(f"[warn] rotation pressure read failed: {exc}", file=sys.stderr)
        rotation_header_row = None
        rotation_observation_rows = []
        rotation_history_rows = []

    rotation_projection = build_rotation_projection(
        rotation_header_row,
        rotation_observation_rows,
        now_utc=now_utc,
        history_rows=rotation_history_rows,
    )

    output_html.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(output_html.parent, 0o755)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    html_content = render_full_html(
        cards,
        broker_mode="db_snapshot",
        monitor_link=monitor_link,
        nav_html=cockpit_nav(account_profile=args.account_profile).strip(),
        storage_scope=args.account_profile,
        render_id=snapshot_render_id,
        writer_instance_id=writer_instance_id,
        pipeline_banner_html=pipeline_banner_html,
        rotation_projection=rotation_projection,
    )
    json_content = json.dumps(
        build_json_snapshot(
            cards,
            broker_mode="db_snapshot",
            writer_instance_id=writer_instance_id,
            render_id=snapshot_render_id,
            account_snapshot_ts_utc=_fmt_ts(context.latest_balance_snapshot_ts_utc),
            order_snapshot_ts_utc=_fmt_ts(context.latest_order_snapshot_ts_utc),
            normalization_audit_by_symbol=normalization_audit,
            pipeline_health=pipeline_health,
            market_context_by_symbol=market_context_by_symbol,
            rotation_projection=rotation_projection,
        ),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )

    # Atomic publication: flush → fsync → chmod 0644 → os.replace.
    atomic_text_write(html_content, output_html)
    atomic_text_write(json_content, output_json)

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
