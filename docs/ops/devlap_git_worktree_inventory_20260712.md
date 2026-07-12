# Devlap Git worktree inventory — 2026-07-12

## Scope and method

This is a read-first inventory taken after `git fetch --prune origin` from the
canonical checkout. The primary was clean, on `main`, at
`c40c0a5f6e3049822852cb11bb845d558d0cd753`. Each registered worktree was
checked for path existence, HEAD, branch/detached state, porcelain status,
local/origin branch presence, merge/ancestor state relative to `origin/main`,
commits absent from `origin/main`, latest commit date, disk use, lock state,
and active process evidence. The nested Claude worktree was included.

`unmerged` below includes branches with commits not contained by `origin/main`.
The inventory does not regard a missing remote tracking branch as unpushed when
the branch has no commits absent from `origin/main`.

## Summary

- Registered at inventory time: 61.
- `KEEP_ACTIVE`: 4; `KEEP_RELEASE`: 2; `KEEP_DIRTY`: 10;
  `KEEP_REFERENCED`: 5; `KEEP_UNMERGED`: 7; `REVIEW_REQUIRED`: 30.
- `SAFE_REMOVE_STALE_TMP`: 4. No other safe-removal class is allowlisted for
  this maintenance run.
- Estimated recoverable disk space from the four allowlisted candidates: 132M.
- No registered worktree was locked or prunable; no process had a registered
  worktree as its current working directory.

## Protected paths

- `/home/gurk/projects/synth-v2` — canonical primary checkout; must remain on
  `main`.
- `/home/gurk/projects/synth-v2-native-short-health-a3` — PR #79 checkout,
  discovered through GitHub as branch
  `feature/native-short-map-level-status-chain-v1`.
- `/tmp/synth-v2-pr79-post-merge-acceptance` — PR #79 acceptance companion;
  retained under the same ownership protection.
- `/home/gurk/projects/synth-v2/.claude/worktrees/breathline-v2-canonical-campaign-v1`
  — active Breathline v2 canonical campaign.
- `/home/gurk/releases/synth-v2-linked-profile-orchestrator-v1` and
  `/home/gurk/releases/synth-v2-p0a-containment-v1` — release worktrees.
- The five `KEEP_REFERENCED` paths below — named by current canonical
  documentation.

## Explicit cleanup allowlist

Only these candidates may be supplied to the cleanup script during this run:

- `/tmp/synth-v2-breathline-preflight`
- `/tmp/synth-v2-market-signal-snapshot-inventory-v1`
- `/tmp/synth-v2-profit-plan-card-evidence-delta-v1`
- `/tmp/synth-v2-profit-plan-market-breath`

Each was clean, under `/tmp`, had no active process evidence, was not mentioned
by canonical docs/scripts/systemd/deployment procedures, and its branch was
merged into `origin/main` with no commits absent from `origin/main`. Their last
commits were respectively 2026-06-24, 2026-07-04, 2026-07-04, and 2026-06-24;
their sizes were 21M, 44M, 45M, and 22M. The script rechecks every condition
immediately before removal.

## Inventory

Legend: `clean` is porcelain status; `merged` means branch is an ancestor of
`origin/main`; `ancestor` applies to detached HEADs. `review` is intentionally
conservative for clean, merged non-temporary worktrees or recently used
temporary worktrees with no explicit retirement confirmation.

