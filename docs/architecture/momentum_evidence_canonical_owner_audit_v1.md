# MOMENTUM Evidence Canonical Owner Audit v1

Status: Phase A audit complete; no implementation
Canonical location: `docs/architecture/momentum_evidence_canonical_owner_audit_v1.md`
Issue: #729 (this audit); downstream consumer contract: #617
Upstream owner: #243 (`docs/architecture/multi_horizon_signal_contract_v1.md`)
Audited baseline: `origin/main` at `330d2fb8`
Scope: market-only, account-agnostic; no DB or runtime mutation

## Decision

`BUILD_MINIMAL_CANONICAL_OWNER`

No existing module on current `main` is an acceptable canonical MOMENTUM
evidence owner for #617. This confirms and extends the prior finding in
`docs/architecture/regime_evidence_matrix_audit_v1.md` section 3.3
(`MOMENTUM: MISSING`), which was produced under PR #667 and remains accurate:
no MACD/oscillator producer of any kind exists anywhere in the repository
(production, research, or reporting), and the one raw momentum-adjacent
value that does exist (`feat_candle.rsi_14`) is a feature-layer primitive
consumed by multiple downstream paths — including a selection-local
composite score, an operational signal-engine query, and a research
validation script — none of which independently exposes, versions, or
contracts `rsi_14` as standalone #243-compliant canonical evidence. None of
these paths constitutes a canonical MOMENTUM evidence owner, and none can be
promoted to that role by a small adapter alone.

```text
MACD_PRODUCER_EXISTS=0
RSI_RAW_PRIMITIVE_EXISTS=1 (feat_candle.rsi_14, not independently contracted)
GENERAL_MOMENTUM_EVIDENCE_OWNER_EXISTS=0
```

This is Phase A: audit only. No indicator math, thresholds, tables, or
runners are introduced by this document. A minimal canonical MOMENTUM
evidence owner must be designed and built in a separate, explicitly scoped
follow-up issue/PR before #617 may consume MOMENTUM evidence.

## Audit method

