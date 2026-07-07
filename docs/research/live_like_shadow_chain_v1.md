## Live-Like Shadow Chain V1

`run_live_like_shadow_chain_v1.py` runs the full shadow vertical slice:

- `StrategyCandidate`
- `DecisionPreview`
- `ExecutionPlanPreview`
- `ShadowEvent`

This is orchestration of the existing preview adapters only.

## Purpose

The chain runner executes the four existing shadow-safe research runners in sequence and writes one aggregate chain summary.

`MarketObserverEvidencePreview` may be attached as an explicit opt-in,
research-only sidecar with
`--include-market-observer-evidence-preview`.

Default behavior remains the same:

- no DB read
- no evidence-preview attachment
- existing heartbeat invocation remains unchanged

It is not:

- paper trading
- live trading
- execution
- an executor path
- `MarketObserverSnapshot`

`no_order_submitted` must remain `true`.

## Sequence

1. Run `run_intraday_retest_reclaim_candidate_v1`
2. Capture candidate run dir
3. Run `run_live_like_decision_preview_v1`
4. Capture decision run dir
5. Run `run_live_like_execution_plan_preview_v1`
6. Capture execution-plan run dir
7. Run `run_live_like_shadow_event_v1`
8. Capture shadow-event run dir
9. Optionally resolve `MarketObserverEvidencePreview` as a sidecar using the
   emitted `StrategyCandidate.created_at_utc`
10. Write aggregate chain summary, manifest, and optional sidecar JSON

## Outputs

Default output root:

```text
data/research/live_like_shadow_chain_v1/
```

Per run:

```text
data/research/live_like_shadow_chain_v1/run_<UTC_RUN_ID>/
```

Files:

- `chain_summary_v1.json`
- `chain_summary_v1.jsonl`
- `manifest_v1.json`
- `market_observer_evidence_preview_v1.json` only when the sidecar opt-in is enabled

The four sub-runs keep writing to their own standard output roots.

The sidecar requires caller-provided canonical join inputs:

- `--canonical-asset-class`
- `--canonical-regime-interval` (default `4h`)

These values are caller-provided only. They are not inferred from symbol,
market, candidate timeframes, candle timestamps, or shadow-event timestamps.

## Architecture Boundary

| Layer | Role | Runtime permission |
|---|---|---|
| `StrategyCandidate` | Market-only candidate generation | No |
| `DecisionPreview` | Preview-only permission adapter | No |
| `ExecutionPlanPreview` | Preview-only execution-plan adapter | No |
| `ShadowEvent` | Shadow lifecycle/logging artifact | No |

Boundary rules:

- no broker private calls
- no broker writes
- no order submission
- no executor calls
- no live permission
- no decision gate bypass
- no execution-planner runtime changes
- no candidate/decision/execution/shadow state mutation from sidecar

`MarketObserverEvidencePreview` remains a descriptive sidecar only. It does not
gate the chain and does not attach to any existing candidate, decision,
execution-plan, or shadow dataclass.

## Safety

Manifest markers include:

- `db_writes=0`
- `broker_private_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`
- `executor_enabled=false`
- `account_tables_used=false`
- `no_order_submitted=true`

When the sidecar opt-in is enabled, the chain summary and manifest also record:

- `market_observer_evidence_preview_enabled`
- `market_observer_evidence_preview_status`
- `market_observer_evidence_preview_path`
- `market_observer_canonical_asset_class`
- `market_observer_canonical_regime_interval`
- `market_observer_db_reads`
- `market_observer_db_writes=0`

Unavailable canonical evidence (`NO_SOURCE`, `AMBIGUOUS`,
`MALFORMED_TAGS`, `DB_READ_ERROR`, `UNEXPECTED_ERROR`) is recorded in the
sidecar JSON and summary fields, while the four existing chain stages continue
unchanged.

## Next Step

This completes the live-like shadow chain.

The next possible step is a static shadow dashboard or report that reads the chain and sub-run artifacts together.

The sidecar does not promote `MarketObserverSnapshot` and does not introduce a
chain gate.

The next step is not executor enablement.
