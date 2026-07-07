# Pipeline Contracts — Synth v2

## Purpose

Canonical layer responsibilities, dependencies, and contract rules. This is the reference for architecture guard tests and implementation bundles.

## Core Rules

- Market observation is not trade permission.
- `MarketObserverSnapshot` is market observation, not trade permission.
- `decision_gate` is the **only** layer allowed to combine upstream market context with account state.
- Execution intent belongs only to `execution_planner`.
- Broker writes belong only to executor/agent order-handling modules.

## Layer Responsibilities

| Layer | Modules | Responsibility | Must not do |
|---|---|---|---|
| market_data | `src/market_data/` | Candles, price, volume, freshness, normalization | Account logic, strategy, ladders, orders |
| market_context / features | `src/market_context/`, `src/features/`, `src/measurement/` | Market-only features, navigation, canonical-regime forwarding, future observer aggregation | Account state, permission, plans, broker calls |
| selection_engine | `src/selection/` | Market-only ranking, setup classification, Strategy State interpretation | Account state, permission, execution, broker calls |
| decision_gate | `src/decision_gate/` | Only account-aware permission layer | Market-feature recomputation, execution planning, broker calls |
| execution_planner | `src/execution_planner/` | Proposed execution intent/plan after approval | Market-feature calculation, permission, broker calls |
| executor / agents | `src/executor/`, `src/execution/` | Broker/order handling, idempotency, audit, failures | Market scoring, feature calculation, strategy selection |
| UI / dashboard | `apps/`, `src/reporting/` | Prepared payload display and explicit manual actions | Hidden market logic, permission inference, broker writes |

## Canonical Flow

```text
market_data
  -> market_context / features
       -> MarketNavigationState
       -> canonical active-regime observation
       -> future sector/breadth observations
       -> future MarketObserverSnapshot
  -> selection_engine
       -> Strategy State / future HorizonStrategyState
  -> decision_gate
  -> execution_planner
  -> executor / agents
  -> broker / exchange
```

`market_observer` is an aggregate inside `market_context`; it is not a new execution layer. Strategy State is a market-only selection output, not a separate layer between selection and decision gate.

## Import and Account Boundaries

| Layer | Forbidden imports/dependencies |
|---|---|
| market_data | decision, planning, execution, broker, account, balance, orders, dashboard/apps |
| market_context / features | decision, planning, execution, broker, account, balance, orders, dashboard/apps |
| selection_engine | decision, planning, execution, broker, account, balance, orders |
| decision_gate | execution planner, executor, broker; market-feature builders |
| execution_planner | executor, broker, market-feature builders, selection/market context recomputation |
| executor / agents | selection, market-context builders, strategy scoring |
| UI / reporting | broker writes, executor submit/cancel, decision mutation, planner mutation |

No runtime module may import a shared contract from `src.research`; research code is not a neutral runtime-contract namespace.

## `MarketNavigationState`

Top-level symbol-level market-context aggregate. It is account-agnostic and market-only.

```text
symbol
navigation_regime
fib_map_state
fib_map_confidence
local_ma_atr_state
impulse_health_state
timing_state
freshness_state
warnings
computed_at_utc
```

`computed_at_utc` is ISO-8601 UTC.

## `MarketObserverSnapshot`

Future market-wide/cross-symbol aggregate. It does not replace `MarketNavigationState`.

It may aggregate canonical global/asset-class regime, BTC structure, ETH relative strength, alt breadth, sector rotation, per-symbol context, external-overlay references, freshness, warnings, and evidence references.

It must remain account-agnostic, market-only, evidence-linked, and descriptive.

It must not read account state, grant permission, emit buy/sell/sizing/allocation labels, create execution intent, call a broker, overwrite canonical regime, or silently treat external research as measured truth.

Canonical contract: `docs/architecture/market_observer_contract_v1.md`.

## Explicit-State Rule

Every candidate/card emits `MarketNavigationState`. Data problems use explicit sentinels:

```text
NO_DATA
STALE
LOW_CONFIDENCE
```

Do not return `None` for market navigation. Future observer snapshots apply the same rule: missing evidence downgrades freshness/confidence; it does not invent a conclusion.

## Navigation vs Permission

The following are observations only:

```text
navigation_regime = BULLISH
timing_state = PULLBACK_ENTRY_ZONE
timing_state = RECLAIM_CONFIRMED
rotation_observation_state = SELECTIVE_ROTATION
alt_breadth_state = EXPANDING_SELECTIVELY
```

They do not mean allowed to buy, submit an order, or permission granted.

## Fibo Lifecycle

Target lifecycle and fib-map lifecycle are separate. A completed/exhausted target does not erase market navigation. A stale/exhausted map may request a refresh, but a rebuild may not cancel, replace, or submit orders.

External maps remain overlays until a dedicated builder or validation lane establishes their relation to an internal map. A chart zoom change does not itself create a new map.

## Canonical Local States

`local_ma_atr_context` is local MA/ATR context, not Breathline. `breathline` is reserved for universal market-cycle/A+ phase context.

Examples:

```text
Local MA/ATR: ABOVE_MA, TESTING_MA, BELOW_MA, RECLAIMING_MA, EXTENDED_ABOVE_MA, SPIKE_COOLING
Impulse: HEALTHY_IMPULSE, EARLY_IMPULSE, EXTENDED_IMPULSE, BLOW_OFF_SPIKE, DISTRIBUTION_RISK, COOLING_PULLBACK, SECOND_BUMP_POSSIBLE, FAILED_RECLAIM
Timing: WAIT_FOR_PULLBACK, WAIT_FOR_BREAKOUT, WAIT_FOR_RECLAIM, RECLAIM_CONFIRMED, BREAKOUT_CONFIRMED, PULLBACK_ENTRY_ZONE, NO_CHASE_EXTENDED, TOO_LATE, FAILED_RECLAIM
```

## Live Safety

Market-context/docs/tests/rendering work must not deploy to Odroid, restart services, write public output, enable broker writes, submit/cancel orders, bypass `decision_gate`, or call broker APIs.

Live execution always requires explicit user action, broker-write permission, decision-gate re-check, idempotency, and executor boundary.

## Related Documents

- `docs/architecture/market_observer_contract_v1.md`
- `docs/architecture/external_research_overlay_contract_v1.md`
- `docs/architecture/multi_horizon_aplus_breathline_strategy_contract_v1.md`
