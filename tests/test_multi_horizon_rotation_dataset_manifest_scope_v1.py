from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.research.multi_horizon_rotation_dataset_builder_v1 import AssetCoverage
from src.research.run_multi_horizon_rotation_dataset_builder_v1 import coverage_fingerprint


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _coverage(asset_id: int, *, first: datetime, last: datetime) -> AssetCoverage:
    return AssetCoverage(asset_id=asset_id, first_close_ts=first, last_close_ts=last)


def test_coverage_fingerprint_is_order_independent_for_same_envelope() -> None:
    rows = [
        _coverage(2, first=BASE + timedelta(hours=1), last=BASE + timedelta(days=5)),
        _coverage(1, first=BASE, last=BASE + timedelta(days=4)),
    ]
    assert coverage_fingerprint(rows) == coverage_fingerprint(list(reversed(rows)))


def test_coverage_fingerprint_changes_when_frozen_envelope_changes() -> None:
    original = [
        _coverage(1, first=BASE, last=BASE + timedelta(days=4)),
        _coverage(2, first=BASE, last=BASE + timedelta(days=5)),
    ]
    changed_first = [
        _coverage(1, first=BASE + timedelta(minutes=15), last=BASE + timedelta(days=4)),
        original[1],
    ]
    changed_last = [
        original[0],
        _coverage(2, first=BASE, last=BASE + timedelta(days=5, minutes=15)),
    ]
    original_hash = coverage_fingerprint(original)
    assert coverage_fingerprint(changed_first) != original_hash
    assert coverage_fingerprint(changed_last) != original_hash
