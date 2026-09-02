# MA Breadth Canonical Owner Audit v1

Status: Phase A audit complete; no implementation
Canonical location: `docs/architecture/ma_breadth_canonical_owner_audit_v1.md`
Issue: #310 (upstream owner); downstream consumer contract: #315 / #617
Audited baseline: `origin/main` at `5ae73df9b534f578acecccabf4c2b6e15caf63de`
Scope: market-only, account-agnostic; no DB or runtime mutation

## Decision

`BUILD_MINIMAL_PRODUCTION_OWNER`

No existing output is an acceptable canonical MA-breadth owner for #617.
In particular, generic Market Breath is not MA breadth:

```text
MARKET_BREATH_EQUIVALENT_TO_MA_BREADTH=0
```

Current main has reusable **per-series** SMA20/SMA50 computation in
`src/features/candle_feat_builder.py`, including `close_above_sma50`. It does
not have a canonical persisted **aggregate** MA-breadth measurement for the
required participation percentages, and it has no shared SMA150/SMA200
primitive established by this audit. The nearest live path is a reporting-side,
on-demand per-asset Market Breath calculation that imports research code; it
cannot be promoted merely because it is used by a live
readout. The next #310 phase must define and validate a minimal, persisted,
production-safe market-only MA-breadth producer before #315 or #617 consumes
any MA-breadth evidence.

This is not a claim that generic Market Breath is invalid. It is a different
feature family (OHLCV return/range/ATR-proxy phase context) and remains
research-only for runtime promotion.

## Audit method and boundaries

Reviewed current-main issue #310 and its 2026-09-02 owner-coordination
comment; issue #315; #243's `SignalHorizonV1` contract;
`regime_evidence_matrix_audit_v1.md`; Market Breath implementation,
research, tests, and consumer paths; feature/volume owners; migrations,
runners, timers, and Git history including commits `76324432`, `9f77fa0b`,
`c25e335e`, `86ff77f3`, and `1e697b9c`.

No indicator calculation, threshold, gauge band, persistence, timer, runtime,
or reporting change was made. Raw numeric MA-breadth percentages remain the
only candidate primary truth; no labels, colors, or classifications are
proposed by this audit.

## Candidate-owner inventory

### 1. Desired #310 MA breadth: absent

The required candidate raw outputs are:

```text
universe_above_sma50_pct
universe_above_sma150_pct
universe_above_sma200_pct
universe_bullish_ma_stack_pct
```

None is calculated, persisted, or consumed as an aggregate MA-breadth output
on current main. `src/features/candle_feat_builder.py` already computes
per-series SMA20/SMA50 and `close_above_sma50`; these are reusable upstream
primitive evidence, not cross-sectional breadth. No SMA150/SMA200 primitive,
aggregate output, matching aggregate migration/table, aggregate runner, timer,
or aggregate test was found. Consequently, none of the following can currently
be truthfully supplied for canonical aggregate breadth: a universe/cohort version, coverage
numerator/denominator, missing-history denominator policy, MA model identity,
or a persisted as-of/freshness record.

| contract item | current status |
| --- | --- |
| architecture owner / namespace | no aggregate MA-breadth owner; #310 owns the future market-only family |
| production vs research | absent |
| persisted vs ephemeral | absent |
| universe identity / reproducibility | absent |
| input interval / lookback / effective horizon | absent; #243 forbids reporting inference |
| observed lifecycle | unmeasured |
| as-of / freshness / coverage | absent |
| missing-history policy | absent |
| model identity/version | absent |
| raw numeric outputs | absent |
| labels, reason codes, thresholds | absent; none invented |
| replay safety / validation | absent |
| runtime dependency / downstream consumers | absent; #315/#617 are only proposed downstream consumers |

### 2. `feat_candle`: production feature primitives, not MA breadth

`src/features/candle_feat_builder.py` is a shared per-series feature builder.
Its default `CandleFeatureConfig` computes SMA20/SMA50 separately for each
`(market, interval)` final-candle series, and its breakout stage emits
`close_above_sma50` (as well as `close_above_sma20`). This is reusable upstream
market-only primitive evidence. It has no aggregate universe definition,
aggregate snapshot, or breadth coverage contract, so it is not itself market
breadth. A future owner must consume this accepted SMA50 primitive where
suitable rather than duplicate its calculation; it must separately audit
whether SMA150/SMA200 require an extension of this shared primitive layer
before adding any aggregate breadth.

