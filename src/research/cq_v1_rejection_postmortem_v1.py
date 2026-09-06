"""Explanatory-only CQ v1 rejection post-mortem for #778.

Consumes the already-opened frozen #684 population/outcomes read-only. This
module characterizes temporal instability and failure concentration only. It
does not scan weights, thresholds, features, or replacement formulas.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import sqrt
from statistics import mean
from typing import Any

from src.research import cq_v1_discovery_validation_evaluator_v1 as core

CANDIDATES = (core.CQ_V1_BALANCED, core.CQ_V1_ANCHOR)
OUTCOMES = core.OUTCOME_METRICS
HORIZONS = core.HORIZONS
SPLITS = core.ALL_SPLITS


def _num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    d = sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    return None if d == 0 else sum(a*b for a, b in zip(dx, dy)) / d


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = ((i + 1) + j) / 2.0
        for k in range(i, j):
            out[order[k]] = rank
        i = j
    return out


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    return None if len(xs) < 2 else _pearson(_ranks(xs), _ranks(ys))


def _spread(rows: list[dict[str, Any]], score: str, metric: str) -> float | None:
    eligible = [r for r in rows if _num(r['scores'].get(score)) is not None and _num(r.get(metric)) is not None]
    if len(eligible) < 2:
        return None
    ordered = sorted(eligible, key=lambda r: (_num(r['scores'][score]), r['observation_id']))
    k = max(1, len(ordered) // 10)
    lo = mean(float(r[metric]) for r in ordered[:k])
    hi = mean(float(r[metric]) for r in ordered[-k:])
    return hi - lo


def _mrp_state(pop: dict[str, Any]) -> str:
    agg = pop.get('mrp_aggregate')
    if not isinstance(agg, dict):
        return 'UNAVAILABLE'
    x = _num(agg.get('market_score'))
    if x is None:
        return 'UNAVAILABLE'
    if x < 0:
        return 'NEGATIVE'
    if x > 0:
        return 'POSITIVE'
    return 'ZERO'


def pair_rows(population: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    core.validate_identity(population, outcomes)
    by_id = {str(r['observation_id']): r for r in population}
    paired: list[dict[str, Any]] = []
    for o in outcomes:
        if str(o['status']) != 'COMPLETE':
            continue
        p = by_id[str(o['observation_id'])]
        paired.append({
            'observation_id': str(o['observation_id']),
            'asset_id': int(o['asset_id']),
            'asof_ts_utc': str(p['asof_ts_utc']),
            'split': str(o['split']),
            'horizon': str(o['horizon']),
            'mrp_state': _mrp_state(p),
            'mrp_aggregate_status': str(p.get('mrp_aggregate_status', 'UNKNOWN')),
            'mrp_asset_status': str(p.get('mrp_asset_status', 'UNKNOWN')),
            'scores': core.score_values(p),
            **{m: o.get(m) for m in OUTCOMES},
        })
    return paired


def comparison(rows: list[dict[str, Any]], candidate: str, metric: str) -> dict[str, Any]:
    eligible = [r for r in rows if _num(r['scores'].get(candidate)) is not None and _num(r['scores'].get(core.CQ_V0)) is not None and _num(r.get(metric)) is not None]
    y = [float(r[metric]) for r in eligible]
    c = [float(r['scores'][candidate]) for r in eligible]
    v = [float(r['scores'][core.CQ_V0]) for r in eligible]
    pc, pv = _pearson(c, y), _pearson(v, y)
    sc, sv = _spearman(c, y), _spearman(v, y)
    bc, bv = _spread(eligible, candidate, metric), _spread(eligible, core.CQ_V0, metric)
    return {
        'n': len(eligible),
        'pearson_delta': None if pc is None or pv is None else pc - pv,
        'spearman_delta': None if sc is None or sv is None else sc - sv,
        'spread_delta': None if bc is None or bv is None else bc - bv,
    }


def per_asof_rows(paired: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in paired:
        grouped[(r['split'], r['asof_ts_utc'], r['horizon'])].append(r)
    out: list[dict[str, Any]] = []
    for (split, asof, horizon), rows in sorted(grouped.items()):
        for candidate in CANDIDATES:
            for metric in OUTCOMES:
                d = comparison(rows, candidate, metric)
                out.append({'split': split, 'asof_ts_utc': asof, 'horizon': horizon, 'candidate': candidate, 'outcome_metric': metric, **d})
    return out


def stratified_rows(paired: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in paired:
        grouped[(r['split'], r['horizon'], r['mrp_state'], r['asof_ts_utc'])].append(r)
    out: list[dict[str, Any]] = []
    for (split, horizon, state, asof), rows in sorted(grouped.items()):
        for candidate in CANDIDATES:
            d = comparison(rows, candidate, 'forward_return_pct')
            out.append({'split': split, 'horizon': horizon, 'mrp_state': state, 'asof_ts_utc': asof, 'candidate': candidate, **d})
    return out


def coverage_missingness_rows(paired: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Describe frozen CQ-v1 feature availability without altering eligibility."""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in paired:
        grouped[(r['split'], r['asof_ts_utc'], r['horizon'])].append(r)
    out: list[dict[str, Any]] = []
    for (split, asof, horizon), rows in sorted(grouped.items()):
        total = len(rows)
        agg_available = sum(r['mrp_aggregate_status'] == 'AVAILABLE' for r in rows)
        asset_available = sum(r['mrp_asset_status'] == 'AVAILABLE' for r in rows)
        candidate_available = sum(_num(r['scores'].get(core.CQ_V1_BALANCED)) is not None for r in rows)
        out.append({
            'split': split, 'asof_ts_utc': asof, 'horizon': horizon, 'n': total,
            'mrp_aggregate_available_n': agg_available,
            'mrp_aggregate_missing_n': total - agg_available,
            'mrp_asset_available_n': asset_available,
            'mrp_asset_missing_n': total - asset_available,
            'cq_v1_candidate_available_n': candidate_available,
            'cq_v1_candidate_missing_n': total - candidate_available,
        })
    return out


