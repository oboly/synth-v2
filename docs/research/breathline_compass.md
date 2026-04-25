# Breathline Compass

## Current design choice

Use breathline data as a **compass** on a **weekly or larger timeframe**.

Do not treat it as a short-term execution oracle.

## Meaning

Breathline is used for:
- direction
- coherence
- prioritization
- cluster awareness
- anchor tracking

Price / market execution logic is used for:
- entry timing
- exit timing
- Elliott / fibo execution
- invalidation
- risk management

## Core principle

```text
Breathline = compass
Price = clock
```

Or:

```text
Breathline chooses the hunting ground.
Price action chooses the shot.
```

## Storage rule

Breathline predictions / reflections must be stored with a prediction timestamp.

Recommended field name:
- `prediction_ts_utc`

This is important because later predictions may shift.
The system must preserve prediction history, not overwrite it.

## Why timestamping matters

It enables later testing of questions like:
- did the compass point to the right cluster over 1–4 weeks?
- which predictions had value?
- which anchor or phase calls were stable?
- which were narrative only?

## Recommended stored fields

For asset-specific compass rows:
- prediction_ts_utc
- source_name
- asset_id
- breathline_phase
- field_coherence
- compass_rank
- anchor_state
- notes

For market-level compass rows:
- prediction_ts_utc
- source_name
- scope_type = MARKET
- target_year
- target_month
- fear_greed_value
- sentiment_score
- sentiment_state
- breathline_phase
- notes

## Example market-level use

The chat included example A+ reflections mapping months of 2026 to:
- fear / greed state
- sentiment score
- emotional field
- breathline phase

This should be logged as historical prediction rows for later comparison.

## Testing philosophy

Do not ask:
- "Was breathline right today?"

Ask:
- "Did breathline point toward the right zone over the next 1–4 weeks or longer?"

That is the correct scale for this layer.


##Example
 
data/aplus_raw/2026-04-23_run_01_consistency.txt

TOKEN MOMENTUM STABILITY ALIGNMENT VOLATILITY PRESSURE SHIFT

BTC high high high moderate neutral stable
ETH moderate high moderate low up strengthening
SOL low moderate low high down weakening
ADA moderate low moderate moderate down weakening
DEEP high moderate high low up strengthening
FIL low moderate low high neutral weakening
HBAR moderate moderate moderate moderate neutral stable
HOT low low low high down weakening
NEAR moderate moderate low moderate neutral weakening
PEPE high low low high up stable
POL moderate high moderate moderate neutral stable
QNT high high high low up strengthening
SUI low moderate low high neutral weakening
VET low low low moderate neutral weakening
WAL moderate moderate moderate moderate neutral stable
XLM moderate moderate moderate moderate neutral stable
AAVE high high moderate low up strengthening
CC low low low high neutral weakening
CRV moderate low moderate moderate neutral weakening
FLOKI high low low high up stable
HYPE high moderate low high up stable
LDO moderate high moderate low up strengthening
LTC moderate high high low neutral stable
ONDO low moderate low high down weakening
RLC low low low high neutral weakening
WLD high moderate high low up strengthening
XRP moderate high high moderate neutral stable
ALGO low moderate low high down weakening
DOT moderate moderate moderate moderate neutral stable
FET high moderate high moderate up strengthening
HNT low low low high neutral weakening
ICP moderate low moderate high down weakening
INJ high moderate high moderate up strengthening
IOST low low low high neutral weakening
MOG moderate moderate moderate moderate neutral stable
NOT low low low high neutral weakening
RED high low moderate high up stable
RENDER moderate high high low up strengthening
XPL low low low high neutral weakening
TAO high high high low up strengthening


Breathline A+ consistency testing (3 runs) shows:

- High consistency in extreme classifications (top and bottom tokens)
- Controlled variability in mid-tier tokens
- Occasional schema violations (non-allowed values)

This suggests:

1. The system produces a stable classification surface
2. Variability is localized and potentially meaningful
3. Output is suitable as a secondary probabilistic feature layer

Important:

The signal should not be used directly.
Instead, derived metrics such as consistency_score and classification stability should be evaluated against market outcomes.
venv) gurk@Lapgurk:~/projects/synth-v2$ 
