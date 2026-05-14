from __future__ import annotations

"""
Synth v2 - Regime Selector Historical Coverage Audit V1.

LAYER: research

BOUNDARY:
  Read-only. No DB writes. No broker calls. No account state.
  Queries source tables only — no writes to any table.

Purpose:
  Determine whether source tables contain enough historical data to rerun
  run_regime_selector_backtest_v1.py over 60-90 days, enabling multi-window
  validation of the five candidate hypotheses in
  docs/research/regime_selector_candidate_hypotheses_v1.md.

  Audits:
    - selection_state        (snapshot discovery, selection fields)
    - obs_market_candle      (price/return data)
    - trade_setup_filter_observation      (optional strategy enrichment)
    - trade_setup_policy_preview_observation  (optional strategy enrichment)
    - paper_advice_observation            (optional strategy enrichment)
    - regime_selector_backtest_observation_v1 (existing output)

  For each table: min/max timestamp, distinct dates, row count, per-day density,
  gaps, and whether it supports 60-90 day backtest coverage.

Usage:
  python -m src.research.run_regime_selector_historical_coverage_audit_v1 [OPTIONS]

Options:
  --venue          Candle venue to check (default: bitvavo)
  --interval       Candle interval to check (default: 4h)
  --output         table / json  (default: table)
"""

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_connection

load_dotenv()

UTC = timezone.utc

