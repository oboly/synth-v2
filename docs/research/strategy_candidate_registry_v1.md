# Strategy Candidate Registry V1

## Purpose

This document tracks strategy candidates that have passed research screening and may be promoted into paper-only evaluation.

This is research documentation only. It does not grant live trading permission.

---

## Candidate: swing_pullback_recovery_v5_24h_tactical

### Status

```text
candidate_state: PROMOTION_CANDIDATE
live_phase: PAPER_ONLY
intended_sleeve: TACTICAL_PULSE
strategy_family: swing_pullback_recovery_v5
```

### Canonical candidate config

```text
hold_hours: 24
max_per_snapshot: 1
cooldown_hours: 48
rank_max: 10
btc_prior_24h_min: -0.02
btc_prior_24h_max: 0.00
min_score: 0.52
score_notch_mode: exclude
```

### 2021 full-year bullrun validation

Window:

```text
from_ts: 2021-01-01 00:00:00
to_ts: 2022-01-01 00:00:00
```

Result:

```text
state: PROMOTION_CANDIDATE
trades: 69
symbols: 11
avg_return: 0.04325288
median_return: 0.00907519
winrate: 0.5942
profit_factor: 3.5789
valid_months: 11
positive_months: 7
worst_month_avg: -0.03165112
max_symbol_trade_share: 0.1884
```

Strong 2021 symbol leaders:

```text
HOT
ADA
XRP
AAVE
VET
```

### 2026 current-regime validation

Window:

```text
from_ts: 2026-03-20 00:00:00
to_ts: 2026-04-28 00:00:00
```

Result:

```text
state: PROMOTION_CANDIDATE
trades: 27
symbols: 20
avg_return: 0.03059917
median_return: 0.01003900
winrate: 0.7037
profit_factor: 4.5329
valid_months: 2
positive_months: 2
worst_month_avg: 0.02879737
max_symbol_trade_share: 0.1111
```

Strong 2026 symbol leaders:

```text
ALGO
XPL
TAO
FLOKI
```

### Interpretation

This candidate behaves as a tactical 24h rebound strategy.

The strategy is strongest when BTC has a mild prior 24h pullback:

```text
btc_prior_24h: -0.02 .. 0.00
```

This suggests the candidate captures altcoin recovery after BTC weakness rather than broad trend-following.

### Architectural placement

```text
selection_engine: market-only candidate selection
decision_gate: later account-aware permissioning
execution_planner: later passive-first order intent
executor: not involved
```

This candidate must not bypass decision_gate or execution_planner.

### Promotion rule

Allowed next phase:

```text
PAPER_ONLY
```

Not allowed yet:

```text
LIVE
CORE_STRUCTURAL
SWING_STRUCTURAL global deployment
```

### Open research follow-ups

The 72h/168h variants produced strong per-symbol returns but failed global promotion due to:

```text
MIN_WINRATE_NOT_MET
MIN_POSITIVE_MONTH_RATIO_NOT_MET
WORST_MONTH_AVG_LOSS_EXCEEDED
```

Likely missing components:

```text
exit algorithm
regime filter
symbol-specific promotion layer
parent-state logic review
```

The 168h branch remains a research lead, not a live or paper candidate.
---

## Research Lead: swing_pullback_recovery_v5_168h_swing

### Status

```text
candidate_state: RESEARCH_LEAD
live_phase: NOT_PAPER_READY
intended_sleeve: SWING_STRUCTURAL
strategy_family: swing_pullback_recovery_v5
hold_hours: 168
```

### Reasoning

The 168h branch shows alpha on the 2021 bullrun replay after fixing the worst-month loss threshold logic, but it is not ready for paper promotion as a global strategy.

```text
alpha_status: PRESENT
primary_blocker: EXIT_REGIME_TAIL_RISK
paper_status: BLOCKED
chart_debugger_status: DEFERRED_UNTIL_PAPER_OR_LIVE_FLOW
```

### Key Observation

```text
168h variant can pass promotion gates when max_worst_month_avg_loss >= 0.11,
but the trade distribution contains enough tail risk that exit/regime logic must be improved first.
```

### Design Rule

Symbol-level strength must not override global variant state directly.

```text
symbol_state = per-symbol diagnostic strength
global_variant_state = full strategy/config promotion state
```

The 168h branch remains a research lead, not a paper candidate.
---

## 2026-04-29 Horizon Sensitivity Review

### Paper-path trace

Existing staged paper-candidate path was traced successfully.

```text
policy_name: swing_pullback_recovery_v5
signal_status: VALIDATED
sleeve: SWING_STRUCTURAL
source_table: bt_selection_v2_replay_eval_horizon_v1
decision_state: BLOCKED_BALANCE
execution_intent: NONE
planner_action: DECISION_GATE_BLOCKED
reason: INSUFFICIENT_BALANCE
```

Interpretation: decision_gate correctly blocks account-invalid candidates, and execution_planner does not bypass decision_gate.

### Contract mismatch

The newer arena candidate is not yet staged in research_paper_candidate_signal.

