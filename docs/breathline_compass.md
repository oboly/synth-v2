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
