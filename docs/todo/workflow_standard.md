# TODO Workflow Standard

## Purpose

Define how Synth v2 TODOs are created, organized, updated, and closed.

The goal is to avoid TODO drift across chat history, temporary notes, stale research docs, and branch-specific handoffs.

## Canonical location

Active or parked TODOs belong under:

```text
docs/todo/
```

The folder index is:

```text
docs/todo/README.md
```

Canonical design details may remain in source docs under:

```text
docs/research/
docs/status/
docs/architecture/
docs/ops/
```

But active task tracking belongs in `docs/todo/`.

## When to create a TODO file

Create or update a TODO file when a task is:

- active
- parked but likely to resume
- cross-lane
- referenced from chat handoff
- important enough that losing it would break continuity
- blocked by another lane
- a safety or architecture guardrail that must be remembered

Do not create a TODO for one-off work that is already completed in the same turn unless it leaves follow-up work.

## File structure

Use one file per lane or operational category.

Examples:

```text
docs/todo/market_breath.md
docs/todo/fibo_zones.md
docs/todo/ui_webview.md
docs/todo/breath_curve.md
docs/todo/dev_ops_hygiene.md
```

Avoid dumping unrelated work into one giant list.

If a lane grows too large, split it by sub-lane and update `docs/todo/README.md`.

## Required sections

Each TODO file should include:

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

Use only the sections that matter, but every file should at least include `Status`, `Sources`, open tasks, and `Boundary`.

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
- `open`: valid task, not necessarily current focus.
- `parked`: intentionally paused, preserved for later.
- `blocked`: cannot proceed until another task is done.
- `done / parked`: resolved enough; keep only standing hygiene notes.
- `backlog`: low-priority idea or future research lane.
- `future design`: architecture concept allowed later, no implementation now.

## Priority labels

Use simple priority labels:

```text
P0 = current blocker / next required cleanup
P1 = next review / decision
P2 = useful continuation after active lane stabilizes
P3 = future design / later adapter / parked operational work
P4 = backlog
```

Priority is not importance. Priority is execution order.

## Boundary rules

Every TODO file must state its architecture boundary.

Use explicit statements like:

```text
No live trading.
No broker calls.
No broker writes.
No order submission.
No decision_gate bypass.
No execution_planner shortcuts.
No executor/order changes.
No runtime promotion.
```

For research lanes, also state:

```text
research-only
market-only
account-agnostic
```

For UI lanes, state:

```text
read-only display / inspection only
no writes to decision, execution, order, account, balance, or position tables
```

For external narrative lanes, state:

```text
external note -> normalized research label -> validation report -> optional feature candidate after validation
not external note -> buy/sell/order logic
```

## Source references

Each TODO must cite source files or source lanes.

Examples:

```text
docs/research/market_breath_v1_1_calibration_audit.md
src/research/run_market_breath_v1_1_calibration_audit.py
docs/status/synth_v2_5_todo.md
docs/research/fib_exit_ladder_v1_findings.md
```

If the source is only from chat, write:

```text
Source: recent chat handoff, not yet canonicalized elsewhere.
```

Then canonicalize it when practical.

## Updating TODOs

When work changes state:

1. Update the lane TODO file.
2. Update `docs/todo/README.md` if the file list, active priority, or lane status changed.
3. Do not duplicate the same task in multiple files.
4. If a task moves to another file, leave a short pointer or remove the old copy.
5. Commit TODO updates separately from code changes when practical.

## Closing TODOs

When a TODO is completed:

- Move it to a `Done` or `Done / Parked` section.
- Keep only useful historical facts, outputs, commit references, and standing hygiene notes.
- Remove obsolete action bullets.
- If the entire lane is obsolete, move the source design doc to `docs/archive/` only if that doc is no longer canonical.

Do not leave stale `open` tasks that are actually done. Stale TODOs are technical debt with a moustache.

## Branch and commit rules

Preferred commit pattern:

```text
Add <lane> TODO file
Update <lane> TODO status
Mark <lane> TODO parked
Organize TODO workflow standard
```

Do not mix unrelated runtime/code changes with TODO cleanup unless the TODO update documents exactly the same change.

Before committing:

```bash
git status --short
git diff --cached --name-only
```

Do not use broad staging commands such as:

```bash
git add data/
git add .
```

unless the branch is clean and the intent is explicit.

## Active-lane rule

The active lane gets priority in `docs/todo/README.md`.

Current active direction:

```text
Market Breath native market-data analysis.
```

Parked lanes should stay parked unless they directly unblock or support the active lane.

## Review cadence

Review `docs/todo/README.md` when:

- starting a new research lane
- closing a branch
- creating a handoff bundle
- after 2-3 days of heavy chat-driven work
- before merging a branch that introduced TODO changes

## Non-goals

The TODO system is not:

- a project-management platform
- a replacement for canonical research docs
- a place for raw notes
- a place for secrets, credentials, logs, dumps, or generated artifacts

It is a compact working board for memory, sequence, and boundaries.
