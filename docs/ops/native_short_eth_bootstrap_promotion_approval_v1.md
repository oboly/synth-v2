# Native SHORT ETH bootstrap-promotion approval

## Status

APPROVED — explicit, scope-specific human approval for exactly one
next-canary `PROMOTE_SCOPE` bootstrap authorization, following the same
mechanism and the same reviewed dependency order already used for SOL
(`docs/ops/native_short_sol_bootstrap_promotion_approval_v1.md`).

This record closes nothing by itself. It is the `approval_reference` named
by ETH's entry in
`src/market_data/native_short_promotion_bootstrap_manifest_v1.json` and is
the human decision that entry's `accepted: true` state represents. Closing
`BOOTSTRAP_ORCHESTRATION_BLOCKED` and `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`
for the exact ETH scope below (the two blockers this manifest still narrows
-- `PROMOTION_CONTRACT_MISSING` is already closed globally, see
`docs/ops/native_short_sol_promotion_operational_acceptance_v1.md`) is
performed at runtime by
`native_short_scope_administration_transaction_v1.decide_administration`
consuming that entry -- see
`docs/todo/native_short_multi_asset_rollout_contract_v1.md` for the full
mechanism.

## Approval

The operator explicitly approved ETH as the next native SHORT managed
production canary after SOL, for exactly this scope and no other:

```text
venue: bitvavo
symbol: ETH
quote_currency: EUR
fib_trading_horizon: SHORT
primary_interval: 4h
supporting_interval: 1h
```

This approval is limited to this exact scope. It does not approve XRP, SUI,
BTC (BTC is a separate, already-legacy scope handled by
`ADOPT_LEGACY_SCOPE`, not this bootstrap path), or any broader rollout. XRP
is approved separately and independently in
`docs/ops/native_short_xrp_bootstrap_promotion_approval_v1.md`; neither
approval depends on or is weakened by the other, and each is evaluated
against its own independent manifest entry and digest.

## Approval basis

At the time of this approval, a read-only production audit
(`native_short_multi_asset_audit_v1`, evaluated against an as-of timestamp
aligned with the last ingested 4h/1h closes to avoid a boundary-lag
artifact) classified ETH `READY_FOR_SEQUENTIAL_CANARY_REVIEW`: market-ready
(enabled, market-data-enabled, tradeable, sufficient and current 4h/1h
history, available native SHORT context, unambiguous tick rule) and
ledger-ready (no scope row, no map, no lifecycle/generation/status residue
-- a genuine first-ever administration attempt). ETH ranked #1 of 17
qualified candidates by trailing-30-day public 4h EUR quote volume,
consistent with the documented `SOL -> ETH -> XRP` review order.

## Approval-evidence binding

```text
approved_implementation_commit: 15fc4c030ced4ed2b5a8ba3dcbf831320fe541a8
```

That is the exact, already-existing, ordinary historical commit, on
`feature/native-short-multi-scope-rollout-v1`, that generalized the
bootstrap-evidence manifest from one hardcoded scope to a reviewed list of
independently evidenced entries -- referenced here as a plain historical
fact, not a value this entry's own tree must contain about itself (same
non-self-referential model as the existing SOL approval).

Two independent things are verified at every evaluation, neither of them a
same-commit self-reference:

- **approval-evidence digest** -- this entry's own `approval_evidence_digest`
  is a deterministic SHA-256 over `accepted`, the exact ETH scope,
  `approval_reference`, `approved_at_utc`, `approved_implementation_commit`,
  and the current SHA-256 of `native_short_promotion_bootstrap_evidence_v1.py`.
  It is recomputed fresh from those same fields (and a fresh read of that
  file) at every evaluation; any edit to this entry's fields or to the
  evidence module itself, without a matching digest update, fails closed
  (`MANIFEST_DIGEST_MISMATCH`).
- **ancestry, not equality** -- `approved_implementation_commit` must be an
  *ancestor* of the current deployed `HEAD` (`git merge-base
  --is-ancestor`), never required to equal it. Any commit created after
  `15fc4c03...`, on any branch descended from it, satisfies this by
  construction. Deployed-checkout identity itself (clean tree, exact `HEAD`
  known) remains entirely the unmodified job of
  `native_short_repository_source_identity_v1.verify_repository_commit_sha`
  and `src.operations.writer_capability_authorization_v1`, both already
  required before any write.

## Scope of this approval

Approved:

- exactly one `PROMOTE_SCOPE` invocation for the ETH scope above, executed
  through the existing `native_short_scope_administration_transaction_v1`
  owner with `native_short_4h_chain` writer authorization, from any clean
  checkout whose `HEAD` descends from
  `15fc4c030ced4ed2b5a8ba3dcbf831320fe541a8`, processed strictly after SOL
  in the documented sequential rollout order.

Not approved by this record:

- XRP, SUI, or any other symbol;
- a second promotion of ETH after the first succeeds (structurally
  impossible via this same bootstrap path once ETH's scope row exists --
  see `native_short_promotion_bootstrap_evidence_v1.py`);
- `REMOVE_SCOPE` for ETH or any other scope (`REMOVAL_CONTRACT_MISSING`
  remains fully, unconditionally active for `REMOVE_SCOPE` and unaffected
  by this record);
- map materialization, snapshot publication, Profit Plan rendering, or any
  wallet/account-aware action;
- any change to `run_chain_4h.sh`, systemd units, timers, or the 4h chain's
  scheduling.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
new_scope_seeds=0
```

No database write, map materialization, snapshot publication, or Profit
Plan render occurred as part of recording this approval.
