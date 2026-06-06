"""
Synth v2.6 research runner: MANUAL_EXACT_ZONE_BACKTEST_V1

Layer: research/backtest only.

Boundary:
  - DB reads allowed (obs_market_candle, asset, paper_advice_observation,
    selection_state, regime_selector_backtest_observation_v1, signal_engine_state).
  - DB writes forbidden.
  - No broker calls, no orders, no account access.
  - No changes to selection_engine, decision_gate, execution_planner, executor.
  - Do not modify existing re-entry or fib modules.

Purpose:
  Backtest a manually-specified exact entry/exit zone against historical 15m candles.

Execution semantics:
  - Enter when first candle (strictly after prediction_ts) with low <= buy_level.
  - Exit when first candle strictly after entry candle with high >= sell_target.
  - No same-candle entry and exit.
  - If target never hit, value position at final candle close.
  - No fees, slippage, spread, orderbook simulation, or partial fills.
  - Entry price = buy_level (exact fill assumed).
  - Exit price = sell_target if hit, else final candle close price.

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pymysql

from src.account.long_reserve_policy_v1 import (
    RESERVE_SOURCE_ASSET_OVERRIDE,
    RESERVE_SOURCE_DEFAULT_ASSUMED,
    TP_SCOPE_CHILD_SHORT_SWING,
    TP_SCOPE_PARENT_TF_FULL,
)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:  # pragma: no cover
    HAS_MATPLOTLIB = False

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RUNNER_NAME = "MANUAL_EXACT_ZONE_BACKTEST_V1"
RUNNER_VERSION = "1.0.0"

DEFAULT_SYMBOL = "NEAR"
DEFAULT_QUOTE = "EUR"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "15m"
DEFAULT_HORIZON_DAYS = 14
DEFAULT_BUY_LEVEL = Decimal("2.00")
DEFAULT_SELL_TARGET = Decimal("2.12")
DEFAULT_STARTING_CAPITAL = Decimal("100.00")
DEFAULT_PREDICTION_TS = "2026-05-21T00:00:00Z"

INTERVAL_DELTA = timedelta(minutes=15)

READ_ONLY_FORBIDDEN = {
    "insert", "update", "delete", "replace", "create", "alter",
    "drop", "truncate", "grant", "revoke", "call", "load",
    "rename", "lock", "unlock",
}

# Continuation gate state constants
GATE_CONTINUATION_SUPPORTED = "CONTINUATION_SUPPORTED"
GATE_CONTINUATION_WEAK = "CONTINUATION_WEAK"
GATE_REGIME_CONFLICT = "REGIME_CONFLICT"
GATE_BREATH_CONFLICT = "BREATH_CONFLICT"
GATE_CONTEXT_UNKNOWN = "CONTEXT_UNKNOWN"
GATE_NOT_LIVE_VALID = "NOT_LIVE_VALID"

# Variant type identifiers
VARIANT_TYPE_STANDARD = "STANDARD"
VARIANT_TYPE_BASELINE = "BASELINE"
VARIANT_TYPE_BREATH_HOLD = "BREATH_HOLD"
VARIANT_TYPE_REGIME_SHIFT = "REGIME_SHIFT"
VARIANT_TYPE_TRAILING_RUNNER = "TRAILING_RUNNER"
VARIANT_TYPE_PARENT_CONTEXT = "PARENT_CONTEXT"

# Staleness thresholds per candle interval (minutes)
_INTERVAL_MAX_STALENESS_MINUTES: dict[str, int] = {
    "15m": 480,    # 8h
    "1h":  1440,   # 24h
    "4h":  2880,   # 48h
    "1d":  10080,  # 7d
}
_DEFAULT_MAX_STALENESS_MINUTES = 480

# Context lookup status codes
CTX_FOUND = "FOUND"
CTX_SOURCE_MISSING = "SOURCE_MISSING"
CTX_TIME_RANGE_MISSING = "TIME_RANGE_MISSING"
CTX_ASOF_JOIN_MISS = "ASOF_JOIN_MISS"
CTX_CONTEXT_TOO_STALE = "CONTEXT_TOO_STALE"
CTX_CONTEXT_TRULY_UNKNOWN = "CONTEXT_TRULY_UNKNOWN"

# Context classification sets (matched upper-cased)
_POSITIVE_BREATH_PHASES = frozenset({
    "EXPANSION", "IMPULSE", "TRENDING", "ACCUMULATION",
    "MARKUP", "BULLISH", "CONTINUATION", "MOMENTUM",
})
_NEGATIVE_BREATH_PHASES = frozenset({
    "EXHAUSTION", "DISTRIBUTION", "REVERSAL", "CORRECTION",
    "BEARISH", "CONTRACTION", "MARKDOWN", "FADE",
})
_POSITIVE_BREATH_ALIGNMENTS = frozenset({
    "POSITIVE", "ALIGNED", "BULLISH", "UP", "STRONG", "SUPPORTIVE",
})
_NEGATIVE_BREATH_ALIGNMENTS = frozenset({
    "NEGATIVE", "DIVERGING", "BEARISH", "DOWN", "WEAK", "CONFLICTING",
})
_POSITIVE_REGIMES = frozenset({
    "BULL", "UPTREND", "MARKUP", "ACCUMULATION", "EXPANSION",
    "BULLISH", "TRENDING_UP", "RISK_ON", "MOMENTUM",
})
_NEGATIVE_REGIMES = frozenset({
    "BEAR", "DOWNTREND", "MARKDOWN", "DISTRIBUTION", "CONTRACTION",
    "BEARISH", "TRENDING_DOWN", "RISK_OFF", "BREAKDOWN",
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class Candle:
    open_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass
class BacktestResult:
    # Input parameters
    symbol: str
    quote: str
    venue: str
    interval_code: str
    horizon_days: int
    buy_level: Decimal
    sell_target: Decimal
    starting_capital: Decimal
    prediction_ts: datetime
    prediction_timestamp_status: str
    window_start_ts: datetime
    window_end_ts: datetime

    # Trade outcome
    entry_hit: bool = False
    entry_ts: Optional[datetime] = None
    entry_price: Optional[Decimal] = None
    target_hit: bool = False
    target_ts: Optional[datetime] = None
    exit_price: Optional[Decimal] = None
    gross_return_pct: Optional[Decimal] = None
    pnl_eur: Optional[Decimal] = None
    time_to_target_hours: Optional[Decimal] = None
    maximum_adverse_excursion_pct: Optional[Decimal] = None
    maximum_favorable_excursion_pct: Optional[Decimal] = None
    final_value_eur: Optional[Decimal] = None
    buy_and_hold_return_from_entry_to_end: Optional[Decimal] = None
    improvement_vs_buy_and_hold: Optional[Decimal] = None

    # Candle coverage
    candles_fetched: int = 0
    first_candle_ts: Optional[datetime] = None
    last_candle_ts: Optional[datetime] = None
    last_close_price: Optional[Decimal] = None

    # Context annotation (best-effort, UNKNOWN if unavailable)
    market_regime: str = "UNKNOWN"
    symbol_regime: str = "UNKNOWN"
    breath_phase: str = "UNKNOWN"
    breath_alignment: str = "UNKNOWN"
    context_quality_tier: str = "UNKNOWN"

    # Event log
    events: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def load_db_config(env_file: Optional[str] = None) -> DbConfig:
    if load_dotenv is not None:
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()
    return DbConfig(
        host=os.getenv("SYNTH_DB_HOST") or os.getenv("DB_HOST") or "127.0.0.1",
        port=int(os.getenv("SYNTH_DB_PORT") or os.getenv("DB_PORT") or "3306"),
        user=os.getenv("SYNTH_DB_USER") or os.getenv("DB_USER") or "root",
        password=os.getenv("SYNTH_DB_PASSWORD") or os.getenv("DB_PASSWORD") or "",
        database=os.getenv("SYNTH_DB_NAME") or os.getenv("DB_NAME") or "synth",
    )


def connect(config: DbConfig):
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _assert_read_only(sql: str) -> None:
    first = sql.strip().lower().split(None, 1)[0] if sql.strip() else ""
    if first in READ_ONLY_FORBIDDEN:
        raise RuntimeError(f"Forbidden write SQL attempted: {first}")


def fetch_all(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    _assert_read_only(sql)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_one(conn, sql: str, params: tuple = ()) -> Optional[dict[str, Any]]:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None


def detect_candle_columns(conn) -> dict[str, str]:
    rows = fetch_all(conn, "SHOW COLUMNS FROM obs_market_candle")
    available = {str(r["Field"]) for r in rows}
    mapping: dict[str, str] = {}
    for logical, candidates in {
        "open": ("open_price", "open"),
        "high": ("high_price", "high"),
        "low": ("low_price", "low"),
        "close": ("close_price", "close"),
    }.items():
        for c in candidates:
            if c in available:
                mapping[logical] = c
                break
        if logical not in mapping:
            raise RuntimeError(f"Cannot find candle column for '{logical}'")
    return mapping


def fetch_asset_id(conn, symbol: str) -> Optional[int]:
    row = fetch_one(
        conn,
        "SELECT asset_id FROM asset WHERE symbol = %s LIMIT 1",
        (symbol,),
    )
    return int(row["asset_id"]) if row else None


def fetch_candles(
    conn,
    columns: dict[str, str],
    asset_id: int,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
) -> list[Candle]:
    rows = fetch_all(
        conn,
        f"""
        SELECT
            open_ts_utc,
            `{columns['open']}` AS open_price,
            `{columns['high']}` AS high_price,
            `{columns['low']}` AS low_price,
            `{columns['close']}` AS close_price
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
          AND open_ts_utc >= %s
          AND open_ts_utc < %s
        ORDER BY open_ts_utc ASC
        """,
        (asset_id, venue, interval_code, from_ts, to_ts),
    )
    result = []
    for r in rows:
        ts = r["open_ts_utc"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        result.append(Candle(
            open_ts_utc=ts,
            open_price=Decimal(str(r["open_price"])),
            high_price=Decimal(str(r["high_price"])),
            low_price=Decimal(str(r["low_price"])),
            close_price=Decimal(str(r["close_price"])),
        ))
    return result


def fetch_context_annotation(
    conn,
    symbol: str,
    venue: str,
    prediction_ts: datetime,
) -> dict[str, str]:
    """Best-effort context annotation at prediction_ts. Returns UNKNOWN for unavailable fields."""
    context: dict[str, str] = {
        "market_regime": "UNKNOWN",
        "symbol_regime": "UNKNOWN",
        "breath_phase": "UNKNOWN",
        "breath_alignment": "UNKNOWN",
        "context_quality_tier": "UNKNOWN",
    }

    window_start = prediction_ts - timedelta(days=3)
    window_end = prediction_ts + timedelta(hours=1)

    # market_regime from regime_selector_backtest_observation_v1
    try:
        row = fetch_one(
            conn,
            """
            SELECT global_regime, asset_class_regime
            FROM regime_selector_backtest_observation_v1
            WHERE symbol = %s AND asof_ts_utc <= %s
            ORDER BY asof_ts_utc DESC
            LIMIT 1
            """,
            (symbol, window_end),
        )
        if row:
            val = _normalize_global_regime(
                str(row.get("global_regime") or "").strip()
            )
            if val:
                context["market_regime"] = val
    except Exception:
        pass

    # breath_phase and context fields from paper_advice_observation (uses asof_ts_utc)
    try:
        rows = fetch_all(
            conn,
            """
            SELECT asof_ts_utc, advice_state, aplus_phase, aplus_field,
                   aplus_strategic_bias, aplus_expansion_quality,
                   selection_state, selection_bias
            FROM paper_advice_observation
            WHERE symbol = %s
              AND asof_ts_utc >= %s
              AND asof_ts_utc <= %s
            ORDER BY asof_ts_utc DESC
            LIMIT 1
            """,
            (symbol, window_start, window_end),
        )
        if rows:
            r = rows[0]
            # A+ strategic bias as breath proxy
            strat = str(r.get("aplus_strategic_bias") or "").strip()
            if strat and context["breath_phase"] == "UNKNOWN":
                context["breath_phase"] = strat.upper()
    except Exception:
        pass

    # symbol_regime from selection_state.regime_label_4h (uses asset_id)
    if context["symbol_regime"] == "UNKNOWN":
        try:
            asset_row = fetch_one(
                conn,
                "SELECT DISTINCT asset_id FROM paper_advice_observation WHERE symbol = %s LIMIT 1",
                (symbol,),
            )
            if asset_row:
                aid = int(asset_row["asset_id"])
                rows = fetch_all(
                    conn,
                    """
                    SELECT asof_ts_utc, regime_label_1h, regime_label_4h
                    FROM selection_state
                    WHERE asset_id = %s
                      AND asof_ts_utc >= %s
                      AND asof_ts_utc <= %s
                    ORDER BY asof_ts_utc DESC
                    LIMIT 1
                    """,
                    (aid, window_start, window_end),
                )
                if rows:
                    r = rows[0]
                    for k in ("regime_label_4h", "regime_label_1h"):
                        v = str(r.get(k) or "").strip()
                        if v and v.upper() not in ("", "NONE", "NULL"):
                            context["symbol_regime"] = v
                            break
        except Exception:
            pass

    return context


def fetch_context_timeline_raw(
    conn,
    symbol: str,
    venue: str,
    window_start: datetime,
    window_end: datetime,
    interval_code: str = "15m",
) -> ContextTimeline:
    """
    Fetch all context rows for the backtest window from available source tables.
    Returns a ContextTimeline for point-in-time lookup during simulation.
    Extends lookback by 3 days to capture context predating the window start.

    Sources (in priority order for context):
      signal_engine_state              — primary breath/regime proxy (by asset_id)
      regime_selector_backtest_observation_v1 — canonical regime (by symbol)
      paper_advice_observation         — A+ supplementary context (by symbol)
      selection_state                  — symbol_regime via regime_label (by asset_id)
    """
    lookback_start = window_start - timedelta(days=3)

    # Resolve asset_id for tables that use it instead of symbol
    asset_id: Optional[int] = None
    try:
        row = fetch_one(
            conn,
            "SELECT DISTINCT asset_id FROM paper_advice_observation WHERE symbol = %s LIMIT 1",
            (symbol,),
        )
        if row:
            asset_id = int(row["asset_id"])
    except Exception:
        pass

    market_regime_rows: list[dict] = []
    breath_rows: list[dict] = []
    selection_rows: list[dict] = []
    signal_rows: list[dict] = []

    # regime_selector_backtest_observation_v1 — canonical regime source
    try:
        market_regime_rows = fetch_all(
            conn,
            """SELECT asof_ts_utc, global_regime, asset_class_regime, global_class_regime
               FROM regime_selector_backtest_observation_v1
               WHERE symbol = %s AND asof_ts_utc >= %s AND asof_ts_utc <= %s
               ORDER BY asof_ts_utc ASC""",
            (symbol, lookback_start, window_end),
        )
    except Exception:
        pass

    # paper_advice_observation — A+ supplementary context (uses asof_ts_utc)
    try:
        breath_rows = fetch_all(
            conn,
            """SELECT asof_ts_utc, context_ts_utc, symbol, advice_state,
                      aplus_bucket, aplus_phase, aplus_coherence, aplus_field,
                      aplus_strategic_bias, aplus_expansion_quality,
                      selection_state, selection_bias
               FROM paper_advice_observation
               WHERE symbol = %s AND asof_ts_utc >= %s AND asof_ts_utc <= %s
               ORDER BY asof_ts_utc ASC""",
            (symbol, lookback_start, window_end),
        )
    except Exception:
        pass

    # selection_state — symbol_regime via regime_label_4h / regime_label_1h (uses asset_id)
    if asset_id is not None:
        try:
            selection_rows = fetch_all(
                conn,
                """SELECT asof_ts_utc, regime_label_1h, regime_label_4h,
                          selection_state, selection_bias, selection_score
                   FROM selection_state
                   WHERE asset_id = %s AND asof_ts_utc >= %s AND asof_ts_utc <= %s
                   ORDER BY asof_ts_utc ASC""",
                (asset_id, lookback_start, window_end),
            )
        except Exception:
            pass

    # signal_engine_state — primary breath + regime proxy (uses asset_id)
    if asset_id is not None:
        try:
            signal_rows = fetch_all(
                conn,
                """SELECT signal_ts_utc, interval_code, trend_signal, phase_signal,
                          compass_signal, rotation_signal, relative_signal,
                          setup_signal, risk_signal
                   FROM signal_engine_state
                   WHERE asset_id = %s AND signal_ts_utc >= %s AND signal_ts_utc <= %s
                   ORDER BY signal_ts_utc ASC""",
                (asset_id, lookback_start, window_end),
            )
        except Exception:
            pass

    return ContextTimeline(
        market_regime_rows=market_regime_rows,
        breath_rows=breath_rows,
        selection_rows=selection_rows,
        signal_rows=signal_rows,
        interval_code=interval_code,
    )


# ---------------------------------------------------------------------------
# Core backtest logic (pure, no DB)
# ---------------------------------------------------------------------------

def simulate_exact_zone(
    candles: list[Candle],
    prediction_ts: datetime,
    buy_level: Decimal,
    sell_target: Decimal,
    starting_capital: Decimal,
) -> tuple[BacktestResult, list[dict[str, Any]]]:
    """
    Pure simulation — no DB access.

    Returns (partial BacktestResult with trade fields filled, event_rows).
    Caller fills symbol/venue/context fields separately.
    """
    events: list[dict[str, Any]] = []

    # Candles strictly after prediction_ts
    eligible = [c for c in candles if c.open_ts_utc > prediction_ts]

    def _ts(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Locate entry candle
    entry_candle_idx: Optional[int] = None
    entry_candle: Optional[Candle] = None
    for idx, c in enumerate(eligible):
        if c.low_price <= buy_level:
            entry_candle_idx = idx
            entry_candle = c
            events.append({
                "event": "ENTRY_HIT",
                "ts": _ts(c.open_ts_utc),
                "candle_low": str(c.low_price),
                "entry_price": str(buy_level),
            })
            break
        else:
            events.append({
                "event": "ENTRY_MISS",
                "ts": _ts(c.open_ts_utc),
                "candle_low": str(c.low_price),
                "buy_level": str(buy_level),
            })

    # No entry
    if entry_candle is None or entry_candle_idx is None:
        last_close = candles[-1].close_price if candles else None
        last_ts = candles[-1].open_ts_utc if candles else None
        events.append({"event": "NO_ENTRY", "note": "buy_level never touched"})
        result = _empty_result()
        result.entry_hit = False
        result.last_close_price = last_close
        result.last_candle_ts = last_ts
        result.candles_fetched = len(candles)
        result.first_candle_ts = candles[0].open_ts_utc if candles else None
        result.events = events
        return result, events

    # Candles after entry (for exit search and excursion)
    post_entry = eligible[entry_candle_idx + 1:]

    # Locate exit candle (strictly after entry)
    exit_candle: Optional[Candle] = None
    for c in post_entry:
        if c.high_price >= sell_target:
            exit_candle = c
            events.append({
                "event": "TARGET_HIT",
                "ts": _ts(c.open_ts_utc),
                "candle_high": str(c.high_price),
                "sell_target": str(sell_target),
            })
            break
        else:
            events.append({
                "event": "TARGET_MISS",
                "ts": _ts(c.open_ts_utc),
                "candle_high": str(c.high_price),
                "sell_target": str(sell_target),
            })

    # Determine exit price and trade window
    if exit_candle is not None:
        exit_price = sell_target
        target_hit = True
        target_ts = exit_candle.open_ts_utc
        events.append({
            "event": "EXIT",
            "ts": _ts(target_ts),
            "exit_price": str(exit_price),
            "reason": "TARGET_HIT",
        })
        # MAE/MFE: entry candle + post-entry candles up to and including exit candle
        excursion_candles = [entry_candle] + [
            c for c in post_entry if c.open_ts_utc <= exit_candle.open_ts_utc
        ]
    else:
        last_candle = eligible[-1] if eligible else (candles[-1] if candles else None)
        exit_price = last_candle.close_price if last_candle else buy_level
        target_hit = False
        target_ts = None
        events.append({
            "event": "EXIT",
            "ts": _ts(last_candle.open_ts_utc) if last_candle else "N/A",
            "exit_price": str(exit_price),
            "reason": "HORIZON_END_VALUED_AT_CLOSE",
        })
        excursion_candles = [entry_candle] + list(post_entry)

    # Metrics
    gross_return_pct = (exit_price - buy_level) / buy_level * Decimal("100")
    pnl_eur = starting_capital * gross_return_pct / Decimal("100")
    final_value_eur = starting_capital + pnl_eur

    if target_hit and target_ts is not None:
        time_to_target_hours = Decimal(str(
            (target_ts - entry_candle.open_ts_utc).total_seconds() / 3600
        ))
    else:
        time_to_target_hours = None

    # MAE: lowest low of excursion candles relative to entry_price
    if excursion_candles:
        worst_low = min(c.low_price for c in excursion_candles)
        mae_pct = (worst_low - buy_level) / buy_level * Decimal("100")
        best_high = max(c.high_price for c in excursion_candles)
        mfe_pct = (best_high - buy_level) / buy_level * Decimal("100")
    else:
        mae_pct = Decimal("0")
        mfe_pct = Decimal("0")

    # Buy-and-hold return: from entry to final candle in window
    final_window_candle = eligible[-1] if eligible else None
    final_close = final_window_candle.close_price if final_window_candle else buy_level
    bah_return_pct = (final_close - buy_level) / buy_level * Decimal("100")
    improvement_pct = gross_return_pct - bah_return_pct

    last_candle_ts = (eligible[-1].open_ts_utc if eligible else
                      (candles[-1].open_ts_utc if candles else None))

    result = _empty_result()
    result.entry_hit = True
    result.entry_ts = entry_candle.open_ts_utc
    result.entry_price = buy_level
    result.target_hit = target_hit
    result.target_ts = target_ts
    result.exit_price = exit_price
    result.gross_return_pct = gross_return_pct
    result.pnl_eur = pnl_eur
    result.time_to_target_hours = time_to_target_hours
    result.maximum_adverse_excursion_pct = mae_pct
    result.maximum_favorable_excursion_pct = mfe_pct
    result.final_value_eur = final_value_eur
    result.buy_and_hold_return_from_entry_to_end = bah_return_pct
    result.improvement_vs_buy_and_hold = improvement_pct
    result.last_close_price = final_close
    result.last_candle_ts = last_candle_ts
    result.candles_fetched = len(candles)
    result.first_candle_ts = candles[0].open_ts_utc if candles else None
    result.events = events
    return result, events


def _empty_result() -> BacktestResult:
    return BacktestResult(
        symbol="", quote="", venue="", interval_code="",
        horizon_days=0, buy_level=Decimal("0"), sell_target=Decimal("0"),
        starting_capital=Decimal("0"),
        prediction_ts=datetime(2000, 1, 1, tzinfo=UTC),
        prediction_timestamp_status="",
        window_start_ts=datetime(2000, 1, 1, tzinfo=UTC),
        window_end_ts=datetime(2000, 1, 1, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Variant simulation — multi-tranche, reserve-policy aware
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SellTranche:
    """Single sell level: sell sell_pct% of starting_capital when price hits target_price."""
    sell_pct: Decimal
    target_price: Decimal


@dataclass(frozen=True)
class VariantSpec:
    """
    Complete specification for one reserve-policy variant.

    All policy fields are pre-resolved; simulate_variant() is pure.
    tranche sell_pct values must sum <= max_sell_pct_allowed.
    """
    variant_id: str
    label: str
    tp_scope: str
    active_long_reserve_pct: Decimal
    max_short_swing_sell_pct: Decimal
    max_sell_pct_allowed: Decimal
    allow_parent_tf_full_exit: bool
    reserve_source: str
    tranches: list[SellTranche]
    parent_tf_target_status: str
    variant_type: str = VARIANT_TYPE_STANDARD

    def __post_init__(self) -> None:
        total = sum(t.sell_pct for t in self.tranches)
        if total > self.max_sell_pct_allowed + Decimal("0.001"):
            raise ValueError(
                f"VariantSpec {self.variant_id}: tranche total {total}% "
                f"exceeds max_sell_pct_allowed {self.max_sell_pct_allowed}%"
            )


@dataclass
class VariantResult:
    variant_id: str
    label: str
    active_long_reserve_pct: Decimal
    reserve_source: str
    tp_scope: str
    max_short_swing_sell_pct: Decimal
    max_sell_pct_allowed: Decimal
    parent_tf_target_status: str
    entry_hit: bool
    target_hits: list[str]
    gross_return_pct: Optional[Decimal]
    pnl_eur: Optional[Decimal]
    final_value_eur: Optional[Decimal]
    realized_pnl_eur: Optional[Decimal]
    unrealized_pnl_eur: Optional[Decimal]
    short_swing_sold_pct: Decimal
    long_runner_remaining_pct: Decimal
    maximum_adverse_excursion_pct: Optional[Decimal]
    maximum_favorable_excursion_pct: Optional[Decimal]
    buy_and_hold_return_from_entry_to_end: Optional[Decimal]
    improvement_vs_buy_and_hold: Optional[Decimal]
    # Continuation gate fields — None for STANDARD variants
    live_valid: Optional[bool] = None
    continuation_gate_state: Optional[str] = None
    continuation_gate_reason: Optional[str] = None
    breath_phase_at_target: Optional[str] = None
    breath_alignment_at_target: Optional[str] = None
    market_regime_at_target: Optional[str] = None
    symbol_regime_at_target: Optional[str] = None
    context_quality_tier_at_target: Optional[str] = None
    sell_reduction_reason: Optional[str] = None
    target_shift_reason: Optional[str] = None
    runner_hold_reason: Optional[str] = None
    overshoot_pct_at_t1: Optional[Decimal] = None
    close_vs_target_pct_at_t1: Optional[Decimal] = None
    # Context lookup audit fields
    context_lookup_status: Optional[str] = None
    context_source: Optional[str] = None
    context_ts_utc: Optional[datetime] = None
    context_age_minutes: Optional[float] = None
    max_context_age_minutes: Optional[int] = None
    context_freshness_status: Optional[str] = None
    gate_applied: Optional[bool] = None
    fallback_policy: Optional[str] = None
    fallback_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Context timeline — point-in-time context for continuation gate (no future leakage)
# ---------------------------------------------------------------------------

def _latest_before(rows: list[dict], ts: datetime, ts_key: str) -> Optional[dict]:
    """Return the latest row where row[ts_key] <= ts. Rows must be sorted ascending by ts_key."""
    result = None
    for row in rows:
        row_ts = row.get(ts_key)
        if row_ts is None:
            continue
        if isinstance(row_ts, str):
            row_ts = datetime.fromisoformat(row_ts.replace("Z", "+00:00"))
        if isinstance(row_ts, datetime) and row_ts.tzinfo is None:
            row_ts = row_ts.replace(tzinfo=UTC)
        if row_ts <= ts:
            result = row
        else:
            break
    return result


def _normalize_phase_signal(v: str) -> str:
    """Map signal_engine_state phase_signal to gate-compatible breath_phase label."""
    u = v.upper()
    for term, mapped in [
        ("EXPANSION", "EXPANSION"), ("IMPULSE", "IMPULSE"),
        ("ACCUMULATION", "ACCUMULATION"), ("DISTRIBUTION", "DISTRIBUTION"),
        ("CONTRACTION", "CONTRACTION"), ("CORRECTION", "CORRECTION"),
        ("REVERSAL", "REVERSAL"), ("MARKDOWN", "MARKDOWN"), ("MARKUP", "MARKUP"),
        ("MOMENTUM", "MOMENTUM"), ("TREND", "TRENDING"),
    ]:
        if term in u:
            return mapped
    return v


def _normalize_compass_signal(v: str) -> str:
    """Map signal_engine_state compass_signal to gate-compatible breath_alignment label."""
    u = v.upper()
    for term, mapped in [
        ("SUPPORT", "SUPPORTIVE"), ("WEAK", "WEAK"),
        ("CONFLICT", "CONFLICTING"), ("BULL", "BULLISH"),
        ("BEAR", "BEARISH"), ("ALIGN", "ALIGNED"),
    ]:
        if term in u:
            return mapped
    return v


def _normalize_trend_signal(v: str) -> str:
    """Map signal_engine_state trend_signal to gate-compatible market_regime label."""
    u = v.upper()
    if "UP" in u and "TREND" in u:
        return "TRENDING_UP"
    if "DOWN" in u and "TREND" in u:
        return "TRENDING_DOWN"
    if "BULL" in u:
        return "BULLISH"
    if "BEAR" in u:
        return "BEARISH"
    if "NEUTRAL" in u:
        return "NEUTRAL"
    return v


def _normalize_global_regime(v: str) -> str:
    """Map regime_selector_backtest_observation_v1 global_regime to gate-compatible label."""
    u = v.upper()
    if "RISK_ON" in u:
        return "RISK_ON"
    if "RISK_OFF" in u:
        return "RISK_OFF"
    if "BREAKDOWN" in u:
        return "BREAKDOWN"
    if "BULL" in u:
        return "BULLISH"
    if "BEAR" in u:
        return "BEARISH"
    if "NEUTRAL" in u:
        return "NEUTRAL"
    return v


def _get_row_ts(row: dict, ts_key: str) -> Optional[datetime]:
    """Extract and timezone-normalise a datetime from a row dict."""
    v = row.get(ts_key)
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if isinstance(v, datetime) and v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v


@dataclass(frozen=True)
class ContextLookupAudit:
    """Audit record for one context lookup at a specific decision timestamp."""
    context_lookup_status: str      # FOUND / SOURCE_MISSING / ASOF_JOIN_MISS / CONTEXT_TOO_STALE / ...
    context_source: str             # e.g. "signal_engine_state+selection_state"
    context_ts_utc: Optional[datetime]
    context_age_minutes: Optional[float]
    max_context_age_minutes: int
    context_freshness_status: str   # FRESH / ACCEPTABLE / STALE / UNKNOWN
    source_refs: str
    gate_applied: bool
    fallback_policy: Optional[str]
    fallback_reason: Optional[str]


@dataclass
class ContextTimeline:
    """
    Pre-fetched context snapshots for a backtest window.
    at(ts) / at_with_audit(ts) merge fields from all sources using only rows
    with asof/signal_ts <= ts — no future leakage.

    Sources:
      market_regime_rows: regime_selector_backtest_observation_v1 (asof_ts_utc)
      breath_rows:        paper_advice_observation (asof_ts_utc)
      selection_rows:     selection_state (asof_ts_utc)
      signal_rows:        signal_engine_state (signal_ts_utc) — primary breath/regime proxy
    """
    market_regime_rows: list[dict]
    breath_rows: list[dict]
    selection_rows: list[dict]
    signal_rows: list[dict] = field(default_factory=list)
    interval_code: str = "15m"

    def _build_ctx(
        self, ts: datetime
    ) -> tuple[dict[str, str], list[str], Optional[datetime], bool]:
        """Return (ctx_dict, sources_found, latest_fresh_ts, any_row_before_ts_found)."""
        ctx: dict[str, str] = {
            "market_regime": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "context_quality_tier": "UNKNOWN",
        }
        max_staleness = _INTERVAL_MAX_STALENESS_MINUTES.get(
            self.interval_code, _DEFAULT_MAX_STALENESS_MINUTES
        )
        sources_found: list[str] = []
        latest_ts: Optional[datetime] = None
        any_row_before_ts = False  # True if any row <= ts exists (even if stale)

        def _age_ok(row_ts: datetime) -> bool:
            return (ts - row_ts).total_seconds() / 60 <= max_staleness

        def _update_latest(row_ts: datetime) -> None:
            nonlocal latest_ts
            if latest_ts is None or row_ts > latest_ts:
                latest_ts = row_ts

        # 1. signal_engine_state — primary breath + market_regime proxy
        sig_row = _latest_before(self.signal_rows, ts, "signal_ts_utc")
        if sig_row:
            sig_ts = _get_row_ts(sig_row, "signal_ts_utc")
            if sig_ts is not None:
                any_row_before_ts = True
                if _age_ok(sig_ts):
                    sources_found.append("signal_engine_state")
                    _update_latest(sig_ts)
                    phase = str(sig_row.get("phase_signal") or "").strip()
                    compass = str(sig_row.get("compass_signal") or "").strip()
                    trend = str(sig_row.get("trend_signal") or "").strip()
                    if phase and ctx["breath_phase"] == "UNKNOWN":
                        ctx["breath_phase"] = _normalize_phase_signal(phase)
                    if compass and ctx["breath_alignment"] == "UNKNOWN":
                        ctx["breath_alignment"] = _normalize_compass_signal(compass)
                    if trend and ctx["market_regime"] == "UNKNOWN":
                        ctx["market_regime"] = _normalize_trend_signal(trend)

        # 2. regime_selector_backtest_observation_v1 — canonical regime (overrides proxy)
        reg_row = _latest_before(self.market_regime_rows, ts, "asof_ts_utc")
        if reg_row:
            reg_ts = _get_row_ts(reg_row, "asof_ts_utc")
            if reg_ts is not None:
                any_row_before_ts = True
                if _age_ok(reg_ts):
                    sources_found.append("regime_selector_backtest_observation_v1")
                    _update_latest(reg_ts)
                    gtr = str(
                        reg_row.get("global_regime")
                        or reg_row.get("market_regime")
                        or reg_row.get("regime") or ""
                    ).strip()
                    if gtr:
                        ctx["market_regime"] = _normalize_global_regime(gtr)

        # 3. selection_state — symbol_regime from regime_label_4h / regime_label_1h
        sel_row = _latest_before(self.selection_rows, ts, "asof_ts_utc")
        if sel_row:
            sel_ts = _get_row_ts(sel_row, "asof_ts_utc")
            if sel_ts is not None:
                any_row_before_ts = True
                if _age_ok(sel_ts):
                    sources_found.append("selection_state")
                    _update_latest(sel_ts)
                    for k in ("regime_label_4h", "regime_label_1h", "symbol_regime", "regime"):
                        v = str(sel_row.get(k) or "").strip()
                        if v and v.upper() not in ("", "NONE", "NULL") and ctx["symbol_regime"] == "UNKNOWN":
                            ctx["symbol_regime"] = v

        # 4. paper_advice_observation — supplementary A+ context
        br_row = _latest_before(self.breath_rows, ts, "asof_ts_utc")
        if br_row:
            br_ts = _get_row_ts(br_row, "asof_ts_utc")
            if br_ts is not None:
                any_row_before_ts = True
                if _age_ok(br_ts):
                    if "paper_advice_observation" not in sources_found:
                        sources_found.append("paper_advice_observation")
                    _update_latest(br_ts)
                    for src_key, dst_key in [
                        ("market_breath_phase", "breath_phase"),
                        ("breath_phase", "breath_phase"),
                        ("breath_alignment", "breath_alignment"),
                        ("context_quality_tier", "context_quality_tier"),
                        ("symbol_regime", "symbol_regime"),
                    ]:
                        v = str(br_row.get(src_key) or "").strip()
                        if v and v.upper() not in ("", "NONE", "NULL") and ctx[dst_key] == "UNKNOWN":
                            ctx[dst_key] = v
                    # A+ strategic bias as breath_phase fallback
                    if ctx["breath_phase"] == "UNKNOWN":
                        strat = str(br_row.get("aplus_strategic_bias") or "").strip()
                        if strat:
                            ctx["breath_phase"] = strat.upper()

        return ctx, sources_found, latest_ts, any_row_before_ts

    def at(self, ts: datetime) -> dict[str, str]:
        ctx, _, _, _ = self._build_ctx(ts)
        return ctx

    def at_with_audit(self, ts: datetime) -> tuple[dict[str, str], ContextLookupAudit]:
        max_staleness = _INTERVAL_MAX_STALENESS_MINUTES.get(
            self.interval_code, _DEFAULT_MAX_STALENESS_MINUTES
        )
        ctx, sources_found, latest_ts, any_row_before_ts = self._build_ctx(ts)

        has_any_rows = bool(
            self.signal_rows or self.market_regime_rows
            or self.selection_rows or self.breath_rows
        )

        if latest_ts is None:
            if not has_any_rows:
                lookup_status = CTX_SOURCE_MISSING
                fallback_reason = "no_rows_in_timeline"
            elif any_row_before_ts:
                # Rows exist before ts but all were too stale
                lookup_status = CTX_CONTEXT_TOO_STALE
                fallback_reason = "all_rows_exceed_staleness_threshold"
            else:
                # Rows exist but none are at or before ts
                lookup_status = CTX_ASOF_JOIN_MISS
                fallback_reason = "no_rows_at_or_before_decision_ts"
            freshness = "UNKNOWN"
            age_minutes = None
            gate_applied = False
        else:
            age_minutes = round((ts - latest_ts).total_seconds() / 60, 1)
            if not sources_found:
                lookup_status = CTX_CONTEXT_TOO_STALE
                freshness = "STALE"
                gate_applied = False
                fallback_reason = f"age_min={age_minutes} threshold={max_staleness}"
            else:
                lookup_status = CTX_FOUND
                if age_minutes <= max_staleness * 0.5:
                    freshness = "FRESH"
                else:
                    freshness = "ACCEPTABLE"
                gate_applied = True
                fallback_reason = None

        audit = ContextLookupAudit(
            context_lookup_status=lookup_status,
            context_source="+".join(sources_found) if sources_found else "NONE",
            context_ts_utc=latest_ts,
            context_age_minutes=age_minutes,
            max_context_age_minutes=max_staleness,
            context_freshness_status=freshness,
            source_refs=(
                f"signal_rows={len(self.signal_rows)} "
                f"regime_rows={len(self.market_regime_rows)} "
                f"selection_rows={len(self.selection_rows)} "
                f"breath_rows={len(self.breath_rows)}"
            ),
            gate_applied=gate_applied,
            fallback_policy=None if gate_applied else "C1_BASELINE",
            fallback_reason=fallback_reason,
        )
        return ctx, audit


def _empty_context_timeline() -> ContextTimeline:
    return ContextTimeline(
        market_regime_rows=[], breath_rows=[], selection_rows=[],
        signal_rows=[], interval_code="15m",
    )


@dataclass(frozen=True)
class ContinuationGateResult:
    gate_state: str
    gate_reason: str
    breath_phase: str
    breath_alignment: str
    market_regime: str
    symbol_regime: str
    context_quality_tier: str
    overshoot_pct: Optional[Decimal]
    close_vs_target_pct: Optional[Decimal]


def evaluate_continuation_gate(
    ctx: dict[str, str],
    touch_candle: Optional[Candle],
    target_price: Decimal,
) -> ContinuationGateResult:
    """
    Pure. No DB. No future leakage.
    Uses only point-in-time context and the touch candle's OHLC at the decision timestamp.

    Gate priority (highest overrides lower):
      REGIME_CONFLICT > BREATH_CONFLICT > CONTEXT_UNKNOWN >
      CONTINUATION_WEAK > CONTINUATION_SUPPORTED
    """
    market_regime = ctx.get("market_regime", "UNKNOWN")
    symbol_regime = ctx.get("symbol_regime", "UNKNOWN")
    breath_phase = ctx.get("breath_phase", "UNKNOWN")
    breath_alignment = ctx.get("breath_alignment", "UNKNOWN")
    context_quality_tier = ctx.get("context_quality_tier", "UNKNOWN")

    overshoot_pct: Optional[Decimal] = None
    close_vs_target_pct: Optional[Decimal] = None
    if touch_candle is not None and target_price > 0:
        overshoot_pct = (touch_candle.high_price - target_price) / target_price * Decimal("100")
        close_vs_target_pct = (touch_candle.close_price - target_price) / target_price * Decimal("100")

    def _mk(state: str, reason: str) -> ContinuationGateResult:
        return ContinuationGateResult(
            gate_state=state, gate_reason=reason,
            breath_phase=breath_phase, breath_alignment=breath_alignment,
            market_regime=market_regime, symbol_regime=symbol_regime,
            context_quality_tier=context_quality_tier,
            overshoot_pct=overshoot_pct, close_vs_target_pct=close_vs_target_pct,
        )

    mr_up = market_regime.upper()
    sr_up = symbol_regime.upper()
    bp_up = breath_phase.upper()
    ba_up = breath_alignment.upper()

    if mr_up in _NEGATIVE_REGIMES or sr_up in _NEGATIVE_REGIMES:
        return _mk(GATE_REGIME_CONFLICT,
                   f"market_regime={market_regime} symbol_regime={symbol_regime}")

    if bp_up in _NEGATIVE_BREATH_PHASES or ba_up in _NEGATIVE_BREATH_ALIGNMENTS:
        return _mk(GATE_BREATH_CONFLICT,
                   f"breath_phase={breath_phase} breath_alignment={breath_alignment}")

    if all(v == "UNKNOWN" for v in [market_regime, symbol_regime, breath_phase, breath_alignment]):
        return _mk(GATE_CONTEXT_UNKNOWN, "all_context_fields_unknown")

    positive_regime = mr_up in _POSITIVE_REGIMES or sr_up in _POSITIVE_REGIMES
    positive_breath = bp_up in _POSITIVE_BREATH_PHASES
    positive_alignment = ba_up in _POSITIVE_BREATH_ALIGNMENTS
    close_above = close_vs_target_pct is not None and close_vs_target_pct > Decimal("0")

    if positive_regime and positive_breath and positive_alignment and close_above:
        ctp = f"{close_vs_target_pct:.2f}%" if close_vs_target_pct is not None else "n/a"
        return _mk(GATE_CONTINUATION_SUPPORTED,
                   f"regime={market_regime} breath={breath_phase} "
                   f"alignment={breath_alignment} close_above_target={ctp}")

    return _mk(GATE_CONTINUATION_WEAK,
               f"partial_context regime={market_regime} breath={breath_phase} "
               f"alignment={breath_alignment}")


# ---------------------------------------------------------------------------
# Pre-configured NEAR variants
NEAR_VARIANTS: list[VariantSpec] = [
    VariantSpec(
        variant_id="A_FULL_EXIT_BENCHMARK",
        label="BENCHMARK_ONLY_NOT_LIVE_POLICY",
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
        active_long_reserve_pct=Decimal("0"),
        max_short_swing_sell_pct=Decimal("100"),
        max_sell_pct_allowed=Decimal("100"),
        allow_parent_tf_full_exit=False,
        reserve_source="NONE_BENCHMARK",
        tranches=[SellTranche(sell_pct=Decimal("100"), target_price=Decimal("2.12"))],
        parent_tf_target_status="N/A",
    ),
    VariantSpec(
        variant_id="B_MAX_50_FIRST_TARGET",
        label="B_MAX_50_FIRST_TARGET",
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
        active_long_reserve_pct=Decimal("50"),
        max_short_swing_sell_pct=Decimal("50"),
        max_sell_pct_allowed=Decimal("50"),
        allow_parent_tf_full_exit=False,
        reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
        tranches=[SellTranche(sell_pct=Decimal("50"), target_price=Decimal("2.12"))],
        parent_tf_target_status="N/A",
    ),
    VariantSpec(
        variant_id="C_20_15_15_RUNNER",
        label="C_20_15_15_RUNNER",
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
        active_long_reserve_pct=Decimal("50"),
        max_short_swing_sell_pct=Decimal("50"),
        max_sell_pct_allowed=Decimal("50"),
        allow_parent_tf_full_exit=False,
        reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
        tranches=[
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.35")),
        ],
        parent_tf_target_status="N/A",
    ),
    VariantSpec(
        variant_id="D_PARENT_TF_FULL_EXIT_BENCHMARK",
        label="LIVE_VALID_ONLY_IF_PARENT_TF_TARGET_CONFIRMED",
        tp_scope=TP_SCOPE_PARENT_TF_FULL,
        active_long_reserve_pct=Decimal("50"),
        max_short_swing_sell_pct=Decimal("50"),
        max_sell_pct_allowed=Decimal("100"),
        allow_parent_tf_full_exit=True,
        reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
        tranches=[SellTranche(sell_pct=Decimal("100"), target_price=Decimal("2.12"))],
        parent_tf_target_status="UNKNOWN",
    ),
]

# Continuation-aware variants — breath/regime gate at each decision point.
# All 5 use NEAR baseline parameters. Numerical results differ only when
# context is available and continuation gate fires. With CONTEXT_UNKNOWN
# (no matching DB rows), C1-C4 fall back to baseline C behavior; C5 is
# marked NOT_LIVE_VALID because parent_tf_target_status=UNKNOWN.
NEAR_CONTINUATION_VARIANTS: list[VariantSpec] = [
    VariantSpec(
        variant_id="C1_BASELINE_20_15_15_RUNNER",
        label="C_BASELINE_NO_GATE",
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
        active_long_reserve_pct=Decimal("50"),
        max_short_swing_sell_pct=Decimal("50"),
        max_sell_pct_allowed=Decimal("50"),
        allow_parent_tf_full_exit=False,
        reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
        tranches=[
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.35")),
        ],
        parent_tf_target_status="N/A",
        variant_type=VARIANT_TYPE_BASELINE,
    ),
    VariantSpec(
        variant_id="C2_BREATH_HOLD_FIRST_TARGET",
        label="C_BREATH_HOLD_REDUCE_T1_ON_CONTINUATION",
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
        active_long_reserve_pct=Decimal("50"),
        max_short_swing_sell_pct=Decimal("50"),
        max_sell_pct_allowed=Decimal("50"),
        allow_parent_tf_full_exit=False,
        reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
        tranches=[
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.35")),
        ],
        parent_tf_target_status="N/A",
        variant_type=VARIANT_TYPE_BREATH_HOLD,
    ),
    VariantSpec(
        variant_id="C3_REGIME_TARGET_SHIFT",
        label="C_REGIME_SHIFT_LADDER_UP_ON_CONTINUATION",
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
        active_long_reserve_pct=Decimal("50"),
        max_short_swing_sell_pct=Decimal("50"),
        max_sell_pct_allowed=Decimal("50"),
        allow_parent_tf_full_exit=False,
        reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
        tranches=[
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.35")),
        ],
        parent_tf_target_status="N/A",
        variant_type=VARIANT_TYPE_REGIME_SHIFT,
    ),
    VariantSpec(
        variant_id="C4_BREATH_TRAILING_RUNNER",
        label="C_BREATH_TRAILING_RUNNER_HOLD_ON_CONTINUATION",
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
        active_long_reserve_pct=Decimal("50"),
        max_short_swing_sell_pct=Decimal("50"),
        max_sell_pct_allowed=Decimal("50"),
        allow_parent_tf_full_exit=False,
        reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
        tranches=[
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.35")),
        ],
        parent_tf_target_status="N/A",
        variant_type=VARIANT_TYPE_TRAILING_RUNNER,
    ),
    VariantSpec(
        variant_id="C5_PARENT_CONTEXT_RUNNER",
        label="C_PARENT_CONTEXT_RUNNER_NOT_LIVE_VALID_IF_UNKNOWN",
        tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
        active_long_reserve_pct=Decimal("50"),
        max_short_swing_sell_pct=Decimal("50"),
        max_sell_pct_allowed=Decimal("50"),
        allow_parent_tf_full_exit=False,
        reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
        tranches=[
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.35")),
        ],
        parent_tf_target_status="UNKNOWN",
        variant_type=VARIANT_TYPE_PARENT_CONTEXT,
    ),
]


def simulate_variant(
    candles: list[Candle],
    prediction_ts: datetime,
    buy_level: Decimal,
    starting_capital: Decimal,
    spec: VariantSpec,
) -> VariantResult:
    """
    Pure variant simulation — no DB access.

    Tranche search: each tranche is triggered by the first candle strictly after
    the previous tranche's hit candle (or the entry candle for the first tranche)
    where candle.high >= tranche.target_price.

    P&L:
      realized_pnl = sum of hit tranches: capital * sell_pct/100 * (target - buy) / buy
      unrealized_pnl = remaining fraction * (final_close - buy) / buy * capital
      final_value_eur = starting_capital + realized_pnl + unrealized_pnl
    """
    _HUNDRED = Decimal("100")
    _ZERO = Decimal("0")

    eligible = [c for c in candles if c.open_ts_utc > prediction_ts]

    # Find entry
    entry_candle: Optional[Candle] = None
    entry_idx: int = -1
    for idx, c in enumerate(eligible):
        if c.low_price <= buy_level:
            entry_candle = c
            entry_idx = idx
            break

    if entry_candle is None:
        final_close = eligible[-1].close_price if eligible else (candles[-1].close_price if candles else buy_level)
        bah = (final_close - buy_level) / buy_level * _HUNDRED if buy_level > 0 else _ZERO
        return VariantResult(
            variant_id=spec.variant_id,
            label=spec.label,
            active_long_reserve_pct=spec.active_long_reserve_pct,
            reserve_source=spec.reserve_source,
            tp_scope=spec.tp_scope,
            max_short_swing_sell_pct=spec.max_short_swing_sell_pct,
            max_sell_pct_allowed=spec.max_sell_pct_allowed,
            parent_tf_target_status=spec.parent_tf_target_status,
            entry_hit=False,
            target_hits=[],
            gross_return_pct=None,
            pnl_eur=None,
            final_value_eur=None,
            realized_pnl_eur=None,
            unrealized_pnl_eur=None,
            short_swing_sold_pct=_ZERO,
            long_runner_remaining_pct=_HUNDRED,
            maximum_adverse_excursion_pct=None,
            maximum_favorable_excursion_pct=None,
            buy_and_hold_return_from_entry_to_end=bah,
            improvement_vs_buy_and_hold=None,
        )

    post_entry = eligible[entry_idx + 1:]

    # Simulate tranches sequentially
    realized_pnl = _ZERO
    total_sold_pct = _ZERO
    target_hits: list[str] = []
    search_from: int = 0  # index into post_entry

    for tranche in spec.tranches:
        hit_candle: Optional[Candle] = None
        for j in range(search_from, len(post_entry)):
            if post_entry[j].high_price >= tranche.target_price:
                hit_candle = post_entry[j]
                search_from = j + 1
                break

        if hit_candle is not None:
            tranche_capital = starting_capital * tranche.sell_pct / _HUNDRED
            tranche_return = (tranche.target_price - buy_level) / buy_level
            realized_pnl += tranche_capital * tranche_return
            total_sold_pct += tranche.sell_pct
            target_hits.append(str(tranche.target_price))
        else:
            # Target not hit — stop searching further tranches (ascending targets)
            break

    # Remaining fraction valued at final window close
    remaining_pct = _HUNDRED - total_sold_pct
    final_window_candle = eligible[-1] if eligible else None
    final_close = final_window_candle.close_price if final_window_candle else buy_level
    remaining_capital = starting_capital * remaining_pct / _HUNDRED
    unrealized_pnl = remaining_capital * (final_close - buy_level) / buy_level

    total_pnl = realized_pnl + unrealized_pnl
    gross_return_pct = total_pnl / starting_capital * _HUNDRED
    final_value_eur = starting_capital + total_pnl

    bah_return_pct = (final_close - buy_level) / buy_level * _HUNDRED
    improvement_pct = gross_return_pct - bah_return_pct

    # MAE / MFE over entire hold window (entry to end of window)
    excursion_candles = [entry_candle] + list(post_entry)
    worst_low = min(c.low_price for c in excursion_candles)
    best_high = max(c.high_price for c in excursion_candles)
    mae_pct = (worst_low - buy_level) / buy_level * _HUNDRED
    mfe_pct = (best_high - buy_level) / buy_level * _HUNDRED

    return VariantResult(
        variant_id=spec.variant_id,
        label=spec.label,
        active_long_reserve_pct=spec.active_long_reserve_pct,
        reserve_source=spec.reserve_source,
        tp_scope=spec.tp_scope,
        max_short_swing_sell_pct=spec.max_short_swing_sell_pct,
        max_sell_pct_allowed=spec.max_sell_pct_allowed,
        parent_tf_target_status=spec.parent_tf_target_status,
        entry_hit=True,
        target_hits=target_hits,
        gross_return_pct=gross_return_pct,
        pnl_eur=total_pnl,
        final_value_eur=final_value_eur,
        realized_pnl_eur=realized_pnl,
        unrealized_pnl_eur=unrealized_pnl,
        short_swing_sold_pct=total_sold_pct,
        long_runner_remaining_pct=remaining_pct,
        maximum_adverse_excursion_pct=mae_pct,
        maximum_favorable_excursion_pct=mfe_pct,
        buy_and_hold_return_from_entry_to_end=bah_return_pct,
        improvement_vs_buy_and_hold=improvement_pct,
    )


def run_all_variants(
    candles: list[Candle],
    prediction_ts: datetime,
    buy_level: Decimal,
    starting_capital: Decimal,
    variants: list[VariantSpec],
) -> list[VariantResult]:
    return [
        simulate_variant(candles, prediction_ts, buy_level, starting_capital, spec)
        for spec in variants
    ]


# ---------------------------------------------------------------------------
# Continuation-aware variant simulation (pure, no DB, no future leakage)
# ---------------------------------------------------------------------------

def simulate_continuation_variant(
    candles: list[Candle],
    prediction_ts: datetime,
    buy_level: Decimal,
    starting_capital: Decimal,
    spec: VariantSpec,
    context_timeline: ContextTimeline,
) -> VariantResult:
    """
    Continuation-aware variant simulation. Pure — no DB. No future leakage.
    Context is resolved at each decision point using context_timeline.at(event_ts).

    variant_type behavior:
      BASELINE:         baseline sell; gate fields set to BASELINE_NOT_GATED.
      BREATH_HOLD:      reduce first tranche sell_pct by 50% when CONTINUATION_SUPPORTED.
      REGIME_SHIFT:     shift sell ladder to [2.25, 2.35, 2.43] when CONTINUATION_SUPPORTED.
      TRAILING_RUNNER:  cancel further tranches on REGIME_CONFLICT or BREATH_CONFLICT.
      PARENT_CONTEXT:   simulate baseline; live_valid=False when parent_tf_status=UNKNOWN.
      STANDARD:         baseline sell (same as simulate_variant); no gate fields set.
    """
    _HUNDRED = Decimal("100")
    _ZERO = Decimal("0")
    variant_type = spec.variant_type

    eligible = [c for c in candles if c.open_ts_utc > prediction_ts]

    entry_candle: Optional[Candle] = None
    entry_idx: int = -1
    for idx, c in enumerate(eligible):
        if c.low_price <= buy_level:
            entry_candle = c
            entry_idx = idx
            break

    final_close_fallback = (
        eligible[-1].close_price if eligible else
        (candles[-1].close_price if candles else buy_level)
    )
    bah_fallback = (final_close_fallback - buy_level) / buy_level * _HUNDRED

    if entry_candle is None:
        is_ptf_no_entry = (variant_type == VARIANT_TYPE_PARENT_CONTEXT
                           and spec.parent_tf_target_status == "UNKNOWN")
        return VariantResult(
            variant_id=spec.variant_id, label=spec.label,
            active_long_reserve_pct=spec.active_long_reserve_pct,
            reserve_source=spec.reserve_source, tp_scope=spec.tp_scope,
            max_short_swing_sell_pct=spec.max_short_swing_sell_pct,
            max_sell_pct_allowed=spec.max_sell_pct_allowed,
            parent_tf_target_status=spec.parent_tf_target_status,
            entry_hit=False, target_hits=[],
            gross_return_pct=None, pnl_eur=None, final_value_eur=None,
            realized_pnl_eur=None, unrealized_pnl_eur=None,
            short_swing_sold_pct=_ZERO, long_runner_remaining_pct=_HUNDRED,
            maximum_adverse_excursion_pct=None, maximum_favorable_excursion_pct=None,
            buy_and_hold_return_from_entry_to_end=bah_fallback,
            improvement_vs_buy_and_hold=None,
            live_valid=not is_ptf_no_entry,
            continuation_gate_state=GATE_NOT_LIVE_VALID if is_ptf_no_entry else None,
            continuation_gate_reason="parent_tf_target_status=UNKNOWN" if is_ptf_no_entry else None,
            breath_phase_at_target="UNKNOWN" if is_ptf_no_entry else None,
            breath_alignment_at_target="UNKNOWN" if is_ptf_no_entry else None,
            market_regime_at_target="UNKNOWN" if is_ptf_no_entry else None,
            symbol_regime_at_target="UNKNOWN" if is_ptf_no_entry else None,
            context_quality_tier_at_target="UNKNOWN" if is_ptf_no_entry else None,
        )

    post_entry = eligible[entry_idx + 1:]

    # Locate T1 touch candle to get decision-point timestamp for gate evaluation
    t1_target_price = spec.tranches[0].target_price if spec.tranches else buy_level
    t1_touch_candle: Optional[Candle] = None
    for c in post_entry:
        if c.high_price >= t1_target_price:
            t1_touch_candle = c
            break

    gate_ts = (
        t1_touch_candle.open_ts_utc if t1_touch_candle is not None
        else (eligible[-1].open_ts_utc if eligible else prediction_ts)
    )
    ctx_at_gate, ctx_audit = context_timeline.at_with_audit(gate_ts)
    gate = evaluate_continuation_gate(ctx_at_gate, t1_touch_candle, t1_target_price)

    # Resolve effective tranches based on variant_type and gate state
    effective_tranches = list(spec.tranches)
    sell_red: Optional[str] = None
    tgt_shift: Optional[str] = None
    run_hold: Optional[str] = None
    is_ptf = (variant_type == VARIANT_TYPE_PARENT_CONTEXT
               and spec.parent_tf_target_status == "UNKNOWN")

    if variant_type in (VARIANT_TYPE_STANDARD, VARIANT_TYPE_BASELINE):
        sell_red = "BASELINE_NOT_GATED"

    elif variant_type == VARIANT_TYPE_BREATH_HOLD:
        if gate.gate_state == GATE_CONTINUATION_SUPPORTED and effective_tranches:
            first = effective_tranches[0]
            reduced = max(first.sell_pct / Decimal("2"), Decimal("5"))
            effective_tranches = (
                [SellTranche(sell_pct=reduced, target_price=first.target_price)]
                + effective_tranches[1:]
            )
            sell_red = f"REDUCED_T1 gate={gate.gate_state} from={first.sell_pct}% to={reduced}%"
        else:
            sell_red = f"BASELINE_FALLBACK gate={gate.gate_state}"

    elif variant_type == VARIANT_TYPE_REGIME_SHIFT:
        if gate.gate_state == GATE_CONTINUATION_SUPPORTED and effective_tranches:
            shifted_prices = [Decimal("2.25"), Decimal("2.35"), Decimal("2.43")]
            effective_tranches = [
                SellTranche(
                    sell_pct=t.sell_pct,
                    target_price=shifted_prices[i] if i < len(shifted_prices) else t.target_price,
                )
                for i, t in enumerate(effective_tranches)
            ]
            tgt_shift = f"LADDER_UP gate={gate.gate_state} original_t1={t1_target_price}"
        else:
            tgt_shift = f"NO_SHIFT gate={gate.gate_state}"

    elif variant_type == VARIANT_TYPE_TRAILING_RUNNER:
        if gate.gate_state in (GATE_REGIME_CONFLICT, GATE_BREATH_CONFLICT):
            if effective_tranches:
                effective_tranches = [effective_tranches[0]]
            run_hold = f"EARLY_STOP gate={gate.gate_state} further_tranches_cancelled"
        elif gate.gate_state == GATE_CONTINUATION_SUPPORTED:
            run_hold = f"RUNNER_HELD gate={gate.gate_state} continuation_confirmed"
        else:
            run_hold = f"RUNNER_HELD_NO_EXIT_SIGNAL gate={gate.gate_state}"

    elif variant_type == VARIANT_TYPE_PARENT_CONTEXT:
        sell_red = "BASELINE_C_BEHAVIOR"

    else:
        sell_red = f"UNRECOGNIZED_TYPE_{variant_type}_BASELINE_FALLBACK"

    # Simulate with effective_tranches
    realized_pnl = _ZERO
    total_sold_pct = _ZERO
    target_hits: list[str] = []
    search_from = 0

    for tranche in effective_tranches:
        hit_candle: Optional[Candle] = None
        for j in range(search_from, len(post_entry)):
            if post_entry[j].high_price >= tranche.target_price:
                hit_candle = post_entry[j]
                search_from = j + 1
                break
        if hit_candle is not None:
            tranche_capital = starting_capital * tranche.sell_pct / _HUNDRED
            realized_pnl += tranche_capital * (tranche.target_price - buy_level) / buy_level
            total_sold_pct += tranche.sell_pct
            target_hits.append(str(tranche.target_price))
        else:
            break

    remaining_pct = _HUNDRED - total_sold_pct
    final_close = eligible[-1].close_price if eligible else buy_level
    unrealized_pnl = starting_capital * remaining_pct / _HUNDRED * (final_close - buy_level) / buy_level
    total_pnl = realized_pnl + unrealized_pnl
    gross_return_pct = total_pnl / starting_capital * _HUNDRED
    final_value_eur = starting_capital + total_pnl
    bah_return_pct = (final_close - buy_level) / buy_level * _HUNDRED
    improvement_pct = gross_return_pct - bah_return_pct

    excursion_candles = [entry_candle] + list(post_entry)
    mae_pct = (min(c.low_price for c in excursion_candles) - buy_level) / buy_level * _HUNDRED
    mfe_pct = (max(c.high_price for c in excursion_candles) - buy_level) / buy_level * _HUNDRED

    if is_ptf:
        lv: Optional[bool] = False
        cgs = GATE_NOT_LIVE_VALID
        cgr = f"parent_tf_target_status={spec.parent_tf_target_status}"
    else:
        lv = True
        cgs = gate.gate_state
        cgr = gate.gate_reason

    # gate_applied: True only when context was found and variant type is gated.
    # BASELINE/STANDARD never applies a gate by design.
    is_gated_type = variant_type not in (VARIANT_TYPE_BASELINE, VARIANT_TYPE_STANDARD)
    eff_gate_applied: bool = ctx_audit.gate_applied and is_gated_type
    if is_gated_type:
        eff_fallback_policy = ctx_audit.fallback_policy
        eff_fallback_reason = ctx_audit.fallback_reason
    else:
        eff_fallback_policy = "BASELINE_NO_GATE"
        eff_fallback_reason = f"variant_type={variant_type}"

    return VariantResult(
        variant_id=spec.variant_id, label=spec.label,
        active_long_reserve_pct=spec.active_long_reserve_pct,
        reserve_source=spec.reserve_source, tp_scope=spec.tp_scope,
        max_short_swing_sell_pct=spec.max_short_swing_sell_pct,
        max_sell_pct_allowed=spec.max_sell_pct_allowed,
        parent_tf_target_status=spec.parent_tf_target_status,
        entry_hit=True, target_hits=target_hits,
        gross_return_pct=gross_return_pct, pnl_eur=total_pnl,
        final_value_eur=final_value_eur, realized_pnl_eur=realized_pnl,
        unrealized_pnl_eur=unrealized_pnl, short_swing_sold_pct=total_sold_pct,
        long_runner_remaining_pct=remaining_pct,
        maximum_adverse_excursion_pct=mae_pct, maximum_favorable_excursion_pct=mfe_pct,
        buy_and_hold_return_from_entry_to_end=bah_return_pct,
        improvement_vs_buy_and_hold=improvement_pct,
        live_valid=lv,
        continuation_gate_state=cgs,
        continuation_gate_reason=cgr,
        breath_phase_at_target=gate.breath_phase,
        breath_alignment_at_target=gate.breath_alignment,
        market_regime_at_target=gate.market_regime,
        symbol_regime_at_target=gate.symbol_regime,
        context_quality_tier_at_target=gate.context_quality_tier,
        sell_reduction_reason=sell_red,
        target_shift_reason=tgt_shift,
        runner_hold_reason=run_hold,
        overshoot_pct_at_t1=gate.overshoot_pct,
        close_vs_target_pct_at_t1=gate.close_vs_target_pct,
        context_lookup_status=ctx_audit.context_lookup_status,
        context_source=ctx_audit.context_source,
        context_ts_utc=ctx_audit.context_ts_utc,
        context_age_minutes=ctx_audit.context_age_minutes,
        max_context_age_minutes=ctx_audit.max_context_age_minutes,
        context_freshness_status=ctx_audit.context_freshness_status,
        gate_applied=eff_gate_applied,
        fallback_policy=eff_fallback_policy,
        fallback_reason=eff_fallback_reason,
    )


def run_all_continuation_variants(
    candles: list[Candle],
    prediction_ts: datetime,
    buy_level: Decimal,
    starting_capital: Decimal,
    variants: list[VariantSpec],
    context_timeline: ContextTimeline,
) -> list[VariantResult]:
    return [
        simulate_continuation_variant(
            candles, prediction_ts, buy_level, starting_capital, spec, context_timeline
        )
        for spec in variants
    ]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _dec_str(v: Optional[Decimal], places: int = 6) -> Optional[str]:
    if v is None:
        return None
    return str(round(v, places))


def _ts_str(v: Optional[datetime]) -> Optional[str]:
    if v is None:
        return None
    return v.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_summary(result: BacktestResult) -> dict[str, Any]:
    return {
        "runner": RUNNER_NAME,
        "version": RUNNER_VERSION,
        "symbol": result.symbol,
        "quote": result.quote,
        "venue": result.venue,
        "interval_code": result.interval_code,
        "horizon_days": result.horizon_days,
        "buy_level": str(result.buy_level),
        "sell_target": str(result.sell_target),
        "starting_capital_eur": str(result.starting_capital),
        "prediction_ts": _ts_str(result.prediction_ts),
        "prediction_timestamp_status": result.prediction_timestamp_status,
        "window_start_ts": _ts_str(result.window_start_ts),
        "window_end_ts": _ts_str(result.window_end_ts),
        "candles_fetched": result.candles_fetched,
        "first_candle_ts": _ts_str(result.first_candle_ts),
        "last_candle_ts": _ts_str(result.last_candle_ts),
        "entry_hit": result.entry_hit,
        "entry_ts": _ts_str(result.entry_ts),
        "entry_price": _dec_str(result.entry_price, 6),
        "target_hit": result.target_hit,
        "target_ts": _ts_str(result.target_ts),
        "exit_price": _dec_str(result.exit_price, 6),
        "gross_return_pct": _dec_str(result.gross_return_pct, 4),
        "pnl_eur": _dec_str(result.pnl_eur, 4),
        "time_to_target_hours": _dec_str(result.time_to_target_hours, 2),
        "maximum_adverse_excursion_pct": _dec_str(result.maximum_adverse_excursion_pct, 4),
        "maximum_favorable_excursion_pct": _dec_str(result.maximum_favorable_excursion_pct, 4),
        "final_value_eur": _dec_str(result.final_value_eur, 4),
        "buy_and_hold_return_from_entry_to_end": _dec_str(
            result.buy_and_hold_return_from_entry_to_end, 4
        ),
        "improvement_vs_buy_and_hold": _dec_str(result.improvement_vs_buy_and_hold, 4),
        "context": {
            "market_regime": result.market_regime,
            "symbol_regime": result.symbol_regime,
            "breath_phase": result.breath_phase,
            "breath_alignment": result.breath_alignment,
            "context_quality_tier": result.context_quality_tier,
        },
    }


def write_outputs(
    result: BacktestResult,
    candles: list[Candle],
    output_dir: Path,
    ref_levels: Optional[list[Decimal]] = None,
    write_chart: bool = True,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    # summary_v1.json
    summary_path = output_dir / "summary_v1.json"
    summary = build_summary(result)
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    written["summary"] = summary_path

    # event_rows_v1.jsonl
    events_path = output_dir / "event_rows_v1.jsonl"
    with events_path.open("w") as f:
        for row in result.events:
            f.write(json.dumps(row, default=str) + "\n")
    written["events"] = events_path

    # chart_v1.png
    if write_chart and HAS_MATPLOTLIB and candles:
        chart_path = output_dir / "chart_v1.png"
        _draw_chart(
            candles=candles,
            result=result,
            ref_levels=ref_levels or [],
            output_path=chart_path,
        )
        written["chart"] = chart_path
    elif write_chart and not HAS_MATPLOTLIB:
        print("  [WARN] matplotlib not available — chart skipped", file=sys.stderr)

    return written


def _variant_to_dict(r: VariantResult) -> dict[str, Any]:
    def ds(v: Optional[Decimal], p: int = 4) -> Optional[str]:
        return str(round(v, p)) if v is not None else None

    return {
        "variant_id": r.variant_id,
        "label": r.label,
        "active_long_reserve_pct": str(r.active_long_reserve_pct),
        "reserve_source": r.reserve_source,
        "tp_scope": r.tp_scope,
        "max_short_swing_sell_pct": str(r.max_short_swing_sell_pct),
        "max_sell_pct_allowed": str(r.max_sell_pct_allowed),
        "parent_tf_target_status": r.parent_tf_target_status,
        "entry_hit": r.entry_hit,
        "target_hits": r.target_hits,
        "gross_return_pct": ds(r.gross_return_pct),
        "pnl_eur": ds(r.pnl_eur),
        "final_value_eur": ds(r.final_value_eur),
        "realized_pnl_eur": ds(r.realized_pnl_eur),
        "unrealized_pnl_eur": ds(r.unrealized_pnl_eur),
        "short_swing_sold_pct": str(r.short_swing_sold_pct),
        "long_runner_remaining_pct": str(r.long_runner_remaining_pct),
        "MAE": ds(r.maximum_adverse_excursion_pct),
        "MFE": ds(r.maximum_favorable_excursion_pct),
        "buy_and_hold_return_from_entry_to_end": ds(r.buy_and_hold_return_from_entry_to_end),
        "improvement_vs_buy_and_hold": ds(r.improvement_vs_buy_and_hold),
        "live_valid": r.live_valid,
        "continuation_gate_state": r.continuation_gate_state,
        "continuation_gate_reason": r.continuation_gate_reason,
        "breath_phase_at_target": r.breath_phase_at_target,
        "breath_alignment_at_target": r.breath_alignment_at_target,
        "market_regime_at_target": r.market_regime_at_target,
        "symbol_regime_at_target": r.symbol_regime_at_target,
        "context_quality_tier_at_target": r.context_quality_tier_at_target,
        "sell_reduction_reason": r.sell_reduction_reason,
        "target_shift_reason": r.target_shift_reason,
        "runner_hold_reason": r.runner_hold_reason,
        "overshoot_pct_at_t1": ds(r.overshoot_pct_at_t1),
        "close_vs_target_pct_at_t1": ds(r.close_vs_target_pct_at_t1),
        "context_lookup_status": r.context_lookup_status,
        "context_source": r.context_source,
        "context_ts_utc": _ts_str(r.context_ts_utc) if r.context_ts_utc else None,
        "context_age_minutes": r.context_age_minutes,
        "max_context_age_minutes": r.max_context_age_minutes,
        "context_freshness_status": r.context_freshness_status,
        "gate_applied": r.gate_applied,
        "fallback_policy": r.fallback_policy,
        "fallback_reason": r.fallback_reason,
    }


def write_variant_outputs(
    variant_results: list[VariantResult],
    output_dir: Path,
    candles: list[Candle],
    buy_level: Decimal,
    prediction_ts: datetime,
    write_chart: bool = True,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    rows = [_variant_to_dict(r) for r in variant_results]

    # variant_summary_v1.json
    summary_path = output_dir / "variant_summary_v1.json"
    summary_payload = {
        "runner": RUNNER_NAME,
        "version": RUNNER_VERSION,
        "variants": rows,
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2, default=str))
    written["variant_summary"] = summary_path

    # variant_rows_v1.jsonl
    rows_path = output_dir / "variant_rows_v1.jsonl"
    with rows_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    written["variant_rows"] = rows_path

    # chart_variants_v1.png
    if write_chart and HAS_MATPLOTLIB and candles:
        chart_path = output_dir / "chart_variants_v1.png"
        _draw_variant_chart(
            candles=candles,
            buy_level=buy_level,
            prediction_ts=prediction_ts,
            variant_results=variant_results,
            output_path=chart_path,
        )
        written["chart_variants"] = chart_path

    return written


def _draw_variant_chart(
    candles: list[Candle],
    buy_level: Decimal,
    prediction_ts: datetime,
    variant_results: list[VariantResult],
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(16, 7))

    for c in candles:
        x = c.open_ts_utc
        color = "#26a69a" if c.close_price >= c.open_price else "#ef5350"
        ax.plot([x, x], [float(c.low_price), float(c.high_price)],
                color=color, linewidth=0.6, zorder=1)
        body_lo = float(min(c.open_price, c.close_price))
        body_hi = float(max(c.open_price, c.close_price))
        body_h = max(body_hi - body_lo, float(buy_level) * 0.0003)
        rect = mpatches.Rectangle(
            (matplotlib.dates.date2num(x) - 0.004, body_lo),
            0.008, body_h,
            linewidth=0, facecolor=color, zorder=2,
        )
        ax.add_patch(rect)

    xs = [c.open_ts_utc for c in candles]
    ax.set_xlim(xs[0], xs[-1])

    ax.axhline(float(buy_level), color="#1e88e5", linewidth=1.5,
               linestyle="--", label=f"Entry {buy_level}", zorder=3)

    target_styles = [
        (Decimal("2.12"), "#43a047", "--", "T1 2.12"),
        (Decimal("2.25"), "#ffa726", "-.", "T2 2.25"),
        (Decimal("2.35"), "#ab47bc", ":", "T3 2.35"),
    ]
    for lvl, color, ls, lbl in target_styles:
        ax.axhline(float(lvl), color=color, linewidth=1.2,
                   linestyle=ls, label=lbl, zorder=3)

    ax.axvline(prediction_ts, color="#bdbdbd", linewidth=1.0,
               linestyle="-.", alpha=0.7, label="Prediction ts", zorder=3)

    # Find entry timestamp from any variant that hit entry
    entry_ts = next(
        (r for r in variant_results if r.entry_hit), None
    )
    if entry_ts is not None:
        for c in candles:
            if c.open_ts_utc > prediction_ts and c.low_price <= buy_level:
                ax.scatter([c.open_ts_utc], [float(buy_level)],
                           marker="^", s=150, color="#1e88e5", zorder=5,
                           label=f"Entry @ {buy_level}")
                break

    # Reserve-policy note
    policy_lines = [
        "Reserve policy variants:",
        "A: 0% reserve — benchmark",
        "B: 50% reserve, sell 50% at 2.12",
        "C: 50% reserve, sell 20%/15%/15% at 2.12/2.25/2.35",
        "D: 50% reserve, allow_parent_tf_full_exit=True [UNKNOWN]",
    ]
    note = "\n".join(policy_lines)
    ax.text(
        0.01, 0.99, note,
        transform=ax.transAxes, fontsize=7,
        verticalalignment="top", fontfamily="monospace",
        bbox={"boxstyle": "round", "facecolor": "#f5f5f5", "alpha": 0.8},
    )

    final_close = candles[-1].close_price if candles else buy_level
    ax.axhline(float(final_close), color="#78909c", linewidth=0.8,
               linestyle=":", alpha=0.7, label=f"Final close {final_close:.4f}")

    ax.set_title(
        f"NEAR/EUR 15m · Reserve Policy Variants · prediction_ts {_ts_str(prediction_ts)}",
        fontsize=11,
    )
    ax.set_ylabel("Price (EUR)")
    ax.xaxis_date()
    fig.autofmt_xdate(rotation=30)
    ax.legend(fontsize=7, loc="upper right", framealpha=0.7)
    ax.grid(True, alpha=0.25, linewidth=0.5)
    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    plt.close(fig)


def print_variant_comparison_table(variant_results: list[VariantResult]) -> None:
    sorted_results = sorted(
        variant_results,
        key=lambda r: r.final_value_eur if r.final_value_eur is not None else Decimal("0"),
        reverse=True,
    )
    sep = "-" * 110
    hdr = (
        f"  {'variant_id':<36} {'final_eur':>9} {'gross%':>7} "
        f"{'realized':>9} {'unrealized':>11} {'sold%':>6} {'reserve%':>9} "
        f"{'vs B&H%':>8}"
    )
    print(sep)
    print("  VARIANT COMPARISON  (sorted by final_value_eur desc)")
    print(sep)
    print(hdr)
    print(sep)
    for r in sorted_results:
        def _f(v: Optional[Decimal], places: int = 2) -> str:
            return f"{round(v, places)}" if v is not None else "n/a"

        live_note = ""
        if r.tp_scope == TP_SCOPE_PARENT_TF_FULL and r.parent_tf_target_status == "UNKNOWN":
            live_note = " [PTF?]"
        elif r.label == "BENCHMARK_ONLY_NOT_LIVE_POLICY":
            live_note = " [BM]"

        print(
            f"  {r.variant_id + live_note:<36} "
            f"{_f(r.final_value_eur):>9} "
            f"{_f(r.gross_return_pct):>7} "
            f"{_f(r.realized_pnl_eur):>9} "
            f"{_f(r.unrealized_pnl_eur):>11} "
            f"{_f(r.short_swing_sold_pct, 0):>6} "
            f"{_f(r.active_long_reserve_pct, 0):>9} "
            f"{_f(r.improvement_vs_buy_and_hold):>8}"
        )
    print(sep)


def write_continuation_outputs(
    continuation_results: list[VariantResult],
    output_dir: Path,
    candles: list[Candle],
    buy_level: Decimal,
    prediction_ts: datetime,
    write_chart: bool = True,
) -> dict[str, Path]:
    import csv as _csv
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    rows = [_variant_to_dict(r) for r in continuation_results]

    summary_path = output_dir / "continuation_variant_summary_v1.json"
    summary_payload = {
        "runner": RUNNER_NAME,
        "version": RUNNER_VERSION,
        "note": (
            "Continuation-gate variants. Gate fires on context from DB at T1 touch timestamp. "
            "CONTEXT_UNKNOWN when no matching DB rows — C1-C4 fall back to baseline C behavior."
        ),
        "continuation_variants": rows,
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2, default=str))
    written["continuation_summary"] = summary_path

    rows_path = output_dir / "continuation_variant_rows_v1.jsonl"
    with rows_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    written["continuation_rows"] = rows_path

    def _ds(v: Any) -> str:
        if isinstance(v, Decimal):
            return str(round(v, 4))
        return str(v) if v is not None else ""

    # continuation_gate_breakdown_v1.csv — one row per continuation variant
    gate_fields = [
        "variant_id", "live_valid", "continuation_gate_state", "continuation_gate_reason",
        "breath_phase_at_target", "breath_alignment_at_target",
        "market_regime_at_target", "symbol_regime_at_target", "context_quality_tier_at_target",
        "overshoot_pct_at_t1", "close_vs_target_pct_at_t1",
        "sell_reduction_reason", "target_shift_reason", "runner_hold_reason",
        "final_value_eur", "gross_return_pct", "improvement_vs_buy_and_hold",
        "sample_note",
    ]
    gate_path = output_dir / "continuation_gate_breakdown_v1.csv"
    with gate_path.open("w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=gate_fields, extrasaction="ignore")
        writer.writeheader()
        for r in continuation_results:
            writer.writerow({
                "variant_id": r.variant_id,
                "live_valid": str(r.live_valid),
                "continuation_gate_state": r.continuation_gate_state or "",
                "continuation_gate_reason": r.continuation_gate_reason or "",
                "breath_phase_at_target": r.breath_phase_at_target or "",
                "breath_alignment_at_target": r.breath_alignment_at_target or "",
                "market_regime_at_target": r.market_regime_at_target or "",
                "symbol_regime_at_target": r.symbol_regime_at_target or "",
                "context_quality_tier_at_target": r.context_quality_tier_at_target or "",
                "overshoot_pct_at_t1": _ds(r.overshoot_pct_at_t1),
                "close_vs_target_pct_at_t1": _ds(r.close_vs_target_pct_at_t1),
                "sell_reduction_reason": r.sell_reduction_reason or "",
                "target_shift_reason": r.target_shift_reason or "",
                "runner_hold_reason": r.runner_hold_reason or "",
                "final_value_eur": _ds(r.final_value_eur),
                "gross_return_pct": _ds(r.gross_return_pct),
                "improvement_vs_buy_and_hold": _ds(r.improvement_vs_buy_and_hold),
                "sample_note": "n=1 NEAR/EUR 2026-05-21 14d — do not overfit single sample",
            })
    written["continuation_gate_breakdown"] = gate_path

    # breath_regime_breakdown_v1.csv — context at each decision point
    brd_fields = [
        "variant_id", "decision_point",
        "breath_phase", "breath_alignment", "market_regime", "symbol_regime",
        "context_quality_tier", "gate_state", "gate_reason",
        "overshoot_pct", "close_vs_target_pct",
        "final_value_eur", "sample_note",
    ]
    brd_path = output_dir / "breath_regime_breakdown_v1.csv"
    with brd_path.open("w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=brd_fields, extrasaction="ignore")
        writer.writeheader()
        for r in continuation_results:
            writer.writerow({
                "variant_id": r.variant_id,
                "decision_point": "T1_TOUCH",
                "breath_phase": r.breath_phase_at_target or "UNKNOWN",
                "breath_alignment": r.breath_alignment_at_target or "UNKNOWN",
                "market_regime": r.market_regime_at_target or "UNKNOWN",
                "symbol_regime": r.symbol_regime_at_target or "UNKNOWN",
                "context_quality_tier": r.context_quality_tier_at_target or "UNKNOWN",
                "gate_state": r.continuation_gate_state or "",
                "gate_reason": r.continuation_gate_reason or "",
                "overshoot_pct": _ds(r.overshoot_pct_at_t1),
                "close_vs_target_pct": _ds(r.close_vs_target_pct_at_t1),
                "final_value_eur": _ds(r.final_value_eur),
                "sample_note": "n=1 — gate fired on single NEAR 2026-05-21 event",
            })
    written["breath_regime_breakdown"] = brd_path

    # Write context lookup audit outputs
    audit_written = write_context_lookup_audit_outputs(continuation_results, output_dir)
    written.update(audit_written)

    return written


def write_context_lookup_audit_outputs(
    continuation_results: list[VariantResult],
    output_dir: Path,
) -> dict[str, Path]:
    """
    Write three context-lookup audit outputs:
      continuation_context_lookup_audit_v1.csv   — one row per variant with full audit fields
      continuation_context_lookup_summary_v1.json — aggregate counts
      continuation_gate_applied_breakdown_v1.csv  — gate_applied=True rows only
    """
    import csv as _csv
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _ds(v: Any) -> str:
        if isinstance(v, Decimal):
            return str(round(v, 4))
        return str(v) if v is not None else ""

    # continuation_context_lookup_audit_v1.csv
    audit_fields = [
        "variant_id", "variant_type", "live_valid",
        "context_lookup_status", "context_source", "context_ts_utc",
        "context_age_minutes", "max_context_age_minutes", "context_freshness_status",
        "gate_applied", "fallback_policy", "fallback_reason",
        "continuation_gate_state",
        "breath_phase_at_target", "breath_alignment_at_target",
        "market_regime_at_target", "symbol_regime_at_target",
        "final_value_eur", "gross_return_pct",
    ]
    audit_path = output_dir / "continuation_context_lookup_audit_v1.csv"
    with audit_path.open("w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=audit_fields, extrasaction="ignore")
        writer.writeheader()
        for r in continuation_results:
            writer.writerow({
                "variant_id": r.variant_id,
                "variant_type": r.label,
                "live_valid": str(r.live_valid),
                "context_lookup_status": r.context_lookup_status or "",
                "context_source": r.context_source or "",
                "context_ts_utc": _ts_str(r.context_ts_utc) if r.context_ts_utc else "",
                "context_age_minutes": str(r.context_age_minutes) if r.context_age_minutes is not None else "",
                "max_context_age_minutes": str(r.max_context_age_minutes) if r.max_context_age_minutes is not None else "",
                "context_freshness_status": r.context_freshness_status or "",
                "gate_applied": str(r.gate_applied),
                "fallback_policy": r.fallback_policy or "",
                "fallback_reason": r.fallback_reason or "",
                "continuation_gate_state": r.continuation_gate_state or "",
                "breath_phase_at_target": r.breath_phase_at_target or "UNKNOWN",
                "breath_alignment_at_target": r.breath_alignment_at_target or "UNKNOWN",
                "market_regime_at_target": r.market_regime_at_target or "UNKNOWN",
                "symbol_regime_at_target": r.symbol_regime_at_target or "UNKNOWN",
                "final_value_eur": _ds(r.final_value_eur),
                "gross_return_pct": _ds(r.gross_return_pct),
            })
    written["context_lookup_audit"] = audit_path

    # continuation_context_lookup_summary_v1.json
    total = len(continuation_results)
    found = sum(1 for r in continuation_results if r.context_lookup_status == CTX_FOUND)
    stale = sum(1 for r in continuation_results if r.context_lookup_status == CTX_CONTEXT_TOO_STALE)
    missing = sum(1 for r in continuation_results if r.context_lookup_status in (
        CTX_SOURCE_MISSING, CTX_ASOF_JOIN_MISS, CTX_CONTEXT_TRULY_UNKNOWN
    ))
    gate_applied_count = sum(1 for r in continuation_results if r.gate_applied)
    fallback_count = sum(1 for r in continuation_results if r.fallback_policy == "C1_BASELINE")

    by_gate_state: dict[str, int] = {}
    for r in continuation_results:
        k = r.continuation_gate_state or "NONE"
        by_gate_state[k] = by_gate_state.get(k, 0) + 1

    summary_payload = {
        "runner": RUNNER_NAME,
        "version": RUNNER_VERSION,
        "total_variants": total,
        "context_found": found,
        "context_stale": stale,
        "context_missing": missing,
        "gate_applied_count": gate_applied_count,
        "fallback_to_c1_baseline_count": fallback_count,
        "gate_state_counts": by_gate_state,
        "note": (
            "gate_applied=True only when valid fresh context found AND variant is a gated type. "
            "BASELINE variants set gate_applied=False by design."
        ),
    }
    summary_path = output_dir / "continuation_context_lookup_summary_v1.json"
    summary_path.write_text(json.dumps(summary_payload, indent=2, default=str))
    written["context_lookup_summary"] = summary_path

    # continuation_gate_applied_breakdown_v1.csv — gated variants only
    gate_fields = [
        "variant_id", "live_valid", "gate_applied",
        "continuation_gate_state", "continuation_gate_reason",
        "context_lookup_status", "context_source", "context_ts_utc", "context_age_minutes",
        "breath_phase_at_target", "breath_alignment_at_target",
        "market_regime_at_target", "symbol_regime_at_target",
        "overshoot_pct_at_t1", "close_vs_target_pct_at_t1",
        "final_value_eur", "gross_return_pct", "improvement_vs_buy_and_hold",
    ]
    gated_path = output_dir / "continuation_gate_applied_breakdown_v1.csv"
    with gated_path.open("w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=gate_fields, extrasaction="ignore")
        writer.writeheader()
        for r in continuation_results:
            if not r.gate_applied:
                continue
            writer.writerow({
                "variant_id": r.variant_id,
                "live_valid": str(r.live_valid),
                "gate_applied": str(r.gate_applied),
                "continuation_gate_state": r.continuation_gate_state or "",
                "continuation_gate_reason": r.continuation_gate_reason or "",
                "context_lookup_status": r.context_lookup_status or "",
                "context_source": r.context_source or "",
                "context_ts_utc": _ts_str(r.context_ts_utc) if r.context_ts_utc else "",
                "context_age_minutes": str(r.context_age_minutes) if r.context_age_minutes is not None else "",
                "breath_phase_at_target": r.breath_phase_at_target or "UNKNOWN",
                "breath_alignment_at_target": r.breath_alignment_at_target or "UNKNOWN",
                "market_regime_at_target": r.market_regime_at_target or "UNKNOWN",
                "symbol_regime_at_target": r.symbol_regime_at_target or "UNKNOWN",
                "overshoot_pct_at_t1": _ds(r.overshoot_pct_at_t1),
                "close_vs_target_pct_at_t1": _ds(r.close_vs_target_pct_at_t1),
                "final_value_eur": _ds(r.final_value_eur),
                "gross_return_pct": _ds(r.gross_return_pct),
                "improvement_vs_buy_and_hold": _ds(r.improvement_vs_buy_and_hold),
            })
    written["gate_applied_breakdown"] = gated_path

    return written


def print_continuation_comparison_table(continuation_results: list[VariantResult]) -> None:
    sorted_results = sorted(
        continuation_results,
        key=lambda r: r.final_value_eur if r.final_value_eur is not None else Decimal("0"),
        reverse=True,
    )
    sep = "-" * 120
    hdr = (
        f"  {'variant_id':<38} {'final_eur':>9} {'gross%':>7} "
        f"{'live':>6} {'gate_state':<24} {'sell_red/shift/hold_note'}"
    )
    print(sep)
    print("  CONTINUATION GATE VARIANT COMPARISON  (sorted by final_value_eur desc)")
    print("  NOTE: n=1 test window — do not overfit; context=UNKNOWN for all NEAR rows")
    print(sep)
    print(hdr)
    print(sep)
    for r in sorted_results:
        def _f(v: Optional[Decimal], p: int = 2) -> str:
            return f"{round(v, p)}" if v is not None else "n/a"
        gate = r.continuation_gate_state or "—"
        note = (
            r.sell_reduction_reason or
            r.target_shift_reason or
            r.runner_hold_reason or "—"
        )
        if len(note) > 35:
            note = note[:34] + "…"
        print(
            f"  {r.variant_id:<38} "
            f"{_f(r.final_value_eur):>9} "
            f"{_f(r.gross_return_pct):>7} "
            f"{str(r.live_valid):>6} "
            f"{gate:<24} "
            f"{note}"
        )
    print(sep)


def _draw_chart(
    candles: list[Candle],
    result: BacktestResult,
    ref_levels: list[Decimal],
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(16, 7))

    # Draw OHLC bars
    for c in candles:
        x = c.open_ts_utc
        color = "#26a69a" if c.close_price >= c.open_price else "#ef5350"
        # High-low wick
        ax.plot([x, x], [float(c.low_price), float(c.high_price)],
                color=color, linewidth=0.6, zorder=1)
        # Open-close body
        body_lo = float(min(c.open_price, c.close_price))
        body_hi = float(max(c.open_price, c.close_price))
        body_h = max(body_hi - body_lo, float(result.buy_level) * 0.0003)
        rect = mpatches.Rectangle(
            (matplotlib.dates.date2num(x) - 0.004, body_lo),
            0.008, body_h,
            linewidth=0, facecolor=color, zorder=2,
        )
        ax.add_patch(rect)

    xs = [c.open_ts_utc for c in candles]
    ax.set_xlim(xs[0], xs[-1])

    # Entry / target lines
    ax.axhline(float(result.buy_level), color="#1e88e5", linewidth=1.4,
               linestyle="--", label=f"Entry {result.buy_level}", zorder=3)
    ax.axhline(float(result.sell_target), color="#43a047", linewidth=1.4,
               linestyle="--", label=f"Target {result.sell_target}", zorder=3)

    # Reference levels
    ref_colors = ["#ffa726", "#ff7043", "#ab47bc", "#7e57c2", "#26c6da"]
    for i, lvl in enumerate(ref_levels):
        ax.axhline(float(lvl), color=ref_colors[i % len(ref_colors)],
                   linewidth=0.8, linestyle=":", alpha=0.8,
                   label=f"Ref {lvl}", zorder=2)

    # Prediction timestamp
    ax.axvline(result.prediction_ts, color="#bdbdbd", linewidth=1.0,
               linestyle="-.", alpha=0.7, label="Prediction ts", zorder=3)

    # Entry marker
    if result.entry_ts is not None and result.entry_price is not None:
        ax.scatter([result.entry_ts], [float(result.entry_price)],
                   marker="^", s=120, color="#1e88e5", zorder=5,
                   label=f"Entry @ {result.entry_price}")

    # Exit marker
    if result.target_ts is not None and result.exit_price is not None:
        ax.scatter([result.target_ts], [float(result.exit_price)],
                   marker="v", s=120, color="#43a047", zorder=5,
                   label=f"Exit @ {result.exit_price}")

    ax.set_title(
        f"{result.symbol}/{result.quote} {result.interval_code} · "
        f"Exact Zone Backtest · {_ts_str(result.prediction_ts)}",
        fontsize=11,
    )
    ax.set_ylabel(f"Price ({result.quote})")
    ax.xaxis_date()
    fig.autofmt_xdate(rotation=30)
    ax.legend(fontsize=7, loc="upper left", framealpha=0.7)
    ax.grid(True, alpha=0.25, linewidth=0.5)
    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Compact terminal summary
# ---------------------------------------------------------------------------

def print_compact_summary(result: BacktestResult, written: dict[str, Path]) -> None:
    sep = "-" * 60
    print(sep)
    print(f"  {RUNNER_NAME} v{RUNNER_VERSION}")
    print(f"  symbol          : {result.symbol}/{result.quote} @ {result.venue}")
    print(f"  interval        : {result.interval_code}  horizon: {result.horizon_days}d")
    print(f"  prediction_ts   : {_ts_str(result.prediction_ts)}"
          f"  [{result.prediction_timestamp_status}]")
    print(f"  buy_level       : {result.buy_level}")
    print(f"  sell_target     : {result.sell_target}")
    print(f"  capital         : {result.starting_capital} EUR")
    print(f"  candles         : {result.candles_fetched}"
          f"  ({_ts_str(result.first_candle_ts)} .. {_ts_str(result.last_candle_ts)})")
    print(sep)
    print(f"  entry_hit       : {result.entry_hit}  ts={_ts_str(result.entry_ts)}"
          f"  price={result.entry_price}")
    print(f"  target_hit      : {result.target_hit}  ts={_ts_str(result.target_ts)}"
          f"  exit={result.exit_price}")
    print(f"  gross_return    : {result.gross_return_pct} %")
    print(f"  pnl_eur         : {result.pnl_eur}")
    print(f"  final_value     : {result.final_value_eur} EUR")
    print(f"  time_to_target  : {result.time_to_target_hours} h")
    print(f"  MAE             : {result.maximum_adverse_excursion_pct} %")
    print(f"  MFE             : {result.maximum_favorable_excursion_pct} %")
    print(f"  B&H return      : {result.buy_and_hold_return_from_entry_to_end} %")
    print(f"  vs B&H          : {result.improvement_vs_buy_and_hold} %")
    print(sep)
    print(f"  market_regime   : {result.market_regime}")
    print(f"  symbol_regime   : {result.symbol_regime}")
    print(f"  breath_phase    : {result.breath_phase}")
    print(f"  breath_align    : {result.breath_alignment}")
    print(f"  ctx_tier        : {result.context_quality_tier}")
    print(sep)
    for label, path in written.items():
        print(f"  {label:<14}: {path}")
    print(sep)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(
    symbol: str = DEFAULT_SYMBOL,
    quote: str = DEFAULT_QUOTE,
    venue: str = DEFAULT_VENUE,
    interval_code: str = DEFAULT_INTERVAL,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    buy_level: Decimal = DEFAULT_BUY_LEVEL,
    sell_target: Decimal = DEFAULT_SELL_TARGET,
    starting_capital: Decimal = DEFAULT_STARTING_CAPITAL,
    prediction_ts_str: str = DEFAULT_PREDICTION_TS,
    output_dir: Optional[Path] = None,
    env_file: Optional[str] = None,
    write_chart: bool = True,
    run_variants: bool = True,
    variants: Optional[list[VariantSpec]] = None,
    run_continuation: bool = True,
    continuation_variants: Optional[list[VariantSpec]] = None,
) -> dict[str, Any]:
    """
    Full run: connect to DB, fetch candles, simulate, write outputs.
    When run_variants=True also runs all reserve-policy variants on the same candles.
    When run_continuation=True also runs continuation-gate variants with context timeline.
    Returns the summary dict.
    """
    print(f"STARTED {RUNNER_NAME}")
    print(f"  symbol={symbol} quote={quote} venue={venue} interval={interval_code}")
    print(f"  horizon={horizon_days}d  buy={buy_level}  target={sell_target}"
          f"  capital={starting_capital}")

    # Parse prediction timestamp
    prediction_ts = parse_ts(prediction_ts_str)
    window_start = prediction_ts
    window_end = prediction_ts + timedelta(days=horizon_days)

    # Resolve output dir
    if output_dir is None:
        output_dir = (
            Path("data/research/manual_exact_zone_backtest_v1") /
            f"{symbol.lower()}_exact_first_test"
        )

    ref_levels = [
        Decimal("1.90"), Decimal("1.95"), Decimal("2.15"),
        Decimal("2.25"), Decimal("2.35"),
    ]

    # DB connection
    config = load_db_config(env_file)
    conn = connect(config)
    print("  DB connected")

    try:
        columns = detect_candle_columns(conn)

        asset_id = fetch_asset_id(conn, symbol)
        if asset_id is None:
            raise RuntimeError(f"Asset '{symbol}' not found in DB")
        print(f"  asset_id={asset_id} for {symbol}")

        candles = fetch_candles(
            conn, columns, asset_id, venue, interval_code,
            window_start, window_end,
        )
        print(f"  fetched {len(candles)} candles  "
              f"({_ts_str(candles[0].open_ts_utc) if candles else 'none'} .. "
              f"{_ts_str(candles[-1].open_ts_utc) if candles else 'none'})")

        context = fetch_context_annotation(conn, symbol, venue, prediction_ts)
        print(f"  context: {context}")

        context_timeline = _empty_context_timeline()
        if run_continuation:
            context_timeline = fetch_context_timeline_raw(
                conn, symbol, venue, window_start, window_end,
                interval_code=interval_code,
            )
            print(
                f"  context_timeline: "
                f"signal_rows={len(context_timeline.signal_rows)} "
                f"regime_rows={len(context_timeline.market_regime_rows)} "
                f"breath_rows={len(context_timeline.breath_rows)} "
                f"selection_rows={len(context_timeline.selection_rows)}"
            )

    finally:
        conn.close()

    # Determine prediction_timestamp_status
    prediction_timestamp_status = "ASSUMED"
    # (No exact observation found in repo/DB for NEAR support=2.00 zone)

    # Simulate
    result, events = simulate_exact_zone(
        candles=candles,
        prediction_ts=prediction_ts,
        buy_level=buy_level,
        sell_target=sell_target,
        starting_capital=starting_capital,
    )

    # Fill result metadata
    result.symbol = symbol
    result.quote = quote
    result.venue = venue
    result.interval_code = interval_code
    result.horizon_days = horizon_days
    result.buy_level = buy_level
    result.sell_target = sell_target
    result.starting_capital = starting_capital
    result.prediction_ts = prediction_ts
    result.prediction_timestamp_status = prediction_timestamp_status
    result.window_start_ts = window_start
    result.window_end_ts = window_end
    result.market_regime = context["market_regime"]
    result.symbol_regime = context["symbol_regime"]
    result.breath_phase = context["breath_phase"]
    result.breath_alignment = context["breath_alignment"]
    result.context_quality_tier = context["context_quality_tier"]

    # Write outputs
    written = write_outputs(
        result=result,
        candles=candles,
        output_dir=output_dir,
        ref_levels=ref_levels,
        write_chart=write_chart,
    )

    summary = build_summary(result)
    print_compact_summary(result, written)

    if run_variants:
        variant_specs = variants if variants is not None else NEAR_VARIANTS
        print(f"  running {len(variant_specs)} reserve-policy variants ...")
        variant_results = run_all_variants(
            candles=candles,
            prediction_ts=prediction_ts,
            buy_level=buy_level,
            starting_capital=starting_capital,
            variants=variant_specs,
        )
        variant_written = write_variant_outputs(
            variant_results=variant_results,
            output_dir=output_dir,
            candles=candles,
            buy_level=buy_level,
            prediction_ts=prediction_ts,
            write_chart=write_chart,
        )
        for label, path in variant_written.items():
            print(f"  {label:<14}: {path}")
        print()
        print_variant_comparison_table(variant_results)
        summary["variants"] = [_variant_to_dict(r) for r in variant_results]

    if run_continuation:
        cont_specs = continuation_variants if continuation_variants is not None else NEAR_CONTINUATION_VARIANTS
        print(f"  running {len(cont_specs)} continuation-gate variants ...")
        continuation_results = run_all_continuation_variants(
            candles=candles,
            prediction_ts=prediction_ts,
            buy_level=buy_level,
            starting_capital=starting_capital,
            variants=cont_specs,
            context_timeline=context_timeline,
        )
        cont_written = write_continuation_outputs(
            continuation_results=continuation_results,
            output_dir=output_dir,
            candles=candles,
            buy_level=buy_level,
            prediction_ts=prediction_ts,
            write_chart=write_chart,
        )
        for label, path in cont_written.items():
            print(f"  {label:<22}: {path}")
        print()
        print_continuation_comparison_table(continuation_results)
        summary["continuation_variants"] = [_variant_to_dict(r) for r in continuation_results]

    print("FINISHED")
    return summary


def parse_ts(ts_str: str) -> datetime:
    ts_str = ts_str.strip()
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=RUNNER_NAME)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL, dest="interval_code")
    parser.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS)
    parser.add_argument("--buy-level", default=str(DEFAULT_BUY_LEVEL))
    parser.add_argument("--sell-target", default=str(DEFAULT_SELL_TARGET))
    parser.add_argument("--starting-capital", default=str(DEFAULT_STARTING_CAPITAL))
    parser.add_argument("--prediction-ts", default=DEFAULT_PREDICTION_TS)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--no-chart", action="store_true")
    parser.add_argument("--no-variants", action="store_true")
    parser.add_argument("--no-continuation", action="store_true")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir) if args.output_dir else None

    run(
        symbol=args.symbol,
        quote=args.quote,
        venue=args.venue,
        interval_code=args.interval_code,
        horizon_days=args.horizon_days,
        buy_level=Decimal(args.buy_level),
        sell_target=Decimal(args.sell_target),
        starting_capital=Decimal(args.starting_capital),
        prediction_ts_str=args.prediction_ts,
        output_dir=output_dir,
        env_file=args.env_file,
        write_chart=not args.no_chart,
        run_variants=not args.no_variants,
        run_continuation=not args.no_continuation,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
