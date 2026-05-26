## Live-Like Shadow Chain Static Dashboard V1

`run_live_like_shadow_chain_static_dashboard_v1.py` renders the latest live-like shadow chain run into one static HTML report.

It is reporting only:

- read-only
- file-input/file-output only
- no DB writes
- no broker/private calls
- no broker writes
- no order submission
- no executor calls
- no decision_gate changes
- no execution_planner runtime changes

## Inputs

Primary chain run dir:

```text
data/research/live_like_shadow_chain_v1/run_*/
```

Files read:

- `chain_summary_v1.json`
- `manifest_v1.json`

Linked run dirs are read when present:

- candidate: `strategy_candidate_v1.json`
- decision: `decision_preview_v1.json`
- execution-plan: `execution_plan_preview_v1.json`
- shadow-event: `shadow_event_v1.json`

## CLI

```bash
python -m src.reporting.run_live_like_shadow_chain_static_dashboard_v1 --help
python -m src.reporting.run_live_like_shadow_chain_static_dashboard_v1 --output-html /tmp/live-like-shadow-chain.html
python -m src.reporting.run_live_like_shadow_chain_static_dashboard_v1 --chain-run-dir data/research/live_like_shadow_chain_v1/run_<UTC_RUN_ID> --output json
```

Defaults:

- `--chain-run-dir`: latest `data/research/live_like_shadow_chain_v1/run_*`
- `--output-html`: `/tmp/live-like-shadow-chain.html`
- `--output`: `table`

## Report Content

The static page shows:

- market
- symbol
- candidate state
- decision state
- execution plan state
- `no_order_submitted`
- `observed_price` when available
- source run dirs
- safety markers

Visible banner text:

- `Shadow preview only.`
- `Not paper trading.`
- `Not live trading.`
- `No order was submitted.`
- `Executor is disabled.`

## Safety Markers

The report surfaces these markers directly from the chain summary/manifest:

- `db_writes`
- `broker_private_calls`
- `broker_writes`
- `order_submission`
- `decision_gate_changes`
- `execution_planner_changes`
- `executor`
- `executor_enabled`
- `account_tables_used`
- `mode`

Expected shadow-safe values:

```text
db_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
decision_gate_changes=0
execution_planner_changes=0
executor=none
executor_enabled=false
account_tables_used=false
mode=shadow
```

This is a preview surface only. It does not create paper trades, live trades, or any executor path.
