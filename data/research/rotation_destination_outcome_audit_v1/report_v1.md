# Rotation Destination Outcome Audit V1

Research-only audit of rotation destination quality using historical paper-advice snapshots and forward candles.

## Scope

- Reads historical `paper_advice_observation`, `obs_market_candle`, `asset`, and historical A+ report rows.
- Does not write DB rows, call brokers, submit orders, or change runtime behavior.
- Forward returns are future-aware research outcomes and must stay inside research outputs.

## Run

- venue: `bitvavo`
- interval: `4h`
- from_ts: `2026-05-01T00:00:00Z`
- to_ts: `2026-05-31T23:59:59Z`
- sample_count: `9`
- event_count: `141`

## Summary By Confidence

| label | events | avg_24h | median_24h | positive_24h | avg_mae_24h | avg_mfe_24h |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| LOW_CONFIDENCE_DESTINATION | 120 | -0.527491 | 2.136772 | 57.0 | -5.466499 | 4.927935 |
| MARKET_ONLY_DESTINATION | 18 | 2.118171 | 2.105944 | 100.0 | -1.993403 | 7.082167 |
| MEDIUM_CONFIDENCE_DESTINATION | 3 | 2.448822 | 2.448822 | 100.0 | -1.287498 | 3.298571 |

## Key Reason Buckets

| label | events | avg_24h | median_24h | positive_24h |
| --- | ---: | ---: | ---: | ---: |
| APLUS_AVOID_OR_DISTORTED | 28 | 4.378122 | 5.516756 | 92.0 |
| CURVE_DOWN_PRESSURE | 87 | -1.230595 | 0.911946 | 58.62069 |
| CURVE_WEAK | 7 | -1.650538 | -6.759657 | 42.857143 |
| EXCLUDED_OR_LOW_CONFIDENCE_DESTINATION | 141 | -0.060128 | 2.136772 | 64.46281 |
| MARKET_ONLY_DESTINATION | 18 | 2.118171 | 2.105944 | 100.0 |
| MISSING_APLUS_CONTEXT | 43 | -2.235244 | -2.410853 | 39.534884 |
| STALE_APLUS_CONTEXT | 72 | 0.303512 | 2.136772 | 67.307692 |

## Safety

- db_writes: `0`
- broker_calls: `0`
- broker_writes: `0`
- order_submission: `0`
- live_orders: `0`
