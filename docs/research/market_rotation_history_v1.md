# Market Rotation History V1

## Purpose

Market Rotation History V1 builds a Synth-native append-only dataset of price momentum and relative volume for all eligible Bitvavo EUR spot markets. Every value is derived from candles already present in `obs_market_candle`. No external provider is required for per-market rotation data.

A separate optional component fetches one global crypto-market context snapshot from CoinGecko per hourly run. Bitvavo volume is exchange-local; the global row records a broader macro reference without combining the two datasets.

This is a rotation/momentum-volume history. It is not verified fund-flow data and it is not execution logic.

## Boundary

- Research-only. Market-only. Account-agnostic.
- No `selection_engine`, `advice_engine`, `decision_gate`, `execution_planner`, or `executor` changes.
- No order logic, broker writes, or live/paper branching.
- No FK coupling to `account_asset`, `account_balance`, `trading_account`, or order tables.
- Dashboards and reporting layers may read these tables; they must not write back.

## Source Data

Table: `obs_market_candle`
Interval: `1h`
Venue: `bitvavo`
Fields used: `asset_id`, `open_ts_utc`, `close_ts_utc`, `close_price`, `volume_quote_eur`

**Universe query:**
```sql
SELECT a.asset_id, a.symbol, vm.market
FROM asset a
JOIN venue_market vm ON vm.base_asset_id = a.asset_id
WHERE a.is_enabled = 1
  AND COALESCE(a.is_tradeable, 0) = 1
  AND vm.venue = 'bitvavo'
  AND vm.quote_currency = 'EUR'
  AND vm.is_tradeable = 1
ORDER BY a.asset_id
```

## Snapshot Anchor

`as_of_ts_utc` = UTC wall-clock time floored to the nearest 1-hour boundary. This equals the `close_ts_utc` of the latest complete 1h candle.

## Horizons and Windows

For each eligible market and each horizon, candle windows are bounded by `close_ts_utc`:

| Horizon | Current window | Baseline window | Expected 1h candles each |
|---|---|---|---|
| 24h | `(as_of_ts − 24h, as_of_ts]` | `(as_of_ts − 48h, as_of_ts − 24h]` | 24 |
| 7d | `(as_of_ts − 168h, as_of_ts]` | `(as_of_ts − 336h, as_of_ts − 168h]` | 168 |

The baseline window is the preceding comparable window of equal length.

## Formulas

**Close-to-close price change:**
```
price_open       = close_price of the last candle in the baseline window
price_close      = close_price of the last candle in the current window
price_change_pct = (price_close − price_open) / price_open × 100
```

**Relative volume:**
```
quote_volume          = SUM(volume_quote_eur) over the current horizon window
baseline_quote_volume = SUM(volume_quote_eur) over the baseline window
relative_volume       = quote_volume / baseline_quote_volume
```
A value > 1.0 means current-window volume exceeds the baseline. It is a raw ratio, not a signal.

**Coverage:**
```
coverage_ratio = actual_candle_count / expected_candle_count
```
Computed independently for current and baseline windows.

## Eligibility Rules

A market is eligible for a given horizon only when all of the following pass:

1. At least one candle exists in the current window.
2. At least one candle exists in the baseline window.
3. `coverage_ratio(current) ≥ 0.90`
4. `coverage_ratio(baseline) ≥ 0.90`
5. `max(close_ts_utc in current) ≥ as_of_ts − 2h` (freshness)
6. `SUM(volume_quote_eur, baseline) > 0` (relative volume must be computable)

**Exclusion reason codes:**
```
NO_CURRENT_CANDLES
NO_BASELINE_CANDLES
LOW_CURRENT_COVERAGE:<ratio>
LOW_BASELINE_COVERAGE:<ratio>
STALE_DATA:<iso8601_ts>
BASELINE_ZERO_VOLUME
```

## Persistence and Idempotency

Three tables:

| Table | Keyed by | Write rule |
|---|---|---|
| `market_rotation_snapshot_v1` | `(as_of_ts_utc, horizon_h, venue)` | create-once header, then reconcile counts on same-hour reruns |
| `market_rotation_observation_v1` | `(snapshot_id, asset_id)` | `INSERT IGNORE` |
| `market_global_snapshot_v1` | `(as_of_ts_utc, provider_name)` | conditional — see below |

