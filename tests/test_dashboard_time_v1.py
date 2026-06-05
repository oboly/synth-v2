from __future__ import annotations

from datetime import UTC, datetime

from src.reporting.dashboard_time_v1 import (
    DEFAULT_UI_TIMEZONE,
    format_ui_now,
    format_ui_timestamp,
)


def test_format_ui_timestamp_uses_cest_in_summer() -> None:
    ts = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    assert format_ui_timestamp(ts) == "2026-06-05 14:00:00 CEST"


def test_format_ui_timestamp_uses_cet_in_winter() -> None:
    ts = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    assert format_ui_timestamp(ts) == "2026-01-05 13:00:00 CET"


def test_format_ui_now_defaults_to_amsterdam() -> None:
    ts = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    assert format_ui_now(now_utc=ts) == "2026-06-05 14:00:00 CEST"
    assert DEFAULT_UI_TIMEZONE == "Europe/Amsterdam"


def main() -> None:
    test_format_ui_timestamp_uses_cest_in_summer()
    test_format_ui_timestamp_uses_cet_in_winter()
    test_format_ui_now_defaults_to_amsterdam()
    print("ok")


if __name__ == "__main__":
    main()
