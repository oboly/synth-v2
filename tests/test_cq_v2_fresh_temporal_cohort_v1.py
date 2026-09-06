from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

CONTRACT = Path('config/research/cq_v2_fresh_temporal_cohort_v1.json')


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)


def test_fresh_cohort_dates_splits_and_label_maturity_gate() -> None:
    payload = json.loads(CONTRACT.read_text(encoding='utf-8'))
    first = _ts(payload['first_asof_ts_utc'])
    last = _ts(payload['last_asof_ts_utc'])
    asofs = [first + timedelta(days=i) for i in range(payload['expected_unique_asofs'])]

    assert len(asofs) == 45
    assert asofs[-1] == last
    assert first > _ts(payload['prior_consumed_terminal_asof'])

    expected = (
        ('discovery', 0, 26, 27),
        ('validation', 27, 35, 9),
        ('holdout', 36, 44, 9),
    )
    for name, start_i, end_i, count in expected:
        split = payload['split'][name]
        assert _ts(split['first_asof_ts_utc']) == asofs[start_i]
        assert _ts(split['last_asof_ts_utc']) == asofs[end_i]
        assert split['expected_unique_asofs'] == count

    assert payload['max_forward_horizon_hours'] == 24
    maturity = last + timedelta(hours=payload['max_forward_horizon_hours'])
    assert _ts(payload['final_label_maturity_ts_utc']) == maturity
    assert _ts(payload['final_holdout_evaluation_not_before']) == maturity
    assert payload['label_maturity_required_before_final_holdout'] is True