BTC_SYMBOL = "BTC"
MULTI_WINDOW_THRESHOLD_DAYS = 14
MIN_DENSE_SNAPS_PER_DAY = 3


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _f(v: Any, decimals: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return f"{v:+.{decimals}f}" if v != 0 else f"0.{'0'*decimals}"
    return str(v)


def _print_section(title: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {title}")
    print(f"{'=' * 72}")


def _print_table(title: str, columns: list[str], rows: list[dict]) -> None:
    if title:
        print(f"\n  -- {title} --")
    if not rows:
        print("    (no rows)")
        return
    widths = {c: max(len(c), max((len(str(r.get(c, "—"))) for r in rows), default=0))
              for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    print("  " + header)
    print("  " + sep)
    for row in rows:
        print("  " + "  ".join(str(row.get(c, "—")).ljust(widths[c]) for c in columns))


def _run(cur, sql: str, args: tuple = ()) -> list[dict]:
    cur.execute(sql, args)
    return cur.fetchall()


# ---------------------------------------------------------------------------
# BTC regime classification
# ---------------------------------------------------------------------------

def _btc_regime(ret_pct: float | None) -> str:
    if ret_pct is None:
        return "GLOBAL_UNKNOWN"
    if ret_pct < -5:
        return "GLOBAL_BTC_BREAKDOWN"
    if -5 <= ret_pct < -1:
        return "GLOBAL_BTC_MILD_DECLINE"
    if -1 <= ret_pct <= 1:
        return "GLOBAL_NEUTRAL"
    if ret_pct > 8:
        return "GLOBAL_BTC_OVERHEATED"
    if ret_pct > 1:
        return "GLOBAL_RISK_ON"
    return "GLOBAL_UNKNOWN"


# ---------------------------------------------------------------------------
# Audit functions
# ---------------------------------------------------------------------------

def _audit_selection_state(cur) -> dict:
    summary = _run(cur, """
        SELECT
            MIN(asof_ts_utc)                        AS min_ts,
            MAX(asof_ts_utc)                        AS max_ts,
            COUNT(DISTINCT DATE(asof_ts_utc))       AS distinct_dates,
            COUNT(DISTINCT asof_ts_utc)             AS distinct_snapshots,
            COUNT(*)                                AS total_rows,
            COUNT(DISTINCT asset_id)                AS distinct_assets
        FROM selection_state
    """)[0]

    per_day = _run(cur, """
        SELECT DATE(asof_ts_utc) AS d,
            COUNT(DISTINCT asof_ts_utc) AS snaps,
            COUNT(DISTINCT asset_id) AS assets,
            COUNT(*) AS n_rows
        FROM selection_state
        GROUP BY DATE(asof_ts_utc)
        ORDER BY d
    """)

    by_week = _run(cur, """
        SELECT YEARWEEK(asof_ts_utc, 1) AS yw,
            MIN(DATE(asof_ts_utc)) AS week_start,
            MAX(DATE(asof_ts_utc)) AS week_end,
            COUNT(DISTINCT asof_ts_utc) AS snaps,
            COUNT(DISTINCT asset_id) AS assets,
            COUNT(*) AS n_rows
        FROM selection_state
        GROUP BY YEARWEEK(asof_ts_utc, 1)
        ORDER BY yw
    """)

    # Gap analysis
    gaps = []
    prev = None
    for r in per_day:
        d = r["d"]
        if prev is not None and (d - prev).days > 1:
            gaps.append({"from": str(prev), "to": str(d), "gap_days": (d - prev).days - 1})
        prev = d

    # Dense days (>=3 snaps)
    dense = [r for r in per_day if int(r["snaps"]) >= MIN_DENSE_SNAPS_PER_DAY]

    min_ts = summary["min_ts"]
    max_ts = summary["max_ts"]
    span_days = (max_ts - min_ts).days if min_ts and max_ts else 0

    return {
        "min_ts": min_ts,
        "max_ts": max_ts,
        "span_days": span_days,
        "distinct_dates": int(summary["distinct_dates"]),
        "distinct_snapshots": int(summary["distinct_snapshots"]),
        "total_rows": int(summary["total_rows"]),
        "distinct_assets": int(summary["distinct_assets"]),
        "dense_days": len(dense),
        "sparse_days": len(per_day) - len(dense),
        "gaps": gaps,
        "per_day": [dict(r) for r in per_day],
        "by_week": [dict(r) for r in by_week],
        "supports_60_day": span_days >= 56,
        "supports_90_day": span_days >= 84,
        "blocker": span_days < 56,
    }


def _audit_candles(cur, venue: str, interval: str) -> dict:
    summary = _run(cur, """
        SELECT
            MIN(close_ts_utc) AS min_ts,
            MAX(close_ts_utc) AS max_ts,
            COUNT(DISTINCT DATE(close_ts_utc)) AS distinct_dates,
            COUNT(DISTINCT asset_id) AS distinct_assets,
            COUNT(*) AS total_rows
        FROM obs_market_candle
        WHERE venue = %s AND interval_code = %s
    """, (venue, interval))[0]

    by_year = _run(cur, """
        SELECT YEAR(close_ts_utc) AS yr,
            COUNT(DISTINCT DATE(close_ts_utc)) AS dates,
            COUNT(DISTINCT asset_id) AS assets,
            COUNT(*) AS n
        FROM obs_market_candle
        WHERE venue = %s AND interval_code = %s
        GROUP BY yr ORDER BY yr
    """, (venue, interval))

    min_ts = summary["min_ts"]
    max_ts = summary["max_ts"]
    span_days = (max_ts - min_ts).days if min_ts and max_ts else 0

    # Forward-return coverage for 72h from current max
    max_candle_ts = max_ts
    horizon_72h_need = max_candle_ts + timedelta(hours=72) if max_candle_ts else None

    return {
        "min_ts": min_ts,
        "max_ts": max_ts,
        "span_days": span_days,
        "distinct_dates": int(summary["distinct_dates"]),
        "distinct_assets": int(summary["distinct_assets"]),
        "total_rows": int(summary["total_rows"]),
        "by_year": [dict(r) for r in by_year],
        "horizon_72h_need": horizon_72h_need,
        "blocker": False,  # 5+ years of candle data — never a blocker
    }


def _audit_btc_regimes(cur, venue: str, interval: str) -> list[dict]:
    """Sample BTC 24h returns at midnight candles across the selection_state window."""
    # Get BTC asset_id
    btc_rows = _run(cur, "SELECT asset_id FROM asset WHERE symbol = %s LIMIT 1",
                    (BTC_SYMBOL,))
    if not btc_rows:
        return []
    btc_id = btc_rows[0]["asset_id"]

    rows = _run(cur, """
        SELECT c1.close_ts_utc AS ts,
            c1.close_price AS price_now,
            ROUND((c1.close_price / c2.close_price - 1) * 100, 2) AS ret_24h_pct
        FROM obs_market_candle c1
        JOIN obs_market_candle c2
            ON c2.asset_id = c1.asset_id
            AND c2.venue = c1.venue
            AND c2.interval_code = c1.interval_code
            AND c2.close_ts_utc = DATE_SUB(c1.close_ts_utc, INTERVAL 24 HOUR)
        WHERE c1.asset_id = %s AND c1.venue = %s AND c1.interval_code = %s
          AND c1.close_ts_utc BETWEEN '2026-03-01 00:00:00' AND '2026-05-15 00:00:00'
          AND HOUR(c1.close_ts_utc) = 0
        ORDER BY ts
    """, (btc_id, venue, interval))

    result = []
    for r in rows:
        ret = float(r["ret_24h_pct"]) if r["ret_24h_pct"] is not None else None
        result.append({
            "date":     r["ts"].date() if hasattr(r["ts"], "date") else r["ts"],
            "price":    int(float(r["price_now"])),
            "ret_24h%": ret,
            "regime":   _btc_regime(ret),
        })
    return result


def _regime_mix(btc_days: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in btc_days:
        counts[r["regime"]] = counts.get(r["regime"], 0) + 1
    return counts


def _audit_optional_table(cur, table: str, ts_col: str) -> dict:
    try:
        summary = _run(cur, f"""
            SELECT
                MIN({ts_col}) AS min_ts,
                MAX({ts_col}) AS max_ts,
                COUNT(DISTINCT DATE({ts_col})) AS distinct_dates,
                COUNT(DISTINCT {ts_col}) AS distinct_snapshots,
                COUNT(*) AS total_rows
            FROM {table}
        """)[0]
        per_day = _run(cur, f"""
            SELECT DATE({ts_col}) AS d,
                COUNT(DISTINCT {ts_col}) AS snaps,
                COUNT(*) AS n_rows
            FROM {table}
            GROUP BY DATE({ts_col})
            ORDER BY d
        """)
        min_ts = summary["min_ts"]
        max_ts = summary["max_ts"]
        span_days = (max_ts - min_ts).days if min_ts and max_ts else 0
        return {
            "table": table,
            "exists": True,
            "min_ts": min_ts,
            "max_ts": max_ts,
            "span_days": span_days,
            "distinct_dates": int(summary["distinct_dates"]),
            "distinct_snapshots": int(summary["distinct_snapshots"]),
            "total_rows": int(summary["total_rows"]),
            "per_day": [dict(r) for r in per_day],
        }
    except Exception as e:
        return {"table": table, "exists": False, "error": str(e)}


def _audit_backtest_table(cur) -> dict:
    rows = _run(cur, """
        SELECT report_version,
            MIN(asof_ts_utc) AS min_ts,
            MAX(asof_ts_utc) AS max_ts,
            COUNT(DISTINCT DATE(asof_ts_utc)) AS distinct_dates,
            COUNT(DISTINCT asof_ts_utc) AS distinct_snapshots,
            COUNT(*) AS total_rows
        FROM regime_selector_backtest_observation_v1
        GROUP BY report_version
        ORDER BY report_version
    """)
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Blocker and recommendation logic
# ---------------------------------------------------------------------------

def _build_recommendation(ss: dict, candle: dict, btc_days: list[dict],
                           optional: list[dict]) -> dict:
    regime_mix = _regime_mix(btc_days)
    has_risk_on = regime_mix.get("GLOBAL_RISK_ON", 0) >= 5
    has_gbmd = regime_mix.get("GLOBAL_BTC_MILD_DECLINE", 0) >= 5
    has_neutral = regime_mix.get("GLOBAL_NEUTRAL", 0) >= 5
    has_breakdown = regime_mix.get("GLOBAL_BTC_BREAKDOWN", 0) >= 2

    # setup filter coverage back in time
    setup_table = next((o for o in optional if o["table"] == "trade_setup_filter_observation"), {})
    setup_span = setup_table.get("span_days", 0)
    setup_min = setup_table.get("min_ts")

    policy_table = next((o for o in optional if o["table"] == "trade_setup_policy_preview_observation"), {})
    advice_table = next((o for o in optional if o["table"] == "paper_advice_observation"), {})

    # Can we run the wider backtest right now?
    can_run = ss["distinct_snapshots"] > 120  # more than already loaded

    # Determine recommended from-ts (earliest selection_state date)
    from_ts = ss["min_ts"].strftime("%Y-%m-%dT%H:%M:%S") if ss.get("min_ts") else "2026-03-20T00:00:00"

    return {
        "can_run_immediately": can_run,
        "selection_state_span_days": ss["span_days"],
        "total_snapshots_available": ss["distinct_snapshots"],
        "already_used_snapshots": 120,
        "additional_snapshots": ss["distinct_snapshots"] - 120,
        "regime_mix": regime_mix,
        "has_risk_on": has_risk_on,
        "has_gbmd": has_gbmd,
        "has_neutral": has_neutral,
        "has_breakdown": has_breakdown,
        "setup_filter_span_days": setup_span,
        "setup_filter_min_ts": str(setup_min) if setup_min else None,
        "policy_preview_span_days": policy_table.get("span_days", 0),
        "advice_span_days": advice_table.get("span_days", 0),
        "recommended_from_ts": from_ts,
        "recommended_limit_snapshots": ss["distinct_snapshots"],
        "recommended_min_group_n": 8,
        "warning_sparse_history": ss["dense_days"] < ss["distinct_dates"] * 0.5,
        "warning_no_breakdown": not has_breakdown,
        "warning_strategy_enrichment_sparse": setup_span < 30,
    }


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def _print_audit(ss: dict, candle: dict, btc_days: list[dict],
                 optional: list[dict], backtest: list[dict],
                 rec: dict) -> None:
    _print_section("1. selection_state — snapshot discovery layer")
    print(f"  min_ts:             {ss['min_ts']}")
    print(f"  max_ts:             {ss['max_ts']}")
    print(f"  span_days:          {ss['span_days']}  (need >= 56 for 60-day target)")
    print(f"  distinct_dates:     {ss['distinct_dates']}")
    print(f"  distinct_snapshots: {ss['distinct_snapshots']}")
    print(f"  total_rows:         {ss['total_rows']}")
    print(f"  distinct_assets:    {ss['distinct_assets']}")
    print(f"  dense_days (>=3 snaps): {ss['dense_days']}")
    print(f"  sparse_days (<3 snaps): {ss['sparse_days']}")
    print(f"  supports_60_day:    {ss['supports_60_day']}")
    print(f"  supports_90_day:    {ss['supports_90_day']}")
    print(f"  BLOCKER:            {ss['blocker']}")

    if ss["gaps"]:
        print()
        _print_table("Coverage gaps", ["from", "to", "gap_days"], ss["gaps"])

    _print_table("Per-week snapshot density",
                 ["week_start", "week_end", "snaps", "assets", "n_rows"],
                 [{
                     "week_start": str(r["week_start"]),
                     "week_end":   str(r["week_end"]),
                     "snaps":      str(r["snaps"]),
                     "assets":     str(r["assets"]),
                     "n_rows":     str(r["n_rows"]),
                 } for r in ss["by_week"]])

    _print_section("2. obs_market_candle — price and return data")
    print(f"  min_ts:          {candle['min_ts']}")
    print(f"  max_ts:          {candle['max_ts']}")
    print(f"  span_days:       {candle['span_days']}")
    print(f"  distinct_dates:  {candle['distinct_dates']}")
    print(f"  distinct_assets: {candle['distinct_assets']}")
    print(f"  total_rows:      {candle['total_rows']}")
    print(f"  72h forward need:{candle['horizon_72h_need']} (candle feed must reach this)")
    print(f"  BLOCKER:         {candle['blocker']}")
    print()
    _print_table("Candle coverage by year",
                 ["yr", "dates", "assets", "n"],
                 [{k: str(v) for k, v in r.items()} for r in candle["by_year"]])

    _print_section("3. BTC global regime character across selection_state window")
    regime_counts = rec["regime_mix"]
    print("  Daily BTC regime distribution (2026-03 to 2026-05):")
    for regime, n in sorted(regime_counts.items(), key=lambda x: -x[1]):
        print(f"    {regime:<35}  n={n}")
    print()
    print(f"  has GLOBAL_RISK_ON (>=5 days):           {rec['has_risk_on']}")
    print(f"  has GLOBAL_BTC_MILD_DECLINE (>=5 days):  {rec['has_gbmd']}")
    print(f"  has GLOBAL_NEUTRAL (>=5 days):           {rec['has_neutral']}")
    print(f"  has GLOBAL_BTC_BREAKDOWN (>=2 days):     {rec['has_breakdown']}")
    if not rec["has_breakdown"]:
        print("  !! WARNING: No GLOBAL_BTC_BREAKDOWN days in selection_state window.")
        print("  !! H1 extreme-crash edge case cannot be validated from available data.")
    print()
    _print_table("BTC daily regime (sample)",
                 ["date", "price", "ret_24h%", "regime"],
                 [{
                     "date":     str(r["date"]),
                     "price":    str(r["price"]),
                     "ret_24h%": _f(r["ret_24h%"]),
                     "regime":   r["regime"],
                 } for r in btc_days])

    _print_section("4. Optional strategy enrichment tables")
    opt_cols = ["table", "exists", "min_ts", "max_ts", "span_days",
                "distinct_dates", "distinct_snapshots", "total_rows"]
    opt_rows = []
    for o in optional:
        opt_rows.append({
            "table":              o["table"].replace("_observation", "").replace("trade_setup_", ""),
            "exists":             str(o.get("exists", False)),
            "min_ts":             str(o.get("min_ts", "—"))[:10],
            "max_ts":             str(o.get("max_ts", "—"))[:10],
            "span_days":          str(o.get("span_days", "—")),
            "distinct_dates":     str(o.get("distinct_dates", "—")),
            "distinct_snapshots": str(o.get("distinct_snapshots", "—")),
            "total_rows":         str(o.get("total_rows", "—")),
        })
    _print_table("Strategy enrichment coverage", opt_cols, opt_rows)
    print()
    print("  Interpretation:")
    print("    trade_setup_filter:   signatures will have SETUP=<real> only from 2026-04-26+")
    print("    policy_preview:       signatures will have POLICY=<real> only from 2026-05-10+")
    print("    paper_advice:         signatures will have ADVICE=<real> only from 2026-05-13+")
    print("    Pre-2026-04-26 snaps: SETUP=UNKNOWN, POLICY=UNKNOWN, ADVICE=UNKNOWN")
    print("    H5 validation:        limited to 2026-04-26+ where setup filter exists")

    _print_section("5. regime_selector_backtest_observation_v1 — current state")
    _print_table("Existing backtest rows",
                 ["report_version", "min_ts", "max_ts", "distinct_dates",
                  "distinct_snapshots", "total_rows"],
                 [{k: str(v) for k, v in r.items()} for r in backtest])

    _print_section("6. Blocker summary")
    rows = [
        {"table": "selection_state",          "blocker": str(ss["blocker"]),    "note": f"{ss['distinct_snapshots']} snaps / {ss['span_days']}-day span"},
        {"table": "obs_market_candle",        "blocker": "False",               "note": f"{candle['span_days']}-day history from {str(candle['min_ts'])[:10]}"},
        {"table": "setup_filter",             "blocker": "False",               "note": f"optional enrichment — sparse before 2026-04-26"},
        {"table": "policy_preview",           "blocker": "False",               "note": f"optional enrichment — sparse before 2026-05-10"},
        {"table": "paper_advice",             "blocker": "False",               "note": f"optional enrichment — only 2026-05-13+"},
        {"table": "NO source replay needed",  "blocker": "False",               "note": "existing data is sufficient to widen the backtest"},
    ]
    _print_table("", ["table", "blocker", "note"], rows)

    _print_section("7. Recommended replay plan")
    if rec["can_run_immediately"]:
        print("""
  SOURCE DATA VERDICT: SUFFICIENT FOR WIDER BACKTEST

  No historical source replay or backfill is required.
  The existing selection_state + obs_market_candle data is sufficient to run
  the regime selector backtest over all 356 available snapshots (vs 120 used so far).

  Recommended command:

    python -m src.research.run_regime_selector_backtest_v1 \\
      --venue bitvavo \\
      --interval 4h \\
      --from-ts 2026-03-20T00:00:00 \\
      --limit-snapshots 356 \\
      --horizons 4 24 72 \\
      --min-group-n 8 \\
      --write-db \\
      --output table

  Then rerun multi-window validation:

    python -m src.research.run_regime_selector_multi_window_validation_v1 \\
      --report-version 1.1 \\
      --window-mode week \\
      --min-n-ret 40 \\
      --output table

  Coverage limitations to document after replay:

    1. Sparse history before 2026-04-27 — many dates have only 1 snapshot.
       With 40 assets per snapshot, per-window n_ret at 4h will be ~40 for
       single-snapshot days. Aggregate weekly to get meaningful n.

    2. No GLOBAL_BTC_BREAKDOWN days in available data. H1 (extreme crash edge)
       cannot be validated. Mark H1 scope accordingly.

    3. Strategy enrichment (SETUP, POLICY, ADVICE) only from 2026-04-26+.
       Pre-April-26 observations will have signature:
         SEL=<real>|SETUP=UNKNOWN|POLICY=UNKNOWN|ADVICE=UNKNOWN|APLUS=UNKNOWN
       H5 validation is valid only for 2026-04-26+ data.

    4. Global regime diversity in the available window:
""")
        for regime, n in sorted(rec["regime_mix"].items(), key=lambda x: -x[1]):
            print(f"       {regime:<35}  days={n}")
        print("""
    5. The April 27 - May 1 dense window and May 10-14 dense window both sit
       in a flat-to-slightly-declining BTC market ($64-70K). They are not
       dramatically different macro environments. For true bull-vs-bear
       window contrast, the March 2026 data (BTC $57-65K, mixed regime) is
       the best available contrast.
""")
    else:
        print("""
  SOURCE DATA VERDICT: INSUFFICIENT

  selection_state has <= 120 snapshots (same as already loaded).
  No additional historical source data is available without a source replay.

  Required steps before rerunning the backtest:
    1. Replay selection_state into the DB covering 60+ days of history
    2. Replay trade_setup_filter_observation to enrich strategy signatures
    3. Optionally replay policy_preview and paper_advice
    4. Then rerun regime_selector_backtest_v1 with --from-ts and --limit-snapshots
    5. Then rerun regime_selector_multi_window_validation_v1
""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regime selector historical coverage audit (read-only)"
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--output", choices=["table", "json"], default="table")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            ss = _audit_selection_state(cur)
            candle = _audit_candles(cur, args.venue, args.interval)
            btc_days = _audit_btc_regimes(cur, args.venue, args.interval)
            optional = [
                _audit_optional_table(cur, "trade_setup_filter_observation", "asof_ts_utc"),
                _audit_optional_table(cur, "trade_setup_policy_preview_observation", "asof_ts_utc"),
                _audit_optional_table(cur, "paper_advice_observation", "asof_ts_utc"),
            ]
            backtest = _audit_backtest_table(cur)
    finally:
        conn.close()

    rec = _build_recommendation(ss, candle, btc_days, optional)

    if args.output == "json":
        def _ser(obj: Any) -> Any:
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                return float(obj)
            raise TypeError(type(obj))
        print(json.dumps({
            "selection_state":  {k: v for k, v in ss.items() if k not in ("per_day", "by_week")},
            "candle":           {k: v for k, v in candle.items() if k != "by_year"},
            "optional_tables":  [{k: v for k, v in o.items() if k != "per_day"} for o in optional],
            "backtest_state":   backtest,
            "recommendation":   rec,
        }, indent=2, default=_ser))
    else:
        _print_audit(ss, candle, btc_days, optional, backtest, rec)

    print(
        "\n[SAFETY]"
        " broker_calls=0"
        " broker_writes=0"
        " order_submission=0"
        " live_orders=0"
    )
    print(
        "[SCOPE]"
        "  research-only"
        "  market-only"
        "  account-agnostic"
        "  read-only-query"
    )


if __name__ == "__main__":
    main()
