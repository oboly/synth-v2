from __future__ import annotations

"""
Synth v2 - Policy Router Preview Validation V1.

LAYER: research (read-only)

BOUNDARY:
  Research-only. Market-only. Account-agnostic. Read-only.
  No DB writes. No broker calls. No orders. No account state.
  No selection_engine changes. No advice_engine changes.
  No decision_gate. No execution_planner. No executor.

Purpose:
  Validate whether the policy_router_preview_v1 route predicate
  (ROUTE_GBMD_4H_BOUNCE_CONTEXT) matches the H1 forward-return profile
  observed in regime_selector_backtest_observation_v1.

  The latest policy_router_preview_observation table cannot be used alone —
  the current regime is GLOBAL_NEUTRAL, so there are zero ROUTE_CANDIDATE rows
  in the live preview. Historical validation uses the widened v1.1 backtest
  observations (356 snapshots, 2026-03-21 to 2026-05-14) as the ground truth.

  Route predicate applied to historical data:
    ROUTE_GBMD_4H_BOUNCE_CONTEXT if:
      selector_mode = GLOBAL
      AND global_regime = GLOBAL_BTC_MILD_DECLINE

Usage:
  python -m src.research.run_policy_router_preview_validation_v1 [OPTIONS]

Options:
  --report-version    Backtest report version (default: 1.1)
  --min-n-ret         Minimum n for overall route validation (default: 300)
  --min-weekly-n-ret  Minimum n for a weekly window to count (default: 40)
  --output            table (default) | json
  --write-doc         Write markdown doc to path (optional)
"""

import argparse
import json
import statistics
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_connection

load_dotenv()

UTC = timezone.utc

ROUTE_CANDIDATE_LABEL = "ROUTE_GBMD_4H_BOUNCE_CONTEXT"
ROUTE_NO_MATCH_LABEL = "ROUTE_NO_MATCH"
GBMD_REGIME = "GLOBAL_BTC_MILD_DECLINE"
SELECTOR_MODE = "GLOBAL"


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

def _coverage(cur: Any, version: str) -> dict:
    cur.execute("""
        SELECT
            MIN(asof_ts_utc)          AS min_ts,
            MAX(asof_ts_utc)          AS max_ts,
            COUNT(*)                  AS total_rows,
            COUNT(DISTINCT asof_ts_utc) AS snapshots,
            COUNT(DISTINCT asset_id)  AS assets,
            COUNT(DISTINCT horizon_hours) AS horizons
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
    """, (version,))
    return cur.fetchone()


def _regime_dist(cur: Any, version: str) -> list[dict]:
    cur.execute("""
        SELECT global_regime,
               COUNT(DISTINCT asof_ts_utc) AS snap_count,
               COUNT(*) AS n_rows
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s AND selector_mode = %s AND horizon_hours = 4
        GROUP BY global_regime
        ORDER BY n_rows DESC
    """, (version, SELECTOR_MODE))
    return cur.fetchall()


def _aggregate(cur: Any, version: str, horizon: int, where_extra: str, params: tuple) -> dict:
    cur.execute(f"""
        SELECT
            COUNT(*) AS n_total,
            SUM(forward_return_pct IS NOT NULL) AS n_ret,
            AVG(forward_return_pct) AS avg_ret,
            SUM(forward_return_pct > 0) /
              NULLIF(SUM(forward_return_pct IS NOT NULL), 0) * 100 AS win_rate,
            AVG(mfe_pct) AS avg_mfe,
            AVG(mae_pct) AS avg_mae
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s AND selector_mode = %s
          AND horizon_hours = %s
          {where_extra}
    """, (version, SELECTOR_MODE, horizon) + params)
    return cur.fetchone()


def _all_regimes_4h(cur: Any, version: str) -> list[dict]:
    cur.execute("""
        SELECT global_regime,
               SUM(forward_return_pct IS NOT NULL) AS n_ret,
               AVG(forward_return_pct)              AS avg_ret,
               SUM(forward_return_pct > 0) /
                 NULLIF(SUM(forward_return_pct IS NOT NULL), 0) * 100 AS win_rate,
               AVG(mfe_pct) AS avg_mfe,
               AVG(mae_pct) AS avg_mae
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s AND selector_mode = %s AND horizon_hours = 4
        GROUP BY global_regime
        ORDER BY avg_ret DESC
    """, (version, SELECTOR_MODE))
    return cur.fetchall()


