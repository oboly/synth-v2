# Momentum / Flow Exhaustion Phase A Audit v1

Status: Phase A audit complete; no feature implementation
Issue: #306
Canonical location: `docs/research/momentum_flow_exhaustion_phase_a_audit_v1.md`
Audited baseline: `origin/main` at `47123a8e183b6d4e24425f3afad8d807ad496c58`
Scope: research-only, market-only, account-agnostic; no DB/runtime/broker mutation

## Decision

`BUILD_OHLCV_EXHAUSTION_PROXY_V0`

Synth already has enough canonical/reusable OHLCV and derived volume/volatility/rejection primitives to build a deterministic point-in-time **effort-vs-result exhaustion proxy v0** without adding a new market-data ingestion layer.

Synth does **not** currently have a canonical historical aggressor-side public-trade substrate sufficient to claim true buy/sell delta, cumulative volume delta (CVD), taker imbalance, or delta-based absorption. Any such v1 must first get a separate market-data foundation if a gurkdb schema/coverage check confirms the repo finding.

```text
OHLCV_PROXY_V0_FEASIBLE=1
CANONICAL_VOLUME_RATIO_EXISTS=1
CANONICAL_VOLUME_ZSCORE_EXISTS=1
CANONICAL_OBV_EXISTS=1
ATR_RANGE_PRIMITIVES_EXIST=1
REJECTION_WICK_CLOSE_POSITION_PRIMITIVES_EXIST=1
TRADE_COUNT_COLUMN_EXISTS=1
BITVAVO_CANDLE_BACKFILL_POPULATES_TRADE_COUNT=0
RAW_PUBLIC_TRADE_INGESTION_FOUND=0
AGGRESSOR_SIDE_HISTORY_FOUND=0
TRUE_DELTA_CVD_READY=0
REPLAY_OUTCOME_INFRA_REUSABLE=1
```

## Architecture conclusion

Correct flow:

```text
canonical OHLCV / accepted candle features
-> #306 research exhaustion v0
-> replay / ablation / outcome validation
-> separate reviewed promotion if supported
-> canonical market-context / selection_engine consumer
-> #277 reporting consumer
```

Forbidden shortcuts:

```text
OHLCV candle direction -> label as true buy/sell delta
#277 reporting -> calculate exhaustion thresholds
#686 morphology -> recompute exhaustion
#663 Fib Reach -> invent hard-coded exhaustion penalty
exhaustion state -> direct decision_gate / execution intent
```

`selection_engine` remains market-only and may consume a later promoted feature. `decision_gate`, `execution_planner`, and executor/agents are unchanged.

## Reusable primitive inventory

### 1. Canonical candle volume and price data

`obs_market_candle` is the common historical source across research and runtime readers. Repository code consumes at least:

```text
open_price
high_price
low_price
close_price
volume_base
volume_quote_eur
trade_count
open_ts_utc
close_ts_utc
interval_code
venue
asset_id
```

`src/asset_profile/repository.py` explicitly reads `volume_quote_eur` and `trade_count` from `obs_market_candle`.

The Bitvavo historical candle backfill in `scripts/backfill_bitvavo_ohlcv_v1.py` uses the public `/{market}/candles` endpoint, derives `volume_quote_eur = close_price * volume_base`, and currently writes:

```text
trade_count=None
```

Therefore `trade_count` must not be assumed historically populated merely because the column exists.

### 2. Existing volume primitives

`src/features/etl_candle_feat.py` already computes and persists/reuses:

```text
volume_ratio_20
volume_zscore_20
obv
obv_slope_5
dollar_volume_ratio_20
```

The implementation is explicit:

```text
volume_ratio_20 = volume / rolling_mean_20(volume)
volume_zscore_20 = (volume - rolling_mean_20) / rolling_std_20
OBV direction = sign(close_t - close_t-1)
```

These are reusable **volume/participation proxies**. OBV is not true aggressor flow and must not be renamed as delta/CVD.

`src/features/candle_feat_builder.py` exposes replay-friendly grouped candle primitives including rolling volume ratio, ATR, range percentage, moving averages, and momentum features. `src/research/ma_volume_candidate_features_v1.py` demonstrates the accepted pattern of cutting future candles before rolling feature construction.

### 3. Existing rejection / absorption-adjacent geometry

`src/features/rejection_event.py` already computes deterministic candle-geometry evidence including:

```text
sweep_down / sweep_up
reclaim_down / reclaim_up
sweep_distance_atr
reclaim_strength
wick_ratio
close_position
volume_ratio
```

These are directly relevant to an OHLCV exhaustion proxy, especially effort-with-rejection and failed price progress. They are not true order-book/trade absorption because no aggressor-side flow is present.

`src/features/run_liquidity_event_feature.py` also uses wick/range/volume-normalized evidence. Reuse shared primitives where semantics match; do not create a third incompatible wick/range definition inside #306 without an explicit reason.

## v0 candidate measurement family

Phase B should implement raw measurements first, not a magic scalar first.

Candidate point-in-time measurements:

```text
directional_price_progress_atr
range_efficiency
close_progress_fraction
new_high_progress_atr
new_low_progress_atr
volume_ratio_20
volume_zscore_20
dollar_volume_ratio_20
obv_slope_5
upper_wick_fraction
lower_wick_fraction
close_position
rejection_strength_atr
follow_through_1b_atr
follow_through_nb_atr
```