`src/features/etl_candle_feat.py`, invoked by
`src.features.run_feat_candle`, is the existing market-only feature-chain
owner of persisted per-asset measurements in `feat_candle`. The 4h runtime
chain refreshes it before downstream signal work. It persists `close_ts_utc`,
`interval_code`, EMA20/EMA50, RSI/ATR, and volume primitives. It does not
persist the shared builder's SMA50/`close_above_sma50` outputs, calculate
SMA150/SMA200, MA stack state, or any aggregate percentage.

The feature writer has a 300-bar warmup default, but that implementation
detail is not an MA-breadth contract and does not establish a future
aggregate's cohort policy. Per-series MA primitives cannot be silently
aggregated into MA breadth: that would introduce production semantics for
eligibility, denominator, snapshot alignment, and coverage.

| contract item | current `feat_candle` evidence |
| --- | --- |
| owner / boundary | `features`; market-only persisted primitive measurement |
| universe | per enabled asset; no retained aggregate cohort identity/version |
| input interval | per row (`interval_code`); active chain commonly uses `4h` |
| lookback | persisted EMA20/EMA50 and volume 20-bar windows; shared builder supplies per-series SMA20/SMA50, not SMA150/200 |
| effective horizon / lifecycle | not emitted for MA breadth; lifecycle unmeasured |
| as-of / freshness | `close_ts_utc` exists; no aggregate MA-breadth freshness owner |
| coverage / missing history | null per primitive as warmup/history requires; no aggregate accounting |
| model/version / classifications | `close_above_sma50` is per-series feature truth; no aggregate MA-breadth model or classifications |
| validation / replay | per-asset deterministic feature computation; no MA-breadth validation or replay artifact |
| consumers | signal, structure/fib and chart paths consume primitives; no MA-breadth consumer |

### 3. `market_breath_live_v1`: live readout, structurally not production-safe owner

`src/reporting/market_breath_live_v1.py` is a read-only reporting helper,
but imports `INTERVAL_SECONDS`, `build_base_observation`,
`add_breadth_and_scores`, `fetch_assets`, `fetch_candles`, and related
helpers directly from `src/research/run_market_breath_analysis_v1.py`. It
resolves the latest candle as-of, queries enabled/tradeable assets, and
computes results in memory for the requested symbols (plus BTC when needed).
It writes neither a snapshot nor a reusable evidence record.

Its `breadth_alignment_score` derives from the share of valid **6-candle
returns** that are positive (`>=0.55` positive or `<=0.45` negative), then
measures each asset's return-direction alignment. It is not a universe-level
SMA participation percentage, MA stack, or retained market aggregate.

`market_breath_live_v1` does expose per-symbol unavailable/stale status:
BTC absence/staleness and source-candle lag of at least one input interval
fail unavailable/stale. That presentation freshness behavior does not repair
the research import, add versioned persistence, or establish aggregate cohort
coverage. Its live use therefore does not constitute production promotion.

| contract item | current evidence |
| --- | --- |
| owner / namespace | reporting wrapper over `src/research/*`; no declared production evidence owner |
| production vs research | reporting is read-only; imported computation declares research-only and `runtime_promotion_allowed=False` |
| persisted vs ephemeral | ephemeral, per invocation; DB reads only |
| universe | enabled + tradeable `asset` rows at invocation; request filter may narrow output; no universe ID/version |
| input interval / lookback | defaults `4h` / 120 candles; configurable |
| effective horizon / lifecycle | not emitted; lifecycle unmeasured |
| as-of / freshness | resolved latest source candle and per-symbol status are emitted; no persisted snapshot freshness |
| coverage | per-symbol confidence is valid candle count / requested lookback; no aggregate numerator/denominator |
| missing-history policy | fewer than 24 candles becomes `INSUFFICIENT_DATA`; stale/absent source becomes unavailable/stale |
| model/version | research runner reports `market_breath_analysis_v1` version `0.1`; live payload does not carry model identity/version |
| numeric output | phase scores and per-asset return alignment; no MA percentages |
| classifications / thresholds | research phase labels and hardcoded return/phase thresholds; not MA thresholds and not promoted |
| replay / validation | computation caps candles at `asof_ts`; Market Breath research validation exists, but no MA-breadth validation |
| consumers | Manual SHORT Profit Plan cards; read-only diagnostics/tests; not #315/#617 MA evidence |

