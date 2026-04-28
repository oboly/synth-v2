# Paper Candidate Execution Planner Preview V1

## Layer

Research / paper-candidate planner preview.

## Purpose

Preview how staged paper candidates flow through:

```text
research_paper_candidate_signal
-> decision_gate
-> execution_planner
-> plan preview
```

This tool does not write plans and does not touch executor/order handling.

## Boundary

Allowed:

- read staged `VALIDATED` paper candidates
- run decision-gate preview logic
- fetch current reference price
- call `build_execution_plan`
- print plan preview

Forbidden:

- writing `decision_state`
- writing `execution_intent`
- writing `execution_plan`
- creating capital reservations
- calling executor
- placing orders

## Important caveat

This is not a historical execution backtest.

The staged candidate timestamps are historical, but the planner preview uses current database state for:

- sleeve equity
- active plans
- open positions
- open orders
- latest reference price

Historical planner replay requires account-state and price snapshots.

## Canonical smoke command

```bash
python -m src.research.run_paper_candidate_execution_planner_preview_v1 --database synth_bt --table research_paper_candidate_signal --signal-status VALIDATED --policy-name swing_pullback_recovery_v5 --account-id 1 --sleeve-code SWING_STRUCTURAL --limit 10
```

## Diagnostic regime override

By default, this preview does not invent planner context.

If staged candidates do not contain a planner-compatible execution regime,
`build_execution_plan` may return no plan with `SKIPPED_POLICY_DISABLED`.

For diagnostic testing only, the runner supports:

```bash
python -m src.research.run_paper_candidate_execution_planner_preview_v1 --database synth_bt --table research_paper_candidate_signal --signal-status VALIDATED --policy-name swing_pullback_recovery_v5 --account-id 1 --sleeve-code SWING_STRUCTURAL --execution-regime-override TREND_UP --limit 10
```

This override must not become the canonical production path. A real adapter must
receive planner-compatible regime context from upstream market/selection context.

## Regime adapter boundary

Execution planner preview expects staged paper-candidate rows to already contain `execution_regime_label`.

Default behavior uses the staged value and passes it through `decision_gate` as `regime_label_4h`.

`--execution-regime-override` is diagnostic only. It must not become the production path and must not hide missing staged regime context.
