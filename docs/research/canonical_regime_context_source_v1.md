# Canonical Regime Context Source V1

## Purpose

This document records the existing canonical regime source that downstream
research and reporting must reuse.

It is not a new regime model.
It does not introduce new labels or thresholds.

## Search Result

Search scope used:

- `docs/`
- `src/`
- `db/`
- `scripts/`

Search terms used:

- `regime`
- `market_regime`
- `risk_regime`
- `macro_regime`
- `market_breath`
- `participation`
- `breadth`
- `rotation regime`
- `regime_state`
- `regime_bucket`
- `regime_asof`

Canonical source was found.

## Canonical Docs

- `docs/research/active_regime_observation_preview_v1.md`
- `docs/research/active_regime_observation_design_v1.md`
- `docs/research/regime_selector_backtest_v1.md`

## Canonical Source Code

- `src/regime/run_active_regime_observation_v1.py`

## Canonical DB Source

- table: `active_regime_observation`
- migration: `db/migrations/20260514_active_regime_observation_v1.sql`

## Canonical Fields

Allowed canonical fields:

- `asof_ts_utc`
- `source_candle_ts_utc`
- `asset_class`
- `global_regime`
- `global_regime_version`
- `asset_class_regime`
- `asset_class_regime_version`
- `global_class_regime`
- `validation_status`
- `validated_hypothesis_tags_json`

Downstream compatibility fields may be added, but canonical values must be
preserved as stored.

## Canonical Values

### `global_regime`

- `GLOBAL_UNKNOWN`
- `GLOBAL_BTC_BREAKDOWN`
- `GLOBAL_BTC_MILD_DECLINE`
- `GLOBAL_NEUTRAL`
- `GLOBAL_BTC_OVERHEATED`
- `GLOBAL_ROTATION_WINDOW`
- `GLOBAL_RISK_ON`

### `asset_class_regime`

- `CLASS_UNKNOWN`
- `CLASS_RISK_OFF`
- `CLASS_STRESS`
- `CLASS_OVERHEATED`
- `CLASS_LEADERSHIP`
- `CLASS_PULLBACK`
- `CLASS_LAGGARD`
- `CLASS_NEUTRAL`

### `global_class_regime`

Cross key:

- `global_regime|asset_class_regime`

Example:

- `GLOBAL_BTC_MILD_DECLINE|CLASS_STRESS`

### `validation_status`

- `H1_CONTEXT_VALIDATED`
- `OBSERVED_UNVALIDATED_CONTEXT`

## Row Grain And Scope

Row grain:

- one row per `(venue, interval_code, asof_ts_utc, asset_class, regime versions)`

Scope:

- market-only
- account-agnostic
- market-wide plus asset-class row per snapshot

This is not symbol-specific.
For symbol-level downstream use, the symbol must map to the canonical
`asset_class`, then read the latest row for that class.

## Interval And As-Of Logic

The source is interval-specific.

Required downstream join rule:

- use the event `venue`
- use the event `interval`
- map symbol to canonical `asset_class`
- select the latest `active_regime_observation` row at or before `event_ts_utc`

Do not forward-fill beyond documented source behavior.

## Freshness

Canonical docs define `asof_ts_utc` and `source_candle_ts_utc`, but they do not
define a downstream freshness threshold for historical joins.

Therefore downstream historical enrichment may expose:

- `regime_asof`
- `source_candle_ts_utc`
- `regime_freshness=UNKNOWN`

until a canonical freshness rule is documented.

## Boundary

This regime source is:

- market-only
- account-agnostic
- no paper/live distinction
- no broker calls
- no orders
- no decision permission
- no execution intent

It must not be replaced by A+ context, market breath labels, or ad-hoc
supportive/neutral/damaged substitutes unless canonical regime research itself
changes.
