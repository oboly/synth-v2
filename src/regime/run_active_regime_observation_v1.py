from __future__ import annotations

"""
Synth v2 - Active Regime Observation V1.

LAYER: regime (market-only)

BOUNDARY:
  Market-only. Account-agnostic. No paper/live distinction.
  Reads obs_market_candle and asset metadata only.
  Writes to active_regime_observation only when --write-db is given.
  No broker calls. No orders. No selection_engine changes.
  No decision_gate. No execution_planner. No executor.
  No policy routing. No buy/sell advice.

Purpose:
  Classify and record current global and asset-class regime state for
  downstream research and future policy routing (not yet implemented).

  Validated hypothesis:
    H1 BTC_MILD_DECLINE_4H_BOUNCE — PROMISING_REPEATED across 6/7 weekly windows.
    Tagged as H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT when GLOBAL_BTC_MILD_DECLINE.
    Tag is context only, not an entry rule or routing instruction.

  Blocked hypotheses (H2–H5) are not tagged. They may be added in a future
  version when their validation status changes.

Usage:
  python -m src.regime.run_active_regime_observation_v1 [OPTIONS]

Options:
  --venue            Exchange venue (default: bitvavo)
  --interval         Candle interval (default: 4h)
  --asof-ts          Observation timestamp (ISO format, default: now)
  --lookback-hours   Candle window before asof_ts (default: 96)
  --write-db         Write observations to active_regime_observation
  --output           table (default) or json
"""

import argparse
import bisect
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_connection

load_dotenv()

UTC = timezone.utc

GLOBAL_REGIME_VERSION = "1.1"
CLASS_REGIME_VERSION = "1.1"
OUTPUT_TABLE = "active_regime_observation"

# ---------------------------------------------------------------------------
# Asset class classification — identical to run_regime_selector_backtest_v1.py
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
# Regime classification — v1.1 semantics, explicit ordering to avoid overlap bugs
# ---------------------------------------------------------------------------

def classify_global_regime(btc_24h: float | None, avg_alt_24h: float | None) -> str:
    # Order is mandatory — several ranges overlap; wrong order silently mislabels.
    # Rule 1: null guard — GLOBAL_UNKNOWN must only mean missing data.
    if btc_24h is None:
        return "GLOBAL_UNKNOWN"
    # Rule 2
    if btc_24h < -0.05:
        return "GLOBAL_BTC_BREAKDOWN"
    # Rule 3 — the H1-validated label
    if -0.05 <= btc_24h < -0.01:
        return "GLOBAL_BTC_MILD_DECLINE"
    # Rule 4
    if -0.01 <= btc_24h <= 0.01:
        return "GLOBAL_NEUTRAL"
    # Rule 5 — must precede RISK_ON (>0.08 is a subset of >0.01)
    if btc_24h > 0.08:
        return "GLOBAL_BTC_OVERHEATED"
    # Rule 6 — must precede RISK_ON
    if avg_alt_24h is not None and btc_24h < 0.04 and (avg_alt_24h - btc_24h) > 0.04:
        return "GLOBAL_ROTATION_WINDOW"
    # Rule 7 — catch-all for positive BTC
    if btc_24h > 0.01:
        return "GLOBAL_RISK_ON"
    # Rule 8 — should not be reached with valid data after rules 1-7
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


def make_hypothesis_tags(global_regime: str) -> list[str]:
    # H1 is the only validated hypothesis. Tag is context, not advice.
    if global_regime == "GLOBAL_BTC_MILD_DECLINE":
        return ["H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT"]
    return []


def make_validation_status(global_regime: str) -> str:
    if global_regime == "GLOBAL_BTC_MILD_DECLINE":
        return "H1_CONTEXT_VALIDATED"
    return "OBSERVED_UNVALIDATED_CONTEXT"


# ---------------------------------------------------------------------------
# Candle helpers
# ---------------------------------------------------------------------------

def _interval_hours(interval_code: str) -> int:
    mapping = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "8h": 8, "12h": 12, "1d": 24}
    return mapping.get(interval_code.lower(), 4)


