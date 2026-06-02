# Synth v2.15 Advice Route Contract v1

## 1. Purpose

This document defines the contract for the new Synth v2.15 advice route after runtime ownership, runtime freshness, and signal inventory have been clarified.

The route is:

```text
framework_context
-> synth_confirmation_context
-> strategy_interpretation
-> strategy_proposal
-> decision_gate later
```

This contract defines market-only interpretation surfaces.

It does not define:

- order logic
- account permission
- execution intent
- broker payloads
- order submission

Breath + Fibo comes first conceptually as the market framework.
Synth signals confirm.
Strategy interprets.
Decision gate later permits.
Execution planner later creates intent.
Executor later handles orders.
Dashboard remains read-only visibility.

## 2. Architecture boundary

Layer meanings:

- signals = evidence
- framework = Breath/Fibo market map
- strategy = interpretation
- proposal = market-only candidate
- decision_gate = account-aware permission
- execution_planner = execution intent
- executor = order handling
- dashboard = read-only visibility

Hard rules:

- The advice route must remain account-agnostic.
- The advice route must not read account balance, available cash, position size, current position quantity, or live orders.
- The advice route must not place, cancel, or replace orders.
- The advice route must not bypass `decision_gate`.
- The advice route must not include broker order payloads.
- `decision_gate` is the first account-aware permission layer.
- `execution_planner` is the first execution-intent layer.
- `executor` is the only order-handling layer.

Explicit anti-patterns:

- dashboard computes canonical advice
- strategy reads account state
- signal directly emits `BUY` / `SELL` permission
- proposal includes order payload
- external research becomes runtime signal without validation
- `advice_state`, `ranking_state`, or `paper_advice_observation` treated as primitive signal truth
- `market_damage`, `failed_breakout`, or `market_trigger` used as normalized runtime signals before such normalization exists

## 3. Route stages

### 3.1 framework_context

Inputs:

- Breath/Fibo research context if available
- fib zones / wave context if available
- external A+ / Martee context only when normalized and clearly marked external or research
- manual higher-timeframe map context if present

Output:

- `framework_bias`
- `framework_horizon`: `SHORT` / `MID` / `LONG` / `MIXED`
- `map_horizon`
- `source_interval`
- `anchor_interval`
- `target_zone_low`
- `target_zone_high`
- `invalidation_zone_low`
- `invalidation_zone_high`
- `framework_confidence_bucket`
- `research_context_flags`

Rules:

- Breath/Fibo comes first conceptually, but remains research-only until a reviewed lane promotes it.
- External A+ / Martee context may frame interpretation but must not become direct signal truth.
- `framework_context` may be sparse or partial and still remain valid as context.
- `framework_context` does not create trade permission.

### 3.2 synth_confirmation_context

Inputs from ACTIVE runtime evidence:

- `signal_engine_state`
- `feat_candle`
- `asset_interval_quality`
- `selection_state`
- `execution_zone_context`
- `trade_setup_filter_observation`
- `trade_setup_policy_preview_observation`

Optional aggregate context:

- `advice_state`
- `ranking_state`
- `paper_advice_observation`

Important:

- aggregate context is not primitive signal truth
- aggregate context may be used as supporting confirmation only

Output:

- `confirmation_state`: `CONFIRMS` / `CONFLICTS` / `MIXED` / `WEAK` / `UNKNOWN`
- `confirmation_strength_bucket`: `NONE` / `LOW` / `MEDIUM` / `HIGH`
- `freshness_state`
- `conflict_flags`
- `quality_flags`
- `runtime_source_flags`

Rules:

- `signal_engine_state` is the canonical live signal table.
- legacy `signal_state` must not be used here.
- freshness must respect eligible `feat_candle` snapshot coverage, not only newest raw candle timestamps.
- `selection_state`, `execution_zone_context`, and `trade_setup_filter_*` may strengthen or weaken confirmation, but must not silently become permission logic.

### 3.3 strategy_interpretation

Inputs:

- `framework_context`
- `synth_confirmation_context`

Output:

- `strategy_candidate`

Non-goals:

- not permission
- not sizing
- not order intent
- not account allocation

Strategy id format:

```text
{ACTION}*{HORIZON}*{SETUP}
```

In this contract, `*` means concatenation. Stored canonical ids remain stable uppercase underscore enums such as `SELL_SHORT_SPIKE`.

`ACTION`:

- `BUY`
- `SELL`
- `HOLD`
- `ROTATE`
- `WARN`

`HORIZON`:

- `SHORT`
- `MID`
- `LONG`

Examples:

- `SELL_SHORT_SPIKE`
- `BUY_SHORT_PULLBACK`
- `HOLD_MID_REL_STRENGTH`
- `SELL_MID_TARGET_BOX_TOUCH`
- `BUY_MID_RECLAIM`
- `HOLD_LONG_CORE_TREND`
- `ROTATE_LONG_LEGACY_EXIT`
- `WARN_SHORT_EXHAUSTION`

### 3.4 strategy_proposal_contract

Required fields:

