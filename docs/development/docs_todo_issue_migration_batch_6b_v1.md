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

### Correction (2026-08-07)

An independent review of #202, #203, #206, #254 and new #267-#271 found four
Lane A ownership errors in the original pass, corrected in place below and in
the source docs:

1. #254 ("Add multi-account operator intent and ladder-request state") was
   misclassified `no overlap`; it explicitly owns the canonical operator-
   intent/ladder-request lifecycle, status model, and dashboard/API write
   boundary that Lane A's mutation flow requires. Reclassified `material
   overlap` and adopted as the upstream owner for P0.4's untrusted-selection
   and lifecycle scope instead of building a parallel request flow.
2. #267 was scoped to include canonical mutation-request identity and the
   authenticated write route, coupling reporting output to `decision_gate`
   permission input. Narrowed to display-only row key + freshness
   presentation, with an explicit non-authority statement.
3. #269 originally defined a second neutral request/intake module,
   duplicating #202 ("account-aware manual execution request artifact,
   immutable plan snapshot, and deterministic request idempotency
   contract"). Narrowed to a post-`APPROVED`-decision execution-intent
   extension only, consuming #202's snapshot and reusing #203's primitives.
4. P0.8 (one-account live canary) was mapped to #206, which explicitly lists
   granting live-trading permission and order submission as out of scope.
   No existing Issue fully owns the canary; a new bounded Issue (#273) was
   created with dependencies on #206, #254, #202, #268, #269, and an
   explicit, separately granted live-trading permission.

Fibo Lane B (#270, #271) was independently reviewed and found
architecturally clean; no changes were made there.

## 2. Source classification

### `docs/todo/profit_plan_live_ladder.md` (corrected)

| Section/scope | Classification | Existing owner | New owner | Result |
| --- | --- | --- | --- | --- |
| P0.0-P0.2 display row key + freshness presentation (no mutation/permission authority) | partially implemented (PR #113 merged; row key still `uuid.uuid4()` in `src/reporting/manual_short_trader_profit_plan_v1.py`) | none | #267 | migrated |
| P0.4/P0.5 untrusted client selection, ladder-request lifecycle, dashboard/API write boundary | genuinely open | #254 | #254 (existing, reused) | migrated |
| P0.4/P0.7 canonical request artifact, immutable snapshot identity, idempotency | genuinely open | #202 | #202 (existing, reused) | migrated |
| P0.6 decision gate and dry-run plan (consuming #254/#202 canonical state only) | genuinely open | none | #268 | migrated |
| execution_planner allocation/rounding/leg-validation primitives | genuinely open | #203 | #203 (existing, reused) | migrated |
| P0.7 post-approval immutable CANCEL_LIMIT -> verify -> CREATE_LIMIT execution intent | genuinely open | none | #269 | migrated |
| P0.3 credential scope, executor identity/runtime boundary, account/credential boundaries (A5) | genuinely open | #206 | #206 (existing, reused) | migrated |
| P0.8 one-account live canary | genuinely open | none | #273 | migrated |
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
| #202 | manual execution request snapshot/idempotency | **material** — owns the canonical request artifact, immutable plan-snapshot identity, and idempotency contract that Lane A's mutation flow requires; adopted as owner, not a mere dependency of a second module |
| #203 | manual execution ladder construction/leg validation | **material** — owns the authoritative allocation/rounding/fee-haircut/minimum-quantity/minimum-notional primitives; #269 reuses these rather than reimplementing them |
| #206 | credential scope / manual execution runtime boundary | full for credential/executor-boundary/mode-contract scope (A5); **does not** cover live-trading permission or order submission (explicitly out of scope in #206's own text) — not the P0.8 live-canary owner |
| #227 | account-aware drawdown/loss/cooldown protection contract | partial — general protection contract, not ladder-repair-specific eligibility (ownership, freshness, duplicates, caps, expiry); recorded as dependency of #268 |
| #254 | multi-account operator intent/ladder-request state | **material** (corrected from "no overlap") — explicitly defines `operator intent persistence -> decision_gate permission/context -> execution_planner intent generation -> executor/agents order handling`, `BUY_LADDER_REQUESTED`/`SELL_LADDER_REQUESTED` intent types, `WAITING_FOR_MARKET_CONTEXT`/`WAITING_FOR_PERMISSION`/`READY_FOR_PLANNING` status model, dashboard/API write boundary, and duplicate/conflicting-ladder fail-closed handling — this is the same lifecycle Lane A's mutation flow needs; adopted as owner instead of building a parallel request path |
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
| #267 | Add display-only row key and freshness presentation to Profit Plan ladder-repair read model | `profit_plan_live_ladder.md` (P0.0-P0.2 display scope only) | reporting | Stable display row key, full 7-class freshness presentation; explicitly no mutation/permission authority |
| #268 | Design decision_gate approval contract for Profit Plan ladder-repair requests | `profit_plan_live_ladder.md` (P0.6) | decision_gate | APPROVED/REJECTED/REVIEW_REQUIRED evaluator over #254/#202 canonical request state: ownership, permission, freshness, funds/position, duplicates, caps, expiry |
| #269 | Define execution_planner post-approval cancel/create intent for Profit Plan ladder repair | `profit_plan_live_ladder.md` (P0.7, post-approval half of P0.4/P0.5) | execution_planner | Post-`APPROVED` immutable ordered CANCEL_LIMIT->verify->CREATE_LIMIT plan, consuming #202 snapshot and #203 primitives only |
| #270 | Validate Fibo/zone exit-profile, leak-free touch, and native map calibration research | `fibo_zones.md` (3 P2 sections) | research | Exit-profile bucket re-validation, leak-free touch evaluator, signed level-error replay/calibration |
| #271 | Add Fibo/zone UI overlays and external target-box display normalization | `fibo_zones.md` (2 P3 sections) | reporting | Zone/fib marker overlays with explicit source, external target-box research-label display |
| #273 | Accept controlled one-account live canary for Profit Plan ladder repair | `profit_plan_live_ladder.md` (P0.8) | executor | One-account/one-market canary acceptance after #206/#254/#202/#268/#269 complete and live permission explicitly granted |

## 5. Existing Issues reused

| Issue | Source section | Ownership |
| --- | --- | --- |
| #254 | `profit_plan_live_ladder.md` P0.4/P0.5 untrusted selection, ladder-request lifecycle, dashboard/API write boundary | material — already owns the operator-intent/ladder-request lifecycle and status model this lane needs |
| #202 | `profit_plan_live_ladder.md` P0.4/P0.7 canonical request artifact/snapshot/idempotency | material — already owns the immutable request/plan-snapshot identity and idempotency contract |
| #203 | `profit_plan_live_ladder.md` execution_planner allocation/rounding/leg-validation primitives | material — already owns the authoritative primitives #269 reuses |
| #206 | `profit_plan_live_ladder.md` P0.3 credential scope, executor identity/runtime boundary (A5) | full for credential/executor-boundary scope; explicitly not the live-canary owner |
| #201 | `profit_plan_live_ladder.md` multi-cycle host acceptance of merged renderer | full — already owns host-ownership/freshness/multi-cycle acceptance for this renderer family |
| #249 | `fibo_zones.md` P0 production publication/cutover | full — production dashboard is live; #249 owns the current open defect on that live surface |

## 6. profit_plan_live_ladder migration (corrected)

- **Reporting/read-only truth**: partially implemented (PR #113 merged, provides canonical read-model consumption); narrowed to a display-only row key and freshness presentation in #267, with an explicit statement that reporting output is never authoritative `decision_gate` input.
- **Operator-intent / ladder-request lifecycle**: fully covered by existing #254 (canonical intent persistence, status model, dashboard/API write boundary); not duplicated. This is the corrected upstream owner for the untrusted client selection that a mutation flow requires.
- **Canonical request artifact / snapshot / idempotency**: fully covered by existing #202; not duplicated.
- **decision_gate**: no prior owner; migrated to #268, which now depends explicitly on #254 and #202 for its input (not on #267's display row key) and on #227 for the general account-protection contract.
- **execution_planner**: no prior owner for the post-approval intent step; migrated to #269, narrowed to consume only an `APPROVED` #202 snapshot and reuse #203's primitives — no second request/intake module.
- **executor/order lifecycle boundary**: fully covered by existing #206 (dry-run/paper/live modes, single-writer protection, immutable handoff identity); not duplicated.
- **credential/account boundaries**: fully covered by existing #206; not duplicated.
- **live canary**: no existing Issue fully owns this — #206 explicitly excludes granting live-trading permission and order submission. New Issue #273 created, depending on #206, #254, #202, #268, #269, and a separately granted live-trading permission.

## 7. fibo_zones migration

- **Production activation/cutover**: found already implemented and deployed — merged PRs #171 (`agent/fibo-dashboard-production-lane-v1`) and #173 (`fix/fibo-dashboard-freshness-clock-v1`), live at `https://synth.aismid.nl/synth/fibo-map.html`. The file's `Status` line describing this as pending is stale/superseded. Current live-surface follow-up is owned by existing #249; not duplicated.
- **Research/calibration**: three open P2 lanes (exit-profile continuation, leak-free touch evaluation, native map calibration) consolidated into one new research Issue, #270, since all three share one architecture owner (research, market-only, account-agnostic) and are thematically linked exit/zone-quality validation work. The zone-context-guardrail P2 item was found to duplicate an existing `AGENTS.md` rule and needs no separate Issue.
- **Reporting overlays**: two open P3 lanes (fib/zone UI overlays, target-box normalization) consolidated into one new reporting Issue, #271, since both are read-only display concerns with no calculation logic and no overlap with #239/#240.
- **Promotion/strategy-adjacent language**: the file's design-implication diagram (research -> asset_exit_profile -> decision_gate -> execution_planner -> executor) is a forward-looking architecture note, not a section with validated promotion scope. Per Batch 6B instructions, no runtime-selection Issue was filed for it; it remains an explicit future-review note in the source file.

