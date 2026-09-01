# Market Rotation Pressure V1

## Status

Implementation-ready. The score engine, persistence contract, aggregate market state, storage schema, console projection, and focused tests are included in the same slice.

Per the #676 owner decision (see
`docs/architecture/rotation_pressure_v1_canonical_promotion_v1.md`), this
broad/regime V1 lane is promoted as the canonical `family=ROTATION`
production-safe market-evidence owner (evidence/reporting authority only —
no selection/decision/execution authority). It is no longer accurately
described as "research/shadow"; that label is retained below only as
historical creation-time context, not current status. #593's faster
C1/C2/C3 multi-horizon Rotation variants remain research-only and are not
affected by this promotion.

The top-screen light bar is a reporting follow-up. It reads this lane; it does not recompute or write pressure state.

## Purpose

Market Rotation Pressure V1 converts Synth-native 24h and 7d rotation observations into a transparent directional pressure score per market and an aggregate market-rotation state.

It answers:

- which assets show the strongest confirmed positive or negative rotation pressure?
- is the short-horizon move confirmed by the 7d horizon?
- is pressure accelerating, persistent, broad, selective, or concentrated?
- is the market context predominantly rotation-in, rotation-out, or mixed?

This is not a claim of verified capital inflow or outflow. Candle volume always includes both buyer and seller. The lane therefore uses the terms `ROTATION_IN` and `ROTATION_OUT` for inferred directional market pressure.

## Architecture Boundary

```text
obs_market_candle
  -> market_rotation_history_v1
  -> market_rotation_pressure_v1
  -> read-only reporting / Market Observer
  -> shadow outcome validation
  -> possible future feature-promotion proposal
```

The lane is:

- market-only;
- account-agnostic;
- canonical production evidence for `family=ROTATION` as of the #676 owner
  decision (originally created as research/shadow — see Status above);
- deterministic and versioned;
- append-only at the observation level.

It must not write to or bypass:

- `selection_engine`;
- `decision_gate`;
- `execution_planner`;
- executor or agents;
- broker, balance, position, account, or order state.

## Source Data

Required source tables:

- `market_rotation_snapshot_v1`;
- `market_rotation_observation_v1`.

A pressure snapshot requires one complete 24h and one complete 168h observation for the same `(venue, as_of_ts_utc, asset_id)`.

Assets missing either horizon are excluded with `excluded_missing_pair_count`. Missing data is never converted to a neutral zero score.

The upstream rotation-history lane already enforces candle coverage, baseline coverage, freshness, and non-zero baseline volume. Pressure V1 accepts only persisted eligible source observations.

## Score Range and Components

Every normalized component is in `[-100, +100]`. The weighted total is also bounded to that range.

| Component | Weight | Meaning |
|---|---:|---|
| 24h return | 25% | current direction and relative strength |
| 24h signed relative volume | 20% | current move confirmed by above-baseline turnover |
| 7d return | 15% | broader directional context |
| 7d signed relative volume | 10% | broader participation confirmation |
| acceleration | 15% | 24h move versus the 7d daily pace |
| market-relative | 10% | asset performance versus the cross-sectional market median |
| persistence | 5% | directional consistency over the previous six common snapshots |

```text
score_total =
    0.25 * score_return_24h
  + 0.20 * score_signed_volume_24h
  + 0.15 * score_return_7d
  + 0.10 * score_signed_volume_7d
  + 0.15 * score_acceleration
  + 0.10 * score_market_relative
  + 0.05 * score_persistence
```

## Factor Normalization

Absolute directional factors use zero-centered robust scaling:

```text
scale = max(median(abs(factor_values)), versioned_floor)
score = 100 * tanh(raw_value / scale)
```

Versioned floors prevent tiny moves in a quiet market from becoming artificial strong signals:

| Factor | Minimum scale |
|---|---:|
| 24h return | 1.0 percentage point |
| 24h signed relative volume | 0.15 log units |
| 7d return | 3.0 percentage points |
| 7d signed relative volume | 0.15 log units |
| acceleration | 1.0 percentage point |

This preserves absolute direction: when the whole market rises, all valid directional scores can remain positive. A purely cross-sectional rank would incorrectly force half the universe negative and flatten the market light bar.

Only the market-relative component uses deterministic tie-aware percentile midranks in `[-100, +100]`, because that component explicitly measures relative leadership rather than absolute direction.

## Signed Relative Volume

Volume does not have an intrinsic direction. Pressure V1 derives confirmation from price direction and above-baseline relative volume:

```text
signed_volume_factor =
    sign(return) * ln(min(relative_volume, 4.0))  when relative_volume > 1
    0                                             otherwise
```

Consequences:

- price up plus elevated volume contributes positive pressure;
- price down plus elevated volume contributes negative pressure;
- below-baseline volume contributes no directional volume evidence;
- flat price plus high volume is not silently labelled inflow;
- extreme relative-volume spikes are capped before ranking.

## Acceleration

```text
acceleration = return_24h - (return_7d / 7)
```

This compares current 24h performance with the average daily pace implied by the 7d move.

## Market-Relative Factor

```text
market_relative =
    return_24h - median(return_24h)
  + 0.35 * ((return_7d / 7) - median(return_7d / 7))
```

