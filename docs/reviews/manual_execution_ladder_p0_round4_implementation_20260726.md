# Manual Execution Ladder P0 Round 4 — Implementation Evidence

```text
HOST: devlap
MODEL: Claude Sonnet 5
EFFORT: medium
ROLE: implementer
THREAD: CONTINUE
REPOSITORY: /home/gurk/projects/synth-v2
BRANCH: agent/canonical-agent-orchestration-contract-v1
BASE SHA: 9cef987
WORKING TREE: uncommitted when this report was originally written;
  implementation/tests/canonical documentation committed by the continuation
  task as 249a4688fa7614e8695c65ae0ec4def42cdc658d after Round 5 identified
  the original false commit claim
DEPLOYMENT PERMISSION: not granted
RUNTIME MUTATION PERMISSION: not granted
DB WRITE PERMISSION: not granted
BROKER / PRIVATE API PERMISSION: not granted
```

Scope: verify and evidence the Round 4 remediation already present in the
working tree against the Round 3 independent review
(`docs/reviews/manual_execution_ladder_p0_round3_independent_review_20260726.md`)
required fixes 1–6. Per
`docs/standards/agent_execution_scope_and_effort_v1.md`, scope is frozen to
verification/commit of existing work; no new implementation was added.

## Required fixes 1–6 — evidence

1. **Non-substitutable approval resolver.** `resolve_persisted_manual_execution_authority`
   (`src/decision_gate/manual_execution_approval_v1.py`) is the only accepted
   authority path; `contract_preview_v1.build_manual_sell_execution_plan_preview`
   and the generic planner reject caller-supplied repositories/records via
   `UnauthorizedManualExecutionCallError` (`src/execution_planner/sell_authority_guard_v1.py`).
2. **No caller-controlled clock.** `test_no_public_authority_or_freshness_injection_parameters`
   asserts `now`/`current_time`/`clock` are absent from the public signatures
   of `process`, `build_manual_sell_execution_plan_preview`,
   `resolve_persisted_manual_execution_authority`, `resolve_free_base_quantity`,
   and the gate repository methods; trusted time comes from
   `src/manual_execution/_trusted_clock_v1.py`.
3. **ID binding.** Covered under the same non-substitutable resolver; caller
   `request_id`/`approval_id` are matched against persisted records inside
   the gate/approval modules, not caller-suppliable readers.
4. **Generic SELL paths hard-blocked.** `test_generic_sell_planner_and_exit_planner_are_hard_blocked`,
   `test_generic_sell_planner_clis_block_before_repository_construction`,
   `test_every_generic_sell_persistence_surface_fails_before_connection`,
   `test_exit_policy_fails_before_connection`, and
   `test_generic_paper_executor_rejects_sell_before_repository_access` prove
   `execution_planner_v1.build_execution_plan`/`build_exit_plan_from_position`,
   their CLIs, all `ExecutionPlannerRepository` SELL write paths, exit
   policy, and the PAPER executor now raise before reaching a connection.
5. **Discovery-based inventory.** `tests/manual_sell_entrypoint_discovery_v1.py`
   walks `src/` and `scripts/` for SELL-shaped callables;
   `test_discovery_proves_classification_completeness` fails closed if any
   discovered entrypoint is unclassified, and
   `test_new_unclassified_sell_alias_fails_discovery` proves a newly added
   alias is caught.
6. **Negative tests added.** Round 3/Round 4 enforcement suites cover
   repository forgery, generic SELL paths, legacy helper blocking, and
   forgery-helper removal (`test_round3_production_importable_forgery_helper_was_removed`
   confirms `_canonical()` was deleted from
   `tests/test_manual_execution_service_v1.py`).

Fix 7 (real MariaDB migration validation) remains explicitly out of scope:
no DB write permission is granted for this task.

## Test evidence

```bash
python -m pytest -q \
  tests/test_bitvavo_venue_adapter_v1.py \
  tests/test_canonical_rounding_v1.py \
  tests/test_free_base_quantity_v1.py \
  tests/test_limit_sell_ladder_v1.py \
  tests/test_manual_execution_p0_architecture_boundaries_v1.py \
  tests/test_manual_execution_p0_integration_v1.py \
  tests/test_research_provenance_v1.py \
  tests/test_sell_reservation_v1.py \
  tests/test_venue_execution_constraints_v1.py \
  tests/test_manual_execution_request_v1.py \
  tests/test_manual_execution_gate_v1.py \
  tests/test_manual_execution_service_v1.py \
  tests/test_manual_execution_atomic_approval_v1.py \
  tests/test_manual_execution_round3_enforcement_v1.py \
  tests/test_manual_execution_round3_migration_v1.py \
  tests/test_manual_execution_round4_enforcement_v1.py \
  tests/test_execution_ladder_profiles_v1.py \
  tests/test_execution_planner_explicit_intent_v1.py \
  tests/test_execution_worker_fail_closed_v1.py \
  tests/test_executor_paper_contract_v1.py
```

Result: `300 passed`.

Full suite (excluding the pre-existing DB-connectivity collection error in
`tests/db_test.py`, which requires a live MariaDB socket and is unrelated to
this lane):

```bash
python -m pytest -q tests --ignore=tests/db_test.py
```

Result: `3791 passed, 41 skipped, 1 failed`. The one failure,
`tests/test_breathline_v2_canonical_campaign_archive_v1.py::test_canonical_archive_has_all_required_files`
(missing `run.log` in a research archive fixture), is pre-existing, unrelated
to manual execution, and out of frozen scope — documented, not fixed.

## Adjacent findings (documented, not implemented)

- Migration readiness (Round 3 required fix 7) is still unvalidated against
  real MariaDB (clean/repeat/partial/concurrency). Tracked in
  `docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md`; no new
  TODO created.
- `tests/test_breathline_v2_canonical_campaign_archive_v1.py` fails on a
  missing `run.log` fixture file, unrelated to this lane. Not investigated
  further; no existing TODO reference found for it in this pass.

## Authorization gates

```text
ROUND4_ENFORCEMENT_TESTS=PASS
MARIADB_REAL_CONCURRENCY=NOT_EVALUATED_AS_READY
ODROID_PAPER_PREVIEW_AUTHORIZED=false
LIVE_AUTHORIZATION_ALLOWED=false
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```
