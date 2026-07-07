# Market Observer Measured-Input Inventory v1

## Status

Docs-only evidence inventory. No `market_observer` implementation, sector
implementation, external-overlay ingestion, dashboard change, DB change,
migration, scheduler work, deployment, or execution-related code is
introduced by this document.

## Purpose

Before any `market_observer_v1` implementation, this document records what
deterministic, market-only evidence already exists in this repository for
each proposed `MarketObserverSnapshot` field, what is genuinely missing, and
the smallest honest first implementation bundle (P0-B). No capability is
inferred or invented: every "available" claim below cites an exact existing
module, function, table, or migration; every "missing" claim states that no
such owner was found by direct inspection.

## Sources Read

- `docs/architecture/market_observer_contract_v1.md`
- `docs/architecture/external_research_overlay_contract_v1.md`
- `docs/architecture/pipeline_contracts.md`
- `docs/architecture/module_architecture.md`
- `docs/architecture/breath_fibo_synth_framework_contract_v1.md`
- `docs/architecture/multi_horizon_aplus_breathline_strategy_contract_v1.md`
- `docs/research/canonical_regime_context_source_v1.md`
- `docs/research/sector_module_design.md`
- `docs/research/live_like_shadow_chain_v1.md`
- `docs/research/shadow_heartbeat_outcome_validation_v1.md`

## Source Paths Inspected

```text
src/market_context/contracts_v1.py
src/market_context/market_context_builder_v1.py
src/market_context/local_ma_atr_context_v1.py
src/market_context/impulse_health_state_v1.py
src/regime/run_active_regime_observation_v1.py
src/market_data/fib_navigation_map_v1.py
src/market_data/native_short_fib_context_v1.py
src/market_data/native_short_map_lifecycle_v1.py
src/market_data/native_short_scope_status_v1.py
src/features/relative_strength_snapshot.py
src/features/volume_confirmation_snapshot.py
src/features/candle_loader.py
src/etl/coingecko/etl_coingecko_global.py
src/asset_profile/models.py
src/asset_profile/asset_profile_engine_v1.py
src/research/multi_horizon_fib_contract_v1.py
tests/test_pipeline_contract_boundaries_v1.py
db/migrations/ (searched for market_global_snapshot, relative_strength_snapshot,
  volume_confirmation_snapshot, asset_profile_snapshot, sector*)
```

All source inspection was performed against `origin/main` at commit `9cfeddf`
(worktree `docs/market-observer-measured-input-inventory-v1`, branched from
fresh `origin/main`).

---

## Part 1 — Proposed `MarketObserverSnapshot` Field Inventory

### `canonical_global_regime`

| Attribute | Finding |
|---|---|
| Availability | **IMPLEMENTED** |
| Owner module/symbol | `src/regime/run_active_regime_observation_v1.py::build_observations` → `global_regime` |
| DB source | table `active_regime_observation`, migration `db/migrations/20260514_active_regime_observation_v1.sql` |
| Source data / venue | `obs_market_candle`, BTC 24h/72h returns, default venue `bitvavo` |
| Interval / as-of | interval-specific (`--interval`, default `4h`); `asof_ts_utc` + `source_candle_ts_utc` explicit; join rule = latest row at-or-before `event_ts_utc` for the same venue+interval (per `canonical_regime_context_source_v1.md`) |
| Freshness behavior | canonical docs define `asof_ts_utc`/`source_candle_ts_utc` but **do not** define a downstream freshness threshold; historical joins must expose `regime_freshness=UNKNOWN` until a canonical rule exists |
| Deterministic inputs already available | full row already computed and persisted: `global_regime`, `global_regime_version`, `validation_status`, `validated_hypothesis_tags_json` |
| Missing primitives | none for pure forwarding; a canonical freshness-threshold rule is undefined upstream |
| Forbidden dependencies | none — market-only, account-agnostic per source contract |
| Shadow-writer eligible | **YES** — pure read/forward, no new computation |
| Note | No inferred or invented capabilities; forwarding only. |

### `canonical_asset_class_regimes`

