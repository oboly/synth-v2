from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


REPORT_NAME = "breath_phase_unknown_diagnostic_v1"
REPORT_VERSION = "1.0"

DEFAULT_EVENT_LEVEL_ROWS = Path(
    "data/research/event_level_symbol_reaction_profile_by_context_v1_event_range"
    "/event_level_symbol_reaction_profile_by_context_rows_v1.csv"
)
DEFAULT_RECOMPUTE_ROWS = Path(
    "data/research/historical_market_breath_source_recompute_v1_event_range"
    "/historical_market_breath_source_recomputed_rows_v1.csv"
)
DEFAULT_CONTEXT_ROWS = Path(
    "data/research/historical_breath_regime_context_builder_v1_event_range"
    "/historical_breath_regime_context_rows_v1.csv"
)
DEFAULT_OUTPUT_DIR = Path("data/research/breath_phase_unknown_diagnostic_v1")

ROWS_CSV = "breath_phase_unknown_diagnostic_rows_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

MAX_STALENESS = timedelta(days=7)

# Unknown-reason labels (mutually exclusive, priority order)
RAW_PHASE_UNKNOWN = "RAW_PHASE_UNKNOWN"
RAW_PHASE_NEUTRAL_TRANSITION = "RAW_PHASE_NEUTRAL_TRANSITION"
RAW_STATE_UNKNOWN = "RAW_STATE_UNKNOWN"
SCORE_BELOW_LIVE_THRESHOLD = "SCORE_BELOW_LIVE_THRESHOLD"
LIVE_SEMANTICS_CONSERVATIVE = "LIVE_SEMANTICS_CONSERVATIVE"
SOURCE_ROW_MISSING = "SOURCE_ROW_MISSING"
UNKNOWN_REASON = "UNKNOWN"

SCORE_FIELDS = (
    "compression_score",
    "expansion_score",
    "momentum_score",
    "reversal_pressure_score",
    "relative_strength_score",
    "btc_alignment_score",
    "breadth_alignment_score",
)

SAFETY_MARKERS: dict[str, Any] = {
    "research_only": True,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "executor": "none",
    "db_writes": 0,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose why breath_phase and breath_alignment remain UNKNOWN for most "
            "event-level rows (research-only, read-only, no DB writes)."
        )
    )
    parser.add_argument("--event-level-rows", default=str(DEFAULT_EVENT_LEVEL_ROWS))
    parser.add_argument("--recompute-rows", default=str(DEFAULT_RECOMPUTE_ROWS))
    parser.add_argument("--context-rows", default=None)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def is_unknown(value: Any) -> bool:
    return str(value or "").strip().upper() in {"", "UNKNOWN"}


def parse_ts(value: Any) -> datetime | None:
    if value in ("", None):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def fmt_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def average_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    converted: list[dict[str, Any]] = []
    for row in rows:
        conv: dict[str, Any] = {}
        for key, value in row.items():
            conv[key] = (
                json.dumps(value, sort_keys=True, ensure_ascii=True)
                if isinstance(value, (list, dict))
                else value
            )
        converted.append(conv)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(converted[0].keys()))
        writer.writeheader()
        writer.writerows(converted)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def load_event_level_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Event-level rows not found: {path}")
    raw = read_csv_rows(path)
    out: list[dict[str, Any]] = []
    for row in raw:
        symbol = str(row.get("symbol") or "").strip().upper()
        event_ts = parse_ts(row.get("event_ts_utc"))
        if not symbol or event_ts is None:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["_event_ts_dt"] = event_ts
        out.append(item)
    return out


def load_recompute_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = read_csv_rows(path)
    out: list[dict[str, Any]] = []
    for row in raw:
        symbol = str(row.get("symbol") or "").strip().upper()
        asof_ts = parse_ts(row.get("asof_ts_utc"))
        if not symbol or asof_ts is None:
            continue
        item = dict(row)
        item["symbol"] = symbol
        item["_asof_ts_dt"] = asof_ts
        out.append(item)
    return out


