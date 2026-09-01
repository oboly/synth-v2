# Regime Evidence Matrix — Canonical Owner Audit v1

Status: Permanent architecture audit (blocking finding, no implementation)
Canonical location: `docs/architecture/regime_evidence_matrix_audit_v1.md`
Scope: audit-only — canonical owner inventory for #617 evidence families
Runtime impact: none
Issue: #617 (first slice)
Upstream owner: #243 (`docs/architecture/multi_horizon_signal_contract_v1.md`)

## 1. Purpose

#617 asks for a regime evidence matrix / multi-TF momentum-trend stack on
the dashboard. Before any versioned evidence envelope or dashboard/LED work
can be built, this document audits current `origin/main` for a canonical,
accepted, production-safe producer per required evidence family, per the
`SignalHorizonV1` fields defined in #243.

Per AGENTS.md: merged code does not automatically mean promoted canonical
truth. This audit treats a module's own declared boundary comment as
authoritative over any downstream document's characterization of it.

## 2. Method

For each family: locate the producer module, its persisted table/artifact
(if any), and check for `model_id`/`model_version`, `input_interval`,
`lookback_horizon`, `effective_horizon`, `observed_lifecycle`, `asof_ts`,
freshness/staleness handling, raw numeric values, deterministic reason
codes, and any declared research/production boundary. No new indicator
math, thresholds, or tables were introduced to perform this audit.

## 3. Findings by family

### 3.1 PRICE_STRUCTURE

- Producer: `src/structure/trend_state_v1.py` (`ENGINE_VERSION = "1.2"`),
  driven by `src/measurement/run_structure_state_engine.py`.
- Persisted table: `structure_state` (columns include `asof_ts_utc`,
  `interval_code`, `trend_state`, `trend_score`, `engine_name`,
  `engine_version`).
- `input_interval`: explicit, per-row (`1h`, `4h`, `1d`).
- `lookback_horizon`: implicit in feature inputs (EMA20/EMA50 spread from
  `feat_candle`), not separately exposed.
- `effective_horizon`: not mapped to the #243 enum anywhere.
- `observed_lifecycle`: not measured/exposed.
- `asof_ts`: present (`asof_ts_utc`).
- Freshness: not exposed by the writer; no `FRESH`/`STALE` classification
  found for this table.
- Raw numeric values: yes (`trend_score`, `pullback_score`, `range_score`).
- Reason/evidence codes: categorical states only (e.g. `UPTREND_STRONG`,
  `RANGE`), no itemized reason-code list.
- Classification thresholds (e.g. `0.40/0.30/0.30` weighting, `0.01`/`0.02`
  cutoffs) are hardcoded in `trend_state_v1.py` with no cited empirical
  validation in-repo.
- **Classification: semantically unresolved.** Real production table with
  `asof_ts` and versioning exists, but `effective_horizon` and `freshness`
  are not defined, and existing thresholds are not documented as validated.

### 3.2 RELATIVE_STRENGTH / selective reclaim

- Two independent, non-unified candidates exist:
  1. `reclaim_state` / `reclaim_score` columns in the same `structure_state`
     table above (states: `RECLAIM_CONFIRMED`, `FAILED_RECLAIM`,
     `NO_RECLAIM_ATTEMPT`), same engine, same gaps (no `effective_horizon`,
     no freshness).
  2. `src/features/relative_strength_snapshot.py` →
     `relative_strength_snapshot` table: cross-asset 7d/14d cross-sectional
     ranking from `obs_market_candle`. It persists `snapshot_ts_utc` per
     row (a real as-of timestamp), but there is no `model_version` and no
     declared freshness/staleness rule, and `snapshot_ts_utc` is not
     mapped to the #243 `SignalHorizonV1.asof_ts`/`freshness` contract.
- These two lanes are not declared as the same evidence or reconciled.
- **Classification: semantically unresolved.** No single declared canonical
  owner for "relative strength" as a #617 evidence family; two overlapping,
  independently-scoped lanes with incomplete horizon metadata.

### 3.3 MOMENTUM

- No dedicated production momentum engine (RSI/MACD or equivalent) exists
  on `main`.
- `src/regime/run_active_regime_observation_v1.py` is the closest lane, but
  it is explicitly scoped to one validated hypothesis
  (`H1_BTC_MILD_DECLINE_4H_BOUNCE_CONTEXT`) with all other hypotheses
  (H2–H5) explicitly blocked/untagged, and its own docstring states purpose
  is "for downstream research and future policy routing (not yet
  implemented)."
