# Automatic-exit profile promotion — canonical architecture contract (Issue #657 Phase A / Phase 1)

## Status

`BLOCKED` — architecture contract only. No promotion producer, no preview seam,
no production rows. This document is the reviewed Phase A deliverable required
by #657 before any Phase B implementation may start.

```text
producer_status=BLOCKED
preview_seam_status=NOT_IMPLEMENTED
db_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation=0
```

## Why this stops at a contract

`automatic_exit_profile_v1` (`db/migrations/20260814_automatic_exit_runtime_contract_v1.sql`)
and its resolver `resolve_automatic_exit_profile`
(`src/exit_policy/automatic_exit_runtime_contract_v1.py`) are already
implemented, tested, and correctly fail-closed on the empty table — this was
proven by #654's root-cause investigation. The missing piece is a producer,
and #657's own decision rule requires one only if a defensible canonical
upstream evidence source exists.

It does not, today:

- `docs/research/fib_exit_ladder_v1_findings.md` and
  `docs/todo/fibo_zones.md` both record the only existing candidate buckets
  (`EXIT_PROFILE_CONTROLLED_3X4X` for LINK/XLM,
  `EXIT_PROFILE_SUPERCYCLE_BALANCED` for SOL/XRP,
  `EXIT_PROFILE_EXPLOSIVE_MOONBAG` for HOT) as an initial 2021-window research
  result only, with the anchor detector itself still a research
  approximation.
- `docs/todo/fibo_zones.md` explicitly instructs: "Keep
  `asset_exit_profile_hint` as metadata only until downstream contracts are
  explicitly designed" and records the fib/target -> `asset_exit_profile`
  promotion scope as "not actionable, future review only, no Issue filed" at
  the time it was written.
- Issue #270 (`OPEN`, unresolved) owns exactly the required validation:
  whether the three exit-profile buckets remain valid beyond the 2021 window,
  a leak-free zone/fib touch evaluation, and native map level calibration.
  None of its three lanes has a validated conclusion.
- #657's own Phase-A/Phase-B dependency comment states this in terms that
  bind this document: "#657 must not promote the current 2021 buckets merely
  because the runtime now needs profiles... any producer capable of writing
  `automatic_exit_profile_v1` operational rows requires a documented #270
  validation conclusion (or another explicitly reviewed evidence source that
  supersedes it) first."

Per this repository's research-promotion rules and the #657 decision rule, a
Phase 1 implementation that invents generic default targets, or promotes the
unvalidated 2021 buckets, to unblock the runtime would be exactly the
fabricated-evidence shortcut those rules forbid. This document therefore
records the full design so that Phase B is mechanical once #270 (or an
explicitly reviewed replacement source) delivers a validated conclusion; it
adds no producer and no preview code.

## Required design decisions

### 1. Canonical upstream source(s) of truth

**Not yet established.** No repository artifact today constitutes validated,
canonical exit-target/invalidation evidence eligible for production
promotion. The only candidate lineage is:

```text
research fib/target maps (src/research/run_pro_target_ladder_preview_v1.py,
  src/research/run_fib_exit_ladder_backtest_v1.py)
-> Fib Exit Ladder V1 asset-profile buckets (2021 window, unvalidated)
-> asset_exit_profile_hint (metadata only, execution_planner contract preview)
```

Promotion to `automatic_exit_profile_v1` may proceed only once a specific,
named upstream artifact is validated and reviewed as canonical. The
candidates, in order of current relevance, are:

- Issue #270's validated Fib Exit Ladder bucket re-review (broader window),
  if it concludes the buckets are stable.
- Issue #270's leak-free zone/fib touch evaluator, if it is promoted to a
  validated strategy-candidate lane per `AGENTS.md` Strategy Candidate Rules.
- Issue #270's native map level calibration correction, if validated,
  changing which map levels are eligible inputs at all.
- A future, separately-scoped, non-fib canonical target/invalidation source
  (e.g. a validated volatility- or structure-based stop/target model) that
  explicitly supersedes the fib lineage.

Whichever source is chosen, the promotion producer must record it as an
explicit `method_version` string (see §9) so a later change of method is a
new version, never a silent redefinition of an existing `profile_id`.

**This document does not choose between these candidates.** That choice
belongs to the reviewed conclusion of #270 (or its explicit successor), not
to this contract.

### 2. Evidence eligibility (promotion criteria)

A candidate evidence artifact is eligible to back a promoted profile row only
if it satisfies every one of the following, mirroring the Strategy Candidate
Rules already required by `AGENTS.md`:

- Point-in-time replay validation with no look-ahead leakage (no latest
  context applied to historical windows; no future-return field applied to a
  live decision).