```text
arena candidate:
  policy_name: swing_pullback_recovery_v5_24h_tactical
  candidate_state: PROMOTION_CANDIDATE
  intended_sleeve: TACTICAL_PULSE
  eval_table: bt_selection_v2_replay_eval_horizon_v2

existing staged candidate:
  policy_name: swing_pullback_recovery_v5
  signal_status: VALIDATED
  sleeve_fit_code: SWING_STRUCTURAL
  eval_table/source_table: bt_selection_v2_replay_eval_horizon_v1
```

These contracts must not be mixed. A later bridge may explicitly stage arena-v2 candidates into the paper-candidate contract.

### Horizon sensitivity conclusion

Supported hold horizons tested: 4h, 24h, 48h, 72h, 168h.

```text
2021 strict tail gate max_worst_month_avg_loss=0.05:
  24h: PROMOTION_CANDIDATE
  48h: WATCH, alpha present, blocked by worst-month loss
  72h: WATCH, weaker, blocked by worst-month loss
  168h: WATCH, strong alpha present, tail-risk too large
  4h: REJECTED, winrate too weak

2021 permissive tail gate max_worst_month_avg_loss=0.11:
  48h/72h/168h can promote only when tail-risk threshold is relaxed

2026 current window:
  24h: PROMOTION_CANDIDATE
  48h/72h/168h: REJECTED
```

Interpretation: the entry logic contains alpha. Longer-horizon branches mainly fail on exit, regime, or tail-risk, not on signal discovery.

### Decision

```text
24h tactical:
  keep as paper-candidate direction
  intended sleeve: TACTICAL_PULSE
  next required bridge: arena-v2 result -> paper_candidate_signal staging

48h / 72h:
  keep as research diagnostics only

168h:
  keep as RESEARCH_LEAD
  do not promote to paper
  requires exit/regime solution before reconsideration
```

### Explicit non-actions

```text
Do not add unsupported 96h/120h horizons yet.
Do not build chart debugger yet.
Do not allow symbol_state to override global_variant_state.
Do not stage arena-v2 candidates through the older swing_pullback_recovery_v5 contract.
```

---

## 2026-04-30 Paper Candidate Flow Audit

### Candidate

```text
policy_name: swing_pullback_recovery_v5_24h_tactical
policy_version: arena_v2_bridge_v1
candidate_state: RESEARCH_PROMOTION_CANDIDATE
signal_status: PROMOTION_CANDIDATE
intended_sleeve: TACTICAL_PULSE
batch_id: arena_v2_24h_tactical_2026
source_table: bt_selection_v2_replay_eval_horizon_v2
simulated_horizon_hours: 24
```

### Verified flow

```text
arena_v2 result
-> arena_v2 paper-candidate bridge
-> research_paper_candidate_signal
-> decision_gate preview
-> execution_planner preview
```

### Staging result

```text
rows_total: 27
symbols: 20
avg_simulated_net_return: 0.03245645
winrate: 0.7037
worst_simulated_net_return: -0.05584745762712
best_simulated_net_return: 0.20728521174401
execution_regime_label: TREND_UP
sleeve_fit_code: TACTICAL_PULSE
```

### Decision-gate preview result

With diagnostic balance gate opened:

```text
decision_state: WATCHLIST_PREPLAN_ALLOWED
execution_intent: PREPARE_PLAN
decision_reason: WATCHLIST_SETUP_FILTER_PASS
rows: 27 / 27
```

### Execution-planner preview result

```text
planner_action: PLAN_PREVIEW
desired_action: PREPARE_PLAN
plan_state: IDLE
target_fraction: 0.03300000
rows: 27 / 27
```

### Point-in-time reference-price audit

The execution-planner preview now uses the staged historical entry price from the replay/evaluation table instead of latest/live obs_market_candle price.

```text
reference_price_source: bt_selection_v2_replay_eval_horizon_v2.entry_close_price
audit_result: PASS
reference_price_mismatches: 0
```

This prevents historical paper-candidate previews from leaking current/live market prices into old candidate rows.

### Architectural status

```text
research bridge: PASS
paper staging: PASS
decision gate preview: PASS
execution planner preview: PASS
live execution permission: NOT GRANTED
```

The candidate is ready for paper-path simulation work, but not live trading.

---

## 2026-04-30 Future-Return Leakage Audit

### Scope

This audit checked that simulated future-return fields remain confined to research, backtest, staging, and read-only paper-preview tooling.

Relevant future-return fields:

```text
simulated_net_return
net_return_24h
gross_return_24h
forward_close_price_*
```

### Result

```text
future-return usage in research tools: PASS
future-return usage in backtest tools: PASS
future-return usage in decision_gate runtime: NONE
future-return usage in execution_planner runtime: NONE
future-return usage in executor/execution runtime: NONE
paper PnL preview read-only scan: PASS
compile checks: PASS
live execution permission: NOT_GRANTED
```

### Interpretation

`simulated_net_return` may be displayed by decision/planner preview tools as diagnostic context, but it must not affect:

```text
decision_state
execution_intent
target_fraction
reference_price_eur
order planning
live execution
```

The tactical 24h candidate remains eligible for paper-path simulation design, not live trading.

