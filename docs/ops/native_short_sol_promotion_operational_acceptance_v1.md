# Native SHORT SOL PROMOTE_SCOPE operational acceptance

## Status

PASS — reviewed acceptance of the already-persisted, real production
`PROMOTE_SCOPE` operation for the SOL scope, executed under the explicit
SOL bootstrap-promotion approval
(`docs/ops/native_short_sol_bootstrap_promotion_approval_v1.md`).

This record closes `PROMOTION_CONTRACT_MISSING` only, via
`native_short_promotion_acceptance_manifest_v1.json`. It is the
`reviewed_acceptance_reference` that manifest's `accepted: true` state
represents, per the "Required later controlled operational acceptance
procedure" in
`docs/todo/native_short_multi_asset_rollout_contract_v1.md` (steps 7-10).
This record is written retrospectively against already-committed database
state; it did not itself perform, request, or wrap any database mutation,
migration, service/timer change, or broker/account action.

## Boundary

Accepted scope:

    bitvavo / SOL / EUR / SHORT / 4h / 1h

BTC and SOL are the only SUPPORTED canonical scopes as of this review. ETH,
XRP, and every other market remain review-only unless separately approved.
The review used public market data and Native SHORT market-data ledgers
only. No `selection_engine`, `decision_gate`, `execution_planner`,
`executor`, account, wallet, private broker, order, or Profit Plan path was
read or mutated to produce this record.

## Reviewed operation-ledger row

    scope_admin_operation_id=1
    operation_uuid=7ef9c93a-4418-458f-939e-7c3caf00705f
    operation_type=PROMOTE_SCOPE
    venue=bitvavo symbol=SOL quote_currency=EUR fib_trading_horizon=SHORT primary_interval=4h supporting_interval=1h
    actor_type=HUMAN_OPERATOR actor_id=joost
    trigger_type=MANUAL_CLI
    request_source=manual-cli-gurkdb
    reason="SOL bootstrap-promotion canary per docs/ops/native_short_sol_bootstrap_promotion_approval_v1.md, PR #178"
    requested_at_utc=2026-08-01T17:30:15.188005Z
    repository_sha=00307b5fb34f06498a945bf1408b18c8cae92260
    schema_version=native_short_scope_administration_v1
    metadata_digest=8f0168b57ed8905154f8157643f5cddfd3e51fa41de85c6d096432801c401a5a
    started_at_utc=2026-08-01T17:30:15.418146Z
    completed_at_utc=2026-08-01T17:30:15.418146Z
    result_class=SUCCESS
    result_code=PROMOTED_NEW_SCOPE
    support_generation_before=NULL
    support_generation_after=1

`repository_sha` (`00307b5f...`) is the merge commit of PR #178
(`fix/native-short-production-promotion-bootstrap-v1`), which introduced and
is the exact reviewed implementation this SOL bootstrap approval trusts —
consistent with `approved_implementation_commit` in the bootstrap manifest
and approval record. Reconstructing this exact row via
`NativeShortScopeAdministrationRequest`/`NativeShortScopeAdministrationProvenance`
with `canonical_metadata={}` recomputes `request_digest` to exactly the
persisted `metadata_digest` above (verified read-only; no duplicated hashing
logic).

## Post-promotion ledger state (read-only, verified)

    native_short_map_scope_v1: scope_id=2, SOL, SUPPORTED, support_generation=1
    native_short_scope_support_event_v1: scope_support_event_id=2, SUPPORTED,
      scope_admin_operation_id=1, support_generation=1,
      reason_code=ADMIN_PROMOTED_NEW_SCOPE
    native_short_scope_cadence_config_v1: cadence_config_id=2, is_active=1,
      activation_operation_id=1, deactivation_operation_id=NULL,
      support_generation=1
    native_short_map_v1: exactly one SOL map (map_id=15), published by the
      canonical 4h-chain writer after promotion, structure_hash/target_levels
      consistent with the existing native SHORT map contract

Exactly one scope row, one support event, and one active cadence row exist
for SOL, all bound to `scope_admin_operation_id=1`. No duplicate, ambiguous,
or cross-scope-attributed row was found. This matches the "Promotion
acceptance contract" checklist in
`docs/todo/native_short_multi_asset_rollout_contract_v1.md`: exact canonical
identity, attributable provenance, all-or-nothing single-scope transaction,
and no ambiguous scope/support/cadence state.

## Transitional audit (read-only, this review)

A read-only `native_short_multi_asset_audit_v1` run against current
production state, evaluated at a timestamp aligned with the last ingested
4h/1h closes (to avoid a boundary-lag artifact), confirmed:

    provenance_audit_run_attributed=true
    writer_provenance_blocker_active=false
    promotion_acceptance_accepted=false  (pre-existing manifest was still unpopulated at audit time)
    promotion_acceptance_evaluation_reason=MANIFEST_NOT_ACCEPTED

This confirms the gap this record closes: the real production promotion
succeeded, but the post-hoc acceptance manifest had not yet been populated,
so `PROMOTION_CONTRACT_MISSING` remained active until this record and the
manifest update that names it.

The same audit run also revealed and this lane's implementation fixed a
separate, unrelated defect: `native_short_multi_asset_audit_v1` hardcoded a
single `EXISTING_CANARY_SYMBOL = "BTC"` constant, causing SOL's post-
promotion `SUPPORTED` scope to misclassify as `SCOPE_CONFLICT` in the audit
report. That defect is corrected in the same change that adds this record
(see `native_short_multi_asset_audit_v1.py`); it did not affect the
administration-transaction gate itself, only the read-only audit's display.

## Safety markers

    broker_private_calls=0
    broker_writes=0
    order_submission=0
    live_orders=0
    account_reads=0
    decision_gate=none
    execution_planner=none
    executor=none
    database_writes_by_this_record=0
    service_changes=0
    timer_changes=0
    new_scope_seeds=0

## Review state

This record and the accompanying `native_short_promotion_acceptance_manifest_v1.json`
update close `PROMOTION_CONTRACT_MISSING`. `REMOVAL_CONTRACT_MISSING`
remains fully, unconditionally active (unaffected by this record).
`BOOTSTRAP_ORCHESTRATION_BLOCKED` and `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`
remain unconditionally active in the canonical audit evaluator and are only
narrowed, per exact reviewed scope, by the bootstrap-evidence manifest —
this record does not touch that mechanism or approve any additional scope.
