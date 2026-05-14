from __future__ import annotations

"""
Synth v2 - Regime Selector Backtest V1.

LAYER: research

BOUNDARY:
  Allowed:
    - read selection_state snapshots (market-only)
    - read obs_market_candle for price/context
    - read optional strategy layer tables (read-only)
    - write regime_selector_backtest_observation_v1
    - compute forward return, MFE, MAE, regime classifications, strategy signatures

  Forbidden:
    - account_id, balances, positions, open orders, execution plans
    - broker calls, broker writes, order submission, live orders
    - decision_gate logic
    - execution_planner logic
    - executor logic
    - paper/live parity logic (risk_mode, PAPER_ONLY, etc.)
    - manual horizon selection for regime routing

Purpose:
  Measure whether selection_engine strategy behavior is better explained by
  global market regime, asset class regime, global x class cross, or
  strategy signature properties derived from existing strategy outputs.

  Four selector_mode variants are stored per observation:
    GLOBAL             -> compares by global_regime dimension
    ASSET_CLASS        -> compares by asset_class_regime dimension
    GLOBAL_CLASS       -> compares by global_class_regime cross dimension
    STRATEGY_SIGNATURE -> compares by strategy_signature bucket

  All four use the same underlying price/return data. The selector_mode tag
  identifies which dimension is the primary analysis axis for that row.

Downstream path (this runner is read-only in the live pipeline):
  regime_selector_backtest_v1
  -> regime selector candidates
  -> active_regime_observation design
  -> policy_router design
  -> optional selection/advice integration after validation

Do NOT add decision_gate / execution_planner / executor changes.
"""

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import mean
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection

REPORT_NAME = "regime_selector_backtest_v1"
REPORT_VERSION = "1.1"
OUTPUT_TABLE = "regime_selector_backtest_observation_v1"

ALL_SELECTOR_MODES = [
    "GLOBAL",
    "ASSET_CLASS",
    "GLOBAL_CLASS",
    "STRATEGY_SIGNATURE",
]

# ---------------------------------------------------------------------------
# Asset class classification
# ---------------------------------------------------------------------------

_BTC = {"BTC"}
_ETH = {"ETH"}
_MEME = {
    "PEPE", "DOGE", "SHIB", "FLOKI", "BONK", "WIF", "MEME", "MOG",
    "BOME", "CATE", "LADYS", "TURBO", "NEIRO", "POPCAT", "BRETT",
}
_DEFI = {
    "UNI", "AAVE", "SUSHI", "CAKE", "COMP", "MKR", "YFI", "SNX",
    "CRV", "BAL", "1INCH", "RUNE", "LDO", "GMX", "GNO", "RPL", "PENDLE",
    "EIGEN", "ENA",
}
_AI = {
    "FET", "AGIX", "RNDR", "WLD", "TAO", "OCEAN", "NMR", "ARPA", "ALI",
    "AI16Z", "VIRTUAL", "AIXBT", "GRASS", "GOAT", "RENDER",
}
_L1_L2 = {
    "SOL", "AVAX", "ADA", "DOT", "MATIC", "POL", "ATOM", "NEAR", "FTM",
    "ONE", "ALGO", "XTZ", "FLOW", "APT", "SUI", "SEI", "INJ", "TIA",
    "OSMO", "KAVA", "EGLD", "ROSE", "MINA", "ZK", "ARB", "OP", "STRK",
    "TON", "HYPE", "MANTLE", "MNT", "BLAST",
}
_INFRA = {
    "LINK", "GRT", "BAND", "API3", "PYTH", "VET", "QNT", "HBAR",
    "XRP", "XLM", "LTC", "BCH", "ETC", "ANKR",
}


def classify_asset_class(symbol: str) -> str:
    sym = symbol.upper()
    for suffix in ("-EUR", "-USD", "-USDT", "-USDC", "EUR", "USD", "USDT", "USDC"):
        if sym.endswith(suffix):
            sym = sym[: -len(suffix)]
            break
    if sym in _BTC:
        return "BTC"
    if sym in _ETH:
        return "ETH"
    if sym in _MEME:
        return "MEME"
    if sym in _DEFI:
        return "DEFI"
    if sym in _AI:
        return "AI"
    if sym in _L1_L2:
        return "L1_L2"
    if sym in _INFRA:
        return "INFRA"
    return "OTHER"


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

