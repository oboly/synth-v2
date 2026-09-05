# VOLATILITY Evidence Canonical Owner Audit v1

Status: Phase A audit complete; no implementation
Canonical location: `docs/architecture/volatility_evidence_canonical_owner_audit_v1.md`
Issue: #747 (this audit); downstream consumer contract: #617
Upstream owner: #243 (`docs/architecture/multi_horizon_signal_contract_v1.md`)
Audited baseline: `origin/main` at `cef27095`
Scope: market-only, account-agnostic; no DB or runtime mutation

## Decision

`BUILD_MINIMAL_CANONICAL_OWNER`

No existing module on current `main` is an acceptable canonical VOLATILITY
evidence owner for #617. This confirms and extends the prior finding in
`docs/architecture/regime_evidence_matrix_audit_v1.md` section 3.6
(`VOLATILITY: MISSING`), produced under PR #667, which at that time had only
found one ATR usage (`local_ma_atr_context_v1.py`, exit-context only). This
audit finds substantially more raw volatility-adjacent material than existed
at that time — a persisted ATR/true-range primitive (`feat_candle.atr_14`,
`atr_pct`; a separate `range_pct` variant is persisted only via the
different `candle_feat_builder.py` path, not in `feat_candle` — see
candidate 1 below), a persisted realized-volatility primitive
(`asset_profile_snapshot.realized_volatility`), and several research-only
volatility calculations — but none of it is an independently versioned,
freshness/horizon-complete, #243-compliant evidence owner, and no accepted
production definition of volatility expansion/compression or upside/downside
asymmetry exists anywhere in the repository.

```text
ATR_TRUE_RANGE_PRIMITIVE_EXISTS=1 (feat_candle.atr_14/atr_pct; range_pct exists only in the separate candle_feat_builder.py path, not in feat_candle; not independently contracted)
REALIZED_VOLATILITY_PRIMITIVE_EXISTS=1 (asset_profile_snapshot.realized_volatility, bundled composite, not standalone)
EXPANSION_COMPRESSION_DEFINITION_EXISTS=0 (no accepted PRODUCTION definition; research-only bases found: an untracked DB view label, research clustering thresholds, a market-breath range-vs-baseline score formula, and a deterministic single-asset-replay range_expansion boolean rule)
ASYMMETRY_DEFINITION_EXISTS=0
GENERAL_VOLATILITY_EVIDENCE_OWNER_EXISTS=0
```

This is Phase A: audit only. No indicator math, thresholds, tables, or
runners are introduced by this document. A minimal canonical VOLATILITY
evidence owner must be designed and built in a separate, explicitly scoped
follow-up issue/PR before #617 may consume VOLATILITY evidence.

## Audit method

