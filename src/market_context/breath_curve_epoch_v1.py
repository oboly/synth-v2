from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


GLOBAL_EPOCH_UTC = datetime(2026, 1, 18, 0, 0, 0, tzinfo=UTC)
CYCLE_DAYS = 21

EPOCH_VALIDATED_THROUGH = date(2026, 4, 12)
VALIDATION_CONFIRMED = "GLOBAL_EPOCH_HISTORICALLY_CONFIRMED"
VALIDATION_HOLDOUT = "CURRENT_EPOCH_HOLDOUT_UNVERIFIED"


def resolve_global_epoch_anchor(as_of_ts_utc: datetime) -> tuple[datetime, int]:
    """
    Return the latest global 21-day epoch anchor at or before as_of_ts_utc,
    plus its zero-based epoch index.

    Proven: all 48 research_breath_curve_policy_result rows (anchors 2026-03-01,
    2026-03-22, 2026-04-12) match this formula exactly with zero deviation.
    """
    if as_of_ts_utc.tzinfo is None:
        as_of_ts_utc = as_of_ts_utc.replace(tzinfo=UTC)
    else:
        as_of_ts_utc = as_of_ts_utc.astimezone(UTC)

    epoch_index = (as_of_ts_utc.date() - GLOBAL_EPOCH_UTC.date()).days // CYCLE_DAYS
    anchor_ts = GLOBAL_EPOCH_UTC + timedelta(days=CYCLE_DAYS * epoch_index)
    return anchor_ts, epoch_index


def validation_state_for_anchor(anchor_ts_utc: datetime) -> str:
    """
    GLOBAL_EPOCH_HISTORICALLY_CONFIRMED for epochs up to 2026-04-12 (backtested).
    CURRENT_EPOCH_HOLDOUT_UNVERIFIED for epochs after that date.
    This is a transparency label, not an availability gate.
    """
    if anchor_ts_utc.tzinfo is None:
        anchor_ts_utc = anchor_ts_utc.replace(tzinfo=UTC)
    else:
        anchor_ts_utc = anchor_ts_utc.astimezone(UTC)

    if anchor_ts_utc.date() <= EPOCH_VALIDATED_THROUGH:
        return VALIDATION_CONFIRMED
    return VALIDATION_HOLDOUT
