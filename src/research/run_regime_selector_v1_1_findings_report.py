from __future__ import annotations

"""
Synth v2 - Regime Selector v1.1 Findings Report.

LAYER: research

BOUNDARY:
  Read-only. No DB writes. No broker calls. No account state.
  Queries regime_selector_backtest_observation_v1 only.

Purpose:
  Compare report_version=1.0 vs 1.1 across:
    - Row counts and selector_mode balance
    - GLOBAL regime distribution (v1.1 introduces GLOBAL_BTC_MILD_DECLINE)
    - v1.0 GLOBAL_UNKNOWN composition vs v1.1 GLOBAL_BTC_MILD_DECLINE resolution
    - Horizon-level stats per regime for both versions
    - Strategy signature format comparison (v1.0 positional vs v1.1 keyed)
    - Top/bottom regimes by avg_return_pct per horizon

Usage:
  python -m src.research.run_regime_selector_v1_1_findings_report --venue bitvavo
"""

import argparse
from decimal import Decimal
from statistics import median
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_connection

REPORT_NAME = "regime_selector_backtest_v1"
VERSIONS = ["1.0", "1.1"]

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _f(v: Any, decimals: int = 2) -> str:
    if v is None:
        return ""
    if isinstance(v, (float, Decimal)):
        return f"{float(v):.{decimals}f}"
    return str(v)


def _print_table(title: str, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        print(f"\n{title}")
        print("  (no rows)")
        return
    col_w = {c: len(c) for c in columns}
    for row in rows:
        for c in columns:
            col_w[c] = max(col_w[c], len(str(row.get(c, ""))))
    print(f"\n{title}")
    header = "  ".join(c.ljust(col_w[c]) for c in columns)
    print(header)
    print("-" * len(header))
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(col_w[c]) for c in columns))


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def q_version_counts(cur: Any) -> list[dict]:
    cur.execute("""
        SELECT report_version,
               COUNT(*) AS total_rows,
               COUNT(DISTINCT selector_mode) AS distinct_modes,
               COUNT(DISTINCT strategy_signature) AS distinct_sigs,
               COUNT(DISTINCT asof_ts_utc) AS distinct_snapshots
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
        GROUP BY report_version
        ORDER BY report_version
    """, (REPORT_NAME,))
    return list(cur.fetchall())


def q_selector_mode_counts(cur: Any) -> list[dict]:
    cur.execute("""
        SELECT report_version, selector_mode, COUNT(*) AS n
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
        GROUP BY report_version, selector_mode
        ORDER BY report_version, selector_mode
    """, (REPORT_NAME,))
    return list(cur.fetchall())


def q_global_regime_distribution(cur: Any, version: str, horizon: int) -> list[dict]:
    cur.execute("""
        SELECT global_regime,
               COUNT(*) AS n_total,
               SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS n_ret,
               ROUND(AVG(forward_return_pct), 3) AS avg_ret_pct,
               ROUND(AVG(CASE WHEN forward_return_pct IS NOT NULL
                               THEN forward_return_pct END), 3) AS avg_ret_filled,
               ROUND(
                   SUM(CASE WHEN forward_return_pct > 0 THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END), 0)
                   * 100, 1
               ) AS win_rate_pct,
               ROUND(AVG(mfe_pct), 3) AS avg_mfe_pct,
               ROUND(AVG(mae_pct), 3) AS avg_mae_pct,
               ROUND(AVG(btc_return_24h_pct), 5) AS avg_btc_24h
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
          AND report_version = %s
          AND selector_mode = 'GLOBAL'
          AND horizon_hours = %s
        GROUP BY global_regime
        ORDER BY avg_ret_pct DESC
    """, (REPORT_NAME, version, horizon))
    return list(cur.fetchall())