def _candle_before(candles: list[dict], ts: datetime) -> dict | None:
    """Return the latest candle with close_ts_utc <= ts."""
    times = [c["close_ts_utc"] for c in candles]
    idx = bisect.bisect_right(times, ts) - 1
    return candles[idx] if idx >= 0 else None


def _price_at(candles: list[dict], ts: datetime) -> float | None:
    c = _candle_before(candles, ts)
    if c is None:
        return None
    return float(c["close_price"])


def _return_between(candles: list[dict], from_ts: datetime, to_ts: datetime) -> float | None:
    p_from = _price_at(candles, from_ts)
    p_to = _price_at(candles, to_ts)
    if p_from is None or p_to is None or p_from == 0:
        return None
    return (p_to - p_from) / p_from


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _f(v: Any, decimals: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return f"{v:+.{decimals}f}"
    return str(v)


def _print_table(title: str, columns: list[str], rows: list[dict]) -> None:
    print(f"\n--- {title} ---")
    if not rows:
        print("  (no rows)")
        return
    widths = {c: max(len(c), max((len(str(r.get(c, "—"))) for r in rows), default=0))
              for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(str(row.get(c, "—")).ljust(widths[c]) for c in columns))


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def build_observations(
    conn: Any,
    venue: str,
    interval_code: str,
    asof_ts: datetime,
    lookback_hours: int,
) -> list[dict]:
    interval_h = _interval_hours(interval_code)
    window_start = asof_ts - timedelta(hours=lookback_hours)
    # Need extra buffer for 72h return lookback
    candle_from = asof_ts - timedelta(hours=max(lookback_hours, 96))
    candle_to = asof_ts + timedelta(hours=1)

    # Fetch all assets tracked in obs_market_candle for this venue/interval
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT a.asset_id, a.symbol
            FROM obs_market_candle omc
            JOIN asset a ON a.asset_id = omc.asset_id
            WHERE omc.venue = %s AND omc.interval_code = %s
              AND omc.close_ts_utc >= %s
        """, (venue, interval_code, window_start))
        assets = cur.fetchall()

    if not assets:
        print(f"[WARN] no assets found for venue={venue} interval={interval_code}")
        return []

    asset_ids = [r["asset_id"] for r in assets]
    symbol_map = {r["asset_id"]: r["symbol"] for r in assets}

    # Bulk-fetch all candles in the window for all assets
    fmt = ",".join(["%s"] * len(asset_ids))
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT asset_id, close_ts_utc, close_price
            FROM obs_market_candle
            WHERE venue = %s AND interval_code = %s
              AND close_ts_utc BETWEEN %s AND %s
              AND asset_id IN ({fmt})
            ORDER BY asset_id, close_ts_utc
        """, (venue, interval_code, candle_from, candle_to) + tuple(asset_ids))
        all_candle_rows = cur.fetchall()

    # Organise candles per asset — sorted by close_ts_utc for binary search
    candles_by_asset: dict[int, list[dict]] = {}
    for row in all_candle_rows:
        aid = row["asset_id"]
        candles_by_asset.setdefault(aid, []).append(row)

    # Compute 24h and 72h returns for each asset at asof_ts
    ts_24h_ago = asof_ts - timedelta(hours=24)
    ts_72h_ago = asof_ts - timedelta(hours=72)

    asset_24h: dict[int, float | None] = {}
    asset_72h: dict[int, float | None] = {}
    asset_candle_ts: dict[int, datetime | None] = {}

    for aid in asset_ids:
        clist = candles_by_asset.get(aid, [])
        asset_24h[aid] = _return_between(clist, ts_24h_ago, asof_ts)
        asset_72h[aid] = _return_between(clist, ts_72h_ago, asof_ts)
        latest = _candle_before(clist, asof_ts)
        asset_candle_ts[aid] = latest["close_ts_utc"] if latest else None

    # BTC returns
    btc_aid: int | None = None
    for aid, sym in symbol_map.items():
        if sym.upper() == "BTC":
            btc_aid = aid
            break

    btc_24h_ret = asset_24h.get(btc_aid) if btc_aid is not None else None
    btc_72h_ret = asset_72h.get(btc_aid) if btc_aid is not None else None
    btc_candle_ts = asset_candle_ts.get(btc_aid) if btc_aid is not None else None

    # Class membership and per-class returns
    class_assets: dict[str, list[int]] = {}
    for aid, sym in symbol_map.items():
        ac = classify_asset_class(sym)
        class_assets.setdefault(ac, []).append(aid)

    class_return_24h: dict[str, float | None] = {}
    for ac, aids in class_assets.items():
        vals = [asset_24h[a] for a in aids if asset_24h.get(a) is not None]
        class_return_24h[ac] = (sum(vals) / len(vals)) if vals else None

    # avg_alt_return_24h — all non-BTC assets
    alt_vals = [
        asset_24h[a]
        for a, sym in symbol_map.items()
        if sym.upper() != "BTC" and asset_24h.get(a) is not None
    ]
    avg_alt_24h = (sum(alt_vals) / len(alt_vals)) if alt_vals else None

    # Global regime (one value for this entire snapshot)
    global_regime = classify_global_regime(btc_24h_ret, avg_alt_24h)
    hyp_tags = make_hypothesis_tags(global_regime)
    val_status = make_validation_status(global_regime)

    source_ref = {
        "scope": "market-only account-agnostic active regime observation",
        "broker_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "live_orders": 0,
        "policy_router": "not_implemented",
        "selection_engine_changes": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor_changes": 0,
        "validated_hypotheses": ["H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT"],
    }

    # Build one row per asset class
    rows: list[dict] = []
    for ac in sorted(class_assets.keys()):
        aids = class_assets[ac]
        class_24h = class_return_24h.get(ac)
        rel = (class_24h - btc_24h_ret) if (class_24h is not None and btc_24h_ret is not None) else None
        class_regime = classify_class_regime(class_24h, btc_24h_ret)
        cross = f"{global_regime}|{class_regime}"

        rows.append({
            "venue":                       venue,
            "interval_code":               interval_code,
            "asof_ts_utc":                 asof_ts,
            "source_candle_ts_utc":        btc_candle_ts,
            "asset_class":                 ac,
            "asset_count":                 len(aids),
            "global_regime":               global_regime,
            "global_regime_version":       GLOBAL_REGIME_VERSION,
            "btc_return_24h_pct":          btc_24h_ret,
            "btc_return_72h_pct":          btc_72h_ret,
            "avg_alt_return_24h_pct":      avg_alt_24h,
            "asset_class_regime":          class_regime,
            "asset_class_regime_version":  CLASS_REGIME_VERSION,
            "class_return_24h_pct":        class_24h,
            "relative_class_vs_btc_24h_pct": rel,
            "global_class_regime":         cross,
            "validated_hypothesis_tags_json": json.dumps(hyp_tags),
            "validation_status":           val_status,
            "source_ref_json":             json.dumps(source_ref),
        })

    return rows