Case-insensitive repository-wide search (`src/`, `db/`, `docs/`, `tests/`,
`apps/`, `scripts/`) for: ATR, true range, `atr_14`, realized volatility,
return stddev/dispersion, rolling/high-low range, range fraction, volatility
expansion/compression/percentile, ATR percentile, range expansion ratio,
volatility change, semivariance, downside/upside volatility, volatility
asymmetry, volatility persistence/clustering, Bollinger bandwidth. Reviewed
every match's producer, persistence, and consumer chain. Cross-checked
against `docs/architecture/momentum_evidence_producer_v1.md` and
`docs/architecture/momentum_evidence_canonical_owner_audit_v1.md` (#741/#742,
same audit-then-build pattern), `docs/architecture/multi_horizon_signal_contract_v1.md`
(#243), `docs/architecture/regime_evidence_matrix_audit_v1.md` (#617 Phase A,
PR #667), `docs/architecture/multi_tf_conviction_contract_v1.md` (#591),
`src/features/structure_evidence_contract_v1.md`-adjacent code
(`structure_evidence_contract_v1.py`) for the in-repo evidence-contract
shape, and searched for `686`/morphology and `301`/`305`/`591` references
(no volatility-specific content found beyond what is cited below). No
dedicated architecture doc exists yet for a volatility family; it is
referenced only as `MISSING` inside the #617 audit.

No indicator calculation, threshold, band, persistence, timer, runtime, or
reporting change was made. Raw numeric values remain the only candidate
primary truth; no categorical volatility states are proposed by this audit.

## Candidate-owner inventory

### 1. `feat_candle.atr_14` / `atr_pct` (plus a separate `candle_feat_builder.py` `range_pct` variant): raw production primitives, not a contracted evidence owner

- Producer: `src/features/etl_candle_feat.py::compute_atr` (Wilder-style ATR:
  true range = max(high-low, |high-prev_close|, |low-prev_close|); ATR =
  `tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()`), invoked by
  `src.features.run_feat_candle` (`src/features/run_feat_candle.py`).
  `atr_pct = atr_14 / close`. A **second, divergent** ATR implementation
  exists in `src/features/candle_feat_builder.py::_add_volatility_features`
  (plain rolling mean of true range, window `cfg.atr_window`, plus
  `range_pct = (high-low)/close`), used only by
  `src/features/ma_breadth_snapshot_v1.py`'s per-series feature reuse — a
  **different formula** (simple rolling mean vs. Wilder EMA) from the one
  written into `feat_candle` by the canonical `run_feat_candle` ETL. These
  two ATR implementations must not be conflated; they are not the same
  evidence.
- Persistence: `feat_candle` table (upsert on `candle_id`, i.e. latest-value
  semantics, not append-only versioned evidence), columns include
  `close_ts_utc`, `interval_code`, `atr_14`, `atr_pct`, plus `ema_20`,
  `ema_50`, `rsi_14`, volume features.
- Market scope: per enabled asset, per `(candle_id, asset_id, venue,
  interval_code)`; `run_feat_candle.py` currently refreshes `1h`, `4h`,
  `1d` for venue `bitvavo`, with a fixed 300-bar warmup lookback
  (`--warmup-bars`, default 300) — a bounded backfill window, not a
  full-contiguous-history-per-asof recursive contract like
  `momentum_evidence_snapshot_v1.py` (#741/#742/#746).
- `model_id` / `model_version`: absent. No version column on `feat_candle`.
- `input_interval`: explicit per row (`interval_code`).
- `lookback_horizon`: implicit only (period=14 baked into `compute_atr`);
  not exposed as a separate field.
- `effective_horizon`: absent; not mapped to the #243 enum anywhere.
- `observed_lifecycle`: absent/unmeasured.
- `asof_ts`: `close_ts_utc` exists and is real, but there is no per-row
  `freshness` classification exposed by the writer itself, no explicit
  `evaluated_at`, and no documented future-asof or fail-closed behavior in
  `etl_candle_feat.py` — the ETL is a batch backfill/upsert job, not an
  asof-parameterized evidence query.
- Replay safety: deterministic per historical candle window in principle,
  but the fixed 300-bar warmup and upsert-on-`candle_id` persistence model
  mean there is no reproducible, versioned point-in-time snapshot analogous
  to the momentum producer's contiguous-history contract.
- Raw numeric fields: yes (`atr_14`, `atr_pct`, `range_pct` in the
  `candle_feat_builder.py` variant only — `range_pct` is **not** written by
  `etl_candle_feat.py`/`feat_candle`, only by the separate
  `ma_breadth_snapshot_v1.py` reuse path).
- State/classification fields: none (raw only) at this layer.
- Reason codes / provenance: none beyond `close_ts_utc`/`interval_code`.
- Direct consumers of `feat_candle.atr_14`/`atr_pct` on current `main`:
  - **Selection/signal consumers (selection-local, threshold use):**
    `src/engine/run_signal_engine.py` (lines 76, 84, 165, 169, 175, 263,
    267) and `src/signal_engine/run_signal_state_etl.py` (lines 123, 131,
    210, 214, 220, 282, 286, 332, 337) both fold `atr_pct` into hardcoded
    threshold checks (e.g. `atr_pct < 0.03`, `atr_pct > 0.08`,
    `atr_pct > 0.12`) and a weighted composite score. These are
    selection-local consumers of the raw primitive, not a volatility
    evidence contract.
  - **Analysis/research consumers:** ten `src/analysis/*_4h.py` modules
    (`reversion_state_features_4h.py`, `known_signal_family_4h.py`,
    `trend_pullback_continuation_4h.py`,
    `reversion_extreme_t1_entry_t2_exit_4h.py`,
    `reversion_extreme_low_participation_liquid_4h.py`,
    `reversion_state_baseline_4h.py`, `rejected_htf_event_diagnostic.py`,
    `reversion_extreme_low_participation_atr_4h.py`,
    `reversion_state_score_diagnostic.py`,
    `reversion_extreme_low_participation_4h.py`) select `atr_pct` from
    DB views (`v_known_signal_family_4h`, `v_volatility_compression_breakout_4h`,
    and similar `v_*_4h` views not present as tracked migrations in `db/`)
    alongside forward-looking `next_return_4h`, for research/backtest
    analysis only.
  - **Reporting consumer:** `src/ui_chart/chart_config.py`,
    `chart_repository.py`, `chart_assembler.py` read `atr_14`/`atr_pct` for
    chart display only — correctly read-only, not an indicator-truth
    violation.
  - **Backtest consumers (independent local reimplementations, not
    `feat_candle` readers):** `src/backtest/strategies/pullback_reclaim_strategy.py`
    and `pullback_reclaim_atr_strategy.py` each compute their own local
    `_atr()` (Wilder-style, on the in-memory backtest dataframe);
    `src/backtest/backtest_runner.py` imports `atr` from a separate
    `indicators` module; `src/strategies/ema_trend_strategy.py` has its own
    local `atr()`/`true_range()` reimplementation. **None of these four
    reads `feat_candle.atr_pct`/`atr_14`** — each recomputes ATR locally
    from raw OHLC on its own backtest dataframe. They use ATR as a backtest
    entry-filter/stop parameter — research/backtest scope, not production
    evidence, and explicitly excluded from this audit's owner candidacy.
  - None of these paths defines, versions, or exposes `atr_14`/`atr_pct` as
    independently addressable, #243-contracted VOLATILITY evidence.
- **Classification: `REUSABLE_PRIMITIVE_ONLY`.** Real, live, deterministic
  raw values, but carrying none of the #243 provenance/freshness/version
  fields, not independently addressable, and — for `etl_candle_feat.py`
  specifically — using a fixed-warmup batch-upsert model rather than an
  asof-parameterized evidence contract. A second, differently-formulated
  ATR (`candle_feat_builder.py`) exists in parallel and must not be
  silently merged with it.

### 2. `asset_profile_snapshot.realized_volatility`: closer to contract shape, still a bundled composite field, not a dedicated volatility owner

- Producer: `src/asset_profile/asset_profile_engine_v1.py::build_asset_profiles`.
  Formula: population stddev (`statistics.pstdev`) of per-candle percentage
  returns over the lookback window, multiplied by an interval normalizer
  (`sqrt(24)` for `1h`, `sqrt(6)` for `4h`, `1` for `1d` —
  `volatility_normalizer()`, lines 105-111) to express volatility on a
  common daily-equivalent basis. This is realized-return volatility, not
  ATR/true-range based.
- Persistence: `asset_profile_snapshot` table
  (`db/migrations/20260501_asset_profile_snapshot_v1.sql`). Has real
  point-in-time shape: `asof_ts_utc DATETIME(6) NOT NULL` (with a migration
  comment explicitly requiring `asof_ts_utc <= replay time` for backtests),
  `lookback_days`, `profile_version VARCHAR(64)`. **However,
  `src/asset_profile/repository.py::upsert_snapshots` writes via
  `INSERT ... ON DUPLICATE KEY UPDATE` keyed on the identical unique key
  `(asset_id, venue, interval_code, asof_ts_utc, lookback_days,
  profile_version)` — this is upsert-over-same-key, not append-only.
  Re-running the engine for an already-written `(…, asof_ts_utc, …,
  profile_version)` tuple overwrites `realized_volatility` and every other
  derived column of that row in place rather than adding a new row; only a
  genuinely new key tuple (new `asof_ts_utc` or a bumped `profile_version`)
  produces a new row.**
- Market scope: per asset, per `(venue, interval_code, asof_ts_utc,
  lookback_days)`.
- `model_id`/`model_version`: only a single composite `profile_version`
  covering the *entire* asset-profile engine (liquidity, beta, sector,
  realized_volatility together) — no independent versioning for the
  volatility calculation alone.
- `input_interval`: explicit (`interval_code`). `lookback_horizon`: explicit
  (`lookback_days`). `effective_horizon`: absent, not mapped to the #243
  enum. `observed_lifecycle`: absent/unmeasured.
- `asof_ts`: explicit and real (`asof_ts_utc`), with a documented
  point-in-time replay contract at the table/migration-comment level — the
  strongest *labeled* asof intent found in this audit for any
  volatility-adjacent field. However, the write path is an upsert keyed on
  `(asset_id, venue, interval_code, asof_ts_utc, lookback_days,
  profile_version)` (see persistence note above), so a row already written
  for a given `asof_ts_utc` is silently overwritten by a later re-run rather
  than preserved as an immutable historical fact — this is a real replay-safety
  gap, not append-only durability. No `evaluated_at` distinct from
  `asof_ts_utc`, no documented future-asof fail-closed behavior, no explicit
  freshness/staleness classification, and no fail-closed contiguity check
  were found in `asset_profile_engine_v1.py` itself.
- Raw numeric field: yes (`realized_volatility`). No expansion/compression
  or asymmetry field. `beta_profile` (`LOW_BETA`/`NORMAL_BETA`/`HIGH_BETA`/
  `EXTREME_BETA`) is a *derived categorical label from beta*, not from
  realized_volatility directly, though `beta_profile_from_values(beta,
  daily_vol)` does take volatility as a secondary input
  (`asset_profile_engine_v1.py:46`) — this conflates a volatility-adjacent
  signal into a beta-named category rather than exposing it as its own
  volatility-regime classification.
- Direct consumers: `src/asset_profile/run_asset_profile_snapshot_v1.py`
  (its own runner/printer), `src/asset_profile/repository.py` (persistence
  layer), `src/ui_chart/chart_repository.py` /
  `docs/architecture/asset_profile_layer_v1.md` (reporting/read model, `line
  270`/`line 81` reference `realized_volatility` for display). No
  `selection_engine`/`decision_gate`/`execution_planner`/`executor` consumer
  found.
- **Classification: `REUSABLE_PRIMITIVE_ONLY`** (with the only explicit
  `asof_ts_utc` labeling of any candidate found, but an upsert-over-same-key
  write path that overwrites rather than preserves historical rows, and not
  a dedicated, independently versioned VOLATILITY owner — `realized_volatility`
  is one field inside a multi-purpose asset-profile composite whose
  `profile_version` covers liquidity/beta/sector together, not volatility
  alone, and it has no `effective_horizon`/`observed_lifecycle`/freshness/
  fail-closed contract of its own).

### 3. Research-only volatility calculations: confirmed research-scoped, not owner candidates

- `src/research/run_market_regime_discovery_v1.py::volatility_pct` (line
  304-309): stddev of trailing returns (`btc_volatility_7d` field, used at
  line 418/424 with hardcoded thresholds `vol >= 4.0` /
  `vol <= 2.0`) feeding a k-means-style `cluster_label_auto()` that emits
  `DISCOVERED_*` labels (`DISCOVERED_VOLATILE_ROTATION`,
  `DISCOVERED_COMPRESSION_BALANCE`, etc.) — explicitly a discovery/research
  script, invented thresholds for exploratory clustering only, no
  persistence contract, no production consumer.
- `src/research/pattern_families/volatility_compression_breakout_4h.py`
  reads a **DB view** `v_volatility_compression_breakout_4h` (not present as
  a tracked migration anywhere in `db/`) joined with forward-looking
  `next_return_4h`, and inspects a pre-existing `signal_family` value
  `VOLATILITY_COMPRESSION_BREAKOUT_4H_V1`. Because the view is untracked,
  its exact expansion/compression formula/threshold cannot be verified from
  the repository — it is not a reviewable, versioned production definition
  regardless of its apparent production-sounding name. This file only
  aggregates/prints forward-return statistics; it is research analysis, not
  a producer.
- `src/analysis/known_signal_family_4h.py` similarly reads
  `v_known_signal_family_4h` (also untracked) joined with `next_return_4h`;
  same research-only classification.
- `src/research/run_market_breath_analysis_v1.py` computes explicit,
  reviewable `compression_score`/`expansion_score` fields (lines 384/386):
  `compression = 0.55 * score_low_vs_baseline(current_range, median_range) +
  0.45 * score_low_vs_baseline(atr_proxy, atr_median)`; `expansion = 0.45 *
  score_high_vs_baseline(current_range, median_range) + 0.35 *
  score_high_vs_baseline(abs(r3), return_baseline) + 0.20 *
  score_high_vs_baseline(atr_proxy, atr_median)` — its own **fourth**
  independent true-range/ATR-proxy implementation (`true_range_pct`, lines
  ~195-211), scored against a rolling median baseline. This is the most
  fully-formed expansion/compression *formula* found anywhere in the
  repository, and it does accept an explicit `--asof-ts` argument
  (`parse_args`), bounds its candle query window to it
  (`fetch_candles(..., asof_ts=asof_ts)`, with the script's own comment "No
  future candles are used; all candles are `close_ts_utc <= asof_ts_utc`"),
  and records `asof_ts_utc` in its output rows — real, explicit
  point-in-time query discipline, not absent. However it is still a
  market-breath research script only: no DB persistence (`db_writes=0`,
  writes only optional local JSONL/JSON files), no `model_id`/
  `model_version`, no `evaluated_at` distinct from `asof_ts_utc`, no
  documented future-asof fail-closed behavior, no freshness/staleness
  classification field, and no producer-owned #243 contract — i.e. explicit
  `asof` *query* support without a production freshness/evidence-owner
  *contract*. Consumed only by other research scripts and by
  `src/reporting/market_breath_context_bridge_v1.py` /
  `market_breath_live_v1.py` for read-only display — never by
  `selection_engine`/`decision_gate`/`execution_planner`/`executor`.
- `src/research/run_signal_matrix_single_asset_replay_v1.py` defines an
  explicit, deterministic range-expansion rule: `RANGE_LOOKBACK = 12`,
  `RANGE_EXPANSION_MULTIPLIER = 1.5`; per bar,
  `current_range_pct = ((high / low) - 1) * 100`, `median_range_pct =
  median(range_pct over the preceding 12 candles, strictly excluding the
  current bar)`, and `range_expansion = current_range_pct >=
  median_range_pct * 1.5`. The result is emitted into `SignalRow.range_expansion`
  (a per-row string field of its output rows). It is point-in-time scoped
  (each row's median is computed only from prior bars via
  `candles[max(0, idx - RANGE_LOOKBACK):idx]`, never the current or future
  bar) and reproducible/deterministic given the same input candles, but it
  is still a **research replay script**, not a production evidence owner:
  `db_writes=0` (only local CSV/JSONL output under
  `data/research/signal_matrix_single_asset_replay_v1/`), no `model_id`/
  `model_version`, no independently versioned volatility-evidence contract,
  no #243 horizon mapping, and no consumer outside its own research report
  (`docs/research/signal_matrix_single_asset_replay_v1.md`). A deterministic,
  replay-safe **research** range-expansion rule existing is not the same
  thing as a canonical, independently versioned, freshness/horizon-complete
  **production** VOLATILITY evidence owner existing — this audit does not
  conflate the two.
- **Classification: `RESEARCH_ONLY`** for all five. None may be treated as
  an implicitly promoted production volatility owner; the untracked views
  in particular mean their exact logic is not currently auditable or
  reviewable in-repo at all, and the market-breath and single-asset-replay
  formulas, while the most complete/deterministic found, have never been
  reviewed or contracted as production evidence.

### 4. Execution/display-context ATR usage: confirmed out of scope, not owner candidates

- `src/market_context/local_ma_atr_context_v1.py` and
  `src/market_context/impulse_health_state_v1.py` compute ATR
  (`_compute_atr`/`_compute_true_ranges`, Wilder-style, independent
  reimplementation from `feat_candle`) purely as an internal tick-distance
  buffer for exit/reclaim/spike-cooling context feeding
  `market_context_builder_v1.py`, which is explicitly a read-only display
  context for the Manual SHORT Trader Profit Plan (`#688`). This matches
  the prior #667 finding that `local_ma_atr_context_v1.py` is "exit-context
  only," now with a sibling module (`impulse_health_state_v1.py`) doing the
  same locally-scoped thing.
- `src/market_data/fib_navigation_map_v1.py::_compute_atr` (own third
  independent ATR implementation) uses ATR only as an impulse-move
  multiplier threshold (`impulse_atr_multiple`) inside fib/navigation map
  construction — a market-data/zone-mapping concern, not a volatility
  evidence contract.
- `src/features/rejection_event.py` computes a simple rolling-mean ATR
  (14-period) purely to normalize a rejection-wick distance feature
  (`rejection_event.py:15, 36-43`) — a feature-local normalizer, not
  exposed as standalone evidence.
- `src/structure/range_state.py::compute_range_state` computes ATR
  (`# --- ATR (simple v1)`) purely as an internal breakout-buffer parameter
  (`0.25 * atr`) for `RANGE_BREAKING`/`NO_RANGE` classification, persisted
  via `src/measurement/run_structure_state_engine.py` into
  `structure_state.range_state`/`range_score` — this is the
  **PRICE_STRUCTURE** family (already flagged "semantically unresolved" in
  `regime_evidence_matrix_audit_v1.md` section 3.1/3.2), not a volatility
  owner; ATR here is an internal breakout-detection buffer, never exposed
  as a volatility value.
- **Classification: `EXECUTION_LOCAL`** (the two `market_context` modules
  and `fib_navigation_map_v1.py`, all read-only display/zone-mapping
  context, none touching `execution_planner`/`executor`/broker/orders
  directly) and **`NOT_VOLATILITY_OWNER`** (`range_state.py`,
  `rejection_event.py` — internal buffers/normalizers for a different
  evidence family). None is a general-purpose volatility owner and none
  should be broadened into that role — each has a distinct, independent ATR
  reimplementation, meaning at least **five** separate ATR/true-range
  formulas exist across the repository
  (`etl_candle_feat.py`, `candle_feat_builder.py`,
  `local_ma_atr_context_v1.py`/`impulse_health_state_v1.py`,
  `fib_navigation_map_v1.py`, `range_state.py`, `rejection_event.py`,
  `strategies/ema_trend_strategy.py`, `run_market_breath_analysis_v1.py`)
  with no single shared, canonical implementation.

### 5. `sector_rotation_engine_v1.py` dispersion: a different evidence family, not per-asset volatility

- `src/research/sector_rotation_engine_v1.py::_weighted_std` computes
  cross-sectional dispersion of *returns across assets at a point in time*
  (a rotation/breadth-adjacent measure), not a single asset's volatility
  over time. Persisted to a research-scoped rotation table
  (`db/migrations/20260716_sector_rotation_engine_v1.sql`).
- **Classification: `NOT_VOLATILITY_OWNER`** — flagged only so it is not
  confused with or duplicated against a future per-asset volatility
  producer; it answers a cross-sectional dispersion question, not a
  time-series volatility question.

## Expansion / compression audit

No reviewed, versioned, in-repo production contract defines deterministic
volatility expansion/compression. The candidate bases found, all
research-only, are:

1. The DB view label `VOLATILITY_COMPRESSION_BREAKOUT_4H_V1` consumed by
   `src/research/pattern_families/volatility_compression_breakout_4h.py` —
   its defining SQL (`v_volatility_compression_breakout_4h`) is **not
   present in `db/migrations/` or anywhere else in the repository**, so its
   exact threshold/formula cannot be verified or treated as reviewable
   production logic despite its name.
2. `src/research/run_market_regime_discovery_v1.py`'s hardcoded
   `vol >= 4.0` / `vol <= 2.0` thresholds inside `cluster_label_auto()` —
   explicitly research/discovery-only, invented for exploratory clustering,
   not a reviewed production baseline.
3. `src/research/run_market_breath_analysis_v1.py`'s `compression_score`/
   `expansion_score` (range-vs-rolling-median-baseline formula, detailed in
   the candidate inventory above) — the most fully-formed *scoring* formula
   found, but still research-only, unpersisted, unversioned, and never
   reviewed as a production evidence contract.
4. `src/research/run_signal_matrix_single_asset_replay_v1.py`'s
   `range_expansion` boolean (`current_range_pct >= median_range_pct * 1.5`
   over a 12-bar trailing window, detailed in the candidate inventory
   above) — the most fully-formed deterministic, point-in-time-safe
   *boolean rule* found, but still a research replay script: unpersisted to
   any DB table, unversioned as an evidence contract, and consumed only by
   its own research report. A deterministic research replay rule is not a
   canonical production evidence owner.

This list reflects a repeated, repository-wide search for `range_expansion`,
`compression_score`, `expansion_score`, `volatility_compression`,
`range_pct`, rolling-range, ATR-percentile, and volatility-percentile terms
across `src/`, `db/`, `docs/`, `tests/`, `apps/`, and `scripts/`; no fifth
expansion/compression candidate base was found beyond the four above.

**Classification: `MISSING`** for a **production** definition. No
ATR-current-vs-prior-ATR, ATR percentile,
range-vs-rolling-baseline, Bollinger-width/percentile, or other normalized
expansion/compression metric exists as an accepted, versioned **production**
definition anywhere in the repository — candidates 3 and 4 above are the
closest in form (a scoring formula and a deterministic boolean rule,
respectively) but neither has ever been reviewed, persisted to a DB table,
or contracted for that role. A research-only deterministic rule existing is
not equivalent to a canonical production VOLATILITY evidence owner existing.
This audit does not invent one.

## Asymmetry audit

Repository-wide search for semivariance, upside/downside volatility,
volatility asymmetry, true-range decomposition, and gap-adjusted range
asymmetry returns **zero matches** anywhere in `src/`, `db/`, `docs/`, or
`tests/`.

**Classification: `MISSING`.** No production, research, or reporting
implementation of upside/downside volatility asymmetry exists to reuse,
promote, or adapt. This audit does not invent semantics for it.

## Persisted artifacts and consumer chain

```text
obs_market_candle
  -> feat_candle (atr_14 via etl_candle_feat.py Wilder-EMA true range;
                  atr_pct = atr_14/close; no #243 contract fields;
                  fixed 300-bar warmup batch-upsert, not asof-parameterized)
     -> src/engine/run_signal_engine.py, src/signal_engine/run_signal_state_etl.py
        (atr_pct folded into hardcoded selection-local threshold checks / composite score)
     -> src/analysis/*_4h.py (10 modules; research/backtest analysis via untracked v_*_4h views)
     -> src/ui_chart/* (reporting display only)

  -> candle_feat_builder.py (SEPARATE, differently-formulated ATR: plain rolling
                             mean, not Wilder-EMA; window=cfg.atr_window)
     -> src/features/ma_breadth_snapshot_v1.py (per-series reuse; MA breadth family, not volatility)

src/backtest/strategies/* + src/backtest/backtest_runner.py + src/strategies/ema_trend_strategy.py
  (each its OWN independent local ATR reimplementation on the backtest
   dataframe; NONE reads feat_candle.atr_14/atr_pct — backtest entry-filter/
   stop parameter, out of scope for this audit's owner candidacy)

obs_market_candle (independent path)
  -> asset_profile_engine_v1.py::build_asset_profiles (realized-return pstdev,
                                                        interval-normalized)
     -> asset_profile_snapshot.realized_volatility (asof_ts_utc + profile_version,
                                                     upsert-keyed on that same tuple
                                                     (not append-only), composite-scoped
                                                     profile_version, no dedicated
                                                     volatility model identity)
        -> src/ui_chart/*, docs/architecture/asset_profile_layer_v1.md (reporting/display)

Independent, unrelated ATR reimplementations (execution/display/structure-local,
each with its own formula, none exposed as volatility evidence):
  -> src/market_context/local_ma_atr_context_v1.py + impulse_health_state_v1.py
     (Manual SHORT Trader Profit Plan exit/reclaim context, #688)
  -> src/market_data/fib_navigation_map_v1.py (impulse-move multiplier for zone mapping)
  -> src/structure/range_state.py (RANGE_BREAKING/NO_RANGE breakout buffer, PRICE_STRUCTURE family)
  -> src/features/rejection_event.py (rejection-wick distance normalizer)
  -> src/strategies/ema_trend_strategy.py (backtest stop parameter)

No current path:
  -> a standalone, versioned, #243-compliant VOLATILITY evidence table
  -> a reviewable production expansion/compression or asymmetry definition
  -> #617 read-only consumption
```

`feat_candle.atr_pct` already has existing signal-engine consumers
(`src/engine/run_signal_engine.py`, `src/signal_engine/run_signal_state_etl.py`
— hardcoded threshold checks and a composite-score term, per the map above).
No `src/selection/`, `src/selection_engine/`, `decision_gate`,
`execution_planner`, `executor`, broker, or order dependency was found on any
candidate module reviewed above. `feat_candle` and `asset_profile_snapshot`
are the only two candidates with real persistence and production-refresh
characteristics; neither is independently versioned or #243-complete for
volatility specifically, and neither has a dedicated, versioned VOLATILITY
evidence-owner consumer — only ad hoc, module-local reuse of raw ATR fields.

## #243 horizon mapping (per candidate)

```text
candidate                                  input_interval  lookback_horizon        effective_horizon  observed_lifecycle
feat_candle.atr_14/atr_pct                 explicit        implicit (period=14)    absent/UNKNOWN     absent/UNMEASURED
candle_feat_builder atr (ma_breadth reuse) explicit        explicit (cfg.atr_window) absent/UNKNOWN   absent/UNMEASURED
asset_profile_snapshot.realized_volatility explicit        explicit (lookback_days) absent/UNKNOWN    absent/UNMEASURED
research volatility_pct / btc_volatility_7d n/a (research)  explicit (periods param) absent/UNKNOWN   absent/UNMEASURED
research market_breath compression/expansion n/a (research) explicit (14/60-bar)    absent/UNKNOWN     absent/UNMEASURED
research signal_matrix range_expansion     n/a (research)  explicit (RANGE_LOOKBACK=12) absent/UNKNOWN absent/UNMEASURED
execution/display-context ATR variants     explicit        implicit (fixed period)  absent/UNKNOWN     absent/UNMEASURED
```

No candidate maps `effective_horizon` deterministically to the #243 enum;
all remain `UNKNOWN` and none is inferred from candle interval by this
audit, per #243 section 3.3's explicit prohibition.

## Asof / replay / freshness gaps (per candidate)

- `feat_candle`: no explicit asof-query contract (fixed warmup-bars batch
  ETL), no freshness classification field, no documented future-asof
  fail-closed behavior, no documented gap/contiguity fail-closed behavior.
- `asset_profile_snapshot`: explicit `asof_ts_utc` with a documented
  point-in-time replay expectation at the table-comment level (strongest
  found), but no `evaluated_at` distinct from `asof_ts_utc`, no
  freshness/staleness field, no documented future-asof or fail-closed
  contiguity behavior in the engine code itself.
- `src/research/run_market_breath_analysis_v1.py` is the one exception to
  "no asof parameterization" among the research-only candidates: it accepts
  an explicit `--asof-ts`, bounds its candle query to it, and records
  `asof_ts_utc` in output (see candidate inventory above) — but still has no
  `evaluated_at`, no freshness/staleness field, no documented future-asof
  fail-closed behavior, and no #243 contract, so it remains
  `RESEARCH_ONLY` rather than a freshness/evidence-owner-complete candidate.
- All other research-only and all execution/display-context candidates: no
  asof parameterization, no freshness contract, no fail-closed behavior
  documented — consistent with their non-owner classification.

## Anti-duplication boundaries

A future minimal VOLATILITY producer must not:

- reuse or repurpose `feat_candle.atr_14`/`atr_pct` in place as the
  contracted evidence value (it may reuse the *raw candle inputs* to
  recompute a canonical ATR/true-range, following the #741/#742/#746
  full-contiguous-pre-asof-history pattern, but must not silently adopt the
  existing fixed-300-bar-warmup batch semantics as canonical);
- reconcile or merge the divergent `candle_feat_builder.py` ATR (plain
  rolling mean) with `etl_candle_feat.py`'s ATR (Wilder EMA) as a side
  effect — if reconciliation is needed, that is a separate reviewed
  decision, not implicit in a volatility-owner build;
- repurpose `asset_profile_snapshot.realized_volatility` or its composite
  `profile_version` as the volatility owner's version identity;
- depend on `v_volatility_compression_breakout_4h` or
  `v_known_signal_family_4h` (untracked views) as an input or as evidence
  for expansion/compression, since their definitions are not reviewable;
- invent expansion/compression or asymmetry thresholds/semantics — both
  remain `MISSING` and must be designed and reviewed explicitly in the
  follow-up implementation issue, not assumed here;
- touch `range_state.py`/`structure_state` (PRICE_STRUCTURE family),
  `sector_rotation_engine_v1.py` dispersion (cross-sectional, different
  family), or any of the execution/display-context ATR modules (`#688`
  Manual SHORT Trader Profit Plan, fib navigation map) — all are out of
  scope and must remain independent.

## Recommended next implementation lane

Create a bounded follow-up design/implementation slice (new issue, e.g.
"Build minimal canonical VOLATILITY evidence producer") for one
market-only, production-safe VOLATILITY evidence owner, following the
`src/features/momentum_evidence_snapshot_v1.py` pattern (#741/#742/#746).
Before it may supply #617, that owner must define and validate:

1. an explicit producer namespace under `src/features/`, distinct from all
   existing ATR/realized-volatility readers identified above;
2. which raw numeric fields it emits — likely `atr_value` (recomputed
   canonically from raw candle true range, full contiguous pre-asof
   history, matching the #741/#742/#746 pattern, not reusing
   `feat_candle.atr_14` in place) and, if retained, a distinctly versioned
   realized-volatility field rather than reusing
   `asset_profile_snapshot.realized_volatility`;
3. `input_interval`, `lookback_horizon` (e.g. the ATR period), an explicit
   `effective_horizon` (declared, not inferred from candle interval), and
   `observed_lifecycle` (may start `UNMEASURED`) per #243's `SignalHorizonV1`
   contract;
4. explicit `asof_ts`, producer-owned freshness
   (`FRESH`/`STALE`/`INSUFFICIENT_DATA`/`UNKNOWN`), fail-closed behavior for
   a future `asof`, and fail-closed behavior for any gap in the pre-asof
   contiguous history (no stitching across gaps), mirroring #741/#742/#746;
5. `model_id`/`model_version` and deterministic provenance sufficient for
   replay;
6. an explicit, separately reviewed decision (not invented by the producer
   build) on whether/how to define expansion/compression and upside/downside
   asymmetry — both are currently `MISSING` and out of scope for a minimal
   first producer unless that follow-up issue explicitly scopes them in;
7. no invented categorical volatility-regime states unless a separately
   reviewed owner already defines them — none currently does.

## Non-goals confirmed for this audit

No dashboard/UI/LED work, no versioned evidence envelope, no new indicator
math or thresholds, no `selection_engine`/`decision_gate`/
`execution_planner`/`executor` changes, no reopening of `#617`'s own
implementation scope, no `#301` composite regime, no `#686` morphology
implementation, and no reconciliation of the divergent ATR formulas found
across the repository — all deferred to the recommended follow-up lane
above or to their own separately owned issues.

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
execution_planner_changed=0
executor_changed=0
reporting_changed=0
thresholds_invented=0
categorical_states_invented=0
617_reopened=0
301_implemented=0
686_implemented=0
```

## Related documents / issues

- `docs/architecture/multi_horizon_signal_contract_v1.md` (#243)
- `docs/architecture/regime_evidence_matrix_audit_v1.md` (#617 Phase A audit, PR #667)
- `docs/architecture/momentum_evidence_canonical_owner_audit_v1.md` (#729, same audit pattern)
- `docs/architecture/momentum_evidence_producer_v1.md` (#741/#742/#746, reference producer pattern)
- `docs/architecture/multi_tf_conviction_contract_v1.md` (#591)
- `docs/architecture/ma_breadth_canonical_owner_audit_v1.md` (#310, same audit pattern)
- `docs/architecture/asset_profile_layer_v1.md`
- #617 regime evidence matrix / multi-TF stack (downstream consumer)
- #747 audit and establish canonical VOLATILITY evidence owner (this audit)
