"""Immutable read-only runner for #778 CQ v1 rejection post-mortem."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from src.research import cq_v1_discovery_validation_evaluator_v1 as frozen
from src.research import cq_v1_rejection_postmortem_v1 as post

RUNNER = 'run_cq_v1_rejection_postmortem_v1'
SAFETY = {
    'research_only': 1,
    'market_only': 1,
    'account_awareness': 0,
    'db_writes': 0,
    'model_retuning': 0,
    'candidate_selection': 0,
    'production_ranking_changes': 0,
    'runtime_activation': 0,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument('--population', required=True)
    p.add_argument('--outcomes', required=True)
    p.add_argument('--output-dir', required=True)
    return p.parse_args(argv)


def _csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text('', encoding='utf-8')
        return
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def run(args: argparse.Namespace) -> dict[str, Any]:
    out = Path(args.output_dir)
    if out.exists():
        raise ValueError(f'immutable output directory already exists: {out}')
    population = frozen.load_population(Path(args.population))
    outcomes = frozen.load_outcomes(Path(args.outcomes))
    paired = post.pair_rows(population, outcomes)
    per_asof = post.per_asof_rows(paired)
    stratified = post.stratified_rows(paired)
    buckets = post.bucket_stability_rows(paired)
    summary = post.summarize(per_asof)
    manifest = {
        'runner': RUNNER,
        'issue': 778,
        'parent_issue': 777,
        'source_issue': 684,
        'population_sha256': frozen.PINNED_POPULATION_SHA256,
        'outcomes_sha256': frozen.PINNED_OUTCOMES_SHA256,
        'population_rows': len(population),
        'outcome_rows': len(outcomes),
        'complete_paired_rows': len(paired),
        'per_asof_rows': len(per_asof),
        'stratified_rows': len(stratified),
        'bucket_stability_rows': len(buckets),
        'diagnostic_only': 1,
        **SAFETY,
    }
    out.mkdir(parents=True, exist_ok=False)
    _json(out / 'postmortem.json', {**summary, **SAFETY})
    _csv(out / 'per_asof.csv', per_asof)
    _csv(out / 'stratified_metrics.csv', stratified)
    _csv(out / 'bucket_stability.csv', buckets)
    _json(out / 'manifest.json', manifest)
    lines = [
        '# CQ v1 rejection post-mortem (#778)', '',
        'diagnostic_only=1',
        *[f'{k}={v}' for k, v in SAFETY.items()], '',
        'This report characterizes the already-rejected #684 model family.',
        'It does not tune, select, or authorize a replacement model.', ''
    ]
    (out / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print('STARTED ' + RUNNER, flush=True)
    print('SAFETY ' + ' '.join(f'{k}={v}' for k, v in SAFETY.items()), flush=True)
    try:
        m = run(args)
    except Exception as exc:
        print(f'FAILED {RUNNER} error={exc!r} db_writes=0 model_retuning=0', flush=True)
        return 1
    print(f"FINISHED {RUNNER} complete_paired_rows={m['complete_paired_rows']} per_asof_rows={m['per_asof_rows']} db_writes=0 model_retuning=0", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
