# Canonical Fib Zone Map Writer Preview V1

## Purpose

`canonical_fib_zone_map_writer_preview_v1` is the first deterministic,
market-only preview writer for `canonical_fib_zone_map_v1`.

It does not write to the DB.

It computes preview candidate rows from:

- `obs_market_candle`
- `asset`

and writes research outputs under:

`data/research/canonical_fib_zone_map_writer_preview_v1/`

The purpose is review first:

- can the repo generate explicit Entry Zone / Target / Invalidation / Current
  Leg rows from public candles only
- is the output understandable
- is provenance explicit
- is the algorithm deterministic

## Why This Exists

The dashboard is no longer allowed to use `paper_advice_observation` as a
strategy source.

That is correct, but it leaves a gap:

- Entry Zone
- Target
- Invalidation Level
- Current Leg

need a canonical market-only source.

This preview writer is the first deterministic candidate generator for that
source.

## Read-Only Boundary

This runner is:

- research-only
- market-only
- account-agnostic
- preview-only

It must not:

- write to the DB
- read `paper_advice_observation`
- read `selection_engine`
- read `decision_gate`
- read `execution_planner`
- read `executor`
- read account tables
- call broker/private APIs
- submit orders

`--write-db` is intentionally not supported in v1 preview.

## Inputs

The runner reads:

- `obs_market_candle`
- `asset`

Optional asset filtering is limited to obvious enabled/quote filters when those
columns exist.

## Algorithm Overview

For each symbol:

1. load the latest `N` candles for `(venue, interval)`
2. detect pivot highs and pivot lows using `swing_window`
3. choose the latest meaningful swing pair
4. classify leg direction
5. derive Entry Zone, Support/Reaction Zone, Targets, and Invalidation
6. emit a canonical preview row aligned to `canonical_fib_zone_map_v1`

## Swing Anchor Selection

Pivot detection:

- pivot low = candle low is the lowest low inside the local `swing_window`
- pivot high = candle high is the highest high inside the local `swing_window`

Latest meaningful swing pair:

- `UP` leg:
  - latest pivot high occurs after latest pivot low
  - choose a prior pivot low before that high
  - prefer larger range and more recent structure using a simple deterministic
    score
- `DOWN` leg:
  - latest pivot low occurs after latest pivot high
  - choose a prior pivot high before that low
  - prefer larger range and more recent structure using the mirrored score
- otherwise:
  - emit `INCOMPLETE`
  - set leg to `RANGE` or `UNKNOWN`

This is deterministic but intentionally simple.

## UP Leg Formulas

Given:

- anchor low = `L`
- anchor high = `H`
- swing range = `R = H - L`

### Entry Zone

Retrace from high back toward low:

- `entry_zone_low  = H - 0.618 * R`
- `entry_zone_high = H - 0.382 * R`
- `entry_zone_mid  = midpoint(low, high)`

Method:

`FIB_RETRACE_0382_0618`

### Support / Reaction Zone

Deeper retrace zone:

- `support_reaction_zone_low  = H - 0.786 * R`
- `support_reaction_zone_high = H - 0.618 * R`

Method:

`FIB_RETRACE_0618_0786`

### Targets

Deterministic extension convention:

- `target_t1        = L + 1.272 * R`
- `target_t2        = L + 1.618 * R`
- `target_extension = L + 2.618 * R`

Method:

`FIB_EXTENSION_1272_1618_2618`

This preview does not use local reaction high as `target_t1`.
It uses the first extension target for consistency.

### Invalidation

Deterministic buffer below the anchor low:

- `invalidation_level = L - 0.05 * R`

Method:

`ANCHOR_RANGE_BUFFER_5PCT`

## DOWN Leg Formulas

Given:

- anchor high = `H`
- anchor low = `L`
- swing range = `R = H - L`

### Entry Zone

Retrace upward from low toward high:

- `entry_zone_low  = L + 0.382 * R`
- `entry_zone_high = L + 0.618 * R`

### Support / Reaction Zone

Higher reaction band:

- `support_reaction_zone_low  = L + 0.618 * R`
- `support_reaction_zone_high = L + 0.786 * R`

### Targets

Downward extensions from the anchor high:

- `target_t1        = H - 1.272 * R`
- `target_t2        = H - 1.618 * R`
- `target_extension = H - 2.618 * R`

### Invalidation

Deterministic buffer above the anchor high:

- `invalidation_level = H + 0.05 * R`

## Output Fields

The preview rows align with `canonical_fib_zone_map_v1`:

- identity/status fields
- leg fields
- anchor fields
- Entry Zone fields
- support/reaction fields
- target fields
- invalidation fields
- optional distance fields
- freshness/provenance fields

The writer also emits:

- `provenance_payload`

which records:

- algorithm name
- swing window
- anchor indices
- bars since anchor end
- target/retrace multipliers
- optional `swing_pct_band`

## Swing Percentage

`swing_range_pct` is the canonical swing-size field.

This exact measured percentage is the field that should be used for:

- validation
- backtests
- optimization
- later threshold research

No swing category labels are used in v1.

V1 may also emit:

- `swing_pct`
- `swing_pct_band`

but these are derived display helpers only.

### `swing_pct_band`

If present, `swing_pct_band` is optional display metadata only:

- `<8`
- `8-25`
- `25-60`
- `>=60`
- `UNKNOWN`

It does not alter:

- Entry Zone
- Targets
- Invalidation
- `map_quality`

Any future banding must remain derived display metadata only and must not
replace raw measurement or drive strategy logic.

## Map Status

V1 uses:

- `ACTIVE` when a complete map is generated and source freshness is `FRESH` or
  `DELAYED`
- `STALE` when a complete map is generated but candle freshness is stale
- `INCOMPLETE` when leg/anchor/level structure cannot be generated cleanly

## Limitations

This is intentionally not optimized.

Known limitations:

- no DB writes
- no latest-view integration
- no backtest validation
- no regime join
- no primitive signal join
- no pattern detectors
- no symbol-specific tuning
- no Elliott / breath phase timing model integration
- no paper advice fallback

It is a first deterministic map generator for review only.

## Why `paper_advice_observation` Is Excluded

`paper_advice_observation` is legacy blackbox advice context.

It may be wrong and it is not a valid canonical source for:

- Entry Zone
- Target
- Invalidation Level
- Current Leg

This preview exists specifically to generate those values from public candles
instead.

## Why This Is Preview-Only

The output still needs review for:

- symbol coverage
- map quality
- freshness behavior
- sensible anchors
- sane target/invalidation placement
- replay usefulness

Only after that review should a later writer consider DB insertion into
`canonical_fib_zone_map_v1`.

## Future Path

Expected next steps after preview review:

1. inspect preview rows visually and statistically
2. refine deterministic anchor and invalidation conventions if needed
3. add coverage/freshness diagnostics
4. only then build a DB-backed writer for `canonical_fib_zone_map_v1`

That future writer must remain:

- deterministic
- market-only
- explicit-source
- explicit-provenance
- no legacy paper-advice fallback
