# Paper Candidate Decision Gate Preview V1

## Layer

Research / paper-candidate adapter preview.

## Purpose

Read staged `research_paper_candidate_signal` rows and preview what the existing
`decision_gate` would return for a configured account and sleeve.

This tool does not write decisions, intents, plans, orders, or portfolio state.

## Boundary

Allowed:

- read staged VALIDATED paper candidates
- translate them into `SelectionInputRow` objects
- fetch account/sleeve duplicate state through `DecisionGateRepository`
- call `evaluate_selection_for_account`
- print preview results

Forbidden:

- writing `decision_state`
- writing `execution_intent`
- writing `execution_plan`
- calling executor
- placing orders

## Mapping

- `candidate_id` is used as preview-only `selection_state_id`
- `sleeve_fit_code` maps to `allowed_sleeves`
- `signal_status=VALIDATED` maps to setup filter `PASS`
- simulated horizon maps to `target_horizon`

## Canonical smoke command

```bash
python -m src.research.run_paper_candidate_decision_gate_preview_v1 \
  --database synth_bt \
  --table research_paper_candidate_signal \
  --signal-status VALIDATED \
  --policy-name swing_pullback_recovery_v5 \
  --account-id 1 \
  --sleeve-code SWING_STRUCTURAL \
  --limit 20
```

## Architectural note

This is the bridge preview only. A future real adapter must still route through
`decision_gate` and must not bypass `execution_planner`.

## Preview caveat

This tool is not a historical decision-gate backtest.

Candidate timestamps are historical, but account-aware context is read from the
current live/paper database state:

- sleeve state
- available equity
- active execution plans
- open positions
- open orders

A future historical decision-gate replay requires account-state snapshots.