This prevents a broad market pump or selloff from making every asset look independently exceptional.

## Persistence

Persistence uses up to six previous common 24h/7d snapshots.

For each historical pair:

```text
raw_direction_pressure =
    0.70 * return_24h
  + 0.30 * (return_7d / 7)
```

A historical direction matching the current direction contributes `+1`; the opposite direction contributes `-1`; flat contributes `0`.

```text
persistence_score = mean(direction_matches) * 100
```

No available history produces `0`, meaning no persistence evidence. It does not pretend that persistence is confirmed.

## Per-Asset States

### Pressure state

```text
+60 .. +100  STRONG_ROTATION_IN
+30 ..  +59  ROTATION_IN
-29 ..  +29  NEUTRAL_OR_MIXED
-59 ..  -30  ROTATION_OUT
-100 .. -60  STRONG_ROTATION_OUT
```

### Phase state

Allowed states:

- `EARLY_REVERSAL_IN`
- `ACCELERATING_IN`
- `SUSTAINED_IN`
- `ROTATION_IN`
- `DISTRIBUTION_RISK`
- `COOLING_IN_UPTREND`
- `ACCELERATING_OUT`
- `SUSTAINED_OUT`
- `ROTATION_OUT`
- `BOUNCE_IN_DOWNTREND`
- `MIXED`

The numeric score controls ordering. The phase state explains the current 24h/7d relationship.

## Aggregate Market State

One aggregate row is produced per `(as_of_ts_utc, venue, model_version)`.

Measured fields include:

- median market score;
- positive, neutral, and negative counts;
- positive and negative breadth;
- acceleration versus the preceding pressure snapshot;
- 24h/7d confirmation;
- concentration of directional score in the top five assets;
- market direction;
- evidence-light count from 0 through 5.

### Market direction

The direction is `ROTATION_IN`, `ROTATION_OUT`, or `MIXED` based on the median score and the difference between positive and negative breadth.

### Concentration

For the dominant direction:

```text
top_five_share =
    sum(abs(score_total) of top five directional assets)
    / sum(abs(score_total) of all directional assets)
```

```text
<= 45%  BROAD
<= 65%  SELECTIVE
>  65%  CONCENTRATED
```

### Evidence lights

The read-only top bar may show up to five lights. Each light represents one explicit condition aligned with the current market direction:

1. meaningful median market score;
2. meaningful dominant breadth;
3. 24h and 7d confirmation;
4. aligned acceleration or persistence;
5. participation is not concentrated in only a few assets.

`MIXED` produces zero directional lights.

## Intended Reporting Projection

The reporting layer should render a compact bar such as:

```text
ROTATION PRESSURE  +38  ●●●●○  ACCELERATING  BREADTH 61%
Broad / 24h+7d confirmed
IN:  AERO +78  XLM +71  NEAR +66
OUT: APT  -74  HOT -61  IOST -54
```

The projection must read persisted pressure truth and must not duplicate scoring logic inside HTML, JavaScript, or reporting code.

Click-through detail should expose component scores, raw returns, relative volumes, pressure state, phase state, freshness provenance, and model version.

## Persistence and Idempotency

Tables:

- `market_rotation_pressure_snapshot_v1`;
- `market_rotation_pressure_observation_v1`.

The snapshot key is:

```text
(as_of_ts_utc, venue, model_version)
```

The observation key is:

```text
(pressure_snapshot_id, asset_id)
```

Repeat runs are idempotent. Same-hour reruns may add newly available paired assets and reconcile aggregate header fields. Existing per-asset observations are immutable.

## Runner Contract

```bash
python -m src.research.run_market_rotation_pressure_v1 --validate-only
python -m src.research.run_market_rotation_pressure_v1 --dry-run
python -m src.research.run_market_rotation_pressure_v1 --write-db
```

Optional explicit source anchor:

```bash
python -m src.research.run_market_rotation_pressure_v1 \
  --dry-run \
  --as-of-ts 2026-07-12T17:00:00Z
```

Without `--as-of-ts`, the runner selects the latest timestamp with both 24h and 168h source snapshots.

Console output includes:

- market direction and score;
- evidence lights;
- breadth;
- acceleration, confirmation, and concentration;
- top five rotation-in assets;
- top five rotation-out assets.

## Validation Plan

This lane remains shadow-only until historical outcome tests show incremental value.

Minimum outcome horizons:

- 4h;
- 12h;
- 24h;
- 7d.

Minimum measurements:

- forward return;
- MFE;
- MAE;
- invalidation-before-target rate where compatible market maps exist;
- hit rate by score bucket;
- incremental value over raw 24h return and raw relative volume;
- value of 7d confirmation, acceleration, persistence, and concentration independently;
- stability across broad pump, broad selloff, selective rotation, and low-liquidity regimes.

Promotion into `selection_engine` requires a separate explicit proposal. This implementation does not grant the score any trade permission or execution authority.

## Implementation Order

1. Pressure score engine and storage — this slice.
2. Deploy migration and run dry/write smoke against production candle history.
3. Schedule after `market_rotation_history_v1` hourly completion.
4. Add read-only dashboard light bar and click-through table.
5. Run historical and forward shadow validation.
6. Consider a separately reviewed selection-feature promotion only after evidence.
