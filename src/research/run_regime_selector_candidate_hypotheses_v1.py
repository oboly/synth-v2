from __future__ import annotations

"""
Synth v2 - Regime Selector Candidate Hypotheses V1 Evidence Runner.

LAYER: research

BOUNDARY:
  Read-only. No DB writes. No broker calls. No account state.
  Queries regime_selector_backtest_observation_v1 only.

Purpose:
  Print per-candidate evidence tables from regime_selector_backtest_observation_v1
  to support review and multi-window validation of the five candidate hypotheses
  defined in docs/research/regime_selector_candidate_hypotheses_v1.md.

  Candidates:
    H1  BTC_MILD_DECLINE_4H_BOUNCE
    H2  BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE
    H3  CLASS_LEADERSHIP_OVEREXTENSION_TRAP
    H4  BTC_RISK_ON_ALT_NO_LIFT_WARNING
    H5  POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET

Usage:
  python -m src.research.run_regime_selector_candidate_hypotheses_v1 [OPTIONS]

Options:
  --venue       Venue filter (default: bitvavo)
  --version     report_version to query (default: 1.1)
  --min-n       Min n_ret to include a row in output tables (default: 20)
  --output      table (default) or json
"""

import argparse
import json
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_connection

load_dotenv()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _f(v: Any, decimals: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return f"{v:+.{decimals}f}" if v != 0 else f"{v:.{decimals}f}"
    return str(v)


def _print_table(title: str, columns: list[str], rows: list[dict]) -> None:
    print(f"\n--- {title} ---")
    if not rows:
        print("  (no rows)")
        return
    widths = {c: max(len(c), max(len(str(r.get(c, "—"))) for r in rows)) for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(str(row.get(c, "—")).ljust(widths[c]) for c in columns))


def _run_query(cursor, sql: str, args: tuple = ()) -> list[dict]:
    cursor.execute(sql, args)
    return cursor.fetchall()


# ---------------------------------------------------------------------------
# Evidence queries — one block per candidate
# ---------------------------------------------------------------------------

def h1_btc_mild_decline_bounce(cursor, venue: str, version: str, min_n: int) -> list[dict]:
    """H1: GLOBAL_BTC_MILD_DECLINE across all horizons."""
    sql = """
        SELECT
            horizon_hours,
            COUNT(*) AS n_total,
            SUM(return_pct IS NOT NULL) AS n_ret,
            ROUND(AVG(return_pct), 3) AS avg_ret,
            ROUND(100.0 * SUM(return_pct > 0) / NULLIF(SUM(return_pct IS NOT NULL), 0), 1) AS win_rate,
            ROUND(AVG(mfe_pct), 3) AS avg_mfe,
            ROUND(AVG(mae_pct), 3) AS avg_mae
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
          AND venue = %s
          AND selector_mode = 'GLOBAL'
          AND global_regime = 'GLOBAL_BTC_MILD_DECLINE'
        GROUP BY horizon_hours
        HAVING n_ret >= %s
        ORDER BY horizon_hours
    """
    rows = _run_query(cursor, sql, (version, venue, min_n))
    return [
        {
            "horizon_h": r["horizon_hours"],
            "n_ret": r["n_ret"],
            "avg_ret%": _f(r["avg_ret"]),
            "win_rate%": _f(r["win_rate"], 1),
            "avg_mfe%": _f(r["avg_mfe"]),
            "avg_mae%": _f(r["avg_mae"]),
        }
        for r in rows
    ]


def h2_mild_decline_class_stress(cursor, venue: str, version: str, min_n: int) -> list[dict]:
    """H2: GLOBAL_BTC_MILD_DECLINE × all class regimes at 4h and 24h."""
    sql = """
        SELECT
            horizon_hours,
            asset_class_regime,
            COUNT(*) AS n_total,
            SUM(return_pct IS NOT NULL) AS n_ret,
            ROUND(AVG(return_pct), 3) AS avg_ret,
            ROUND(100.0 * SUM(return_pct > 0) / NULLIF(SUM(return_pct IS NOT NULL), 0), 1) AS win_rate,
            ROUND(AVG(mae_pct), 3) AS avg_mae
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
          AND venue = %s
          AND selector_mode = 'GLOBAL_CLASS'
          AND global_regime = 'GLOBAL_BTC_MILD_DECLINE'
          AND horizon_hours IN (4, 24)
        GROUP BY horizon_hours, asset_class_regime
        HAVING n_ret >= %s
        ORDER BY horizon_hours, avg_ret DESC
    """
    rows = _run_query(cursor, sql, (version, venue, min_n))
    return [
        {
            "horizon_h": r["horizon_hours"],
            "class_regime": r["asset_class_regime"],
            "n_ret": r["n_ret"],
            "avg_ret%": _f(r["avg_ret"]),
            "win_rate%": _f(r["win_rate"], 1),
            "avg_mae%": _f(r["avg_mae"]),
        }
        for r in rows
    ]


def h3_class_leadership_trap(cursor, venue: str, version: str, min_n: int) -> list[dict]:
    """H3: CLASS_LEADERSHIP crosses at 4h — sorted by avg_ret ascending."""
    sql = """
        SELECT
            global_regime,
            asset_class_regime,
            SUM(return_pct IS NOT NULL) AS n_ret,
            ROUND(AVG(return_pct), 3) AS avg_ret,
            ROUND(100.0 * SUM(return_pct > 0) / NULLIF(SUM(return_pct IS NOT NULL), 0), 1) AS win_rate,
            ROUND(AVG(mae_pct), 3) AS avg_mae
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
          AND venue = %s
          AND selector_mode = 'GLOBAL_CLASS'
          AND asset_class_regime = 'CLASS_LEADERSHIP'
          AND horizon_hours = 4
        GROUP BY global_regime, asset_class_regime
        HAVING n_ret >= %s
        ORDER BY avg_ret ASC
    """
    rows = _run_query(cursor, sql, (version, venue, min_n))
    return [
        {
            "global_regime": r["global_regime"],
            "class_regime": r["asset_class_regime"],
            "n_ret": r["n_ret"],
            "avg_ret%": _f(r["avg_ret"]),
            "win_rate%": _f(r["win_rate"], 1),
            "avg_mae%": _f(r["avg_mae"]),
        }
        for r in rows
    ]


def h4_risk_on_no_lift(cursor, venue: str, version: str, min_n: int) -> list[dict]:
    """H4: GLOBAL_RISK_ON × class regimes at 4h."""
    sql = """
        SELECT
            global_regime,
            asset_class_regime,
            SUM(return_pct IS NOT NULL) AS n_ret,
            ROUND(AVG(return_pct), 3) AS avg_ret,
            ROUND(100.0 * SUM(return_pct > 0) / NULLIF(SUM(return_pct IS NOT NULL), 0), 1) AS win_rate,
            ROUND(AVG(mae_pct), 3) AS avg_mae
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
          AND venue = %s
          AND selector_mode = 'GLOBAL_CLASS'
          AND global_regime = 'GLOBAL_RISK_ON'
          AND horizon_hours = 4
        GROUP BY global_regime, asset_class_regime
        HAVING n_ret >= %s
        ORDER BY avg_ret ASC
    """
    rows = _run_query(cursor, sql, (version, venue, min_n))
    return [
        {
            "global_regime": r["global_regime"],
            "class_regime": r["asset_class_regime"],
            "n_ret": r["n_ret"],
            "avg_ret%": _f(r["avg_ret"]),
            "win_rate%": _f(r["win_rate"], 1),
            "avg_mae%": _f(r["avg_mae"]),
        }
        for r in rows
    ]


def h5_insufficient_sample(cursor, venue: str, version: str, min_n: int) -> list[dict]:
    """H5: Strategy signature policy buckets at 24h, sorted by avg_ret ascending."""
    keyed_pattern = "SEL=%%|SETUP=%%|POLICY=%%|ADVICE=%%|APLUS=%%"
    sql = """
        SELECT
            strategy_signature,
            SUM(return_pct IS NOT NULL) AS n_ret,
            ROUND(AVG(return_pct), 3) AS avg_ret,
            ROUND(100.0 * SUM(return_pct > 0) / NULLIF(SUM(return_pct IS NOT NULL), 0), 1) AS win_rate
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
          AND venue = %s
          AND selector_mode = 'STRATEGY_SIGNATURE'
          AND horizon_hours = 24
          AND strategy_signature LIKE %s
        GROUP BY strategy_signature
        HAVING n_ret >= %s
        ORDER BY avg_ret ASC
        LIMIT 12
    """
    rows = _run_query(cursor, sql, (version, venue, keyed_pattern, min_n))
    return [
        {
            "signature": r["strategy_signature"],
            "n_ret": r["n_ret"],
            "avg_ret%": _f(r["avg_ret"]),
            "win_rate%": _f(r["win_rate"], 1),
        }
        for r in rows
    ]


def baseline_global(cursor, venue: str, version: str, min_n: int) -> list[dict]:
    """All global regimes at 4h — reference baseline."""
    sql = """
        SELECT
            global_regime,
            SUM(return_pct IS NOT NULL) AS n_ret,
            ROUND(AVG(return_pct), 3) AS avg_ret,
            ROUND(100.0 * SUM(return_pct > 0) / NULLIF(SUM(return_pct IS NOT NULL), 0), 1) AS win_rate,
            ROUND(AVG(mfe_pct), 3) AS avg_mfe,
            ROUND(AVG(mae_pct), 3) AS avg_mae
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
          AND venue = %s
          AND selector_mode = 'GLOBAL'
          AND horizon_hours = 4
        GROUP BY global_regime
        HAVING n_ret >= %s
        ORDER BY avg_ret DESC
    """
    rows = _run_query(cursor, sql, (version, venue, min_n))
    return [
        {
            "global_regime": r["global_regime"],
            "n_ret": r["n_ret"],
            "avg_ret%": _f(r["avg_ret"]),
            "win_rate%": _f(r["win_rate"], 1),
            "avg_mfe%": _f(r["avg_mfe"]),
            "avg_mae%": _f(r["avg_mae"]),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regime selector candidate hypotheses evidence runner (read-only)"
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--version", default="1.1")
    parser.add_argument("--min-n", type=int, default=20)
    parser.add_argument("--output", choices=["table", "json"], default="table")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            print(
                f"\n[INFO] candidate hypotheses evidence"
                f"  venue={args.venue}  report_version={args.version}  min_n={args.min_n}"
            )

            baseline = baseline_global(cur, args.venue, args.version, args.min_n)
            h1 = h1_btc_mild_decline_bounce(cur, args.venue, args.version, args.min_n)
            h2 = h2_mild_decline_class_stress(cur, args.venue, args.version, args.min_n)
            h3 = h3_class_leadership_trap(cur, args.venue, args.version, args.min_n)
            h4 = h4_risk_on_no_lift(cur, args.venue, args.version, args.min_n)
            h5 = h5_insufficient_sample(cur, args.venue, args.version, args.min_n)

    finally:
        conn.close()

    if args.output == "json":
        print(json.dumps({
            "baseline_global_4h": baseline,
            "H1_btc_mild_decline_bounce": h1,
            "H2_mild_decline_class_stress": h2,
            "H3_class_leadership_trap": h3,
            "H4_risk_on_no_lift": h4,
            "H5_insufficient_sample_24h": h5,
        }, indent=2))
        return

    _print_table(
        "Baseline — GLOBAL regimes at 4h",
        ["global_regime", "n_ret", "avg_ret%", "win_rate%", "avg_mfe%", "avg_mae%"],
        baseline,
    )

    _print_table(
        "H1 BTC_MILD_DECLINE_4H_BOUNCE — GLOBAL_BTC_MILD_DECLINE across horizons",
        ["horizon_h", "n_ret", "avg_ret%", "win_rate%", "avg_mfe%", "avg_mae%"],
        h1,
    )

    _print_table(
        "H2 BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE — GBMD × class at 4h and 24h",
        ["horizon_h", "class_regime", "n_ret", "avg_ret%", "win_rate%", "avg_mae%"],
        h2,
    )

    _print_table(
        "H3 CLASS_LEADERSHIP_OVEREXTENSION_TRAP — CLASS_LEADERSHIP crosses at 4h",
        ["global_regime", "class_regime", "n_ret", "avg_ret%", "win_rate%", "avg_mae%"],
        h3,
    )

    _print_table(
        "H4 BTC_RISK_ON_ALT_NO_LIFT_WARNING — GLOBAL_RISK_ON × class at 4h",
        ["global_regime", "class_regime", "n_ret", "avg_ret%", "win_rate%", "avg_mae%"],
        h4,
    )

    _print_table(
        "H5 POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET — strategy signatures at 24h",
        ["signature", "n_ret", "avg_ret%", "win_rate%"],
        h5,
    )

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
