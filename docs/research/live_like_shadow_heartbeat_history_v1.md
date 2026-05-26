## Live-Like Shadow Heartbeat History V1

`run_live_like_shadow_heartbeat_history_v1.py` renders a read-only history report for recent live-like shadow chain runs.

This runner reads local ignored run outputs only:

- `data/research/live_like_shadow_chain_v1/run_*/chain_summary_v1.json`
- `data/research/live_like_shadow_chain_v1/run_*/manifest_v1.json`

It is reporting only:

- read-only
- file-input/file-output only
- no DB writes
- no broker private calls
- no broker writes
- no order submission
- no executor calls
- no decision_gate changes
- no execution_planner runtime changes
- no live permission

## Purpose

This report measures state stability only across recent shadow-safe chain runs.

It shows:

- total runs
- first run timestamp
- latest run timestamp
- market and symbol from the latest run
- latest candidate, decision, and execution-plan states
- latest observed price
- per-state counts for candidate, decision, and execution-plan states
- `ENTRY_CANDIDATE`, `WAIT_RETEST`, `NO_CANDIDATE`, and `BLOCKED` counts
- state transition count across the ordered `(candidate_state, decision_state, execution_plan_state)` tuple
- latest 20 runs table
- latest safety markers

This is not performance validation yet.

The next step after this may be outcome validation, not executor enablement.

## CLI

```bash
python -m src.reporting.run_live_like_shadow_heartbeat_history_v1 --help
python -m src.reporting.run_live_like_shadow_heartbeat_history_v1 --output-html /tmp/live-like-shadow-history.html
python -m src.reporting.run_live_like_shadow_heartbeat_history_v1 --max-runs 50 --output json
```

Defaults:

- `--chain-root`: `data/research/live_like_shadow_chain_v1`
- `--max-runs`: `100`
- `--output-html`: `/tmp/live-like-shadow-history.html`
- `--output`: `table`

## Visible Banner

The HTML report includes this explicit banner:

- `Shadow history only.`
- `Not paper trading.`
- `Not live trading.`
- `No order was submitted.`
- `Executor is disabled.`

## Safety

The report surfaces the latest run safety markers directly:

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

Expected shadow-safe values remain:

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

This report is not paper trading, not live trading, and does not create an executor path.
