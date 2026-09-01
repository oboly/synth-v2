# Market Rotation Pressure V1 — Canonical Authority Audit v1

Status: Permanent architecture audit (blocking finding, no implementation)
Canonical location: `docs/architecture/rotation_pressure_v1_authority_audit_v1.md`
Scope: audit-only — resolve whether Market Rotation Pressure V1 is a
production-safe canonical evidence owner for downstream #617
Runtime impact: none
Issue: #676
Upstream owner: #243 (`docs/architecture/multi_horizon_signal_contract_v1.md`)
Related: #617, #591, #593, #449, #661/#568 (unaffected, unaltered)

## 1. Purpose

#676 asked whether the existing Market Rotation Pressure V1 lane is a
production-safe canonical evidence owner, so that (if so) the smallest
missing mapping into the `SignalHorizonV1` evidence-contract seam
introduced by #669/#672 (`src/features/evidence_contract_v1.py` and its two
family adapters) could be completed for `family=ROTATION`.

This is not a new Rotation model, and #243's own horizon interpretation
(`lookback_horizon: 24h + 168h`, `effective_horizon: REGIME`,
`observed_lifecycle: UNMEASURED unless backed by persisted empirical
analysis`) is used here only as horizon interpretation, per the task
contract, never as evidence that #243 itself promoted the lane to
production.

## 2. Method

Re-audited current `origin/main` directly (producer module, migration,
dashboard, ops runtime docs, #591 contract doc) rather than trusting the
prior finding in `docs/architecture/regime_evidence_matrix_audit_v1.md`
§3.5. No new indicator math, thresholds, tables, or Rotation model changes
were introduced to perform this audit. #593 (C1/C2/C3 multi-horizon
research/replay), #449 (Rotation Flip), and #661/#568 (CQ temporal
population/evaluation) were not touched, read for modification, or
referenced beyond confirming they are unaffected.

## 3. Findings

### 3.1 Producer / storage / identity

- Producer: `src/research/run_market_rotation_pressure_v1.py`. Its own CLI
  docstring (line 552): `"Research-only Synth market rotation pressure
  scoring"`.
- Persisted tables: `market_rotation_pressure_snapshot_v1` (aggregate) and
  `market_rotation_pressure_observation_v1` (per-asset), both defined in
  `db/migrations/20260712_market_rotation_pressure_v1.sql`. That file has
  exactly one commit in its history; its header has never been edited:

  ```text
  db/migrations/20260712_market_rotation_pressure_v1.sql:1  -- Migration: market_rotation_pressure_v1
  db/migrations/20260712_market_rotation_pressure_v1.sql:2  -- Boundary: research-only · market-only · account-agnostic
  db/migrations/20260712_market_rotation_pressure_v1.sql:3  --           no account, balance, position, order, broker, decision, planning, or execution coupling
  ```

- `model_version` is a real persisted column, set from
  `MODEL_VERSION = "1.0"` (`run_market_rotation_pressure_v1.py:13`, written
  at lines 481/506). No `model_id` column/field exists anywhere in the
  schema or producer.
- `asof` = `as_of_ts_utc` (`DATETIME(6)`), resolved from the underlying
  `market_rotation_snapshot_v1` source table where both a 24h and a 168h
  horizon row exist for the same timestamp
  (`run_market_rotation_pressure_v1.py:364-397`) — not wall-clock "now".
- Natural key `(as_of_ts_utc, venue, model_version)`, `INSERT IGNORE`
  writer (lines 476, 493): append-only, not upsert-to-latest. Consumed for
  replay by several `src/research/` modules (dataset builders, PIT
  extractors) — research replay usage exists and is unaffected by this
  audit.

### 3.2 Raw score / state semantics (unchanged, not touched)

Raw composition matches #243 §7.1 exactly, with no discrepancy found:

```text
run_market_rotation_pressure_v1.py:22-30
WEIGHTS = {return_24h:25%, signed_volume_24h:20%, return_7d:15%,
           signed_volume_7d:10%, acceleration:15%, market_relative:10%,
           persistence:5%}
market_score = sum(component * weight) / 100.0   (line 247)
```

Categorical states (all producer-owned, unchanged): `acceleration_state`,
`concentration_state`, `confirmation_state`, `market_direction`,
per-asset `pressure_state`, per-asset `phase_state` — full enum lists and
`file:line` citations are recorded in the #676 audit working notes and are
not reproduced here since they are descriptive-only and this document adds
no new state.

### 3.3 `effective_horizon` / `observed_lifecycle` / `input_interval`