| Classification | Path | HEAD / branch | State / evidence |
| --- | --- | --- | --- |
| KEEP_ACTIVE | `/home/gurk/projects/synth-v2` | `c40c0a5` / `main` | clean; merged; 3.3G; primary |
| KEEP_ACTIVE | `/home/gurk/projects/synth-v2-native-short-health-a3` | `eecbc843` / PR #79 branch | clean; unmerged; 54M; protected |
| KEEP_ACTIVE | `/tmp/synth-v2-pr79-post-merge-acceptance` | `67fce007` / detached | clean; ancestor; 45M; protected PR #79 companion |
| KEEP_ACTIVE | `/home/gurk/projects/synth-v2/.claude/worktrees/breathline-v2-canonical-campaign-v1` | `5b0d1a12` / research branch | dirty (2); 86M; protected campaign |
| KEEP_RELEASE | `/home/gurk/releases/synth-v2-linked-profile-orchestrator-v1` | `cb3ffa79` / detached | clean; ancestor; 44M; release |
| KEEP_RELEASE | `/home/gurk/releases/synth-v2-p0a-containment-v1` | `f56c58ac` / deploy branch | clean; unmerged; 22M; release |
| KEEP_DIRTY | `/home/gurk/projects/synth-v2-aplus-breathline-alignment-v1` | `89edaf04` / research branch | dirty (1); merged; 52M |
| KEEP_DIRTY | `/home/gurk/projects/synth-v2-arm-a-20260702T151610Z` | `36276473` / detached | dirty (1); ancestor; 78M |
| KEEP_DIRTY | `/home/gurk/projects/synth-v2-arm-a-b2a-comparison-run-20260702T224621Z` | `2661030b` / detached | dirty (1); ancestor; 54M |
| KEEP_DIRTY | `/home/gurk/projects/synth-v2-arm-a-b2a-comparison-run-20260702T231357Z` | `2661030b` / detached | dirty (1); ancestor; 54M |
| KEEP_DIRTY | `/home/gurk/projects/synth-v2-b2a-acceptance-20260702T172142Z` | `eafc571c` / detached | dirty (1); ancestor; 64M |
| KEEP_DIRTY | `/home/gurk/projects/synth-v2-b2a-full-20260702T174219Z` | `eafc571c` / detached | dirty (1); ancestor; 643M |
| KEEP_DIRTY | `/home/gurk/projects/synth-v2-breathline-marker-timing-report` | `0bb38423` / research branch | dirty (3); unmerged; 21M |
| KEEP_DIRTY | `/home/gurk/projects/synth-v2-zone-backtest` | `75eafdd4` / research branch | dirty (11); unmerged; 67M |
| KEEP_DIRTY | `/home/gurk/synth-v2-breathline-v1-recovery-smoke` | `039cb158` / detached | dirty (1); ancestor; 22M |
| KEEP_DIRTY | `/tmp/synth-v2-p0a-combined-pr` | `b1cf43a4` / fix branch | dirty (9); unmerged; 44M |
| KEEP_REFERENCED | `/home/gurk/projects/synth-v2-breathline-baseline-replay` | `7daed489` / research branch | dirty (1); merged; 51M; docs research path |
| KEEP_REFERENCED | `/home/gurk/projects/synth-v2-map-lifecycle-audit-core` | `f0dfea4f` / feat branch | clean; merged; 21M; docs research path |
| KEEP_REFERENCED | `/home/gurk/projects/synth-v2-map-rollover` | `dc3fe792` / fix branch | clean; merged; 22M; docs research path |
| KEEP_REFERENCED | `/home/gurk/projects/synth-v2-native-short-map-audit-v1` | `14c85a70` / feature branch | clean; merged; 21M; docs research path |
| KEEP_REFERENCED | `/home/gurk/projects/synth-v2-native-short-map-materializer-v1` | `4956178d` / feature branch | clean; unmerged; 22M; docs research path |
| KEEP_UNMERGED | `/home/gurk/projects/synth-v2-hugo-dashboard` | `ef316c07` / feature branch | clean; unmerged; 24M |
| KEEP_UNMERGED | `/home/gurk/projects/synth-v2-runtime-freshness-docs` | `41794d13` / wip branch | clean; unmerged; 52M |
| KEEP_UNMERGED | `/home/gurk/synth-v2-pr42a` | `a8d3dfcc` / research branch | clean; unmerged; 50M |
| KEEP_UNMERGED | `/tmp/breathline-clean-branch` | `3970de13` / docs branch | clean; unmerged; 21M |
| KEEP_UNMERGED | `/tmp/synth-v2-native-short-map-level-status-chain-v1` | `117d48f5` / detached | clean; not ancestor; 46M |
| KEEP_UNMERGED | `/tmp/synth-v2-profit-plan-breath-curve-live` | `c463c950` / feat branch | clean; unmerged; 27M |
| KEEP_UNMERGED | `/tmp/synth-v2-profit-plan-market-breath-diagnostics` | `1e697b9c` / feat branch | clean; unmerged; 22M |
| SAFE_REMOVE_STALE_TMP | `/tmp/synth-v2-breathline-preflight` | `c25e335e` / research branch | clean; merged; no unique commits; 2026-06-24; 21M |
| SAFE_REMOVE_STALE_TMP | `/tmp/synth-v2-market-signal-snapshot-inventory-v1` | `4eeb651c` / research branch | clean; merged; no unique commits; 2026-07-04; 44M |
| SAFE_REMOVE_STALE_TMP | `/tmp/synth-v2-profit-plan-card-evidence-delta-v1` | `85849cd8` / feature branch | clean; merged; no unique commits; 2026-07-04; 45M |
| SAFE_REMOVE_STALE_TMP | `/tmp/synth-v2-profit-plan-market-breath` | `86ff77f3` / feat branch | clean; merged; no unique commits; 2026-06-24; 22M |
| REVIEW_REQUIRED | all remaining clean registered worktrees not listed above | see `git worktree list --porcelain` inventory | Clean/merged or detached ancestor state alone is insufficient retirement evidence outside the explicit `/tmp` allowlist. |

