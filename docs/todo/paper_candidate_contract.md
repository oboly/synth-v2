# TODO — Paper Candidate Contract

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- P3 Future decision_gate adapter design -> superseded, no Issue required. `docs/architecture/strategy_proposal_contract_v1.md` (PR #257, canonical/merged) already defines the proposal -> decision_gate input envelope this file was designing toward.

Unmigrated executable scope:
- none

## Status

Future adapter design allowed. No execution wiring.

## Source

```text
docs/research/paper_candidate_contract_v1.md
```

## Current contract path

```text
research preview
-> paper_candidate_contract
-> future decision_gate adapter
```

Not:

```text
research preview
-> execution
```

## P3 — Future decision_gate adapter design

Status: open / future design.

Task:

- Design a future adapter that reads contract-valid research candidates and presents them to `decision_gate`.

Rules:

- No shortcut from research preview to execution.
- No account, portfolio, wallet, balance, position, order, execution plan, broker, or fill fields in research candidate transport.
- `decision_gate` may receive account-aware context later; research must not derive it.

## Boundary

```text
Research can produce a market candidate.
Research cannot produce a buy order.
Research cannot allocate capital.
Research cannot open a position.
```
