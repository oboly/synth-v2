from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


DEFAULT_UI_TIMEZONE = "Europe/Amsterdam"


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_ui_timestamp(
    value: datetime | None,
    *,
    timezone: str = DEFAULT_UI_TIMEZONE,
    missing_text: str = "not available",
) -> str:
    if value is None:
        return missing_text
    localized = _normalize_utc(value).astimezone(ZoneInfo(timezone))
    return localized.strftime("%Y-%m-%d %H:%M:%S %Z")


def format_ui_now(
    *,
    now_utc: datetime | None = None,
    timezone: str = DEFAULT_UI_TIMEZONE,
) -> str:
    return format_ui_timestamp(now_utc or datetime.now(UTC), timezone=timezone)