def write_observations(conn: Any, rows: list[dict]) -> int:
    if not rows:
        return 0

    sql = f"""
        INSERT INTO {OUTPUT_TABLE} (
            venue, interval_code, asof_ts_utc, source_candle_ts_utc,
            asset_class, asset_count,
            global_regime, global_regime_version,
            btc_return_24h_pct, btc_return_72h_pct, avg_alt_return_24h_pct,
            asset_class_regime, asset_class_regime_version,
            class_return_24h_pct, relative_class_vs_btc_24h_pct,
            global_class_regime,
            validated_hypothesis_tags_json, validation_status,
            source_ref_json
        ) VALUES (
            %(venue)s, %(interval_code)s, %(asof_ts_utc)s, %(source_candle_ts_utc)s,
            %(asset_class)s, %(asset_count)s,
            %(global_regime)s, %(global_regime_version)s,
            %(btc_return_24h_pct)s, %(btc_return_72h_pct)s, %(avg_alt_return_24h_pct)s,
            %(asset_class_regime)s, %(asset_class_regime_version)s,
            %(class_return_24h_pct)s, %(relative_class_vs_btc_24h_pct)s,
            %(global_class_regime)s,
            %(validated_hypothesis_tags_json)s, %(validation_status)s,
            %(source_ref_json)s
        )
        ON DUPLICATE KEY UPDATE
            source_candle_ts_utc           = VALUES(source_candle_ts_utc),
            asset_count                    = VALUES(asset_count),
            global_regime                  = VALUES(global_regime),
            btc_return_24h_pct             = VALUES(btc_return_24h_pct),
            btc_return_72h_pct             = VALUES(btc_return_72h_pct),
            avg_alt_return_24h_pct         = VALUES(avg_alt_return_24h_pct),
            asset_class_regime             = VALUES(asset_class_regime),
            class_return_24h_pct           = VALUES(class_return_24h_pct),
            relative_class_vs_btc_24h_pct  = VALUES(relative_class_vs_btc_24h_pct),
            global_class_regime            = VALUES(global_class_regime),
            validated_hypothesis_tags_json = VALUES(validated_hypothesis_tags_json),
            validation_status              = VALUES(validation_status),
            source_ref_json                = VALUES(source_ref_json)
    """

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, row)
    conn.commit()
    return len(rows)


