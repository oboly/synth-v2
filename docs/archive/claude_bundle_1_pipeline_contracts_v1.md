Status: Archived historical record
Active ownership: none
Current work: see canonical documentation / GitHub Issues
Archived by: docs/TODO cleanup Batch 4A

Canonical replacement: `docs/architecture/pipeline_contracts.md`
Guard tests: `tests/test_pipeline_contract_boundaries_v1.py`

---

# Claude Bundle 1 — Pipeline Contracts + Guard Tests v1

You are working in Synth v2.

## Task type

Contract / architecture / guard tests.

## Scope

Create the canonical pipeline contract foundation.

Implement:

1. `docs/architecture/pipeline_contracts.md`
2. executable market-context contracts/enums in the best existing location, or create:
   - `src/market_context/contracts_v1.py`
3. architecture guard tests in the nearest existing style, or create:
   - `tests/test_pipeline_contract_boundaries_v1.py`

## Non-goals

Do not:
- add new trading logic
- change Profit Plan behavior
- change FibNavigationMap behavior
- change dashboard rendering
- deploy
- restart services
- write to `/var/www/html`
- enable broker writes
- submit/cancel orders

## Architecture primer

Layers:

1. `market_data`
   - candles, ticker/current price, volume, freshness, symbol normalization

2. `market_context / selection_engine features`
   - market-only deterministic feature objects
   - owns MarketNavigationState, FibNavigationMap, BreathlineState, ImpulseHealthState, TimingState

3. `selection_engine scoring`
   - market-only ranking/classification

4. `decision_gate`
   - account-aware permission only

5. `execution_planner`
   - execution intent only

6. `executor / agents`
   - broker/order handling only

7. `UI / dashboard`
   - display payload and explicit manual actions only

## Required contracts

Add explicit contracts/enums for:

- MarketNavigationState
- FibNavigationMap contract reference or wrapper
- BreathlineState
- ImpulseHealthState
- TimingState

Unavailable states must be explicit:

- NO_DATA
- STALE
- LOW_CONFIDENCE

MarketNavigationState must always be representable for every candidate/card.

Navigation availability is not trade permission.

## Guard tests required

Tests must fail if market-context contracts/features import:

- account state
- balances
- open orders
- decision_gate
- execution_planner
- executor
- agents
- dashboard/view modules
- broker clients
- order submit/cancel functions

Also test:
- contracts are JSON-safe or trivially convertible to JSON-safe primitives
- rendering/dashboard code stays display-only where applicable

## Docs required

`docs/architecture/pipeline_contracts.md` must explain:

- layer responsibilities
- allowed dependencies
- forbidden dependencies
- navigation vs permission
- target lifecycle vs fib-map lifecycle
- always-emitted market navigation objects
- live safety rules

## Acceptance criteria

Pass if:
- docs created
- contracts created
- guard tests created
- tests pass
- no behavior changes
- no deploy/webroot/service changes

Fail if:
- market-context imports account/order/execution/dashboard
- dashboard starts calculating features
- decision_gate calculates market features
- executor gets market-feature logic

## Report required

Report:
- branch name
- files changed
- docs added/updated
- tests added
- tests run
- pass/fail
- known limitations
- confirmation: no deploy, no restart, no webroot write, no broker writes