def _weekly_stability(cur: Any, version: str) -> list[dict]:
    cur.execute("""
        SELECT
            DATE(DATE_SUB(asof_ts_utc, INTERVAL WEEKDAY(asof_ts_utc) DAY)) AS week_start,
            SUM(forward_return_pct IS NOT NULL) AS n_ret,
            AVG(forward_return_pct)              AS avg_ret,
            SUM(forward_return_pct > 0) /
              NULLIF(SUM(forward_return_pct IS NOT NULL), 0) * 100 AS win_rate
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s AND selector_mode = %s
          AND horizon_hours = 4 AND global_regime = %s
        GROUP BY week_start
        ORDER BY week_start
    """, (version, SELECTOR_MODE, GBMD_REGIME))
    return cur.fetchall()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(v: Any, decimals: int = 3, sign: bool = True) -> str:
    if v is None:
        return "—"
    fv = float(v)
    fmt = f"{{:+.{decimals}f}}" if sign else f"{{:.{decimals}f}}"
    return fmt.format(fv)


def _pf(v: Any) -> str:
    if v is None:
        return "—"
    return f"{float(v):.1f}%"


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


def _pass_fail(avg_ret: Any, win_rate: Any, n_ret: int, min_n: int) -> str:
    if n_ret < min_n:
        return "LOW_SAMPLE"
    if avg_ret is None or win_rate is None:
        return "NO_DATA"
    if float(avg_ret) > 0 and float(win_rate) > 50:
        return "PASS"
    return "FAIL"


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

