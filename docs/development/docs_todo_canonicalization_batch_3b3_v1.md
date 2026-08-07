# Docs/TODO Canonicalization — Batch 3B3

## 1. Status

COMPLETE

## 2. Source-section classification

Source: `docs/todo/synth_v214_signal_dashboard_strategy_bridge_backlog.md`
(289 lines, tracked on `origin/main` at base commit `a788bbfd`, removed by
this batch).

| Source section | Classification | Disposition |
| --- | --- | --- |
| Title / intro | `historical_backlog` | Framing preserved in archive intro. |
| A. Problem Summary | `historical_backlog` | Moved to archive, "v2.14-specific dashboard complaints". |
| B. Correct Architecture | `canonical_architecture` | Restated in `strategy_proposal_contract_v1.md` Section 2 (Separation of concerns). |
| C. Signal Dashboard Direction | `existing_owner` | Owned by `docs/todo/signal_matrix_dashboard.md` (still active); not duplicated. |
| D. Horizon-Separated Dashboard | `existing_owner` | Owned by `docs/todo/signal_matrix_dashboard.md` / `docs/todo/manual_ladder_dashboard.md` horizon reading-order sections; not duplicated. |
| E. UI Design Principles | `reporting_guidance` | Durable principle ("no hidden final labels", human labels first) folded into `strategy_proposal_contract_v1.md` Section 13; layout specifics remain owned by `docs/todo/manual_ladder_dashboard.md`. |
| F. Strategy-Linked Proposals (id format, ACTION/HORIZON/SETUP enums, synonym rules, required fields, candidate strategies) | `canonical_schema` | Canonicalized into `strategy_proposal_contract_v1.md` Sections 3-9. Candidate strategy examples moved to archive (unvalidated). |
| Strategy Profile Ownership (unlettered, under F) | `account_aware_configuration` | Canonicalized into `strategy_proposal_contract_v1.md` Section 8. |
| Bucket Allocation Model (unlettered, under F) | `account_aware_configuration` | Canonicalized into `strategy_proposal_contract_v1.md` Section 8; `bucket_id` (reference) and `bucket_target_pct`/`bucket_available_pct`/`bucket_current_pct` (account state) are all excluded from the proposal schema and assigned to the `decision_gate` input envelope / `decision_gate` account state (Section 3a). |
| Strategy Leg Lifecycle (unlettered, under F) | `canonical_schema` | Canonicalized into `strategy_proposal_contract_v1.md` Section 9 (proposal lifecycle) and Section 6 (horizon cadence examples). |
| G. LLM / Agent Bridge | `temporary_bridge` | Durable boundary canonicalized into `strategy_proposal_contract_v1.md` Section 11; cross-referenced against existing `docs/ops/runtime_chain_ownership_v1.md` "Agent / LLM Bridge Boundary" (`existing_owner` for the runtime-ownership-side statement of the same boundary). |
| H. Manual Fallback Path | `temporary_bridge` | Durable transport principles canonicalized into `strategy_proposal_contract_v1.md` Section 12; XLSX explicitly demoted from "canonical format" to "optional transport". Excel/dropfolder implementation itself is `future_issue_candidate` (Section 10 below). |
| I. Breath / A+ Separation | `existing_owner` | Owned by `docs/ops/market_breath_context_bridge_v1.md` (Synth breath vs. A+ legacy separation, freshness bands) and `docs/research/external_research_ingestion_v1.md` (A+ as external research). Not duplicated; cross-referenced in Section 15 of the new contract. |
| J. Freshness Model | `existing_owner` | Owned by `docs/ops/runtime_chain_ownership_v1.md` "Freshness Contract"; restated by reference in `strategy_proposal_contract_v1.md` Section 10, not duplicated. |
| K. External Research / Macro Context | `existing_owner` | Owned by `docs/research/external_research_ingestion_v1.md` and `docs/research/external_elliott_wave_claim_validation_v1.md`. Not duplicated. |
| L. Deferred Implementation Order (10 steps) | mixed — see Section 9/10 below | Step-by-step disposition in Sections 9-10. |
| M. Anti-Patterns To Avoid | `canonical_architecture` | Canonicalized into `strategy_proposal_contract_v1.md` Section 14, merged with anti-patterns already implied by Sections 2/8/11. |
| Existing Overlap (closing list) | `superseded` | The listed `docs/todo/external_research_ingestion.md` entry was already repaired in Batch 3B1 (PR #251) to point at the two split canonical research docs; the remaining listed docs (`signal_matrix_dashboard.md`, `manual_ladder_dashboard.md`, `runtime_chain_ownership_v1.md`, `market_breath_context_bridge_v1.md`) are the `existing_owner` rows above. |

`unclassified_substantive_sections=0`. No section required an `ambiguous`
or `future_issue_candidate` top-level classification on its own — items 6-8
of Section L (Deferred Implementation Order) resolve to `future_issue_candidate`
at the individual-step level; see Section 10.

## 3. Existing canonical overlap

Inspected before writing the new contract (per task Section 1):

- `docs/todo/signal_matrix_dashboard.md` — active, current; signal inventory
  and horizon-separated matrix scope. Not superseded.
- `docs/todo/manual_ladder_dashboard.md` — active, current; asset-card
  dashboard and UI display scope. Not superseded.
- `docs/ops/runtime_chain_ownership_v1.md` — active; runtime ownership,
  freshness contract, and an existing "Agent / LLM Bridge Boundary" section
  with `strategy_id`/`input_context_run_id`/`created_ts`/`expiry_ts`
  requirements consistent with the new contract. Cross-referenced, not
  duplicated.
- `docs/ops/market_breath_context_bridge_v1.md` — active; Synth breath vs.
  A+ legacy separation. Cross-referenced, not duplicated.
- `docs/research/external_research_ingestion_v1.md` and
  `docs/research/external_elliott_wave_claim_validation_v1.md` — active
  research-only contracts (canonicalized in Batch 3B1). Cross-referenced.
- `docs/research/paper_advice_manual_trading_cockpit_v1.md` — active,
  read-only manual-review cockpit role. Cross-referenced.
- `docs/research/breath_fibo_strategy_static_dashboard_v1.md` — active,
  market-only research strategy dashboard; not a proposal-schema document,
  no conflict.
- **`docs/research/synth_v215_advice_route_contract_v1.md` — the most
  significant overlap found.** This research-stage document already defines
  a `strategy_proposal_contract` (its Section 3.4) with `proposal_id`,
  `action`, `horizon`, `setup_id`, `confidence_bucket`, and other fields, plus
  a `{ACTION}*{HORIZON}*{SETUP}` strategy id convention. It is explicitly
  research-stage (open design questions, "Recommended Batch 4" section), not
  in `docs/architecture/`, and does not itself claim to be the canonical
  architecture authority. The new `docs/architecture/strategy_proposal_contract_v1.md`
  (Section 3) states explicitly that it is the canonical schema authority
  and that the v215 route document's proposal-contract section should align
  to it going forward. This document was **not edited** — no changes outside
  the paths listed in "Expected changed paths" were made. No duplicate or
  conflicting canonical contract exists: only one document lives under
  `docs/architecture/` for this schema.
- GitHub Issues reviewed via `gh issue list`/`gh issue view` (gh available
  and authenticated): Issue #243 "Define multi-horizon strategy architecture
  contract" is an existing, broader-scope Issue (Breathline/Fibo/Confirmation/
  Strategy-State cross-horizon composition, decision_gate/execution_planner
  data flow) that is adjacent to but not identical to this batch's proposal-
  schema scope; it is not closed by this document and was not modified.
  Issues #227 (account-aware drawdown/cooldown), #203 (manual execution
  ladder unification), #206 (credential scope / manual execution boundary),
  and #254 (multi-account operator intent / ladder-request state) are
  existing owners for `decision_gate`/`execution_planner`/`executor`-side
  work adjacent to proposal consumption; none were modified.