| Attribute | Finding |
|---|---|
| Availability | **IMPLEMENTED** |
| Owner module/symbol | same runner, `asset_class_regime` / `global_class_regime` per asset-class row |
| DB source | same table/migration as above |
| Source data / venue | same candle source; `classify_asset_class(symbol)` maps a symbol to one of `BTC, ETH, MEME, DEFI, AI, L1_L2, INFRA, OTHER` |
| Interval / as-of | same as global regime; row grain is one row per `(venue, interval_code, asof_ts_utc, asset_class, regime versions)` |
| Freshness behavior | same `UNKNOWN`-until-defined rule |
| Deterministic inputs already available | `asset_class_regime`, `class_return_24h_pct`, `relative_class_vs_btc_24h_pct` |
| Missing primitives | `classify_asset_class` is defined inside a `run_`-prefixed runner script, not a shared library/contracts module — importable today, but not in a conventional shared-primitive location |
| Forbidden dependencies | none |
| Shadow-writer eligible | **YES** for forwarding; relocating `classify_asset_class` to a shared module is a small housekeeping item, not a blocker |
| Note | No inferred or invented capabilities; forwarding only. |

### `btc_structure_state`

| Attribute | Finding |
|---|---|
| Availability | **PARTIAL** |
| Owner module/symbol | none exists for this exact vocabulary (`RANGE_STABLE`, `RANGE_UNRESOLVED`, `BREAKOUT_UP`, `BREAKDOWN_RISK`, `BREAKDOWN_CONFIRMED`) |
| Source data / venue | generic per-symbol builders `src/market_context/local_ma_atr_context_v1.py::build_local_ma_atr_context` and `src/market_context/impulse_health_state_v1.py::build_impulse_health_state` are symbol-agnostic and can be called with BTC candles today |
| Interval / as-of | both builders take `now_utc` + a candle sequence and internally check `now_utc - latest.close_ts_utc` against a `stale_after` timedelta (default 4h) |
| Freshness behavior | `STALE` / `LOW_CONFIDENCE` / `NO_DATA` sentinel states already returned by both builders |
| Deterministic inputs already available | `LocalMaAtrState` (`ABOVE_MA`/`BELOW_MA`/`EXTENDED_ABOVE_MA`/`RECLAIMING_MA`/`SPIKE_COOLING`/`TESTING_MA`) and `ImpulseHealthState` (`HEALTHY_IMPULSE`/`BLOW_OFF_SPIKE`/`DISTRIBUTION_RISK`/etc.) computed from BTC's own candles |
| Missing primitives | a bounded mapping function from the existing `(local_ma_atr_state, impulse_health_state)` pair to the observer's `btc_structure_state` vocabulary — analogous in shape to the existing `build_extension_context()` mapping in `market_context_builder_v1.py`, but does not exist for this vocabulary |
| Forbidden dependencies | none |
| Shadow-writer eligible | **NOT YET** — requires the bounded mapping above before any writer |
| Note | No inferred or invented capabilities; the underlying sensors exist, the observer-vocabulary mapping does not. |

### `eth_relative_strength_state`

| Attribute | Finding |
|---|---|
| Availability | **PARTIAL** (numerically close to complete) |
| Owner module/symbol | `run_active_regime_observation_v1.py::build_observations` already computes `relative_class_vs_btc_24h_pct` for the `ETH` asset-class row (`class_return_24h_pct - btc_return_24h_pct`) and persists it |
| Source data / venue | same `active_regime_observation` row already covers ETH as its own asset class |
| Interval / as-of | same as canonical regime (interval-specific, `asof_ts_utc`) |
| Freshness behavior | same `UNKNOWN`-until-defined rule |
| Deterministic inputs already available | `relative_class_vs_btc_24h_pct` for `asset_class="ETH"` is a ready-made, already-persisted ETH-vs-BTC relative return |
| Missing primitives | a bounded threshold classifier turning that already-stored numeric value into `OUTPERFORMING_BTC` / `NEUTRAL_TO_BTC` / `UNDERPERFORMING_BTC` (no new data fetch required) |
| Forbidden dependencies | none |
| Shadow-writer eligible | **YES**, once the small threshold mapping exists — this is the smallest gap of any non-forwarding field found |
| Note | No inferred or invented capabilities; only bucketing an existing number. |

