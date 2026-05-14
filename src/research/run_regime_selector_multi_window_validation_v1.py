from __future__ import annotations

"""
Synth v2 - Regime Selector Multi-Window Validation V1.

LAYER: research

BOUNDARY:
  Read-only. No DB writes. No broker calls. No account state.
  Queries regime_selector_backtest_observation_v1 only.

Purpose:
  Validate the five candidate hypotheses from
  docs/research/regime_selector_candidate_hypotheses_v1.md across
  independent market windows.

  If only one window exists in the DB, the script reports
  VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE and describes what additional
  historical replay is required to unblock each hypothesis.

Candidates:
  H1  BTC_MILD_DECLINE_4H_BOUNCE
  H2  BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE
  H3  CLASS_LEADERSHIP_OVEREXTENSION_TRAP
  H4  BTC_RISK_ON_ALT_NO_LIFT_WARNING
  H5  POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET

Usage:
  python -m src.research.run_regime_selector_multi_window_validation_v1 [OPTIONS]

Options:
  --report-version  report_version to query (default: 1.1)
  --window-mode     day / week / all  (default: day)
  --min-n-ret       Min n_ret per window to include a row (default: 40)
  --output          table / json  (default: table)
  --write-doc       Optional path to write a markdown findings report
"""

import argparse
import json
import textwrap
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_connection

load_dotenv()

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# A single window is considered insufficient for multi-window validation.
# We require at least two distinct calendar windows (days or weeks).
MIN_WINDOWS_FOR_VALIDATION = 2

# Minimum calendar-day span for the dataset to be considered multi-window.
MIN_DAY_SPAN_FOR_MULTI_WINDOW = 14


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _f(v: Any, decimals: int = 2, sign: bool = True) -> str:
    if v is None:
        return "—"
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        fmt = f"+.{decimals}f" if sign and v > 0 else f".{decimals}f"
        return format(v, fmt)
    return str(v)


def _print_table(title: str, columns: list[str], rows: list[dict]) -> None:
    print(f"\n--- {title} ---")
    if not rows:
        print("  (no rows above min-n threshold)")
        return
    widths = {c: max(len(c), max((len(str(r.get(c, "—"))) for r in rows), default=0)) for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(str(row.get(c, "—")).ljust(widths[c]) for c in columns))


def _run(cursor, sql: str, args: tuple = ()) -> list[dict]:
    cursor.execute(sql, args)
    return cursor.fetchall()


# ---------------------------------------------------------------------------
# Coverage audit
# ---------------------------------------------------------------------------

def _coverage_audit(cur, version: str) -> dict:
    rows = _run(cur, """
        SELECT
            MIN(asof_ts_utc)                       AS min_ts,
            MAX(asof_ts_utc)                       AS max_ts,
            COUNT(DISTINCT DATE(asof_ts_utc))       AS distinct_dates,
            COUNT(DISTINCT asof_ts_utc)             AS distinct_snapshots,
            COUNT(*)                                AS total_rows,
            COUNT(DISTINCT selector_mode)           AS selector_modes,
            COUNT(DISTINCT global_regime)           AS global_regimes,
            COUNT(DISTINCT asset_class_regime)      AS class_regimes,
            COUNT(DISTINCT strategy_signature)      AS distinct_sigs
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
    """, (version,))
    base = dict(rows[0]) if rows else {}

    hor = _run(cur, """
        SELECT horizon_hours,
            SUM(forward_return_pct IS NOT NULL) AS n_ret,
            SUM(forward_return_pct IS NULL)     AS n_missing
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
        GROUP BY horizon_hours ORDER BY horizon_hours
    """, (version,))
    base["horizons"] = [dict(r) for r in hor]

    day_dist = _run(cur, """
        SELECT DATE(asof_ts_utc) AS d,
            COUNT(DISTINCT asof_ts_utc) AS snapshots,
            COUNT(*)                    AS n_rows
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
        GROUP BY DATE(asof_ts_utc) ORDER BY d
    """, (version,))
    base["day_distribution"] = [dict(r) for r in day_dist]

    # Global regime distribution
    gr = _run(cur, """
        SELECT global_regime, COUNT(*) AS n
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s AND selector_mode = 'GLOBAL'
        GROUP BY global_regime ORDER BY n DESC
    """, (version,))
    base["global_regime_dist"] = [dict(r) for r in gr]

    # Determine multi-window status
    min_ts = base.get("min_ts")
    max_ts = base.get("max_ts")
    if min_ts and max_ts:
        span_days = (max_ts - min_ts).days
    else:
        span_days = 0
    base["span_days"] = span_days
    base["is_multi_window"] = span_days >= MIN_DAY_SPAN_FOR_MULTI_WINDOW
    return base


