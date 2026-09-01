# PRICE_STRUCTURE / RELATIVE_STRENGTH Evidence Contract Completion v1

Status: Permanent architecture contract
Canonical location: `docs/architecture/structure_relative_strength_evidence_contract_v1.md`
Scope: contract completion only — no new indicator engines, no schema migration
Runtime impact: none (pure functions, no DB access, no I/O)
Issue: #669
Upstream owners: #243 (`docs/architecture/multi_horizon_signal_contract_v1.md`),
`docs/architecture/regime_evidence_matrix_audit_v1.md` (#617 audit)
Downstream: #617 (`RegimeEvidenceEnvelopeV1`, remains out of scope here)

## 1. Purpose

`docs/architecture/regime_evidence_matrix_audit_v1.md` found that neither
PRICE_STRUCTURE nor RELATIVE_STRENGTH satisfies the canonical
`SignalHorizonV1` contract (#243): both lack `effective_horizon`,
`observed_lifecycle`, and a freshness/staleness rule, and
`relative_strength_snapshot` additionally has no provenance field at all.

This document completes both families as consumable, replay-safe evidence
by adding a pure mapping layer over the existing producers. It does not
change producer calculation, does not add a schema migration, and does not
resolve the `effective_horizon` ownership gap — it makes that gap explicit
and machine-readable instead of silent.

## 2. Canonical producers (unchanged)

```text
PRICE_STRUCTURE
  producer: src/structure/trend_state_v1.py (ENGINE_VERSION "1.2")
            src/measurement/run_structure_state_engine.py
  table:    structure_state

RELATIVE_STRENGTH
  component RECLAIM:
    producer: same as PRICE_STRUCTURE (structure_state.reclaim_state/reclaim_score)
  component CROSS_SECTIONAL_RANK:
    producer: src/features/relative_strength_snapshot.py
    table:    relative_strength_snapshot
```

Per the audit, these two RELATIVE_STRENGTH components are not reconciled
into one canonical value. This contract preserves them as two separately
identified components rather than forcing consensus (#243 §4.5 "Preserve
both observations separately"). Reconciliation remains an explicit open
owner decision (audit §5 item 3), not resolved here.

ETH/BTC leadership is not part of `relative_strength_snapshot` (confirmed:
no BTC/ETH-specific logic in that producer) and is out of scope for this
completion, unchanged from the audit's finding.

## 3. Completed contract shape

New modules add a pure `SignalHorizonV1Evidence` mapping layer:

```text
src/features/evidence_contract_v1.py                    shared enums/helpers
src/features/structure_evidence_contract_v1.py           PRICE_STRUCTURE (TREND/PULLBACK/RANGE)
                                                          + RELATIVE_STRENGTH.RECLAIM
src/features/relative_strength_evidence_contract_v1.py   RELATIVE_STRENGTH.CROSS_SECTIONAL_RANK
```

Each builder function takes an already-fetched producer row plus an
explicit `evaluated_at` timestamp and returns a `SignalHorizonV1Evidence`
with:

```text
family, component, market
status                  VALID | STALE | INSUFFICIENT_DATA (today always
                         INSUFFICIENT_DATA — see §3.2/§3.4)
model_id, model_version
input_interval
lookback_horizon
effective_horizon       always UNKNOWN today (see §4)
observed_lifecycle      always UNMEASURED (neither producer measures lifecycle)
asof_ts, freshness
provenance
raw                     verbatim producer state/score/numeric fields
reason_codes
```

No DB access, no lookup of "latest" state: callers pass the exact row for
the timestamp being evaluated, so a replay caller can never receive
current/live truth for a historical `asof`.

### 3.1 Producer timestamp mapping

```text
structure_state.asof_ts_utc          -> asof_ts   (unchanged correction from #617 audit)
relative_strength_snapshot.snapshot_ts_utc -> asof_ts (per #669's explicit correction —
                                                        this is a real producer as-of
                                                        timestamp, not absent)
```

### 3.2 Freshness rule (producer-owned; not invented here)

Per #243 §3.5, `freshness` is producer-owned. Neither `structure_state_engine`
nor `relative_strength_snapshot` has a reviewed staleness rule, so
`evidence_contract_v1.compute_freshness` does not invent one — no
interval-relative threshold, no caller-supplied threshold:

```text
asof_ts absent                         -> freshness=INSUFFICIENT_DATA (MISSING_ASOF_TS)
asof_ts after evaluated_at             -> freshness=INSUFFICIENT_DATA (ASOF_AFTER_EVALUATION_TS)
                                           (a producer timestamp from the future relative
                                           to the replay/evaluation point is a data-integrity
                                           contradiction, not a staleness judgement)
asof_ts present, otherwise             -> freshness=UNKNOWN (FRESHNESS_NOT_OWNER_DEFINED)
```

`FreshnessState.FRESH`/`STALE` remain reserved enum values for a future
producer-owned rule; this contract never emits them. Promoting a producer
to FRESH/STALE requires an explicit upstream owner decision recording a
reviewed staleness rule for that producer specifically, tracked outside
this issue.

Both `asof_ts` and `evaluated_at` are normalized to aware UTC
(`evidence_contract_v1.normalize_to_utc`) before comparison: persisted
`structure_state`/`relative_strength_snapshot` rows are naive-UTC (the
writers strip tzinfo before `INSERT`), so a naive producer value is
interpreted as UTC and a non-UTC aware value is converted via
`astimezone`, never compared against a naive value directly.

### 3.3 Model identity / provenance

```text
PRICE_STRUCTURE / RECLAIM:
  model_id maps from persisted engine_name only when it exactly equals
    "structure_state_engine"; otherwise model_id=None.
  model_version maps from persisted engine_version only when it is in the
    reviewed set {"1.2"}; otherwise model_version=None.
  missing engine_name        -> MISSING_ENGINE_NAME, fails closed
  engine_name != "structure_state_engine" -> UNEXPECTED_ENGINE_NAME, fails closed
  missing engine_version     -> MISSING_ENGINE_VERSION, fails closed
  engine_version not reviewed -> UNSUPPORTED_MODEL_VERSION, fails closed
  Never substitutes/fabricates a model_id merely because engine_version
  is present, and never fabricates a model_id from this producer's own
  ENGINE_NAME constant without checking the persisted value first.

CROSS_SECTIONAL_RANK:
  relative_strength_snapshot has no model_id/model_version column at all.
  model_id/model_version must be supplied explicitly by a caller that owns
  a reviewed identity for the run; omitted -> MISSING_PROVENANCE, fails
  closed. This contract does not fabricate provenance for a producer that
  never persisted it.
```

### 3.4 `effective_horizon` (deliberately left unresolved)

`structure_state_engine` and `relative_strength_snapshot` have never
declared an `effective_horizon` (#243 §3.3: producer-owned, must not be
inferred from `input_interval`). Per #669's required fail-closed behavior
("unknown/unmapped horizon -> INSUFFICIENT_DATA"), every evidence produced
by this completion therefore carries `effective_horizon = UNKNOWN` and an
`UNMAPPED_HORIZON` reason code, and its top-level `status` is
`INSUFFICIENT_DATA` even when identity and provenance are otherwise clean.

This is an honest, deterministic reflection of the current gap, not a
defect: the `freshness` and `reason_codes` fields still record the
specific reason(s) independently, so a future horizon-owner decision
(tracked outside this issue) can be layered on without touching this
mapping's identity/provenance logic. This document does not invent a
horizon mapping to make the top-level status look complete.

### 3.5 `observed_lifecycle`

Neither producer measures lifecycle. Every evidence emits
`ObservedLifecycle(status=UNMEASURED)` per #243 §3.4 ("do not invent typical
durations when they have not been measured").

## 4. Fail-closed behavior summary

```text
missing asof_ts                -> freshness=INSUFFICIENT_DATA (MISSING_ASOF_TS)
asof_ts after evaluated_at     -> freshness=INSUFFICIENT_DATA (ASOF_AFTER_EVALUATION_TS)
asof_ts present, no owner rule -> freshness=UNKNOWN (FRESHNESS_NOT_OWNER_DEFINED);
                                   status=INSUFFICIENT_DATA (compounds with the
                                   permanent UNMAPPED_HORIZON gap, see §3.4)
unknown input_interval         -> status=INSUFFICIENT_DATA (UNKNOWN_INPUT_INTERVAL)
missing/wrong engine_name      -> status=INSUFFICIENT_DATA (PRICE_STRUCTURE/RECLAIM only)
missing/unsupported engine_version -> status=INSUFFICIENT_DATA (PRICE_STRUCTURE/RECLAIM only)
missing provenance              -> status=INSUFFICIENT_DATA (CROSS_SECTIONAL_RANK default)
naive vs aware asof_ts/evaluated_at -> normalized to aware UTC before any comparison
replay                          -> caller-supplied row + evaluated_at only; no internal
                                    "latest" query exists in these modules
```

## 5. Non-goals (explicit)

This completion does not:

- change `trend_state_v1.py`, `run_structure_state_engine.py`, or
  `relative_strength_snapshot.py` calculation logic or thresholds;
- add a database migration or new persisted column;
- reconcile `structure_state.reclaim_*` with `relative_strength_snapshot`
  into a single RELATIVE_STRENGTH value;
- resolve `effective_horizon` ownership for either producer;
- implement ETH/BTC leadership, Rotation, CQ temporal population, or
  Conviction semantics (owned by #593, #661, #591 respectively);
- implement `RegimeEvidenceEnvelopeV1` or any #617 dashboard/reporting;
- touch `selection_engine`, `decision_gate`, `execution_planner`,
  `executor`, account awareness, or broker calls.

## 6. Safety

```text
new_structure_thresholds_added=0
new_relative_strength_thresholds_added=0
schema_migration_added=0
db_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate_changed=0
execution_planner_changed=0
executor_changed=0
selection_engine_changed=0
account_awareness_added=0
rotation_contract_changed=0
cq_temporal_lane_changed=0
production_deploy=0
```

## 7. Related documents / issues

- `docs/architecture/multi_horizon_signal_contract_v1.md` (#243)
- `docs/architecture/regime_evidence_matrix_audit_v1.md` (#617 audit)
- #617 regime evidence matrix / multi-TF momentum-trend stack (downstream)
- #593 multi-horizon per-asset Rotation research/history (unrelated, unchanged)
- #661 canonical daily PIT CQ v1 (unrelated, unchanged)
- #591 Multi-TF Conviction (unrelated, unchanged)
