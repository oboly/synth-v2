@AGENTS.md

# CLAUDE.md — Synth v2.6 Repo Instructions

## Role

You are assisting on Synth v2.6, a modular quantitative trading system.

Act as a precise system-level code reviewer and implementation assistant.

Prefer:
- robustness over cleverness
- clear layer boundaries
- deterministic logic
- minimal, scoped changes

## Hard architecture boundaries

selection_engine:
- market-only
- account-agnostic
- no balances
- no positions
- no orders
- no execution plans

decision_gate:
- account-aware permission layer
- checks balance, sleeve, position, active plan, open order, duplicate exposure
- produces allowed/blocked decision state or execution intent
- no market-regime logic
- no order placement

execution_planner:
- converts approved execution intent into execution plan
- decides passive vs urgent limit, laddering, tick placement, repricing controls, urgency, spread capture
- does not place orders
- does not call broker/exchange
- does not decide account permission
- does not bypass decision_gate

executor / agents:
- order handling only
- place/cancel/monitor orders
- write execution_event / order state
- no strategy logic
- no account allocation logic
- no target selection logic
- no fib/pro/profile interpretation

## Live trading

Live trading permission is NOT_GRANTED.

Do not:
- place live orders
- add live order paths
- patch live execution onto paper runtime
- bypass explicit live permission
- add broker calls to planner or research code

## Research boundary

Research/backtest/oracle tools may use future-aware data only in:

- src/research/
- src/backtest/
- research_*
- bt_*
- docs/research/

Future-aware data must never leak into:

- live selection_engine path
- decision_gate
- execution_planner runtime
- executor
- live inference

## Fib / exit profile rule

Pro Elliott/Fibo charts are harvest maps, not buy/sell buttons.

Correct flow:

asset_exit_profile candidate
-> decision_gate validates actual position / sleeve / permission
-> execution_planner builds passive / urgent / ladder plan
-> executor places / monitors orders only

asset_exit_profile:
- is candidate metadata only
- must not create orders
- must not bypass decision_gate
- must not instruct executor directly

## Current planner lane

The active safe lane is:

- src/execution_planner/contract_preview_v1.py
- src/execution_planner/run_execution_planner_contract_preview_v1.py

Contract preview rules:
- read-only
- no DB writes
- no executor calls
- no reservations
- no broker calls
- no live mode

## Code delivery preferences

Prefer full-file replacements or clearly scoped complete blocks.

Avoid:
- patchy cross-layer shortcuts
- hidden state
- implicit coupling
- broad rewrites
- touching unrelated files

Do not use `git add .`.

## Review focus

When reviewing diffs, check:

1. Layer-boundary violations
2. Accidental DB/executor/order coupling
3. Runtime permission bypasses
4. Live-trading leakage
5. Future-aware leakage
6. Deterministic validation
7. Minimality of change

Return:
- PASS / BLOCK
- issues
- minimal fixes only

## Claude Code Repository Integration

- State `agent=claude-code` in every final task report.
- Before editing files under `src/research/`, read and obey `src/research/AGENTS.override.md`.
- Treat direct task instructions as additional constraints, not replacements for repository architecture and safety rules.
- Do not push unless explicitly requested.