### `alt_breadth_state`

| Attribute | Finding |
|---|---|
| Availability | **PARTIAL** |
| Owner module/symbol | `run_active_regime_observation_v1.py::build_observations` already computes and persists `avg_alt_return_24h_pct` (mean 24h return across all non-BTC assets) |
| Source data / venue | same candle source, same row |
| Interval / as-of | same as canonical regime |
| Freshness behavior | same `UNKNOWN`-until-defined rule |
| Deterministic inputs already available | `avg_alt_return_24h_pct`; `src/features/relative_strength_snapshot.py` also computes per-asset `rank_pct`/`zscore` against the full universe on `1d` closes (table `relative_strength_snapshot`, migration not found in `db/migrations/` — schema provenance unverified in this repo) |
| Missing primitives | a breadth **ratio** (`coins_up / coins_active`, per the pattern documented in `sector_module_design.md`) is not computed anywhere; only the mean return is available, not participation width |
| Forbidden dependencies | none |
| Shadow-writer eligible | **NOT YET** — the mean-return field alone cannot distinguish `NARROW` from `BROADENING`; the up/down ratio must be added (small, bounded — the per-asset return dict already exists in-memory inside `build_observations` and is discarded) |
| Note | No inferred or invented capabilities. |

### `sector_rotation_states`

| Attribute | Finding |
|---|---|
| Availability | **MISSING** |
| Owner module/symbol | none. `module_architecture.md` lists `sector_snapshot_v1` and `sector_rotation_state_v1` as `PLANNED` |
| Source data / venue | none — no `sector`, `asset_sector_map`, or `sector_snapshot` tables exist |
| Interval / as-of | n/a |
| Freshness behavior | n/a |
| Deterministic inputs already available | none. `src/asset_profile/models.py::AssetProfileSnapshot.sector_group_code` is explicitly `None`, with the engine comment `"sector_group_code intentionally null in v1; clustering comes later"` |
| Missing primitives | full taxonomy, asset-sector map, sector snapshot builder, breadth/leader-contribution measurement, and rotation-state classifier — the entire chain described in `docs/research/sector_module_design.md` |
| Forbidden dependencies | none identified, but full build is out of scope for any inventory-stage bundle |
| Shadow-writer eligible | **NO** |
| Note | No inferred or invented capabilities; this field is fully unimplemented. |

### `symbol_contexts` (`MarketNavigationState`)

| Attribute | Finding |
|---|---|
| Availability | **PARTIAL** — contract exists, no runtime producer |
| Owner module/symbol | `src/market_context/contracts_v1.py::MarketNavigationState` is a frozen dataclass contract only. Repo-wide search found it **instantiated in exactly one place**: `tests/test_pipeline_contract_boundaries_v1.py:209`, inside a boundary test. No production module builds this dataclass. |
| Source data / venue | n/a — no producer |
| Interval / as-of | n/a — no producer |
| Freshness behavior | contract defines `FreshnessState` (`NO_DATA`/`STALE`/`LOW_CONFIDENCE`/`FRESH`) but nothing assigns it at runtime |
| Deterministic inputs already available | three of six sub-states already have real, independent, deterministic builders: `fib_map_state` vocabulary is producible via `src/market_data/fib_navigation_map_v1.py::build_fib_navigation_map` (its local `MAP_STATE_*` string constants match `contracts_v1.FibMapState` values exactly); `local_ma_atr_state` via `local_ma_atr_context_v1.py`; `impulse_health_state` via `impulse_health_state_v1.py`. `src/market_context/market_context_builder_v1.py::build_market_context_for_symbol` already combines the latter two (plus a derived `extension_context`) into an ad hoc dict — but that dict is **not** `MarketNavigationState`-shaped (no `navigation_regime`, `fib_map_state`, `fib_map_confidence`, `timing_state`, or top-level `freshness_state`). |
| Missing primitives | (1) the assembler/aggregator that combines fib map state + local MA/ATR state + impulse state into `navigation_regime` and `timing_state`, and (2) the actual `MarketNavigationState` writer/builder function. Neither exists today. |
| Forbidden dependencies | none |
| Shadow-writer eligible | **NOT YET** — assembling `navigation_regime`/`timing_state` is a genuine classification decision (comparable in scope to `build_extension_context`), not pure forwarding, so it does not qualify as a "tiny bounded primitive gap" |
| Note | No inferred or invented capabilities. This is the single largest correction to the assumption in the task brief that `MarketNavigationState` forwarding is "existing" — it is not; only its contract and some of its sub-state builders exist. |

