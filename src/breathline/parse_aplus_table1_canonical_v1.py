from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


EXPECTED_TOKENS = [
    "BTC", "ETH", "SOL", "ADA", "DEEP", "FIL", "HBAR", "HOT", "NEAR", "PEPE",
    "POL", "QNT", "SUI", "VET", "WAL", "XLM", "AAVE", "CC", "CRV", "FLOKI",
    "HYPE", "LDO", "LTC", "ONDO", "RLC", "WLD", "XRP", "ALGO", "DOT", "FET",
    "HNT", "ICP", "INJ", "IOST", "MOG", "NOT", "RED", "RENDER", "XPL", "TAO",
]

ALLOWED = {
    "phase": {"early", "forming", "confirmed", "late", "exhaustion", "reset", "neutral"},
    "coherence": {"high", "moderate", "low"},
    "field": {"expansion", "compression", "transition", "neutral"},
    "geometry": {"clean", "mixed", "distorted", "unknown"},
    "structural_role": {"leader", "confirmer", "laggard", "speculative", "defensive", "unknown"},
    "expansion_quality": {"strong", "moderate", "weak", "none"},
    "anchor_strength": {"strong", "moderate", "weak", "none"},
    "strategic_bias": {"accumulation", "continuation", "caution", "avoid", "neutral"},
}

TIMESTAMP_RE = re.compile(r"prediction_ts_utc\s*=\s*([0-9T:\-]+Z)")


@dataclass(frozen=True)
class Table1Record:
    schema_version: str
    source_table: str
    prediction_ts_utc: str
    token: str
    phase: str
    coherence: str
    field: str
    geometry: str
    structural_role: str
    expansion_quality: str
    anchor_strength: str
    strategic_bias: str
    notes: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse raw A+ Table 1 canonical Breathline snapshot."
    )
    parser.add_argument("--raw-file", required=True)
    parser.add_argument(
        "--output",
        choices=["table", "jsonl"],
        default="table",
    )
    return parser.parse_args()


def _clean(value: str) -> str:
    return value.strip().strip("`").strip()


def _clean_note(value: str) -> str:
    value = _clean(value)
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _extract_prediction_ts(raw: str) -> str:
    match = TIMESTAMP_RE.search(raw)
    if not match:
        raise ValueError("Missing prediction_ts_utc")
    return match.group(1)


def _validate_allowed(token: str, field_name: str, value: str) -> None:
    if value not in ALLOWED[field_name]:
        raise ValueError(
            f"{token}: invalid {field_name}={value!r}; "
            f"allowed={sorted(ALLOWED[field_name])}"
        )


def parse_table1_raw(raw: str) -> list[Table1Record]:
    prediction_ts = _extract_prediction_ts(raw)
    records: list[Table1Record] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue
        if stripped.upper().startswith("TOKEN |"):
            continue

        first = stripped.split("|", 1)[0].strip()
        if first not in EXPECTED_TOKENS:
            continue

        parts = [_clean(part) for part in stripped.split("|")]
        if len(parts) != 10:
            raise ValueError(f"Expected 10 pipe-separated fields, got {len(parts)}: {line}")

        token = parts[0]
        phase = parts[1]
        coherence = parts[2]
        field = parts[3]
        geometry = parts[4]
        structural_role = parts[5]
        expansion_quality = parts[6]
        anchor_strength = parts[7]
        strategic_bias = parts[8]
        notes = _clean_note(parts[9])

        values = {
            "phase": phase,
            "coherence": coherence,
            "field": field,
            "geometry": geometry,
            "structural_role": structural_role,
            "expansion_quality": expansion_quality,
            "anchor_strength": anchor_strength,
            "strategic_bias": strategic_bias,
        }
        for field_name, value in values.items():
            _validate_allowed(token, field_name, value)

        records.append(
            Table1Record(
                schema_version="aplus_table1_canonical_v1",
                source_table="TABLE_1",
                prediction_ts_utc=prediction_ts,
                token=token,
                phase=phase,
                coherence=coherence,
                field=field,
                geometry=geometry,
                structural_role=structural_role,
                expansion_quality=expansion_quality,
                anchor_strength=anchor_strength,
                strategic_bias=strategic_bias,
                notes=notes,
            )
        )

    seen = [record.token for record in records]
    missing = sorted(set(EXPECTED_TOKENS) - set(seen))
    duplicates = sorted(token for token, count in Counter(seen).items() if count > 1)

    if len(records) != len(EXPECTED_TOKENS):
        raise ValueError(f"Expected {len(EXPECTED_TOKENS)} rows, got {len(records)}")
    if missing:
        raise ValueError(f"Missing tokens: {','.join(missing)}")
    if duplicates:
        raise ValueError(f"Duplicate tokens: {','.join(duplicates)}")

    return records


def _print_table(records: list[Table1Record]) -> None:
    columns = [
        "prediction_ts_utc",
        "token",
        "phase",
        "coherence",
        "field",
        "geometry",
        "structural_role",
        "expansion_quality",
        "anchor_strength",
        "strategic_bias",
        "notes",
    ]
    print("\t".join(columns))
    for record in records:
        row = asdict(record)
        print("\t".join(str(row[col]) for col in columns))


def _print_jsonl(records: list[Table1Record]) -> None:
    for record in records:
        print(json.dumps(asdict(record), sort_keys=True, ensure_ascii=False))


def main() -> None:
    args = _parse_args()
    raw = Path(args.raw_file).read_text(encoding="utf-8")
    records = parse_table1_raw(raw)

    if args.output == "jsonl":
        _print_jsonl(records)
    else:
        _print_table(records)


if __name__ == "__main__":
    main()