def q_unknown_composition(cur: Any) -> list[dict]:
    """v1.0 GLOBAL_UNKNOWN: what BTC 24h ranges are in it?"""
    cur.execute("""
        SELECT
            CASE
                WHEN btc_return_24h_pct IS NULL              THEN 'NULL (missing data)'
                WHEN btc_return_24h_pct < -0.05              THEN 'below -5pct (breakdown)'
                WHEN btc_return_24h_pct < -0.01              THEN '-5pct to -1pct (mild decline - leak)'
                WHEN btc_return_24h_pct <= 0.01              THEN '-1pct to +1pct (neutral)'
                ELSE                                              'above +1pct'
            END AS btc_range_bucket,
            COUNT(*) AS n,
            ROUND(AVG(forward_return_pct), 3) AS avg_ret_pct,
            ROUND(
                SUM(CASE WHEN forward_return_pct > 0 THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END), 0)
                * 100, 1
            ) AS win_rate_pct
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
          AND report_version = '1.0'
          AND selector_mode = 'GLOBAL'
          AND global_regime = 'GLOBAL_UNKNOWN'
          AND horizon_hours = 24
        GROUP BY btc_range_bucket
        ORDER BY n DESC
    """, (REPORT_NAME,))
    return list(cur.fetchall())


def q_mild_decline_detail(cur: Any, version: str) -> list[dict]:
    """v1.1 GLOBAL_BTC_MILD_DECLINE per horizon."""
    cur.execute("""
        SELECT horizon_hours,
               COUNT(*) AS n_total,
               SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS n_ret,
               ROUND(AVG(forward_return_pct), 3) AS avg_ret_pct,
               ROUND(
                   SUM(CASE WHEN forward_return_pct > 0 THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END), 0)
                   * 100, 1
               ) AS win_rate_pct,
               ROUND(AVG(mfe_pct), 3) AS avg_mfe_pct,
               ROUND(AVG(mae_pct), 3) AS avg_mae_pct
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
          AND report_version = %s
          AND selector_mode = 'GLOBAL'
          AND global_regime = 'GLOBAL_BTC_MILD_DECLINE'
        GROUP BY horizon_hours
        ORDER BY horizon_hours
    """, (REPORT_NAME, version))
    return list(cur.fetchall())


def q_global_class_cross(cur: Any, version: str, horizon: int, min_n_ret: int = 40) -> list[dict]:
    cur.execute("""
        SELECT global_class_regime,
               COUNT(*) AS n_total,
               SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS n_ret,
               ROUND(AVG(forward_return_pct), 3) AS avg_ret_pct,
               ROUND(
                   SUM(CASE WHEN forward_return_pct > 0 THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END), 0)
                   * 100, 1
               ) AS win_rate_pct,
               ROUND(AVG(mfe_pct), 3) AS avg_mfe_pct,
               ROUND(AVG(mae_pct), 3) AS avg_mae_pct
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
          AND report_version = %s
          AND selector_mode = 'GLOBAL_CLASS'
          AND horizon_hours = %s
        GROUP BY global_class_regime
        HAVING n_ret >= %s
        ORDER BY avg_ret_pct DESC
    """, (REPORT_NAME, version, horizon, min_n_ret))
    return list(cur.fetchall())


def q_strategy_sig_samples(cur: Any, version: str, n: int = 8) -> list[dict]:
    """Representative strategy signature samples per version."""
    cur.execute("""
        SELECT strategy_signature,
               COUNT(*) AS n_total,
               SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS n_ret,
               ROUND(AVG(forward_return_pct), 3) AS avg_ret_pct,
               ROUND(
                   SUM(CASE WHEN forward_return_pct > 0 THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END), 0)
                   * 100, 1
               ) AS win_rate_pct
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
          AND report_version = %s
          AND selector_mode = 'STRATEGY_SIGNATURE'
          AND horizon_hours = 24
        GROUP BY strategy_signature
        HAVING n_ret >= 50
        ORDER BY n_total DESC
        LIMIT %s
    """, (REPORT_NAME, version, n))
    return list(cur.fetchall())