## 4. Canonical contract content

Created `docs/architecture/strategy_proposal_contract_v1.md` (377 lines)
with all sections required by the task: Purpose, Separation of concerns,
Proposal identity, Required proposal fields (plus an explicit "fields owned
elsewhere" table), Canonical action enum, Horizon enum, Setup enum, Strategy
profile and bucket ownership, Proposal lifecycle, Freshness and provenance,
External/LLM proposal producers, Manual ingestion boundary, Reporting
contract, Anti-patterns, and Related documents.

## 5. Schema normalization decisions

- `strategy_id` and `proposal_id` are now explicitly distinct (Section 3):
  `proposal_id` identifies one emitted instance; `strategy_id` identifies the
  stable `{ACTION}_{HORIZON}_{SETUP}` strategy identity. The backlog's
  "canonical internal `strategy_id` / proposal id format" phrasing (which
  treated the two as interchangeable) is not preserved. `trade_cycle_id`
  is also kept distinct from both.
- `strategy_profile_id`, `account_scope_ref`, and `bucket_id` are **not**
  proposal fields. They are decision-gate input-envelope fields (contract
  Section 3a): attached only when a market-only proposal is paired with
  account-aware evaluation context at the `decision_gate` boundary, never
  emitted by the `strategy` layer as part of the proposal object.
  `account_scope_ref` was added (explicit account-agnostic marker option)
  per task instruction, since the source never made account-scope explicit
  beyond the profile/bucket references — it lives at the envelope layer for
  the same reason `strategy_profile_id` and `bucket_id` do.
  `SCHEMA_FIELDS_NORMALIZED` count: `proposal_id` vs `strategy_id` split;
  introduction of the `decision_gate` input envelope as the sole owner of
  `strategy_profile_id`, `account_scope_ref`, and `bucket_id` (all three
  excluded from the proposal object, not merely referenced by it);
  reclassification of `bucket_target_pct`/`bucket_available_pct`/
  `bucket_current_pct` out of the proposal object — 3 normalization
  decisions (the profile/scope/bucket-id exclusion and the three
  account-state-percentage exclusions are treated as one consolidated
  envelope-ownership decision each rather than double-counted).
- `ambiguous_schema_fields=0` — no field could not be classified after
  inspection of `docs/research/synth_v215_advice_route_contract_v1.md` and
  `docs/ops/runtime_chain_ownership_v1.md`.

## 6. Strategy-profile and bucket ownership

Handled in Section 8 and Section 3a of the corrected contract.
**Correction (2026-08-07, follow-up to initial batch commit):** an earlier
version of both the canonical contract and this manifest incorrectly stated
that `strategy_profile_id` and `bucket_id` were "proposal-carried
references." That framing has been corrected. The current, canonical model
is:

- the proposal object is market-only and account-agnostic; it carries no
  profile, account-scope, or bucket reference at all;
- `strategy_profile_id`, `account_scope_ref`, and `bucket_id` exist only in
  the `decision_gate` input envelope, constructed at the `decision_gate`
  boundary when a proposal is submitted for evaluation — never emitted or
  carried by the `strategy` layer as part of the proposal;
- target/configured bucket percentage, observed/current allocation, and
  available allocation remain explicitly assigned to `decision_gate`, never
  to the proposal schema or to `selection_engine`.

`account_state_fields_misowned=0` and `cross_layer_authority_violations=0`
hold under this corrected model (both the contract and this manifest were
checked and now agree); they did not hold under the prior
"proposal-carried" wording, which implied the `strategy` layer was carrying
account-aware reference fields on the proposal object itself.

## 7. Temporary LLM/manual bridge disposition

- LLM/agent bridge: durable boundary (proposal-producer-only, no permission/
  execution/order authority) kept in Section 11; the temporary/tactical
  framing ("Codex or Synth gathers context... Joost remains manual executor")
  moved to the archive as historical context, since it describes a specific
  v2.14-era workflow rather than a permanent architecture rule.
- Manual Excel/dropfolder fallback: durable transport principles (atomic
  intake, completeness marker, incoming/processed/rejected, schema
  validation, idempotency, reject-partial) kept in Section 12; XLSX itself
  demoted to "optional transport representation". The implementation task
  itself (dropfolder ingestion runner) is unowned; preserved as a future
  Issue candidate (Section 10).

## 8. Reporting/UI disposition

Durable principles (human-readable labels with stable internal ids, evidence/
freshness/lifecycle visibility, no hidden final labels, no dashboard-owned
calculation) folded into Section 13 of the new contract. Layout-specific
guidance (asset cards vs. tables, column order, ALGO/WLD worked examples)
remains owned by `docs/todo/manual_ladder_dashboard.md` and was not
duplicated; the new contract explicitly defers to that document for UI
layout.

## 9. Existing Issue and implementation ownership

Deferred Implementation Order (source Section L), item by item:

| # | Item | Disposition |
| --- | --- | --- |
| 1 | Runtime freshness audit and ownership docs | `already_implemented` — `docs/ops/runtime_chain_ownership_v1.md` exists and covers this. |
| 2 | Signal inventory | `existing_owner` — `docs/todo/signal_matrix_dashboard.md`. |
| 3 | Horizon-separated signal matrix | `existing_owner` — `docs/todo/signal_matrix_dashboard.md`. |
| 4 | Asset-card dashboard | `existing_owner` — `docs/todo/manual_ladder_dashboard.md`. |
| 5 | Strategy proposal contract | `already_implemented` by this batch — `docs/architecture/strategy_proposal_contract_v1.md`. |
| 6 | Manual Excel or dropfolder path | `genuinely_unowned` — see future Issue candidate below. |
| 7 | LLM strategy bridge (implementation, not the architecture boundary) | `genuinely_unowned` — see future Issue candidate below. |
| 8 | Outcome logging | `genuinely_unowned` — adjacent to but not identical in scope to Issue #232 ("Validate current strategy candidates against buy-and-hold baselines"); see future Issue candidate below. |
| 9 | Promotion rules for measured strategy logic | `already_implemented` — `AGENTS.md` "Strategy Candidate Rules" already defines required evidence before promotion. |
| 10 | Only later: decision or execution integration, if explicitly approved | `existing_owner` — governed by `AGENTS.md` Live Trading Safety (`NOT_GRANTED` by default); no change needed. |

`EXISTING_ISSUE_OWNERS`: signal-matrix and manual-ladder dashboard TODOs (2,
still `docs/todo/` lanes, not GitHub Issues — both are active/current per
inspection, not stale); adjacent GitHub Issues #243, #227, #203, #206, #254
noted as related but not owning this exact scope; #232 noted as adjacent to
outcome-logging.
`SUPERSEDED_SCOPES`: 1 (runtime freshness audit, item 1) plus item 9
(promotion rules, already covered by `AGENTS.md`) — 2 items resolved as
already-covered by existing canonical material, no new Issue needed.

## 10. Future Issue candidates

No Issues were created or modified. The following are preserved as future
Issue candidates only, for genuinely unowned implementation scope:

### Candidate A — Manual proposal dropfolder ingestion

- Title: "Implement manual strategy-proposal dropfolder ingestion"
- Scope: build the `incoming`/`processed`/`rejected` dropfolder transport
  and schema validator described in `strategy_proposal_contract_v1.md`
  Section 12, accepting proposal batches (any schema-valid transport
  encoding, not necessarily XLSX) against the Section 4 schema.
- Architecture owner: reporting/ingestion boundary feeding the `strategy`
  layer; must not touch `decision_gate`, `execution_planner`, or `executor`.
- Dependencies: `docs/architecture/strategy_proposal_contract_v1.md`
  (this batch).
- Acceptance criteria: atomic intake; completeness marker; schema
  validation against the canonical contract; idempotent re-ingestion;
  partial/malformed payloads rejected, not partially applied; safety
  markers (`broker_writes=0`, `order_submission=0`, `decision_gate=none`,
  `execution_planner=none`, `executor=none`).
- Explicit non-goals: no order creation, no account-aware permission logic,
  no execution intent, no live trading enablement.

### Candidate B — LLM strategy-proposal bridge runner

- Title: "Implement bounded LLM strategy-proposal producer"
- Scope: a runner that assembles an explicit, bounded context bundle from
  active market evidence and emits schema-valid proposals per
  `strategy_proposal_contract_v1.md` Section 4, with an LLM acting only as
  proposal producer per Section 11.
- Architecture owner: `strategy` interpretation layer (upstream of
  `decision_gate`); must not read account state.
- Dependencies: `docs/architecture/strategy_proposal_contract_v1.md`
  (this batch); Candidate A if manual transport is the initial path.
- Acceptance criteria: proposals are schema-valid; `requires_manual_review`
  always true unless a separately validated automated lane exists;
  provenance (`input_signal_refs`, `input_context_run_id`) populated; no
  broker/account calls; `decision_gate`, `execution_planner`, `executor`
  untouched.
- Explicit non-goals: no permission grant, no execution intent, no order
  submission, no automatic promotion to paper/live without separate review.

### Candidate C — Proposal outcome logging

- Title: "Add strategy-proposal outcome logging for later promotion review"
- Scope: record what happened after a proposal expired/was invalidated/was
  accepted or rejected by `decision_gate`, to support the evidence required
  by `AGENTS.md` "Strategy Candidate Rules" before any promotion. Distinct
  from, but complementary to, Issue #232's buy-and-hold baseline validation
  work.
- Architecture owner: research/reporting (read-only outcome capture); must
  not write into operational latest-state tables per `AGENTS.md` DB rules.
- Dependencies: `docs/architecture/strategy_proposal_contract_v1.md`
  (this batch); coordinate with Issue #232 to avoid duplicate validation
  harnesses.
- Acceptance criteria: outcome records are research/backtest-namespaced;
  point-in-time correct; do not backfill operational tables; queryable per
  `strategy_id`/`proposal_id`.
- Explicit non-goals: no automated promotion, no runtime strategy
  activation, no account-aware logic.

`FUTURE_ISSUE_CANDIDATES=3` (documented, not created).

## 11. Archive handling

Created `docs/archive/synth_v214_signal_dashboard_strategy_bridge_backlog_history_v1.md`
containing only genuinely historical material: the v2.14-specific dashboard
complaints (Section A of the source), the originally proposed implementation
order with per-step disposition notes, the unvalidated candidate strategy
list, and a note that the worked ALGO/WLD ladder examples are not duplicated
here because they are already superseded by the live examples in
`docs/todo/manual_ladder_dashboard.md`. The archive states historical-only
status, no active ownership, and points to the canonical contract and to
GitHub Issues for current work, per task requirement. It is not a full
duplicate of the source (`full_source_archives_created=0`); large parts of
the source (Sections B-M, Existing Overlap) are intentionally not repeated
in the archive because they are canonicalized or already owned elsewhere.

## 12. Reference handling

Inbound references to the old source path updated: 0 required updates found
beyond what Batch 3B1 (PR #251) already repaired. Live-reference search
(`rg` over the full worktree, excluding `.git`) found only:

- `docs/development/docs_todo_canonicalization_batch_3b1_v1.md` (2 matches)
  — a dated Batch 3B1 completion report describing a prior bounded reference
  fix; historical provenance, not a live pointer. Retained.
- `docs/development/github_issues_remaining_todo_inventory_v1.md` (5
  matches) — a dated planning/inventory document recording pre-canonicalization
  analysis of this exact file, following the same retention pattern already
  established by Batch 3B1 for this document. Retained.
- The new `docs/architecture/strategy_proposal_contract_v1.md` and
  `docs/archive/..._history_v1.md` themselves, which correctly reference the
  removed path as dated provenance and the archive's own historical scope.

`docs/todo/README.md` was checked and does not list this source file; no
change required. `INBOUND_REFERENCES_UPDATED=0` (none needed beyond prior
batch);`HISTORICAL_OLD_PATH_REFERENCES_RETAINED=7` (2 + 5 above).

## 13. Worktree-policy documentation

Added `## Worktree policy for concurrent agents` to
`docs/development/github_issues_workflow.md`, covering: normal workflow in a
clean/idle/exclusive checkout; isolated worktree use when the shared
checkout is active/concurrent/unstable/contaminated; never switch branches
or commit in a checkout used by another agent/process; stop and relocate if
concurrency appears mid-task; never silently delete/reuse another agent's
branch/worktree; report worktree path/branch/base when used. No separate
worktree-policy document was created.

## 14. Architecture safety

- No changes to `selection_engine`, `decision_gate`, `execution_planner`,
  `executor`, broker integrations, or any runtime/DB/service/timer code.
- The new canonical contract explicitly excludes account-aware reference
  fields (`strategy_profile_id`, `account_scope_ref`, `bucket_id`) and
  account-state fields (`bucket_target_pct`, `bucket_available_pct`,
  `bucket_current_pct`, balance, cash, position, open orders) from the
  proposal object entirely, assigning all of them to the `decision_gate`
  input envelope / `decision_gate` account state (contract Section 3a and
  Section 8), and explicitly forbids broker-write/order-submission fields
  on the proposal object.
- No LLM/agent bypass authority is granted; Section 11 explicitly restates
  the boundary already present in `docs/ops/runtime_chain_ownership_v1.md`.
- No dashboard-ownership violation: Section 13 explicitly keeps freshness
  and calculation ownership outside the renderer.
- Only one document exists under `docs/architecture/` for this schema; the
  pre-existing research-stage `docs/research/synth_v215_advice_route_contract_v1.md`
  is explicitly deferred to it (Section 3) rather than left as a competing
  authority, without editing that file.
- Documentation-only change; no code, test, runtime, database, service, or
  timer files touched.

## 15. Acceptance evidence

```text
source_files=1
canonical_architecture_documents_created=1
source_paths_removed=1
redirect_shells_created=0
full_source_archives_created=0
unclassified_substantive_sections=0
duplicate_canonical_contracts=0
ambiguous_schema_fields=0
account_state_fields_misowned=0
cross_layer_authority_violations=0
active_todo_index_entries_remaining=0
broken_references=0
ambiguous_canonical_references=0
issues_created=0
issues_modified=0
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```

`remaining_blockers=none`; `review_result=PASS`.
