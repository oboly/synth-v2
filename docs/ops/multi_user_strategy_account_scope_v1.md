# Multi-User Strategy / Account Scope v1

Synth is moving from a single-user cockpit toward future multi-user usage. This document defines where user, strategy profile, account, and query scope belong before code starts adding `user_id` broadly.

Core boundary:

- `selection_engine` is market-only and account-agnostic.
- `decision_gate` is the account-aware permission layer.
- `execution_planner` creates execution intent and sizing only.
- `executor` and agents handle orders.
- Market data and market-derived features are global and must not be duplicated per user.
- User/account scope begins only at advice, intent, decision, execution, or explicit strategy-profile configuration layers.

## Scope Model

### Global Market Layer

Global market data is shared by all users and accounts. It includes assets, candles, market price snapshots, normalized market features, signals, market breath, structural zones, and other exchange/asset observations.

This layer must not know about users, balances, positions, account permissions, or portfolio state.

### Global Research / Backtest Layer

Generic research and backtest outputs are global unless explicitly declared profile-specific. They score market behavior, strategy candidates, regimes, assets, horizons, and failure modes.

This layer may produce validated strategy candidates, but it must not grant account permission or execution permission.

### Strategy Candidate Registry

The strategy candidate registry is global. It records validated strategy-regime-asset-horizon buckets that passed research criteria.

It answers: "This market strategy candidate is valid enough to be considered."

It does not answer: "This user/account is allowed to trade it now."

### User Strategy Profile Layer

`user_strategy_profile` is the first explicit user preference/configuration layer. It decides which validated strategy buckets, venues, assets, horizons, risk modes, and sleeves are allowed for a user or account.

It filters the global strategy candidate registry into user/account-eligible strategy context.

### User / Account Advice Layer

Advice snapshots that are personalized for a user/account must carry user/account scope. This includes scoped paper advice, scoped live intent previews, and any dashboard/report that combines strategy profile, account state, or account permissions with market context.

Advice remains review context. It does not submit orders.

### Decision Gate

`decision_gate` is the account-aware permission layer. It must evaluate account-scoped state such as positions, balances, exposure, risk limits, permissions, and user strategy profile constraints.

No upstream market-only layer may bypass it.

### Execution Planner

`execution_planner` converts decision-approved context into execution intent, sizing, notional constraints, and order-planning details.

It is downstream of decision gate and must remain separate from market selection and research scoring.

### Executor

The executor and agents handle order state, broker calls, order submission, cancellation, reconciliation, and fills. This layer is always account/user scoped.

## Layers That Must Not Have `user_id`

Do not add `user_id` to global market or market-derived tables, including:

- `asset`
- `obs_market_candle`
- `feat_candle`
- `signal_state`
- `market_breath`
- `execution_zone_context`
- `selection_engine` outputs
- generic research/backtest outputs unless explicitly profile-specific

Rationale: these records describe market state, not user/account state. Duplicating them per user creates inconsistent markets, excess storage, and cross-user leakage risks.

## Layers That Must Have User / Account Scope

These layers must include user/account scope when they become multi-user:

- user strategy profiles
- user-specific advice snapshots
- live intent preview, if persisted or personalized
- decision gate outputs
- execution plans
- execution/order state
- portfolio/account snapshots
- any account-aware dashboard/reporting

Read-only account-aware dashboards must still filter by account/user. Read-only does not mean scope-free.

## Recommended Identifiers

Use explicit identifiers rather than inferring scope:

- `user_id`
- `trading_account_id`
- `strategy_profile_id`
- `strategy_candidate_id`
- `venue`
- `asset_id`
- `interval_code`
- `asof_ts_utc`

Use `venue`, `asset_id`, `interval_code`, and `asof_ts_utc` for market scope. Use `user_id`, `trading_account_id`, and `strategy_profile_id` only where user/account/profile scope is required.

## Query Discipline

Market-only queries:

- must not filter by `user_id`
- must not read account tables
- must not infer positions, balances, or permissions
- should use market identifiers such as `venue`, `asset_id`, `symbol`, `interval_code`, and `asof_ts_utc`

Account-aware queries:

- must always filter by `user_id` and/or `trading_account_id`
- must not rely on `asset_id`, `symbol`, or `venue` to infer account identity
- must keep account filters on the account-side of joins to market tables
- must prevent accidental cross-user leakage

Joins from account-aware tables to market tables are allowed only when the account side is already scoped. Example: a scoped position row may join to global latest price by `venue` and `asset_id`; the price row itself remains global.

Never duplicate market data per user.

## Strategy / Backtest Model

Backtests should score strategy-regime-asset-horizon combinations, not simply choose "best historical profit."

Scoring must include:

- sample size
- profit factor
- max drawdown
- out-of-sample result
- walk-forward result
- regime stability
- fee/slippage sensitivity
- liquidity
- failure modes

Validated strategy candidates can feed market-only candidate ranking. A `user_strategy_profile` then decides which validated buckets are allowed for a user/account.

`decision_gate` remains the account-aware permission layer. `execution_planner` handles sizing and notional constraints after decision approval.

## Example Flow

```text
global candles
-> market features
-> market regime / breath / zones
-> strategy-regime-asset-horizon candidate score
-> validated strategy registry
-> user strategy profile filter
-> user-specific advice / live intent preview
-> decision_gate
-> execution_planner
-> executor
```

## Explicit Anti-Patterns

Do not:

- add `user_id` to `obs_market_candle`
- add `user_id` to `selection_engine` outputs
- let `selection_engine` see balances, cash, or positions
- allow live intent preview to become order intent
- bypass `decision_gate` from strategy/backtest outputs
- query account tables without user/account filters
- choose strategies only by historical profit
- duplicate market data per user
- infer account identity from asset, venue, or symbol

## Migration Notes

The current single-user setup may later map to one default `strategy_profile_id`.

Current `trading_account_id=2` style runtime must eventually be tied to explicit user/account scope. The transition should be additive and explicit.

Avoid broad schema churn until a table-specific migration plan exists. Do not add `user_id` to existing market tables as a shortcut.

Recommended migration posture:

- introduce new scoped tables when scope is genuinely required
- leave global market tables global
- update account-aware queries to require explicit scope
- migrate dashboards one at a time
- add tests for query-scope discipline before enabling multi-user behavior

## Open Implementation Follow-Ups

- define `user_strategy_profile` table
- define `strategy_candidate_registry` table
- define user-scoped live intent preview table or view, if persistence is needed
- audit account-aware queries for required `user_id` / `trading_account_id` filters
- add tests that fail if account-aware queries omit scope
- keep market-only modules free of user/account imports
- define default single-user profile mapping for current runtime
- decide which existing advice tables remain global and which require scoped successors
