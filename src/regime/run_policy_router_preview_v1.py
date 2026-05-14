from __future__ import annotations

"""
Synth v2 - Policy Router Preview V1.

LAYER: regime (market-only)

BOUNDARY:
  Market-only. Account-agnostic. No paper/live distinction.
  Reads active_regime_observation, asset, and selection_state only.
  Writes to policy_router_preview_observation only when --write-db is given.
  No broker calls. No orders. No account state. No balances. No positions.
  No selection_engine changes. No advice_engine changes.
  No decision_gate. No execution_planner. No executor.
  Route output is a research-only preview — not permission, not execution intent.

Purpose:
  Map active market regime context to a research-only route candidate per asset.
  Only one route can become ROUTE_CANDIDATE in v1:

    ROUTE_GBMD_4H_BOUNCE_CONTEXT
      Condition: global_regime = GLOBAL_BTC_MILD_DECLINE
                 AND H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT tag is present
      Meaning:   Market context consistent with H1-validated short-window bounce
                 observation. Does NOT mean buy, hold, or entry permission.

  All other assets receive ROUTE_NO_MATCH.
  H2–H5 routes are explicitly blocked.

Usage:
  python -m src.regime.run_policy_router_preview_v1 [OPTIONS]

Options:
  --venue        Exchange venue (default: bitvavo)
  --interval     Candle interval (default: 4h)
  --asof-ts      Observation timestamp ISO format (default: latest ARO snapshot)
  --write-db     Write rows to policy_router_preview_observation
  --output       table (default) | json
"""

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_connection

load_dotenv()

UTC = timezone.utc

ROUTE_VERSION = "1.0"
OUTPUT_TABLE = "policy_router_preview_observation"

_SOURCE_REF = {
    "scope": "market-only account-agnostic policy router preview",
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate_changes": 0,
    "execution_planner_changes": 0,
    "executor_changes": 0,
    "selection_engine_changes": 0,
    "advice_engine_changes": 0,
    "paper_live_logic": "not_allowed",
    "account_state": "not_allowed",
    "route_is_permission": False,
    "route_is_order_intent": False,
}

# ---------------------------------------------------------------------------
# Asset class classification — identical to run_active_regime_observation_v1
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
# Route logic
# ---------------------------------------------------------------------------

_CANDIDATE_REASON_CODES = [
    "H1_PROMISING_REPEATED",
    "GLOBAL_BTC_MILD_DECLINE",
    "MARKET_ONLY_CONTEXT",
    "NOT_PERMISSION",
    "NOT_ORDER_INTENT",
]
_NO_MATCH_REASON_CODES = [
    "NO_VALIDATED_ROUTE_MATCH",
    "MARKET_ONLY_CONTEXT",
    "NOT_PERMISSION",
    "NOT_ORDER_INTENT",
]
_CANDIDATE_ALLOWED_FAMILIES = ["BOUNCE_RECLAIM_SHORT_WINDOW"]
_CANDIDATE_BLOCKED_FAMILIES = [
    "SWING_CONTINUATION",
    "LONG_HORIZON_HOLD",
    "BREAKOUT_FOLLOW_WITHOUT_CONFIRMATION",
]


def _is_h1_active(global_regime: str, hyp_tags: list[str]) -> bool:
    return (
        global_regime == "GLOBAL_BTC_MILD_DECLINE"
        and "H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT" in hyp_tags
    )