def asset_concentration_rows(paired: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report concentration of COMPLETE paired rows by asset, split and horizon."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in paired:
        grouped[(r['split'], r['horizon'])].append(r)
    out: list[dict[str, Any]] = []
    for (split, horizon), rows in sorted(grouped.items()):
        counts = Counter(int(r['asset_id']) for r in rows)
        n = len(rows)
        top_asset_id, top_n = (counts.most_common(1)[0] if counts else (None, 0))
        shares = [(count / n) for count in counts.values()] if n else []
        out.append({
            'split': split, 'horizon': horizon, 'n': n,
            'unique_assets': len(counts),
            'top_asset_id': top_asset_id,
            'top_asset_share': None if not n else top_n / n,
            'asset_hhi': None if not n else sum(share * share for share in shares),
        })
    return out


def _bucket_members(rows: list[dict[str, Any]], candidate: str) -> tuple[set[str], set[str]]:
    eligible = [r for r in rows if _num(r['scores'].get(candidate)) is not None]
    if not eligible:
        return set(), set()
    ordered = sorted(eligible, key=lambda r: (_num(r['scores'][candidate]), r['observation_id']))
    k = max(1, len(ordered) // 10)
    return ({str(r['asset_id']) for r in ordered[:k]}, {str(r['asset_id']) for r in ordered[-k:]})


def _jaccard(a: set[str], b: set[str]) -> float | None:
    union = a | b
    return None if not union else len(a & b) / len(union)


def bucket_stability_rows(paired: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Measure adjacent-asof stability of candidate top/bottom ranked deciles."""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in paired:
        grouped[(r['split'], r['horizon'], r['asof_ts_utc'])].append(r)
    out: list[dict[str, Any]] = []
    for split in SPLITS:
        for horizon in HORIZONS:
            asofs = sorted(a for (sp, h, a) in grouped if sp == split and h == horizon)
            for candidate in CANDIDATES:
                prev_asof: str | None = None
                prev_lo: set[str] = set()
                prev_hi: set[str] = set()
                for asof in asofs:
                    lo, hi = _bucket_members(grouped[(split, horizon, asof)], candidate)
                    if prev_asof is not None:
                        out.append({
                            'split': split, 'horizon': horizon, 'candidate': candidate,
                            'previous_asof_ts_utc': prev_asof, 'asof_ts_utc': asof,
                            'bottom_bucket_n': len(lo), 'top_bucket_n': len(hi),
                            'bottom_jaccard': _jaccard(prev_lo, lo),
                            'top_jaccard': _jaccard(prev_hi, hi),
                        })
                    prev_asof, prev_lo, prev_hi = asof, lo, hi
    return out


def summarize(per_asof: list[dict[str, Any]]) -> dict[str, Any]:
    """Preserve split boundaries and directly compare balanced vs anchor instability."""
    summary: dict[str, Any] = {'candidate_split_horizon': {}, 'balanced_vs_anchor': {}}
    for split in SPLITS:
        for horizon in HORIZONS:
            candidate_stats: dict[str, dict[str, Any]] = {}
            for candidate in CANDIDATES:
                rows = [
                    r for r in per_asof
                    if r['split'] == split and r['candidate'] == candidate and r['horizon'] == horizon
                    and r['outcome_metric'] == 'forward_return_pct' and r['spearman_delta'] is not None
                ]
                rows = sorted(rows, key=lambda r: r['asof_ts_utc'])
                signs = Counter('POSITIVE' if r['spearman_delta'] > 0 else 'NEGATIVE' if r['spearman_delta'] < 0 else 'ZERO' for r in rows)
                seq = [0 if r['spearman_delta'] == 0 else (1 if r['spearman_delta'] > 0 else -1) for r in rows]
                flips = sum(1 for a, b in zip(seq, seq[1:]) if a and b and a != b)
                stats = {
                    'dates_with_metric': len(rows), 'sign_counts': dict(signs),
                    'adjacent_sign_flips': flips,
                    'mean_spearman_delta': None if not rows else mean(r['spearman_delta'] for r in rows),
                }
                candidate_stats[candidate] = stats
                summary['candidate_split_horizon'][f'{candidate}:{split}:{horizon}'] = stats
            b = candidate_stats[core.CQ_V1_BALANCED]
            a = candidate_stats[core.CQ_V1_ANCHOR]
            summary['balanced_vs_anchor'][f'{split}:{horizon}'] = {
                'balanced_minus_anchor_adjacent_sign_flips': b['adjacent_sign_flips'] - a['adjacent_sign_flips'],
                'balanced_minus_anchor_negative_dates': b['sign_counts'].get('NEGATIVE', 0) - a['sign_counts'].get('NEGATIVE', 0),
                'balanced_minus_anchor_mean_spearman_delta': None if b['mean_spearman_delta'] is None or a['mean_spearman_delta'] is None else b['mean_spearman_delta'] - a['mean_spearman_delta'],
            }
    return summary