- No `effective_horizon`, `observed_lifecycle`, or `input_interval` column
  exists anywhere in the persisted schema or producer. All three exist only
  as interpretive text in `docs/architecture/multi_horizon_signal_contract_v1.md`
  §7.1 (lines 347-350) — a documentation-level assertion, not a code-level
  fact. Per the #676 task contract, this document is used only for horizon
  *interpretation* if and when a promotion decision is made; it is not
  itself that decision.

### 3.4 Freshness ownership

`classify_freshness()` lives in the **reporting/dashboard** layer, not the
producer: `src/reporting/market_rotation_pressure_dashboard_v1.py:107-122`,
with `DEFAULT_STALE_AFTER = timedelta(hours=2, minutes=30)`
(same file, line 10). The producer module itself has no freshness/staleness
concept. This confirms the prior audit's distinction precisely: freshness
here is consumer/dashboard-owned, not an upstream-producer-reviewed rule.

### 3.5 Production consumption

- Zero references under `src/selection/`, `src/decision_gate/`,
  `src/execution_planner/`, or `src/executor/` (grep-confirmed empty).
- Reporting-layer consumption exists: `src/reporting/market_rotation_pressure_dashboard_v1.py`
  is imported by `src/reporting/market_rotation_profit_plan_projection_v1.py`,
  `src/reporting/run_manual_short_trader_profit_plan_v1.py`, and
  `src/reporting/manual_short_trader_profit_plan_v1.py` (Manual SHORT Trader
  Profit Plan reads `market_rotation_pressure_snapshot_v1` directly at
  render time per `docs/ops/market_rotation_pressure_runtime_owners_v1.md:236-240`).
- Per `docs/ops/market_rotation_pressure_runtime_owners_v1.md:212-232`, on
  2026-08-08, under explicit user production-cutover authorization for
  Issue #266, the gurkDB writer timer was enabled
  (`sudo systemctl enable --now synth-market-rotation-pressure-writer.timer`),
  recording `production_runtime_owner=gurkdb`,
  `production_authorization_status=AUTHORIZED`, `runtime_lifecycle=ACTIVE`,
  with a confirmed real hourly write cycle. This is a genuine, explicit,
  user-authorized operator decision to run the writer in production — it is
  not an unauthorized or accidental activation.

### 3.6 The unresolved conflict (unchanged since the prior #617 audit)

Three artifacts about the *same lane* disagree and have never been
reconciled by any commit:

```text
migration header (architecture-owning)   -> research-only · market-only · account-agnostic
                                             (db/migrations/20260712_market_rotation_pressure_v1.sql:2,
                                              never edited since creation)
design doc (architecture-owning)         -> "research/shadow" (docs/research/market_rotation_pressure_v1.md:37)
producer CLI docstring                   -> "Research-only ... scoring"
                                             (src/research/run_market_rotation_pressure_v1.py:552)

#243 itself (upstream horizon owner)     -> silent on promotion; only says
                                             "Owner: existing Rotation Pressure market-only lane"
                                             (docs/architecture/multi_horizon_signal_contract_v1.md:328)

#591 contract doc (downstream consumer)  -> asserts, on its own authority, that Rotation
                                             Pressure V1 is "the one canonical, accepted,
                                             versioned, persisted per-asset lane with real
                                             asof_ts and model_version"
                                             (docs/architecture/multi_tf_conviction_contract_v1.md:62-64)

ops runtime doc (operational authority)  -> production_authorization_status=AUTHORIZED,
                                             runtime_lifecycle=ACTIVE, under explicit
                                             user cutover authorization for Issue #266
                                             (docs/ops/market_rotation_pressure_runtime_owners_v1.md:212-224)
```

The ops-layer production authorization is a real, explicit, user-approved
*runtime* decision (the writer may run on gurkdb). It is not, by itself, an
*architectural* decision that reclassifies the lane's evidence-boundary
status for downstream consumers like #617/#676 — no commit has touched the
migration boundary comment or the design doc's `research/shadow` label to
reflect it, and #591's "canonical, accepted" characterization is its own
downstream assertion, not something #243 or the migration itself grants.
Per the #676 task contract ("Do NOT treat #243 as proof that Rotation V1
was promoted to production" / "Do not invent authority"), this audit cannot
resolve that gap by inference.

## 4. Decision

**BLOCKED_OWNER_DECISION.**