### 4. Market Breath research runner/classifier: useful research, not promotion candidate

`src/research/run_market_breath_analysis_v1.py` declares
`scope="research-only market-only account-agnostic"`, writes only optional
`data/research/market_breath_analysis_v1/` files, and sets both
`runtime_promotion_allowed=False` and
`feature_candidate_promotion_allowed=False`. Its classifier is separately
located in `src/research/market_breath_classifier_v1.py`; extracting it did
not change its namespace or boundary.

The research lane has replay-safe input bounding (`close_ts_utc <= asof_ts`)
and first-pass/extended outcome research. That evidence concerns Market Breath
phase behavior, not MA position/stack participation. The current summary's
explicit outcome is `No runtime promotion`; it calls the sensor
`research-only` and `parked until downstream use-case`. Merged commits and
reporting consumers do not override that finding.

### 5. Volume ratio/z-score: existing per-asset owners, no aggregate breadth

The established feature-chain owner persists per-asset
`volume_ratio_20`, `volume_zscore_20`, and `dollar_volume_ratio_20` in
`feat_candle`, with 20-bar self-history semantics. Signal code consumes those
existing primitives. This audit retains them as existing owners and does not
duplicate them.

`src/features/volume_confirmation_snapshot.py` is a second per-asset,
1d-oriented writer for 7/14-day ratio/z-score snapshots. Repository inventory
finds no migration, timer/runtime ownership, version contract, or accepted
aggregate consumer for it. It does not compute a cross-sectional volume or MA
breadth percentage. It is not a production-safe aggregate owner.

## Persisted artifacts and consumer chain

No `market_breath*` or MA-breadth table/migration is present on current main.
The only current Market Breath artifacts are optional research files and
ephemeral reporting output. The `market_breath_context_bridge_v1` and
`market_breath_live_v1` compute current values on demand and are consumed by
read-only Profit Plan/paper-advice/rotation reporting surfaces. Those
consumers must not become producers: #315 explicitly requires a persisted,
versioned #310 output and must not calculate MA breadth itself.

```text
obs_market_candle + asset
  -> feat_candle (existing per-asset EMA/volume primitives)
  -> research Market Breath on-demand computation
  -> reporting readout

No current path:
  -> persisted canonical MA-breadth snapshot
  -> #315 / #617 read-only consumption
```

No timer or runner invokes `run_market_breath_analysis_v1` or an MA-breadth
writer in the production runtime inventory. No selection, decision, planner,
executor, broker, or order dependency was found.

## Required next step for #310

Create a bounded follow-up design/implementation slice for one minimal
market-only, production-safe MA-breadth snapshot owner. Before it may supply
#315/#617, that owner must define and validate:

1. a reproducible, versioned eligible universe/cohort and its inclusion rules;
2. interval and SMA50/SMA150/SMA200 history semantics, consuming the accepted
   per-series SMA50 primitive where suitable rather than duplicating it;
3. explicit eligible, excluded-missing-history, and stale counts plus the
   denominator used by each raw percentage;
4. `asof_ts`, producer-owned freshness, `model_id`, `model_version`, and
   `effective_horizon` per #243; observed lifecycle may be `UNMEASURED`;
5. append-safe/persisted snapshot identity and point-in-time replay behavior;
6. focused validation of raw MA participation measurements, separate from the
   existing Market Breath phase validation; and
7. an explicit shared-primitive-layer decision for SMA150/SMA200 before those
   aggregate metrics are added; and
8. only after validation, any secondary labels/reason codes. Gauge bands or
   thresholds are intentionally not specified here.

The future owner may reuse accepted market-data/feature infrastructure, but
must not repurpose reporting or research output as canonical runtime truth
without an explicit boundary review. It remains market-only and must not alter
`selection_engine`, `decision_gate`, `execution_planner`, `executor`,
broker, or orders.

## Safety record

```text
audit_only=1
market_only=1
account_aware=0
db_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
selection_engine_changed=0
decision_gate_changed=0
execution_changed=0
thresholds_invented=0
```