Searched current `main` for: MACD, oscillator, momentum, RSI, histogram,
signal line/crossover, divergence, inflection, EMA fast/slow, multi-timeframe
trend/momentum, `active_regime_observation`, feature builders, `signal_engine`,
reporting calculations, persisted indicator/state tables, research-only #415,
and any post-#667 implementation. Reviewed `docs/architecture/` in full,
`docs/architecture/multi_horizon_signal_contract_v1.md` (#243),
`docs/architecture/regime_evidence_matrix_audit_v1.md` (#617 Phase A audit,
merged via PR #667), `docs/architecture/multi_tf_conviction_contract_v1.md`
(#591), `docs/architecture/rotation_pressure_v1_authority_audit_v1.md` and
`rotation_pressure_v1_canonical_promotion_v1.md`, `docs/research/synth_v215_signal_inventory_matrix_v1.md`,
and `git log 93b5a7bd..origin/main` (93b5a7bd = PR #667 merge; 175 commits,
none touching MACD/RSI/oscillator/momentum production code). No dedicated
architecture doc exists yet for #301, #415, or #449; each is referenced only
inside #243 section 7 and the #617 audit, both of which state their scope is
unimplemented on `main` (#415, #449) or out of this contract's scope (#301).

No indicator calculation, threshold, band, persistence, timer, runtime, or
reporting change was made. Raw numeric values remain the only candidate
primary truth; no categorical momentum states are proposed by this audit.

## Candidate-owner inventory

### 1. `feat_candle.rsi_14`: raw production primitive, not a contracted evidence owner

- Producer: `src/features/etl_candle_feat.py::compute_rsi` (Wilder-style
  RSI, period 14), invoked by `src.features.run_feat_candle`
  (`src/features/run_feat_candle.py`), refreshed by the active 4h runtime
  chain (`scripts/run_chain_4h.sh`) per
  `docs/research/synth_v215_signal_inventory_matrix_v1.md`.
- Persistence: `feat_candle` table, columns include `close_ts_utc`,
  `interval_code`, `rsi_14`, `ema_20`, `ema_50`, `atr_14`,
  `volume_ratio_20`, `volume_zscore_20`, plus derived `price_vs_ema20`,
  `price_vs_ema50`, `ema_spread`, `ema_spread_pct`.
- Market scope: per enabled asset, per `(candle_id, asset_id, venue,
  interval_code)`.
- `model_id` / `model_version`: absent. No version column on `feat_candle`
  and no versioned model identity attached to the RSI calculation.
- `input_interval`: explicit per row (`interval_code`); active chain
  currently refreshes `4h`.
- `lookback_horizon`: implicit only (`period=14` bars baked into
  `compute_rsi`); not exposed as a separate field.
- `effective_horizon`: absent; not mapped to the #243 enum anywhere.
- `observed_lifecycle`: absent/unmeasured.
- `asof_ts`: `close_ts_utc` exists and is real, but there is no per-row
  `freshness` classification (`FRESH`/`STALE`/`INSUFFICIENT_DATA`) exposed
  by the writer itself; freshness is only enforced indirectly by the chain's
  own eligibility gate (`docs/research/synth_v215_signal_inventory_matrix_v1.md`
  line 47), not by a `feat_candle`-owned contract field.
- Replay safety: writer is deterministic per historical candle window; no
  wall-clock fallback observed in `etl_candle_feat.py`. Not itself a problem,
  but replay-facing `evaluated_at` is not exposed.
- Raw numeric fields: yes (`rsi_14`).
- State/classification fields: none (raw only) at this layer.
- Reason codes / provenance: none beyond `close_ts_utc`/`interval_code`.
- Downstream use is multi-path, not exclusive to one consumer. Direct
  readers of `feat_candle.rsi_14` on current `main`:
  - **Selection/signal consumer:**
    `src/signal_engine/run_signal_state_etl.py` (lines 122, 346, 351) folds
    `rsi_14` (weight `0.15`) into a composite `pullback_quality_score`
    alongside EMA/volume terms with hardcoded weights. This is a
    selection-local composite feature, not standalone momentum evidence.
  - **Operational/runtime consumer:** `src/engine/run_signal_engine.py`
    (line 75) selects `fc.rsi_14` in its `feat_candle` query, but no
    `classify_*` function or `SignalEngineInput` field in this engine
    (`src/signal_engine/signal_engine.py`,
    `build_signal_engine_input` in `run_signal_engine.py`) reads or scores
    it — the column is fetched but not consumed by this engine's
    trend/volume/phase/compass/rotation/relative/setup/risk classifiers.
    It is not a MOMENTUM evidence path in this engine today.
  - **Research/validation consumer:**
    `src/research/run_breath_curve_symbol_regime_validation_v1.py`
    (`classify_rsi`, lines 310-320) buckets `rsi_14` into an ad hoc
    `RSI_LOW`/`RSI_MID`/`RSI_HIGH`/`RSI_EXTREME` categorical scheme for a
    research validation report only. This is a research-only categorical
    invention, confined to `src/research/`, with no `model_id`/version/
    freshness/horizon fields; it must not be read back as a canonical
    MOMENTUM evidence contract per this task's constraints.
  - **Reporting consumer:** `src/ui_chart/chart_renderer.py` (`show_rsi` /
    `"RSI 14"` subplot, via `chart_repository.py` and `chart_config.py`)
    only plots the value it is given; it does not compute RSI itself, so
    this is a correctly read-only reporting consumer, not a dashboard-owned
    indicator-truth violation.
  - None of these four paths defines, versions, or exposes `rsi_14` as
    independently addressable, #243-contracted MOMENTUM evidence; per this
    task's constraints, none may be treated as an implicitly promoted
    general-purpose MOMENTUM owner.
- **Classification: reusable production primitive, not a canonical MOMENTUM
  evidence owner.** The raw value is real, live, and deterministic, but it
  carries none of the #243 `SignalHorizonV1` provenance/freshness/version
  fields and is not independently addressable as evidence — it is buried
  inside a different feature's composite score. Adding the missing
  `model_id`/`model_version`/`effective_horizon`/freshness/provenance fields
  to `feat_candle` itself, or standing up a dedicated evidence table that
  cites `feat_candle.rsi_14` as an input, is schema/producer-level work, not
  a small adapter.

### 2. MACD / oscillator / histogram / signal line / crossover: no implementation anywhere

- Repository-wide case-insensitive search for `macd`, `oscillator`,
  `histogram`, `signal line`, and `crossover` returns zero production or
  research code matches. The only `macd` occurrence in the entire repository
  is the sentence in `docs/architecture/regime_evidence_matrix_audit_v1.md`
  line 78 stating that no such engine exists.
- No `macd_value`, `signal_value`, `histogram_value`, or `histogram_delta`
  field, table, or migration exists anywhere in `db/`, `database/`, or
  `src/`.
- **Classification: MISSING.** There is no research-only, reporting-only, or
  production implementation to reuse, promote, or adapt.

### 3. `src/regime/run_active_regime_observation_v1.py`: single validated hypothesis, not general momentum

- Persists to an `active_regime_observation`-style table (per its own
  runner) but is explicitly scoped, by its own docstring and
  `make_hypothesis_tags`, to exactly one validated hypothesis
  (`H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT`); hypotheses H2-H5 remain
  untagged/blocked in code (`# H1 is the only validated hypothesis`).
- Its own docstring/purpose is "for downstream research and future policy
  routing (not yet implemented)."
- No `model_id`/`model_version`, no `effective_horizon`/`observed_lifecycle`
  mapping, no raw numeric momentum field — output is a narrow categorical
  hypothesis tag, not general momentum evidence.
- **Classification: research-only, narrow single-hypothesis lane.** Not a
  candidate general-purpose MOMENTUM owner; must not be broadened or
  repurposed by #617/#729.

### 4. `src/features/momentum_persistence_snapshot.py`: distinct feature family, not oscillator momentum

- Persists to `momentum_persistence_snapshot` (`snapshot_ts_utc`,
  `asset_id`, `lookback_days`, `up_days`/`down_days`/`flat_days`,
  `green_ratio`, `mean_daily_return_pct`, `std_daily_return_pct`,
  `persistence_score`), computed from daily-candle green/red-day streaks
  over 7d/14d windows.
- This measures return-day persistence/streakiness, not price-oscillator
  momentum (no EMA/MACD/RSI math anywhere in the module). It answers a
  different question than #617's MACD/RSI/oscillator request and must not
  be conflated with it.
- No `model_id`/`model_version`, no `effective_horizon`/`observed_lifecycle`,
  no per-row freshness classification; `snapshot_ts_utc` exists as an
  as-of timestamp only.
- **Classification: distinct existing feature, not a MOMENTUM-family
  candidate.** Named "momentum" but semantically unrelated to the
  MACD/RSI/oscillator evidence family #617 needs; flagged only so it is not
  mistaken for that family or duplicated against.

### 5. `#415` RSI divergence and `#449` Rotation Flip: confirmed unimplemented, not touched

- Repository-wide search for divergence/inflection logic and for any
  Rotation-Flip-named module finds no `src/` implementation. This matches
  `regime_evidence_matrix_audit_v1.md`'s finding that #415 "has zero
  implementation in `src/`; only archive/legacy doc mentions exist." No
  post-#667 commit changes this (`git log 93b5a7bd..origin/main`).
- `#449` is referenced only as "Rotation Flip research" in #243 section 15's
  related-issues list; no dedicated architecture doc or `src/` module exists.
- This audit does not implement, duplicate, or narrow either issue's future
  scope. Neither is a MOMENTUM-owner candidate today.

### 6. `#301` composite regime and `#591` conviction: consumers, not producers, of momentum

- `docs/architecture/multi_tf_conviction_contract_v1.md` (#591) defines a
  conviction contract that consumes already-produced #243-compliant
  evidence (it cites Rotation Pressure V1 as its only currently-accepted
  input); it does not compute or own momentum evidence itself.
- No dedicated `#301` composite-regime architecture doc exists yet. #243
  section 6 forbids exactly the pattern a composite-regime momentum
  shortcut would require (`mean(SHORT, MID, LONG, REGIME)`,
  "weighted opaque consensus without a separate reviewed owner"). Neither
  issue is a MOMENTUM producer candidate.

## Persisted artifacts and consumer chain

```text
obs_market_candle
  -> feat_candle (ema_20, ema_50, atr_14, rsi_14 — raw per-asset primitives, no #243 contract fields)
     -> src/signal_engine/run_signal_state_etl.py (rsi_14 folded into pullback_quality_score composite, weight 0.15)
     -> src/engine/run_signal_engine.py (selects rsi_14 in query; not read by any classifier — unused in this engine's output)
     -> src/research/run_breath_curve_symbol_regime_validation_v1.py (rsi_14 -> ad hoc RSI_LOW/MID/HIGH/EXTREME research bucket; research-only)
     -> src/ui_chart/chart_renderer.py (reads rsi_14 for display only)

No current path:
  -> macd_value / signal_value / histogram_value / histogram_delta (none exist)
  -> standalone, versioned, #243-compliant MOMENTUM evidence table
  -> #617 read-only consumption
```

No timer or runner computes MACD anywhere in the production runtime
inventory. No selection, decision, planner, executor, broker, or order
dependency was found in any candidate module reviewed above.

## Required next step for #729/#617

Create a bounded follow-up design/implementation slice for one minimal,
market-only, production-safe MOMENTUM evidence owner. Before it may supply
#617, that owner must define and validate:

1. an explicit producer namespace (`src/features/` or `src/signal_engine/`,
   consistent with AGENTS.md layer definitions) that is distinct from all
   existing `rsi_14` readers identified above (the selection-local
   `pullback_quality_score` composite, the `run_signal_engine.py` query, and
   the research validation script);
2. which raw numeric fields it emits — prefer `macd_value`, `signal_value`,
   `histogram_value`, `histogram_delta`, and, if RSI is retained as part of
   this family, a distinctly versioned `rsi_value` rather than reusing
   `feat_candle.rsi_14` in place;
3. `input_interval`, `lookback_horizon` (e.g. the 12/26/9 EMA windows for
   MACD), `effective_horizon` (declared, not inferred from candle interval
   per #243 section 3.3), and `observed_lifecycle` (may be `UNMEASURED`
   initially) per the #243 `SignalHorizonV1` contract;
4. explicit `asof_ts`, producer-owned `freshness`
   (`FRESH`/`STALE`/`INSUFFICIENT_DATA`/`UNKNOWN`), and fail-closed behavior
   for a future `asof` or unsupported `model_version`;
5. `model_id`/`model_version` and deterministic provenance sufficient for
   replay;
6. no invented categorical momentum states (e.g. no `MOMENTUM_REVERSAL`/
   `EARLY_UP`) unless a separately reviewed owner already defines them —
   none currently does;
7. replay-safe historical access with an explicit `evaluated_at` where
   replay-facing, with no implicit wall-clock or latest/current fallback.

The future owner may reuse `feat_candle`'s already-computed EMA/RSI values as
raw inputs where suitable, but must not repurpose the existing selection-local
`pullback_quality_score` composite, the unused `rsi_14` query column in
`run_signal_engine.py`, the research-only `RSI_LOW`/`MID`/`HIGH`/`EXTREME`
bucket in `run_breath_curve_symbol_regime_validation_v1.py`,
`active_regime_observation`'s single hypothesis, or
`momentum_persistence_snapshot`'s return-persistence metric as
that owner. It remains market-only and must not alter `selection_engine`,
`decision_gate`, `execution_planner`, `executor`, broker, or orders, and must
not duplicate #415 (RSI divergence) or #449 (Rotation Flip).

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
415_duplicated=0
449_duplicated=0
```

## Related documents / issues

- `docs/architecture/multi_horizon_signal_contract_v1.md` (#243)
- `docs/architecture/regime_evidence_matrix_audit_v1.md` (#617 Phase A audit, PR #667)
- `docs/architecture/multi_tf_conviction_contract_v1.md` (#591)
- `docs/architecture/rotation_pressure_v1_authority_audit_v1.md`
- `docs/architecture/ma_breadth_canonical_owner_audit_v1.md` (#310, same audit pattern)
- `docs/research/synth_v215_signal_inventory_matrix_v1.md`
- #415 RSI divergence (unimplemented on `main`)
- #449 Rotation Flip research (unimplemented on `main`)
- #617 regime evidence matrix / multi-TF momentum-trend stack (downstream consumer)
- #729 audit and establish canonical MOMENTUM evidence owner (this audit)
