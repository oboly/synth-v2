# Decision Gate v1

## Doel

De `decision_gate` is de account-aware permissionlaag tussen market-only selectie/setup filtering en execution planning.

Hij bepaalt per account en per sleeve:

- mag dit account nu iets doen met dit asset?
- zo ja: welke execution intent mag doorstromen?

Belangrijk:

- geen marktlogica hier
- geen trend/setup herbeoordeling
- geen orderlogica
- geen BTC-regime interpretatie
- alleen permission / duplicate / exposure / balance checks

## Plaats in pipeline

```text
selection_engine_v2
→ trade_setup_filter_v1
→ decision_gate
→ execution_planner
→ executor / agents
```

## Input

De decision gate gebruikt de latest effective selection/setup state:

- `selection_state`
- `selection_score`
- `priority_rank`
- `allowed_sleeves`
- `setup_filter_state`
- `setup_filter_reason`
- account/sleeve state
- duplicate state
- balance / available equity

## Output

- `decision_state`
- `decision_reason`
- `execution_intent`

## Core rules v1

### Selection eligibility

Allowed selection states:

- `WATCHLIST` only if `trade_setup_filter_v1` is `PASS`
- `PREPARE`
- `BUY_READY`

Other states produce:

```text
NO_ACTION / NONE
```

### Trade setup filter

`trade_setup_filter_v1` is market-only.

It may pass context-qualified WATCHLIST rows into decision gate.

Examples:

- `RANK_AND_MARKET_CONTEXT_OK`
- `MARKET_MARKUP_CANDIDATE`

It may block rows for market/setup reasons, for example:

- `MARKET_DAMAGE_RISK`
- `RANK_OUTSIDE_SWEET_SPOT`
- `ASSET_SUITABILITY_WEAK_SET_CANDIDATE`

### Duplicate prevention

Block if:

- active execution plan exists
- open position exists
- open order exists, once live order tracking is connected

### Sleeve check

Block if:

- sleeve does not exist
- sleeve is inactive
- requested sleeve is not allowed for the selected asset/state

### Balance check

Block if:

```text
available_equity_eur < min_available_equity_eur
```

## Intent mapping

```text
WATCHLIST + setup PASS → PREPARE_PLAN
PREPARE                → PREPARE_PLAN
BUY_READY              → PLACE_PASSIVE_LIMIT
```

## Market context correction

BTC prior 24h return is a temporary global regime proxy, not an asset-level comparison.

Positive BTC movement must not be treated as an automatic hard block. A strong BTC move can mean overheat in normal conditions, but it can also mark broad risk-on, alt expansion, structural repricing, or parabolic markup conditions.

Current rule direction:

- negative BTC shock can remain a damage/risk block
- positive BTC movement should route into market context / strategy interpretation
- future `market_context_engine_v1` should classify regimes such as `CALM_ROTATION`, `BROAD_RISK_ON`, `ALT_EXPANSION`, `PARABOLIC_MARKUP`, `BLOWOFF_RISK`, and `MARKET_DAMAGE`
- `decision_gate` remains account-aware permission only and must not contain market-regime logic