The `REVIEW_REQUIRED` group consists of: `synth-v2-arm-a-b2a-comparison-v1`,
`synth-v2-b2a-integer-day-phase-null-v1`,
`synth-v2-breathline-lattice-shift-residual-calibration-v2`,
`synth-v2-breathline-marker-evidence-viewer-v1`,
`synth-v2-breathline-todos`, `synth-v2-manual-execution-ladder-profiles-v1`,
`synth-v2-map-outcome-baseline`, `synth-v2-market-observer-evidence-preview-v1`,
`synth-v2-market-observer-inventory`, `synth-v2-market-rotation`,
`synth-v2-native-map-ledger-audit`, `synth-v2-native-map-ledger-canary`,
`synth-v2-native-map-ledger-health-report-v1`,
`synth-v2-native-map-scope-seed-canary`, `synth-v2-native-short-cadence-a1b`,
`synth-v2-native-short-cadence-contract`, `synth-v2-native-short-status-a1`,
`synth-v2-native-short-status-a2`, `synth-v2-native-short-status-contract`,
`synth-v2-p0a-paper-advice-log-containment`, `synth-v2-profit-plan-forensic`,
`synth-v2-replay-preconditions`, `synth-v2-system-facts`,
`synth-v2-breathline-next`,
`/tmp/synth-v2-btc-native-short-canary`, `/tmp/synth-v2-main-merge-inventory`,
`/tmp/synth-v2-native-short-doc`, `/tmp/synth-v2-native-short-evidence-doc`,
`/tmp/synth-v2-native-short-health-smoke-a3`, and `/tmp/synth-v2-pr54-clean`.

## Operation, non-goals, and rollback

Dry-run and apply use only the recorded allowlist, for example:

```bash
scripts/dev/cleanup_git_worktrees_v1.sh --allow /tmp/synth-v2-breathline-preflight --allow /tmp/synth-v2-market-signal-snapshot-inventory-v1 --allow /tmp/synth-v2-profit-plan-card-evidence-delta-v1 --allow /tmp/synth-v2-profit-plan-market-breath
scripts/dev/cleanup_git_worktrees_v1.sh --apply --allow /tmp/synth-v2-breathline-preflight --allow /tmp/synth-v2-market-signal-snapshot-inventory-v1 --allow /tmp/synth-v2-profit-plan-card-evidence-delta-v1 --allow /tmp/synth-v2-profit-plan-market-breath
```

Non-goals: source changes, branch deletion, rebasing, merging, pushing other
work, deployment, broker interaction, and any mutation of PR #79 or Breathline
v2 work. `git worktree remove` removes the working directory, not its branch.
Rollback is limited: a removed clean worktree can be recreated from its retained
branch or commit, but untracked/dirty content is not recoverable; therefore the
script rejects dirty or changed-state paths and never uses `--force` or `rm -rf`.
