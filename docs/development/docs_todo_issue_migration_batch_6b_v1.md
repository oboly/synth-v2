# docs/TODO cleanup Batch 6B — Issue migration for the two highest-risk unowned lanes

## 1. Status

```text
COMPLETE
```

Both `docs/todo/profit_plan_live_ladder.md` and `docs/todo/fibo_zones.md` now
carry `unmigrated_executable_scope=0` migration blocks. Every substantive
open section resolved to either an existing GitHub Issue, a new bounded
GitHub Issue, an already-implemented/superseded finding, or an
explicitly-non-actionable design note (no promotion scope present).

## 2. Source classification

### `docs/todo/profit_plan_live_ladder.md`

| Section/scope | Classification | Existing owner | New owner | Result |
| --- | --- | --- | --- | --- |
| P0.0 canonical read-model prerequisites (scope-status, map-level status, market/wallet/position/order observations) | partially implemented (PR #113 merged) | none | #267 | migrated |
| P0.1 stable map/row identity (deterministic, non-UUID) | genuinely open (verified `row_id=str(uuid.uuid4())` in `src/reporting/manual_short_trader_profit_plan_v1.py`) | none | #267 | migrated |
| P0.2 freshness and account authority (7 absolute observation classes) | partially implemented (current-price and order-snapshot freshness exist; full class set does not) | none | #267 | migrated |
| P0.3 inspect canonical write infrastructure — route/session/CSRF | genuinely open | none | #267 | migrated |
| P0.3 inspect canonical write infrastructure — decision_gate/execution_planner/executor/broker semantics | genuinely open | none | #268 (gate), #269 (planner) | migrated |
| P0.4 neutral ladder-repair request/plan contract | genuinely open | none | #269 | migrated |
| P0.5 server preview with explicit sizing | genuinely open | none | #269 | migrated |
| P0.6 decision gate and dry-run plan | genuinely open | none | #268 | migrated |
| P0.7 immutable confirmation | genuinely open | none | #269 | migrated |
| P0.8 one-account live canary | genuinely open | none | #206 (existing, reused) | migrated |
| Account/credential boundaries | genuinely open | #206 | #206 (existing, reused) | migrated |
| Multi-cycle host acceptance of the merged renderer (PR #113) | genuinely open, distinct lane | #201 | #201 (existing, reused) | migrated |
| Later non-blocking work (scanner filtering, visual polish, wallet styling, mobile review, 5m Trade Path) | historical-only / not currently blocking | none | none | not migrated — explicitly non-blocking per the source text; no Issue filed |

The "Later non-blocking work" line item is text that self-declares it does
not block the safe preview/canary and is not itself an executable task with
defined scope; it is not counted against `unmigrated_executable_scope`
because the source file explicitly defers it without describing bounded
work.

### `docs/todo/fibo_zones.md`

| Section/scope | Classification | Existing owner | New owner | Result |
| --- | --- | --- | --- | --- |
| P0 production publication/cutover (4h Fib map writer, MariaDB publication, Odroid cockpit render, `/synth/fibo-map.html`) | already implemented / superseded (merged PRs #171, #173; live at `https://synth.aismid.nl/synth/fibo-map.html`) | none | #249 (existing, reused) | migrated |
| P2 — Exit-profile research continuation | genuinely open | none | #270 | migrated |
| P2 — Zone context guardrails | already canonical (duplicates `AGENTS.md` operational-table contamination rule) | AGENTS.md | none | migrated (no Issue needed) |
| P2 — Leak-free Zone/Fib touch evaluation | genuinely open | none | #270 | migrated |
| P2 — Native map level calibration / signed price bias | genuinely open | none | #270 | migrated |
| P3 — Fibo/zone UI overlays | genuinely open | none | #271 | migrated |
| P3 — Target-box normalization backlog | genuinely open | none | #271 | migrated |
| Strategy-promotion design note (research -> asset_exit_profile -> decision_gate -> execution_planner -> executor) | ambiguous / no validated promotion scope present | none | none | not migrated — explicitly non-actionable per Batch 6B instructions ("do not make a runtime selection Issue unless the source explicitly contains validated promotion scope"); future review only |
| Non-goals section | historical/policy only | none | none | not applicable |

The strategy-promotion design note and the "Later non-blocking work" note
above are the only two sections not mapped to an Issue; both are explicitly
non-executable narrative rather than open scope, so both source files still
report `unmigrated_executable_scope=0`.

## 3. Existing Issue overlap

| Issue | Area | Overlap found |
| --- | --- | --- |
| #202 | manual execution request snapshot/idempotency | partial — shared execution_planner primitives (allocation/rounding), not the cancel/create dependency contract itself; recorded as dependency of #269 |
| #203 | manual execution ladder construction/leg validation | partial — `EXIT_LADDER` construction path is a different request domain than the ladder-repair cancel/create pairs; recorded as dependency of #269 |
| #206 | credential scope / manual execution runtime boundary | full — already covers dry-run/paper/live mode definition, decision-gate-before-executor-intake, single-writer protection, immutable handoff identity; reused for P0.8/A4/A5 |
| #227 | account-aware drawdown/loss/cooldown protection contract | partial — general protection contract, not ladder-repair-specific eligibility (ownership, freshness, duplicates, caps, expiry); recorded as dependency of #268 |
| #254 | multi-account operator intent/ladder-request state | no overlap — different feature (operator intent marking), not the ladder-repair mutation flow |
| #218 | machine-readable backtest capability contract | no overlap |
| #219 | research-layer import removal from native SHORT market-data context | no overlap |
| #231 | regime research Phase 1 | no overlap — different research subject (rotation regimes, not fib/zone touch evaluation) |
| #239 | read-only bullrun-start dashboard module | no overlap — different indicator set |
| #240 | cockpit and wallet UI cleanup | no overlap |
| #241 | Elliott Wave daily-context labeler Phase 1 | no overlap |
| #242 | market-state classes and golden regression fixtures | no overlap |
| #243 | multi-horizon strategy architecture contract | no overlap |
| #249 | Fibo Map dashboard only renders A-C symbols | full — confirms production Fib map dashboard is live; reused as the current owner of production-cutover follow-up scope |
| #201 | linked-profile freshness and multi-cycle runtime acceptance | full — already owns multi-cycle host acceptance of the same renderer family; reused, not duplicated |

Keyword searches also run (no additional overlap found): `ladder`, `fibo`,
`fib zone`, `exit ladder`, `cancel`, `replace order`, `map calibration`,
`target box`, `zone overlay`.

## 4. New Issues created

| Issue | Title | Source | Architecture owner | Scope |
| --- | --- | --- | --- | --- |
| #267 | Add deterministic row identity and freshness model to Profit Plan ladder-repair read model | `profit_plan_live_ladder.md` (P0.0-P0.2, part of P0.3) | reporting | Deterministic non-UUID row identity, full 7-class freshness authority model, route/session/CSRF documentation |
| #268 | Design decision_gate approval contract for Profit Plan ladder-repair requests | `profit_plan_live_ladder.md` (P0.6, part of P0.3) | decision_gate | APPROVED/REJECTED/REVIEW_REQUIRED evaluator: ownership, permission, freshness, funds/position, duplicates, caps, expiry |
| #269 | Define execution_planner cancel/create dependency contract for Profit Plan ladder repair | `profit_plan_live_ladder.md` (P0.4, P0.5, P0.7, part of P0.3) | execution_planner | Neutral request/plan module, server preview, immutable ordered CANCEL_LIMIT->CREATE_LIMIT plan |
| #270 | Validate Fibo/zone exit-profile, leak-free touch, and native map calibration research | `fibo_zones.md` (3 P2 sections) | research | Exit-profile bucket re-validation, leak-free touch evaluator, signed level-error replay/calibration |
| #271 | Add Fibo/zone UI overlays and external target-box display normalization | `fibo_zones.md` (2 P3 sections) | reporting | Zone/fib marker overlays with explicit source, external target-box research-label display |

## 5. Existing Issues reused

| Issue | Source section | Ownership |
| --- | --- | --- |
| #206 | `profit_plan_live_ladder.md` P0.8 live canary, account/credential boundaries | full — already covers dry-run/paper/live mode, decision-gate-before-executor-intake, immutable handoff identity |
| #201 | `profit_plan_live_ladder.md` multi-cycle host acceptance of merged renderer | full — already owns host-ownership/freshness/multi-cycle acceptance for this renderer family |
| #249 | `fibo_zones.md` P0 production publication/cutover | full — production dashboard is live; #249 owns the current open defect on that live surface |

## 6. profit_plan_live_ladder migration

- **Reporting/read-only truth**: partially implemented (PR #113 merged, provides canonical read-model consumption); deterministic row identity and the full freshness-authority set remain open, migrated to #267.
- **decision_gate**: no prior owner; migrated to #268, which depends on #227 for the general account-protection contract but does not duplicate it.
- **execution_planner**: no prior owner; migrated to #269, which is scoped to the cancel/create dependency contract distinct from #202/#203's `EXIT_LADDER` construction domain, with explicit coordination requirement to avoid a second divergent planner implementation.
- **executor/order lifecycle**: fully covered by existing #206 (dry-run/paper/live modes, single-writer protection, immutable handoff identity); not duplicated.
- **credential/account boundaries**: fully covered by existing #206; not duplicated.
- **live canary**: fully covered by existing #206's scope (mode definition without silently upgrading authority); not duplicated.

## 7. fibo_zones migration

- **Production activation/cutover**: found already implemented and deployed — merged PRs #171 (`agent/fibo-dashboard-production-lane-v1`) and #173 (`fix/fibo-dashboard-freshness-clock-v1`), live at `https://synth.aismid.nl/synth/fibo-map.html`. The file's `Status` line describing this as pending is stale/superseded. Current live-surface follow-up is owned by existing #249; not duplicated.
- **Research/calibration**: three open P2 lanes (exit-profile continuation, leak-free touch evaluation, native map calibration) consolidated into one new research Issue, #270, since all three share one architecture owner (research, market-only, account-agnostic) and are thematically linked exit/zone-quality validation work. The zone-context-guardrail P2 item was found to duplicate an existing `AGENTS.md` rule and needs no separate Issue.
- **Reporting overlays**: two open P3 lanes (fib/zone UI overlays, target-box normalization) consolidated into one new reporting Issue, #271, since both are read-only display concerns with no calculation logic and no overlap with #239/#240.
- **Promotion/strategy-adjacent language**: the file's design-implication diagram (research -> asset_exit_profile -> decision_gate -> execution_planner -> executor) is a forward-looking architecture note, not a section with validated promotion scope. Per Batch 6B instructions, no runtime-selection Issue was filed for it; it remains an explicit future-review note in the source file.

## 8. Architecture safety

- No new Issue grants `decision_gate` market-ranking authority, grants `execution_planner` broker-write authority, or grants `executor` selection/account-permission authority.
- #268 (decision_gate) and #269 (execution_planner) are separate Issues with separate primary owners; #269 explicitly states `account_permission_owned_elsewhere=1`.
- #267 (reporting) carries no decision or execution authority (`decision_permission=0`, `execution_intent=0`).
- #270/#271 (research/reporting) carry no account awareness, decision, or execution authority.
- No layer bypass is introduced: the migrated Issue set preserves `selection_engine` (untouched) -> reporting (#267) -> `decision_gate` (#268) -> `execution_planner` (#269) -> executor (#206, existing) sequencing for Lane A, and research (#270) -> reporting (#271) with no direct promotion path for Lane B.

```text
architecture_boundary_violations=0
```

## 9. Retirement impact

```text
profit_plan_live_ladder_unmigrated_scope=0
fibo_zones_unmigrated_scope=0
batch_6a_R1_delta=2 additional files moved from "no Issue" to fully Issue-mapped (profit_plan_live_ladder.md, fibo_zones.md); Batch 6A's "no Issue exists at all" list drops from 24 to 22 files
batch_6a_R2_delta=both files' README rows now carry explicit Issue-ownership annotations consistent with the ISSUE_OWNED pattern used elsewhere in the frozen board; global R2 status for the remaining 22 files is unchanged by this batch
```

Global R1/R2 PASS is not claimed. This batch improves exactly the two named
files; the remaining Batch 6C/6D file sets from the Batch 6A manifest are
still open.

## 10. Acceptance evidence

```text
source_files=2
source_files_fully_migrated=2
source_files_partially_migrated=0
existing_issues_reused=3
new_issues_created=5
duplicate_issues_created=0
unmigrated_executable_scope_items=0
architecture_boundary_violations=0
source_files_deleted=0
source_files_moved=0
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```