# ---------------------------------------------------------------------------
# Window grouping
# ---------------------------------------------------------------------------

def _isoweek(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _assign_windows(day_distribution: list[dict], mode: str) -> dict[str, list[date]]:
    """Return {window_label: [date, ...]} mapping."""
    windows: dict[str, list[date]] = {}
    for entry in day_distribution:
        d = entry["d"] if isinstance(entry["d"], date) else entry["d"]
        if mode == "day":
            key = str(d)
        elif mode == "week":
            key = _isoweek(d)
        else:  # all
            key = "all"
        windows.setdefault(key, []).append(d)
    return windows


# ---------------------------------------------------------------------------
# Hypothesis evaluation helpers
# ---------------------------------------------------------------------------

def _hyp_aggregate(cur, version: str, selector_mode: str, horizon: int,
                   extra_where: str, args: tuple, min_n: int,
                   date_filter: tuple[date, date] | None = None) -> dict | None:
    date_clause = ""
    date_args: tuple = ()
    if date_filter:
        date_clause = "AND DATE(asof_ts_utc) BETWEEN %s AND %s"
        date_args = (date_filter[0], date_filter[1])

    sql = f"""
        SELECT
            SUM(forward_return_pct IS NOT NULL) AS n_ret,
            ROUND(AVG(forward_return_pct), 3)   AS avg_ret,
            ROUND(AVG(mfe_pct), 3)              AS avg_mfe,
            ROUND(AVG(mae_pct), 3)              AS avg_mae,
            ROUND(100.0 * SUM(forward_return_pct > 0)
                / NULLIF(SUM(forward_return_pct IS NOT NULL), 0), 1) AS win_rate
        FROM regime_selector_backtest_observation_v1
        WHERE report_version = %s
          AND selector_mode   = %s
          AND horizon_hours   = %s
          {extra_where}
          {date_clause}
    """
    rows = _run(cur, sql, (version, selector_mode, horizon) + args + date_args)
    r = rows[0] if rows else {}
    n_ret = int(r.get("n_ret") or 0)
    if n_ret < min_n:
        return None
    return {
        "n_ret":    n_ret,
        "avg_ret":  float(r["avg_ret"]) if r.get("avg_ret") is not None else None,
        "avg_mfe":  float(r["avg_mfe"]) if r.get("avg_mfe") is not None else None,
        "avg_mae":  float(r["avg_mae"]) if r.get("avg_mae") is not None else None,
        "win_rate": float(r["win_rate"]) if r.get("win_rate") is not None else None,
    }


# ---------------------------------------------------------------------------
# Per-hypothesis definitions
# ---------------------------------------------------------------------------

def _eval_h1(cur, version: str, min_n: int,
             date_filter: tuple[date, date] | None = None) -> dict | None:
    return _hyp_aggregate(
        cur, version, "GLOBAL", 4,
        "AND global_regime = 'GLOBAL_BTC_MILD_DECLINE'", (),
        min_n, date_filter,
    )


def _eval_h2(cur, version: str, min_n: int,
             date_filter: tuple[date, date] | None = None) -> dict | None:
    return _hyp_aggregate(
        cur, version, "GLOBAL_CLASS", 4,
        "AND global_regime = 'GLOBAL_BTC_MILD_DECLINE' AND asset_class_regime = 'CLASS_STRESS'", (),
        min_n, date_filter,
    )


def _eval_h3(cur, version: str, min_n: int,
             date_filter: tuple[date, date] | None = None) -> dict | None:
    return _hyp_aggregate(
        cur, version, "GLOBAL_CLASS", 4,
        "AND asset_class_regime = 'CLASS_LEADERSHIP'", (),
        min_n, date_filter,
    )


def _eval_h4(cur, version: str, min_n: int,
             date_filter: tuple[date, date] | None = None) -> dict | None:
    return _hyp_aggregate(
        cur, version, "GLOBAL", 4,
        "AND global_regime = 'GLOBAL_RISK_ON'", (),
        min_n, date_filter,
    )


def _eval_h5(cur, version: str, min_n: int,
             date_filter: tuple[date, date] | None = None) -> dict | None:
    insuff_pattern = "%%POLICY=INSUFFICIENT%%"
    return _hyp_aggregate(
        cur, version, "STRATEGY_SIGNATURE", 24,
        "AND strategy_signature LIKE %s", (insuff_pattern,),
        min_n, date_filter,
    )


# ---------------------------------------------------------------------------
# Stability classification
# ---------------------------------------------------------------------------

def _sign_stable(results: list[dict | None], key: str = "avg_ret") -> bool:
    vals = [r[key] for r in results if r and r.get(key) is not None]
    if len(vals) < 2:
        return False
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    return pos == len(vals) or neg == len(vals)


HYPO_PASS = {
    "H1": lambda r: r["avg_ret"] is not None and r["avg_ret"] > 0 and r["win_rate"] is not None and r["win_rate"] > 50,
    "H2": lambda r: r["avg_ret"] is not None and r["avg_ret"] > 0 and r["win_rate"] is not None and r["win_rate"] > 55,
    "H3": lambda r: r["avg_ret"] is not None and r["avg_ret"] < 0 and r["win_rate"] is not None and r["win_rate"] < 40,
    "H4": lambda r: r["avg_ret"] is not None and r["avg_ret"] < 0 and r["win_rate"] is not None and r["win_rate"] < 30,
    "H5": lambda r: r["avg_ret"] is not None and r["avg_ret"] < 0 and r["win_rate"] is not None and r["win_rate"] < 30,
}


def _classify_stability(hyp_id: str, per_window: list[dict | None], is_multi: bool) -> str:
    valid_windows = [r for r in per_window if r is not None]
    if not valid_windows:
        return "LOW_SAMPLE"

    fn = HYPO_PASS[hyp_id]
    passes = [fn(r) for r in valid_windows]

    if not is_multi:
        # Regardless of per-day results, the overall status is blocked
        all_pass = all(passes) and len(passes) >= 2
        if all_pass:
            return "PROMISING_SINGLE_WINDOW_ONLY"
        elif any(passes):
            return "PROMISING_SINGLE_WINDOW_ONLY"
        else:
            return "VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE"

    # True multi-window path (not yet reachable with current data)
    n_windows = len(valid_windows)
    n_pass = sum(passes)
    if n_windows < MIN_WINDOWS_FOR_VALIDATION:
        return "LOW_SAMPLE"
    ratio = n_pass / n_windows
    if ratio >= 0.8:
        return "PROMISING_REPEATED"
    elif ratio >= 0.5:
        return "MIXED"
    else:
        return "REJECTED"


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def _fmt_row(label: str, r: dict | None) -> dict:
    if r is None:
        return {"window": label, "n_ret": "—", "avg_ret%": "—", "win_rate%": "—",
                "avg_mfe%": "—", "avg_mae%": "—", "pass": "—"}
    passed_str = "PASS" if r.get("_pass") else "FAIL"
    return {
        "window":    label,
        "n_ret":     str(r["n_ret"]),
        "avg_ret%":  _f(r["avg_ret"]),
        "win_rate%": _f(r["win_rate"], 1),
        "avg_mfe%":  _f(r["avg_mfe"]),
        "avg_mae%":  _f(r["avg_mae"]),
        "pass":      passed_str,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regime selector multi-window validation runner (read-only)"
    )
    parser.add_argument("--report-version", default="1.1")
    parser.add_argument("--window-mode", choices=["day", "week", "all"], default="day")
    parser.add_argument("--min-n-ret", type=int, default=40)
    parser.add_argument("--output", choices=["table", "json"], default="table")
    parser.add_argument("--write-doc", default=None,
                        help="Optional path to write a markdown findings report")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # ----------------------------------------------------------------
            # Step 1 — Coverage audit
            # ----------------------------------------------------------------
            cov = _coverage_audit(cur, args.report_version)

            day_dist = cov["day_distribution"]
            windows = _assign_windows(day_dist, args.window_mode)
            window_labels = sorted(windows.keys())
            is_multi = cov["is_multi_window"]

            # ----------------------------------------------------------------
            # Step 2 — Per-hypothesis per-window evaluation
            # ----------------------------------------------------------------
            def _window_date_filter(label: str) -> tuple[date, date]:
                dates = windows[label]
                return (min(dates), max(dates))

            hyps = {
                "H1": (_eval_h1, "BTC_MILD_DECLINE_4H_BOUNCE",              "GLOBAL", 4),
                "H2": (_eval_h2, "BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE",  "GLOBAL_CLASS", 4),
                "H3": (_eval_h3, "CLASS_LEADERSHIP_OVEREXTENSION_TRAP",       "GLOBAL_CLASS", 4),
                "H4": (_eval_h4, "BTC_RISK_ON_ALT_NO_LIFT_WARNING",           "GLOBAL", 4),
                "H5": (_eval_h5, "POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET","STRATEGY_SIGNATURE", 24),
            }

            results: dict[str, dict] = {}
            for hyp_id, (eval_fn, name, mode, hz) in hyps.items():
                # Overall aggregate (all data)
                overall = eval_fn(cur, args.report_version, args.min_n_ret)
                if overall:
                    overall["_pass"] = HYPO_PASS[hyp_id](overall)

                # Per-window
                per_window: list[dict | None] = []
                per_window_labels: list[str] = []
                for label in window_labels:
                    df = _window_date_filter(label)
                    r = eval_fn(cur, args.report_version, max(5, args.min_n_ret // 4), df)
                    if r:
                        r["_pass"] = HYPO_PASS[hyp_id](r)
                    per_window.append(r)
                    per_window_labels.append(label)

                stability = _classify_stability(hyp_id, per_window, is_multi)
                results[hyp_id] = {
                    "name":               name,
                    "mode":               mode,
                    "horizon_hours":      hz,
                    "overall":            overall,
                    "per_window":         per_window,
                    "per_window_labels":  per_window_labels,
                    "stability":          stability,
                }

    finally:
        conn.close()

    # ----------------------------------------------------------------
    # Output
    # ----------------------------------------------------------------
    if args.output == "json":
        def _ser(obj: Any) -> Any:
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                return float(obj)
            raise TypeError(type(obj))
        print(json.dumps({
            "coverage":      {k: v for k, v in cov.items() if k != "day_distribution"},
            "day_span_days": cov["span_days"],
            "is_multi_window": is_multi,
            "window_mode":   args.window_mode,
            "windows":       window_labels,
            "hypotheses":    {
                hid: {
                    "name":      v["name"],
                    "stability": v["stability"],
                    "overall":   {k: vv for k, vv in (v["overall"] or {}).items() if not k.startswith("_")},
                }
                for hid, v in results.items()
            },
        }, indent=2, default=_ser))
    else:
        _print_coverage(cov, args.window_mode, is_multi)
        _print_hypotheses(results, args.min_n_ret)

    _print_summary_table(results, is_multi)
    _print_next_steps(is_multi, cov)

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

    if args.write_doc:
        _write_markdown(args.write_doc, cov, results, args, is_multi)
        print(f"\n[DOC] wrote findings report to {args.write_doc}")


# ---------------------------------------------------------------------------
# Table printing
# ---------------------------------------------------------------------------

def _print_coverage(cov: dict, window_mode: str, is_multi: bool) -> None:
    print("\n" + "=" * 70)
    print("COVERAGE AUDIT")
    print("=" * 70)
    min_ts = cov.get("min_ts")
    max_ts = cov.get("max_ts")
    print(f"  min_ts:            {min_ts}")
    print(f"  max_ts:            {max_ts}")
    print(f"  span_days:         {cov.get('span_days')}")
    print(f"  distinct_dates:    {cov.get('distinct_dates')}")
    print(f"  distinct_snapshots:{cov.get('distinct_snapshots')}")
    print(f"  total_rows:        {cov.get('total_rows')}")
    print(f"  selector_modes:    {cov.get('selector_modes')}")
    print(f"  global_regimes:    {cov.get('global_regimes')}")
    print(f"  class_regimes:     {cov.get('class_regimes')}")
    print(f"  distinct_sigs:     {cov.get('distinct_sigs')}")
    print()
    print(f"  window_mode:       {window_mode}")
    print(f"  is_multi_window:   {is_multi}  (requires span >= {MIN_DAY_SPAN_FOR_MULTI_WINDOW} days)")
    print()

    print("  Horizon forward-return coverage:")
    for h in cov.get("horizons", []):
        print(f"    {h['horizon_hours']:2d}h  n_ret={h['n_ret']}  n_missing={h['n_missing']}")
    print()

    print("  Day distribution:")
    for d in cov.get("day_distribution", []):
        print(f"    {d['d']}  snapshots={d['snapshots']}  rows={d['n_rows']}")
    print()

    print("  Global regime distribution (GLOBAL selector mode):")
    for g in cov.get("global_regime_dist", []):
        print(f"    {g['global_regime']:<35}  n={g['n']}")
    print()

    if not is_multi:
        print(
            "  !! VALIDATION STATUS: VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE\n"
            "  !! Only a single 4-day bearish window exists in the DB.\n"
            "  !! Day-level splits are shown but are NOT independent windows.\n"
            "  !! All hypotheses remain UNVALIDATED at the multi-window level."
        )


def _print_hypotheses(results: dict, min_n: int) -> None:
    cols = ["window", "n_ret", "avg_ret%", "win_rate%", "avg_mfe%", "avg_mae%", "pass"]
    for hyp_id, v in results.items():
        name = v["name"]
        hz = v["horizon_hours"]
        stability = v["stability"]
        print(f"\n{'=' * 70}")
        print(f"{hyp_id}  {name}  (horizon={hz}h)  stability={stability}")
        print(f"{'=' * 70}")

        overall = v["overall"]
        rows = []
        if overall:
            rows.append(_fmt_row("OVERALL", overall))
        for label, r in zip(v["per_window_labels"], v["per_window"]):
            rows.append(_fmt_row(label, r))
        _print_table(f"{hyp_id} per-window evidence (min_n_ret≥{min_n}//4)", cols, rows)


def _print_summary_table(results: dict, is_multi: bool) -> None:
    top_status = "VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE" if not is_multi else "MULTI_WINDOW_DATA_PRESENT"
    print(f"\n{'=' * 70}")
    print(f"VALIDATION SUMMARY  (top-level: {top_status})")
    print(f"{'=' * 70}")
    cols = ["id", "name", "horizon_h", "overall_avg_ret%", "overall_win_rate%", "overall_n_ret", "stability"]
    rows = []
    for hyp_id, v in results.items():
        ov = v["overall"]
        rows.append({
            "id":               hyp_id,
            "name":             v["name"],
            "horizon_h":        str(v["horizon_hours"]),
            "overall_avg_ret%": _f(ov["avg_ret"]) if ov else "—",
            "overall_win_rate%":_f(ov["win_rate"], 1) if ov else "—",
            "overall_n_ret":    str(ov["n_ret"]) if ov else "—",
            "stability":        v["stability"],
        })
    _print_table("Hypothesis stability", cols, rows)


def _print_next_steps(is_multi: bool, cov: dict) -> None:
    print(f"\n{'=' * 70}")
    print("REQUIRED NEXT STEPS TO UNBLOCK VALIDATION")
    print(f"{'=' * 70}")
    if not is_multi:
        print(textwrap.dedent("""
  The DB contains report_version=1.1 rows only for 2026-05-10 to 2026-05-14
  (5 calendar days, 1 bearish macro window). This is insufficient for
  multi-window hypothesis validation.

  Required to unblock:

  1. Historical replay across a wider time range using
     run_regime_selector_backtest_v1.py with --from-ts / --to-ts covering
     at minimum:
       a. 60+ days back from the current date (--limit-snapshots 1440)
       b. A period containing a sustained BTC bull run
          (e.g. BTC +20% over 30 days) to test H4
       c. A period containing a rotation window
          (BTC flat, alts outperforming) to test H2 and H3

  2. After historical replay, re-run this validation script. The coverage
     check will pass once span_days >= 14 and multiple distinct regime
     types appear across separate calendar weeks.

  3. Do NOT promote any candidate to active_regime_observation design
     until at least 2 independent windows (different macro regime
     character) both show consistent hypothesis pass results.

  Current hypothesis statuses are per-day splits within the SAME bearish
  window. They provide weak internal consistency evidence only.
        """).strip())
    else:
        print("  Multi-window data is present. Review per-hypothesis stability above.")
        print("  PROMISING_REPEATED → eligible for active_regime_observation design review.")
        print("  MIXED / REJECTED   → downgrade or reject the candidate.")
        print("  LOW_SAMPLE         → collect more data before deciding.")


# ---------------------------------------------------------------------------
# Markdown report writer
# ---------------------------------------------------------------------------

def _write_markdown(path: str, cov: dict, results: dict, args: Any, is_multi: bool) -> None:
    min_ts = cov.get("min_ts", "—")
    max_ts = cov.get("max_ts", "—")
    span = cov.get("span_days", 0)
    now = datetime.now(UTC).strftime("%Y-%m-%d")

    top_status = "VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE" if not is_multi else "MULTI_WINDOW_DATA_PRESENT"

    lines: list[str] = [
        "# Regime Selector Multi-Window Validation V1",
        "",
        f"**Generated:** {now}",
        f"**Script:** `run_regime_selector_multi_window_validation_v1.py`",
        f"**Table:** `regime_selector_backtest_observation_v1`",
        f"**report_version:** {args.report_version}",
        f"**window_mode:** {args.window_mode}",
        f"**min_n_ret:** {args.min_n_ret}",
        "",
        "---",
        "",
        "## Boundary",
        "",
        "- Research-only",
        "- Market-only",
        "- Account-agnostic",
        "- No account state, no balances, no positions",
        "- No broker calls",
        "- No order logic",
        "- No paper/live distinction",
        "- No routing implementation",
        "",
        "---",
        "",
        "## Source candidates",
        "",
        "- `docs/research/regime_selector_candidate_hypotheses_v1.md`",
        "- `docs/research/regime_selector_backtest_v1_1_findings_summary.md`",
        "",
        "---",
        "",
        "## Coverage audit",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| min_ts | {min_ts} |",
        f"| max_ts | {max_ts} |",
        f"| span_days | {span} |",
        f"| distinct_dates | {cov.get('distinct_dates')} |",
        f"| distinct_snapshots | {cov.get('distinct_snapshots')} |",
        f"| total_rows | {cov.get('total_rows')} |",
        f"| selector_modes | {cov.get('selector_modes')} |",
        f"| global_regimes | {cov.get('global_regimes')} |",
        f"| class_regimes | {cov.get('class_regimes')} |",
        f"| distinct_sigs | {cov.get('distinct_sigs')} |",
        "",
        "**Horizon forward-return coverage:**",
        "",
        "| horizon_h | n_ret | n_missing |",
        "|---|---|---|",
    ]
    for h in cov.get("horizons", []):
        lines.append(f"| {h['horizon_hours']}h | {h['n_ret']} | {h['n_missing']} |")

    lines += [
        "",
        "**Day distribution:**",
        "",
        "| date | snapshots | rows |",
        "|---|---|---|",
    ]
    for d in cov.get("day_distribution", []):
        lines.append(f"| {d['d']} | {d['snapshots']} | {d['n_rows']} |")

    lines += [
        "",
        "**Global regime distribution (GLOBAL selector mode):**",
        "",
        "| global_regime | n |",
        "|---|---|",
    ]
    for g in cov.get("global_regime_dist", []):
        lines.append(f"| {g['global_regime']} | {g['n']} |")

    lines += [
        "",
        "---",
        "",
        "## Validation method",
        "",
        f"Window mode: **{args.window_mode}**. The dataset is split by calendar "
        f"{args.window_mode} and each hypothesis is evaluated independently per window.",
        "",
        f"Minimum n_ret per window: **{args.min_n_ret}** (per-window threshold is "
        f"min_n_ret // 4 = {max(5, args.min_n_ret // 4)} to allow day-level splits).",
        "",
        "Multi-window threshold: the dataset must span at least "
        f"**{MIN_DAY_SPAN_FOR_MULTI_WINDOW} calendar days** across distinct macro regime "
        "characters (bull, bear, sideways) before any hypothesis can be promoted.",
        "",
        "---",
        "",
        "## Hypothesis pass/fail criteria",
        "",
        "| Hypothesis | Primary horizon | Pass condition |",
        "|---|---|---|",
        "| H1 BTC_MILD_DECLINE_4H_BOUNCE | 4h | avg_ret > 0 AND win_rate > 50% |",
        "| H2 BTC_MILD_DECLINE_CLASS_STRESS_4H_BOUNCE | 4h | avg_ret > 0 AND win_rate > 55% |",
        "| H3 CLASS_LEADERSHIP_OVEREXTENSION_TRAP | 4h | avg_ret < 0 AND win_rate < 40% |",
        "| H4 BTC_RISK_ON_ALT_NO_LIFT_WARNING | 4h | avg_ret < 0 AND win_rate < 30% |",
        "| H5 POLICY_INSUFFICIENT_SAMPLE_NEGATIVE_BUCKET | 24h | avg_ret < 0 AND win_rate < 30% |",
        "",
        "Stability classifications:",
        "",
        "| Status | Meaning |",
        "|---|---|",
        "| `VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE` | Data does not span multiple independent windows |",
        "| `PROMISING_REPEATED` | Passes in ≥ 80% of windows (multi-window only) |",
        "| `PROMISING_SINGLE_WINDOW_ONLY` | Passes within the available window but no multi-window evidence |",
        "| `MIXED` | Passes in 50–80% of windows |",
        "| `REJECTED` | Passes in < 50% of windows |",
        "| `LOW_SAMPLE` | Insufficient n_ret to evaluate |",
        "",
        "---",
        "",
        "## Results",
        "",
        f"**Top-level validation status: `{top_status}`**",
        "",
    ]

    if not is_multi:
        lines += [
            "> **IMPORTANT:** The DB contains only a single 4-day bearish window",
            "> (2026-05-10 to 2026-05-14, 120 snapshots). Day-level splits within",
            "> this window are shown for internal consistency inspection only.",
            "> They are **not** independent market windows. All hypotheses remain",
            "> **unvalidated** at the multi-window level.",
            "",
        ]

    for hyp_id, v in results.items():
        ov = v["overall"]
        stability = v["stability"]
        lines += [
            f"### {hyp_id} — {v['name']}",
            "",
            f"**Horizon:** {v['horizon_hours']}h | **Stability:** `{stability}`",
            "",
            "**Overall aggregate:**",
            "",
            "| n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% |",
            "|---|---|---|---|---|",
        ]
        if ov:
            lines.append(
                f"| {ov['n_ret']} | {_f(ov['avg_ret'])} | {_f(ov['win_rate'],1)} "
                f"| {_f(ov['avg_mfe'])} | {_f(ov['avg_mae'])} |"
            )
        else:
            lines.append("| — | — | — | — | — |")

        lines += [
            "",
            f"**Per-{args.window_mode} breakdown (min_n_ret≥{max(5, args.min_n_ret//4)}):**",
            "",
            "| window | n_ret | avg_ret% | win_rate% | avg_mfe% | avg_mae% | pass |",
            "|---|---|---|---|---|---|---|",
        ]
        for label, r in zip(v["per_window_labels"], v["per_window"]):
            row = _fmt_row(label, r)
            lines.append(
                f"| {row['window']} | {row['n_ret']} | {row['avg_ret%']} "
                f"| {row['win_rate%']} | {row['avg_mfe%']} | {row['avg_mae%']} | {row['pass']} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## Insufficient coverage handling",
        "",
        "When only the May 2026 mini-window is present, this script:",
        "",
        "- Reports `VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE` as the top-level status.",
        "- Still produces day-level evidence tables for internal consistency inspection.",
        "- Does not promote any hypothesis to routing-ready status.",
        "- States explicitly: **Candidate hypotheses remain unvalidated.**",
        "",
        "---",
        "",
        "## Required next data / replay steps",
        "",
        "To unblock multi-window validation:",
        "",
        "1. Run `run_regime_selector_backtest_v1.py` with a much wider `--from-ts` / `--to-ts`:",
        "   - Target: 60–90 days of history",
        "   - `--limit-snapshots 2160` (90 days × 6 snapshots/day at 4h)",
        "   - Ensure candle history covers the full window in `obs_market_candle`",
        "",
        "2. Required window characters for full validation:",
        "   - Sustained BTC bull run (+20% over 30 days) — to test H4",
        "   - Rotation window (BTC flat, alts outperforming) — to test H2 and H3",
        "   - Post-spike crash (BTC -30% in 7 days) — to test H1 edge case",
        "   - Sideways ranging (BTC ±5% over 30 days) — baseline neutrality",
        "",
        "3. After replay, re-run:",
        "   ```",
        "   python -m src.research.run_regime_selector_multi_window_validation_v1 \\",
        "     --report-version 1.1 \\",
        "     --window-mode week \\",
        "     --min-n-ret 40",
        "   ```",
        "",
        "4. Do NOT design `active_regime_observation` until at least one hypothesis",
        "   achieves `PROMISING_REPEATED` status across ≥ 2 independent macro windows.",
        "",
        "---",
        "",
        "## Downstream gate",
        "",
        "```",
        "1. regime_selector_backtest_v1.1 findings  ← DONE",
        "2. regime_selector_candidate_hypotheses_v1  ← DONE",
        "3. regime_selector_multi_window_validation_v1  ← THIS DOCUMENT",
        "   status: VALIDATION_BLOCKED_INSUFFICIENT_COVERAGE",
        "   gate: DO NOT PROCEED to step 4 until at least one hypothesis",
        "         achieves PROMISING_REPEATED across independent market windows",
        "4. active_regime_observation design  ← BLOCKED",
        "5. policy_router preview  ← BLOCKED",
        "6. selection/advice integration  ← BLOCKED",
        "7. decision_gate / execution  ← NOT STARTED (separate design)",
        "```",
        "",
        "---",
        "",
        "## Safety",
        "",
        "```",
        "[SAFETY] broker_calls=0  broker_writes=0  order_submission=0  live_orders=0",
        "[SCOPE]  research-only  market-only  account-agnostic  read-only-query",
        "```",
    ]

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