This is a genuine, unresolved owner-boundary conflict between the lane's
own architecture-owning artifacts (migration + design doc + producer
docstring, all still "research-only"/"shadow") and both a downstream
document's unilateral "canonical, accepted" characterization (#591 §2) and
an operational production-authorization record (Issue #266) that never
updated the architectural boundary label. #676 has no authority to decide
this unilaterally, per its own task contract, and this audit does not
guess or manufacture a resolution.

No `family=ROTATION` evidence-contract mapping is added in this PR.
Consistent with the required fail-closed behavior: **unresolved authority
-> no active Rotation evidence.**

## 5. Required owner/promotion decision (either path, explicitly)

One of the following, made by whoever owns the migration/design-doc
architecture boundary (not #676, not this audit):

**(a) Promote the lane.** If the Issue #266 production-cutover decision is
intended to also mean "this lane is canonical production evidence, not
research-only market-only shadow output":
  - correct `db/migrations/20260712_market_rotation_pressure_v1.sql:2-3`'s
    boundary comment to reflect the promotion (a migration comment edit,
    not a schema change);
  - correct `docs/research/market_rotation_pressure_v1.md:37`'s
    `research/shadow` characterization and the producer CLI docstring
    (`run_market_rotation_pressure_v1.py:552`) to match;
  - explicitly record what "promoted" means for reporting-only consumption
    vs. any future `selection_engine`/`decision_gate` consumption (none
    exists today; this audit found zero such references, so promotion here
    would only affect reporting/evidence-contract consumers).
  - Only after that correction should a follow-up issue add the
    `family=ROTATION` mapping into `src/features/evidence_contract_v1.py`'s
    seam, reusing exactly the pattern in
    `src/features/structure_evidence_contract_v1.py` /
    `relative_strength_evidence_contract_v1.py`: `model_id` would still
    need a value (none persisted today — same `MISSING_PROVENANCE` fail-
    closed gap already documented for `relative_strength_snapshot` in
    `docs/architecture/structure_relative_strength_evidence_contract_v1.md`
    §3.3), `effective_horizon=REGIME` would need a producer-level (not
    doc-level) declaration to stop failing closed on `UNMAPPED_HORIZON`,
    and `freshness` would need the dashboard's `classify_freshness()`
    rule (or an equivalent) explicitly adopted as producer-owned rather
    than dashboard-only, per #676's fail-closed requirement ("stale only
    if an existing reviewed producer-owned rule supports it").

**(b) Correct the downstream characterization.** If the lane is intended
to remain research-only/shadow despite the Issue #266 writer activation:
  - correct `docs/architecture/multi_tf_conviction_contract_v1.md:62-64`
    (#591 §2) to remove or qualify the "canonical, accepted" claim;
  - treat the existing reporting-layer consumption (Manual SHORT Trader
    Profit Plan, `market_rotation_pressure_dashboard_v1.py` and its three
    importers) as a boundary question for its owning issue to resolve
    separately — this audit does not open or resolve that question, only
    surfaces it;
  - the Issue #266 writer activation would then need its own explicit
    reviewed statement that production *writing* is authorized while the
    data remains architecturally research-only for evidence-contract
    purposes (an unusual but not inherently invalid split, if that is the
    intent).

Neither path is decided here. This document exists so a future decision
does not have to re-derive this evidence from scratch.

## 6. Non-goals confirmed for this slice

Per the #676 task contract, this audit performs no Rotation formula/weight
changes, no #593 C1/C2/C3 changes, no #449 Rotation Flip work, no CQ/#661/
#568 lane, no #591 Conviction changes, no #617 dashboard/reporting
implementation, no `selection_engine`/`decision_gate`/`execution_planner`/
`executor` changes, no account awareness, and no new generic evidence
framework (the existing #669/#672 seam is confirmed reusable once/if a
promotion decision is made).

## 7. Safety

```text
architecture_contract_only=1
audit_only=1
new_rotation_algorithm_added=0
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
production_mutation_performed=0
production_deploy=0
```

## 8. Related documents / issues

- `docs/architecture/multi_horizon_signal_contract_v1.md` (#243)
- `docs/architecture/regime_evidence_matrix_audit_v1.md` (#617 audit, prior finding)
- `docs/architecture/multi_tf_conviction_contract_v1.md` (#591)
- `docs/architecture/structure_relative_strength_evidence_contract_v1.md` (#669/#672 seam)
- `db/migrations/20260712_market_rotation_pressure_v1.sql`
- `docs/research/market_rotation_pressure_v1.md`
- `docs/ops/market_rotation_pressure_runtime_owners_v1.md` (Issue #266 activation)
- #617 regime evidence matrix (downstream, blocked on this decision)
- #593 multi-horizon per-asset Rotation research/history (unaffected)
- #449 Rotation Flip research (unaffected)
- #661 / #568 CQ temporal population/evaluation (unaffected)
- #266 Rotation Pressure production writer cutover (operational authorization only)
- #676 this audit