- Explicit sample size, average/median return, winrate, and profit factor
  for the specific asset/market the profile targets.
- Out-of-sample or walk-forward evidence, not only in-sample backtest.
- Explicit method/version identifier for the detector or model that produced
  the target/invalidation levels (e.g. a specific structure-detector
  version, not "current fib map").
- A recorded review conclusion (an Issue comment, merged doc, or equivalent
  reviewed artifact) stating the evidence is promotion-eligible. Historical
  profit alone, or an unreviewed research script's output, is never
  sufficient by itself.
- Freshness at promotion time: the evidence must not be stale relative to
  the source method's own validity window (a bull-run map computed against a
  structure state that has since flipped is not eligible even if the numeric
  levels still look plausible).

A producer must reject and refuse to emit a row for any asset/market lacking
all of the above, rather than falling back to a default or generic value.

### 3. Asset vs market scope

Profile scope is **market-level**, matching the existing
`automatic_exit_profile_v1` schema exactly: `(venue, asset_id, market)`, with
no strategy, horizon, or setup-context column. This is a deliberate
simplification already baked into the deployed Phase 4A schema and resolver
(`resolve_automatic_exit_profile` matches on venue/asset_id/market only), and
changing it would require a new migration, not just a new producer.

This means a promoted profile cannot yet distinguish
`(asset, strategy_family, horizon_bucket, setup_context)` per the canonical
Strategy Candidate Rules unit — it is deliberately coarser: one profile per
tradeable market. If a future validated evidence source needs per-strategy
granularity, that requires a schema change and is out of scope for a Phase B
producer built against the current table. Flag any such need back to a
schema-owning Issue rather than overloading `profile_id` to encode it
informally.

### 4. Global vs account-specific semantics

**Global.** `automatic_exit_profile_v1` carries no `trading_account_id`
column; it is explicitly documented in
`docs/architecture/automatic_exit_policy_v1.md` Phase 4A as "an append-only
market-level V1 policy input shared across accounts." A promotion producer
must not attempt to key profiles per account. Account-specific behavior
(whether an account may act on a profile at all) is owned entirely by
`automatic_exit_account_permission_v1` and `decision_gate`, never by the
profile itself. This document proves no account-scoped ownership for the
profile row; per `docs/ops/state_model_discipline_v1.md`, absent such proof,
no account-aware branching may be added to the promotion producer.

### 5. Versioning

- `profile_id` identifies one logical market policy lineage; `profile_version`
  identifies a specific revision. The table's
  `uq_automatic_exit_profile_revision (profile_id, profile_version)` unique
  key is the enforced identity.
- The resolver (`resolve_automatic_exit_profile`) additionally requires
  `profile_version == PROFILE_CONTRACT_VERSION` ("1"), i.e. the *contract*
  version, distinct from the per-row `profile_version` field name — a
  producer must set `profile_version="1"` for every row while
  `PROFILE_CONTRACT_VERSION` is `"1"`; a future contract version bump is a
  resolver-side change reviewed independently of any single promotion.
- A producer never mutates an existing row's price/evidence fields. A
  changed target/invalidation is always a new row with a new
  `(profile_id, profile_version)` pair (see §8, supersession).

### 6. `effective_from` / `effective_until` semantics

- `effective_from_ts_utc` is the timestamp from which the row is eligible to
  resolve, not the evidence's `observed_ts_utc`. A producer sets it to the
  promotion decision time (when the row is inserted / operator-approved),
  never backdated to make a row retroactively cover past evaluation cycles.
- `effective_until_ts_utc` is `NULL` for an open-ended row. The DB check
  constraint (`chk_automatic_exit_profile_window`) already requires
  `effective_until_ts_utc > effective_from_ts_utc` when set.
- Superseding a profile requires the producer to insert the new row with
  `effective_from_ts_utc` and, in the same promotion transaction/batch, set
  the prior row's `effective_until_ts_utc` to that same instant — see §8.
  Because the table has no immutability trigger today (unlike
  `automatic_exit_live_decision_gate_permission_v1`), this window-close write
  is technically an `UPDATE`, which contradicts the doc's own "append-only"
  characterization; §11 records this as a pre-Phase-B fix requirement, not a
  Phase A design gap to route around silently.

### 7. Freshness / staleness

- The resolver already enforces `max_profile_age_seconds` (default 15
  minutes, `DEFAULT_MAX_PROFILE_AGE_SECONDS`) against `observed_ts_utc`, and
  rejects `at - observed_ts_utc < 0` (future-dated evidence).
