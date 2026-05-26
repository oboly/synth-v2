## INTRADAY_RETEST_RECLAIM Candidate V1

`run_intraday_retest_reclaim_candidate_v1.py` is the first market-only candidate emitter for the live-like vertical slice.

It is research-only and shadow-safe.

- no broker private calls
- no broker writes
- no order submission
- no account tables
- no decision permission
- no execution intent

## Purpose

This runner emits one `StrategyCandidate` row from public Bitvavo market data only.

It is the first concrete step in the downstream path:

`StrategyCandidate -> DecisionPreview -> ExecutionPlanPreview -> ShadowEvent`

This runner stops at `StrategyCandidate`.

## Inputs

Public Bitvavo endpoints only:

- `/ticker/price`
- `/{market}/candles?interval=15m`
- `/{market}/candles?interval=1h`

No private API keys are used.

## CLI

```bash
python -m src.research.run_intraday_retest_reclaim_candidate_v1 \
  --market NEAR-EUR \
  --symbol NEAR \
  --venue bitvavo \
  --quote EUR \
  --strategy-instance-id near_intraday_retest_reclaim_v1 \
  --write-files
```

Arguments:

- `--market` default `NEAR-EUR`
- `--symbol` default `NEAR`
- `--venue` default `bitvavo`
- `--quote` default `EUR`
- `--strategy-instance-id` default `near_intraday_retest_reclaim_v1`
- `--base-url` default `https://api.bitvavo.com/v2`
- `--write-files` / `--no-write-files`
- `--output-root` default `data/research/intraday_retest_reclaim_candidate_v1`

## Market-State Reuse

V1 reuses the generic watcher-style market states:

- `IMPULSE_CONTINUATION`
- `WICK_REJECTION_PULLBACK`
- `SHALLOW_PULLBACK_STRONG`
- `NORMAL_RETEST_ZONE`
- `DEEP_RETEST_ZONE`
- `NO_CLEAN_ENTRY`

These are descriptive public-market states only.

## Candidate-State Mapping

Base mapping:

- `IMPULSE_CONTINUATION -> IMPULSE_ACTIVE` or `WAIT_RETEST`
- `WICK_REJECTION_PULLBACK -> WAIT_RETEST`
- `SHALLOW_PULLBACK_STRONG -> SHALLOW_RETEST_ACTIVE`
- `NORMAL_RETEST_ZONE -> NORMAL_RETEST_ACTIVE`
- `DEEP_RETEST_ZONE -> DEEP_RETEST_ACTIVE`
- `NO_CLEAN_ENTRY -> NO_CANDIDATE`

Upgrade to `ENTRY_CANDIDATE` only when:

- `15m` is shallow, normal, or deep retest
- `1h` is not clearly invalidated
- freshness is `FRESH`
- `risk_severity_score <= max_risk_severity_score`
- `confidence_score >= min_confidence_score`

If those checks fail, the runner emits the mapped descriptive candidate state instead of forcing entry readiness.

## Outputs

Default output root:

```text
data/research/intraday_retest_reclaim_candidate_v1/
```

Per run:

```text
data/research/intraday_retest_reclaim_candidate_v1/run_<UTC_RUN_ID>/
```

Files:

- `strategy_candidate_v1.json`
- `strategy_candidate_v1.jsonl`
- `manifest_v1.json`

## Safety Markers

Manifest markers:

- `db_writes=0`
- `broker_private_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`
- `account_tables_used=false`
- `mode=shadow`

## Interpretation

This runner does not:

- grant trade permission
- bypass `decision_gate`
- create execution instructions
- create orders

It is the market-only candidate side of the vertical slice and nothing more.

NEAR is the first example instance only. The logic is generic by market, symbol, venue, quote, and instance config.
