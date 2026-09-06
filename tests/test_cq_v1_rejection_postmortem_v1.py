from types import SimpleNamespace

import pytest

from src.research import cq_v1_rejection_postmortem_v1 as p
from src.research import run_cq_v1_rejection_postmortem_v1 as runner


def row(obs, asof, split, horizon, cq0, balanced, anchor, y):
    return {
        'observation_id': obs,
        'asset_id': 1,
        'asof_ts_utc': asof,
        'split': split,
        'horizon': horizon,
        'mrp_state': 'POSITIVE',
        'scores': {'cq_v0': cq0, 'cq_v1_balanced': balanced, 'cq_v1_anchor': anchor},
        'forward_return_pct': y,
        'mfe_pct': y,
        'mae_pct': -abs(y),
    }


def test_comparison_uses_identical_eligible_sample():
    rows = [
        row('a', '2026-01-01', 'discovery', '1h', 0.1, 0.2, 0.15, 1.0),
        row('b', '2026-01-01', 'discovery', '1h', 0.2, 0.3, 0.25, 2.0),
        row('c', '2026-01-01', 'discovery', '1h', 0.3, None, 0.35, 3.0),
    ]
    got = p.comparison(rows, 'cq_v1_balanced', 'forward_return_pct')
    assert got['n'] == 2


def test_summary_counts_temporal_sign_flip():
    per_asof = [
        {'candidate': 'cq_v1_balanced', 'horizon': '1h', 'outcome_metric': 'forward_return_pct', 'spearman_delta': 0.2},
        {'candidate': 'cq_v1_balanced', 'horizon': '1h', 'outcome_metric': 'forward_return_pct', 'spearman_delta': -0.1},
    ]
    got = p.summarize(per_asof)['candidate_horizon']['cq_v1_balanced:1h']
    assert got['sign_counts'] == {'POSITIVE': 1, 'NEGATIVE': 1}
    assert got['adjacent_sign_flips'] == 1


def test_mrp_state_uses_sign_only():
    assert p._mrp_state({'mrp_aggregate': {'market_score': -1}}) == 'NEGATIVE'
    assert p._mrp_state({'mrp_aggregate': {'market_score': 0}}) == 'ZERO'
    assert p._mrp_state({'mrp_aggregate': {'market_score': 1}}) == 'POSITIVE'
    assert p._mrp_state({}) == 'UNAVAILABLE'


def test_runner_rejects_existing_output_dir(tmp_path):
    args = SimpleNamespace(population='x', outcomes='y', output_dir=str(tmp_path))
    with pytest.raises(ValueError, match='immutable output directory already exists'):
        runner.run(args)


def test_safety_markers_are_non_tuning():
    assert runner.SAFETY['research_only'] == 1
    assert runner.SAFETY['db_writes'] == 0
    assert runner.SAFETY['model_retuning'] == 0
    assert runner.SAFETY['candidate_selection'] == 0
    assert runner.SAFETY['production_ranking_changes'] == 0