## 8. Architecture safety

- No new Issue grants `decision_gate` market-ranking authority, grants `execution_planner` broker-write authority, or grants `executor` selection/account-permission authority.
- The reporting -> decision_gate coupling flagged in review is corrected: #267 is display-only and carries an explicit non-authority statement (`display_row_key != canonical request identity`, `reporting output is never authoritative decision_gate input`); #268 now depends on #254/#202 canonical state, not on #267.
- #268 (decision_gate) and #269 (execution_planner) are separate Issues with separate primary owners; #269 explicitly states `account_permission_owned_elsewhere=1` and accepts input only after an `APPROVED` #268 result.
- #269 no longer defines a second request/intake module; untrusted client input is owned exclusively by #254/#202, avoiding a parallel ladder-request lifecycle.
- #273 (live canary) does not itself grant permission, construct plans, rank markets, bypass `decision_gate`, or provision credentials; it requires #206/#254/#202/#268/#269 to be independently complete plus a separately granted live-trading permission (`permission_must_preexist=1`, `execution_plan_must_preexist=1`).
- #270/#271 (research/reporting) carry no account awareness, decision, or execution authority.
- No layer bypass is introduced: the corrected Issue set preserves `selection_engine` (untouched) -> reporting (#267, display only) -> operator-intent/request layer (#254, #202) -> `decision_gate` (#268 + #227) -> `execution_planner` (#269, using #203 primitives) -> executor/credential boundary (#206) -> live canary (#273) -> executor order handling, matching the required flow; and research (#270) -> reporting (#271) with no direct promotion path for Lane B.

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
existing_issues_reused=6
new_issues_created=6
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