def classify_global_regime(btc_24h: float | None, avg_alt_24h: float | None) -> str:
    # UNKNOWN is reserved for missing/undetermined data only.
    # Every real BTC 24h return must resolve to a named label.
    if btc_24h is None:
        return "GLOBAL_UNKNOWN"
    if btc_24h < -0.05:
        return "GLOBAL_BTC_BREAKDOWN"
    if -0.05 <= btc_24h < -0.01:
        return "GLOBAL_BTC_MILD_DECLINE"
    if -0.01 <= btc_24h <= 0.01:
        return "GLOBAL_NEUTRAL"
    if btc_24h > 0.08:
        return "GLOBAL_BTC_OVERHEATED"
    if avg_alt_24h is not None:
        relative = avg_alt_24h - btc_24h
        if btc_24h < 0.04 and relative > 0.04:
            return "GLOBAL_ROTATION_WINDOW"
    if btc_24h > 0.01:
        return "GLOBAL_RISK_ON"
    return "GLOBAL_UNKNOWN"


def classify_class_regime(class_24h: float | None, btc_24h: float | None) -> str:
    if class_24h is None:
        return "CLASS_UNKNOWN"
    btc = btc_24h if btc_24h is not None else 0.0
    relative = class_24h - btc
    if relative < -0.05:
        return "CLASS_RISK_OFF"
    if relative < -0.02:
        return "CLASS_STRESS"
    if class_24h > 0.10:
        return "CLASS_OVERHEATED"
    if relative > 0.04:
        return "CLASS_LEADERSHIP"
    if btc > 0 and class_24h < 0:
        return "CLASS_PULLBACK"
    if relative < -0.01:
        return "CLASS_LAGGARD"
    return "CLASS_NEUTRAL"