- A profile that is fundamentally not time-series-fresh in the same sense as
  a price snapshot (a fib map or structure-derived target does not change
  every 15 minutes) must still satisfy this window, because the resolver
  applies one fixed freshness bound uniformly. Two compliant designs exist,
  and the choice belongs to whichever producer implementation is scoped in
  Phase B, not to this contract:
  - **event-driven**: the producer re-observes evidence and re-emits a
    row (new `observed_ts_utc`, same `profile_id`, incremented
    `profile_version`) on a cadence at or below 15 minutes even when the
    underlying levels are unchanged, so the resolver never sees stale
    evidence; or
  - **resolver-side widening**: a reviewed change to
    `max_profile_age_seconds` (or a profile-class-specific freshness bound)
    for this evidence family, made explicitly and separately from any single
    producer's implementation.
- A producer must never synthesize a fresh `observed_ts_utc` without a
  genuinely re-observed evidence fact — that would silently defeat the
  freshness check's purpose.

### 8. Deterministic conflict resolution / exactly-one-effective-profile

Already fully owned by the existing resolver and already tested
(`tests/test_automatic_exit_runtime_contract_v1.py`):
`resolve_automatic_exit_profile` requires exactly one row whose
`(venue, asset_id, market)` matches and whose effective window contains the
query instant; zero or more-than-one matches both raise
`MISSING_OR_CONFLICTING_AUTOMATIC_EXIT_PROFILE`. A producer's obligation is
therefore purely upstream: never insert two rows for the same
`(venue, asset_id, market)` with overlapping effective windows. Supersession
(§6) must close the old window at exactly the new row's `effective_from`
instant, with no gap and no overlap, in one atomic promotion operation.

### 9. Provenance to source artifact/data/method version

Every promoted row must populate:

- `evidence_id`: a stable identifier for the specific evidence artifact
  (e.g. a research run ID, backtest output row ID, or fib map publication
  ID) — never a constant or placeholder.
- `evidence_provenance`: a human-legible string naming the producing
  method/script and its version (e.g.
  `"fib_exit_ladder_v1:<method_version>:<research_run_id>"`), sufficient for
  a reviewer to trace the row back to §1's chosen canonical source and §2's
  eligibility review artifact without a database join to a table that may
  not exist yet.
- `observed_ts_utc`: the timestamp the evidence was actually observed/computed
  — never the promotion/write time (that is `effective_from_ts_utc`, §6, and
  `created_ts_utc`, a DB default).

`automatic_exit_evaluation_audit_v1` already captures
`exit_profile_id`/`exit_profile_version`/`exit_profile_observed_ts_utc` as
idempotency evidence per `automatic_exit_idempotency_key_v1`, so provenance
recorded at promotion time is preserved transitively into every downstream
audit row without any additional plumbing.

### 10. Supersession and rollback

- Supersession is append-only: a new `(profile_id, profile_version)` row
  with a later `effective_from_ts_utc`; see §6/§8 for the atomic window
  transition.
- Rollback to a prior profile is not a delete or an `UPDATE` of the
  superseding row. It is a new row that re-asserts the prior row's
  target/invalidation values under a new `profile_version`, so the full
  history remains an accurate, append-only audit trail of what was actually
  effective at every instant. This mirrors the pattern already proven for
  `automatic_exit_live_decision_gate_permission_v1`
  (revocation-by-fact, never mutation).
- A producer must never delete a row. If §11's immutability trigger is added
  before Phase B, this becomes DB-enforced rather than convention-only.

### 11. Pre-Phase-B schema fix requirement

`automatic_exit_profile_v1` has no DB trigger rejecting `UPDATE`/`DELETE`,
unlike `automatic_exit_live_decision_gate_permission_v1`
(`db/migrations/20260818_automatic_exit_live_decision_gate_permission_v1.sql`).
The current doc text calling it "append-only" is a convention, not a DB
guarantee. §6's window-close step needs exactly one `UPDATE` (setting
`effective_until_ts_utc` on the row being superseded) to keep the "exactly
one effective row" invariant without ever creating an overlapping pair
visible to concurrent readers. Two compliant paths, to be resolved by
whichever migration accompanies the Phase B producer, not by this document:

- add a trigger that permits exactly one `UPDATE` of
  `effective_until_ts_utc` from `NULL` to a later timestamp and rejects
  every other mutation; or
- redesign supersession as pure-insert by giving the resolver a
  "most-recently-inserted still-open-ended-or-covering row wins, ties are
  conflicts" rule instead of relying on an explicit window close.

This is flagged as a decision Phase B must resolve, not left implicit.

