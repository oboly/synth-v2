# Stale 1h advice freshness truth v1

> **Migration pointer.** Current execution status, priority, blockers,
> acceptance criteria, and closure for this lane are owned by GitHub Issue
> [#221 — Fix stale 1h advice freshness truth for named assets](https://github.com/oboly/synth-v2/issues/221).
> This file is retained as frozen historical/design context; the status and
> observation text below is preserved but superseded operationally by Issue
> #221. Do not update status, priority, blockers, next action, or execution
> order here. See `docs/development/github_issues_workflow.md`,
> `docs/todo/MIGRATION_FREEZE.md`, and
> `docs/development/github_issues_batch_2a_migration_v1.md`.

## Status

Candidate improvement only. This document is not an execution queue item.

## Observed behavior

After a successful 1h candle backfill and canonical `scripts/run_chain_1h.sh` run on 2026-08-05, most assets received fresh 1h advice at `2026-08-05T10:00:00Z`, while a subset still surfaced older advice timestamps from 2026-07-17/18 in `selection_engine_v2` output.

Examples observed included IMU, ZORA, IRYS, NOT, RUNE, RED, DEEP, KAIA, INX, SAND, GRT and others.

The current output therefore mixes current and stale 1h advice without making the freshness distinction sufficiently explicit at the selection/reporting boundary.

## Required outcome

Improve 1h advice freshness truth so downstream consumers can distinguish:

- fresh advice produced for the current expected snapshot;
- unavailable advice because current features/signals could not produce a row;
- stale fallback advice retained only for historical/reference purposes.

Stale fallback advice must never appear equivalent to current advice.

## Architectural boundary

- `selection_engine` remains market-only and account-agnostic.
- Freshness classification belongs in the market-data/advice truth path or in an explicit read model consumed by selection.
- Do not silently repair, synthesize, or overwrite missing current advice inside `selection_engine`.
- Do not involve `decision_gate`, `execution_planner`, or executor layers.

## Acceptance direction

A future implementation should provide an explicit freshness/status field and deterministic age rule, preserve source timestamps, fail closed where current advice is required, and add regression coverage for mixed fresh/stale universes.
