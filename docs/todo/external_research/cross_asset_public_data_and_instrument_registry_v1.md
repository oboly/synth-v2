# Cross-Asset Public Data and Instrument Registry v1

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- provider feasibility / instrument allowlist / neutral identity contract -> Issue #302

Unmigrated executable scope:
- none

## Status

```text
open P3 external/public-data feasibility
non-blocking
no broker or account integration
```

## Purpose

Own the source, provenance, identity, and ingestion boundary required to research metals, miners, and food/agriculture without coupling research to a broker.

## Scope

This lane owns:

- public-data provider feasibility and terms review;
- a reviewed 20–30 instrument candidate allowlist;
- explicit rejected products and reasons;
- neutral instrument identity and provider mappings;
- source timestamps, provenance, freshness policy, and session calendars;
- 1d candles and optional 4h candles only after quality acceptance;
- corporate-action, missing-bar, retry, rate-limit, and stale-source behavior;
- idempotent public observation writes.

Initial groups:

```text
METALS
MINERS
FOOD_AGRICULTURE
```

Initial product boundary:

```text
allowed: UCITS ETF, ETC/ETP, listed unleveraged equity or fund
excluded: futures, options, CFDs, leveraged/inverse products, short selling, margin
```

## Neutral identity contract

Minimum canonical metadata:

```text
instrument_key
canonical_name
asset_class
rotation_group
exposure_type
product_type
issuer
underlying_reference
exchange
listing_currency
price_currency
trading_timezone
provider_name
provider_symbol
broker_symbol optional
ibkr_con_id optional
isin optional
freshness_policy
```

Provider, broker, `conId`, and ISIN values are mappings. None is the global Synth identity by itself.

## Provider acceptance

A provider is accepted only after review of:

- Dutch/EEA accessibility and terms;
- stable symbols and historical depth;
- 1d coverage and any claimed 4h coverage;
- volume availability and meaning;
- exchange timezone and session handling;
- split/dividend/corporate-action treatment;
- rate limits and reliability;
- redistribution/dashboard permissions;
- absolute timestamps and deterministic provenance.

An unofficial package being able to download data is not acceptance.

## Output contract

```text
provider feasibility record
reviewed instrument registry
public candle/observation records
explicit stale, missing, rejected, and unmapped states
```

## Boundaries

```text
canonical market classification = not owned
account state                   = not read
broker calls                    = 0
broker writes                   = 0
order submission                = 0
selection_engine                = unchanged
decision_gate                   = unchanged
execution_planner               = unchanged
executor                         = unchanged
```

Any future authenticated IBKR integration requires a separate architecture and acceptance lane.