def make_strategy_signature(
    selection_state: str | None,
    setup_filter_state: str | None,
    policy_decision: str | None,
    advice_state: str | None,
    aplus_bucket: str | None,
) -> str:
    # Canonical format: fixed key=value pairs in fixed order.
    # UNKNOWN is the only substitute for missing/blank values.
    def _v(s: str | None) -> str:
        v = (s or "").strip()
        return v if v else "UNKNOWN"

    return (
        f"SEL={_v(selection_state)}"
        f"|SETUP={_v(setup_filter_state)}"
        f"|POLICY={_v(policy_decision)}"
        f"|ADVICE={_v(advice_state)}"
        f"|APLUS={_v(aplus_bucket)}"
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _check_table_exists(conn: Any, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = %s",
            (table_name,),
        )
        row = cur.fetchone()
    return bool(row and row["n"])


def _discover_candle_columns(conn: Any) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM obs_market_candle")
        rows = cur.fetchall()
    return {str(row["Field"]) for row in rows}


def _fetch_btc_asset_id(conn: Any) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT asset_id FROM asset WHERE symbol = 'BTC' LIMIT 1")
        row = cur.fetchone()
    return int(row["asset_id"]) if row else None


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

def fetch_snapshots(
    conn: Any,
    *,
    venue: str,
    from_ts: datetime | None,
    to_ts: datetime | None,
    limit: int,
) -> list[datetime]:
    where: list[str] = ["ss.venue = %s"]
    params: list[Any] = [venue]
    if from_ts is not None:
        where.append("ss.asof_ts_utc >= %s")
        params.append(from_ts)
    if to_ts is not None:
        where.append("ss.asof_ts_utc <= %s")
        params.append(to_ts)
    sql = f"""
    SELECT DISTINCT ss.asof_ts_utc
    FROM selection_state ss
    WHERE {" AND ".join(where)}
    ORDER BY ss.asof_ts_utc DESC
    LIMIT {int(limit)}
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return sorted(row["asof_ts_utc"] for row in rows)


def fetch_selection_rows(
    conn: Any,
    *,
    venue: str,
    snapshot_ts_list: list[datetime],
) -> list[dict]:
    if not snapshot_ts_list:
        return []
    placeholders = ",".join(["%s"] * len(snapshot_ts_list))
    sql = f"""
    SELECT
        ss.asset_id,
        a.symbol,
        ss.venue,
        ss.asof_ts_utc,
        ss.selection_state,
        ss.selection_bias,
        ss.selection_score,
        ss.priority_rank
    FROM selection_state ss
    INNER JOIN asset a ON a.asset_id = ss.asset_id
    WHERE ss.venue = %s
      AND ss.asof_ts_utc IN ({placeholders})
    ORDER BY ss.asof_ts_utc, ss.priority_rank, ss.asset_id
    """
    params: list[Any] = [venue] + list(snapshot_ts_list)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_candles(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    asset_ids: list[int],
    from_ts: datetime,
    to_ts: datetime,
    has_high: bool,
    has_low: bool,
) -> dict[int, list[dict]]:
    if not asset_ids:
        return {}
    extras = ""
    if has_high:
        extras += ", high_price"
    if has_low:
        extras += ", low_price"
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
    SELECT asset_id, close_ts_utc, close_price{extras}
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = %s
      AND asset_id IN ({placeholders})
      AND close_ts_utc >= %s
      AND close_ts_utc <= %s
    ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, interval_code] + list(asset_ids) + [from_ts, to_ts]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    result: dict[int, list[dict]] = {}
    for row in rows:
        aid = int(row["asset_id"])
        result.setdefault(aid, []).append(row)
    return result


def fetch_optional_filter(
    conn: Any,
    *,
    venue: str,
    asset_ids: list[int],
    ts_list: list[datetime],
) -> dict[tuple[int, datetime], dict]:
    if not _check_table_exists(conn, "trade_setup_filter_observation"):
        return {}
    if not asset_ids or not ts_list:
        return {}
    aid_ph = ",".join(["%s"] * len(asset_ids))
    ts_ph = ",".join(["%s"] * len(ts_list))
    sql = f"""
    SELECT asset_id, asof_ts_utc, setup_filter_state, setup_filter_reason
    FROM trade_setup_filter_observation
    WHERE venue = %s
      AND asset_id IN ({aid_ph})
      AND asof_ts_utc IN ({ts_ph})
    ORDER BY asof_ts_utc, asset_id
    """
    params: list[Any] = [venue] + list(asset_ids) + list(ts_list)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return {(int(r["asset_id"]), r["asof_ts_utc"]): r for r in rows}


def fetch_optional_policy(
    conn: Any,
    *,
    venue: str,
    asset_ids: list[int],
    ts_list: list[datetime],
) -> dict[tuple[int, datetime], dict]:
    if not _check_table_exists(conn, "trade_setup_policy_preview_observation"):
        return {}
    if not asset_ids or not ts_list:
        return {}
    aid_ph = ",".join(["%s"] * len(asset_ids))
    ts_ph = ",".join(["%s"] * len(ts_list))
    sql = f"""
    SELECT asset_id, asof_ts_utc, setup_filter_state, setup_filter_reason, policy_decision
    FROM trade_setup_policy_preview_observation
    WHERE venue = %s
      AND asset_id IN ({aid_ph})
      AND asof_ts_utc IN ({ts_ph})
    ORDER BY asof_ts_utc, asset_id
    """
    params: list[Any] = [venue] + list(asset_ids) + list(ts_list)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return {(int(r["asset_id"]), r["asof_ts_utc"]): r for r in rows}


def fetch_optional_advice(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    asset_ids: list[int],
    ts_list: list[datetime],
) -> dict[tuple[int, datetime], dict]:
    if not _check_table_exists(conn, "paper_advice_observation"):
        return {}
    if not asset_ids or not ts_list:
        return {}
    aid_ph = ",".join(["%s"] * len(asset_ids))
    ts_ph = ",".join(["%s"] * len(ts_list))
    sql = f"""
    SELECT asset_id, asof_ts_utc,
           setup_filter_state, setup_filter_reason,
           policy_decision, advice_state, advice_action, aplus_bucket
    FROM paper_advice_observation
    WHERE venue = %s
      AND interval_code = %s
      AND asset_id IN ({aid_ph})
      AND asof_ts_utc IN ({ts_ph})
    ORDER BY asof_ts_utc, asset_id
    """
    params: list[Any] = [venue, interval_code] + list(asset_ids) + list(ts_list)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return {(int(r["asset_id"]), r["asof_ts_utc"]): r for r in rows}


# ---------------------------------------------------------------------------
# Candle lookup helpers (binary search on sorted candle list)
# ---------------------------------------------------------------------------

def _price_before(candles: list[dict], ts: datetime) -> Decimal | None:
    lo, hi, found = 0, len(candles) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if candles[mid]["close_ts_utc"] <= ts:
            found = candles[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    if found is None or found["close_price"] is None:
        return None
    try:
        return Decimal(str(found["close_price"]))
    except InvalidOperation:
        return None


def _price_after(candles: list[dict], ts: datetime) -> Decimal | None:
    lo, hi, found = 0, len(candles) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if candles[mid]["close_ts_utc"] >= ts:
            found = candles[mid]
            hi = mid - 1
        else:
            lo = mid + 1
    if found is None or found["close_price"] is None:
        return None
    try:
        return Decimal(str(found["close_price"]))
    except InvalidOperation:
        return None


def _ts_before(candles: list[dict], ts: datetime) -> datetime | None:
    lo, hi, found = 0, len(candles) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if candles[mid]["close_ts_utc"] <= ts:
            found = candles[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return found["close_ts_utc"] if found else None


def _ts_after(candles: list[dict], ts: datetime) -> datetime | None:
    lo, hi, found = 0, len(candles) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if candles[mid]["close_ts_utc"] >= ts:
            found = candles[mid]
            hi = mid - 1
        else:
            lo = mid + 1
    return found["close_ts_utc"] if found else None


def _mfe_mae(
    candles: list[dict],
    base_ts: datetime,
    future_ts: datetime,
    current_price: Decimal,
) -> tuple[Decimal | None, Decimal | None]:
    if not current_price or current_price == 0:
        return None, None
    highs: list[Decimal] = []
    lows: list[Decimal] = []
    for c in candles:
        cts = c["close_ts_utc"]
        if cts < base_ts or cts > future_ts:
            continue
        if c.get("high_price") is not None:
            try:
                highs.append(Decimal(str(c["high_price"])))
            except InvalidOperation:
                pass
        if c.get("low_price") is not None:
            try:
                lows.append(Decimal(str(c["low_price"])))
            except InvalidOperation:
                pass
    mfe = ((max(highs) / current_price) - 1) * 100 if highs else None
    mae = ((min(lows) / current_price) - 1) * 100 if lows else None
    return mfe, mae


def _pct(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float((numerator / denominator) - 1)


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

_UPSERT_SQL = f"""
INSERT INTO {OUTPUT_TABLE} (
    report_name, report_version, run_ts_utc,
    selector_mode,
    asset_id, symbol, venue, interval_code, asof_ts_utc, horizon_hours,
    current_price, future_price, forward_return_pct, mfe_pct, mae_pct,
    btc_return_24h_pct, btc_return_72h_pct, asset_return_24h_pct,
    class_return_24h_pct, relative_class_vs_btc_24h_pct,
    asset_class, global_regime, asset_class_regime, global_class_regime,
    strategy_signature,
    selection_state, selection_bias, selection_score, priority_rank,
    setup_filter_state, setup_filter_reason, policy_decision,
    advice_state, advice_action, aplus_bucket,
    source_ref_json
) VALUES (
    %s, %s, %s,
    %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s,
    %s, %s, %s, %s,
    %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    %s
)
ON DUPLICATE KEY UPDATE
    report_name = VALUES(report_name),
    run_ts_utc = VALUES(run_ts_utc),
    current_price = VALUES(current_price),
    future_price = VALUES(future_price),
    forward_return_pct = VALUES(forward_return_pct),
    mfe_pct = VALUES(mfe_pct),
    mae_pct = VALUES(mae_pct),
    btc_return_24h_pct = VALUES(btc_return_24h_pct),
    btc_return_72h_pct = VALUES(btc_return_72h_pct),
    asset_return_24h_pct = VALUES(asset_return_24h_pct),
    class_return_24h_pct = VALUES(class_return_24h_pct),
    relative_class_vs_btc_24h_pct = VALUES(relative_class_vs_btc_24h_pct),
    asset_class = VALUES(asset_class),
    global_regime = VALUES(global_regime),
    asset_class_regime = VALUES(asset_class_regime),
    global_class_regime = VALUES(global_class_regime),
    selection_state = VALUES(selection_state),
    selection_bias = VALUES(selection_bias),
    selection_score = VALUES(selection_score),
    priority_rank = VALUES(priority_rank),
    setup_filter_state = VALUES(setup_filter_state),
    setup_filter_reason = VALUES(setup_filter_reason),
    policy_decision = VALUES(policy_decision),
    advice_state = VALUES(advice_state),
    advice_action = VALUES(advice_action),
    aplus_bucket = VALUES(aplus_bucket),
    source_ref_json = VALUES(source_ref_json),
    updated_ts_utc = CURRENT_TIMESTAMP(6)
"""


def _row_to_params(obs: dict) -> tuple:
    def _d(v: Any) -> Any:
        if isinstance(v, Decimal):
            return str(v)
        return v

    return (
        obs["report_name"], obs["report_version"], obs["run_ts_utc"],
        obs["selector_mode"],
        obs["asset_id"], obs["symbol"], obs["venue"], obs["interval_code"],
        obs["asof_ts_utc"], obs["horizon_hours"],
        _d(obs["current_price"]), _d(obs["future_price"]),
        obs["forward_return_pct"], obs["mfe_pct"], obs["mae_pct"],
        obs["btc_return_24h_pct"], obs["btc_return_72h_pct"], obs["asset_return_24h_pct"],
        obs["class_return_24h_pct"], obs["relative_class_vs_btc_24h_pct"],
        obs["asset_class"], obs["global_regime"], obs["asset_class_regime"], obs["global_class_regime"],
        obs["strategy_signature"],
        obs["selection_state"], obs["selection_bias"],
        _d(obs["selection_score"]) if obs["selection_score"] is not None else None,
        obs["priority_rank"],
        obs["setup_filter_state"], obs["setup_filter_reason"], obs["policy_decision"],
        obs["advice_state"], obs["advice_action"], obs["aplus_bucket"],
        obs["source_ref_json"],
    )


def upsert_rows(conn: Any, obs_list: list[dict], batch_size: int = 200) -> int:
    written = 0
    for i in range(0, len(obs_list), batch_size):
        batch = obs_list[i : i + batch_size]
        with conn.cursor() as cur:
            for obs in batch:
                cur.execute(_UPSERT_SQL, _row_to_params(obs))
        conn.commit()
        written += len(batch)
    return written


# ---------------------------------------------------------------------------
# Aggregate reporting
# ---------------------------------------------------------------------------

def _aggregate(obs_list: list[dict], group_key: str) -> dict[str, dict]:
    groups: dict[str, list[float]] = defaultdict(list)
    mfe_groups: dict[str, list[float]] = defaultdict(list)
    mae_groups: dict[str, list[float]] = defaultdict(list)
    for obs in obs_list:
        key = obs.get(group_key) or "UNKNOWN"
        ret = obs.get("forward_return_pct")
        if ret is not None:
            groups[key].append(float(ret))
        mfe = obs.get("mfe_pct")
        if mfe is not None:
            mfe_groups[key].append(float(mfe))
        mae = obs.get("mae_pct")
        if mae is not None:
            mae_groups[key].append(float(mae))

    result: dict[str, dict] = {}
    all_keys = set(groups) | {obs.get(group_key) or "UNKNOWN" for obs in obs_list}
    for key in all_keys:
        rets = groups.get(key, [])
        n_total = sum(1 for obs in obs_list if (obs.get(group_key) or "UNKNOWN") == key)
        wins = [r for r in rets if r > 0]
        result[key] = {
            "label": key,
            "n_total": n_total,
            "n_with_return": len(rets),
            "win_rate_pct": (len(wins) / len(rets) * 100) if rets else 0.0,
            "avg_return_pct": mean(rets) if rets else 0.0,
            "avg_mfe_pct": mean(mfe_groups[key]) if mfe_groups.get(key) else None,
            "avg_mae_pct": mean(mae_groups[key]) if mae_groups.get(key) else None,
        }
    return result


def _print_aggregate_table(
    title: str,
    aggregates: dict[str, dict],
    min_group_n: int,
    limit_groups: int,
) -> None:
    rows = [
        row for row in aggregates.values()
        if row["n_with_return"] >= min_group_n
    ]
    rows.sort(key=lambda r: abs(r["avg_return_pct"]), reverse=True)
    rows = rows[:limit_groups]

    if not rows:
        print(f"\n{title}")
        print("  (no groups with n >= {min_group_n})")
        return

    cols = ["label", "n_total", "n_with_return", "win_rate_pct", "avg_return_pct",
            "avg_mfe_pct", "avg_mae_pct"]
    col_w = {c: max(len(c), max((len(_fmt(r.get(c))) for r in rows), default=0)) for c in cols}

    header = "  ".join(c.ljust(col_w[c]) for c in cols)
    sep = "-" * len(header)

    print(f"\n{title}")
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(_fmt(row.get(c)).ljust(col_w[c]) for c in cols))


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def print_all_tables(
    all_obs: list[dict],
    horizons: list[int],
    selector_modes: list[str],
    min_group_n: int,
    limit_groups: int,
) -> None:
    mode_key_map = {
        "GLOBAL": "global_regime",
        "ASSET_CLASS": "asset_class_regime",
        "GLOBAL_CLASS": "global_class_regime",
        "STRATEGY_SIGNATURE": "strategy_signature",
    }
    for horizon in horizons:
        h_obs = [o for o in all_obs if o["horizon_hours"] == horizon]
        for mode in selector_modes:
            dim_key = mode_key_map.get(mode, mode.lower())
            mode_obs = [o for o in h_obs if o["selector_mode"] == mode]
            agg = _aggregate(mode_obs, dim_key)
            _print_aggregate_table(
                f"=== horizon={horizon}h | selector_mode={mode} | dim={dim_key} ===",
                agg,
                min_group_n=min_group_n,
                limit_groups=limit_groups,
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Regime selector backtest v1. "
            "Research-only. Market-only. Account-agnostic. "
            "Measures whether selection_engine behavior is better explained by "
            "global regime, asset-class regime, global x class, or strategy signature."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h", dest="interval_code")
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    parser.add_argument("--limit-snapshots", type=int, default=180)
    parser.add_argument("--horizons", nargs="+", type=int, default=[4, 24, 72])
    parser.add_argument("--min-group-n", type=int, default=8)
    parser.add_argument("--limit-groups", type=int, default=12)
    parser.add_argument(
        "--selector-modes",
        nargs="+",
        default=ALL_SELECTOR_MODES,
        choices=ALL_SELECTOR_MODES + ["EXPERIMENTAL"],
        metavar="MODE",
    )
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("T", " "))
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _json_default(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    return str(v)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    load_dotenv()
    args = parse_args()

    horizons: list[int] = sorted(set(args.horizons))
    selector_modes: list[str] = args.selector_modes

    if any(h <= 0 for h in horizons):
        print("[ERROR] All --horizons values must be positive integers.")
        return 1

    from_ts = _parse_ts(args.from_ts) if args.from_ts else None
    to_ts = _parse_ts(args.to_ts) if args.to_ts else None

    conn = get_db_connection()
    try:
        # Discover candle schema robustly
        candle_cols = _discover_candle_columns(conn)
        has_high = "high_price" in candle_cols
        has_low = "low_price" in candle_cols

        print(
            f"[INFO] candle columns discovered  has_high={has_high}  has_low={has_low}"
        )

        # BTC asset_id for global context
        btc_id = _fetch_btc_asset_id(conn)
        if btc_id is None:
            print("[WARN] BTC asset_id not found — BTC context will be null.")

        # Fetch distinct snapshot timestamps
        snapshots = fetch_snapshots(
            conn,
            venue=args.venue,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=args.limit_snapshots,
        )
        if not snapshots:
            print("[ERROR] No selection_state snapshots found for the given filters.")
            return 1

        print(
            f"[INFO] snapshots={len(snapshots)}"
            f"  from={snapshots[0].isoformat()}"
            f"  to={snapshots[-1].isoformat()}"
        )

        # Fetch all selection_state rows for those snapshots
        sel_rows = fetch_selection_rows(conn, venue=args.venue, snapshot_ts_list=snapshots)
        if not sel_rows:
            print("[ERROR] No selection_state rows found for the discovered snapshots.")
            return 1

        print(f"[INFO] selection_state rows={len(sel_rows)}")

        # Determine asset_id set for bulk candle fetch
        asset_ids: list[int] = sorted({int(r["asset_id"]) for r in sel_rows})
        if btc_id is not None and btc_id not in asset_ids:
            asset_ids = sorted(asset_ids + [btc_id])

        max_horizon = max(horizons)
        candle_from = snapshots[0] - timedelta(hours=72)
        candle_to = snapshots[-1] + timedelta(hours=max_horizon + 24)

        print(
            f"[INFO] fetching candles  assets={len(asset_ids)}"
            f"  interval={args.interval_code}"
            f"  window=[{candle_from.isoformat()}, {candle_to.isoformat()}]"
        )
        candles_by_asset = fetch_candles(
            conn,
            venue=args.venue,
            interval_code=args.interval_code,
            asset_ids=asset_ids,
            from_ts=candle_from,
            to_ts=candle_to,
            has_high=has_high,
            has_low=has_low,
        )
        total_candles = sum(len(v) for v in candles_by_asset.values())
        print(f"[INFO] candles loaded={total_candles}")

        # Optional table data (fetched once, keyed by (asset_id, asof_ts))
        ts_set = list({r["asof_ts_utc"] for r in sel_rows})
        aid_set = asset_ids

        filter_data = fetch_optional_filter(conn, venue=args.venue, asset_ids=aid_set, ts_list=ts_set)
        policy_data = fetch_optional_policy(conn, venue=args.venue, asset_ids=aid_set, ts_list=ts_set)
        advice_data = fetch_optional_advice(
            conn, venue=args.venue, interval_code=args.interval_code,
            asset_ids=aid_set, ts_list=ts_set,
        )

        print(
            f"[INFO] optional rows  filter={len(filter_data)}"
            f"  policy={len(policy_data)}"
            f"  advice={len(advice_data)}"
        )

        # ----------------------------------------------------------------
        # Core computation pass
        # ----------------------------------------------------------------
        run_ts = datetime.now(UTC).replace(tzinfo=None)

        # Per (asof_ts, asset_class) → list of asset_return_24h values
        # (independent of horizon; computed once and reused)
        asset_returns_by_ts_class: dict[tuple[datetime, str], list[float]] = defaultdict(list)
        asset_return_map: dict[tuple[int, datetime], float | None] = {}

        for ss in sel_rows:
            asset_id = int(ss["asset_id"])
            asof_ts: datetime = ss["asof_ts_utc"]
            symbol: str = str(ss["symbol"])
            asset_class = classify_asset_class(symbol)
            a_candles = candles_by_asset.get(asset_id, [])

            current_price = _price_before(a_candles, asof_ts)
            price_24h_ago = _price_before(a_candles, asof_ts - timedelta(hours=24))
            asset_24h = _pct(current_price, price_24h_ago)

            asset_return_map[(asset_id, asof_ts)] = asset_24h
            if asset_class != "BTC" and asset_24h is not None:
                asset_returns_by_ts_class[(asof_ts, asset_class)].append(asset_24h)

        # Class avg return per (asof_ts, asset_class)
        class_return_avg: dict[tuple[datetime, str], float] = {
            k: mean(v) for k, v in asset_returns_by_ts_class.items() if v
        }

        # Avg alt (non-BTC) return per asof_ts (for global regime rotation detection)
        alt_return_by_ts: dict[datetime, list[float]] = defaultdict(list)
        for (ts, ac), vals in asset_returns_by_ts_class.items():
            if ac != "BTC":
                alt_return_by_ts[ts].extend(vals)
        avg_alt_by_ts: dict[datetime, float] = {
            ts: mean(v) for ts, v in alt_return_by_ts.items() if v
        }

        # BTC 24h and 72h context per snapshot ts
        btc_context: dict[datetime, tuple[float | None, float | None]] = {}
        if btc_id is not None:
            btc_candles = candles_by_asset.get(btc_id, [])
            for snap_ts in snapshots:
                btc_now = _price_before(btc_candles, snap_ts)
                btc_24h_ago = _price_before(btc_candles, snap_ts - timedelta(hours=24))
                btc_72h_ago = _price_before(btc_candles, snap_ts - timedelta(hours=72))
                b24 = _pct(btc_now, btc_24h_ago)
                b72 = _pct(btc_now, btc_72h_ago)
                btc_context[snap_ts] = (b24, b72)

        # Build all observations (one per ss_row × horizon × selector_mode)
        all_obs: list[dict] = []
        skipped = 0

        for ss in sel_rows:
            asset_id = int(ss["asset_id"])
            asof_ts = ss["asof_ts_utc"]
            symbol = str(ss["symbol"])
            asset_class = classify_asset_class(symbol)
            a_candles = candles_by_asset.get(asset_id, [])

            current_price = _price_before(a_candles, asof_ts)
            if current_price is None:
                skipped += 1
                continue

            base_ts = _ts_before(a_candles, asof_ts)
            btc_24h, btc_72h = btc_context.get(asof_ts, (None, None))
            asset_24h = asset_return_map.get((asset_id, asof_ts))
            class_24h = class_return_avg.get((asof_ts, asset_class))
            avg_alt = avg_alt_by_ts.get(asof_ts)

            rel_class_vs_btc = (
                (class_24h - btc_24h) if class_24h is not None and btc_24h is not None else None
            )

            global_regime = classify_global_regime(btc_24h, avg_alt)
            class_regime = classify_class_regime(class_24h, btc_24h)
            global_class_regime = f"{global_regime}|{class_regime}"

            # Optional table join (advice > policy > filter precedence)
            key = (asset_id, asof_ts)
            adv = advice_data.get(key, {})
            pol = policy_data.get(key, {})
            flt = filter_data.get(key, {})

            setup_filter_state = (
                adv.get("setup_filter_state")
                or pol.get("setup_filter_state")
                or flt.get("setup_filter_state")
            )
            setup_filter_reason = (
                adv.get("setup_filter_reason")
                or pol.get("setup_filter_reason")
                or flt.get("setup_filter_reason")
            )
            policy_decision = adv.get("policy_decision") or pol.get("policy_decision")
            advice_state = adv.get("advice_state")
            advice_action = adv.get("advice_action")
            aplus_bucket = adv.get("aplus_bucket")

            strategy_signature = make_strategy_signature(
                ss.get("selection_state"),
                setup_filter_state,
                policy_decision,
                advice_state,
                aplus_bucket,
            )

            source_ref = {
                "scope": "research-only market-only account-agnostic",
                "broker_calls": 0,
                "broker_writes": 0,
                "order_submission": 0,
                "live_orders": 0,
                "report_name": REPORT_NAME,
                "report_version": REPORT_VERSION,
                "run_ts_utc": run_ts.isoformat(sep=" "),
                "venue": args.venue,
                "interval_code": args.interval_code,
            }
            source_ref_json = json.dumps(source_ref, ensure_ascii=False, default=_json_default)

            for horizon in horizons:
                future_target_ts = asof_ts + timedelta(hours=horizon)
                future_ts = _ts_after(a_candles, future_target_ts)
                future_price = _price_after(a_candles, future_target_ts)

                forward_return_pct: float | None = None
                if future_price is not None and current_price > 0:
                    forward_return_pct = float((future_price / current_price) - 1) * 100.0

                mfe_pct: float | None = None
                mae_pct: float | None = None
                if has_high and has_low and base_ts is not None and future_ts is not None:
                    mfe_d, mae_d = _mfe_mae(a_candles, base_ts, future_ts, current_price)
                    mfe_pct = float(mfe_d) if mfe_d is not None else None
                    mae_pct = float(mae_d) if mae_d is not None else None

                base_obs = {
                    "report_name": REPORT_NAME,
                    "report_version": REPORT_VERSION,
                    "run_ts_utc": run_ts,
                    "asset_id": asset_id,
                    "symbol": symbol,
                    "venue": str(ss["venue"]),
                    "interval_code": args.interval_code,
                    "asof_ts_utc": asof_ts,
                    "horizon_hours": horizon,
                    "current_price": current_price,
                    "future_price": future_price,
                    "forward_return_pct": forward_return_pct,
                    "mfe_pct": mfe_pct,
                    "mae_pct": mae_pct,
                    "btc_return_24h_pct": btc_24h,
                    "btc_return_72h_pct": btc_72h,
                    "asset_return_24h_pct": asset_24h,
                    "class_return_24h_pct": class_24h,
                    "relative_class_vs_btc_24h_pct": rel_class_vs_btc,
                    "asset_class": asset_class,
                    "global_regime": global_regime,
                    "asset_class_regime": class_regime,
                    "global_class_regime": global_class_regime,
                    "strategy_signature": strategy_signature,
                    "selection_state": ss.get("selection_state"),
                    "selection_bias": ss.get("selection_bias"),
                    "selection_score": ss.get("selection_score"),
                    "priority_rank": ss.get("priority_rank"),
                    "setup_filter_state": setup_filter_state,
                    "setup_filter_reason": setup_filter_reason,
                    "policy_decision": policy_decision,
                    "advice_state": advice_state,
                    "advice_action": advice_action,
                    "aplus_bucket": aplus_bucket,
                    "source_ref_json": source_ref_json,
                }

                for mode in selector_modes:
                    all_obs.append({**base_obs, "selector_mode": mode})

        print(
            f"[INFO] observations built={len(all_obs)}"
            f"  skipped_no_candle={skipped}"
            f"  horizons={horizons}"
            f"  selector_modes={selector_modes}"
        )

        if not all_obs:
            print("[ERROR] No observations produced — check candle data availability.")
            return 1

        # ----------------------------------------------------------------
        # Output
        # ----------------------------------------------------------------
        if args.output == "table":
            print_all_tables(
                all_obs=all_obs,
                horizons=horizons,
                selector_modes=selector_modes,
                min_group_n=args.min_group_n,
                limit_groups=args.limit_groups,
            )
        elif args.output == "json":
            # JSON aggregate summary (not raw rows)
            summary: dict[str, Any] = {}
            mode_key_map = {
                "GLOBAL": "global_regime",
                "ASSET_CLASS": "asset_class_regime",
                "GLOBAL_CLASS": "global_class_regime",
                "STRATEGY_SIGNATURE": "strategy_signature",
            }
            for horizon in horizons:
                h_obs = [o for o in all_obs if o["horizon_hours"] == horizon]
                summary[f"horizon_{horizon}h"] = {}
                for mode in selector_modes:
                    dim_key = mode_key_map.get(mode, mode.lower())
                    mode_obs = [o for o in h_obs if o["selector_mode"] == mode]
                    agg = _aggregate(mode_obs, dim_key)
                    summary[f"horizon_{horizon}h"][mode] = {
                        k: v for k, v in agg.items()
                        if v["n_with_return"] >= args.min_group_n
                    }
            print(json.dumps(summary, indent=2, default=_json_default))

        # ----------------------------------------------------------------
        # DB write
        # ----------------------------------------------------------------
        if args.write_db:
            written = upsert_rows(conn, all_obs)
            print(f"\n[DONE] wrote rows={written} table={OUTPUT_TABLE}")
        else:
            print(f"\n[DONE] dry-run (use --write-db to persist)  obs={len(all_obs)}")

        print(
            "\n[SAFETY]"
            " broker_calls=0"
            " broker_writes=0"
            " order_submission=0"
            " live_orders=0"
        )
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