Observation rows remain append-only and idempotent. Same-hour reruns may add newly eligible observations and then reconcile the header counts so `eligible_market_count`, `excluded_market_count`, and `observation_count` always match the latest local computation plus the actual stored observation rows.

## Global Market Context (CoinGecko)

One optional CoinGecko `/global` fetch runs alongside each hourly rotation snapshot. It records global crypto-market totals that Bitvavo-local candle volume cannot show.

**Credential:** `COINGECKO_API_KEY` environment variable. Header sent: `x-cg-demo-api-key`. If the variable is absent, `source_status = SKIPPED_NO_CREDENTIAL` and all metric fields are NULL.

**Payload validation:** HTTP 200 is not sufficient for `AVAILABLE`. The payload must contain parseable finite values for:

- `total_volume.usd`
- `total_market_cap.usd`
- `volume_change_percentage_24h_usd`
- `market_cap_change_percentage_24h_usd`
- `market_cap_percentage.btc`
- `market_cap_percentage.eth`
- `updated_at`

`total_volume.usd` and `total_market_cap.usd` must be `> 0`. BTC and ETH dominance must be within `0..100`. Any empty, malformed, NaN, infinite, or out-of-range payload is persisted as `UNAVAILABLE` with `source_error_reason` prefixed by `INVALID_PAYLOAD`.

**Fields populated from CoinGecko `data.*`:**

| Column | Source field |
|---|---|
| `total_volume_24h_usd` | `total_volume.usd` |
| `volume_change_pct_24h` | `volume_change_percentage_24h_usd` |
| `total_market_cap_usd` | `total_market_cap.usd` |
| `market_cap_change_pct_24h` | `market_cap_change_percentage_24h_usd` |
| `btc_dominance_pct` | `market_cap_percentage.btc` |
| `eth_dominance_pct` | `market_cap_percentage.eth` |
| `provider_updated_at_utc` | `updated_at` (Unix timestamp → UTC datetime) |

**Global row write semantics:**

| Existing row status | New fetch result | Action |
|---|---|---|
| None | any | INSERT |
| `AVAILABLE` | any | no-op (immutable) |
| `UNAVAILABLE` or `SKIPPED_NO_CREDENTIAL` | `AVAILABLE` | UPDATE (promote) |
| `UNAVAILABLE` or `SKIPPED_NO_CREDENTIAL` | non-AVAILABLE | no-op |

An existing `AVAILABLE` row is never overwritten or downgraded. A malformed HTTP-200 payload is not treated as `AVAILABLE`, so null-metric `AVAILABLE` rows are never created.

## Transaction Ownership

Local rotation is the primary dataset. In `--write-db` mode:

- both requested horizons share one local transaction;
- snapshot headers and observation rows commit exactly once after both horizons succeed;
- any local horizon/header/observation failure rolls back all local writes.

Global context is optional and independent:

- local rotation commits before any global context persistence starts;
- provider failures (`UNAVAILABLE` or `SKIPPED_NO_CREDENTIAL`) are valid outcomes and still persist normally when the table is present;
- global schema or DB write failures never roll back already committed local rotation rows;
- global persistence failure is surfaced to operators via `GLOBAL_CONTEXT_TARGET_SCHEMA_MISSING` or `GLOBAL_CONTEXT_PERSIST_FAILED`, and the runner exits non-zero after the local commit.

**Separation:** Bitvavo per-market metrics and CoinGecko global metrics are stored in separate tables and are never combined into a composite score in v1. Later reporting may display them side by side for context; they remain independent primitives.

**Not a trade signal:** CoinGecko global metrics are provider context only. They are not fund-flow claims, not money-flow scores, and not execution logic.

## Runner

```
python -m src.research.run_market_rotation_history_v1 --validate-only
python -m src.research.run_market_rotation_history_v1 --dry-run
python -m src.research.run_market_rotation_history_v1 --write-db
```

| Mode | DB connection | DB writes |
|---|---|---|
| `--validate-only` | No | No |
| `--dry-run` | Yes (read-only) | No |
| `--write-db` | Yes | Yes |

Optional flags: `--venue` (default: bitvavo), `--as-of-ts` (ISO8601 UTC, default: current hour), `--horizon 24` or `--horizon 168` (default: both).

## Safety Markers

```
broker_private_calls=0  broker_writes=0  order_submission=0
live_orders=0  decision_gate=none  execution_planner=none  executor=none
```
