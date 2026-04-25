from __future__ import annotations

import re
from dataclasses import dataclass

from src.breathline.models import (
    ALLOWED_LEVEL_VALUES,
    ALLOWED_PRESSURE_VALUES,
    ALLOWED_SHIFT_VALUES,
    BreathlineTokenRow,
)


TABLE_HEADER = "TOKEN MOMENTUM STABILITY ALIGNMENT VOLATILITY PRESSURE SHIFT"
TOKEN_LINE_RE = re.compile(r"^[A-Z0-9]{2,20}\b")


@dataclass(slots=True, frozen=True)
class ParsedBreathlineTable:
    rows: list[BreathlineTokenRow]
    rejected_lines: list[str]


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _clean_raw_text(raw_text: str) -> list[str]:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in text.split("\n") if line.strip()]


def _normalize_shift(value: str) -> str:
    """
    Strict normalization for known observed schema leakage.
    We only coerce values we have explicitly seen and agreed on.
    """
    value = value.strip().lower()
    if value == "volatile":
        return "stable"
    if value == "neutral":
        return "stable"
    return value


def _validate_row_parts(parts: list[str], original_line: str) -> BreathlineTokenRow:
    if len(parts) != 7:
        raise ValueError(f"Invalid token row column count ({len(parts)}): {original_line}")

    token, momentum, stability, alignment, volatility, pressure, shift = parts

    momentum = momentum.lower()
    stability = stability.lower()
    alignment = alignment.lower()
    volatility = volatility.lower()
    pressure = pressure.lower()
    shift = _normalize_shift(shift)

    if momentum not in ALLOWED_LEVEL_VALUES:
        raise ValueError(f"Invalid momentum '{momentum}' in line: {original_line}")
    if stability not in ALLOWED_LEVEL_VALUES:
        raise ValueError(f"Invalid stability '{stability}' in line: {original_line}")
    if alignment not in ALLOWED_LEVEL_VALUES:
        raise ValueError(f"Invalid alignment '{alignment}' in line: {original_line}")
    if volatility not in ALLOWED_LEVEL_VALUES:
        raise ValueError(f"Invalid volatility '{volatility}' in line: {original_line}")
    if pressure not in ALLOWED_PRESSURE_VALUES:
        raise ValueError(f"Invalid pressure '{pressure}' in line: {original_line}")
    if shift not in ALLOWED_SHIFT_VALUES:
        raise ValueError(f"Invalid shift '{shift}' in line: {original_line}")

    return BreathlineTokenRow(
        token=token.upper(),
        momentum=momentum,
        stability=stability,
        alignment=alignment,
        volatility=volatility,
        pressure=pressure,
        shift=shift,
    )


def parse_breathline_table(raw_text: str) -> ParsedBreathlineTable:
    """
    Parses only strict table rows from a raw A+ output.
    Narrative lines are ignored if they do not look like token rows.
    The function intentionally starts reading only after the expected header
    or after the first valid token row if header is absent.
    """
    lines = _clean_raw_text(raw_text)

    rows: list[BreathlineTokenRow] = []
    rejected_lines: list[str] = []
    seen_header = False
    parsing_started = False

    for line in lines:
        normalized = _normalize_space(line)

        if normalized.upper() == TABLE_HEADER:
            seen_header = True
            parsing_started = True
            continue

        if not parsing_started:
            if TOKEN_LINE_RE.match(normalized):
                parsing_started = True
            else:
                rejected_lines.append(normalized)
                continue

        if not TOKEN_LINE_RE.match(normalized):
            rejected_lines.append(normalized)
            continue

        parts = normalized.split(" ")
        try:
            row = _validate_row_parts(parts, normalized)
        except ValueError:
            rejected_lines.append(normalized)
            continue

        rows.append(row)

    if not rows:
        raise ValueError("No valid Breathline token rows found in raw input.")

    tokens = [row.token for row in rows]
    duplicate_tokens = sorted({token for token in tokens if tokens.count(token) > 1})
    if duplicate_tokens:
        raise ValueError(f"Duplicate tokens in Breathline table: {', '.join(duplicate_tokens)}")

    return ParsedBreathlineTable(rows=rows, rejected_lines=rejected_lines)