def q_top_bottom_global(cur: Any, version: str, horizon: int) -> tuple[list[dict], list[dict]]:
    """Top and bottom 3 global regimes by avg_ret_pct with n_ret >= 40."""
    cur.execute("""
        SELECT global_regime,
               SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS n_ret,
               ROUND(AVG(forward_return_pct), 3) AS avg_ret_pct,
               ROUND(
                   SUM(CASE WHEN forward_return_pct > 0 THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END), 0)
                   * 100, 1
               ) AS win_rate_pct,
               ROUND(AVG(mfe_pct), 3) AS avg_mfe_pct,
               ROUND(AVG(mae_pct), 3) AS avg_mae_pct
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
          AND report_version = %s
          AND selector_mode = 'GLOBAL'
          AND horizon_hours = %s
        GROUP BY global_regime
        HAVING n_ret >= 40
        ORDER BY avg_ret_pct DESC
    """, (REPORT_NAME, version, horizon))
    rows = list(cur.fetchall())
    return rows[:3], rows[-3:]


def q_sig_format_sanity(cur: Any) -> list[dict]:
    """Count signatures matching each format per version."""
    keyed_pattern = "SEL=%%|SETUP=%%|POLICY=%%|ADVICE=%%|APLUS=%%"
    cur.execute("""
        SELECT report_version,
               SUM(CASE WHEN strategy_signature LIKE %s
                        THEN 1 ELSE 0 END) AS keyed_format,
               SUM(CASE WHEN strategy_signature NOT LIKE %s
                         AND strategy_signature IS NOT NULL
                         AND strategy_signature != ''
                        THEN 1 ELSE 0 END) AS positional_format,
               SUM(CASE WHEN strategy_signature IS NULL OR strategy_signature = ''
                        THEN 1 ELSE 0 END) AS null_or_empty
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
        GROUP BY report_version
        ORDER BY report_version
    """, (keyed_pattern, keyed_pattern, REPORT_NAME))
    return list(cur.fetchall())


def q_global_unknown_sanity(cur: Any) -> list[dict]:
    """Check GLOBAL_UNKNOWN no longer contains real BTC returns in v1.1."""
    cur.execute("""
        SELECT report_version,
               SUM(CASE WHEN global_regime = 'GLOBAL_UNKNOWN'
                         AND btc_return_24h_pct IS NOT NULL
                        THEN 1 ELSE 0 END) AS unknown_with_btc_data,
               SUM(CASE WHEN global_regime = 'GLOBAL_UNKNOWN'
                         AND btc_return_24h_pct IS NULL
                        THEN 1 ELSE 0 END) AS unknown_truly_missing,
               SUM(CASE WHEN global_regime = 'GLOBAL_UNKNOWN'
                        THEN 1 ELSE 0 END) AS unknown_total
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
          AND selector_mode = 'GLOBAL'
        GROUP BY report_version
        ORDER BY report_version
    """, (REPORT_NAME,))
    return list(cur.fetchall())


