# Paper Candidate Ledger Preview V1

## Purpose

`run_paper_candidate_ledger_preview_v1.py` builds a read-only simulated paper ledger from staged paper candidate rows.

It creates deterministic `OPEN` and `CLOSE` preview events using point-in-time entry price plus simulated forward exit price and simulated net return from the research/backtest evaluation table.

## Boundary

Allowed:

```text
read staged paper candidate rows
read research/backtest evaluation rows
compute simulated trades
compute simulated OPEN and CLOSE events
print table or JSON output
```

Forbidden:

```text
no decision_state writes
no execution_plan writes
no live orders
no account balance mutation
no future-return fields outside research/backtest namespace
```

## Default candidate

```text
policy_name: swing_pullback_recovery_v5_24h_tactical
batch_id: arena_v2_24h_tactical_2026
signal_status: PROMOTION_CANDIDATE
hold_hours: 24
```

## Example

```bash
python -m src.research.run_paper_candidate_ledger_preview_v1 --limit 10 --output table
```

## Safety

This tool is research-only. It intentionally uses simulated future exit prices and future returns. It must not be imported by live runtime, decision gate, execution planner, executor, or agents.
