## Live-Like Shadow Chain V1

`run_live_like_shadow_chain_v1.py` runs the full shadow vertical slice:

- `StrategyCandidate`
- `DecisionPreview`
- `ExecutionPlanPreview`
- `ShadowEvent`

This is orchestration of the existing preview adapters only.

## Purpose

The chain runner executes the four existing shadow-safe research runners in sequence and writes one aggregate chain summary.

`MarketObserverEvidencePreview` is not attached to this chain yet. The current
chain remains limited to the four existing preview adapters above.

It is not:

- paper trading
- live trading
- execution
- an executor path

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
9. Write aggregate chain summary and manifest

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

The four sub-runs keep writing to their own standard output roots.

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

## Next Step

This completes the live-like shadow chain.

The next possible step is a static shadow dashboard or report that reads the chain and sub-run artifacts together.

Attaching `MarketObserverEvidencePreview` to the chain is a separate deferred
research step, not part of the current chain contract.

The next step is not executor enablement.
