# Adaptive Fib Execution Offset v1

> **Migration pointer.** GitHub Issue
> [#224 — Build offline execution-offset replay dataset and policy contract](https://github.com/oboly/synth-v2/issues/224)
> owns "Follow-up Sequence" steps 1-2 below: building the offline
> near-miss/fill replay dataset and defining the versioned execution-offset
> policy contract.
>
> GitHub Issue
> [#317 — Add read-only preview and paper-validation for adaptive Fib execution-offset policies](https://github.com/oboly/synth-v2/issues/317)
> owns steps 3-4: read-only proposal preview integration and paper-execution
> validation with fee/slippage modelling.
>
> Step 5 (any later decision-gated runtime consumption) is explicitly
> deferred in the source text ("Only then consider...") and is contingent on
> the outcome of #317's validation. It is not independently executable today
> and is not filed as a separate Issue; it remains historical/design
> guidance until #317 produces evidence that would make it a bounded task.
>
> This file must not become a parallel status board for the migrated scope.
> The design/architecture sections below (selection_engine / decision_gate /
> execution_planner / executor split, V1 scope, policies, metrics, safety
> rules) are preserved as historical/design context.
>
> See `docs/development/github_issues_workflow.md`,
> `docs/todo/MIGRATION_FREEZE.md`, and
> `docs/development/github_issues_batch_2b_migration_v1.md`.
>
> ## GitHub Issue migration
>
> Status: migrated
>
> Operational status/priority is owned by GitHub Issues.
>
> Section ownership:
> - Follow-up Sequence steps 1-2 (dataset, policy contract) -> Issue #224
> - Follow-up Sequence steps 3-4 (preview integration, paper validation) -> Issue #317
> - Follow-up Sequence step 5 (decision-gated runtime consumption) -> no Issue required; contingent/deferred future step per source text, not yet executable
>
> Unmigrated executable scope:
> - none

Status: TODO

## Goal

Improve fill probability around canonical Fibonacci reload zones without changing the market thesis or bypassing architectural layers.

The current system already exposes canonical fib buy-zone levels and can propose `ADD_LIMIT_BUY` operations at those levels. This TODO adds a separate execution-research capability for choosing an execution price around the canonical level.

## Problem

Exact limit placement at a fib level can miss valid reversals when price turns slightly above the order. Placing every order mechanically below the fib makes that failure mode worse.

The system must distinguish:

- `ideal_market_level`: canonical market-only fib/SR level;
- `execution_price`: account-aware intended limit price derived from the canonical level;
- `zone_match_tolerance`: reporting/audit tolerance only, not an execution-price rule.

These concepts must not be conflated.

## Architecture

### selection_engine

Owns market-only setup quality and canonical levels.

Outputs, without account context:

- selected fib map and provenance;
- ideal fib/reload levels;
- confluence and invalidation context;
- volatility and liquidity observations when market-derived.

It must not choose an account-specific order price or position size.

### decision_gate

Owns account-aware permission only.

It may allow or block use of an execution-offset policy based on account configuration, risk state, stale data, open-order state, or other permission inputs.

It must not calculate the market level or submit orders.

### execution_planner

Owns execution intent.

It may transform an approved canonical level into an intended limit price using an explicit, deterministic offset policy.

Example:

```text
ideal_market_level = 38.20
execution_offset_pct = +0.18%
execution_price = 38.26876
```

For a buy order, a positive offset means placing slightly above the canonical fib to reduce missed fills. Negative offsets are allowed only when supported by the selected policy and evidence.

The planner must emit both the original level and all transformation inputs for audit.

### executor / agents

Own order handling only.

They consume the approved execution intent and must not recompute fibs, offsets, permissions, or sizing logic.

## V1 Scope

Implement an offline, read-only research and proposal layer first.

Inputs:

- canonical fib/reload level;
- symbol and market;
- side;
- market timestamp and horizon;
- recent volatility;
- spread and tick size where available;
- liquidity observations where available;
- historical candles/trades sufficient to evaluate touch, near-miss, fill, adverse excursion, and subsequent move.

Outputs:

- `ideal_market_level`;
- `execution_offset_pct`;
- `execution_price` rounded to valid tick size;
- `offset_policy_id` and version;
- evidence window and provenance;
- expected fill-rate delta versus exact-level placement;
- expected entry-price degradation;
- sample size and confidence state;
- fail-closed reason when evidence is insufficient.

No broker writes, live orders, or runtime activation are in V1.

## Initial Policies To Compare

1. `EXACT_LEVEL`
   - execution price equals canonical level.

2. `STATIC_BUFFER`
   - small fixed percentage above a buy level or below a sell level.
   - research baseline only; not a universal production default.

3. `VOLATILITY_SCALED_BUFFER`
   - deterministic fraction of recent ATR or equivalent volatility measure.

4. `LADDER_AROUND_LEVEL`
   - multiple explicit prices around the canonical level with fixed allocation weights.
   - requires account-aware sizing later and therefore must remain a planner concern after decision permission.

5. `ASSET_PROFILED_BUFFER`
   - per-symbol policy derived from sufficient historical evidence.
   - must fall back to a conservative global policy when sample quality is insufficient.

## Research Metrics

Compare policies on at least:

- fill rate;
- near-miss rate;
- average price improvement/degradation versus canonical level;
- maximum adverse excursion after fill;
- maximum favourable excursion after fill;
- target-hit rate after fill;
- invalidation-hit rate after fill;
- time to fill;
- stale-order exposure;
- sensitivity by asset, regime, timeframe, spread, and volatility bucket.

Optimisation must not maximise fill rate alone. A policy that fills everything by chasing price is invalid.

## Safety And Determinism

- Fail closed on stale or missing canonical market context.
- Never silently substitute current market price for the canonical level.
- Never derive offsets from account PnL or desired exposure inside `selection_engine`.
- Preserve exact decimal arithmetic and tick-size rounding rules.
- Persist policy version, input snapshot identity, and provenance.
- Separate offline learned parameters from runtime consumption.
- Any future runtime consumer requires explicit validation, decision-gate permission, tests, rollout evidence, and no direct broker coupling.

## Acceptance Criteria

- Exact-level behaviour remains available as the control policy.
- A reproducible replay compares at least exact, static-buffer, and volatility-scaled policies.
- Buy-side sign semantics are covered explicitly: placing below a fib is not treated as a fix for reversals occurring above the existing order.
- Results are segmented by symbol and market regime and include minimum sample thresholds.
- The execution planner contract carries both canonical level and transformed execution price.
- Reporting clearly distinguishes market level, proposed execution price, and matching tolerance.
- No changes are made to live execution, broker permissions, deployment, or account state.

## Follow-up Sequence

1. Build the offline near-miss/fill replay dataset and baseline report.
2. Define the versioned execution-offset policy contract.
3. Add read-only proposal preview integration.
4. Validate with paper execution and realistic fee/slippage modelling.
5. Only then consider decision-gated runtime consumption.
