# gurkDB Canonical Runtime Checkout Guard v1

## Purpose

Protect the canonical gurkDB runtime checkout from agent/development branch switches.

The protected checkout is:

```text
host=gurkdb
path=/home/gurk/projects/synth-v2
required_branch=main
```

This checkout is runtime infrastructure. It is not an agent worktree.

## Incident

On 2026-08-22 the canonical checkout was left on
`codex/issue-471-automatic-buy-dry-run`. The existing writer authorization guards
correctly failed closed because the checkout was not on `main`.

That stopped `public_price_snapshot` and `public_candle_freshness`, which made
persisted market data stale. The Odroid linked-profile orchestrator then blocked
on `PUBLIC_PRICE_VALIDATION_BLOCKED`, preventing normal Profit Plan refreshes.

The writers recovered after restoring the canonical checkout to exact current
`origin/main`.

## Required Invariant

All providers and agents, including Claude Code and Codex, must follow these
rules on gurkDB:

- `/home/gurk/projects/synth-v2` must remain on `main`.
- Never run `git switch <feature-branch>` or `git checkout <feature-branch>` in
  the canonical runtime checkout.
- Never create an issue branch in the canonical runtime checkout.
- Every issue implementation on gurkDB must use a dedicated worktree outside
  `/home/gurk/projects/synth-v2`.
- A normal issue worktree should use an explicit issue-scoped path such as
  `/home/gurk/projects/synth-v2-wt-475`.
- Runtime writer authorization guards remain mandatory. They are the final
  fail-closed runtime defense, not the development-workflow mechanism.

## Agent Preflight

Before agent/development branch work on gurkDB, run the repository guard from
the intended checkout/worktree:

```bash
python -m src.operations.verify_agent_worktree_v1 \
  --worktree-path "$PWD" \
  --requested-branch '<intended-branch>'
```

Expected behavior:

```text
canonical gurkDB checkout + main requested     -> PASS
canonical gurkDB checkout + non-main requested -> FAIL
canonical gurkDB checkout already non-main     -> FAIL
canonical gurkDB checkout detached             -> FAIL
separate gurkDB issue worktree                  -> PASS
other hosts                                     -> PASS
```

A guard failure is not an invitation to bypass the check. Create or move to a
separate worktree instead.

## Correct Issue Workflow on gurkDB

Use the canonical checkout only to establish the reviewed base and to create a
separate worktree while it remains on `main`.

The resulting development path must be separate from the runtime path:

```text
runtime checkout: /home/gurk/projects/synth-v2
issue worktree:   /home/gurk/projects/synth-v2-wt-<issue>
```

The issue worktree may use its dedicated feature branch. The runtime checkout
must remain on `main` throughout.

## Scope and Safety

This guard belongs to development/operations workflow only. It does not change
runtime ownership and must not bypass any runtime authorization guard.

```text
selection_engine=unchanged
decision_gate=unchanged
execution_planner=unchanged
executor=unchanged
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_activation=0
```

## Verification

Focused tests live in:

```text
tests/test_verify_agent_worktree_v1.py
```

Repository implementation:

```text
src/operations/verify_agent_worktree_v1.py
```

The guard is deterministic and path/host/branch based. It does not modify git,
systemd, database state, broker state, or runtime authorization.
