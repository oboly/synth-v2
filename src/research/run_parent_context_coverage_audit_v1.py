"""
run_parent_context_coverage_audit_v1.py
=========================================
Research runner: Audit parent-horizon context coverage for outcome_rows_v1 dataset.

Goal
----
  Determine WHY 87.7% of events in outcome_rows_v1 have PARENT_CONTEXT_UNKNOWN
  and whether valid historical coverage can be increased without fabrication or
  future leakage.

Failure Reason Classification
------------------------------
  SOURCE_MISSING            No pre-computed parent context source exists for
                            the relevant symbol / time range in data/research/.
                            The canonical_fib_zone_map_v1 table exists in the
                            live DB but is not accessible from pre-computed
                            research artifacts.
  SYMBOL_MISSING            Symbol not found in any candidate source.
  TIME_RANGE_MISSING        Candidate source exists but does not cover this
                            event timestamp.
  ASOF_JOIN_MISS            Source covers the time range but no as-of row
                            is available at or before event timestamp.
  INTERVAL_MISMATCH         Source is at a different interval than required.
  MAP_ID_MISMATCH           Source map IDs do not align.
  CONTEXT_TOO_STALE         Source exists but is older than max_context_age.
  QUALITY_FILTERED          Source exists but quality below threshold.
  PARENT_HORIZON_NOT_DEFINED No parent horizon concept defined or derivable
                            for this event (e.g. breath model returns no
                            directional parent-horizon signal).
  CONTEXT_TRULY_UNKNOWN     Source exists, all checks pass, but state is
                            genuinely unknown (e.g. NEUTRAL_TRANSITION — the
                            breath model could not classify the market state).

Coverage Improvement Conclusion
---------------------------------
  Coverage CANNOT be increased from available pre-computed research artifacts.
  The outcome_rows_v1 dataset contains only market_breath signal fields, not
  parent fib map analysis. No parent fib map files were found in data/research/
  for the 2026-03-14 to 2026-05-12 period.

  To increase coverage:
  1. Query canonical_fib_zone_map_v1 from the live DB for the relevant period
     and join on (symbol, venue, interval_code, asof_ts_utc <= event_ts).
  2. Use strict backward matching (parent_context_ts <= decision_ts).
  3. Never synthesize a parent terminal state.
  4. Preserve source_refs and context age.

  This runner documents the limitation precisely without manufacturing coverage.
  It retains fail-closed behavior for all unknown events.

Candidate Reusable Sources Inspected
--------------------------------------
  market_breath_analysis_v1: 41 rows · single date (2026-05-16) · outside range.
  market_breath_v1_1_calibration_audit: phase distribution by asof; per-symbol summary
    only; no parent fib map context; no parent terminal state.
  aplus_table1_only_normalized_v1: A+ external research snapshots; not parent fib maps.
  aplus_phase_exposure_stability_v1: phase exposure trajectories; not parent context.
  canonical_fib_zone_map_v1 (DB table): canonical source; not available as a pre-computed
    file artifact in data/research/; requires DB query.

Strict Historical Matching
--------------------------
  parent_context_ts_utc <= decision_ts_utc (enforced).
  Synthetic states derived only from the event's own row (point-in-time by construction).
  Future rows are never synthesized, assumed, or interpolated.

Research-only. No DB writes. No broker/account/execution/decision_gate code.

Safety markers
--------------
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
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RUNNER_NAME = "PARENT_CONTEXT_COVERAGE_AUDIT_V1"
VERSION = "1.0.0"
DEFAULT_OUTPUT_DIR = Path("data/research/parent_context_coverage_audit_v1")
OUTCOME_ROWS_PATH = Path(
    "data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl"
)
MAX_EVENTS = 2500

# Known candidate source paths to inspect
_CANDIDATE_SOURCES: list[dict[str, str]] = [
    {
        "name": "market_breath_analysis_v1",
        "path": "data/research/market_breath_analysis_v1/market_breath_observations_v1.jsonl",
        "type": "breath_observation",
        "has_parent_fib_map": "NO",
        "has_parent_terminal_state": "NO",
        "note": "Per-symbol breath snapshot; market_breath_phase only; no parent fib map.",
    },
    {
        "name": "market_breath_v1_1_calibration_audit",
        "path": "data/research/market_breath_v1_1_calibration_audit/phase_distribution_by_asof_v1.jsonl",
        "type": "phase_distribution_summary",
        "has_parent_fib_map": "NO",
        "has_parent_terminal_state": "NO",
        "note": "Aggregated phase distribution by asof_ts; no per-symbol parent context.",
    },
    {
        "name": "aplus_table1_only_normalized_v1",
        "path": "data/research/aplus_table1_only_normalized_v1/table1_normalized_20260513_1915.jsonl",
        "type": "aplus_external_research",
        "has_parent_fib_map": "NO",
        "has_parent_terminal_state": "NO",
        "note": "A+ external research table 1; not parent fib map analysis.",
    },
    {
        "name": "aplus_phase_exposure_stability_v1",
        "path": "data/research/aplus_phase_exposure_stability_v1/phase_exposure_transition_rows_v1.jsonl",
        "type": "phase_exposure_trajectory",
        "has_parent_fib_map": "NO",
        "has_parent_terminal_state": "NO",
        "note": "Phase exposure trajectories; not parent context.",
    },
    {
        "name": "canonical_fib_zone_map_v1 (DB)",
        "path": "DB_ONLY",
        "type": "canonical_fib_map",
        "has_parent_fib_map": "YES",
        "has_parent_terminal_state": "DERIVABLE",
        "note": (
            "Canonical source for parent fib map context. "
            "Exists in live DB (canonical_fib_zone_map_v1 table). "
            "NOT available as a pre-computed file artifact in data/research/. "
            "Would require DB query with strict backward as-of join. "
            "Coverage increase possible if DB is queried — but outside this runner's scope."
        ),
    },
]

# Failure reason codes
REASON_SOURCE_MISSING = "SOURCE_MISSING"
REASON_SYMBOL_MISSING = "SYMBOL_MISSING"
REASON_TIME_RANGE_MISSING = "TIME_RANGE_MISSING"
REASON_ASOF_JOIN_MISS = "ASOF_JOIN_MISS"
REASON_INTERVAL_MISMATCH = "INTERVAL_MISMATCH"
REASON_MAP_ID_MISMATCH = "MAP_ID_MISMATCH"
REASON_CONTEXT_TOO_STALE = "CONTEXT_TOO_STALE"
REASON_QUALITY_FILTERED = "QUALITY_FILTERED"
REASON_PARENT_HORIZON_NOT_DEFINED = "PARENT_HORIZON_NOT_DEFINED"
REASON_CONTEXT_TRULY_UNKNOWN = "CONTEXT_TRULY_UNKNOWN"
REASON_SYNTHETIC_PROXY_USED = "SYNTHETIC_PROXY_USED"

_NEUTRAL_TRANSITION_REASONS = (REASON_SOURCE_MISSING, REASON_CONTEXT_TRULY_UNKNOWN)


def classify_unknown_reason(
    breath_phase: str,
    breath_state: str,
    symbol: str,
    asof_ts: str,
    candidate_source_coverage: dict[str, Any],
) -> tuple[str, str]:
    """
    Classify the primary and secondary failure reason for a PARENT_CONTEXT_UNKNOWN event.

    Returns (primary_reason, detail_note).

    Priority:
      1. No pre-computed parent fib map source → SOURCE_MISSING (all events).
      2. NEUTRAL_TRANSITION breath phase → also CONTEXT_TRULY_UNKNOWN
         (breath model cannot derive parent state from neutral signal).
      3. Non-neutral events → PARENT_HORIZON_NOT_DEFINED
         (breath proxy exists but is not validated parent fib map analysis).

    The synthetic proxy used in the parent-terminal runner is labeled
    SYNTHETIC_PROXY_USED — it is not a valid parent context source.
    """
    source_available = candidate_source_coverage.get("file_available", False)
    covers_symbol = candidate_source_coverage.get("covers_symbol", False)
    covers_time = candidate_source_coverage.get("covers_time", False)

    if not source_available:
        if breath_phase == "NEUTRAL_TRANSITION":
            return (
                REASON_SOURCE_MISSING,
                (
                    "No pre-computed parent fib map file in data/research/. "
                    "NEUTRAL_TRANSITION breath phase cannot derive parent state: "
                    "breath model could not classify market state → also CONTEXT_TRULY_UNKNOWN."
                ),
            )
        else:
            return (
                REASON_SOURCE_MISSING,
                (
                    f"No pre-computed parent fib map file in data/research/. "
                    f"Breath phase={breath_phase} provides synthetic proxy only (not parent map analysis). "
                    f"→ also PARENT_HORIZON_NOT_DEFINED for synthetic path."
                ),
            )

    if not covers_symbol:
        return (REASON_SYMBOL_MISSING, f"symbol={symbol} not in source coverage.")

    if not covers_time:
        return (REASON_TIME_RANGE_MISSING, f"asof_ts={asof_ts} not in source time range.")

    return (REASON_ASOF_JOIN_MISS, f"Symbol/time covered but no as-of row found for {asof_ts}.")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_events(
    path: Path,
    max_events: int = MAX_EVENTS,
    symbols: Optional[list[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Required input not found: {path}")
    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = (r["symbol"], r["asof_ts_utc"])
            if key in seen:
                continue
            seen.add(key)
            if symbols and r["symbol"] not in symbols:
                continue
            if date_from and r["asof_ts_utc"] < date_from:
                continue
            if date_to and r["asof_ts_utc"] > date_to:
                continue
            rows.append(r)
    rows.sort(key=lambda r: (r["asof_ts_utc"], r["symbol"]))
    return rows[:max_events]


# ---------------------------------------------------------------------------
# Candidate source inspection
# ---------------------------------------------------------------------------

def inspect_candidate_sources(
    outcome_symbols: set[str],
    outcome_date_range: tuple[str, str],
) -> list[dict[str, Any]]:
    """
    Inspect each candidate source file for coverage relevance.
    Returns annotated source metadata (no DB queries; file-only).
    """
    results = []
    for src in _CANDIDATE_SOURCES:
        path_str = src["path"]
        file_available = False
        covers_symbol = False
        covers_time = False
        row_count = 0
        source_symbols: set[str] = set()
        source_date_range: tuple[str, str] = ("", "")
        has_parent_fields = "NO"
        usable_for_parent_context = False

        if path_str == "DB_ONLY":
            file_available = False  # not a file artifact
            has_parent_fields = src.get("has_parent_fib_map", "NO")
            usable_for_parent_context = (has_parent_fields == "YES")
            row_count = -1  # DB — unknown
        else:
            p = Path(path_str)
            file_available = p.exists()
            if file_available:
                try:
                    with open(p) as f:
                        src_rows = [json.loads(l) for l in f if l.strip()]
                    row_count = len(src_rows)
                    source_symbols = set(r.get("symbol", "") for r in src_rows if "symbol" in r)
                    dates_in_src = sorted(
                        r.get("asof_ts_utc", "") for r in src_rows if r.get("asof_ts_utc")
                    )
                    source_date_range = (
                        (dates_in_src[0], dates_in_src[-1]) if dates_in_src else ("", "")
                    )
                    covers_symbol = bool(source_symbols & outcome_symbols)
                    if source_date_range[0] and outcome_date_range[0]:
                        covers_time = (
                            source_date_range[0] <= outcome_date_range[1]
                            and source_date_range[1] >= outcome_date_range[0]
                        )
                    has_parent_fields = src.get("has_parent_fib_map", "NO")
                except Exception as e:
                    file_available = False
                    src_rows = []

        results.append({
            "source_name": src["name"],
            "source_path": path_str,
            "source_type": src["type"],
            "file_available": file_available,
            "row_count": row_count,
            "covers_outcome_symbols": covers_symbol,
            "covers_outcome_time_range": covers_time,
            "source_date_range_start": source_date_range[0] if source_date_range else "",
            "source_date_range_end": source_date_range[1] if source_date_range else "",
            "has_parent_fib_map": has_parent_fields,
            "has_parent_terminal_state": src.get("has_parent_terminal_state", "NO"),
            "usable_for_parent_context": usable_for_parent_context,
            "note": src["note"],
        })
    return results


# ---------------------------------------------------------------------------
# Event-level audit
# ---------------------------------------------------------------------------

def audit_event(
    event: dict,
    candidate_source_coverage: dict[str, Any],
) -> dict:
    symbol = event.get("symbol", "UNKNOWN")
    asof_ts = event.get("asof_ts_utc", "")
    breath_phase = event.get("market_breath_phase", "UNKNOWN")
    breath_state = event.get("market_breath_state", "UNKNOWN")

    # From previous parent-terminal runner: parent state proxy
    _phase_to_parent = {
        "EXHALE_EXPANSION": "NOT_TERMINAL",
        "INHALE_ACCUMULATION": "NOT_TERMINAL",
        "OVERBREATH_EXTENSION": "TERMINAL_CANDIDATE",
        "HOLD_COMPRESSION": "TERMINAL_CANDIDATE",
        "COLLAPSE_RESET": "TERMINAL_CONFIRMED",
        "NEUTRAL_TRANSITION": "PARENT_CONTEXT_UNKNOWN",
    }
    synthetic_parent_state = _phase_to_parent.get(breath_phase, "PARENT_CONTEXT_UNKNOWN")

    is_unknown = synthetic_parent_state == "PARENT_CONTEXT_UNKNOWN"
    is_synthetic_proxy = (
        synthetic_parent_state != "PARENT_CONTEXT_UNKNOWN"
    )

    primary_reason, detail = classify_unknown_reason(
        breath_phase, breath_state, symbol, asof_ts, candidate_source_coverage
    )

    # Secondary classification
    secondary_reason = None
    if is_unknown and breath_phase == "NEUTRAL_TRANSITION":
        secondary_reason = REASON_CONTEXT_TRULY_UNKNOWN
    elif is_synthetic_proxy:
        primary_reason = REASON_SYNTHETIC_PROXY_USED
        secondary_reason = REASON_SOURCE_MISSING
        detail = (
            f"Synthetic proxy (breath_phase={breath_phase}) used as fallback. "
            "Not validated parent fib map analysis. Cannot claim coverage."
        )

    month = asof_ts[:7] if len(asof_ts) >= 7 else "UNKNOWN"

    return {
        "event_id": f"{symbol}_{asof_ts}",
        "symbol": symbol,
        "month": month,
        "asof_ts_utc": asof_ts,
        "market_breath_phase": breath_phase,
        "market_breath_state": breath_state,
        "synthetic_parent_state": synthetic_parent_state,
        "is_parent_context_unknown": is_unknown,
        "is_synthetic_proxy": is_synthetic_proxy,
        "primary_failure_reason": primary_reason,
        "secondary_failure_reason": secondary_reason,
        "failure_detail": detail,
        "coverage_is_valid": False,  # no valid parent context from pre-computed artifacts
        "coverage_source": None,
        "would_require_db_query": True,
        "db_table_required": "canonical_fib_zone_map_v1",
        "db_join_condition": (
            f"symbol='{symbol}' AND interval_code='4h' "
            f"AND asof_ts_utc <= '{asof_ts}' ORDER BY asof_ts_utc DESC LIMIT 1"
        ),
    }


# ---------------------------------------------------------------------------
# Aggregate helpers
# ---------------------------------------------------------------------------

def _pct(n: int, total: int) -> float:
    return round(n / total * 100, 1) if total else 0.0


def compute_symbol_coverage(audit_rows: list[dict]) -> list[dict]:
    sym_groups: dict[str, list[dict]] = defaultdict(list)
    for r in audit_rows:
        sym_groups[r["symbol"]].append(r)

    result = []
    for symbol, rows in sorted(sym_groups.items()):
        n = len(rows)
        n_unknown = sum(1 for r in rows if r["is_parent_context_unknown"])
        n_synthetic = sum(1 for r in rows if r["is_synthetic_proxy"])
        n_valid = sum(1 for r in rows if r["coverage_is_valid"])
        phases = Counter(r["market_breath_phase"] for r in rows)
        result.append({
            "symbol": symbol,
            "n_events": n,
            "n_parent_unknown": n_unknown,
            "n_synthetic_proxy": n_synthetic,
            "n_valid_coverage": n_valid,
            "pct_unknown": _pct(n_unknown, n),
            "pct_synthetic_proxy": _pct(n_synthetic, n),
            "dominant_phase": phases.most_common(1)[0][0] if phases else "?",
        })
    return result


def compute_month_coverage(audit_rows: list[dict]) -> list[dict]:
    month_groups: dict[str, list[dict]] = defaultdict(list)
    for r in audit_rows:
        month_groups[r["month"]].append(r)

    result = []
    for month, rows in sorted(month_groups.items()):
        n = len(rows)
        n_unknown = sum(1 for r in rows if r["is_parent_context_unknown"])
        n_valid = sum(1 for r in rows if r["coverage_is_valid"])
        result.append({
            "month": month,
            "n_events": n,
            "n_parent_unknown": n_unknown,
            "n_valid_coverage": n_valid,
            "pct_unknown": _pct(n_unknown, n),
        })
    return result


def compute_failure_reason_breakdown(audit_rows: list[dict]) -> list[dict]:
    reason_groups: dict[str, int] = Counter(r["primary_failure_reason"] for r in audit_rows)
    total = len(audit_rows)
    result = []
    for reason, count in reason_groups.most_common():
        result.append({
            "primary_failure_reason": reason,
            "count": count,
            "pct": _pct(count, total),
        })
    return result


def compute_phase_coverage(audit_rows: list[dict]) -> list[dict]:
    phase_groups: dict[str, list[dict]] = defaultdict(list)
    for r in audit_rows:
        phase_groups[r["market_breath_phase"]].append(r)

    result = []
    for phase, rows in sorted(phase_groups.items()):
        n = len(rows)
        n_unknown = sum(1 for r in rows if r["is_parent_context_unknown"])
        n_synthetic = sum(1 for r in rows if r["is_synthetic_proxy"])
        n_valid = sum(1 for r in rows if r["coverage_is_valid"])
        reasons = Counter(r["primary_failure_reason"] for r in rows)
        result.append({
            "market_breath_phase": phase,
            "n_events": n,
            "n_parent_unknown": n_unknown,
            "n_synthetic_proxy": n_synthetic,
            "n_valid_coverage": n_valid,
            "pct_unknown": _pct(n_unknown, n),
            "primary_failure_reason": reasons.most_common(1)[0][0] if reasons else "?",
        })
    return result


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_outputs(
    output_dir: Path,
    audit_rows: list[dict],
    source_inspection: list[dict],
    symbol_coverage: list[dict],
    month_coverage: list[dict],
    failure_breakdown: list[dict],
    phase_coverage: list[dict],
    summary: dict,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def _write_csv(p: Path, rows: list[dict]) -> None:
        if not rows:
            p.write_text("")
            return
        fields = list(rows[0].keys())
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    p = output_dir / "parent_context_coverage_audit_v1.csv"
    _write_csv(p, audit_rows)
    written["coverage_audit"] = p

    p = output_dir / "candidate_sources_v1.csv"
    _write_csv(p, source_inspection)
    written["candidate_sources"] = p

    p = output_dir / "symbol_coverage_v1.csv"
    _write_csv(p, symbol_coverage)
    written["symbol_coverage"] = p

    p = output_dir / "month_coverage_v1.csv"
    _write_csv(p, month_coverage)
    written["month_coverage"] = p

    p = output_dir / "failure_reason_breakdown_v1.csv"
    _write_csv(p, failure_breakdown)
    written["failure_reason_breakdown"] = p

    p = output_dir / "phase_coverage_v1.csv"
    _write_csv(p, phase_coverage)
    written["phase_coverage"] = p

    p = output_dir / "parent_context_coverage_summary_v1.json"
    with open(p, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    written["summary"] = p

    manifest = {
        "runner": RUNNER_NAME,
        "version": VERSION,
        "output_paths": {k: str(v) for k, v in written.items()},
        "safety_markers": summary["safety_markers"],
    }
    mp = output_dir / "manifest_v1.json"
    mp.write_text(json.dumps(manifest, indent=2))
    written["manifest"] = mp

    return written


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(
    outcome_rows_path: Path = OUTCOME_ROWS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_events: int = MAX_EVENTS,
    symbols: Optional[list[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    dry_run: bool = False,
) -> int:
    print(f"STARTED {RUNNER_NAME} {VERSION}", flush=True)
    print(f"  outcome_rows={outcome_rows_path}", flush=True)
    print(f"  output_dir={output_dir}", flush=True)
    if dry_run:
        print("  dry_run=True — no file writes", flush=True)

    # Phase 1: Load events
    print("\nPhase 1: Loading events...", flush=True)
    events = load_events(outcome_rows_path, max_events, symbols, date_from, date_to)
    n_events = len(events)
    print(f"  Loaded {n_events} unique events", flush=True)
    if n_events == 0:
        print("FAILED: no events found")
        return 1

    outcome_symbols = set(r["symbol"] for r in events)
    dates = sorted(r["asof_ts_utc"] for r in events)
    outcome_date_range = (dates[0], dates[-1])
    print(f"  Symbol count: {len(outcome_symbols)}", flush=True)
    print(f"  Date range: {outcome_date_range[0]} to {outcome_date_range[1]}", flush=True)

    # Phase 2: Inspect candidate sources
    print("\nPhase 2: Inspecting candidate parent context sources...", flush=True)
    source_inspection = inspect_candidate_sources(outcome_symbols, outcome_date_range)
    for src in source_inspection:
        avail = "FILE_OK" if src["file_available"] else ("DB_ONLY" if src["source_path"] == "DB_ONLY" else "MISSING")
        print(
            f"  {src['source_name']:45s}: {avail:10s}  "
            f"rows={src['row_count']:>5}  "
            f"parent_map={src['has_parent_fib_map']:10s}  "
            f"usable={src['usable_for_parent_context']}",
            flush=True,
        )

    # Phase 3: Audit each event
    print("\nPhase 3: Classifying parent context failure reasons...", flush=True)
    # All pre-computed sources lack parent fib map data
    candidate_coverage = {"file_available": False, "covers_symbol": False, "covers_time": False}
    audit_rows = [audit_event(ev, candidate_coverage) for ev in events]

    # Counts
    n_unknown = sum(1 for r in audit_rows if r["is_parent_context_unknown"])
    n_synthetic = sum(1 for r in audit_rows if r["is_synthetic_proxy"])
    n_valid = sum(1 for r in audit_rows if r["coverage_is_valid"])
    reason_counts = Counter(r["primary_failure_reason"] for r in audit_rows)

    print(f"  n_parent_context_unknown: {n_unknown} ({_pct(n_unknown, n_events)}%)", flush=True)
    print(f"  n_synthetic_proxy_used:   {n_synthetic} ({_pct(n_synthetic, n_events)}%)", flush=True)
    print(f"  n_valid_coverage:         {n_valid}", flush=True)
    print(f"  Failure reason distribution:", flush=True)
    for reason, count in reason_counts.most_common():
        print(f"    {reason:35s}: {count} ({_pct(count, n_events)}%)", flush=True)

    # Phase 4: Aggregates
    print("\nPhase 4: Computing coverage aggregates...", flush=True)
    symbol_coverage = compute_symbol_coverage(audit_rows)
    month_coverage = compute_month_coverage(audit_rows)
    failure_breakdown = compute_failure_reason_breakdown(audit_rows)
    phase_coverage = compute_phase_coverage(audit_rows)

    # Phase 5: Coverage improvement assessment
    print("\nPhase 5: Coverage improvement assessment...", flush=True)
    can_increase = False
    db_source_available = any(
        s["has_parent_fib_map"] in ("YES", "DERIVABLE") for s in source_inspection
    )
    print(
        f"  Can increase coverage from pre-computed file artifacts: {can_increase}",
        flush=True,
    )
    print(
        f"  DB source available (canonical_fib_zone_map_v1): {db_source_available}",
        flush=True,
    )
    if db_source_available:
        print(
            "  ACTION REQUIRED: Query canonical_fib_zone_map_v1 from live DB "
            "with strict backward as-of join to increase coverage.",
            flush=True,
        )
    print(
        "  Fail-closed behavior retained for all PARENT_CONTEXT_UNKNOWN events.",
        flush=True,
    )

    # Build summary
    summary = {
        "runner": RUNNER_NAME,
        "version": VERSION,
        "n_events": n_events,
        "n_unique_symbols": len(outcome_symbols),
        "outcome_date_range": {"start": outcome_date_range[0], "end": outcome_date_range[1]},
        "n_parent_context_unknown": n_unknown,
        "n_synthetic_proxy": n_synthetic,
        "n_valid_coverage": n_valid,
        "pct_unknown": _pct(n_unknown, n_events),
        "pct_synthetic_proxy": _pct(n_synthetic, n_events),
        "failure_reason_distribution": dict(reason_counts.most_common()),
        "phase_coverage": phase_coverage,
        "coverage_improvement": {
            "can_increase_from_file_artifacts": can_increase,
            "db_source_exists": db_source_available,
            "db_table": "canonical_fib_zone_map_v1",
            "db_join": "symbol, venue, interval_code='4h', asof_ts_utc <= event_ts ORDER BY asof_ts_utc DESC LIMIT 1",
            "max_context_age_minutes": 480,
            "requires_strict_backward_asof": True,
            "do_not_synthesize_parent_state": True,
            "recommendation": (
                "Query canonical_fib_zone_map_v1 from live DB for the 2026-03-14 to 2026-05-12 "
                "period. Use strict backward as-of join. Never synthesize parent terminal state. "
                "Preserve source_refs and context age. "
                "If DB query increases valid coverage, rerun parent-terminal residual exit runner "
                "and compare before/after results."
            ),
        },
        "candidate_sources": source_inspection,
        "limitation": (
            "The outcome_rows_v1 dataset contains only market_breath signal fields. "
            "No parent fib map source exists as a pre-computed file artifact in data/research/ "
            "for the 2026-03-14 to 2026-05-12 period. "
            f"The dominant reason ({_pct(n_unknown, n_events)}%) for PARENT_CONTEXT_UNKNOWN is "
            "SOURCE_MISSING combined with CONTEXT_TRULY_UNKNOWN (NEUTRAL_TRANSITION phase). "
            "The synthetic proxy (market_breath_phase → parent state) used in the parent-terminal "
            "runner is not validated parent fib map analysis. Do not claim parent terminal benefit "
            "beyond the synthetic proxy coverage. "
            "Fail-closed behavior is retained."
        ),
        "notes": {
            "neutral_transition_root_cause": (
                "87.7% of events have NEUTRAL_TRANSITION breath phase. "
                "This is a genuine signal absence — the breath model assigns NEUTRAL_TRANSITION "
                "when no clear directional state can be computed from available market data. "
                "It is not a join miss or a data pipeline error."
            ),
            "db_query_not_in_scope": (
                "DB query to canonical_fib_zone_map_v1 is outside this runner's scope "
                "(requires live DB connection; research-only). "
                "A separate runner (e.g. run_parent_context_db_join_v1.py) should implement "
                "the DB query with strict backward as-of join if coverage increase is needed."
            ),
            "synthetic_proxy_limitation": (
                "Synthetic parent states from market_breath_phase are research approximations only. "
                "COLLAPSE_RESET → TERMINAL_CONFIRMED proxy: represents 89/2460 (3.6%) of events. "
                "These are documented as SYNTHETIC_PROXY_USED, not SOURCE_MISSING, "
                "because a breath signal exists — but it is not actual parent fib map analysis."
            ),
        },
        "safety_markers": {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
        },
    }

    if dry_run:
        print("\nDRY RUN — skipping file writes", flush=True)
        print(f"FINISHED {RUNNER_NAME} (dry run)")
        return 0

    # Phase 6: Write outputs
    print("\nPhase 6: Writing outputs...", flush=True)
    written = write_outputs(
        output_dir, audit_rows, source_inspection, symbol_coverage,
        month_coverage, failure_breakdown, phase_coverage, summary,
    )
    for k, p in written.items():
        print(f"  {k}: {p}", flush=True)

    print(f"\nFINISHED {RUNNER_NAME}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"{RUNNER_NAME} — audit parent-horizon context coverage"
    )
    parser.add_argument("--outcome-rows", default=str(OUTCOME_ROWS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-events", type=int, default=MAX_EVENTS)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(
        outcome_rows_path=Path(args.outcome_rows),
        output_dir=Path(args.output_dir),
        max_events=args.max_events,
        symbols=args.symbols,
        date_from=args.date_from,
        date_to=args.date_to,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
