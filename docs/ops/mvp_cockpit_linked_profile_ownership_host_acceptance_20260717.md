# Host Acceptance — Linked-Profile Ownership & MVP Cockpit Decoupling (2026-07-17)

Host: `odroid` · checkout `/home/theone/projects/synth-v2` · agent=claude-code

This document records operational acceptance of the safe Profit Plan render
owner rollout (PR #113) and the MVP cockpit ownership decoupling (PR #117) on
the Odroid. Multi-cycle P2-C acceptance across several consecutive scheduled
cycles remains **OPEN** and is not claimed here.

## Repository state

```text
origin/main at rollout start   = 587262e00aecb8a34b5db365ef86ffd7d6faeb17 (PR #113 merge)
PR #113 merge contained         = yes
PR #115 (native SHORT PR A)     = contained
PR #112 (freshness classifier)  = contained
host pre-deploy HEAD            = 587262e (already at target; ff pull was a no-op)
```

## Pre-rollout ownership (2026-07-17 audit)

Duplicate owners were active simultaneously:

- system `synth-linked-profile-runtime-refresh.timer` (safe orchestrator, incl. Profit Plan stage);
- user `synth-account-wallet-dashboard@{joost,hugo}.timer` (legacy wallet + old Profit Plan writer + native SHORT build in render);
- user `synth-account-wallet-refresh@{joost,hugo}.timer` (duplicate account refresh);
- user `synth-mvp-readonly-cockpit.timer` → `run_linked_profile_dashboard_refresh_once.sh` (third duplicate Profit Plan/wallet writer + union native SHORT build).

Observed symptom: canonical `profit-plan.{html,json}` were written by multiple owners each cycle (safe owner then clobbered by legacy writers); a legacy `refresh@joost` run failed with a Bitvavo `403` (rate-limit) seconds after the orchestrator's own successful joost refresh.

## Manual acceptance (all named timers stopped)

Two full orchestrator cycles + one controlled lock test:

```text
cycle 1: overall_result=ok  account 2/0  render 2/0  profit_plan 2/0
cycle 2: overall_result=ok  account 2/0  render 2/0  profit_plan 2/0
```

Render-owner chaining (previous → current render_id):

```text
joost: cycle1 current 7ff64f82... == cycle2 previous 7ff64f82...  (card_count=53, deltas sum=53, NO_PREVIOUS_SNAPSHOT=0)
hugo:  cycle1 current ac9b0268... == cycle2 previous ac9b0268...  (card_count=48, deltas sum=48, NO_PREVIOUS_SNAPSHOT=0)
native SHORT snapshot validated: nsctx-v1-4414f3802631ff2879b945ff (row_count=1)
```

Lock/non-overlap test (same profile, shared lock): first owner `result=ok`, second `result=skipped_locked`, canonical output remained valid.

Safety markers observed on every render stage:

```text
broker_private_calls_from_renderer=0  broker_writes=0  order_submission=0
live_orders=0  decision_gate=none  execution_planner=none  executor=none
native_short_context_build_in_render_stage=false
```

Private read-only broker calls occurred only in the account-refresh stage (`broker_private_calls=2` per profile, `broker_writes=0`).

## Legacy timer retirement

Disabled and stopped individually (unit files preserved):

```text
synth-account-wallet-dashboard@joost.timer  -> disabled/inactive
synth-account-wallet-dashboard@hugo.timer   -> disabled/inactive
synth-account-wallet-refresh@joost.timer    -> disabled/inactive
synth-account-wallet-refresh@hugo.timer     -> disabled/inactive
```

Per-family rollback (independent): `systemctl --user enable --now <family>.timer`.

## MVP cockpit decoupling (PR #117)

`run_mvp_dashboard_render_once.sh` no longer invokes
`run_linked_profile_dashboard_refresh_once.sh`. The cockpit render now produces
only entry-candidate dashboard + about page. Verified on host: a real cockpit
render advanced `entry-candidates.html`, `about.html`, `index.html`, while
`profit-plan.{html,json}`, linked-profile wallet/open-orders, and the native
SHORT union snapshot were **unchanged** (identical sha256 + mtime before/after).

`run_linked_profile_dashboard_refresh_once.sh` is retained as manual/acceptance
-only; its only executable caller is `run_odroid_deployment_acceptance_v1.sh`;
no systemd unit owns it. Cockpit timer re-enabled at its prior cadence
(`OnBootSec=2min`, `OnUnitActiveSec=5min`).

## Final single-ownership (post rollout)

```text
Profit Plan writer            = 1  (synth-linked-profile-runtime-refresh.timer)
linked-profile wallet render  = 1  (synth-linked-profile-runtime-refresh.timer)
joost/hugo account refresh    = 1  (synth-linked-profile-runtime-refresh.timer)
native SHORT snapshot publish = 1  (synth-4h-market-chain.timer)
```

## Guards added (PR: test/mvp-cockpit-ownership-acceptance-v1)

- `tests/test_entry_candidate_dashboard_privacy_boundary_v1.py` — entry-candidates market-only (import closure, args, tables, safety markers);
- `tests/test_run_mvp_readonly_pipeline_once_sh.py` — MVP pipeline stages/order, exit propagation, no direct/indirect linked-profile ownership;
- `tests/test_linked_profile_refresh_caller_ownership_v1.py` — only manual/acceptance caller allowed; fails if a scheduled/runtime or unit caller is added;
- `tests/test_run_mvp_dashboard_render_once_sh.py` — cockpit renders market surfaces, never touches linked-profile/Profit Plan/native SHORT (from PR #117; made environment-robust here).

## Open items

- **P2-C multi-cycle acceptance:** OPEN — observe several consecutive scheduled
  `synth-linked-profile-runtime-refresh.timer` cycles with no overlap, stable
  freshness, and bounded disk/log growth. Not claimed from the two manual runs.