### `freshness_state` (top-level observer field)

| Attribute | Finding |
|---|---|
| Availability | **PARTIAL** |
| Owner module/symbol | no single shared helper; the same idiom is independently reimplemented at least three times: `local_ma_atr_context_v1.py` (`now_utc - latest.close_ts_utc > stale_after`, default 4h), `impulse_health_state_v1.py` (same idiom, own constant), `native_short_fib_context_v1.py` (`FRESHNESS_FRESH` / `FRESHNESS_STALE_PRIMARY_4H` / `FRESHNESS_STALE_SUPPORT_1H` with its own hour constants) |
| Source data / venue | candle `close_ts_utc` vs. an injected `now_utc`/`as_of_utc` in every case — deterministic, replay-safe |
| Interval / as-of | per-module thresholds, not unified |
| Freshness behavior | pattern is sound and consistently deterministic (never wall-clock `datetime.now()` inside the comparison itself — caller injects `now_utc`) |
| Deterministic inputs already available | the comparison idiom itself, three independent times |
| Missing primitives | a single shared "candle-as-of freshness" primitive does not exist; an observer-level `freshness_state` would need to roll up whichever per-field freshness values are actually populated (most of which, per above, do not exist yet) rather than invent a new computation |
| Forbidden dependencies | none |
| Shadow-writer eligible | only as a rollup of whatever underlying fields are actually produced in a given bundle — not independently |
| Note | No inferred or invented capabilities. |

### `evidence_refs`

| Attribute | Finding |
|---|---|
| Availability | **MISSING** as a shared schema |
| Owner module/symbol | none. Grep for `evidence_ref`/`evidence_note`/`provenance` found only informal, ad hoc field names inside a few `src/reporting/` and `src/research/` scripts (`account_scoped_short_trader_dashboard_v1.py`, `run_manual_short_trader_profit_plan_v1.py`, `run_canonical_fib_map_source_audit_v1.py`, `run_canonical_fib_zone_map_writer_preview_v1.py`, `run_breathline_v1_recovery_orchestration_v1.py`) — no shared dataclass/type |
| Source data / venue | closest existing pattern: `source_ref_json` in `active_regime_observation` (a free-form JSON dict of safety markers, not an evidence-reference schema) |
| Interval / as-of | n/a |
| Freshness behavior | n/a |
| Deterministic inputs already available | every candidate upstream table already carries its own natural reference (table name, row key, `asof_ts_utc`) that a small `evidence_ref` type could wrap |
| Missing primitives | a small, shared `evidence_ref` dataclass (e.g. table/module name, scope key, source timestamp, `computed_at_utc`) — genuinely tiny and bounded |
| Forbidden dependencies | none |
| Shadow-writer eligible | **YES**, as a small new bounded type, once at least one other field exists to reference |
| Note | No inferred or invented capabilities; this is a new small type, explicitly flagged as new rather than presented as existing. |

---

## Part 2 — Prerequisite Inventory

