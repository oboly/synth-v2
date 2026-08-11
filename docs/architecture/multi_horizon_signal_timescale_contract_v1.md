# Multi-Horizon Signal Timescale Contract v1

## Purpose

Canonical contract for signal timescale across Synth's market-only, research,
and reporting lanes. It answers GitHub Issue #243: make signal timescale
explicit and prevent invalid cross-horizon composition.

It distinguishes four separate time concepts for every relevant signal/lane,
inventories current lanes against them, defines deterministic horizon
composition semantics, and defines precedence/combination rules that prevent
unrelated horizons from being collapsed into one opaque score.

This document extends `multi_horizon_aplus_breathline_strategy_contract_v1.md`
and `pipeline_contracts.md`. It does not replace either.

**Relationship to the SHORT/MEDIUM/LONG strategy-horizon contract.**
`multi_horizon_aplus_breathline_strategy_contract_v1.md` defines the
`FIB_TRADING_HORIZONS = ("SHORT", "MEDIUM", "LONG")` strategy-classification
vocabulary and each bucket's allowed inputs. That is a *strategy holding-window
bucket*, chosen once per candidate. This document defines a different,
orthogonal axis: for any individual signal/lane, regardless of which strategy
bucket eventually consumes it, what timescale does the signal itself carry,
and how observed lifecycle durations are measured rather than assumed. A
signal's declared interval/lookback is not the same thing as the strategy
horizon bucket that later consumes it.

**Holding-window vocabulary vs. observed lifecycle duration.**
`multi_horizon_aplus_breathline_strategy_contract_v1.md`'s SHORT bucket
states a holding window of "days to 2 weeks." That figure is *design intent
strategy taxonomy* — a chosen classification bucket — not a measurement of
Native SHORT Fibonacci map/wave lifecycle behavior. The two must never be
substituted for one another: the strategy-taxonomy holding window does not
become evidence about how long a Native SHORT structural swing actually
persists, and a future empirical measurement of Native SHORT lifecycle
duration does not by itself redefine the SHORT strategy bucket's holding
window. Per the Signal/Lane Inventory and "Empirical Duration Findings"
below, observed Native SHORT map/level lifecycle duration is **UNKNOWN**
until the deterministic measurement specified in this document is actually
implemented and run; no document, dashboard, or code comment may substitute
the SHORT holding-window figure for a measured Native SHORT duration.

## Scope

This is an architecture/evidence contract only. It does not change any signal
algorithm, weight, map-generation logic, Rotation Pressure calculation,
`decision_gate` behavior, `execution_planner` behavior, executor/broker
behavior, or DB schema. Where empirical duration analysis would require new
runtime tooling, that tooling is scoped as follow-up work (see
"Empirical Duration Findings" and "Follow-Up Work" below), not implemented
here.

## The Four Time Concepts

Every relevant signal/lane must be described using all four of the following,
kept strictly separate:

1. **Input interval** — source candle/snapshot granularity the signal reads,
   e.g. `1h`, `4h`, `1d`, `weekly external report`.
2. **Lookback horizon** — history consumed to compute the signal, e.g. `24h`,
   `7d`, `SMA200`, `14-period RSI`.
3. **Effective signal horizon** — the market move/regime the signal is
   intended to describe. This may be narrower or broader than the input
   interval or lookback suggests, and must be stated explicitly rather than
   inferred.
4. **Observed lifecycle duration** — how long the resulting state/map/wave
   actually persists in historical data, measured from persisted timestamps.
   `UNKNOWN` is a valid and required value when no measurement has been made.

**Rule:** input interval never implies effective horizon, and effective
horizon never implies observed lifecycle duration. A `4h` primary interval
does not mean the resulting structure lasts a multiple of 4 hours. Any
document, dashboard, or code comment that states a specific duration (e.g.
"2-6 days") without a reproducible measurement behind it is describing an
assumption, not a fact, and must be corrected or removed.

## Signal/Lane Inventory

