# TODO Workflow Standard

## Purpose

Define how Synth v2 TODOs are created, indexed, prioritized, grouped, updated, and closed without drifting into chat-only state.

## Canonical location

Active or parked TODOs belong under:

```text
docs/todo/
```

The cross-lane index and execution order live in:

```text
docs/todo/README.md
```

Design and evidence may remain under `docs/research/`, `docs/status/`, `docs/architecture/`, or `docs/ops/`, but active tracking must point back to one TODO lane.

## Folder structure

`docs/todo/README.md` remains the sole owner of cross-lane status, priority, and execution order.

Responsibility folders may group TODO files:

```text
execution/
runtime/
market_intelligence/
research_validation/
reporting/
completed/
backlog/
```

Folder `README.md` files are navigation and boundary documents only. They must not define a second priority order or duplicate active task ownership.

Files may remain top-level during staged migration. Every move must update all exact path references in the same reviewed change.

## Lane ownership

Use one TODO file per coherent lane or operational category.

Create or update a TODO when work is:

- active
- parked but expected to resume
- blocked by another lane
- a cross-lane safety or architecture guardrail
- important enough that losing chat history would break continuity

Do not create a new lane when an existing file already owns the task.
Do not retain a TODO for one-off work completed in the same change unless follow-up remains.

## Minimum lane structure

Each lane should contain the sections that materially apply:

```text
# TODO — <Lane Name>
## Status
## Sources
## Current state / facts
## Open tasks by priority
## Blockers / dependencies
## Boundary
## Non-goals
```

## Status labels

Use these labels consistently:

```text
active
open
parked
blocked
done / parked
backlog
future design
```

Meaning:

- `active`: current working lane.
- `open`: valid work, not necessarily current focus.
- `parked`: intentionally paused and preserved.
- `blocked`: cannot proceed until a named dependency is satisfied.
- `done / parked`: implementation is closed; retain only evidence and standing hygiene.
- `backlog`: low-priority future work.
- `future design`: architecture concept only; no implementation authority.

## Priority labels

```text
P0 = current board blocker or required cleanup
P1 = next implementation/review decision
P2 = operational or useful continuation after P1 is controlled
P3 = research, future design, or non-blocking work
P4 = backlog
```

Priority is execution order, not importance.

## Architecture boundaries

Every TODO must name its owner and forbidden shortcuts.

Default safety wording:

```text
No live trading.
No broker writes.
No order submission.
No decision_gate bypass.
No execution_planner bypass.
No executor shortcut.
```

Research lanes also state:

```text
research-only
market-only
account-agnostic
```

UI/reporting lanes also state:

```text
read-only display or untrusted user input only
no direct broker access
no authority derived from HTML/JSON presentation
```

Architecture split:

```text
selection_engine  = market-only candidate ranking
decision_gate     = account-aware permission and conflict resolution
execution_planner = execution intent only
executor / agents = order handling only
```

## Updating status or priority

When work changes state:

1. Update the owning lane TODO.
2. Update `docs/todo/README.md` in the same change when lane status, priority, or execution order changes.
3. Remove or replace duplicate bullets in other files with one pointer to the owner.
4. Preserve exact merged PRs, commits, acceptance evidence, and unresolved risks.
5. Do not convert unverified host state into an accepted fact.

## Closing work

When a task or lane completes:

- move the result to `done / parked`;
- record the decisive PRs and acceptance evidence;
- remove obsolete open action bullets;
- retain only standing hygiene, rollback, or future defect-reopen criteria;
- move obsolete source material to `docs/archive/` only when it is no longer canonical.

A completed implementation must not remain labelled `active` or `open` merely because host activation, product consumption, or later research is still separate. Track each remaining responsibility in its actual owner lane.

## Source references

Each TODO cites its canonical sources or merged PR evidence.
When the source is initially chat-only, state that explicitly and canonicalize it as soon as practical.

## Branch and commit rules

Prefer docs-only TODO reconciliation commits that do not mix runtime or feature changes.
Before publishing, verify:

```bash
git status --short
git diff --check
```

Stage only intended paths. Avoid broad staging when unrelated changes exist.

## Active-lane rule

`docs/todo/README.md` is the sole owner of the current cross-lane priority order.

This workflow standard must not hardcode a particular current research or product lane. That would create a second, stale board.

Parked lanes remain parked unless they directly unblock an indexed higher-priority lane.

## Review cadence

Reconcile the board:

- after a major PR chain closes;
- when a lane changes priority or ownership;
- when new work is accepted from chat;
- before starting another parallel implementation lane.
