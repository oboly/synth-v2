from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


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
class Table1Row:
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
        description="Validate raw A+ Table 1 canonical Breathline snapshot."
    )
    parser.add_argument("--raw-file", required=True)
    return parser.parse_args()


def _clean(value: str) -> str:
    return value.strip().strip("`").strip()


def _parse_rows(raw: str) -> list[Table1Row]:
    rows: list[Table1Row] = []

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

        rows.append(
            Table1Row(
                token=parts[0],
                phase=parts[1],
                coherence=parts[2],
                field=parts[3],
                geometry=parts[4],
                structural_role=parts[5],
                expansion_quality=parts[6],
                anchor_strength=parts[7],
                strategic_bias=parts[8],
                notes=parts[9],
            )
        )

    return rows


def _validate_allowed(row: Table1Row) -> list[str]:
    errors: list[str] = []
    checks = {
        "phase": row.phase,
        "coherence": row.coherence,
        "field": row.field,
        "geometry": row.geometry,
        "structural_role": row.structural_role,
        "expansion_quality": row.expansion_quality,
        "anchor_strength": row.anchor_strength,
        "strategic_bias": row.strategic_bias,
    }

    for field_name, value in checks.items():
        if value not in ALLOWED[field_name]:
            errors.append(f"{row.token}: invalid {field_name}={value!r}")

    return errors


def main() -> None:
    args = _parse_args()
    raw_file = Path(args.raw_file)
    raw = raw_file.read_text(encoding="utf-8")

    timestamp_match = TIMESTAMP_RE.search(raw)
    prediction_ts = timestamp_match.group(1) if timestamp_match else None

    rows = _parse_rows(raw)
    seen = [row.token for row in rows]

    errors: list[str] = []

    if prediction_ts is None:
        errors.append("Missing prediction_ts_utc")
    if len(rows) != len(EXPECTED_TOKENS):
        errors.append(f"Expected {len(EXPECTED_TOKENS)} token rows, got {len(rows)}")

    missing = sorted(set(EXPECTED_TOKENS) - set(seen))
    extra = sorted(set(seen) - set(EXPECTED_TOKENS))
    duplicates = sorted(token for token, count in Counter(seen).items() if count > 1)

    if missing:
        errors.append(f"Missing tokens: {','.join(missing)}")
    if extra:
        errors.append(f"Unexpected tokens: {','.join(extra)}")
    if duplicates:
        errors.append(f"Duplicate tokens: {','.join(duplicates)}")

    for row in rows:
        errors.extend(_validate_allowed(row))

    print("[RUN] A+ Table 1 raw validator")
    print(f"raw_file={raw_file}")
    print(f"prediction_ts_utc={prediction_ts or ''}")
    print(f"row_count={len(rows)}")

    print()
    print("=== COUNTS ===")
    for field_name in [
        "phase",
        "coherence",
        "field",
        "geometry",
        "structural_role",
        "expansion_quality",
        "anchor_strength",
        "strategic_bias",
    ]:
        counter = Counter(getattr(row, field_name) for row in rows)
        print(field_name)
        for key, value in sorted(counter.items()):
            print(f"  {key}: {value}")

    if errors:
        print()
        print("=== ERRORS ===")
        for error in errors:
            print(error)
        raise SystemExit(1)

    print()
    print("[OK] Table 1 raw snapshot is valid")


if __name__ == "__main__":
    main()