def build_recompute_by_sym_ts(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Key: (symbol, asof_ts_utc string) for direct join on the embedded timestamp."""
    return {
        (row["symbol"], str(row.get("asof_ts_utc") or "")): row
        for row in rows
        if str(row.get("asof_ts_utc") or "")
    }


def build_recompute_lookup(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Sorted per-symbol list for nearest-at-or-before fallback."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: (r["symbol"], r["_asof_ts_dt"])):
        grouped[row["symbol"]].append(row)
    return dict(grouped)


def nearest_recompute_at_or_before(
    lookup: dict[str, list[dict[str, Any]]],
    *,
    symbol: str,
    event_ts: datetime,
) -> dict[str, Any] | None:
    matched: dict[str, Any] | None = None
    for row in lookup.get(symbol, []):
        if row["_asof_ts_dt"] > event_ts:
            break
        matched = row
    if matched is None:
        return None
    if event_ts - matched["_asof_ts_dt"] > MAX_STALENESS:
        return None
    return matched


def classify_unknown_reason(
    event_row: dict[str, Any],
    recomp_row: dict[str, Any] | None,
) -> str:
    """Assign a single mutually-exclusive reason why breath_phase is UNKNOWN.

    Priority:
      1. No recompute row within staleness → SOURCE_ROW_MISSING
      2. raw_phase is UNKNOWN → RAW_PHASE_UNKNOWN
      3. raw_phase is NEUTRAL_TRANSITION → RAW_PHASE_NEUTRAL_TRANSITION
      4. raw_state is UNKNOWN → RAW_STATE_UNKNOWN
      5. raw_phase is a known phase but canonical mapping yielded UNKNOWN
         → LIVE_SEMANTICS_CONSERVATIVE
      6. Fallback → UNKNOWN_REASON
    """
    if recomp_row is None:
        return SOURCE_ROW_MISSING

    raw_phase = str(recomp_row.get("market_breath_phase_raw") or "").strip().upper()
    raw_state = str(recomp_row.get("market_breath_state_raw") or "").strip().upper()

    if raw_phase in ("", "UNKNOWN"):
        return RAW_PHASE_UNKNOWN

    if raw_phase == "NEUTRAL_TRANSITION":
        return RAW_PHASE_NEUTRAL_TRANSITION

    if raw_state in ("", "UNKNOWN"):
        return RAW_STATE_UNKNOWN

    # Known raw_phase and known raw_state but canonical breath_phase is UNKNOWN →
    # the live mapper is being conservative about confirming the label.
    if not is_unknown(raw_phase) and not is_unknown(raw_state):
        return LIVE_SEMANTICS_CONSERVATIVE

    return UNKNOWN_REASON


def build_diagnostic_rows(
    *,
    event_rows: list[dict[str, Any]],
    recomp_by_sym_ts: dict[tuple[str, str], dict[str, Any]],
    recomp_lookup: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    for row in sorted(event_rows, key=lambda r: (r["symbol"], r["_event_ts_dt"])):
        symbol = row["symbol"]
        event_ts = row["_event_ts_dt"]
        breath_phase = str(row.get("breath_phase") or "UNKNOWN").upper()
        breath_alignment = str(row.get("breath_alignment") or "UNKNOWN").upper()
        breath_unknown = is_unknown(breath_phase) or is_unknown(breath_alignment)

        # Prefer direct timestamp join, fall back to nearest lookup
        recomp_ts_str = str(row.get("recompute_asof_ts_utc") or "").strip()
        recomp_row = recomp_by_sym_ts.get((symbol, recomp_ts_str)) if recomp_ts_str else None
        if recomp_row is None:
            recomp_row = nearest_recompute_at_or_before(
                recomp_lookup, symbol=symbol, event_ts=event_ts
            )

        raw_phase = str((recomp_row or {}).get("market_breath_phase_raw") or "UNKNOWN").upper()
        raw_state = str((recomp_row or {}).get("market_breath_state_raw") or "UNKNOWN").upper()
        confidence = as_float((recomp_row or {}).get("market_breath_confidence"))

        scores: dict[str, float | None] = {
            field: as_float((recomp_row or {}).get(field)) for field in SCORE_FIELDS
        }

        unknown_reason: str | None = None
        if breath_unknown:
            unknown_reason = classify_unknown_reason(row, recomp_row)

        diag_row: dict[str, Any] = {
            "symbol": symbol,
            "event_ts_utc": fmt_ts(event_ts),
            "breath_phase": breath_phase,
            "breath_alignment": breath_alignment,
            "breath_unknown": breath_unknown,
            "recompute_asof_ts_utc": recomp_ts_str or None,
            "raw_phase": raw_phase,
            "raw_state": raw_state,
            "market_breath_confidence": confidence,
            "unknown_reason": unknown_reason,
            **scores,
            "research_only": True,
        }
        output.append(diag_row)
    return output


def _score_stats(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    vals = [v for v in (as_float(r.get(field)) for r in rows) if v is not None]
    if not vals:
        return {"mean": None, "min": None, "max": None, "count": 0}
    return {
        "mean": round(sum(vals) / len(vals), 4),
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "count": len(vals),
    }


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(rows)
    breath_unknown_rows = [r for r in rows if r.get("breath_unknown")]
    breath_known_rows = [r for r in rows if not r.get("breath_unknown")]

    raw_phase_dist = dict(Counter(r["raw_phase"] for r in rows))
    raw_state_dist = dict(Counter(r["raw_state"] for r in rows))
    unknown_reason_dist = dict(
        Counter(r["unknown_reason"] for r in breath_unknown_rows if r.get("unknown_reason"))
    )

    # Score distributions for unknown-breath rows
    score_stats: dict[str, Any] = {
        field: _score_stats(breath_unknown_rows, field) for field in SCORE_FIELDS
    }

    # Per-symbol summary
    sym_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sym_rows[row["symbol"]].append(row)

    by_symbol: dict[str, dict[str, Any]] = {}
    for sym, sym_list in sorted(sym_rows.items()):
        unk_list = [r for r in sym_list if r.get("breath_unknown")]
        dominant = (
            Counter(r["unknown_reason"] for r in unk_list if r.get("unknown_reason")).most_common(1)
        )
        by_symbol[sym] = {
            "event_count": len(sym_list),
            "breath_known_count": sum(1 for r in sym_list if not r.get("breath_unknown")),
            "breath_unknown_count": len(unk_list),
            "dominant_unknown_reason": dominant[0][0] if dominant else None,
            "raw_phase_distribution": dict(Counter(r["raw_phase"] for r in sym_list)),
            "raw_state_distribution": dict(Counter(r["raw_state"] for r in sym_list)),
        }

    dominant_unknown = (
        max(unknown_reason_dist, key=lambda k: unknown_reason_dist[k])
        if unknown_reason_dist
        else None
    )

    # Expansion justification verdict
    expansion_verdict: str
    if dominant_unknown == RAW_PHASE_NEUTRAL_TRANSITION:
        expansion_verdict = (
            "SHOULD_REMAIN_UNKNOWN — raw signal is NEUTRAL_TRANSITION, "
            "which is genuinely ambiguous; forcing EXPANSION would be inaccurate"
        )
    elif dominant_unknown == RAW_PHASE_UNKNOWN:
        expansion_verdict = (
            "SHOULD_REMAIN_UNKNOWN — raw signal itself is UNKNOWN; no label is justifiable"
        )
    elif dominant_unknown == LIVE_SEMANTICS_CONSERVATIVE:
        expansion_verdict = (
            "REVIEW_LIVE_THRESHOLD — raw phase is known but canonical mapper is conservative; "
            "consider whether threshold can be relaxed for research context"
        )
    elif dominant_unknown == SOURCE_ROW_MISSING:
        expansion_verdict = (
            "EXTEND_RECOMPUTE_RANGE — no source row available; "
            "rerun recompute with wider date range"
        )
    else:
        expansion_verdict = "INVESTIGATE — mixed or unclassified reasons"

    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "total_events": total,
        "breath_known_events": len(breath_known_rows),
        "breath_unknown_events": len(breath_unknown_rows),
        "raw_phase_distribution": raw_phase_dist,
        "raw_state_distribution": raw_state_dist,
        "unknown_reason_distribution": unknown_reason_dist,
        "dominant_unknown_reason": dominant_unknown,
        "expansion_verdict": expansion_verdict,
        "score_stats_for_unknown_breath": score_stats,
        "by_symbol": by_symbol,
        "event_level_rows": str(args.event_level_rows),
        "recompute_rows": str(args.recompute_rows),
        "context_rows": str(args.context_rows) if args.context_rows else None,
        "output_dir": str(output_dir),
        "research_only": True,
        "safety_markers": dict(SAFETY_MARKERS),
    }


def print_summary(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(f"total_events={manifest['total_events']}")
    print(f"breath_known_events={manifest['breath_known_events']}")
    print(f"breath_unknown_events={manifest['breath_unknown_events']}")

    raw_phase = manifest["raw_phase_distribution"]
    print(
        "raw_phase_distribution "
        + " ; ".join(f"{k}:{raw_phase[k]}" for k in sorted(raw_phase, key=lambda k: -raw_phase[k]))
    )
    raw_state = manifest["raw_state_distribution"]
    print(
        "raw_state_distribution "
        + " ; ".join(f"{k}:{raw_state[k]}" for k in sorted(raw_state, key=lambda k: -raw_state[k]))
    )

    unk_reasons = manifest["unknown_reason_distribution"]
    if unk_reasons:
        print(
            "unknown_reason_distribution "
            + " ; ".join(
                f"{k}:{unk_reasons[k]}"
                for k in sorted(unk_reasons, key=lambda k: -unk_reasons[k])
            )
        )
    print(f"dominant_unknown_reason={manifest['dominant_unknown_reason']}")
    print(f"expansion_verdict={manifest['expansion_verdict']}")

    print("per_symbol:")
    for sym, data in sorted(manifest["by_symbol"].items()):
        print(
            f"  {sym}: total={data['event_count']} known={data['breath_known_count']}"
            f" unknown={data['breath_unknown_count']}"
            f" dominant_reason={data['dominant_unknown_reason']}"
        )

    print(
        "safety "
        + " ".join(f"{key}={value}" for key, value in SAFETY_MARKERS.items())
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    event_level_rows_path = Path(args.event_level_rows)
    recompute_rows_path = Path(args.recompute_rows)
    output_dir = Path(args.output_dir)

    event_rows = load_event_level_rows(event_level_rows_path)
    recomp_rows = load_recompute_rows(recompute_rows_path)

    recomp_by_sym_ts = build_recompute_by_sym_ts(recomp_rows)
    recomp_lookup = build_recompute_lookup(recomp_rows)

    diag_rows = build_diagnostic_rows(
        event_rows=event_rows,
        recomp_by_sym_ts=recomp_by_sym_ts,
        recomp_lookup=recomp_lookup,
    )
    manifest = build_manifest(args=args, output_dir=output_dir, rows=diag_rows)

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / ROWS_CSV, diag_rows)
        write_json(output_dir / MANIFEST_JSON, manifest)

    if args.output == "json":
        print(
            json.dumps(
                {"rows": diag_rows, "manifest": manifest},
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
        )
    else:
        print_summary(diag_rows, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