| Lane | Owner / layer | Market-only / account-aware / reporting / research | Input interval(s) | Lookback(s) | Effective signal horizon | Freshness / as-of | Version / provenance | Persisted lifecycle history? | Observed duration measurable today? |
|---|---|---|---|---|---|---|---|---|---|
| Market Rotation Pressure | `src/research/run_market_rotation_pressure_v1.py`, `market_rotation_pressure_snapshot_v1` / `market_rotation_pressure_observation_v1` | Market-only, account-agnostic, research/shadow | 24h and 168h (7d) candle-derived snapshots (both required per asset) | 24h return/volume (25%+20%), 7d return/volume (15%+10%), acceleration (15%, 24h vs. 7d/7 daily pace), market-relative (10%), persistence over up to 6 prior common snapshots (5%) | Short-horizon (24h) rotation pressure **confirmed or contradicted** by broader (7d) context — not a pure 7d signal | `as_of_ts_utc` per `(venue, asset_id)`; snapshot key `(as_of_ts_utc, venue, model_version)` | `model_version` on snapshot; append-only observations | Yes — append-only per-asset observations across snapshots, in principle allow reconstructing `pressure_state`/`phase_state` transition timelines | Not yet — no existing code computes state-duration distributions; append-only history supports it (see Empirical Duration Findings) |
| Native SHORT Fibonacci map/context/lifecycle | `src/market_data/` (`native_short_map_lifecycle_v1.py`, `native_short_scope_status_v1.py`, `native_short_map_level_status_v1.py`); reporting/research are read-only downstream consumers | Market-only, account-agnostic | Primary `4h`, supporting `1h` (confirm/conflict only) | Scope key `venue/symbol/quote_currency/SHORT/4h/1h`; primary freshness 12h, supporting freshness 3h, target evaluation interval 1h | One structural swing/wave on the SHORT scope — explicitly **not** assumed to equal any multiple of the 4h candle | `published_at_utc` per map; freshness/coverage cadence per scope config | `native_short_map_lifecycle_event_v1` event ledger: `ACTIVATED` (non-terminal — marks entry into active evaluation) plus terminal events `COMPLETED`/`EXPIRED`/`INVALIDATED`/`SUPERSEDED` | Yes — map-level: `published_at_utc` → terminal `event_ts_utc`. Level-level (anchor→target): only for maps whose per-map, persisted `coverage_cutoff_utc` was actually established (see "Empirical Duration Findings > Native SHORT Fibonacci > COVERAGE"); historical backfill is explicitly unauthorized | Map-level: yes, no code computes it yet. Level-level: only for maps with an established `coverage_cutoff_utc`; maps that never had coverage established are `LEGACY_UNAVAILABLE` |
| RSI / structure / confirmation ("Synth Confirmation" sensors) | `src/market_context/contracts_v1.py`, `local_ma_atr_context_v1.py`, `impulse_health_state_v1.py`, `src/features/etl_candle_feat.py` | Market-only | Caller-supplied candle interval — SHORT scope feeds 4h/1h, MEDIUM feeds 1d/4h, LONG feeds 1w/1d (per `multi_horizon_aplus_breathline_strategy_contract_v1.md`) | Candle-count based, not calendar-fixed: RSI 14, EMA 20/50, ATR 14, impulse swing lookback 8, volume SMA 20 | Not explicitly documented in code; only implied by which strategy horizon bucket feeds it | `MarketNavigationState.computed_at_utc` (single snapshot field, no history) | No dedicated version field found on the sensor namespace | No — no persisted state-duration/history table found under `src/market_context/` | No |
| Strategy State / `HorizonStrategyState` | Documented target: `selection_engine` (per `multi_horizon_aplus_breathline_strategy_contract_v1.md`) | Market-only, account-agnostic (documented) | N/A — not implemented | N/A | Intended to equal the `fib_trading_horizon` (SHORT/MEDIUM/LONG) of the candidate it belongs to | N/A | N/A | N/A — nothing persisted yet | Not applicable; guarded by `tests/test_multi_horizon_aplus_breathline_contract_v1.py::test_horizon_strategy_state_is_pending_implementation` |
| MA/volume trend-flow (#310) | Documented target: `research` (per Issue #310); `selection_engine` promotion requires separate review | Research-only until promoted | SMA50/150/200 context, slope, reclaim/extension over 4H/1D per Issue #310 (not yet implemented in `src/`) | SMA50/150/200 windows; volume-lifecycle classification | Multi-day to multi-week trend regime (implied by SMA50-200) — not yet formally stated | Not yet implemented | Not yet implemented | Not yet — feature does not exist in `src/` yet | Not applicable until #310 lands |
| MA/volume stoplight presentation (#315) | `reporting`, blocked on #310 | Reporting-only, read-only | Consumes #310 output at 4H/1D per #310's contract | N/A (consumer) | Same as #310's effective horizon | Consumes #310's persisted freshness | Consumes #310's version | N/A (reporting does not persist lifecycle state) | N/A |
| Breathline / A+ universal cycle context | External research source, forwarded read-only via `src/aplus/factor_extractor.py` into `market_context` | Research/external, forwarded read-only; must not become a duplicated local technical sensor | External symbolic report cadence — weekly/monthly, not candle-driven | `cycle_window`: WEEKLY / MONTHLY / MULTI_MONTH | Multi-week to multi-month macro cycle context | `freshness_state`: FRESH / AGING / STALE / VERY_STALE | Source-report provenance (external) | Yes — marker timestamps in local research-artifact JSONL, not an operational persisted lifecycle table (see `run_breathline_marker_timing_report_v1.py`'s `--input-jsonl`) | **Yes, already implemented**: `src/research/run_breathline_marker_timing_report_v1.py` computes `observed_duration_hours` / `median_observed_duration_hours` from marker-to-marker timestamps in that local JSONL research artifact. This is the existing precedent methodology for lifecycle duration measurement in this repository; it is research-only and has no operational DB counterpart. |

Rows left `N/A` reflect lanes that are documented-only or not yet
implemented; that state itself is the finding, not an omission.

## Empirical Duration Findings

### Native SHORT Fibonacci

**No existing code computes duration distributions.**
`run_short_swing_map_outcome_baseline_v1.py` computes which of
target-vs-invalidation happens first, not elapsed duration or percentile
statistics. The following is the deterministic measurement specification for
follow-up implementation, not performed here.

#### MAP-LEVEL

- **Map identity key**: `native_short_map_v1.map_id` — the exact immutable
  map. A rollover to a successor map is a new `map_id`; it is never the same
  identity continued, and durations must never be summed or joined across a
  rollover.
- **Publication/start timestamp source**: `native_short_map_v1.published_at_utc`.
- **Terminal lifecycle event source**: `native_short_map_lifecycle_event_v1`,
  filtered to the same `map_id`.
- **Accepted terminal event types**: `COMPLETED`, `EXPIRED`, `INVALIDATED`,
  `SUPERSEDED`. `ACTIVATED` is **not** a terminal event — it marks entry into
  active evaluation only and must be excluded from any terminal-duration
  computation. This matches the code:
  `_TERMINAL_LIFECYCLE_EVENT_TYPES` in `native_short_map_lifecycle_v1.py`
  contains only `COMPLETED`/`EXPIRED`/`INVALIDATED`/`SUPERSEDED`, and
  `project_current_native_short_map_lifecycle` treats a map whose latest
  event is `ACTIVATED` (or has no lifecycle event) as active, never as
  terminal.
- **Exact terminal timestamp used**: `event_ts_utc` of the single terminal
  event recorded for that `map_id`. The lifecycle validator in
  `native_short_map_lifecycle_v1.py` guarantees at most one terminal event
  per map and rejects any lifecycle event recorded after a terminal event, so
  this lookup is unambiguous: `duration = terminal_event_ts_utc -
  published_at_utc`.
- **Active/right-censored treatment**: a map whose latest lifecycle event is
  `ACTIVATED`, or that has no lifecycle event at all, is active/right-censored.
  Report `elapsed_so_far = now_utc - published_at_utc` in a separate censored
  bucket; never fold it into the completed distribution.
- Report `n`, `p25`, `p50` (median), `p75`, `p90` of `duration` per
  `lifecycle_event_type` (the terminal type), per asset where sample size
  permits, and combined.

#### LEVEL-LEVEL / ANCHOR→TARGET

- **Exact metric-start source**: the publication→target metric starts at the
  map's own `published_at_utc`. There is no separate persisted target-metric
  "anchor event" in the current model. A separately defined anchor→target
  metric must name its exact persisted anchor timestamp source; it must never
  substitute `published_at_utc` for an anchor timestamp merely because both
  belong to the same map.
- **Exact map/cycle identity used to join anchor and target events**: the
  exact `map_id` only. `native_short_map_level_target_event_v1`'s canonical
  identity is `map_id + canonical_map_level_role + side +
  canonical_unrounded_price + target_event_type`; a target event must never
  be joined to a different map's anchor, including a successor map from the
  same scope (rollover never carries target events forward — a new map has a
  new `map_id`).
- **Exact target event identity**: only `REACHED` and `PASSED` event types
  exist for a given map-level identity; there is no persisted `ACTIVE` event
  — `ACTIVE` is defined as the absence of a terminal event for a covered
  level identity, not a row to join against.
- **Ordering semantics for first target / later targets**: order target
  events for the map by `(effective_at_utc ASC, target_event_id ASC)`.
  `effective_at_utc` is sourced only from the causal closed primary-interval
  candle's `close_ts_utc`; a DB CHECK constraint enforces
  `effective_at_utc = causal_candle_close_ts_utc`, and `recorded_at_utc` —
  the writer's wall-clock insert time — is never substituted. The persisted
  reader `fetch_native_short_map_level_target_events_for_map` returns the
  stable `target_event_id`; it is the required deterministic tie-breaker when
  multiple map-level events share an effective timestamp. "First target
  event" is the first `REACHED`/`PASSED` event across all level roles for the
  exact `map_id` in that total order; "later target events" are the remaining
  events in the same total order. Equal-timestamp events are distinct events,
  not duplicates, and retain that `target_event_id` order.
- **Repeated/duplicate target events**: events are insert-only, and the
  database unique-identity constraint on `map_id + canonical_map_level_role +
  side + canonical_unrounded_price + target_event_type` is the sole
  duplicate-write fence. A duplicate insert attempt is rejected and treated
  as an idempotent no-op, never as a second observation or a mutation of the
  original row's causal candle/timestamp.
- **Exact end timestamp used for target achievement**: the target event's
  `effective_at_utc` (causal candle close), never `recorded_at_utc`.
- **Canonical source**: target achievement is read from the persisted
  `native_short_map_level_target_event_v1` row, written by the single shared
  write authority `append_native_short_map_level_target_events_for_map`. It
  is a level-status/target-event persisted row, not a lifecycle event and not
  a re-derivation from current-state snapshots; there is no second,
  independently computed target-event decision anywhere in the codebase.
- **No cross-map/cross-cycle joining**: anchor and target must always be read
  from the same `map_id`.
- Full publication/anchor→target statistics include only `FULLY_OBSERVED`
  intervals (see COVERAGE below), and report `n`, `p25`, `p50`, `p75`, `p90`
  per level role and combined, per asset where sample size permits.

#### COVERAGE

- `coverage_cutoff_utc` is **durable, persisted, per-`map_id`** state in
  `native_short_map_level_target_event_coverage_v1` — it is **not** a single
  global date applicable to every map. Its provenance is
  `coverage_cutoff_utc = GREATEST(map.published_at_utc,
  requested_watermark_utc_at_establishment)`, computed once per map at
  coverage-establishment time
  (`compute_target_event_coverage_cutoff` /
  `establish_or_fetch_target_event_coverage_for_map`, per the addendum dated
  2026-07-31 in `native_short_map_level_status_contract_v1.md`). "2026-07-31"
  is the date this coverage mechanism was authorized and first able to
  establish per-map coverage rows going forward — it is not a universal
  per-map cutoff. Each map's actual `coverage_cutoff_utc` must be read from
  that map's own coverage row, never assumed from the authorization date.
- **Required full-observation rule**: for every requested publication→target
  or anchor→target metric, define `metric_start_ts` from that metric's exact
  stated start source. Only when a coverage row exists and
  `coverage_cutoff_utc <= metric_start_ts` may the interval be eligible for
  `FULLY_OBSERVED` classification. For publication→target,
  `metric_start_ts = published_at_utc`; an anchor-based metric uses its own
  exact `anchor_ts`, never an interchangeable publication timestamp.
- **Left-truncated case**: when `coverage_cutoff_utc > metric_start_ts`, the
  requested start→target interval is `LEFT_TRUNCATED` / `UNAVAILABLE`. Do not
  infer the unobserved pre-cutoff interval, reconstruct it from current state,
  or treat it as ordinary right-censoring. A map with no coverage row is
  `LEGACY_UNAVAILABLE`, a distinct unavailable class because coverage never
  started for that `map_id`.
- **Right-censored case**: `RIGHT_CENSORED` applies only when coverage exists
  from or before `metric_start_ts`, no target event has occurred, and target
  evaluation remains ongoing. It is distinct from both `LEFT_TRUNCATED` and
  `LEGACY_UNAVAILABLE`; neither unavailable class may enter the fully
  observed or right-censored population.
- **Optional partial metric**: where a coverage row exists and
  `coverage_cutoff_utc > metric_start_ts`, a separately labelled
  `coverage_cutoff_utc→target_event_ts` metric may be reported from the
  persisted event timestamp. It is a **PARTIAL_OBSERVED_INTERVAL**, not an
  anchor→target or publication→target duration, and must be grouped
  separately from `FULLY_OBSERVED` start→target statistics.
- A map that goes terminal without ever having had coverage established
  remains `LEGACY_UNAVAILABLE` permanently — never silently inferred `ACTIVE`
  and never reconstructed from the current full-history
  `classify_level_state` row-projection, which reports level state
  independent of coverage and must not be conflated with coverage-gated
  target-event history.
- Do not reconstruct pre-coverage target events from current state snapshots
  under any circumstance; `HISTORICAL_BACKFILL_AUTHORIZED=false` remains in
  force and this contract does not propose changing that.

### Market Rotation Pressure

**No existing code computes this today.** No runner in the codebase
currently walks the observation history to build duration distributions. The
append-only `market_rotation_pressure_observation_v1` history — consecutive
observations for the same `(venue, asset_id, model_version)` carrying
`as_of_ts_utc` and `pressure_state`/`phase_state` — is sufficient to compute
it without new schema. The following is the canonical run/duration
definition; it applies identically, and is computed independently, for
`pressure_state` and for `phase_state` (the two are never merged into one
run).

**Canonical completed-state-run definition:**

- **Observation ordering**: observations for a given `(venue, asset_id,
  model_version)` are ordered by `as_of_ts_utc` ascending. Where the
  observation store exposes a monotonic insert/observation id, it is the
  deterministic tie-breaker for any rows sharing an identical `as_of_ts_utc`.
- **Duplicate timestamps**: an exact duplicate `(as_of_ts_utc, venue,
  asset_id, model_version)` row is a data-quality condition, not a second
  observation. A measurement runner must reject/fail loudly on it rather than
  silently pick one, count both, or average them.
- **run_entry_ts** = `as_of_ts_utc` of the first observation in a run of
  consecutive, ordered observations that share the same `pressure_state` (or,
  separately, `phase_state`) for that `(venue, asset_id, model_version)`.
- **run_exit_ts** = `as_of_ts_utc` of the first subsequent observation, for
  the same `(venue, asset_id, model_version)`, whose relevant state differs
  from the run's state — the first *differing* observation, not the last
  matching one.
- **completed_duration = run_exit_ts - run_entry_ts.** This is the single
  canonical formula. A run is only "completed" once a differing successor
  observation exists. An implementation that instead computes duration as
  `last_ts_in_run - first_ts_in_run` (span between the first and last
  *matching* observations) undercounts the true state duration by one
  inter-observation gap and must not be used; this correction supersedes any
  earlier last-matching-observation formula.
- **Observation gaps**: a missing expected snapshot (a gap larger than the
  configured observation cadence) does not by itself end a run and must
  never be interpolated or backfilled — run membership is defined only by
  actually persisted observations. Report the run's largest inter-observation
  gap as separate metadata (e.g. `max_gap_seconds`) so a duration built
  across an unusually large gap is distinguishable from one built on dense
  observations; the run's state is never inferred for the gap interval
  itself.
- **Missing expected snapshots**: the same rule applies to the required
  24h/168h snapshot pairing — if one of the two required snapshots for an
  `as_of_ts_utc` is absent, that observation is incomplete and must not be
  used to open, continue, or close a run; it is excluded, not treated as a
  state-preserving placeholder.
- **Model/version boundaries**: `model_version` is part of run identity. A
  `model_version` change ends the current run at the last observation under
  the old version — right-censored at that point, never folded into a
  completed duration — and starts a new run under the new version, even if
  the state label is unchanged, because component weights (and therefore
  state-boundary meaning) are not guaranteed comparable across versions. A
  run must never span a `model_version` change.
- **Active / right-censored runs**: the most recent run per `(venue,
  asset_id, model_version)` — one with no observed differing successor yet —
  is right-censored. Report `elapsed_so_far = latest_observation_ts -
  run_entry_ts` in a separate censored bucket; never merge it into the
  completed-duration percentile distribution.

**Deterministic measurement specification** (follow-up, not performed here):

- For each `(venue, asset_id, model_version)`, walk
  `market_rotation_pressure_observation_v1` ordered as above, segmenting into
  runs per the canonical definition, independently for `pressure_state` and
  `phase_state`.
- Report `n`, `p25`, `p50`, `p75`, `p90` of `completed_duration` per state
  (`STRONG_ROTATION_IN`/`ROTATION_IN`/`NEUTRAL_OR_MIXED`/`ROTATION_OUT`/
  `STRONG_ROTATION_OUT`, and separately per `phase_state`), reported per
  `model_version`; combine across versions only where comparability has been
  separately validated, never by default.
- Report right-censored `elapsed_so_far` runs as a separate `n_censored`
  bucket per state, excluded from the percentile statistics above.
- Separately measure transition timing such as `+30 -> 0 -> -30` (and the
  reverse) as the elapsed time between the observation crossing each
  threshold, treating threshold crossings as events rather than states; the
  same ordering, duplicate-timestamp, gap, and version-boundary rules apply.
- Where both Native SHORT lifecycle events and Rotation Pressure
  observations exist for the same asset and overlapping time range,
  timestamp alignment may be reported (e.g. "pressure state X entered N
  hours before/after Native SHORT lifecycle event Y") as observational
  evidence only. This must not be presented as, or coded as, a causal or
  predictive claim — see "Precedence and Combination Rules" below.

### Other lanes

- **Synth Confirmation sensors** (RSI/MA/ATR/impulse): no persisted
  state-transition history exists; no duration analysis is possible without
  new persistence, which is out of scope here.
- **Breathline**: duration measurement already exists and is the reference
  implementation/methodology (`run_breathline_marker_timing_report_v1.py`).
  No further work needed for this contract.
- **MA/volume trend-flow (#310)** and its presentation (#315): not yet
  implemented; no duration analysis is possible until #310 lands and
  persists trend/volume-lifecycle state history.
- **Strategy State / `HorizonStrategyState`**: not implemented; not
  applicable.

## Follow-Up Work

Computing the actual duration distributions specified above (Native SHORT
map/level-level, Rotation Pressure state/phase/transition-timing) requires a
new research-lane runner that reads existing tables and writes to
`data/research/` — no schema change. That is deliberately **not** implemented
in this contract per Issue #243's scope discipline: the contract documents
the exact deterministic measurement specification above so that follow-up
work can implement it directly against agreed semantics. A dedicated
follow-up Issue is recommended once this contract is accepted; it is not
opened by this change.

## Horizon Composition Semantics

When two or more signals with declared timescales are considered together,
their relationship must be classified as exactly one of the following. Simple
label disagreement between signals is never by itself "conflict" — the
classification depends on whether the signals' effective horizons are
actually comparable.

- **ALIGNED** — different horizons point in the same direction for the
  window where they overlap. Example: Rotation Pressure is `ROTATION_IN` and
  a Native SHORT map's structural bias is bullish over the same window.
- **NESTED** — a faster-horizon move occurs inside a still-valid
  slower-horizon regime. Example: a 24h-driven Rotation Pressure dip while
  the 7d component and a Native SHORT structural map remain intact. A nested
  faster move does not, by itself, invalidate the slower regime.
- **TRANSITIONAL** — the faster horizon has turned, but the slower horizon
  has not yet confirmed a change. Example: 24h return/volume flip negative
  while the 7d component has not yet confirmed; or a Native SHORT map
  showing early weakness with no terminal lifecycle event yet.
- **GENUINELY_CONFLICTING** — signals intended to describe *comparable*
  horizons disagree. Example: two signals both describing the same SHORT
  4h-scope structural bias disagree in direction over the same window.
- **NOT_COMPARABLE** — signals answer materially different questions and
  must not be collapsed into one consensus. Example: Breathline's
  multi-month macro cycle context versus a Native SHORT 4h map's structural
  state; or Synth Confirmation's candle-count-based RSI versus Rotation
  Pressure's calendar-based 24h/7d window.

Classification requires knowing each signal's effective signal horizon (not
its input interval) from the inventory above. A classifier or presentation
layer must not guess comparability from labels alone.

## Precedence and Combination Rules

No validated precedence currently exists between any two lanes in the
inventory above. Until a specific combination is separately validated (per
the Strategy Candidate Rules in `AGENTS.md`), the following are forbidden:

- Averaging or otherwise blending unrelated-horizon signals into one opaque
  score. Rotation Pressure, Native SHORT map state, Synth Confirmation
  sensors, trend-flow (#310), and Breathline must remain separately
  addressable.
- Using a slow-horizon signal (e.g. Breathline's multi-month cycle context,
  or a MEDIUM/LONG trend classification) as immediate execution timing.
- Treating a fast-horizon pullback (e.g. a 24h Rotation Pressure dip) as
  proof that a slower structural regime (e.g. an active Native SHORT map)
  has ended. A terminal lifecycle event, not a correlated faster-horizon
  signal, is what ends a Native SHORT map.
- Reporting/dashboard code inventing cross-horizon authority — e.g.
  recomputing a "combined confidence" score inside a renderer instead of
  consuming a persisted, versioned analysis output.
- Account state altering market-only signal truth. `decision_gate` and
  `execution_planner` must not recompute, filter, or reinterpret Rotation
  Pressure, Native SHORT, or any other market-only signal's timescale
  classification; they consume it as given.
- `execution_planner` independently resolving apparent market disagreement
  between signals. Any GENUINELY_CONFLICTING or TRANSITIONAL classification
  is a market-layer output to be surfaced, not resolved downstream of
  `decision_gate`.

Where no validated precedence exists, the correct behavior is to preserve and
present the separate signals with their horizon classification — not to
invent a consensus value.

## Horizon Identity and Provenance Contract

Every combined or operator-facing signal presentation must be able to expose,
directly or through evidence/detail:

- signal/model identity and version (e.g. Rotation Pressure `model_version`,
  Native SHORT map/scope identity);
- input interval(s);
- lookback horizon(s);
- effective horizon classification (from this contract's inventory or a
  successor entry using the same four-concept structure);
- as-of/freshness timestamp;
- lifecycle/state timestamp where applicable (e.g. `published_at_utc`,
  lifecycle `event_ts_utc`);
- observed typical duration when empirically established (from the follow-up
  analysis above), otherwise explicit `UNKNOWN`;
- source owner/provenance (lane name from the inventory table).

`UNKNOWN` duration must render as `UNKNOWN`, never as an invented figure such
as "2-6 days," and never silently omitted.

## Operator/Reporting Contract

Reporting is a read-only consumer of the above. It may render timescale
metadata; it must not compute new horizon classification, comparability, or
combination logic in the renderer. Example projection:

```text
Rotation pressure    -30.2   ROTATION_OUT   input/lookback: 24h + 7d (both required)
                                             effective horizon: short rotation, 7d-confirmed
Fibonacci map (SHORT) ACTIVE                 primary: 4h / support: 1h
                                             observed typical duration: UNKNOWN (not yet measured)
Trend (#310)          -- not yet implemented --
Breathline             EXPANSION             cycle_window: MONTHLY
                                             observed typical duration: see breathline marker
                                             timing report (median hours, from local JSONL
                                             research artifact — research-only, not an
                                             operational persisted table)
```

Once the follow-up duration analysis (see "Follow-Up Work") produces
persisted percentile output, reporting may additionally expose it (e.g.
median/p75 lifecycle), but must read that persisted/validated output rather
than compute it inline. This document defines the contract; dashboard
implementation belongs to the relevant reporting Issue(s), per Issue #243
scope.

## Ownership and Data-Flow Boundaries

Unchanged from `AGENTS.md` and `pipeline_contracts.md`:

```text
selection_engine    = market-only, account-agnostic
decision_gate        = account-aware permission only
execution_planner    = execution intent only
executor / agents    = order handling only
reporting/dashboard  = read-only consumer
```

No signal-timescale classification, composition semantics, or duration
metadata may be used to bypass or collapse these layers. Horizon
classification (ALIGNED/NESTED/TRANSITIONAL/GENUINELY_CONFLICTING/
NOT_COMPARABLE) is market-layer evidence; it grants no permission and creates
no execution intent.

## Forbidden Shortcuts

```text
input interval                     -> assumed effective horizon
effective horizon                  -> assumed observed lifecycle duration
unvalidated duration figure         -> presented as fact
unrelated-horizon signals          -> averaged/blended opaque score
slow-horizon signal                -> immediate execution timing
fast-horizon pullback              -> proof slower regime ended
reporting/dashboard code           -> cross-horizon authority or recomputation
account state                      -> market-only signal truth
decision_gate                      -> market signal timescale reinterpretation
execution_planner                  -> independent resolution of market disagreement
label disagreement alone           -> GENUINELY_CONFLICTING classification
```

## Guard Expectations

Guard tests should preserve, using the existing import-boundary-scan pattern
in `tests/test_multi_horizon_aplus_breathline_contract_v1.py`:

1. `decision_gate` has no imports from Rotation Pressure or Native SHORT
   research/market-data modules beyond what it already consumes as
   permission input (no new market-recomputation imports).
2. `execution_planner` and `executor` gain no new imports into Rotation
   Pressure or Native SHORT internals.
3. No reporting module under `src/reporting/` recomputes Rotation Pressure
   score components or Native SHORT lifecycle classification inline (import
   boundary + forbidden-recomputation-symbol scan).
4. Any future combined-signal contract module exposes the required horizon
   identity/provenance fields (interval, lookback, effective horizon,
   as-of, duration-or-UNKNOWN) rather than omitting them.

## Related Documents

- `docs/architecture/multi_horizon_aplus_breathline_strategy_contract_v1.md`
- `docs/architecture/pipeline_contracts.md`
- `docs/research/market_rotation_pressure_v1.md`
- `docs/architecture/native_short_fib_context_bridge_v1.md`
- `docs/architecture/native_short_map_level_status_contract_v1.md`
- `docs/research/breathline_marker_timing_report_v1.md`
- `src/market_context/contracts_v1.py`
- `tests/test_multi_horizon_aplus_breathline_contract_v1.py`
