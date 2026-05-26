# TODO — Strategy Candidates

## Status

Open design questions. No implementation yet.

## Source

```text
docs/research/strategy_candidate_horizon_buckets_v1.md
```

## Core rule

```text
Asset != strategy.
```

Correct selection unit:

```text
candidate = (
    asset,
    strategy_family,
    horizon_bucket,
    setup_context,
    validation_state,
)
```

## P2 — Horizon bucket design review

Status: open.

Tasks:

- Decide whether selection_engine should rank per horizon bucket independently.
- Specify how same-asset candidates conflict or reinforce each other.
- Specify how decision_gate resolves exposure when multiple active candidates target the same asset.
- Define graduation rules from `BREATH_CURVE_RESEARCH` to runtime-eligible candidate buckets only after validation.
- Preserve the rule: asset is not a strategy.

## P1 — Current strategy audit follow-up

Status: open.

Source:

```text
docs/research/current_strategy_audit_v1.md
```

Tasks:

- Start with same-window buy-and-hold baselines before evaluating strategy labels.
- Validate `selection_state` forward returns from replay tables, not operational table backfills.
- Validate `trade_setup_filter_v1` PASS/FAIL/reason buckets only from point-in-time replay rows.
- Keep `paper_advice_policy_v1` validation blocked until A+ Table 1 and zone context can be replayed point-in-time.
- Treat rotation preview as account-aware retrospective review only, not a selection strategy.

Boundary:

```text
Backtest outputs stay in synth_bt or data/research.
No forward-return fields in runtime tables.
No decision_gate, execution_planner, executor, broker, or order changes.
```

## P1 — Long-term regime classifier and dual-bucket research

Status: open research, but not next.

Long-term regime classifier:

- `market_regime_discovery_v1` is now the exploratory clustering baseline.
- Next readout belongs in `docs/todo/regime_research.md`.
- Build and validate a replay-safe regime classifier only after the discovered-regime review, symbol breath profile design, and regime interaction audit design are complete.
- Regime labels to backtest:
  - `SIDEWAYS_MARKET`
  - `BULL_MARKET`
  - `BEAR_MARKET`
  - `CRASH_MARKET`
  - `SUPER_BULL_MARKET`
  - `LIQUIDITY_ROTATION`

Dual bucket policy research:

- Backtest a dual bucket policy:
  - 50% long-term fibo target exposure
  - 50% short-term breath trading
- Compare with single-bucket variants and buy-and-hold baselines.

Super-bull / god-candle scenario:

- Backtest preselected long-term exposure versus waiting for short-term entry signal.
- Measure risk of missing a move if no prior exposure exists.
- Include drawdown, missed-move, and opportunity-cost metrics.

Scoring requirements:

- Do not choose strategies only by historical profit.
- Include sample size, profit factor, max drawdown, out-of-sample result, walk-forward result, regime stability, fee/slippage sensitivity, liquidity, and failure modes.

Boundary:

- Research/backtest only.
- Validated candidates may feed market-only candidate ranking later.
- User/account permissions still belong in user strategy profiles, decision_gate, and execution_planner.

Terminology rule:

- Use `breath` for rhythm / phase / waveform / cycle.
- Use `participation` for cross-asset participation.
- Avoid `breadth` unless a field name or prior artifact already uses it.

## P2 — `MACRO_DIP_BUDGET_MODE_V1`

Status: future portfolio/research lane. No runtime change.

Concept:

- Keep roughly `2/3` as long-cycle survivor exposure.
- Reserve roughly `1/3` as staged dip budget.
- Dip budget is not deployed across all `40+` assets.
- Deploy only into strongest survivor/reclaim candidates after a liquidity shock.

Staged tranches:

- early dip / first reclaim
- deeper real dip
- panic/liquidation dip
- reclaim reserve after higher low

Entry rule:

```text
flush -> reclaim -> retest holds
```

Execution discipline:

- do not buy first freefall
- do not wait only for perfect bottom
- do not chase vertical extension

Research use:

- external macro scenario only
- relative strength watch
- market-only validation
- no direct `BUY_READY`
- no runtime change
- no `selection_engine` change
- no `decision_gate` change
- no execution change

Candidate priority examples:

- tier 1: `BTC`, `ETH`, `LINK`, `ONDO`, `CC`, `SOL`
- tier 2: `HYPE`, `NEAR`, `WLD`, `SUI`, `PLUME`, `RED`, `QNT`, `XDC`, `HBAR`

Architecture boundary:

- macro scenario can inform dashboard/context only
- strategy layer may later measure relative strength and reclaim candidates
- `decision_gate` later decides whether dip budget may be used
- `execution_planner` later creates passive/retest plan
- `executor` remains disabled unless separately enabled

Boundary:

```text
external macro scenario -> dashboard/context/research watch only
```

Not:

```text
external macro scenario -> direct BUY_READY -> runtime deployment
```

## Boundary

```text
selection_engine may rank market-only candidates.
decision_gate resolves account-aware exposure/conflicts/sizing/permission.
execution_planner/executor do not contain candidate logic.
```

No direct buy/sell/order logic belongs here.

## P2 — Swing pullback 168h research lead

Status: research lead / not paper-ready.

Source:

```text
docs/research/strategy_candidate_registry_v1.md
```

Context:

The 72h/168h swing pullback variants produced strong per-symbol returns but failed global promotion due to:

```text
MIN_WINRATE_NOT_MET
MIN_POSITIVE_MONTH_RATIO_NOT_MET
WORST_MONTH_AVG_LOSS_EXCEEDED
```

Likely missing components:

- exit algorithm
- regime filter
- symbol-specific promotion layer
- parent-state logic review

Tasks:

- Keep the 168h branch as a research lead, not a live or paper candidate.
- Revisit only through explicit validation of exit logic, regime filtering, and symbol-specific promotion rules.
- Do not stage arena-v2 candidates through the older `swing_pullback_recovery_v5` contract.

## P3 — Legacy Synth v1 regime/strategy prior review

Status: parked research prior.

Source:

```text
docs/legacy_synth_v1_regime_strategy_priors.md
```

Tasks:

- Define a v2 `regime_selector` contract.
- Define a v2 `strategy_selector` contract.
- Build a research export with `asset_id`, `symbol`, `interval_code`, `asof_ts_utc`, `regime_code`, `candidate_strategy_family`, and `source_prior`.
- Validate old priors on current v2 feature/signal data.
- Only then consider selection_engine integration.

Boundary:

```text
Legacy priors are microscope data, not steering input.
Do not implement direct old Synth v1 strategy routing in live code.
No selection/advice/decision/execution changes without a separate reviewed task.
```
