# Market Rotation Pressure V1 — Canonical Promotion & Evidence Contract v1

Status: Permanent architecture contract (supersedes prior research-only
labeling for this lane)
Canonical location: `docs/architecture/rotation_pressure_v1_canonical_promotion_v1.md`
Scope: authority reconciliation + `family=ROTATION` evidence-contract
completion for downstream #617
Runtime impact: none (pure mapping function, no DB access, no I/O, no
runtime/deploy change)
Issue: #676 (Phase B, following the `BLOCKED_OWNER_DECISION` audit in
`docs/architecture/rotation_pressure_v1_authority_audit_v1.md`)
Upstream owners: #243 (`docs/architecture/multi_horizon_signal_contract_v1.md`),
#669/#672 (`docs/architecture/structure_relative_strength_evidence_contract_v1.md`,
the evidence-contract seam this document reuses)
Related, explicitly unaffected: #593, #449, #661/#568, #591, #617
reporting/dashboard, `selection_engine`, `decision_gate`,
`execution_planner`, `executor`

## 1. Owner decision (authority reconciliation)

The #676 GitHub issue owner decision (quoted for record):

> Decision: **PROMOTE / CANONICAL_EVIDENCE_OWNER**. The explicit production
> writer authorization already recorded under #266 is intended to be
> consistent with architectural use of existing Market Rotation Pressure V1
> as the canonical broad/regime `ROTATION` market-evidence owner. This
> decision resolves the `BLOCKED_OWNER_DECISION` finding recorded by PR
> #678.

Exact meaning of promotion:

```text
market_rotation_pressure_v1 (the broad/regime V1 lane only)
-> canonical production-safe market evidence owner for family=ROTATION
-> downstream read-only evidence consumers (#617 and future accepted consumers)
```

This does **not** grant or change: `selection_engine` ranking authority,
account awareness, decision permission, execution intent, execution
planning, executor behavior, broker access, order submission, or
runtime/deployment state. The lane remains market-only and
account-agnostic.

**#593's faster C1/C2/C3 multi-horizon Rotation candidates are explicitly
NOT promoted by this decision** and remain research-only, per #593's own
ownership and per the #676 task contract's anti-duplication guard. Nothing
in this document or its accompanying code reads, imports, or references
`src/research/multi_horizon_rotation_replay_v1.py`,
`src/research/run_multi_horizon_rotation_dataset_builder_v1.py`, or any
other #593/#449-owned module.

### 1.1 Why the migration/design-doc labels are corrected here, not the schema