Candidate derived effort/result quantities:

```text
buy_efficiency_proxy  = positive normalized price progress / normalized positive-side effort proxy
sell_efficiency_proxy = negative normalized price progress / normalized negative-side effort proxy
```

Direction attribution must remain explicitly **proxy semantics** because OHLCV cannot identify the actual initiating buyer/seller volume.

A first exhaustion state should require a bounded combination of:

```text
high or rising participation effort
+ falling directional price efficiency
+ rejection and/or poor close location
+ weak bounded follow-through
```

Buyer and seller sides must remain symmetric.

## v1 true order-flow audit result

Repository-wide search found no canonical raw public-trade ingestion, no aggressor/taker-side historical store, and no existing CVD/delta producer.

The Bitvavo candle ingestion path only fetches aggregated candles. Candle volume plus close direction is insufficient to reconstruct true:

```text
buy_volume
sell_volume
taker_buy_volume
taker_sell_volume
volume_delta
CVD
aggressor_imbalance
delta-based absorption
```

Phase A therefore rejects any implementation that infers these values from candle direction and labels them as order flow.

A read-only gurkdb schema/coverage confirmation was completed on 2026-09-06. `obs_market_candle` has the expected OHLCV columns plus nullable `trade_count`, but `trade_count` has zero non-null rows across every stored interval checked:

```text
15m rows=2,116,833 trade_count_nonnull=0
1h  rows=2,112,132 trade_count_nonnull=0
4h  rows=632,789   trade_count_nonnull=0
1d  rows=149,536   trade_count_nonnull=0
1w  rows=60,340    trade_count_nonnull=0
```

The same read-only audit searched table names for trade/orderbook/tick/aggressor candidates. Matches were execution/strategy/research artifacts (`trade_lot`, `trade_setup_filter_observation`, `bt_trade_scratch`, archives/previews, plus `obs_venue_ticker_24h`), not a canonical raw public-trade/aggressor-side market-data substrate.

Therefore the repository finding is confirmed against live schema/coverage: true delta/CVD v1 requires a separate market-data foundation if/when prioritized. No production DB mutation was performed.

## Replay / outcome infrastructure

The repository already contains multiple research-only outcome patterns suitable for reuse rather than building an exhaustion-specific backtester.

Relevant examples include:

- `src/research/run_shadow_heartbeat_outcome_validation_v1.py`: forward candle windows, forward return, MFE, MAE.
- `src/research/run_context_touch_fakeout_shape_audit_v1.py`: forward returns plus MFE/MAE grouped by evidence state.
- `src/research/run_cq_v1_discovery_validation_evaluator_v1.py`: frozen discovery/validation handling and holdout sealing discipline.
- `src/research/run_historical_fib_map_episode_substrate_v1.py`: explicit PIT feature/outcome separation and source-content identity.

Phase B should reuse these patterns/contracts where appropriate and must not introduce a parallel generic replay framework.

## Proposed Phase B scope

Smallest useful next slice:

1. define a pure deterministic `src/research/` OHLCV exhaustion candidate builder;
2. consume canonical/reused candle primitives only;
3. emit raw symmetric buyer/seller proxy measurements plus explicit support/freshness/reason codes;
4. no production persistence or selection consumption yet;
5. build focused synthetic golden cases for:
   - strong effort + strong progress = not exhausted;
   - stronger effort + shrinking progress = developing exhaustion;
   - high effort + upper rejection + weak follow-through = buyer exhaustion candidate;
   - symmetric seller case;
   - low-volume drift = insufficient/low confidence, not exhaustion;
   - strong trend continuation = false-exhaustion control;
6. freeze feature definitions before broad historical outcome evaluation.

Phase C can then run multi-asset replay/ablation with discovery/validation/holdout and determine whether the v0 family is `REJECT`, `RESEARCH_FURTHER`, `DISPLAY_ONLY`, or `PROMOTION_CANDIDATE`.

## Dependencies / consumers

- #306 owns the exhaustion research family.
- #277 is reporting-only and may consume prepared upstream evidence after promotion.
- #686 may consume validated exhaustion as morphology context but must not recompute it.
- #663 may evaluate validated exhaustion as Fib Reach evidence but must not hard-code a penalty before calibration.
- #758 owns separate `volume_ratio_20` horizon/regime research; #306 should reuse the primitive and avoid claiming that raw relative volume alone equals exhaustion.

## Acceptance status after Phase A

- [x] Existing candle/volume/rejection primitives audited.
- [x] OHLCV v0 feasibility determined.
- [x] True order-flow/CVD availability audited at repository level.
- [x] Trade-count historical limitation identified in Bitvavo candle backfill.
- [x] Existing replay/outcome patterns identified for reuse.
- [x] Reporting/morphology/Fib Reach ownership boundaries preserved.
- [x] gurkdb schema/coverage confirmation: no canonical aggressor-side source; `trade_count` non-null coverage is zero across stored intervals.
- [ ] v0 feature definitions frozen in code/tests.
- [ ] historical replay/ablation completed.
- [ ] any production promotion decision made.

## Safety

```text
research_only=1
market_only=1
account_awareness=0
production_db_mutation=0
runtime_mutation=0
selection_engine_change=0
decision_gate_change=0
execution_planner_change=0
executor_change=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```
