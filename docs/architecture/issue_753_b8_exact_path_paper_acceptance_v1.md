# Issue #753 B8 — exact-path PAPER acceptance v1

## Scope

B8 is an acceptance harness, not a runtime layer. It composes reviewed
candidate/gate/planner, PAPER executor, #752 ownership, immutable Fib binding,
map-bound exit decision, and SELL handoff/reconciliation contracts.

No production trading semantics are added by B8.

## Canonical chain

```text
market-only setup
-> automatic BUY candidate
-> decision_gate
-> BUY planner
-> shared PAPER handoff
-> post-only ACTIVE placement
-> later strict price-through FILLED
-> #752 strategy-owned BUY event
-> authoritative first-fill verification
-> immutable Fib-map binding
-> target/invalidation decision
-> bounded SELL planner + PAPER handoff
-> later strict price-through SELL fill
-> #752 strategy-owned SELL event
```

## Exact issue acceptance matrix

Canonical evidence is
`tests/test_issue_753_b8_exact_path_paper_acceptance_v1.py`.

| # | Issue requirement | Acceptance assertion |
|---|---|---|
| 1 | valid map -> BUY candidate -> gate -> BUY plan -> simulated fill -> immutable map binding | Builds a real candidate from `AutomaticBuySetupContextV1`, obtains an APPROVED gate decision, builds the real BUY plan, rests all PAPER legs ACTIVE, later fills them only on strict price-through, persists #752 BUY events, verifies the authoritative earliest BUY, and persists the immutable B6 binding. |
| 2 | target 1 partial SELL | B2 emits target index 0; B3 builds a bounded SELL plan; the SELL is actually placed ACTIVE, later reconciled FILLED, and persisted as a #752 SELL event reducing the exact owned lineage. |
| 3 | multiple targets deterministic order | After target 1 is consumed, B2 with progression `{0}` selects target index 1 and the frozen second target price. |
| 4 | invalidation before any target | Invalidation price produces `PROTECTIVE_EXIT` for the full owned quantity before any target progression. |
| 5 | target partial fill then invalidation exits remainder | After the real target-1 SELL fill reduces #752 ownership, invalidation plans and PAPER-fills exactly the remainder; projected owned quantity becomes zero. |
| 6 | new canonical map while old-map trade remains open | A rolled map with new map/cycle/hash/targets cannot rebind the existing lineage; B6 raises a conflict and the original binding remains unchanged. |
| 7 | restart/replay preserves binding and remaining quantity | Fresh repository objects over the same persisted stores reload the exact binding and #752 projected quantity; after target+invalidation the terminal remaining quantity remains zero, and the target handoff identity replays identically. |
| 8 | stale/missing/conflicting bound-map evidence fails closed | B2 with missing binding returns typed `FAIL_CLOSED`; B7 rejects stale map evidence; B6 rejects conflicting rebind evidence. |
| 9 | two strategy buckets owning same asset do not cross-sell | A second same-account/same-market bucket owns independent quantity; evaluating that position against this Fib binding fails with ownership mismatch and its quantity remains untouched. |
| 10 | duplicate runtime cycles cannot duplicate exit plans/orders | Replaying target and protective decisions returns the same deterministic handoff rows; resolved PAPER SELL submission replay creates no second placement/order or #752 fill event. |

## Invariants

- No direct fixture mutation to `FILLED`.
- No broker wallet balance is accepted as strategy SELL authority.
- B7/B6 binding is immutable for the trade lifetime.
- B2 quantity is always bounded by #752-owned lineage quantity.
- B3 may only round down from the decision quantity.
- PAPER placement history remains immutable.
- Temporary evidence failures never become lifecycle state.
- No LIVE authority, credentials, or broker/private API are activated.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
live_orders=0
live_authority_changes=0
wallet_balance_sell_authority=0
production_runtime_changes=0
#707_policy_promotion=0
```
