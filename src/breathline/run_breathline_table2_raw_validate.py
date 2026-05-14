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
    "harmonic_phase": {
        "pre_0618",
        "forming_0618",
        "confirmed_0618",
        "forming_0786",
        "confirmed_0786",
        "forming_1000",
        "confirmed_1000",
        "extension_1272",
        "late_extension",
        "reset",
        "unclear",
    },
    "phase_state": {"early", "forming", "confirmed", "late", "exhausted", "unclear"},
    "offset_band": {
        "-10.5", "-9", "-8", "-7", "-5", "-3", "0",
        "+3", "+5", "+7", "+9", "+10.5", "unknown",
    },
    "drift_direction": {
        "converging", "forward_drift", "backward_drift", "flat", "unstable", "unknown",
    },
    "quality": {"clean", "mixed", "dirty", "unknown"},
    "extension_risk": {"low", "moderate", "high", "unknown"},
}

TIMESTAMP_RE = re.compile(r"prediction_ts_utc\s*=\s*([0-9T:\-]+Z)")


@dataclass(frozen=True)
class Table2Row:
    token: str
    harmonic_phase: str
    phase_state: str
    offset_band: str
    drift_direction: str
    quality: str
    extension_risk: str
    notes: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate raw A+ Table 2 harmonic phase overlay snapshot."
    )
    parser.add_argument("--raw-file", required=True)
    return parser.parse_args()


def _clean(value: str) -> str:
    return value.strip().strip("`").strip()


def _parse_rows(raw: str) -> list[Table2Row]:
    rows: list[Table2Row] = []

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
        if len(parts) != 8:
            raise ValueError(f"Expected 8 pipe-separated fields, got {len(parts)}: {line}")

        rows.append(
            Table2Row(
                token=parts[0],
                harmonic_phase=parts[1],
                phase_state=parts[2],
                offset_band=parts[3],
                drift_direction=parts[4],
                quality=parts[5],
                extension_risk=parts[6],
                notes=parts[7],
            )
        )

    return rows


def _validate_allowed(row: Table2Row) -> list[str]:
    errors: list[str] = []
    checks = {
        "harmonic_phase": row.harmonic_phase,
        "phase_state": row.phase_state,
        "offset_band": row.offset_band,
        "drift_direction": row.drift_direction,
        "quality": row.quality,
        "extension_risk": row.extension_risk,
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

    print("[RUN] A+ Table 2 raw validator")
    print(f"raw_file={raw_file}")
    print(f"prediction_ts_utc={prediction_ts or ''}")
    print(f"row_count={len(rows)}")

    print()
    print("=== COUNTS ===")
    for field_name in [
        "harmonic_phase",
        "phase_state",
        "offset_band",
        "drift_direction",
        "quality",
        "extension_risk",
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
    print("[OK] Table 2 raw snapshot is valid")


if __name__ == "__main__":
    main()
