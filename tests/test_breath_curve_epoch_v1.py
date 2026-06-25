from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.market_context.breath_curve_epoch_v1 import (
    CYCLE_DAYS,
    GLOBAL_EPOCH_UTC,
    VALIDATION_CONFIRMED,
    VALIDATION_HOLDOUT,
    resolve_global_epoch_anchor,
    validation_state_for_anchor,
)


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=UTC)


# --- epoch resolver ---


def test_2026_03_13_resolves_to_2026_03_01() -> None:
    anchor, idx = resolve_global_epoch_anchor(_utc(2026, 3, 13))
    assert anchor == _utc(2026, 3, 1)
    assert idx == 2


def test_2026_04_03_resolves_to_2026_03_22() -> None:
    anchor, idx = resolve_global_epoch_anchor(_utc(2026, 4, 3))
    assert anchor == _utc(2026, 3, 22)
    assert idx == 3


def test_2026_06_24_resolves_to_2026_06_14() -> None:
    anchor, idx = resolve_global_epoch_anchor(_utc(2026, 6, 24))
    assert anchor == _utc(2026, 6, 14)
    assert idx == 7


def test_anchor_is_at_or_before_as_of() -> None:
    for days_offset in range(0, 22):
        as_of = GLOBAL_EPOCH_UTC + timedelta(days=days_offset)
        anchor, _ = resolve_global_epoch_anchor(as_of)
        assert anchor <= as_of


def test_epoch_index_zero_on_origin_date() -> None:
    anchor, idx = resolve_global_epoch_anchor(GLOBAL_EPOCH_UTC)
    assert anchor == GLOBAL_EPOCH_UTC
    assert idx == 0


def test_epoch_advances_on_cycle_boundary() -> None:
    before_boundary = GLOBAL_EPOCH_UTC + timedelta(days=CYCLE_DAYS - 1)
    on_boundary = GLOBAL_EPOCH_UTC + timedelta(days=CYCLE_DAYS)

    _, idx_before = resolve_global_epoch_anchor(before_boundary)
    anchor_on, idx_on = resolve_global_epoch_anchor(on_boundary)

    assert idx_before == 0
    assert idx_on == 1
    assert anchor_on == GLOBAL_EPOCH_UTC + timedelta(days=CYCLE_DAYS)


def test_deterministic_utc_same_input_same_output() -> None:
    as_of = _utc(2026, 5, 15, 12)
    a1, i1 = resolve_global_epoch_anchor(as_of)
    a2, i2 = resolve_global_epoch_anchor(as_of)
    assert a1 == a2
    assert i1 == i2


def test_naive_datetime_treated_as_utc() -> None:
    naive = datetime(2026, 3, 13, 0, 0, 0)
    aware = _utc(2026, 3, 13)
    anchor_naive, idx_naive = resolve_global_epoch_anchor(naive)
    anchor_aware, idx_aware = resolve_global_epoch_anchor(aware)
    assert anchor_naive == anchor_aware
    assert idx_naive == idx_aware


def test_non_utc_timezone_normalised() -> None:
    cet = timezone(timedelta(hours=2))
    as_of_cet = datetime(2026, 3, 13, 2, 0, 0, tzinfo=cet)  # == 2026-03-13 00:00 UTC
    anchor, idx = resolve_global_epoch_anchor(as_of_cet)
    assert anchor == _utc(2026, 3, 1)
    assert idx == 2


# --- validation state ---


def test_validated_epochs_return_confirmed() -> None:
    for anchor_date_str in ("2026-03-01", "2026-03-22", "2026-04-12"):
        y, m, d = (int(x) for x in anchor_date_str.split("-"))
        state = validation_state_for_anchor(_utc(y, m, d))
        assert state == VALIDATION_CONFIRMED, f"expected CONFIRMED for {anchor_date_str}"


def test_current_epoch_returns_holdout() -> None:
    state = validation_state_for_anchor(_utc(2026, 5, 3))
    assert state == VALIDATION_HOLDOUT

    state = validation_state_for_anchor(_utc(2026, 6, 14))
    assert state == VALIDATION_HOLDOUT


def test_boundary_epoch_2026_04_12_is_confirmed() -> None:
    state = validation_state_for_anchor(_utc(2026, 4, 12))
    assert state == VALIDATION_CONFIRMED


def test_epoch_after_boundary_is_holdout() -> None:
    state = validation_state_for_anchor(_utc(2026, 5, 3))
    assert state == VALIDATION_HOLDOUT