### 12. Exclusion of `MANUAL_RFQ`, `MANUAL`, and `NONE` execution modes

Canonical execution-mode classification already exists and is
independently owned by `src/execution_capability/execution_capability_v1.py`
(Issue #638): `AUTOMATED`, `MANUAL_RFQ`, `MANUAL`, `NONE`, with
`capability_for_mode` returning `automated_execution_eligible=True` only for
`AUTOMATED`.

A promotion producer must query `asset.execution_mode` (the same field
Issue #653 wires into automatic-exit runtime evidence assembly) before
emitting any row for an asset, and must refuse to emit a profile for any
asset whose `execution_mode` is not `AUTOMATED`. This is evidence gating at
promotion time, distinct from and in addition to the existing runtime-side
exclusion Issue #653 is fixing (which prevents the *evaluator* from
requiring a `venue_market` for manual assets). Promoting a profile for a
manual/RFQ/non-executable asset would be dead, misleading operational data:
`decision_gate`/`execution_planner` never reach automatic-exit
target/invalidation logic for those assets regardless, so such a row could
only mislead a human reviewer inspecting `automatic_exit_profile_v1`
directly.

### 13. Operator approval boundary before production promotion

No producer may write directly to `automatic_exit_profile_v1` from an
unattended/scheduled process while promotion is new. The required boundary,
mirroring the read-only-preview-then-approval pattern already used elsewhere
in this repository (`execution_planner/contract_preview_v1.py`):

```text
evidence eligibility check (producer, read-only)
-> proposed profile row(s) with full provenance (preview output, no DB write)
-> explicit human operator review of the preview output
-> explicit human-triggered promotion write (separately scoped, reviewed Issue)
```

The preview stage may be automated (computed on a schedule or on demand);
the write stage may not be, until this repository has separately reviewed
and accepted an unattended-write producer for this table. This document
does not implement the preview stage (see "Why this stops at a contract");
it fixes the boundary's shape so Phase B's preview, when built, has no
ambiguity about where automation must stop.

## Phase B entry criteria (must all hold before implementation starts)

1. #270 (or an explicitly reviewed successor Issue) records a validated
   conclusion for a specific evidence source per §1/§2, merged as reviewed
   documentation.
2. §11's schema fix (trigger or insert-only redesign) is itself reviewed and
   applied via migration.
3. A Phase B Issue explicitly scopes: which producer script, its input
   evidence table(s)/artifact(s), its cadence, its host (per `AGENTS.md`
   host-ownership rules), and confirms the preview/approval boundary in §13.
4. The Phase B preview implementation satisfies the test list below before
   any write-capable code is proposed.

## Required tests once a deterministic source exists (Phase B, not this doc)

```text
deterministic preview: same evidence input -> same proposed row(s), no clock/
  random/network dependency
exactly-one semantics: proposed rows for one (venue, asset_id, market) never
  overlap in effective window
conflict fail-closed: ambiguous/overlapping candidate evidence produces no
  proposed row, not a best-guess pick
stale/missing evidence fail-closed: evidence older than its method's validity
  window, or absent, produces no proposed row
manual/RFQ/NONE excluded: no proposed row for any asset whose
  execution_mode != AUTOMATED
no account-awareness: preview output carries no trading_account_id and does
  not branch on any account fact
zero DB writes: preview process performs no INSERT/UPDATE/DELETE
no execution-layer imports: preview module imports nothing from
  decision_gate, execution_planner, executor, or broker packages
  (enforceable by the same AST-guard pattern already used in
  tests/test_automatic_exit_runtime_architecture_guards_v1.py)
```

## Non-goals (this document and any Phase B built from it)

- No fabricated/default target or invalidation values.
- No promotion of the unvalidated 2021 Fib Exit Ladder buckets absent a
  reviewed #270 (or successor) conclusion.
- No account-aware profile semantics.
- No `decision_gate`, `execution_planner`, or `executor` bypass.
- No broker calls, order submission, or LIVE authority change.
- No unattended write path until separately reviewed per §13.

## Related

- #657 (this Issue), #654 (root-cause investigation this document extends),
  #666 (V1 priority amendment), #270 (blocking research validation), #653 /
  #655 / #656 (execution-mode routing this document's §12 depends on), #392
  (Phase 4B runtime orchestrator, the resolver's only current caller).
- `docs/architecture/automatic_exit_policy_v1.md` — existing Phase 1-6
  automatic-exit contract; this document extends its "Known production gap"
  section without modifying it.
- `docs/todo/fibo_zones.md`, `docs/research/fib_exit_ladder_v1_findings.md` —
  candidate evidence lineage and its explicit non-promotion status.
