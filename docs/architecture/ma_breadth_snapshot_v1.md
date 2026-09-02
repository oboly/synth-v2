# Canonical MA Breadth Snapshot v1

Issue: #310.  Owner: `src/features/ma_breadth_snapshot_v1.py`.  This is a
market-only, account-agnostic persisted producer.  It is distinct from
`market_breath_live_v1` (an ephemeral reporting-side return-alignment readout)
and from Rotation Pressure (a separate numeric evidence family).

```text
obs_market_candle + canonical publication cohort
-> candle_feat_builder SMA50 primitive
-> ma_breadth_snapshot_v1
-> future #617 evidence adapter
-> #315 reporting read-only consumption
```

The v1 universe is `publication_cohort_enabled_tradeable_venue_market`: global
account-agnostic `asset.is_publication_cohort`, `asset.is_enabled`,
`asset.is_tradeable`, and `venue_market.is_tradeable`, bound to venue. It
admits an asset only when it has exactly one eligible `venue_market` on that
venue. `obs_market_candle` is canonically keyed by
`(asset_id, venue, interval_code, open_ts_utc)` and carries no market, pair,
quote, or `venue_market_id`; #310 V1 therefore excludes ambiguous multi-market
assets rather than attributing one candle series to multiple markets. This
restriction remains until a canonical market-keyed candle source exists. Each
snapshot saves a deterministic SHA-256 of sorted `(asset_id, market, symbol)`;
that hash is part of its idempotent identity.

Candle/feature evaluation uses the sole vetted market for each
`(venue, asset_id)` candle identity. A caller supplying more than one market
for an asset fails closed. No usable exact-asof candle is `stale`; an exact-asof
series with fewer than 50 observations is `insufficient_history`. Duplicate
exact-asof candle rows within the canonical identity fail closed; dataframe order
is not a tie-breaker.

`asof_ts_utc` is an exact caller-supplied final-candle close timestamp.  The
producer never falls back to a later/latest row during replay.  An eligible
constituent with no exact-asof candle is `stale`; one with exact-asof data but
fewer than 50 final candles is `insufficient_history`. Ambiguous multi-market
assets are excluded before `eligible_count` is calculated. Only evaluated
constituents form the MA percentage denominator, while `coverage_pct` is
`evaluated_count / eligible_count` for that unambiguous universe. Zero evaluated constituents is
`INSUFFICIENT_DATA` and the percentage is null.

v1 primary truth is only `universe_above_sma50_count` and
`universe_above_sma50_pct`.  SMA50 is reused from the shared candle feature
builder; it is not reimplemented.  SMA150, SMA200, and bullish stack are not
retained because their shared canonical primitives have not been added.

Input interval is `4h`; lookback is `50 bars @ 4h`; effective horizon is
`UNKNOWN` rather than inferred from the moving average.  Freshness is also
`UNKNOWN`: no producer cadence or justified stale-after duration has been
accepted.  `created_at`, model identity/version, universe identity/version,
coverage, and data status are persisted in `ma_breadth_snapshot_v1`.

No labels, thresholds, colors, classifications, dashboard/UI behavior, or
synthetic consensus are produced here.  #617 may consume persisted raw values
through a future evidence adapter; #315 is presentation-only and must not
recompute them.  The runner is manual and fail-closed; no timer or runtime
activation is included in v1.
