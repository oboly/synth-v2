from __future__ import annotations

import html
from typing import Any

from src.reporting.label_registry_v1 import (
    get_label_aria_label,
    get_label_description,
)


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def badge_html(
    label: Any,
    *,
    css_name: str,
    text: Any | None = None,
) -> str:
    label_text = "" if label is None else str(label)
    visible_text = label_text if text is None else str(text)
    return (
        f"<span class='pill {css_name}' title='{esc(get_label_description(label_text))}' "
        f"aria-label='{esc(get_label_aria_label(label_text))}'>{esc(visible_text)}</span>"
    )
