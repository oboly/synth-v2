from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_NAME = "aplus_table1_table2_normalized_v1"
PARSER_VERSION = "0.1"

EXPECTED_TOKENS = [
    "BTC", "ETH", "SOL", "ADA", "DEEP", "FIL", "HBAR", "HOT", "NEAR", "PEPE",
    "POL", "QNT", "SUI", "VET", "WAL", "XLM", "AAVE", "CC", "CRV", "FLOKI",
    "HYPE", "LDO", "LTC", "ONDO", "RLC", "WLD", "XRP", "ALGO", "DOT", "FET",
    "HNT", "ICP", "INJ", "IOST", "MOG", "NOT", "RED", "RENDER", "XPL", "TAO",
    "LINK",
]
EXPECTED_TOKEN_SET = set(EXPECTED_TOKENS)
EXPECTED_TOKEN_COUNT = len(EXPECTED_TOKENS)

TABLE1_HEADER = [
    "TOKEN", "PHASE", "COHERENCE", "FIELD", "GEOMETRY",
    "STRUCTURAL_ROLE", "EXPANSION_QUALITY", "ANCHOR_STRENGTH",
    "STRATEGIC_BIAS", "NOTES",
]
TABLE2_HEADER = [
    "TOKEN", "HARMONIC_PHASE", "PHASE_STATE", "OFFSET_BAND",
    "DRIFT_DIRECTION", "QUALITY", "EXTENSION_RISK", "NOTES",
]

TABLE1_ALLOWED = {
    "phase": {"early", "forming", "confirmed", "late", "exhaustion", "reset", "neutral"},
    "coherence": {"high", "moderate", "low"},
    "field": {"expansion", "compression", "transition", "neutral"},
    "geometry": {"clean", "mixed", "distorted", "unknown"},
    "structural_role": {"leader", "confirmer", "laggard", "speculative", "defensive", "unknown"},
    "expansion_quality": {"strong", "moderate", "weak", "none"},
    "anchor_strength": {"strong", "moderate", "weak", "none"},
    "strategic_bias": {"accumulation", "continuation", "caution", "avoid", "neutral"},
}

TABLE2_ALLOWED = {
    "harmonic_phase": {
        "pre_0618", "forming_0618", "confirmed_0618",
        "forming_0786", "confirmed_0786",
        "forming_1000", "confirmed_1000",
        "extension_1272", "late_extension", "reset", "unclear",
    },
    "phase_state": {"early", "forming", "confirmed", "late", "exhausted", "unclear"},
    "offset_band": {
        "-10.5", "-9", "-8", "-7", "-5", "-3", "0",
        "+3", "+5", "+7", "+9", "+10.5", "unknown",
    },
    "drift_direction": {"converging", "forward_drift", "backward_drift", "flat", "unstable", "unknown"},
    "quality": {"clean", "mixed", "dirty", "unknown"},
    "extension_risk": {"low", "moderate", "high", "unknown"},
}

TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")
SEP_CELL_RE = re.compile(r"^[\s\-:]+$")
TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_+\-]*$")


