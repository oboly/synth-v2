# Elliott Wave Daily Context Lane — Design Bundle v1

> **Migration pointer — PARTIAL migration only.** This file is **not**
> wholly owned by an Issue.
>
> - GitHub Issue
>   [#219 — Remove research-layer import from native SHORT market-data context](https://github.com/oboly/synth-v2/issues/219)
>   owns **only** the narrow architecture-hygiene item in §0 ("Layering
>   violation to fix first"): `src/market_data/native_short_fib_context_v1.py`
>   must not import from `src.research`. Current execution status, priority,
>   blockers, acceptance criteria, and closure **for that one item only**
>   belong to Issue #219.
> - The remaining Elliott Wave Phase-1 research/labeler scope (§1-§5, §7 —
>   the labeler spec, trade hypotheses, manual-approval path, validation
>   protocol, and the "what the coordinating chat should produce" work
>   order) is **still proposal-only and unmigrated**. It has no owning
>   Issue. Do not treat it as filed, scheduled, or in progress.
> - This file must not become a parallel status board for the migrated
>   subtask: do not update status, priority, blockers, or next action for
>   the layering-fix item here — that lives in Issue #219 only. The
>   unmigrated research scope may still be edited as design content, but
>   not represented as having Issue-backed execution status.
> - See `docs/development/github_issues_workflow.md`,
>   `docs/todo/MIGRATION_FREEZE.md`, and
>   `docs/development/github_issues_batch_2a_migration_v1.md`.

Handoff document for the coordinating chat. Purpose: turn the Elliott Wave discussion
into a falsifiable, Synth-compatible research lane and a work order for an agent.
Origin: Claude/Joost session 2026-07-06, including repo verification of oboly/synth-v2.

---

## 0. Ground truth (verified against the repo — do not redesign against assumptions)

- Database is **MariaDB/MySQL**, not PostgreSQL (`cur.lastrowid`, docs/dev_ops_hygiene).
- Venue is **Bitvavo spot, EUR quote only**. No perps, no funding, no bearish shorting.
- `SHORT` in Synth means **trading horizon**, not direction. Existing native maps are
  long-side breakout/extension maps on 4h primary / 1h support.
- `now_utc` is already an injected parameter in `build_native_short_context_row` and
  `materialize_scope_symbol`. Remaining wall-clock poison: 3× `... or datetime.now(UTC)`
  fallbacks in the materializer fetch functions (must fail closed instead).
- Layering violation to fix first: `src/market_data/native_short_fib_context_v1.py`
  imports `src.research.htf_fib_extension_confluence_v1` and
  `src.research.htf_fib_reentry_ladder_v1`. Extract pure fib/swing math to a shared
  pure module usable by both runtime and research.
- Active P0 is `docs/todo/profit_plan_live_ladder.md`. This EW lane is research-only
  and must not compete with or touch that lane.

## 1. Concept

A **deterministic, incremental, event-sourced Elliott Wave labeler on the 1d timeframe**,
used as a context/regime layer above the existing 4h native maps — not as a standalone
entry engine.

Core insight from the discussion: EW's subjectivity lives almost entirely in pivot
selection and hindsight relabeling. Synth already has deterministic pivot detection
(`_detect_swings`, fixed `pivot_span`) and an append-only confirmed-structure ledger
(native_short_map_v1 + generation/lifecycle events). The EW lane reuses both patterns.
Confirmed wave labels are frozen; new candles extend the count; broken counts emit
INVALIDATED lifecycle events and re-anchor deterministically. No silent recounting, ever.

## 2. Labeler specification (v1)

- **Scale:** 1d candles only. One count object per (venue, symbol, timeframe). Never mix scales within a count.
- **Pivots:** reuse existing pivot logic with a deliberately coarse daily `pivot_span` (candidate range 3–5, to be swept, plateau preferred).
- **Hard rules (falsifiable core):**
  - Wave 2 never retraces below start of wave 1.
  - Wave 3 is never the shortest of 1/3/5.
  - Wave 4 does not overlap wave 1 territory (impulse).
  - Corrections labeled as A-B-C only after impulse completion is confirmed.
- **Confirmation:** a wave label is confirmed only when its terminal pivot is confirmed
  (pivot_span daily candles later). Confirmed labels are immutable ledger rows.
- **Invalidation / re-anchor:** any hard-rule violation → count INVALIDATED (lifecycle
  event with reason code) → new count anchors at a pre-defined deterministic point
  (e.g., the invalidating swing low). Mirror the existing CASE_A/B/C rollover semantics.
- **Ambiguity:** if multiple counts are valid at time T, build all candidates, rank with
  a deterministic `_candidate_rank`-style function, store the chosen one, log the rest.
  If ranking cannot separate them → state `AMBIGUOUS`. The AMBIGUOUS rate is itself a
  primary research output.
- **State output per symbol per day:** `wave_phase` ∈ {IMPULSE_1, IMPULSE_3, IMPULSE_5,
  CORRECTIVE_A, CORRECTIVE_B, CORRECTIVE_C, AMBIGUOUS, INVALIDATED, INSUFFICIENT_HISTORY}
  plus count metadata (anchors, rule distances, confirmation lag).

## 3. Trade hypotheses (to validate, not to assume)

1. **Regime gate (primary, lowest risk):** 4h long breakout maps only get green light
   when the daily count is in IMPULSE_3 / IMPULSE_5; suppressed during CORRECTIVE_A/B/C.
   Testable as an interaction effect on the existing map outcomes.
2. **C-bottom entry (Joost's preferred setup):** end of corrective C as long entry zone.
   Constraint: C-completion is only knowable after reversal confirmation — the entry
   trigger must be "C-zone reached AND reversal confirmed on 4h" (e.g., reclaim of a
   level, higher-low structure), never "price is at projected C target." Confluence with
   existing fib reload ladder levels (r382–r786) is the natural implementation: EW gives
   the phase, the fib ladder gives the level, 4h structure gives the trigger.
3. **B-wave profit-taking (secondary):** B tops as *exit/de-risk* signal for open longs.
   Note: trading B as a fresh counter-trend entry is the weakest-edge, worst-risk variant
   (B is by definition inside a correction); v1 should test B only as an exit modifier.

## 4. Manual approval path (human-in-the-loop)

When the labeler outputs AMBIGUOUS (or a low-confidence rank margin), the lane may raise
a **manual review request** instead of deciding:

- Review requests and human verdicts are **persisted events** (who/when/what/why),
  because replay determinism requires that manual decisions are part of the recorded
  event stream — a replay must see the same approvals, not re-ask.
- Manual approval fits Synth's existing proposal culture (cockpit, manual ladder) and
  must flow through the normal layers: it can promote a context state, never place or
  modify orders directly.
- Metric to watch: manual-review rate. If humans must arbitrate most counts, the
  algorithm isn't a labeler yet.

## 5. Validation protocol (before any strategy coupling)

Phase 1 — label quality only (no PnL):
- (a) AMBIGUOUS + INVALIDATED rates per symbol.
- (b) Forward return distributions per wave_phase vs. unconditional baseline
  (leak-free, point-in-time, same style as bt_selection_v2 eval horizons).

Phase 2 — only if Phase 1 separates phases: hypothesis 1 (regime gate) as an
interaction test on existing 4h map outcomes.

Phase 3 — only if Phase 2 survives costs: hypotheses 2/3 through the standard
experiment contract (immutable configs, manifests, train/validation/locked OOS,
plateau selection).

Sample-size honesty: a full daily impulse+correction cycle spans months–years. With
available history this yields few independent cycles per coin; alts are BTC-correlated,
so the effective cross-sectional sample is small. Therefore: coarse parameters, broad
plateaus, simple rules. Fine-tuning on this sample is curve-fitting by construction.

## 6. Boundaries

- Research-only lane: `src/research/` + `research_*` tables / `data/research/` outputs.
- Market-only, account-agnostic. No selection/decision/execution changes in v1.
- Does not touch profit_plan_live_ladder P0, run_chain_4h.sh, broker paths.
- Prerequisite hygiene PRs (small, do first): (1) materializer timestamp fallbacks fail
  closed; (2) extract pure fib/swing functions out of `src.research` imports; (3) CI
  guard forbidding `datetime.now|utcnow` in market code and `src.research` imports
  outside research/backtest namespaces.

## 7. What the coordinating chat should produce

1. A GitHub Issue for this file conforming to
   `docs/development/github_issues_workflow.md` (objective, scope, architecture
   boundary, acceptance criteria, evidence, safety). The legacy TODO board is
   frozen: do not add a new TODO entry or index row.
2. An agent prompt whose deliverable is **Phase 1 only**: labeler module + ledger tables
   (or parquet outputs) + the two metrics on BTC-EUR first, then top-N liquid symbols.
3. Explicit non-goals in the agent prompt: no strategy code, no execution, no UI, no
   parameter optimization beyond the coarse pivot_span sweep.
4. Promotion criteria written down BEFORE running: e.g., AMBIGUOUS < X%,
   phase-conditioned forward-return separation significant under the pre-registered
   test, stable across 2+ market regimes.

---
*Verified sources: https://github.com/oboly/synth-v2 (README, docs index, docs/todo,
src/market_data/native_short_map_materializer_v1.py,
src/market_data/native_short_fib_context_v1.py, commit a835eb4).*
