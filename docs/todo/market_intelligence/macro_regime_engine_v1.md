# TODO — Macro Regime Engine v1

## Status

**future design / P3 research** — canonical macro inputs, classifiers, persistence, replay, and dashboard consumption are not implemented. This lane must remain market-only and account-agnostic.

## Sources

- `docs/architecture/market_observer_contract_v1.md`
- `docs/research/market_observer_measured_input_inventory_v1.md`
- `docs/research/canonical_regime_context_source_v1.md`
- `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md`
- FFG chart and rotation briefings supplied in chat on 2026-07-28; external research only, not canonical market truth.

## Current state / facts

- Synth already has crypto-native regime observations and partial BTC/ETH/alt evidence.
- Sector Rotation Engine v1 measures sector participation, relative strength, volume confirmation, persistence, liquidity quality, and proxy-rotation state.
- Synth does not yet have a canonical replay-safe macro series chain for DXY, metals, equities, semiconductors, oil, volatility, or broad crypto-market indices.
- External market commentary may propose turning points, but Synth must classify measured state rather than copy forecasts.

## Open tasks by priority

### P1 — Input inventory and provider contract

Define exact source, symbol, venue, interval, as-of, timezone, licensing, and freshness behavior for:

```text
DXY
Gold
Silver
WTI
Brent
NASDAQ Composite or NASDAQ-100
SOX / Philadelphia Semiconductor Index
S&P 500
Dow Jones
VIX
BTC dominance
ETH/BTC
TOTAL2
TOTAL3
stablecoin supply
measured ETF flows where legally and technically available
```

For each input record:

```text
canonical_series_code
source_provider
source_symbol
interval_code
asof_ts_utc
source_ts_utc
freshness_state
replay_support
licensing_status
fallback_policy
```

No provider may be selected only because a current/latest HTTP response is easy to fetch. Historical point-in-time reconstruction and source provenance are mandatory.

### P1 — Canonical macro snapshot contract

Define a versioned `MacroRegimeSnapshot` or equivalent market-observer-owned contract with:

- raw measured values;
- normalized returns and volatility;
- state components;
- confidence and coverage;
- freshness per component;
- source provenance;
- model version;
- no account or portfolio fields.

### P1 — Deterministic classifiers

Preregister and validate bounded state vocabularies such as:

```text
USD_STRENGTHENING
USD_EXHAUSTION
USD_WEAKENING

EQUITY_RISK_ON
EQUITY_EXHAUSTION
EQUITY_CORRECTION

SEMI_EXPANSION
SEMI_OVERHEATED
SEMI_CORRECTION

METALS_CORRECTING
METALS_BOTTOMING
METALS_EXPANDING

OIL_DISINFLATIONARY
OIL_INFLATION_PRESSURE
OIL_SUPPLY_STRESS
```

Every state requires:

- explicit thresholds or deterministic mapping;
- tie behavior;
- stale/no-data behavior;
- versioned constants;
- replay tests;
- explanation fields showing why the state was assigned.

Do not classify a predicted future top or bottom as current state.

### P2 — BTC and broad-crypto macro primitives

Add or canonicalize:

- BTC structure mapping from existing local MA/ATR and impulse-health sensors;
- alt breadth ratio, not only mean alt return;
- percentage of assets outperforming BTC and ETH;
- percentage of assets above selected moving averages;
- BTC dominance trend;
- ETH/BTC leadership;
- TOTAL2/TOTAL3 breadth and trend where a licensed provider is accepted;
- stablecoin supply change and measured ETF flows as separately typed public flow evidence.

Candidate BTC states may include:

```text
RANGE_STABLE
RANGE_UNRESOLVED
BREAKOUT_UP
BREAKDOWN_RISK
CAPITULATION
BOTTOMING
RECOVERY_CONFIRMING
```

`CAPITULATION` and `BOTTOMING` must be measured from preregistered evidence, not inferred from narrative commentary.

### P2 — Persistence and replay

- Add deterministic backfill/replay support.
- Measure state-transition stability and false positives.
- Preserve raw component values for audit.
- Prove current/as-of parity for identical inputs.
- Fail closed on stale, unavailable, or temporally inconsistent series.

### P3 — Read-only reporting

Expose macro states, confidence, freshness, and source timestamps through a read-only reporting contract. Dashboard implementation belongs in its own reporting lane and may consume only persisted accepted snapshots.

## Blockers / dependencies

- Provider and licensing review.
- Point-in-time historical availability.
- Canonical freshness rules.
- Accepted persisted Sector Rotation Engine snapshots are required before composite-regime research, but not before independent macro input inventory work.
- The future `backtest_capability_contract_v1.md` must govern replay claims.

## Boundary

```text
Owner: market observer / research analytics
Mode: research-only, market-only, account-agnostic
DB writes: deterministic macro analytics snapshots only after separate review
Broker writes: 0
Order submissions: 0
Execution impact: none
```

No live trading. No broker writes. No order submission. No `decision_gate` bypass. No `execution_planner` bypass. No executor shortcut.

## Non-goals

- Predicting a specific calendar-date market top or bottom.
- Treating external commentary as measured evidence.
- Directly changing asset eligibility, ranking, account permissions, position sizing, order plans, or execution.
- Combining macro, sector, catalyst, and narrative logic inside one unversioned classifier.