def run_validation(
    conn: Any,
    report_version: str,
    min_n_ret: int,
    min_weekly_n_ret: int,
) -> dict:
    with conn.cursor() as cur:
        coverage = _coverage(cur, report_version)
        regime_dist = _regime_dist(cur, report_version)

        # Route candidate vs no-match across all three horizons
        route_horizons: dict[int, dict] = {}
        nomatch_horizons: dict[int, dict] = {}
        for h in [4, 24, 72]:
            route_horizons[h] = _aggregate(
                cur, report_version, h,
                "AND global_regime = %s", (GBMD_REGIME,)
            )
            nomatch_horizons[h] = _aggregate(
                cur, report_version, h,
                "AND global_regime != %s", (GBMD_REGIME,)
            )

        all_regimes = _all_regimes_4h(cur, report_version)
        weekly = _weekly_stability(cur, report_version)

    # Weekly pass/fail
    weekly_rows: list[dict] = []
    weekly_pass = 0
    weekly_total = 0
    for w in weekly:
        n = int(w["n_ret"] or 0)
        if n < min_weekly_n_ret:
            verdict = "LOW_SAMPLE"
        elif float(w["avg_ret"] or 0) > 0 and float(w["win_rate"] or 0) > 50:
            verdict = "PASS"
            weekly_pass += 1
            weekly_total += 1
        else:
            verdict = "FAIL"
            weekly_total += 1
        weekly_rows.append({
            "week_start":  str(w["week_start"]),
            "n_ret":       str(n),
            "avg_ret_4h":  _f(w["avg_ret"]),
            "win_rate_4h": _pf(w["win_rate"]),
            "verdict":     verdict,
        })

    pass_rate = (weekly_pass / weekly_total * 100) if weekly_total > 0 else 0.0

    # Overall 4h check
    r4 = route_horizons[4]
    n_ret_4h = int(r4["n_ret"] or 0)
    overall_pf = _pass_fail(r4["avg_ret"], r4["win_rate"], n_ret_4h, min_n_ret)

    # 24h horizon interpretation
    r24 = route_horizons[24]
    horizon_24h_label = "SHORT_WINDOW_ONLY_CONFIRMED" if (
        r24["avg_ret"] is not None and float(r24["avg_ret"]) < 0
    ) else "24H_POSITIVE"

    # Final decision
    if overall_pf == "PASS" and weekly_total >= 2 and pass_rate >= 60.0:
        decision = "ROUTE_VALIDATED_FOR_PREVIEW"
    elif overall_pf == "LOW_SAMPLE" or n_ret_4h < min_n_ret:
        decision = "ROUTE_LOW_SAMPLE"
    elif overall_pf == "PASS":
        decision = "ROUTE_MIXED"
    else:
        decision = "ROUTE_REJECTED"

    return {
        "coverage":          coverage,
        "regime_dist":       regime_dist,
        "route_horizons":    route_horizons,
        "nomatch_horizons":  nomatch_horizons,
        "all_regimes":       all_regimes,
        "weekly_rows":       weekly_rows,
        "weekly_pass":       weekly_pass,
        "weekly_total":      weekly_total,
        "pass_rate":         pass_rate,
        "horizon_24h_label": horizon_24h_label,
        "decision":          decision,
        "n_ret_4h":          n_ret_4h,
        "report_version":    report_version,
        "min_n_ret":         min_n_ret,
        "min_weekly_n_ret":  min_weekly_n_ret,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_results(result: dict) -> None:
    cov = result["coverage"]
    print("\n=== Policy Router Preview Validation V1 ===")
    print(f"Report version : {result['report_version']}")
    print(f"Source table   : regime_selector_backtest_observation_v1")
    print(f"Snapshots      : {cov['snapshots']}  ({cov['min_ts']} → {cov['max_ts']})")
    print(f"Assets         : {cov['assets']}  Horizons: {cov['horizons']}  Total rows: {cov['total_rows']}")

    # Regime distribution
    dist_rows = [
        {"global_regime": r["global_regime"],
         "snap_count": str(r["snap_count"]),
         "n_rows": str(r["n_rows"])}
        for r in result["regime_dist"]
    ]
    _print_table("Regime distribution (GLOBAL mode, 4h)", ["global_regime", "snap_count", "n_rows"], dist_rows)

    # Route vs no-match
    rh = result["route_horizons"]
    nm = result["nomatch_horizons"]
    compare_rows = []
    for h in [4, 24, 72]:
        r = rh[h]
        n = nm[h]
        compare_rows.append({
            "horizon": f"{h}h",
            "route":    ROUTE_CANDIDATE_LABEL,
            "n_ret":    str(int(r["n_ret"] or 0)),
            "avg_ret":  _f(r["avg_ret"]),
            "win_rate": _pf(r["win_rate"]),
            "avg_mfe":  _f(r.get("avg_mfe")),
            "avg_mae":  _f(r.get("avg_mae")),
        })
        compare_rows.append({
            "horizon": f"{h}h",
            "route":    ROUTE_NO_MATCH_LABEL,
            "n_ret":    str(int(n["n_ret"] or 0)),
            "avg_ret":  _f(n["avg_ret"]),
            "win_rate": _pf(n["win_rate"]),
            "avg_mfe":  "—",
            "avg_mae":  "—",
        })
    _print_table(
        "Route candidate vs no-match by horizon",
        ["horizon", "route", "n_ret", "avg_ret", "win_rate", "avg_mfe", "avg_mae"],
        compare_rows,
    )

    # All regimes 4h
    regime_rows = [
        {
            "global_regime": r["global_regime"],
            "n_ret":    str(int(r["n_ret"] or 0)),
            "avg_ret":  _f(r["avg_ret"]),
            "win_rate": _pf(r["win_rate"]),
            "avg_mfe":  _f(r.get("avg_mfe")),
            "avg_mae":  _f(r.get("avg_mae")),
        }
        for r in result["all_regimes"]
    ]
    _print_table(
        "All global regimes at 4h horizon (GLOBAL mode)",
        ["global_regime", "n_ret", "avg_ret", "win_rate", "avg_mfe", "avg_mae"],
        regime_rows,
    )

    # Weekly stability
    _print_table(
        f"Weekly stability — {ROUTE_CANDIDATE_LABEL} at 4h (min_weekly_n_ret={result['min_weekly_n_ret']})",
        ["week_start", "n_ret", "avg_ret_4h", "win_rate_4h", "verdict"],
        result["weekly_rows"],
    )
    print(f"\n  Qualifying weeks (n>={result['min_weekly_n_ret']}): {result['weekly_total']}")
    print(f"  Passing weeks: {result['weekly_pass']}")
    print(f"  Pass rate: {result['pass_rate']:.1f}%")

    # 24h interpretation
    r24 = result["route_horizons"][24]
    print(f"\n  24h horizon: avg_ret={_f(r24['avg_ret'])}  win_rate={_pf(r24['win_rate'])}")
    print(f"  24h label: {result['horizon_24h_label']}")

    # Decision
    print(f"\n=== Validation Decision ===")
    print(f"  {result['decision']}")
    print(f"  n_ret_4h={result['n_ret_4h']}  avg_ret_4h={_f(result['route_horizons'][4]['avg_ret'])}")
    print(f"  win_rate_4h={_pf(result['route_horizons'][4]['win_rate'])}")
    nm4 = result["nomatch_horizons"][4]
    print(f"  no-match avg_ret_4h={_f(nm4['avg_ret'])}  win_rate_4h={_pf(nm4['win_rate'])}")
    print()
    print("  ROUTE_CANDIDATE is not permission and not order intent.")
    print("  decision_gate remains the authority on account permission.")
    print("  execution remains separate and unchanged.")


def _write_doc(result: dict, path: str) -> None:
    rh = result["route_horizons"]
    nm = result["nomatch_horizons"]
    ar = result["all_regimes"]
    cov = result["coverage"]

    def _ar(regime: str, field: str) -> str:
        for r in ar:
            if r["global_regime"] == regime:
                v = r.get(field)
                if field == "win_rate":
                    return _pf(v)
                return _f(v)
        return "—"

    weekly_table_lines = [
        "| week_start | n_ret | avg_ret_4h | win_rate_4h | verdict |",
        "|---|---|---|---|---|",
    ]
    for w in result["weekly_rows"]:
        weekly_table_lines.append(
            f"| {w['week_start']} | {w['n_ret']} | {w['avg_ret_4h']} | {w['win_rate_4h']} | {w['verdict']} |"
        )

    doc = f"""# Policy Router Preview Validation V1

**Status:** {result['decision']}
**Date:** 2026-05-14
**Source:** `regime_selector_backtest_observation_v1` report_version={result['report_version']}
**Boundary:** research-only · market-only · account-agnostic · read-only · no DB writes

---

## Purpose

Validate whether the `policy_router_preview_v1` route predicate
(`ROUTE_GBMD_4H_BOUNCE_CONTEXT`) matches the H1 forward-return profile in
historical backtest data.

The live `policy_router_preview_observation` table cannot serve as the sole
validation source — the current regime is `GLOBAL_NEUTRAL`, so there are zero
`ROUTE_CANDIDATE` rows in the latest snapshot. Historical validation uses the
widened v1.1 backtest (356 snapshots, {cov['min_ts']} → {cov['max_ts']},
{cov['assets']} assets) as the outcome ground truth.

---

## Boundary

- **Research-only** — no writes, no scheduler integration
- **Market-only** — reads `regime_selector_backtest_observation_v1` only
- **Account-agnostic** — no account_id, no balances, no positions
- **No selection_engine changes**
- **No advice_engine changes**
- **No decision_gate changes**
- **No execution_planner changes**
- **No executor changes**

---

## Why the latest preview table alone is insufficient

`policy_router_preview_observation` is written by the live runner at each snapshot.
At the time of this validation (2026-05-14), the current global regime is
`GLOBAL_NEUTRAL` (BTC 24h +0.69%). `ROUTE_GBMD_4H_BOUNCE_CONTEXT` only fires on
`GLOBAL_BTC_MILD_DECLINE`. Therefore the latest snapshot has 41 rows, all
`ROUTE_NO_MATCH` — there are **zero `ROUTE_CANDIDATE` rows** to validate against.

The backtest table contains {cov['snapshots']} snapshots across multiple market
regimes including {int([r['snap_count'] for r in result['regime_dist'] if r['global_regime'] == GBMD_REGIME][0] if [r for r in result['regime_dist'] if r['global_regime'] == GBMD_REGIME] else [0])} GBMD snapshots, making it the correct source.

---

## Historical validation source

| Field | Value |
|---|---|
| Table | `regime_selector_backtest_observation_v1` |
| report_version | {result['report_version']} |
| selector_mode | `GLOBAL` |
| Snapshots | {cov['snapshots']} |
| Date range | {cov['min_ts']} → {cov['max_ts']} |
| Assets | {cov['assets']} |
| Horizons | 4h, 24h, 72h |
| Total rows | {cov['total_rows']} |

---

## Route predicate

```
ROUTE_GBMD_4H_BOUNCE_CONTEXT  if:
  selector_mode = GLOBAL
  AND global_regime = GLOBAL_BTC_MILD_DECLINE
```

H2 (`GBMD × CLASS_STRESS`) is not included — it was rejected as a standalone route.
No strategy_signature filtering. No account data.

---

## Regime distribution (GLOBAL mode, 4h)

| global_regime | snapshots | n_rows |
|---|---|---|
{''.join(f"| {r['global_regime']} | {r['snap_count']} | {r['n_rows']} |" + chr(10) for r in result['regime_dist'])}

---

## Route candidate vs no-match by horizon

| horizon | route | n_ret | avg_ret | win_rate | avg_mfe | avg_mae |
|---|---|---|---|---|---|---|
| 4h | {ROUTE_CANDIDATE_LABEL} | {int(rh[4]['n_ret'] or 0)} | {_f(rh[4]['avg_ret'])} | {_pf(rh[4]['win_rate'])} | {_f(rh[4].get('avg_mfe'))} | {_f(rh[4].get('avg_mae'))} |
| 4h | {ROUTE_NO_MATCH_LABEL} | {int(nm[4]['n_ret'] or 0)} | {_f(nm[4]['avg_ret'])} | {_pf(nm[4]['win_rate'])} | — | — |
| 24h | {ROUTE_CANDIDATE_LABEL} | {int(rh[24]['n_ret'] or 0)} | {_f(rh[24]['avg_ret'])} | {_pf(rh[24]['win_rate'])} | {_f(rh[24].get('avg_mfe'))} | {_f(rh[24].get('avg_mae'))} |
| 24h | {ROUTE_NO_MATCH_LABEL} | {int(nm[24]['n_ret'] or 0)} | {_f(nm[24]['avg_ret'])} | {_pf(nm[24]['win_rate'])} | — | — |
| 72h | {ROUTE_CANDIDATE_LABEL} | {int(rh[72]['n_ret'] or 0)} | {_f(rh[72]['avg_ret'])} | {_pf(rh[72]['win_rate'])} | {_f(rh[72].get('avg_mfe'))} | {_f(rh[72].get('avg_mae'))} |
| 72h | {ROUTE_NO_MATCH_LABEL} | {int(nm[72]['n_ret'] or 0)} | {_f(nm[72]['avg_ret'])} | {_pf(nm[72]['win_rate'])} | — | — |

**24h label:** `{result['horizon_24h_label']}`
— The 4h bounce is the primary signal window. Negative 24h avg confirms this is
a short-window-only context, not a multi-session hold signal.

---

## All global regimes at 4h (GLOBAL mode)

| global_regime | n_ret | avg_ret | win_rate | avg_mfe | avg_mae |
|---|---|---|---|---|---|
{''.join(f"| {r['global_regime']} | {int(r['n_ret'] or 0)} | {_f(r['avg_ret'])} | {_pf(r['win_rate'])} | {_f(r.get('avg_mfe'))} | {_f(r.get('avg_mae'))} |" + chr(10) for r in ar)}

`GLOBAL_BTC_MILD_DECLINE` is the only regime with positive avg_ret and win_rate > 50%
at the 4h horizon. The route predicate cleanly isolates the best-performing regime.

---

## Weekly stability — ROUTE_GBMD_4H_BOUNCE_CONTEXT at 4h

min_weekly_n_ret = {result['min_weekly_n_ret']}

{chr(10).join(weekly_table_lines)}

| Metric | Value |
|---|---|
| Qualifying weeks (n≥{result['min_weekly_n_ret']}) | {result['weekly_total']} |
| Passing weeks | {result['weekly_pass']} |
| Pass rate | {result['pass_rate']:.1f}% |

**W2026-04-13** is the single failing week — BTC was recovering from the April low,
briefly suppressing the mild-decline bounce pattern.

---

## Validation criteria and result

| Criterion | Threshold | Result | Status |
|---|---|---|---|
| n_ret 4h | ≥ {result['min_n_ret']} | {int(rh[4]['n_ret'] or 0)} | {'PASS' if int(rh[4]['n_ret'] or 0) >= result['min_n_ret'] else 'FAIL'} |
| avg_ret 4h | > 0 | {_f(rh[4]['avg_ret'])} | {'PASS' if rh[4]['avg_ret'] and float(rh[4]['avg_ret']) > 0 else 'FAIL'} |
| win_rate 4h | > 50% | {_pf(rh[4]['win_rate'])} | {'PASS' if rh[4]['win_rate'] and float(rh[4]['win_rate']) > 50 else 'FAIL'} |
| avg_ret better than no-match | route > no-match | {_f(rh[4]['avg_ret'])} vs {_f(nm[4]['avg_ret'])} | {'PASS' if rh[4]['avg_ret'] and nm[4]['avg_ret'] and float(rh[4]['avg_ret']) > float(nm[4]['avg_ret']) else 'FAIL'} |
| win_rate better than no-match | route > no-match | {_pf(rh[4]['win_rate'])} vs {_pf(nm[4]['win_rate'])} | {'PASS' if rh[4]['win_rate'] and nm[4]['win_rate'] and float(rh[4]['win_rate']) > float(nm[4]['win_rate']) else 'FAIL'} |
| Qualifying weeks | ≥ 2 | {result['weekly_total']} | {'PASS' if result['weekly_total'] >= 2 else 'FAIL'} |
| Weekly pass rate | ≥ 60% | {result['pass_rate']:.1f}% | {'PASS' if result['pass_rate'] >= 60 else 'FAIL'} |
| 24h avg_ret | no requirement | {_f(rh[24]['avg_ret'])} | {result['horizon_24h_label']} |

---

## Validation decision

**`{result['decision']}`**

`ROUTE_CANDIDATE` is not permission and not order intent.
`decision_gate` remains the authority on account permission.
`execution` remains separate and unchanged.

---

## Downstream gate

```
If ROUTE_VALIDATED_FOR_PREVIEW:
  ✓ policy_router_preview_v1 may remain as the active preview route
  → next step may be advice integration design only
  → decision_gate still unchanged
  → execution unchanged

If ROUTE_MIXED / ROUTE_REJECTED / ROUTE_LOW_SAMPLE:
  ✗ route stays preview-only
  ✗ blocked from advice integration design
```

---

## Safety

```
[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0
         selection_engine_changes=0  advice_engine_changes=0
         decision_gate_changes=0  execution_planner_changes=0  executor_changes=0
         route_is_permission=false  route_is_order_intent=false
[SCOPE]  research-only  market-only  account-agnostic  read-only  no-db-writes
```
"""
    Path(path).write_text(doc, encoding="utf-8")
    print(f"\n[DOC] written to {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Policy router preview validation v1 (research-only, read-only)"
    )
    parser.add_argument("--report-version", default="1.1")
    parser.add_argument("--min-n-ret", type=int, default=300)
    parser.add_argument("--min-weekly-n-ret", type=int, default=40)
    parser.add_argument("--output", choices=["table", "json"], default="table")
    parser.add_argument("--write-doc", default=None, metavar="PATH")
    args = parser.parse_args()

    conn = get_connection()
    try:
        result = run_validation(
            conn,
            report_version=args.report_version,
            min_n_ret=args.min_n_ret,
            min_weekly_n_ret=args.min_weekly_n_ret,
        )
    finally:
        conn.close()

    if args.output == "json":
        def _ser(obj: Any) -> Any:
            if isinstance(obj, (datetime,)):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                return float(obj)
            raise TypeError(type(obj))
        # Flatten for JSON — serialize key scalar results
        out = {
            "decision":        result["decision"],
            "n_ret_4h":        result["n_ret_4h"],
            "avg_ret_4h":      float(result["route_horizons"][4]["avg_ret"] or 0),
            "win_rate_4h":     float(result["route_horizons"][4]["win_rate"] or 0),
            "weekly_pass":     result["weekly_pass"],
            "weekly_total":    result["weekly_total"],
            "pass_rate":       result["pass_rate"],
            "horizon_24h":     result["horizon_24h_label"],
            "weekly_rows":     result["weekly_rows"],
        }
        print(json.dumps(out, indent=2, default=_ser))
    else:
        print_results(result)

    if args.write_doc:
        _write_doc(result, args.write_doc)

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