def build_route_row(
    venue: str,
    interval_code: str,
    asof_ts: datetime,
    asset: dict,
    aro_row: dict | None,
    sel_ref: dict | None,
) -> dict:
    regime_asset_class = classify_asset_class(asset["symbol"])

    if aro_row is not None:
        global_regime = aro_row["global_regime"]
        asset_class_regime = aro_row["asset_class_regime"]
        global_class_regime = aro_row["global_class_regime"]
        hyp_tags = json.loads(aro_row["validated_hypothesis_tags_json"] or "[]")
        aro_id = aro_row["active_regime_observation_id"]
    else:
        global_regime = "GLOBAL_UNKNOWN"
        asset_class_regime = "CLASS_UNKNOWN"
        global_class_regime = "GLOBAL_UNKNOWN|CLASS_UNKNOWN"
        hyp_tags = []
        aro_id = None

    if _is_h1_active(global_regime, hyp_tags):
        route_code = "ROUTE_GBMD_4H_BOUNCE_CONTEXT"
        route_status = "ROUTE_CANDIDATE"
        route_confidence = Decimal("0.575000")
        reason_codes = _CANDIDATE_REASON_CODES
        allowed_families = _CANDIDATE_ALLOWED_FAMILIES
        blocked_families = _CANDIDATE_BLOCKED_FAMILIES
    else:
        route_code = "ROUTE_NO_MATCH"
        route_status = "ROUTE_NO_MATCH"
        route_confidence = Decimal("0.000000")
        reason_codes = _NO_MATCH_REASON_CODES
        allowed_families = []
        blocked_families = []

    source_sel_ref = None
    if sel_ref is not None:
        source_sel_ref = json.dumps({
            "selection_state_id": sel_ref["selection_state_id"],
            "asof_ts_utc": sel_ref["asof_ts_utc"].isoformat()
                if hasattr(sel_ref["asof_ts_utc"], "isoformat") else str(sel_ref["asof_ts_utc"]),
            "selection_state": sel_ref.get("selection_state"),
            "selection_score": float(sel_ref["selection_score"])
                if sel_ref.get("selection_score") is not None else None,
        })

    return {
        "venue":          venue,
        "interval_code":  interval_code,
        "asof_ts_utc":    asof_ts,
        "asset_id":       asset["asset_id"],
        "symbol":         asset["symbol"],
        "asset_class":    regime_asset_class,
        "source_active_regime_observation_id": aro_id,
        "source_selection_state_ref_json":     source_sel_ref,
        "source_strategy_state_ref_json":      None,
        "route_code":              route_code,
        "route_version":           ROUTE_VERSION,
        "route_status":            route_status,
        "route_confidence":        route_confidence,
        "route_reason_codes_json": json.dumps(reason_codes),
        "global_regime":                  global_regime,
        "asset_class_regime":             asset_class_regime,
        "global_class_regime":            global_class_regime,
        "validated_hypothesis_tags_json": json.dumps(hyp_tags),
        "allowed_policy_family_json":     json.dumps(allowed_families),
        "blocked_policy_family_json":     json.dumps(blocked_families),
        "source_ref_json":                json.dumps(_SOURCE_REF),
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _load_aro_snapshot(
    conn: Any,
    venue: str,
    interval_code: str,
    asof_ts: datetime | None,
) -> tuple[datetime | None, dict[str, dict]]:
    """Return (snapshot_ts, {asset_class: aro_row})."""
    with conn.cursor() as cur:
        if asof_ts is not None:
            cur.execute("""
                SELECT *
                FROM active_regime_observation
                WHERE venue = %s AND interval_code = %s AND asof_ts_utc = %s
            """, (venue, interval_code, asof_ts))
        else:
            cur.execute("""
                SELECT *
                FROM active_regime_observation
                WHERE venue = %s AND interval_code = %s
                  AND asof_ts_utc = (
                      SELECT MAX(asof_ts_utc)
                      FROM active_regime_observation
                      WHERE venue = %s AND interval_code = %s
                  )
            """, (venue, interval_code, venue, interval_code))
        rows = cur.fetchall()

    if not rows:
        return None, {}

    snapshot_ts = rows[0]["asof_ts_utc"]
    aro_by_class = {r["asset_class"]: r for r in rows}
    return snapshot_ts, aro_by_class


def _load_assets(conn: Any) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id, symbol
            FROM asset
            WHERE is_enabled = 1 AND is_tradeable = 1
            ORDER BY asset_id
        """)
        return cur.fetchall()


def _load_selection_state_refs(conn: Any, venue: str) -> dict[int, dict]:
    """Load latest selection_state snapshot as a reference dict keyed by asset_id."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT asset_id, selection_state_id, asof_ts_utc, selection_state, selection_score
            FROM selection_state
            WHERE venue = %s
              AND asof_ts_utc = (
                  SELECT MAX(asof_ts_utc) FROM selection_state WHERE venue = %s
              )
        """, (venue, venue))
        rows = cur.fetchall()
    return {r["asset_id"]: r for r in rows}


def build_preview(
    conn: Any,
    venue: str,
    interval_code: str,
    asof_ts: datetime | None,
) -> tuple[datetime | None, list[dict]]:
    snapshot_ts, aro_by_class = _load_aro_snapshot(conn, venue, interval_code, asof_ts)

    if snapshot_ts is None:
        print(f"[WARN] no active_regime_observation rows found for venue={venue} interval={interval_code}")
        return None, []

    assets = _load_assets(conn)
    if not assets:
        print(f"[WARN] no enabled+tradeable assets found")
        return snapshot_ts, []

    sel_refs = _load_selection_state_refs(conn, venue)

    route_rows: list[dict] = []
    for asset in assets:
        regime_class = classify_asset_class(asset["symbol"])
        aro_row = aro_by_class.get(regime_class)
        sel_ref = sel_refs.get(asset["asset_id"])
        row = build_route_row(venue, interval_code, snapshot_ts, asset, aro_row, sel_ref)
        route_rows.append(row)

    return snapshot_ts, route_rows


def write_preview(conn: Any, rows: list[dict]) -> int:
    if not rows:
        return 0

    sql = f"""
        INSERT INTO {OUTPUT_TABLE} (
            venue, interval_code, asof_ts_utc,
            asset_id, symbol, asset_class,
            source_active_regime_observation_id,
            source_selection_state_ref_json,
            source_strategy_state_ref_json,
            route_code, route_version, route_status,
            route_confidence, route_reason_codes_json,
            global_regime, asset_class_regime, global_class_regime,
            validated_hypothesis_tags_json,
            allowed_policy_family_json, blocked_policy_family_json,
            source_ref_json
        ) VALUES (
            %(venue)s, %(interval_code)s, %(asof_ts_utc)s,
            %(asset_id)s, %(symbol)s, %(asset_class)s,
            %(source_active_regime_observation_id)s,
            %(source_selection_state_ref_json)s,
            %(source_strategy_state_ref_json)s,
            %(route_code)s, %(route_version)s, %(route_status)s,
            %(route_confidence)s, %(route_reason_codes_json)s,
            %(global_regime)s, %(asset_class_regime)s, %(global_class_regime)s,
            %(validated_hypothesis_tags_json)s,
            %(allowed_policy_family_json)s, %(blocked_policy_family_json)s,
            %(source_ref_json)s
        )
        ON DUPLICATE KEY UPDATE
            source_active_regime_observation_id = VALUES(source_active_regime_observation_id),
            source_selection_state_ref_json     = VALUES(source_selection_state_ref_json),
            route_code                          = VALUES(route_code),
            route_status                        = VALUES(route_status),
            route_confidence                    = VALUES(route_confidence),
            route_reason_codes_json             = VALUES(route_reason_codes_json),
            global_regime                       = VALUES(global_regime),
            asset_class_regime                  = VALUES(asset_class_regime),
            global_class_regime                 = VALUES(global_class_regime),
            validated_hypothesis_tags_json      = VALUES(validated_hypothesis_tags_json),
            allowed_policy_family_json          = VALUES(allowed_policy_family_json),
            blocked_policy_family_json          = VALUES(blocked_policy_family_json),
            source_ref_json                     = VALUES(source_ref_json)
    """

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, row)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_table(title: str, columns: list[str], rows: list[dict]) -> None:
    print(f"\n--- {title} ---")
    if not rows:
        print("  (no rows)")
        return
    widths = {
        c: max(len(c), max((len(str(r.get(c, "—"))) for r in rows), default=0))
        for c in columns
    }
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(str(row.get(c, "—")).ljust(widths[c]) for c in columns))


def print_table_output(snapshot_ts: datetime | None, rows: list[dict]) -> None:
    if not rows:
        print("  (no preview rows built)")
        return

    ts_str = snapshot_ts.isoformat() if snapshot_ts and hasattr(snapshot_ts, "isoformat") else str(snapshot_ts)
    print(f"\n[INFO] asof_ts={ts_str}")
    print(f"[INFO] rows_built={len(rows)}")

    # Summary counts
    from collections import Counter
    counts = Counter(r["route_status"] for r in rows)
    print("[INFO] route_status counts:")
    for status, n in sorted(counts.items()):
        print(f"       {status}: {n}")

    cols = ["symbol", "asset_class", "global_regime", "asset_class_regime", "route_code", "route_status"]
    display = [
        {
            "symbol":             r["symbol"],
            "asset_class":        r["asset_class"],
            "global_regime":      r["global_regime"],
            "asset_class_regime": r["asset_class_regime"],
            "route_code":         r["route_code"],
            "route_status":       r["route_status"],
        }
        for r in rows
    ]
    _print_table("Policy router preview", cols, display)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Policy router preview v1 (market-only, account-agnostic)"
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--asof-ts", default=None,
                        help="Snapshot timestamp (ISO format). Default: latest ARO snapshot.")
    parser.add_argument("--write-db", action="store_true",
                        help="Write rows to policy_router_preview_observation")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    args = parser.parse_args()

    asof_ts: datetime | None = None
    if args.asof_ts:
        asof_ts = datetime.fromisoformat(args.asof_ts).replace(tzinfo=None)

    conn = get_connection()
    try:
        snapshot_ts, rows = build_preview(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            asof_ts=asof_ts,
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
            print_table_output(snapshot_ts, rows)

        if args.write_db:
            written = write_preview(conn, rows)
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
        " advice_engine_changes=0"
        " decision_gate_changes=0"
        " execution_planner_changes=0"
        " executor_changes=0"
        " route_is_permission=false"
        " route_is_order_intent=false"
    )


if __name__ == "__main__":
    main()
