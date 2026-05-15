from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_NAME = "aplus_table1_only_normalized_v1"
PARSER_VERSION = "0.1"
SNAPSHOT_ID_SUFFIX = "table1_only"

EXPECTED_TOKENS = [
    "BTC", "ETH", "SOL", "ADA", "DEEP", "FIL", "HBAR", "HOT", "NEAR", "PEPE",
    "POL", "QNT", "SUI", "VET", "WAL", "XLM", "AAVE", "CC", "CRV", "FLOKI",
    "HYPE", "LDO", "LTC", "ONDO", "RLC", "WLD", "XRP", "ALGO", "DOT", "FET",
    "HNT", "ICP", "INJ", "IOST", "MOG", "NOT", "RED", "RENDER", "XPL", "TAO",
    "LINK",
]
EXPECTED_TOKEN_SET = set(EXPECTED_TOKENS)

TABLE1_CONTROLLED_FIELDS = [
    "phase", "coherence", "field", "geometry",
    "structural_role", "expansion_quality", "anchor_strength", "strategic_bias",
]
TABLE1_HEADER_TOKENS = [
    "TOKEN", "PHASE", "COHERENCE", "FIELD", "GEOMETRY",
    "STRUCTURAL_ROLE", "EXPANSION_QUALITY", "ANCHOR_STRENGTH",
    "STRATEGIC_BIAS", "NOTES",
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


def slug_from_ts(ts: str) -> str:
    dt = datetime.strptime(ts.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    return dt.strftime("%Y%m%d_%H%M")


def clean_notes(text: str) -> str:
    s = text.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    return s


# ── pipe-separated parser ──────────────────────────────────────────────────────

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


def is_pipe_header(cells: list[str]) -> bool:
    if len(cells) != len(TABLE1_HEADER_TOKENS):
        return False
    return [c.strip().upper() for c in cells] == TABLE1_HEADER_TOKENS


def parse_table1_pipe(text: str, source_path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    header_seen = False
    for line in text.splitlines():
        cells = parse_pipe_row(line)
        if cells is None:
            continue
        if not header_seen:
            if is_pipe_header(cells):
                header_seen = True
            continue
        if len(cells) != len(TABLE1_HEADER_TOKENS):
            continue
        token_cell = cells[0].strip().upper()
        if not TOKEN_RE.match(token_cell):
            continue
        rows.append(cells)
    return rows, header_seen


# ── space-separated parser ─────────────────────────────────────────────────────

def is_space_header(parts: list[str]) -> bool:
    """True when the first 10 whitespace-split tokens match the Table 1 header."""
    if len(parts) < len(TABLE1_HEADER_TOKENS):
        return False
    return [p.upper() for p in parts[:len(TABLE1_HEADER_TOKENS)]] == TABLE1_HEADER_TOKENS


def parse_table1_space(text: str, source_path: Path) -> tuple[list[list[str]], bool]:
    """Parse a space-separated Table 1 file.

    Data rows: TOKEN field1 field2 ... field8 [notes words...]
    The first 9 whitespace tokens are the 8 controlled fields + token.
    Everything from position 9 onward is joined as NOTES.
    """
    rows: list[list[str]] = []
    header_seen = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if not header_seen:
            if is_space_header(parts):
                header_seen = True
            continue
        if len(parts) < 9:
            continue
        token = parts[0].upper()
        if not TOKEN_RE.match(token):
            continue
        notes = " ".join(parts[9:]) if len(parts) > 9 else ""
        # Reconstruct as a 10-cell list matching TABLE1_HEADER_TOKENS order.
        cells = [token] + [p.lower() for p in parts[1:9]] + [notes]
        rows.append(cells)
    return rows, header_seen


# ── unified parser ─────────────────────────────────────────────────────────────

def parse_table1(path: Path) -> tuple[str, list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8")
    prediction_ts_utc = extract_timestamp(text)

    # Try pipe format first; fall back to space-separated.
    pipe_rows, pipe_header = parse_table1_pipe(text, path)
    if pipe_header and pipe_rows:
        cell_rows = pipe_rows
    else:
        space_rows, space_header = parse_table1_space(text, path)
        if not space_header:
            raise ValueError(
                f"No recognisable Table 1 header found in {path} "
                "(tried pipe-separated and space-separated formats)"
            )
        cell_rows = space_rows

    rows = [normalize_row(c, prediction_ts_utc, path) for c in cell_rows]
    return prediction_ts_utc, rows


def normalize_row(cells: list[str], prediction_ts_utc: str, source_path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "token": cells[0].strip().upper(),
        "table1_phase": cells[1].strip().lower(),
        "table1_coherence": cells[2].strip().lower(),
        "table1_field": cells[3].strip().lower(),
        "table1_geometry": cells[4].strip().lower(),
        "table1_structural_role": cells[5].strip().lower(),
        "table1_expansion_quality": cells[6].strip().lower(),
        "table1_anchor_strength": cells[7].strip().lower(),
        "table1_strategic_bias": cells[8].strip().lower(),
        "table1_notes": clean_notes(cells[9]) if len(cells) > 9 else "",
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


# ── staging row builder ────────────────────────────────────────────────────────

def build_staging_row(
    raw: dict[str, Any],
    snapshot_id: str,
    prediction_ts_utc: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "table1_prediction_ts_utc": prediction_ts_utc,
        "prediction_ts_utc": prediction_ts_utc,
        "table2_present": False,
        "joined_pair_available": False,
        "token": raw["token"],
        "table1_phase": raw["table1_phase"],
        "table1_coherence": raw["table1_coherence"],
        "table1_field": raw["table1_field"],
        "table1_geometry": raw["table1_geometry"],
        "table1_structural_role": raw["table1_structural_role"],
        "table1_expansion_quality": raw["table1_expansion_quality"],
        "table1_anchor_strength": raw["table1_anchor_strength"],
        "table1_strategic_bias": raw["table1_strategic_bias"],
        "table1_notes": raw.get("table1_notes", ""),
        "source_table1_path": raw["source_table1_path"],
        "parser_version": raw["parser_version"],
        "validation_status": raw["validation_status"],
    }
    return row


# ── audit helpers ──────────────────────────────────────────────────────────────

def token_audit(tokens: list[str]) -> dict[str, Any]:
    token_set = set(tokens)
    counts = Counter(tokens)
    return {
        "token_count": len(tokens),
        "unique_count": len(token_set),
        "duplicates": sorted(k for k, v in counts.items() if v > 1),
        "missing_vs_expected": sorted(EXPECTED_TOKEN_SET - token_set),
        "extra_vs_expected": sorted(token_set - EXPECTED_TOKEN_SET),
    }


# ── output helpers ─────────────────────────────────────────────────────────────

def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def _fmt_list(lst: list) -> str:
    return ", ".join(sorted(lst)) if lst else "none"


def render_table_summary(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"report={REPORT_NAME} version={PARSER_VERSION}")
    lines.append("scope=research-only market-only account-agnostic")
    lines.append("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    lines.append("selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none")
    lines.append(f"snapshot_id={summary['snapshot_id']}")
    lines.append(f"table1_prediction_ts_utc={summary['table1_prediction_ts_utc']}")
    lines.append(f"table2_present={summary['table2_present']}")
    lines.append(f"joined_pair_available={summary['joined_pair_available']}")
    lines.append(f"table1_rows={summary['table1_rows']}")
    lines.append(f"duplicate_tokens={summary['duplicate_tokens']}")
    lines.append(f"invalid_controlled_values={summary['invalid_controlled_values']}")
    lines.append(f"missing_expected_tokens={_fmt_list(summary['missing_expected_tokens'])}")
    lines.append(f"extra_tokens={_fmt_list(summary['extra_tokens'])}")
    lines.append(f"validation_status={summary['validation_status']}")
    lines.append("")
    lines.append(f"wrote_files={summary['wrote_files']}")
    if summary["wrote_files"]:
        for k, v in summary["output_paths"].items():
            lines.append(f"  {k}={v}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize a Table 1-only A+ Breathline snapshot into the Table1-only staging dataset (research-only)."
    )
    parser.add_argument(
        "--table1-path",
        default="data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt",
    )
    parser.add_argument(
        "--output-dir",
        default="data/research/aplus_table1_only_normalized_v1",
    )
    parser.add_argument("--output", choices=["table", "json"], default="table")
    parser.add_argument("--write-files", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    table1_path = Path(args.table1_path)
    out_dir = Path(args.output_dir)

    prediction_ts_utc, raw_rows = parse_table1(table1_path)

    slug = slug_from_ts(prediction_ts_utc)
    snapshot_id = f"{slug}_{SNAPSHOT_ID_SUFFIX}"

    staging_rows = [build_staging_row(r, snapshot_id, prediction_ts_utc) for r in raw_rows]

    tokens = [r["token"] for r in raw_rows]
    audit = token_audit(tokens)

    invalid_rows = [r for r in raw_rows if r["validation_status"] != "VALID"]
    invalid_count = sum(len(r.get("_invalid", [])) for r in raw_rows)
    all_rows_valid = all(r["validation_status"] == "VALID" for r in raw_rows)

    is_valid = (
        len(raw_rows) > 0
        and audit["unique_count"] == len(tokens)  # no duplicates
        and invalid_count == 0
        and all_rows_valid
    )
    validation_status = "VALID" if is_valid else "INVALID"

    output_paths = {
        "table1_jsonl": str(out_dir / f"table1_normalized_{slug}.jsonl"),
        "validation_json": str(out_dir / f"validation_summary_{slug}.json"),
    }

    summary: dict[str, Any] = {
        "report": REPORT_NAME,
        "parser_version": PARSER_VERSION,
        "scope": "research-only market-only account-agnostic",
        "snapshot_id": snapshot_id,
        "table1_prediction_ts_utc": prediction_ts_utc,
        "prediction_ts_utc": prediction_ts_utc,
        "table2_present": False,
        "joined_pair_available": False,
        "source_table1_path": str(table1_path),
        "table1_rows": len(raw_rows),
        "expected_token_count": len(EXPECTED_TOKENS),
        "duplicate_tokens": len(audit["duplicates"]),
        "duplicate_token_list": audit["duplicates"],
        "invalid_controlled_values": invalid_count,
        "invalid_rows": [
            {"token": r["token"], "invalid_fields": r.get("_invalid", [])}
            for r in invalid_rows
        ],
        "missing_expected_tokens": audit["missing_vs_expected"],
        "extra_tokens": audit["extra_vs_expected"],
        "all_rows_valid": all_rows_valid,
        "validation_status": validation_status,
        "output_paths": output_paths,
        "wrote_files": bool(args.write_files),
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
    }

    if args.write_files:
        write_jsonl(Path(output_paths["table1_jsonl"]), staging_rows)
        write_json(Path(output_paths["validation_json"]), summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(render_table_summary(summary))

    return 0 if validation_status == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