def print_table_output(rows: list[dict]) -> None:
    if not rows:
        print("  (no observations built)")
        return

    # Summary line
    global_regime = rows[0]["global_regime"] if rows else "—"
    btc_24h = rows[0]["btc_return_24h_pct"]
    print(f"\n[INFO] asof_ts={rows[0]['asof_ts_utc'].isoformat() if hasattr(rows[0]['asof_ts_utc'], 'isoformat') else rows[0]['asof_ts_utc']}")
    print(f"[INFO] global_regime={global_regime}  btc_24h={_f(btc_24h if btc_24h else None, 4)}")
    print(f"[INFO] rows_built={len(rows)}")

    cols = [
        "asset_class", "asset_count", "global_regime",
        "asset_class_regime", "global_class_regime",
        "btc_24h%", "class_24h%", "rel_vs_btc%",
        "hyp_tags", "validation_status",
    ]
    display_rows = []
    for r in rows:
        tags = json.loads(r["validated_hypothesis_tags_json"] or "[]")
        display_rows.append({
            "asset_class":       r["asset_class"],
            "asset_count":       str(r["asset_count"]),
            "global_regime":     r["global_regime"],
            "asset_class_regime":r["asset_class_regime"],
            "global_class_regime":r["global_class_regime"],
            "btc_24h%":          _f(r["btc_return_24h_pct"], 3),
            "class_24h%":        _f(r["class_return_24h_pct"], 3),
            "rel_vs_btc%":       _f(r["relative_class_vs_btc_24h_pct"], 3),
            "hyp_tags":          str(tags),
            "validation_status": r["validation_status"],
        })
    _print_table("Active regime observation", cols, display_rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Active regime observation v1 (market-only, account-agnostic)"
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--asof-ts", default=None,
                        help="Observation timestamp (ISO format, default: now UTC)")
    parser.add_argument("--lookback-hours", type=int, default=96)
    parser.add_argument("--write-db", action="store_true",
                        help="Write observations to active_regime_observation table")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    args = parser.parse_args()

    if args.asof_ts:
        asof_ts = datetime.fromisoformat(args.asof_ts).replace(tzinfo=None)
    else:
        asof_ts = datetime.now(UTC).replace(tzinfo=None)

    conn = get_connection()
    try:
        rows = build_observations(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            asof_ts=asof_ts,
            lookback_hours=args.lookback_hours,
        )

        if args.output == "json":
            def _ser(obj: Any) -> Any:
                if isinstance(obj, datetime):
                    return obj.isoformat()
                if isinstance(obj, Decimal):
                    return float(obj)
                raise TypeError(type(obj))
            print(json.dumps(rows, indent=2, default=_ser))
        else:
            print_table_output(rows)

        if args.write_db:
            written = write_observations(conn, rows)
            print(f"\n[DONE] wrote rows={written} table={OUTPUT_TABLE}")
        else:
            print(f"\n[DRY-RUN] rows_built={len(rows)} (use --write-db to persist)")

    finally:
        conn.close()

    print(
        "\n[SAFETY]"
        " broker_calls=0"
        " broker_writes=0"
        " order_submission=0"
        " live_orders=0"
        " selection_engine_changes=0"
        " decision_gate_changes=0"
        " execution_planner_changes=0"
        " executor_changes=0"
    )


if __name__ == "__main__":
    main()