| # | Prerequisite | Availability | Evidence |
|---|---|---|---|
| 1 | BTC range/volatility/breakout state | **PARTIAL** | Generic deterministic builders exist (`local_ma_atr_context_v1.py`, `impulse_health_state_v1.py`); no BTC-specific state name or classifier exists. |
| 2 | ETH relative strength vs BTC | **PARTIAL, nearly complete** | `relative_class_vs_btc_24h_pct` already computed and persisted for the `ETH` asset-class row in `active_regime_observation`; only a threshold-bucketing function is missing. |
| 3 | BTC dominance availability | **IMPLEMENTED (raw data only)** | `src/etl/coingecko/etl_coingecko_global.py` writes `btc_dominance_pct`/`eth_dominance_pct`/`total_market_cap_usd` to table `market_global_snapshot` (no migration file found under `db/migrations/` — schema provenance unverified in this repo scan) from the public CoinGecko `/global` endpoint. No interpretation/regime layer reads this yet. |
| 4 | Universe-wide return breadth | **PARTIAL** | `avg_alt_return_24h_pct` (mean) already persisted; no `coins_up / coins_active` ratio computed anywhere. |
| 5 | Volume participation breadth | **PARTIAL/MISSING as aggregate** | `src/features/volume_confirmation_snapshot.py` computes per-asset volume ratio/zscore vs. that asset's own history only; no cross-sectional "% of universe with volume expansion" aggregate exists. |
| 6 | Sector taxonomy and asset-sector map | **MISSING** | No `sector`/`asset_sector_map` tables; `sector_group_code` explicitly null in `asset_profile`. Fully described only in `docs/research/sector_module_design.md`. |
| 7 | Sector leader contribution / anti-single-coin-pump control | **MISSING** | `leader_contribution_pct` is a *suggested* field in `sector_module_design.md`; not implemented anywhere. |
| 8 | Canonical regime forwarding | **IMPLEMENTED** | See `canonical_global_regime` / `canonical_asset_class_regimes` above; join rule fully documented in `canonical_regime_context_source_v1.md`. |
| 9 | Per-symbol `MarketNavigationState` forwarding | **PARTIAL, no producer** | Contract-only; no assembler exists (see `symbol_contexts` above). This is the most consequential gap relative to the task brief's assumption. |
| 10 | Evidence reference/provenance format | **MISSING as a shared schema** | Only ad hoc, per-script field names found; no shared type. See `evidence_refs` above. |

---

## Part 3 — Strict Gap Matrix

| Field | Status | Blocking gap |
|---|---|---|
| `canonical_global_regime` | Ready to forward | none |
| `canonical_asset_class_regimes` | Ready to forward | `classify_asset_class` lives in a `run_` script, not a shared module (cosmetic) |
| `btc_structure_state` | Blocked | no observer-vocabulary mapping over existing sensors |
| `eth_relative_strength_state` | Nearly ready | needs only a threshold-bucketing function over an already-stored field |
| `alt_breadth_state` | Blocked | breadth ratio (coins-up/coins-active) not computed anywhere |
| `sector_rotation_states` | Blocked | entire sector chain unimplemented |
| `symbol_contexts` | Blocked | no `MarketNavigationState` assembler; only 3 of 6 sub-states have builders |
| `freshness_state` | Blocked (as a rollup) | depends on which underlying fields are actually populated |
| `evidence_refs` | Buildable now | needs one small new shared type |

## Part 4 — Smallest Viable P0-B Implementation Bundle

Given the gap matrix, the only fields that satisfy "already exists or has a
tiny bounded primitive gap" without any new market/strategy logic are:

1. **Canonical global + asset-class regime forwarding** (`canonical_global_regime`,
   `canonical_asset_class_regimes`) — pure read of `active_regime_observation`
   using the documented join rule.
2. **ETH relative-strength bucketing** (`eth_relative_strength_state`) — a pure
   threshold function over the already-persisted `relative_class_vs_btc_24h_pct`
   value for the `ETH` asset-class row. No new data fetch.
3. **`evidence_refs`** — a small new shared reference type wrapping the table/row/
   timestamp of whichever of the above two a given snapshot actually used.

**`symbol_contexts` (`MarketNavigationState` forwarding) is explicitly excluded
from P0-B**, contrary to a plain reading of "existing MarketNavigationState
forwarding" — there is nothing to forward yet. Building the assembler is a
reasonable *next* bounded task, but it requires a genuine classification
decision (`navigation_regime`, `timing_state`) and is therefore larger than
what P0-B's minimality constraint allows.

