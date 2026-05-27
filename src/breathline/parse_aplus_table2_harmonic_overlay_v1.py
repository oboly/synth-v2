from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
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
class Table2Record:
    schema_version: str
    source_table: str
    prediction_ts_utc: str
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
        description="Parse raw A+ Table 2 harmonic phase overlay snapshot."
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


def parse_table2_raw(raw: str) -> list[Table2Record]:
    prediction_ts = _extract_prediction_ts(raw)
    records: list[Table2Record] = []

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

        token = parts[0]
        harmonic_phase = parts[1]
        phase_state = parts[2]
        offset_band = parts[3]
        drift_direction = parts[4]
        quality = parts[5]
        extension_risk = parts[6]
        notes = _clean_note(parts[7])

        values = {
            "harmonic_phase": harmonic_phase,
            "phase_state": phase_state,
            "offset_band": offset_band,
            "drift_direction": drift_direction,
            "quality": quality,
            "extension_risk": extension_risk,
        }
        for field_name, value in values.items():
            _validate_allowed(token, field_name, value)

        records.append(
            Table2Record(
                schema_version="aplus_table2_harmonic_overlay_v1",
                source_table="TABLE_2",
                prediction_ts_utc=prediction_ts,
                token=token,
                harmonic_phase=harmonic_phase,
                phase_state=phase_state,
                offset_band=offset_band,
                drift_direction=drift_direction,
                quality=quality,
                extension_risk=extension_risk,
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


def _print_table(records: list[Table2Record]) -> None:
    columns = [
        "prediction_ts_utc",
        "token",
        "harmonic_phase",
        "phase_state",
        "offset_band",
        "drift_direction",
        "quality",
        "extension_risk",
        "notes",
    ]
    print("\t".join(columns))
    for record in records:
        row = asdict(record)
        print("\t".join(str(row[col]) for col in columns))


def _print_jsonl(records: list[Table2Record]) -> None:
    for record in records:
        print(json.dumps(asdict(record), sort_keys=True, ensure_ascii=False))


def main() -> None:
    args = _parse_args()
    raw = Path(args.raw_file).read_text(encoding="utf-8")
    records = parse_table2_raw(raw)

    if args.output == "jsonl":
        _print_jsonl(records)
    else:
        _print_table(records)


if __name__ == "__main__":
    main()
