# Issue #753 B8 — exact-path PAPER acceptance v1

## Scope

B8 is an acceptance harness, not a new runtime layer. It composes the reviewed
contracts already present after B7.5 and must not introduce parallel trading
semantics.

Canonical chain exercised:

```text
automatic-BUY plan
-> shared PAPER handoff
-> B5.5 post-only placement ACTIVE
-> B7.5 later strict price-through FILLED
-> B5/#752 strategy-owned BUY event
-> B7 authoritative first-fill verification
-> B6 immutable Fib-map binding
-> B2 target/invalidation decision
-> B3 bounded SELL plan + shared PAPER handoff
```

## Acceptance invariants

- No synthetic `FILLED` fixture mutation is used.
- No wallet balance is accepted as SELL authority.
- The bound Fib map is immutable for the life of the trade.
- Exit quantity is bounded by the exact #752-owned lineage quantity.
- Invalidation wins over profit targets.
- Restart/replay preserves deterministic identities.
- Cross-account/bucket lineage is isolated and fails closed.
- Duplicate-cycle replay creates no duplicate placement, ownership event,
  binding, or exit handoff.

## Evidence

`tests/test_issue_753_b8_exact_path_paper_acceptance_v1.py` is the canonical
B8 acceptance test. B8 is PASS only when that test and its adjacent suites are
green on the reviewed PR head.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
live_orders=0
live_authority_changes=0
wallet_balance_sell_authority=0
production_runtime_changes=0
```