`db/migrations/20260712_market_rotation_pressure_v1.sql` is a deployed,
already-applied migration against a live table with production data.
Rewriting a deployed migration file's header comment after the fact is not
this repository's convention for already-applied schema files (migrations
are additive/forward-only; see e.g. the "forward-only, non-destructive"
convention noted in
`docs/architecture/native_short_scope_administration_contract_v1.md:197`),
and no schema change is required to reconcile authority. Per the #676 task
contract ("Do not perform a schema migration merely to edit a historical
migration comment... leave the migration SQL untouched, add an explicit
canonical superseding architecture declaration instead"), this document is
that explicit superseding declaration:

```text
db/migrations/20260712_market_rotation_pressure_v1.sql:2
  "-- Boundary: research-only · market-only · account-agnostic"
  -> describes the boundary AT MIGRATION CREATION TIME ONLY.
  -> SUPERSEDED for authority purposes by the #676 owner decision recorded
     in this document and in Issue #676. The "market-only · account-agnostic"
     half of that comment remains true and unchanged; only "research-only"
     is superseded.
```

The migration SQL itself (schema, constraints, comments) is left byte-for-byte
unmodified. `docs/research/market_rotation_pressure_v1.md` (a documentation
file, not a deployed schema artifact) has been updated directly to reflect
the promotion, retaining its original "research/shadow" wording as
historical creation-time context rather than deleting it.

## 2. Canonical horizon metadata (explicit owner declaration, not inference)

Per #243 §7.1 and the #676 owner decision:

```text
lookback_horizon   = "24h+168h"    (24h + 7d, matching #243's "24h + 168h" wording)
effective_horizon  = REGIME
observed_lifecycle = UNMEASURED    (no persisted empirical lifecycle analysis exists)
```

This is an explicit, reviewed declaration for this specific promoted lane —
not an inference from `input_interval` (#243 §3.3's prohibition is about
silently *inferring* `effective_horizon` from candle interval; an explicit,
reviewed owner declaration is exactly the escape hatch #243 §3.3 itself
describes: "Domain-specific display aliases... may exist, but canonical
machine contracts must map deterministically to one of the values above or
remain UNKNOWN until reviewed" — this has now been reviewed). This
declaration applies only to `market_rotation_pressure_v1`; it grants no
horizon interpretation to #593's variants.

### 2.1 `input_interval` (verified from producer/source code, not guessed)

`input_interval = "1h"`, established deterministically from the upstream
source, not guessed from the 24h/168h lookback windows:

```text
db/migrations/20260627_market_rotation_history_v1.sql:32-34
  candle_interval_code VARCHAR(8) NOT NULL DEFAULT '1h'
src/research/run_market_rotation_history_v1.py:18-19
  CANDLE_INTERVAL = "1h"   (the sole writer of market_rotation_snapshot_v1;
                            never writes any other value)
```

`market_rotation_pressure_v1` exclusively consumes
`market_rotation_snapshot_v1`/`market_rotation_observation_v1`
(`SOURCE_TABLES` in `run_market_rotation_pressure_v1.py:36`), so this is the
real, deterministic input interval for every row it produces.

## 3. Model identity / provenance

No `model_id` column is persisted anywhere in
`market_rotation_pressure_snapshot_v1` or
`market_rotation_pressure_observation_v1`. `model_version` is a real,
persisted, `NOT NULL` column (migration lines 18/72), written from the
producer's own `MODEL_VERSION = "1.0"` constant
(`run_market_rotation_pressure_v1.py:13`).

Per the #676 owner decision ("a deterministic producer identity may be
declared if the producer contract uniquely establishes it. Preferred
identity: `model_id = market_rotation_pressure_v1`"), this contract declares:

```text
model_id = "market_rotation_pressure_v1"   (the producer's own RUNNER_NAME
                                             constant, run_market_rotation_pressure_v1.py:11)
supported model_version values reviewed here: {"1.0"}
```

This `model_id` is **never fabricated from row data** — it is only ever
attached when the row's own persisted `model_version` is present and in
the reviewed set. A missing, blank, or unsupported `model_version` fails
the whole identity closed (`model_id` stays `None` too), exactly mirroring
the fail-closed pattern already established for `structure_state` in
`docs/architecture/structure_relative_strength_evidence_contract_v1.md`
§3.3. No historical DB rows are rewritten to add a `model_id` column; this
is a pure adapter-level declaration.

## 4. Freshness ownership (still not producer-owned — #547 Phase A: BLOCKED_NEEDS_MEASUREMENT)

**#547 Phase A evaluated, and explicitly declined to adopt, a producer-owned
staleness rule.** The candidate derivation considered was:

```text
input_interval (60 min, INPUT_INTERVAL, reviewed producer fact)
+ writer's expected worst-case persist lag (~25 min: gurkDB
  synth-market-rotation-pressure-writer.timer OnCalendar=*:20:00 UTC,
  RandomizedDelaySec=180 -> configured worst-case latest start :23:00, a
  deterministic schedule fact; plus a historically observed, not rigorously
  measured, ~1-2 min runtime across three real per-invocation-verified
  cycles -> estimated persist-by :24-:25, per
  docs/ops/market_rotation_pressure_runtime_owners_v1.md "Expected
  worst-case candle-to-visibility lag")
+ operational safety margin for runtime variance beyond the observed
  ~1-2 min figure
= candidate ROTATION_STALE_AFTER
```

Only the first component has a fully concrete, reviewed evidentiary basis:
the 60-minute cadence is an explicit, reviewed owner decision (see "Cadence
decision" in `docs/ops/market_rotation_pressure_runtime_owners_v1.md`, not
timer cadence alone treated as freshness semantics). The second component
is **partially** defensible: the `:23:00` worst-case start is a genuine
deterministic fact of the configured schedule (`OnCalendar`/
`RandomizedDelaySec`), but the runtime addition on top of it ("historically
~1-2 min") is an anecdotal observation from three cycles, not a measured
worst-case bound (no p95/p99, no stress case, no documented runtime-outlier
review) — three data points cannot establish a worst-case runtime, only a
typical one. Presenting "~25 min" as directly measured evidence overstates
what is actually known. The third component — the operational safety
margin — is **not** defensible at all: no measured distribution of writer
invocation duration exists beyond the same three-cycle anecdote, no
incident/postmortem record establishes a needed buffer, and no owner
decision in #547 records a reviewed margin value. Any specific minute
figure for either the runtime addition or the safety margin would be
invented, not evidence — so per the #547 task contract ("do not invent a
threshold"), no `ROTATION_STALE_AFTER` is adopted.

The dashboard's `classify_freshness()` /
`DEFAULT_STALE_AFTER = timedelta(hours=2, minutes=30)` in
`src/reporting/market_rotation_pressure_dashboard_v1.py:10,107-122` remains a
separate consumer/dashboard-owned rule and continues to be **not** adopted
as producer-owned truth (unchanged from the #676 finding).

**Decision: `BLOCKED_NEEDS_MEASUREMENT`.** `evidence_contract_v1.compute_freshness`
and `rotation_evidence_contract_v1` are unchanged by #547 Phase A: freshness
still resolves to `UNKNOWN` (`FRESHNESS_NOT_OWNER_DEFINED`) for any present,
non-future `asof_ts`, and to `INSUFFICIENT_DATA` for a missing or
future-dated `asof_ts` or for `status`. What #547 Phase B needs before a
producer-owned rule can be adopted:

```text
1. Measured end-to-end persist lag (asof_ts_utc/candle close -> row
   committed/queryable), not just writer runtime duration, across a
   materially larger, continuous sample (e.g. one full week of real hourly
   cycles) -- capture ExecMainStartTimestamp/ExecMainExitTimestamp plus the
   actual DB commit time, and record p50/p95/p99, not only the historical
   "~1-2 min" three-cycle anecdote.
2. An explicit owner decision recording the reviewed safety-margin value
   (or a documented policy for deriving it from the measured distribution,
   e.g. "p99 + fixed constant"), attached to #547 as evidence -- not
   invented ad hoc in this contract module.
3. Re-run this Phase A derivation with that measurement in hand, describing
   any worst-case component precisely as either a deterministic configured
   fact (e.g. `OnCalendar`/`RandomizedDelaySec`) or a measured statistic --
   never as "directly measured" when it is actually an estimate. Only then
   may `rotation_evidence_contract_v1` gain a `ROTATION_STALE_AFTER`
   constant and pass it into `compute_freshness`.
```

### 4.1 #547 Phase B — measurement collected, still `BLOCKED_NEEDS_MEASUREMENT`

Item 1 above is now satisfied for the producer-owned leg:
`docs/research/market_rotation_pressure_freshness_sla_measurement_v1.md`
records a 417-real-cycle, continuous, OBSERVED `asof_to_persist_lag`
distribution (gurkDB, `2026-08-08`..`2026-09-01`; steady-state p50=1298.0s,
p95=1383.0s, p99=1416.2s, max=1418.0s), replacing the three-cycle anecdote,
plus `writer_scheduling_lag` and `writer_runtime` distributions confirming
runtime is trivial (p99=6s) and persist lag is dominated by the deliberate
`:20:00` schedule offset.

The publisher leg (`persist_to_published_lag`/`total_asof_to_published_lag`)
is now partially observed from a manually-collected Odroid journal export
(34 successful + 6 network-outage-failed cycles, ~33h coverage:
`2026-08-31T06:36Z`..`2026-09-01T15:36Z`), but that document's own harness
reports `publisher_leg_sufficiency=MEASUREMENT_INSUFFICIENT_PARTIAL_COVERAGE`
against the 417-cycle writer sample (missing ~546.6h / ~22.8 days of
further-back publisher journal history) -- per the #547 task contract, this
partial sample is **not** treated as equivalent evidentiary weight to the
writer leg and no threshold candidate is drawn from it alone (see that
document's §5.3 and §6).

Items 2 and 3 remain open: no owner-reviewed safety-margin decision has
been recorded, and this document's own `ROTATION_STALE_AFTER` derivation
has not yet been re-run against the new measurement. **Decision remains
`BLOCKED_NEEDS_MEASUREMENT`** -- `evidence_contract_v1.compute_freshness`
and `rotation_evidence_contract_v1` are unchanged. Adopting a threshold is
an explicit follow-up, not performed by this document or by the #547 Phase
B measurement task.

## 5. Completed evidence mapping

New module `src/features/rotation_evidence_contract_v1.py`,
`build_rotation_pressure_evidence(row, *, evaluated_at)`, reusing the
existing #669/#672 seam (`src/features/evidence_contract_v1.py`) without
any new generic framework:

```text
family              = "ROTATION"
component           = "PER_ASSET_PRESSURE"
market              = "asset"
model_id            = "market_rotation_pressure_v1" | None (see §3)
model_version       = row.model_version | None (see §3)
input_interval      = "1h"
lookback_horizon    = "24h+168h"
effective_horizon   = REGIME
observed_lifecycle  = UNMEASURED
asof_ts             = row.as_of_ts_utc, normalized to aware UTC
freshness           = UNKNOWN | INSUFFICIENT_DATA (see §4)
provenance          = {asset_id, market, venue, source_snapshot_24h_id, source_snapshot_7d_id}
raw                 = {score_total, pressure_state, phase_state,
                       raw_return_24h_pct, raw_return_7d_pct}   (verbatim, unmodified)
reason_codes        = deterministic (see §6)
```

`score_total` is the primary raw numeric evidence value and is passed
through byte-for-byte from the persisted column; `pressure_state` and
`phase_state` are the existing producer-owned categorical states (no new
thresholds). Both are copied, never recomputed.

As in #669/#672, `asof_ts` and `evaluated_at` are normalized via
`evidence_contract_v1.normalize_to_utc` before comparison, so a
naive-UTC-persisted `as_of_ts_utc` (this producer's `DATETIME(6)` columns
carry no explicit tzinfo) compares correctly against an aware-UTC
`evaluated_at` without raising `TypeError` and without assuming local time.

### 5.1 Scope: per-asset only (bounded, per task contract)

Only `market_rotation_pressure_observation_v1` (per-asset) is mapped in
this slice. `market_rotation_pressure_snapshot_v1` (market-level aggregate:
`market_direction`, `acceleration_state`, `concentration_state`,
`confirmation_state`, `market_score`, `evidence_light_count`) is **not**
mapped here. Per the #676 task contract ("only add [aggregate evidence] if
it fits the same clean contract seam without broadening scope. Otherwise
explicitly keep this bounded to the per-asset evidence needed by #617"),
aggregate evidence is deferred as an explicit, separately-scoped follow-up
slice, reusing the same `family=ROTATION` seam with a
`component=MARKET_AGGREGATE` (or similar) once that slice is opened.

## 6. Fail-closed behavior

```text
missing asof_ts                -> freshness=INSUFFICIENT_DATA (MISSING_ASOF_TS)
asof_ts after evaluated_at     -> freshness=INSUFFICIENT_DATA (ASOF_AFTER_EVALUATION_TS)
asof_ts present, no owner rule -> freshness=UNKNOWN (FRESHNESS_NOT_OWNER_DEFINED);
                                   status=INSUFFICIENT_DATA (see §4, #547 Phase A:
                                   BLOCKED_NEEDS_MEASUREMENT)
missing/blank model_version    -> status=INSUFFICIENT_DATA (MISSING_PROVENANCE);
                                   model_id/model_version both None
unsupported model_version      -> status=INSUFFICIENT_DATA (UNSUPPORTED_MODEL_VERSION);
                                   model_id/model_version both None
naive vs aware timestamps       -> normalized to aware UTC before any comparison
replay                          -> caller-supplied row + evaluated_at only; no internal
                                    "latest" query exists in this module; no
                                    freshness/threshold override parameter exists
```

`effective_horizon = REGIME` is always resolved (an explicit owner
declaration, see §2), so — unlike PRICE_STRUCTURE/RELATIVE_STRENGTH in
#669/#672 — no `UNMAPPED_HORIZON` reason code applies to `ROTATION`
evidence.

## 7. Non-goals (explicit)

This completion does not:

- change any Rotation Pressure V1 formula, weight, threshold, or state
  enum in `src/research/run_market_rotation_pressure_v1.py`;
- touch, promote, rename, or average #593's C1/C2/C3 candidates;
- define or promote #449 Rotation Flip;
- create or alter any CQ temporal population/evaluation lane (#661/#568);
- change #591 Conviction semantics;
- implement `RegimeEvidenceEnvelopeV1` or any #617 dashboard/reporting;
- touch `selection_engine`, `decision_gate`, `execution_planner`,
  `executor`, account awareness, or broker calls;
- change runtime/deployment state (the gurkDB writer cadence, timers, and
  Issue #266 authorization are unaffected);
- add a database migration or rewrite historical rows;
- map market-level aggregate Rotation evidence (deferred, §5.1).

## 8. Safety

```text
architecture_contract_only=1
rotation_formula_changed=0
rotation_593_changed=0
rotation_flip_changed=0
cq_temporal_lane_changed=0
conviction_591_changed=0
selection_engine_changed=0
decision_gate_changed=0
execution_planner_changed=0
executor_changed=0
account_awareness_added=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation_changed=0
production_mutation_performed=0
production_deploy=0
```

## 9. Related documents / issues

- `docs/architecture/rotation_pressure_v1_authority_audit_v1.md` (#676 Phase A audit, BLOCKED_OWNER_DECISION)
- `docs/architecture/multi_horizon_signal_contract_v1.md` (#243)
- `docs/architecture/structure_relative_strength_evidence_contract_v1.md` (#669/#672 seam)
- `docs/architecture/multi_tf_conviction_contract_v1.md` (#591, unaffected)
- `db/migrations/20260712_market_rotation_pressure_v1.sql` (unmodified)
- `db/migrations/20260627_market_rotation_history_v1.sql` (unmodified; source of `input_interval`)
- `docs/research/market_rotation_pressure_v1.md` (updated to reflect promotion)
- `docs/ops/market_rotation_pressure_runtime_owners_v1.md` (Issue #266 writer authorization, unaffected)
- `docs/research/market_rotation_pressure_freshness_sla_measurement_v1.md` (#547 Phase B OBSERVED measurement, `BLOCKED_NEEDS_MEASUREMENT` still stands pending owner safety-margin decision)
- #617 regime evidence matrix (downstream consumer)
- #593 multi-horizon per-asset Rotation research/history (unaffected, not promoted)
- #449 Rotation Flip research (unaffected)
- #661 / #568 CQ temporal population/evaluation (unaffected)
- #266 Rotation Pressure production writer cutover (operational, unaffected)
- #676 this promotion
- #547 Rotation Pressure freshness pipeline Phase A (this document's §4 update: `BLOCKED_NEEDS_MEASUREMENT`, no `ROTATION_STALE_AFTER` adopted; measurement contract recorded for Phase B)
