from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


TOKEN_PATTERN = re.compile(
    r"^([A-Z0-9]+)\s+"
    r"([A-Za-z ]+?)\s+"
    r"([A-Za-z ]+?)\s+"
    r"([A-Za-z ]+?)\s+"
    r"([A-Za-z ]+?)\s+"
    r"([A-Za-z\- ]+?)\s+"
    r"([A-Za-z ]+?)\s+"
    r"([A-Za-z ]+?)\s+"
    r"([A-Za-z ]+?)\s+"
    r"(.+)$"
)


def parse_compass_table(raw_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        match = TOKEN_PATTERN.match(stripped)
        if not match:
            continue

        rows.append(
            {
                "token": match.group(1).strip(),
                "phase": match.group(2).strip(),
                "coherence": match.group(3).strip(),
                "field": match.group(4).strip(),
                "geometry": match.group(5).strip(),
                "structural_role": match.group(6).strip(),
                "expansion_quality": match.group(7).strip(),
                "anchor_strength": match.group(8).strip(),
                "strategic_bias": match.group(9).strip(),
                "notes": match.group(10).strip(),
            }
        )

    return rows


def build_parsed_payload(
    source_filename: str,
    source_name: str,
    source_type: str,
    prediction_ts_utc: str,
    raw_text: str,
) -> dict[str, Any]:
    rows = parse_compass_table(raw_text)

    return {
        "meta": {
            "source_filename": source_filename,
            "source_name": source_name,
            "source_type": source_type,
            "prediction_ts_utc": prediction_ts_utc,
            "row_count": len(rows),
            "parser_version": "v1",
        },
        "rows": rows,
    }


def write_parsed_json(parsed_payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(parsed_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