def extract_timestamp(text: str) -> str:
    match = TS_RE.search(text)
    if not match:
        raise ValueError("Could not find prediction_ts_utc (YYYY-MM-DDTHH:MM:SSZ) in raw file")
    raw = match.group(1)
    dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def slug_from_ts(prediction_ts_utc: str) -> str:
    dt = datetime.strptime(prediction_ts_utc.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    return dt.strftime("%Y%m%d_%H%M")


def parse_ts_to_dt(prediction_ts_utc: str) -> datetime:
    dt = datetime.strptime(prediction_ts_utc.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)


def compute_pair_metadata(t1_ts: str, t2_ts: str) -> dict[str, Any]:
    t1_dt = parse_ts_to_dt(t1_ts)
    t2_dt = parse_ts_to_dt(t2_ts)
    delta_seconds = abs((t1_dt - t2_dt).total_seconds())
    mismatch_minutes = int(round(delta_seconds / 60.0))
    same_snapshot_ts = mismatch_minutes <= 5
    later_dt = max(t1_dt, t2_dt)
    pair_reference_ts_utc = later_dt.isoformat().replace("+00:00", "Z")
    return {
        "table1_prediction_ts_utc": t1_ts,
        "table2_prediction_ts_utc": t2_ts,
        "pair_reference_ts_utc": pair_reference_ts_utc,
        "timestamp_mismatch_minutes": mismatch_minutes,
        "same_snapshot_ts": same_snapshot_ts,
        "timestamp_mismatch_allowed": True,
    }


def clean_notes(text: str) -> str:
    s = text.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    return s


def parse_pipe_row(line: str) -> list[str] | None:
    if "|" not in line:
        return None
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    cells = [cell.strip() for cell in raw.split("|")]
    if cells and all(SEP_CELL_RE.match(c) for c in cells):
        return None
    return cells


def is_header_row(cells: list[str], expected: list[str]) -> bool:
    if len(cells) != len(expected):
        return False
    return [c.strip().lower() for c in cells] == [e.lower() for e in expected]


def parse_table_rows(text: str, expected_header: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    header_seen = False
    for line in text.splitlines():
        cells = parse_pipe_row(line)
        if cells is None:
            continue
        if not header_seen:
            if is_header_row(cells, expected_header):
                header_seen = True
            continue
        if len(cells) != len(expected_header):
            continue
        token_cell = cells[0].strip().upper()
        if not TOKEN_RE.match(token_cell):
            continue
        rows.append(cells)
    if not header_seen:
        raise ValueError(f"Expected header not found: {expected_header}")
    return rows


def normalize_table1_row(cells: list[str], prediction_ts_utc: str, source_path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "prediction_ts_utc": prediction_ts_utc,
        "token": cells[0].strip().upper(),
        "table1_phase": cells[1].strip().lower(),
        "table1_coherence": cells[2].strip().lower(),
        "table1_field": cells[3].strip().lower(),
        "table1_geometry": cells[4].strip().lower(),
        "table1_structural_role": cells[5].strip().lower(),
        "table1_expansion_quality": cells[6].strip().lower(),
        "table1_anchor_strength": cells[7].strip().lower(),
        "table1_strategic_bias": cells[8].strip().lower(),
        "table1_notes": clean_notes(cells[9]),
        "source_table1_path": str(source_path),
        "parser_version": PARSER_VERSION,
    }
    invalid: list[tuple[str, str]] = []
    for key, allowed in TABLE1_ALLOWED.items():
        value = record[f"table1_{key}"]
        if value not in allowed:
            invalid.append((key, value))
    record["validation_status"] = "VALID" if not invalid else "INVALID"
    record["_invalid"] = invalid
    return record


def normalize_table2_row(cells: list[str], prediction_ts_utc: str, source_path: Path) -> dict[str, Any]:
    raw_offset = cells[3].strip()
    offset_band = "unknown" if raw_offset.lower() == "unknown" else raw_offset
    record: dict[str, Any] = {
        "prediction_ts_utc": prediction_ts_utc,
        "token": cells[0].strip().upper(),
        "table2_harmonic_phase": cells[1].strip().lower(),
        "table2_phase_state": cells[2].strip().lower(),
        "table2_offset_band": offset_band,
        "table2_drift_direction": cells[4].strip().lower(),
        "table2_quality": cells[5].strip().lower(),
        "table2_extension_risk": cells[6].strip().lower(),
        "table2_notes": clean_notes(cells[7]),
        "source_table2_path": str(source_path),
        "parser_version": PARSER_VERSION,
    }
    invalid: list[tuple[str, str]] = []
    for key, allowed in TABLE2_ALLOWED.items():
        value = record[f"table2_{key}"]
        if value not in allowed:
            invalid.append((key, value))
    record["validation_status"] = "VALID" if not invalid else "INVALID"
    record["_invalid"] = invalid
    return record


def parse_table1_space_rows(text: str) -> tuple[list[list[str]], bool]:
    """Parse space-separated Table 1 rows.

    Header line: TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE
                 EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES
    Data lines:  TOKEN field1 ... field8 [notes words...]
    """
    rows: list[list[str]] = []
    header_seen = False
    header_upper = [h.upper() for h in TABLE1_HEADER]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if not header_seen:
            if len(parts) >= len(TABLE1_HEADER) and [p.upper() for p in parts[:len(TABLE1_HEADER)]] == header_upper:
                header_seen = True
            continue
        if len(parts) < 9:
            continue
        # Check the raw token (before uppercasing) so mixed-case prose lines
        # like "This snapshot reflects..." are rejected — they fail [A-Z][A-Z0-9_+\-]*
        # because of lowercase letters.
        if not TOKEN_RE.match(parts[0]):
            continue
        token = parts[0].upper()
        notes = " ".join(parts[9:]) if len(parts) > 9 else ""
        # Reconstruct as a cell list matching TABLE1_HEADER column order.
        cells = [token] + [p.lower() for p in parts[1:9]] + [notes]
        rows.append(cells)
    return rows, header_seen


def parse_table1(path: Path) -> tuple[str, list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8")
    prediction_ts_utc = extract_timestamp(text)

    # Try pipe-separated first; fall back to space-separated.
    try:
        cell_rows = parse_table_rows(text, TABLE1_HEADER)
    except ValueError:
        space_rows, space_header = parse_table1_space_rows(text)
        if not space_header or not space_rows:
            raise ValueError(
                f"No recognisable Table 1 header found in {path} "
                "(tried pipe-separated and space-separated formats)"
            )
        cell_rows = space_rows

    rows = [normalize_table1_row(c, prediction_ts_utc, path) for c in cell_rows]
    return prediction_ts_utc, rows


def parse_table2(path: Path) -> tuple[str, list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8")
    prediction_ts_utc = extract_timestamp(text)
    cell_rows = parse_table_rows(text, TABLE2_HEADER)
    rows = [normalize_table2_row(c, prediction_ts_utc, path) for c in cell_rows]
    return prediction_ts_utc, rows


def build_joined(
    t1_rows: list[dict[str, Any]],
    t2_rows: list[dict[str, Any]],
    t1_path: Path,
    t2_path: Path,
    pair_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    t1_by = {row["token"]: row for row in t1_rows}
    t2_by = {row["token"]: row for row in t2_rows}
    tokens = sorted(set(t1_by) & set(t2_by))
    joined: list[dict[str, Any]] = []
    for token in tokens:
        t1 = t1_by[token]
        t2 = t2_by[token]
        rec: dict[str, Any] = {
            "prediction_ts_utc": pair_meta["pair_reference_ts_utc"],
            "token": token,
            "table1_prediction_ts_utc": pair_meta["table1_prediction_ts_utc"],
            "table2_prediction_ts_utc": pair_meta["table2_prediction_ts_utc"],
            "pair_reference_ts_utc": pair_meta["pair_reference_ts_utc"],
            "timestamp_mismatch_minutes": pair_meta["timestamp_mismatch_minutes"],
            "same_snapshot_ts": pair_meta["same_snapshot_ts"],
            "timestamp_mismatch_allowed": pair_meta["timestamp_mismatch_allowed"],
        }
        for k, v in t1.items():
            if k.startswith("table1_"):
                rec[k] = v
        for k, v in t2.items():
            if k.startswith("table2_"):
                rec[k] = v
        rec["source_table1_path"] = str(t1_path)
        rec["source_table2_path"] = str(t2_path)
        rec["parser_version"] = PARSER_VERSION
        both_valid = t1["validation_status"] == "VALID" and t2["validation_status"] == "VALID"
        rec["validation_status"] = "VALID" if both_valid else "INVALID"
        joined.append(rec)
    return joined


def token_audit(t1_tokens: list[str], t2_tokens: list[str]) -> dict[str, Any]:
    t1_set = set(t1_tokens)
    t2_set = set(t2_tokens)
    return {
        "table1_count": len(t1_tokens),
        "table2_count": len(t2_tokens),
        "table1_unique": len(t1_set),
        "table2_unique": len(t2_set),
        "duplicates_table1": sorted(k for k, v in Counter(t1_tokens).items() if v > 1),
        "duplicates_table2": sorted(k for k, v in Counter(t2_tokens).items() if v > 1),
        "missing_table1_vs_expected": sorted(EXPECTED_TOKEN_SET - t1_set),
        "missing_table2_vs_expected": sorted(EXPECTED_TOKEN_SET - t2_set),
        "extra_table1_vs_expected": sorted(t1_set - EXPECTED_TOKEN_SET),
        "extra_table2_vs_expected": sorted(t2_set - EXPECTED_TOKEN_SET),
        "tokens_in_both": sorted(t1_set & t2_set),
        "tokens_only_in_table1": sorted(t1_set - t2_set),
        "tokens_only_in_table2": sorted(t2_set - t1_set),
    }


def collect_invalid(rows: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        for key, value in row.get("_invalid", []):
            out.append({"token": row["token"], "field": f"{prefix}_{key}", "value": value})
    return out


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            fh.write(json.dumps(clean, sort_keys=True, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def render_table_summary(summary: dict[str, Any]) -> str:
    audit = summary["token_audit"]

    def join_or_none(values: list[str]) -> str:
        return ",".join(values) if values else "none"

    lines = [
        f"report={REPORT_NAME} version={PARSER_VERSION}",
        "scope=research-only market-only account-agnostic",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none",
        f"table1_prediction_ts_utc={summary['table1_prediction_ts_utc']}",
        f"table2_prediction_ts_utc={summary['table2_prediction_ts_utc']}",
        f"pair_reference_ts_utc={summary['pair_reference_ts_utc']}",
        f"timestamp_mismatch_minutes={summary['timestamp_mismatch_minutes']}",
        f"same_snapshot_ts={summary['same_snapshot_ts']}",
        f"timestamp_mismatch_allowed={summary['timestamp_mismatch_allowed']}",
        f"prediction_ts_utc_pair_ref={summary['prediction_ts_utc']}",
        f"table1_ts_override_applied={summary['table1_ts_override_applied']}",
        f"table2_ts_override_applied={summary['table2_ts_override_applied']}",
        f"table1_ts_internal={summary['table1_ts_internal']}",
        f"table2_ts_internal={summary['table2_ts_internal']}",
        f"table1_path={summary['source_table1_path']}",
        f"table2_path={summary['source_table2_path']}",
        f"table1_rows={summary['table1_rows']}",
        f"table2_rows={summary['table2_rows']}",
        f"joined_rows={summary['joined_rows']}",
        f"expected_tokens={summary['expected_token_count']}",
        f"missing_table1={join_or_none(audit['missing_table1_vs_expected'])}",
        f"missing_table2={join_or_none(audit['missing_table2_vs_expected'])}",
        f"extra_table1={join_or_none(audit['extra_table1_vs_expected'])}",
        f"extra_table2={join_or_none(audit['extra_table2_vs_expected'])}",
        f"duplicates_table1={join_or_none(audit['duplicates_table1'])}",
        f"duplicates_table2={join_or_none(audit['duplicates_table2'])}",
        f"only_in_table1={join_or_none(audit['tokens_only_in_table1'])}",
        f"only_in_table2={join_or_none(audit['tokens_only_in_table2'])}",
        f"invalid_table1_count={len(summary['invalid_table1'])}",
        f"invalid_table2_count={len(summary['invalid_table2'])}",
        f"all_valid_joined={summary['all_valid_joined']}",
        f"validation_status={summary['validation_status']}",
        f"wrote_files={summary['wrote_files']}",
    ]
    if summary["wrote_files"]:
        for k in ("table1_jsonl", "table2_jsonl", "joined_jsonl", "validation_json"):
            lines.append(f"  {k}={summary['output_paths'][k]}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize A+ Table 1 and Table 2 snapshots into a joined research dataset.",
    )
    parser.add_argument("--table1-path", required=True)
    parser.add_argument("--table2-path", required=True)
    parser.add_argument(
        "--output-dir",
        default="data/research/aplus_table1_table2_normalized_v1",
    )
    parser.add_argument("--output", choices=["table", "json"], default="table")
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument(
        "--table1-ts-override",
        default=None,
        help="Override the internal Table 1 timestamp (YYYY-MM-DDTHH:MM:SSZ). "
             "Use when the raw file carries a stale or incorrect timestamp.",
    )
    parser.add_argument(
        "--table2-ts-override",
        default=None,
        help="Override the internal Table 2 timestamp (YYYY-MM-DDTHH:MM:SSZ). "
             "Use when the raw file carries a stale or incorrect timestamp.",
    )
    args = parser.parse_args(argv)

    t1_path = Path(args.table1_path)
    t2_path = Path(args.table2_path)

    t1_ts, t1_rows = parse_table1(t1_path)
    t2_ts, t2_rows = parse_table2(t2_path)

    # Record internal timestamps before any override so the override fact is documented.
    t1_ts_internal = t1_ts
    t2_ts_internal = t2_ts

    if args.table1_ts_override:
        t1_ts = args.table1_ts_override
        for r in t1_rows:
            r["prediction_ts_utc"] = t1_ts

    if args.table2_ts_override:
        t2_ts = args.table2_ts_override
        for r in t2_rows:
            r["prediction_ts_utc"] = t2_ts

    t1_tokens = [r["token"] for r in t1_rows]
    t2_tokens = [r["token"] for r in t2_rows]
    audit = token_audit(t1_tokens, t2_tokens)

    invalid_table1 = collect_invalid(t1_rows, "table1")
    invalid_table2 = collect_invalid(t2_rows, "table2")

    pair_meta = compute_pair_metadata(t1_ts, t2_ts)
    joined = build_joined(t1_rows, t2_rows, t1_path, t2_path, pair_meta)

    table1_count_matches_expected = len(t1_rows) == EXPECTED_TOKEN_COUNT
    table2_count_matches_expected = len(t2_rows) == EXPECTED_TOKEN_COUNT
    joined_count_equals_intersection = len(joined) == len(audit["tokens_in_both"])
    all_expected_in_t1 = not audit["missing_table1_vs_expected"]
    all_expected_in_t2 = not audit["missing_table2_vs_expected"]
    no_dups = not audit["duplicates_table1"] and not audit["duplicates_table2"]
    no_extras = not audit["extra_table1_vs_expected"] and not audit["extra_table2_vs_expected"]
    no_invalid_t1 = not invalid_table1
    no_invalid_t2 = not invalid_table2
    all_valid_joined = all(r["validation_status"] == "VALID" for r in joined)

    validation_status = "VALID" if all([
        no_dups,
        no_invalid_t1,
        no_invalid_t2,
        all_valid_joined,
        joined_count_equals_intersection,
        len(joined) > 0,
        pair_meta["timestamp_mismatch_allowed"],
    ]) else "INVALID"

    t1_slug = slug_from_ts(t1_ts)
    t2_slug = slug_from_ts(t2_ts)
    if t1_slug == t2_slug:
        pair_slug = t1_slug
    else:
        date_part_t1, time_part_t1 = t1_slug.split("_")
        _, time_part_t2 = t2_slug.split("_")
        pair_slug = f"{date_part_t1}_{time_part_t1}_{time_part_t2}"

    out_dir = Path(args.output_dir)
    output_paths = {
        "table1_jsonl": str(out_dir / f"table1_normalized_{t1_slug}.jsonl"),
        "table2_jsonl": str(out_dir / f"table2_normalized_{t2_slug}.jsonl"),
        "joined_jsonl": str(out_dir / f"table1_table2_joined_{pair_slug}.jsonl"),
        "validation_json": str(out_dir / f"validation_summary_{pair_slug}.json"),
    }

    summary: dict[str, Any] = {
        "report": REPORT_NAME,
        "parser_version": PARSER_VERSION,
        "scope": "research-only market-only account-agnostic",
        "prediction_ts_utc": pair_meta["pair_reference_ts_utc"],
        "prediction_ts_utc_note": "pair-level reference only; see table1_prediction_ts_utc / table2_prediction_ts_utc for per-table snapshot timestamps",
        "source_table1_path": str(t1_path),
        "source_table2_path": str(t2_path),
        "table1_prediction_ts_utc": pair_meta["table1_prediction_ts_utc"],
        "table2_prediction_ts_utc": pair_meta["table2_prediction_ts_utc"],
        "pair_reference_ts_utc": pair_meta["pair_reference_ts_utc"],
        "timestamp_mismatch_minutes": pair_meta["timestamp_mismatch_minutes"],
        "same_snapshot_ts": pair_meta["same_snapshot_ts"],
        "timestamp_mismatch_allowed": pair_meta["timestamp_mismatch_allowed"],
        "table1_ts_internal": t1_ts_internal,
        "table2_ts_internal": t2_ts_internal,
        "table1_ts_override_applied": bool(args.table1_ts_override),
        "table2_ts_override_applied": bool(args.table2_ts_override),
        "expected_token_count": EXPECTED_TOKEN_COUNT,
        "expected_tokens": EXPECTED_TOKENS,
        "table1_rows": len(t1_rows),
        "table2_rows": len(t2_rows),
        "joined_rows": len(joined),
        "table1_count_matches_expected": table1_count_matches_expected,
        "table2_count_matches_expected": table2_count_matches_expected,
        "joined_count_equals_intersection": joined_count_equals_intersection,
        "all_expected_in_table1": all_expected_in_t1,
        "all_expected_in_table2": all_expected_in_t2,
        "no_duplicates": no_dups,
        "no_extras": no_extras,
        "no_invalid_table1": no_invalid_t1,
        "no_invalid_table2": no_invalid_t2,
        "all_valid_joined": all_valid_joined,
        "token_audit": audit,
        "invalid_table1": invalid_table1,
        "invalid_table2": invalid_table2,
        "validation_status": validation_status,
        "safety_markers": {
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "db_writes": 0,
            "selection_engine_changes": 0,
            "advice_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
            "paper_live_logic": "not_allowed",
            "account_state": "not_allowed",
            "research_only": True,
            "market_only": True,
            "account_agnostic": True,
        },
        "output_paths": output_paths,
        "wrote_files": bool(args.write_files),
    }

    if args.write_files:
        write_jsonl(Path(output_paths["table1_jsonl"]), t1_rows)
        write_jsonl(Path(output_paths["table2_jsonl"]), t2_rows)
        write_jsonl(Path(output_paths["joined_jsonl"]), joined)
        write_json(Path(output_paths["validation_json"]), summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(render_table_summary(summary))

    return 0 if validation_status == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
