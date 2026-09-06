from types import SimpleNamespace

import pytest

from src.research import cq_v1_rejection_postmortem_v1 as p
from src.research import run_cq_v1_rejection_postmortem_v1 as runner


def row(obs, asof, split, horizon, cq0, balanced, anchor, y, *, asset_id=1, agg='AVAILABLE', asset='AVAILABLE'):
    return {
        'observation_id': obs,
        'asset_id': asset_id,
        'asof_ts_utc': asof,
        'split': split,
        'horizon': horizon,
        'mrp_state': 'POSITIVE',
        'mrp_aggregate_status': agg,
        'mrp_asset_status': asset,
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


def test_summary_preserves_split_and_compares_candidate_instability():
    per_asof = [
        {'split': 'discovery', 'candidate': 'cq_v1_balanced', 'horizon': '1h', 'outcome_metric': 'forward_return_pct', 'asof_ts_utc': '2026-01-01', 'spearman_delta': 0.2},
        {'split': 'discovery', 'candidate': 'cq_v1_balanced', 'horizon': '1h', 'outcome_metric': 'forward_return_pct', 'asof_ts_utc': '2026-01-02', 'spearman_delta': -0.1},
        {'split': 'discovery', 'candidate': 'cq_v1_anchor', 'horizon': '1h', 'outcome_metric': 'forward_return_pct', 'asof_ts_utc': '2026-01-01', 'spearman_delta': 0.1},
        {'split': 'discovery', 'candidate': 'cq_v1_anchor', 'horizon': '1h', 'outcome_metric': 'forward_return_pct', 'asof_ts_utc': '2026-01-02', 'spearman_delta': 0.05},
    ]
    got = p.summarize(per_asof)
    balanced = got['candidate_split_horizon']['cq_v1_balanced:discovery:1h']
    assert balanced['sign_counts'] == {'POSITIVE': 1, 'NEGATIVE': 1}
    assert balanced['adjacent_sign_flips'] == 1
    direct = got['balanced_vs_anchor']['discovery:1h']
    assert direct['balanced_minus_anchor_adjacent_sign_flips'] == 1
    assert direct['balanced_minus_anchor_negative_dates'] == 1


def test_coverage_missingness_is_explicit():
    rows = [
        row('a', '2026-01-01', 'discovery', '1h', .1, .2, .15, 1, asset_id=1),
        row('b', '2026-01-01', 'discovery', '1h', .2, None, None, 2, asset_id=2, agg='UNAVAILABLE_MRP_AGGREGATE', asset='UNAVAILABLE_MRP_ASSET'),
    ]
    got = p.coverage_missingness_rows(rows)[0]
    assert got['n'] == 2
    assert got['mrp_aggregate_missing_n'] == 1
    assert got['mrp_asset_missing_n'] == 1
    assert got['cq_v1_candidate_missing_n'] == 1


def test_asset_concentration_reports_top_share_and_hhi():
    rows = [
        row('a', '2026-01-01', 'discovery', '1h', .1, .2, .15, 1, asset_id=1),
        row('b', '2026-01-02', 'discovery', '1h', .2, .3, .25, 2, asset_id=1),
        row('c', '2026-01-02', 'discovery', '1h', .3, .4, .35, 3, asset_id=2),
    ]
    got = p.asset_concentration_rows(rows)[0]
    assert got['n'] == 3
    assert got['unique_assets'] == 2
    assert got['top_asset_id'] == 1
    assert got['top_asset_share'] == pytest.approx(2 / 3)
    assert got['asset_hhi'] == pytest.approx((2 / 3) ** 2 + (1 / 3) ** 2)


def test_bucket_stability_tracks_asset_membership_not_observation_identity():
    rows = []
    for asof, suffix in [('2026-01-01', 'a'), ('2026-01-02', 'b')]:
        for i in range(10):
            rows.append(row(f'{suffix}{i}', asof, 'discovery', '1h', i, i, i, i, asset_id=i + 1))
    got = p.bucket_stability_rows(rows)
    balanced = [r for r in got if r['candidate'] == 'cq_v1_balanced' and r['split'] == 'discovery' and r['horizon'] == '1h']
    assert len(balanced) == 1
    assert balanced[0]['top_jaccard'] == 1.0
    assert balanced[0]['bottom_jaccard'] == 1.0


def test_stratified_rows_pool_multiple_asofs_with_same_mrp_state():
    rows = [
        row('a', '2026-01-01', 'discovery', '1h', .1, .2, .15, 1, asset_id=1),
        row('b', '2026-01-01', 'discovery', '1h', .2, .3, .25, 2, asset_id=2),
        row('c', '2026-01-02', 'discovery', '1h', .3, .4, .35, 3, asset_id=3),
        row('d', '2026-01-02', 'discovery', '1h', .4, .5, .45, 4, asset_id=4),
    ]
    got = p.stratified_rows(rows)
    balanced = [r for r in got if r['candidate'] == 'cq_v1_balanced']
    assert len(balanced) == 1
    assert balanced[0]['split'] == 'discovery'
    assert balanced[0]['horizon'] == '1h'
    assert balanced[0]['mrp_state'] == 'POSITIVE'
    assert balanced[0]['n'] == 4
    assert 'asof_ts_utc' not in balanced[0]


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