- Issue #415 (RSI divergence) has zero implementation in `src/`; only
  archive/legacy doc mentions exist (`docs/archive/...`,
  `docs/todo/...`), none of which assert current-main ownership.
- **Classification: MISSING.** No general-purpose momentum evidence family
  exists on `main`.

### 3.4 BREADTH

- Live/production reporting path `src/reporting/market_breath_live_v1.py`
  imports its computation directly from `src/research/run_market_breath_analysis_v1.py`
  and `src/research/market_breath_classifier_v1.py`.
- This means the "live" breadth reporting surface is structurally built on
  a `src/research/`-namespaced module, which AGENTS.md scopes to
  validation/replay/diagnostics, not standing production truth.
- **Classification: semantically unresolved / architecture boundary
  concern.** This is not a #617-resolvable decision — it requires an
  explicit owner decision on whether the research module is promoted (with
  its own review) or a separate production breadth producer is built.
  #617 must not silently treat `src/research` output as production
  evidence to close this gap.

### 3.5 ROTATION

- Producer: `src/research/run_market_rotation_pressure_v1.py`; tables
  `market_rotation_pressure_snapshot_v1` /
  `market_rotation_pressure_observation_v1`
  (`db/migrations/20260712_market_rotation_pressure_v1.sql`).
- The migration file's own header states: `-- Boundary: research-only ·
  market-only · account-agnostic`.
- #243 section 7.1 itself says only: `Owner: existing Rotation Pressure
  market-only lane`, plus a canonical horizon interpretation
  (`lookback_horizon: 24h + 168h`, `effective_horizon: REGIME`,
  `observed_lifecycle: UNMEASURED unless backed by persisted empirical
  analysis`). It does not, in its own text, grant production promotion.
  The stronger phrase "the one canonical, accepted, versioned, persisted
  per-asset lane" is a downstream characterization in
  `docs/architecture/multi_tf_conviction_contract_v1.md` (#591) section 2,
  not #243's own wording.
- Fields present regardless of the boundary question: `model_version`,
  `as_of_ts_utc`, `market_score` (raw), categorical states
  (`acceleration_state`, `concentration_state`, `confirmation_state`), a
  dashboard-side `classify_freshness()` (`FRESH`/`STALE`,
  `DEFAULT_STALE_AFTER≈2h30m`).
- **Classification: semantically unresolved (not a confirmed
  contradiction).** The producer has real operational characteristics
  (writer cadence, freshness, persistence, versioning) that look
  production-grade, but its own migration boundary comment says
  research-only, while #591's contract doc treats it as the canonical
  production lane. #243 §7.1's own text is silent on production-promotion
  status either way. #617 cannot resolve this by itself — it requires an
  explicit, reviewed promotion decision for
  `market_rotation_pressure_snapshot_v1`: either update the migration's
  boundary comment to reflect an already-made promotion decision, or
  correct #591 section 2's "canonical, accepted" characterization if the
  table is in fact still research-only.

### 3.6 VOLATILITY

- No persisted production volatility-regime table or classifier exists.
- The only ATR usage found, `src/market_context/local_ma_atr_context_v1.py`,
  computes ATR purely as an exit-context tick-distance parameter for the
  Manual SHORT Trader Profit Plan — a different scope, already flagged as
  unrelated by the #591 contract doc.
- **Classification: MISSING.**

### 3.7 MACRO / LIQUIDITY

- GitHub Issue #305 ("Macro regime engine input inventory and deterministic
  classifiers") is confirmed `OPEN` via the GitHub Issue itself (not the
  frozen `docs/todo/` reference doc, which is legacy/non-authoritative per
  `AGENTS.md`). No canonical macro classifier exists in `src/` on `main`.
- The closest artifact, `market_global_snapshot_v1` (`btc_dominance_pct`,
  `eth_dominance_pct`, `as_of_ts_utc`), is a raw ingestion side-table
  embedded in the Rotation ETL pipeline, not a standalone macro producer —
  no classifier, no `effective_horizon`, no freshness contract.
- A second, non-versioned, apparently orphaned table/ETL
  (`market_global_snapshot`, `src/etl/coingecko/etl_coingecko_global.py`)
  also exists and does not appear wired into any current runner/cron.
- **Classification: MISSING** as an evidence family (raw ingestion data
  exists; no accepted classifier or owner).

### 3.8 ETH/BTC leadership

- No distinct producer exists. `market_global_snapshot_v1` carries raw
  BTC/ETH dominance percentages (see 3.7) but no leadership classification.
- `src/features/relative_strength_snapshot.py` is generic asset-vs-market,
  not BTC/ETH-specific.
- A research-only sector-rotation dataset builder has unused
  `relative_strength_vs_btc` / `relative_strength_vs_eth` columns, not
  consumed by any production path.
- **Classification: MISSING / not distinct** from general relative
  strength on `main` today.

## 4. Summary table

```text
family                  status                    owner/table
PRICE_STRUCTURE         semantically unresolved    structure_state (trend_state_v1 1.2)
RELATIVE_STRENGTH       semantically unresolved    structure_state.reclaim_* + relative_strength_snapshot (unreconciled)
MOMENTUM                MISSING                     none (active_regime_observation is a single narrow hypothesis, not general)
BREADTH                 semantically unresolved    market_breath_live_v1 built on src/research module
ROTATION                semantically unresolved    market_rotation_pressure_snapshot_v1 (migration says research-only; #591 characterizes it as canonical, #243 §7.1 itself is silent on promotion)
VOLATILITY              MISSING                     none
MACRO/LIQUIDITY         MISSING                     market_global_snapshot_v1 (raw only, #305 open)
ETH/BTC leadership      MISSING                     none distinct
```

No family on current `main` cleanly satisfies "accepted, production-safe,
versioned, freshness-and-horizon-complete owner." Per the #617 task
contract's Decision B, this blocks implementation of the versioned
evidence envelope in this slice.

## 5. Required owner/promotion decisions before an evidence envelope can be built

1. **Rotation promotion status** — a reviewed decision on whether
   `market_rotation_pressure_snapshot_v1` is production or research-only.
   If production, the migration's boundary comment must be corrected by
   its owning issue; if research-only, #591 section 2's "canonical,
   accepted" characterization needs a correction pass. #617 must not
   decide this unilaterally.
2. **PRICE_STRUCTURE / RELATIVE_STRENGTH `effective_horizon` and
   freshness mapping** — the `structure_state` engine owner must define
   `effective_horizon` (per #243 §3.3) and a freshness/staleness rule for
   its own table before #617 can cite it as evidence.
3. **RELATIVE_STRENGTH reconciliation** — `structure_state.reclaim_*` and
   `relative_strength_snapshot` need a single declared canonical owner (or
   an explicit statement that they are distinct evidence items), not
   inference by #617.
4. **BREADTH production/research boundary** — `market_breath_live_v1`'s
   dependency on `src/research/*` needs an explicit promotion review (or a
   dedicated production breadth producer), owned outside #617.
5. **MOMENTUM owner** — no issue currently owns a general momentum family;
   #415 (RSI divergence) has no implementation to promote. A new or
   re-scoped issue is needed before momentum evidence can exist.
6. **VOLATILITY owner** — no issue currently owns a general volatility
   regime family; needs a new issue.
7. **MACRO/LIQUIDITY and ETH/BTC leadership** — GitHub Issue #305 is
   confirmed `OPEN` and already owns this space; #617 has no authority to
   invent a classifier in its place.

## 6. Non-goals confirmed for this slice

Per the #617 task contract, this audit performs no dashboard/UI/LED work,
no versioned evidence envelope, no new indicator math or thresholds, no
`selection_engine`/`decision_gate`/`execution_planner`/`executor` changes,
no account awareness, and no promotion of any research-only source to
production status.

## 7. Safety

```text
architecture_contract_only=1
audit_only=1
market_ranking_changes=0
account_awareness_added=0
decision_permission_changes=0
execution_planning_changes=0
executor_changes=0
selection_engine_changes=0
dashboard_changed=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_mutation_performed=0
production_deploy=0
```

## 8. Related documents / issues

- `docs/architecture/multi_horizon_signal_contract_v1.md` (#243)
- `docs/architecture/multi_tf_conviction_contract_v1.md` (#591)
- `docs/todo/market_intelligence/macro_regime_engine_v1.md` (#305)
- `db/migrations/20260712_market_rotation_pressure_v1.sql`
- #593 multi-horizon per-asset Rotation research/history (research-only)
- #449 Rotation Flip research
- #415 RSI divergence research (unimplemented on `main`)
- #617 regime evidence matrix / multi-TF momentum-trend stack (this audit)
