from __future__ import annotations

import html
from typing import Any

from src.reporting.label_registry_v1 import (
    get_label_aria_label,
    get_label_axis_value,
    get_label_description,
    get_label_metadata,
)


UNKNOWN_AXIS_DESCRIPTION = "Display score/axis value. No description registered yet."
_AXIS_DESCRIPTIONS = {
    "candidate_readiness_pressure": (
        "Negative means caution/blocking pressure; zero means neutral/wait; "
        "positive means stronger entry-readiness context. It is not expected return and not order permission."
    )
}


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def badge_html(
    label: Any,
    *,
    css_name: str | None = None,
    text: Any | None = None,
) -> str:
    label_text = "" if label is None else str(label)
    visible_text = label_text if text is None else str(text)
    if not visible_text.strip():
        return ""
    return (
        f"<span class='pill {esc(css_name or 'muted')}' title='{esc(get_label_description(label_text))}' "
        f"aria-label='{esc(get_label_aria_label(label_text))}'>{esc(visible_text)}</span>"
    )


def axis_value_description(label: Any) -> str:
    metadata = get_label_metadata("" if label is None else str(label))
    if metadata.axis_name is None or metadata.axis_value is None:
        return UNKNOWN_AXIS_DESCRIPTION
    description = _AXIS_DESCRIPTIONS.get(metadata.axis_name, UNKNOWN_AXIS_DESCRIPTION)
    if metadata.action_hint:
        description = f"{description} Action hint: {metadata.action_hint}."
    return description


def axis_value_html(label: Any) -> str:
    label_text = "" if label is None else str(label)
    metadata = get_label_metadata(label_text)
    axis_value = get_label_axis_value(label_text, metadata.axis_name or "")
    if axis_value is None:
        return ""
    visible_text = f"({axis_value:+d})"
    description = axis_value_description(label_text)
    aria = f"{label_text} axis {axis_value:+d}: {description}"
    return (
        f"<span class='muted small axis-value' title='{esc(description)}' "
        f"aria-label='{esc(aria)}'>{esc(visible_text)}</span>"
    )


def badge_with_axis_html(
    label: Any,
    *,
    css_name: str | None = None,
    text: Any | None = None,
) -> str:
    return f"{badge_html(label, css_name=css_name, text=text)}{axis_value_html(label)}"