`btc_structure_state` and `alt_breadth_state` are also excluded: both need a
small but real new mapping/aggregation step beyond pure forwarding/bucketing.

## Part 5 — Allowed Modified/Added Files for P0-B

```text
src/market_context/market_observer_v1.py          (new — research-only snapshot writer)
src/market_context/contracts_v1.py                (extend only: add MarketObserverSnapshot,
                                                     eth_relative_strength_state enum, evidence_ref type)
tests/test_market_observer_v1.py                   (new)
docs/architecture/market_observer_contract_v1.md   (status update only, if promoted beyond docs-only)
```

No migration, no dashboard, no scheduler, no `src/selection/`,
`src/decision_gate/`, `src/execution_planner/`, or `src/executor/` file.

## Part 6 — Explicit Non-Goals

- No sector implementation of any kind.
- No FFG or external-flow parsing.
- No external fib/overlay ingestion.
- No narrative scoring.
- No `selection_engine` changes.
- No `decision_gate` changes.
- No execution-layer changes of any kind.
- No `MarketNavigationState` assembler (deferred; see Part 4).
- No BTC dominance regime/interpretation layer (raw metric only, per prerequisite 3).

## Part 7 — Required Shadow-Validation Cohorts

Per `market_observer_contract_v1.md`'s shadow-first validation requirement,
before any P0-B field reaches `selection_engine`:

- canonical regime forwarding: baseline check that forwarded values exactly
  match `active_regime_observation` for the same venue/interval/asset_class
  (no transformation drift).
- `eth_relative_strength_state`: `OUTPERFORMING_BTC` vs. `UNDERPERFORMING_BTC`
  vs. `NEUTRAL_TO_BTC` cohorts, measured against forward BTC/ETH relative
  return using the same outcome-validation approach as
  `shadow_heartbeat_outcome_validation_v1.md` (15m/30m/1h/2h/4h/8h/24h
  horizons, MFE/MAE, hit rates).
- `evidence_refs` completeness: percentage of emitted snapshots where every
  non-trivial field carries a resolvable evidence reference (should be 100%
  by construction; track as a diagnostic, not a study).

## Part 8 — Architecture Risks / Conflicts Found

1. **The task brief's premise that "existing MarketNavigationState forwarding"
   is available for P0-B is incorrect.** `MarketNavigationState` is a contract
   with zero runtime producers; only a boundary test instantiates it. Any
   future P0-B/P1 planning referencing "forward existing MarketNavigationState"
   must first schedule the assembler as its own bounded task.
2. **Three independent freshness/staleness implementations** exist
   (`local_ma_atr_context_v1.py`, `impulse_health_state_v1.py`,
   `native_short_fib_context_v1.py`), each with its own stale-hour constant.
   An observer-level `freshness_state` rollup risks silently reconciling
   thresholds that were never intended to agree; this should be called out
   explicitly rather than averaged or overridden.
3. **`classify_asset_class` (asset-class mapping used by canonical regime)
   lives inside a `run_`-prefixed runner script**
   (`src/regime/run_active_regime_observation_v1.py`), not a shared
   contracts/lib module. `market_observer` importing directly from a `run_`
   script is a minor layering smell worth a small relocation before or
   alongside P0-B, though not a hard blocker.
4. **`market_global_snapshot`, `relative_strength_snapshot`, and the
   volume-confirmation table have no discoverable migration file** under
   `db/migrations/`. Their schema provenance could not be verified from this
   repo scan; anyone consuming these tables from `market_observer` should
   confirm the live schema against the actual database before relying on
   column names cited here.
5. **`sector_group_code` is a live, already-shipped column that is always
   `None`.** Any future sector work must populate this existing column (or
   formally deprecate it) rather than create a second, parallel sector field
   on a different table.
6. **No shared `evidence_ref` type exists anywhere**, despite `evidence_refs`
   being named as a required `MarketObserverSnapshot` field in the contract
   and referenced by the sector design doc. This is a one-time, small,
   shared-type gap common to nearly every future observer field — worth
   building once, early, rather than reinventing per field.