def q_horizon_summary(cur: Any, version: str, horizon: int) -> dict:
    """Overall stats for a version/horizon combination."""
    cur.execute("""
        SELECT
            COUNT(*) AS n_total,
            SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END) AS n_ret,
            ROUND(AVG(forward_return_pct), 3) AS avg_ret_pct,
            ROUND(
                SUM(CASE WHEN forward_return_pct > 0 THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN forward_return_pct IS NOT NULL THEN 1 ELSE 0 END), 0)
                * 100, 1
            ) AS win_rate_pct,
            ROUND(AVG(mfe_pct), 3) AS avg_mfe_pct,
            ROUND(AVG(mae_pct), 3) AS avg_mae_pct,
            ROUND(MIN(forward_return_pct), 3) AS min_ret_pct,
            ROUND(MAX(forward_return_pct), 3) AS max_ret_pct
        FROM regime_selector_backtest_observation_v1
        WHERE report_name = %s
          AND report_version = %s
          AND selector_mode = 'GLOBAL'
          AND horizon_hours = %s
    """, (REPORT_NAME, version, horizon))
    row = cur.fetchone()
    return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def run_report(conn: Any, *, venue: str) -> None:
    with conn.cursor() as cur:

        print("=" * 80)
        print("REGIME SELECTOR BACKTEST — v1.0 vs v1.1 FINDINGS REPORT")
        print(f"report_name={REPORT_NAME}  venue={venue}")
        print("read-only | market-only | account-agnostic | no broker calls")
        print("=" * 80)

        # ----------------------------------------------------------------
        # 1. Row counts
        # ----------------------------------------------------------------
        print("\n\n### 1. REPORT VERSION COUNTS ###")
        rows = q_version_counts(cur)
        _print_table(
            "Row counts by report_version",
            ["report_version", "total_rows", "distinct_modes", "distinct_sigs", "distinct_snapshots"],
            [{
                "report_version": r["report_version"],
                "total_rows": r["total_rows"],
                "distinct_modes": r["distinct_modes"],
                "distinct_sigs": r["distinct_sigs"],
                "distinct_snapshots": r["distinct_snapshots"],
            } for r in rows],
        )

        # ----------------------------------------------------------------
        # 2. Selector mode balance
        # ----------------------------------------------------------------
        print("\n\n### 2. SELECTOR MODE COUNTS BY VERSION ###")
        rows = q_selector_mode_counts(cur)
        _print_table(
            "selector_mode distribution (expect balanced counts within each version)",
            ["report_version", "selector_mode", "n"],
            [{k: r[k] for k in ["report_version", "selector_mode", "n"]} for r in rows],
        )

        # ----------------------------------------------------------------
        # 3. Strategy signature format sanity
        # ----------------------------------------------------------------
        print("\n\n### 3. STRATEGY SIGNATURE FORMAT SANITY ###")
        rows = q_sig_format_sanity(cur)
        _print_table(
            "Signature format counts by version  (v1.0=positional, v1.1=keyed)",
            ["report_version", "keyed_format", "positional_format", "null_or_empty"],
            [{k: r[k] for k in ["report_version", "keyed_format", "positional_format", "null_or_empty"]}
             for r in rows],
        )

        # ----------------------------------------------------------------
        # 4. GLOBAL_UNKNOWN sanity check
        # ----------------------------------------------------------------
        print("\n\n### 4. GLOBAL_UNKNOWN SEMANTIC SANITY ###")
        rows = q_global_unknown_sanity(cur)
        _print_table(
            "GLOBAL_UNKNOWN composition: v1.0 had real BTC data mixed in; v1.1 must have 0 with BTC data",
            ["report_version", "unknown_total", "unknown_with_btc_data", "unknown_truly_missing"],
            [{k: r[k] for k in ["report_version", "unknown_total", "unknown_with_btc_data", "unknown_truly_missing"]}
             for r in rows],
        )

        # ----------------------------------------------------------------
        # 5. v1.0 GLOBAL_UNKNOWN composition breakdown
        # ----------------------------------------------------------------
        print("\n\n### 5. v1.0 GLOBAL_UNKNOWN — BTC RETURN RANGE BREAKDOWN (24h) ###")
        rows = q_unknown_composition(cur)
        _print_table(
            "What was inside v1.0 GLOBAL_UNKNOWN? (horizon=24h)",
            ["btc_range_bucket", "n", "avg_ret_pct", "win_rate_pct"],
            [{
                "btc_range_bucket": r["btc_range_bucket"],
                "n": r["n"],
                "avg_ret_pct": _f(r["avg_ret_pct"]),
                "win_rate_pct": _f(r["win_rate_pct"]),
            } for r in rows],
        )

        # ----------------------------------------------------------------
        # 6. GLOBAL regime distribution per version × horizon
        # ----------------------------------------------------------------
        print("\n\n### 6. GLOBAL REGIME DISTRIBUTION — v1.0 vs v1.1 ###")
        for version in VERSIONS:
            for horizon in [4, 24, 72]:
                rows = q_global_regime_distribution(cur, version, horizon)
                _print_table(
                    f"version={version}  horizon={horizon}h  selector_mode=GLOBAL",
                    ["global_regime", "n_total", "n_ret", "avg_ret_pct", "win_rate_pct",
                     "avg_mfe_pct", "avg_mae_pct", "avg_btc_24h"],
                    [{
                        "global_regime": r["global_regime"],
                        "n_total": r["n_total"],
                        "n_ret": r["n_ret"],
                        "avg_ret_pct": _f(r["avg_ret_pct"]),
                        "win_rate_pct": _f(r["win_rate_pct"]),
                        "avg_mfe_pct": _f(r["avg_mfe_pct"]),
                        "avg_mae_pct": _f(r["avg_mae_pct"]),
                        "avg_btc_24h": _f(r["avg_btc_24h"], 4),
                    } for r in rows],
                )

        # ----------------------------------------------------------------
        # 7. v1.1 GLOBAL_BTC_MILD_DECLINE across horizons
        # ----------------------------------------------------------------
        print("\n\n### 7. v1.1 GLOBAL_BTC_MILD_DECLINE — ACROSS HORIZONS ###")
        rows = q_mild_decline_detail(cur, "1.1")
        _print_table(
            "GLOBAL_BTC_MILD_DECLINE by horizon (v1.1 only)",
            ["horizon_hours", "n_total", "n_ret", "avg_ret_pct", "win_rate_pct",
             "avg_mfe_pct", "avg_mae_pct"],
            [{
                "horizon_hours": r["horizon_hours"],
                "n_total": r["n_total"],
                "n_ret": r["n_ret"],
                "avg_ret_pct": _f(r["avg_ret_pct"]),
                "win_rate_pct": _f(r["win_rate_pct"]),
                "avg_mfe_pct": _f(r["avg_mfe_pct"]),
                "avg_mae_pct": _f(r["avg_mae_pct"]),
            } for r in rows],
        )

        # ----------------------------------------------------------------
        # 8. Horizon overall summary — v1.1
        # ----------------------------------------------------------------
        print("\n\n### 8. HORIZON OVERALL SUMMARY — v1.1 ###")
        summary_rows = []
        for horizon in [4, 24, 72]:
            s = q_horizon_summary(cur, "1.1", horizon)
            if s:
                summary_rows.append({
                    "horizon_hours": horizon,
                    "n_ret": s.get("n_ret", ""),
                    "avg_ret_pct": _f(s.get("avg_ret_pct")),
                    "win_rate_pct": _f(s.get("win_rate_pct")),
                    "avg_mfe_pct": _f(s.get("avg_mfe_pct")),
                    "avg_mae_pct": _f(s.get("avg_mae_pct")),
                    "min_ret_pct": _f(s.get("min_ret_pct")),
                    "max_ret_pct": _f(s.get("max_ret_pct")),
                })
        _print_table(
            "Overall GLOBAL-mode horizon summary (v1.1)",
            ["horizon_hours", "n_ret", "avg_ret_pct", "win_rate_pct",
             "avg_mfe_pct", "avg_mae_pct", "min_ret_pct", "max_ret_pct"],
            summary_rows,
        )

        # ----------------------------------------------------------------
        # 9. Top/bottom global regimes per horizon — v1.1
        # ----------------------------------------------------------------
        print("\n\n### 9. TOP / BOTTOM GLOBAL REGIMES BY avg_ret_pct — v1.1 ###")
        for horizon in [4, 24, 72]:
            top, bottom = q_top_bottom_global(cur, "1.1", horizon)
            cols = ["global_regime", "n_ret", "avg_ret_pct", "win_rate_pct",
                    "avg_mfe_pct", "avg_mae_pct"]

            def fmt_rows(rs: list[dict]) -> list[dict]:
                return [{
                    "global_regime": r["global_regime"],
                    "n_ret": r["n_ret"],
                    "avg_ret_pct": _f(r["avg_ret_pct"]),
                    "win_rate_pct": _f(r["win_rate_pct"]),
                    "avg_mfe_pct": _f(r["avg_mfe_pct"]),
                    "avg_mae_pct": _f(r["avg_mae_pct"]),
                } for r in rs]

            _print_table(f"TOP regimes  horizon={horizon}h (v1.1)", cols, fmt_rows(top))
            _print_table(f"BOTTOM regimes  horizon={horizon}h (v1.1)", cols, fmt_rows(bottom))

        # ----------------------------------------------------------------
        # 10. GLOBAL_CLASS cross — v1.1, 4h (where signal is strongest)
        # ----------------------------------------------------------------
        print("\n\n### 10. GLOBAL_CLASS CROSS — v1.1, 4h (n_ret >= 40) ###")
        rows = q_global_class_cross(cur, "1.1", 4, min_n_ret=40)
        _print_table(
            "GLOBAL_CLASS cross (v1.1, horizon=4h)",
            ["global_class_regime", "n_total", "n_ret", "avg_ret_pct",
             "win_rate_pct", "avg_mfe_pct", "avg_mae_pct"],
            [{
                "global_class_regime": r["global_class_regime"],
                "n_total": r["n_total"],
                "n_ret": r["n_ret"],
                "avg_ret_pct": _f(r["avg_ret_pct"]),
                "win_rate_pct": _f(r["win_rate_pct"]),
                "avg_mfe_pct": _f(r["avg_mfe_pct"]),
                "avg_mae_pct": _f(r["avg_mae_pct"]),
            } for r in rows],
        )

        # 24h cross for context
        rows = q_global_class_cross(cur, "1.1", 24, min_n_ret=40)
        _print_table(
            "GLOBAL_CLASS cross (v1.1, horizon=24h)",
            ["global_class_regime", "n_total", "n_ret", "avg_ret_pct",
             "win_rate_pct", "avg_mfe_pct", "avg_mae_pct"],
            [{
                "global_class_regime": r["global_class_regime"],
                "n_total": r["n_total"],
                "n_ret": r["n_ret"],
                "avg_ret_pct": _f(r["avg_ret_pct"]),
                "win_rate_pct": _f(r["win_rate_pct"]),
                "avg_mfe_pct": _f(r["avg_mfe_pct"]),
                "avg_mae_pct": _f(r["avg_mae_pct"]),
            } for r in rows],
        )

        # ----------------------------------------------------------------
        # 11. Strategy signature samples — v1.0 vs v1.1 (24h, n_ret >= 50)
        # ----------------------------------------------------------------
        print("\n\n### 11. STRATEGY SIGNATURE SAMPLES — v1.0 vs v1.1 (24h, n_ret >= 50) ###")
        for version in VERSIONS:
            rows = q_strategy_sig_samples(cur, version)
            _print_table(
                f"Top signatures by volume  version={version}  horizon=24h",
                ["strategy_signature", "n_total", "n_ret", "avg_ret_pct", "win_rate_pct"],
                [{
                    "strategy_signature": r["strategy_signature"],
                    "n_total": r["n_total"],
                    "n_ret": r["n_ret"],
                    "avg_ret_pct": _f(r["avg_ret_pct"]),
                    "win_rate_pct": _f(r["win_rate_pct"]),
                } for r in rows],
            )

        # ----------------------------------------------------------------
        # Safety footer
        # ----------------------------------------------------------------
        print("\n" + "=" * 80)
        print("[SAFETY] broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
        print("[SCOPE]  research-only  market-only  account-agnostic  read-only-query")
        print("=" * 80)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only findings report: regime selector backtest v1.0 vs v1.1."
    )
    parser.add_argument("--venue", default="bitvavo")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    conn = get_connection()
    try:
        run_report(conn, venue=args.venue)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