- `proposal_id`
- `symbol`
- `created_at_utc`
- `route_version`
- `action`
- `horizon`
- `setup_id`
- `framework_bias`
- `framework_horizon`
- `confirmation_state`
- `confirmation_strength_bucket`
- `confidence_bucket`
- `entry_zone_low`
- `entry_zone_high`
- `target_zone_low`
- `target_zone_high`
- `invalidation_level`
- `source_interval`
- `anchor_interval`
- `map_horizon`
- `wave_degree` optional
- `freshness_state`
- `quality_flags`
- `conflict_flags`
- `research_context_flags`
- `source_refs`
- `account_awareness: false`
- `broker_write_allowed: false`
- `order_submission: false`
- `decision_required: true`

Forbidden fields:

- `account_balance`
- `available_cash`
- `position_size`
- `current_position_qty`
- `live_order_id`
- `broker_order_payload`
- `order_submit`
- `cancel_order`
- `replace_order`
- direct size instruction
- direct portfolio allocation permission

Interpretation:

- A strategy proposal is a market-only interpretation object.
- It is not a decision.
- It is not an execution plan.
- It is not an order preview payload.

## 4. Input source classification

| source_name | source_type | allowed_in_framework_context | allowed_in_synth_confirmation_context | allowed_in_strategy_interpretation | reason / notes |
| --- | --- | --- | --- | --- | --- |
| `signal_engine_state` | `PRIMITIVE_SIGNAL` | NO | YES | YES | Canonical live runtime signal truth. |
| `signal_state` | `LEGACY` | NO | NO | NO | Legacy / stale / not runtime-owned. |
| `feat_candle` | `PRIMITIVE_SIGNAL` | NO | YES | YES | Deterministic feature context and freshness gate for canonical signals. |
| `asset_interval_quality_snapshot` | `PRIMITIVE_SIGNAL` | NO | YES | YES | Quality and freshness confidence; not directional but active evidence quality input. |
| `selection_state` | `AGGREGATE_CONTEXT` | NO | YES | YES | Market-only candidate persistence, not primitive truth. |
| `execution_zone_context` | `AGGREGATE_CONTEXT` | NO | YES | YES | Market map context for reclaim / continuation / zone interpretation. |
| `trade_setup_filter_observation` | `AGGREGATE_CONTEXT` | NO | YES | YES | Market-only setup-quality context. |
| `trade_setup_policy_preview_observation` | `AGGREGATE_CONTEXT` | NO | YES | YES | Downstream preview layer; supporting context only. |
| `advice_state` | `AGGREGATE_CONTEXT` | NO | YES | YES | Optional supporting confirmation only; not primitive signal truth. |
| `ranking_state` | `AGGREGATE_CONTEXT` | NO | YES | YES | Optional supporting confirmation only; relative ordering layer. |
| `paper_advice_observation` | `AGGREGATE_CONTEXT` | NO | YES | YES | Paper/readout interpretation only; not canonical signal truth. |
| `Breath/Fibo` | `FRAMEWORK_CONTEXT` | YES | NO | YES | Conceptually first framework context; still research-oriented until promoted. |
| `A+ external context` | `RESEARCH_CONTEXT` | YES | NO | YES | External research / validation context only. |
| `Martee/Oracle semantics` | `RESEARCH_CONTEXT` | YES | NO | YES | External semantic framing only; not runtime signal truth. |
| `failed_breakout` | `EXCLUDED` | NO | NO | NO | Not normalized as active runtime signal yet. |
| `market_damage` | `EXCLUDED` | NO | NO | NO | Not normalized as active runtime signal yet. |
| `market_trigger` | `EXCLUDED` | NO | NO | NO | No active runtime normalized table identified. |
| `position_lifecycle_research` | `EXCLUDED` | NO | NO | NO | Account-aware research lane; must stay outside market-only signal truth. |

## 5. Promotion path

Strict downstream path:

```text
strategy_proposal
-> decision_gate
-> execution_planner
-> executor
```

`decision_gate` later owns:

- account balance
- current position
- allocation bucket
- available cash
- risk permission
- exposure conflicts

`execution_planner` later owns:

- limit or market intent
- ladder construction intent
- execution parameters
- order preview payload concept

`executor` later owns:

- broker interaction
- submit / cancel / replace
- live order lifecycle

Boundary rule:

- The advice route ends before account-aware permission begins.
- Nothing in this contract bypasses `decision_gate`.

## 6. Open design questions

- When does Breath/Fibo graduate from research context to a validated framework signal lane?
- How should `failed_breakout`, `market_damage`, and `market_trigger` be normalized without collapsing them into hidden dashboard logic?
- Should `advice_state` and `ranking_state` remain supporting aggregate confirmation layers, or should they later be deprecated in favor of a cleaner route?
- Should `paper_advice_observation` remain as a review surface only, or be narrowed further once the new route exists?
- How should strategy profiles and allocation buckets connect later at the `decision_gate` level without leaking account-aware logic upstream?
- How should proposals be displayed so dashboards remain read-only visibility instead of becoming canonical advice owners?
- How should framework sparsity be represented when Breath/Fibo context exists for only part of the universe or only part of the horizon map?
- How should stale external research context be shown without letting it masquerade as current market evidence?

## 7. Recommended Batch 4

Recommended next step:

- review this contract first
- then optionally create an implementation skeleton only
- no order logic
- no `decision_gate` integration
- no `execution_planner` integration
- no `executor` integration

Safe Batch 4 scope:

- typed proposal dataclasses or schemas only
- route-stage interface stubs only
- no DB writes unless explicitly approved
- no broker calls
- no account-aware inputs
