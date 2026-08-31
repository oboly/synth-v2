from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path("config/research/cq_v1_temporal_sampling_v1.json")
UTC = timezone.utc


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware UTC: {value}")
    parsed = parsed.astimezone(UTC)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"timestamp must resolve to UTC: {value}")
    return parsed


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("temporal sampling contract must be a JSON object")
    return payload


def derive_asofs(contract: dict[str, Any]) -> tuple[datetime, ...]:
    sampling = contract["sampling"]
    cadence_seconds = int(sampling["cadence_seconds"])
    if cadence_seconds <= 0:
        raise ValueError("cadence_seconds must be positive")
    first = _parse_utc(str(sampling["first_asof_ts_utc"]))
    last = _parse_utc(str(sampling["last_asof_ts_utc"]))
    if last < first:
        raise ValueError("last_asof_ts_utc must be >= first_asof_ts_utc")

    step = timedelta(seconds=cadence_seconds)
    values: list[datetime] = []
    current = first
    while current <= last:
        values.append(current)
        current += step

    expected = int(sampling["expected_unique_asofs"])
    if len(values) != expected:
        raise ValueError(f"derived as-of count {len(values)} does not match expected {expected}")
    if values[-1] != last:
        raise ValueError("last_asof_ts_utc is not aligned to the frozen cadence")
    return tuple(values)


def split_for_asof(asof: datetime, contract: dict[str, Any]) -> str:
    if asof.tzinfo is None:
        raise ValueError("as-of must be timezone-aware UTC")
    normalized = asof.astimezone(UTC)
    if normalized not in derive_asofs(contract):
        raise ValueError(f"as-of is not a frozen temporal sample: {normalized.isoformat()}")

    matches: list[str] = []
    for split_name in ("discovery", "validation", "holdout"):
        split = contract["chronological_split"][split_name]
        first = _parse_utc(str(split["first_asof_ts_utc"]))
        last = _parse_utc(str(split["last_asof_ts_utc"]))
        if first <= normalized <= last:
            matches.append(split_name)
    if len(matches) != 1:
        raise ValueError(f"as-of must belong to exactly one frozen split: {normalized.isoformat()}")
    return matches[0]


def split_asofs(contract: dict[str, Any]) -> dict[str, tuple[datetime, ...]]:
    grouped: dict[str, list[datetime]] = {
        "discovery": [],
        "validation": [],
        "holdout": [],
    }
    for asof in derive_asofs(contract):
        grouped[split_for_asof(asof, contract)].append(asof)

    result = {name: tuple(values) for name, values in grouped.items()}
    for split_name, values in result.items():
        expected = int(contract["chronological_split"][split_name]["expected_unique_asofs"])
        if len(values) != expected:
            raise ValueError(f"split {split_name} has {len(values)} as-ofs, expected {expected}")
    return result
