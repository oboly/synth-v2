# Multi-Account Asset Foundation — Phase 2-5 Current-State Audit

> **Revision note (2026-08-09):** corrected in response to PR #337 program
> review, which found the original `R2_AFTER=PASS` /
> `BACKLOG_UNMIGRATED_EXECUTABLE_SCOPE_COUNT=0` conclusion internally
> inconsistent with this document's own Phase 3 and Phase 5.3 findings.
> Sections 4, 6, 10, 11, 12 revised to count the Phase 3 tail and Phase 5.3
> verification as executable unowned scope; `R2_AFTER` is now `FAIL`. See
> Section 10 for the reconciled rule application.

Fresh current-`main` architecture/call-site review of historical Phases 2-5,
required by `docs/todo/multi_account_asset_foundation_backlog.md` ("Phase 2-5
review gate") and `docs/research/multi_account_asset_foundation_v1.md`
before any follow-up Issue for these phases may be filed. This document is
read-only evidence, not a new architecture contract.

## 1. Scope / non-goals

In scope: current-`main` call-site inventory and classification for
`asset.is_portfolio`, `asset.quote_asset`/`quote_currency`,
`asset.is_tradeable`, `venue_market`, `account_asset`; Phase 5 sub-item
verification; Issue #319 overlap; backlog/R2 determination; future Issue
decomposition proposal (not created).

Out of scope (explicitly not performed): filing GitHub Issues, code changes,
schema changes, production DB access/queries, closing/editing existing
Issues, repairing Issue #333's drift, resolving Issue #319 itself.

## 2. Current-main baseline

```text
BASE_SHA=d82f7a95ecf94d6153e0c79102b61ea7f9fee21e
BRANCH=docs/multi-account-phase-2-5-current-state-audit-v1 (from origin/main)
LATEST_MAIN_COMMIT_TOUCHING_TOPIC=d82f7a95 "Correct multi-account asset foundation docs to reflect production reality (#334)"
```

Canonical docs read: `docs/research/multi_account_asset_foundation_v1.md`,
`docs/todo/multi_account_asset_foundation_backlog.md`,
`docs/development/multi_account_asset_foundation_phase_1_reality_audit_v1.md`.
GitHub Issues read: #294 (CLOSED, Phase 1), #319 (OPEN), #333 (OPEN).

No production/DB access was used in this audit (read-only static/code
evidence only, per task instruction to mark DB-dependent items UNVERIFIED
rather than reuse Phase 1's live-verified figures, which are 2026-08-09
point-in-time and not re-queried here).

## 3. Phase 2 findings — `asset.is_portfolio`

Current-main reference count is far higher than the historical "3 refs,
watchlist only" premise. `is_portfolio` now has two materially different
live meanings on `main`:

1. **Legacy per-symbol membership flag** (original meaning) — still read in
   `src/research/run_kite_watchlist_candidate_check_v1.py` (research-only,
   3-ish refs, matches original premise).
2. **Account-agnostic "publication cohort" gate** (new meaning, not present
   in the original design) — `asset.is_portfolio` (together with
   `is_core_sensor`) now gates canonical Fib zone map publication eligibility
   across `src/market_data/`:
   - `src/market_data/held_market_coverage_v1.py` — explicit docstring:
     "account-agnostic publication cohort (asset.is_portfolio/is_core_sensor
     set)" (Issue #238 follow-up).
   - `src/market_data/canonical_fib_zone_map_v1.py:571` —
     `WHERE ... (COALESCE(a.is_portfolio,0)=1 OR COALESCE(a.is_core_sensor,0)=1)`.
   - `src/market_data/run_held_market_enrollment_v1.py` — dedicated runner
     that flips `asset.is_portfolio` 0->1 to enroll held-but-uncovered assets
     into this cohort; explicitly documents it "only ever flips ... from 0 to
     1", i.e. one-way enrollment, not account-scoped membership toggling.
   - `src/market_data/run_held_market_coverage_health_check_v1.py` — health
     check keyed on the same flag pair.
   - `src/reporting/account_scoped_short_trader_dashboard_v1.py` — reads
     `a.is_portfolio` as `asset_is_portfolio` for account-scoped display.
   - `src/reporting/manual_short_trader_profit_plan_v1.py` — a *different*,
     dataclass-level `is_portfolio_asset` (computed from
     `portfolio_asset_markets`, not read directly from
     `asset.is_portfolio`) with its own deprecated-alias handling
     (`is_portfolio_held`, see `tests/test_profit_plan_portfolio_composition_v1.py:262-263`).

Classification:

| Reference | Class |
|---|---|
| `run_kite_watchlist_candidate_check_v1.py` | ACTIVE_RUNTIME_READ (research) |
| `held_market_coverage_v1.py`, `canonical_fib_zone_map_v1.py`, `run_held_market_enrollment_v1.py`, `run_held_market_coverage_health_check_v1.py` | ACTIVE_RUNTIME_READ/WRITE (market_data — account-agnostic, consistent with layer boundary) |
| `account_scoped_short_trader_dashboard_v1.py` | ACTIVE_RUNTIME_READ (reporting, read-only display) |
| `manual_short_trader_profit_plan_v1.py` `is_portfolio_asset`/`is_portfolio_held` | ACTIVE_RUNTIME_READ (reporting; own dataclass field, deprecated-alias compatibility, not a direct `asset.is_portfolio` column read) |
| `run_bitvavo_market_sync_v1.py`, `db/migrations/20260619_*` | MIGRATION_COMPATIBILITY / ETL upsert passthrough |
| `tests/test_*` (7 files) | TEST_ONLY |
| `docs/asset_flag_policy.md`, `docs/repo_structure_policy.md`, `docs/research/watchlist_design.md`, `docs/research/watchlist_feature_signal_status_v1.md`, `docs/todo/watchlist_candidates.md`, `docs/status/*`, `docs/ops/held_market_enrollment_v1.md`, `docs/ops/bitvavo_market_sync_v1.md`, `docs/research/kite_watchlist_candidate_check_v1.md` | DOC_ONLY |
| `db/migrations/20260603_multi_account_asset_foundation_v1.sql` (`account_asset.is_portfolio_member` comment "replaces asset.is_portfolio") | HISTORICAL (Phase 1 skeleton intent) |

**Determination:** Historical Phase 2 ("migrate `is_portfolio` to
`account_asset`, 3 refs, low risk") is **superseded, not satisfied**. The
original premise — that `is_portfolio` is purely a low-traffic per-account
watchlist flag safe to move to `account_asset.is_portfolio_member` — no
longer matches reality. `is_portfolio` has organically grown into a
load-bearing, account-agnostic publication-cohort primitive for the Fib
zone map pipeline (`market_data` layer), which is architecturally correct
where it lives (market-only, account-agnostic) but is a different design
problem than the one Phase 2 was scoped to solve. Moving it wholesale to
`account_asset` (a per-`trading_account_id` table) would be an architecture
regression: it would make an account-agnostic market-data gating flag
account-specific, breaking the very Fib publication cohort that depends on
it being global. **Not ready to file as-is.** Any future Issue must first
resolve a naming/design question (should the account-agnostic cohort flag
be renamed/kept distinct from a true per-account watchlist flag?) before
a call-site migration is executable — this is a design decision, not
mechanical work, so it does not count as executable scope.

## 4. Phase 3 findings — `asset.quote_asset` / quote currency

`quote_asset` (35 refs) and `quote_currency` (61 refs) both exist on
current `main`, with `venue_market.quote_currency` already the source of
truth for market-data/reporting code:

- `src/market_data/` (30 `quote_currency` refs) — dominant consumer,
  already venue_market-based (ACTIVE_RUNTIME_READ, no `asset.quote_asset`
  dependency observed here).
- `src/reporting/` (15 `quote_currency` refs, incl.
  `account_wallet_dashboard_v1.py: vm.is_tradeable`,
  `vm.quote_currency`) — already reads `venue_market` directly
  (ACTIVE_RUNTIME_READ, venue_market-based, matches target design).
- `src/research/` — mixed: several runners
  (`run_fibo_target_map_v1.py`, `run_multi_horizon_fib_backtest_v1.py`,
  `run_fib_leg_pair_observation_preview_v1.py`,
  `run_canonical_fib_zone_map_writer_preview_v1.py`) use the documented
  compatibility pattern `if "quote_asset" in columns: ... else quote_currency`
  — exactly the fallback pattern the canonical design doc already describes
  as intentional interim compatibility (MIGRATION_COMPATIBILITY).
- `src/etl/bitvavo/run_candles_etl.py`, `etl_bitvavo_ticker24h.py` —
  `quote_asset` used as ETL config/request field (own dataclass, not a
  direct `asset.quote_asset` column read) (ACTIVE_RUNTIME_READ, ETL-owned).
- `src/decision_gate/manual_execution_approval_v1.py`,
  `manual_execution_gate_v1.py`, `src/execution_planner/contract_preview_v1.py`,
  `src/manual_execution/manual_execution_request_v1.py` — `quote_asset` here
  is a field on the manual-execution request/approval record (its own table,
  not `asset.quote_asset`), used for market-pair identification in an
  account-aware approval flow. This is legitimate: decision_gate/
  execution_planner are permitted to know the market/quote pair for the
  trade they are approving; this is not an `asset` table coupling and not
  an account-agnostic-layer violation (ACTIVE_RUNTIME_READ, decision_gate/
  execution_planner-owned, architecturally fine as-is).

**Determination:** venue_market already supersedes the old `asset.quote_asset`
design premise for the dominant consumers (market_data, reporting). The
remaining `asset.quote_asset`-column reads are confined to a handful of
research runners using the documented fallback pattern, which is safe,
narrow, and was explicitly anticipated by the canonical design doc. No
account coupling was found where it should not exist, and no design
decision is outstanding — the target state (`venue_market`-only) is already
established and in use by the dominant consumers.

**Reconciliation (program review, 2026-08-09):** this is **currently
executable, unowned scope**, not merely "close to executable." Named files
(`run_fibo_target_map_v1.py`, `run_multi_horizon_fib_backtest_v1.py`,
`run_fib_leg_pair_observation_preview_v1.py`,
`run_canonical_fib_zone_map_writer_preview_v1.py`,
`run_kite_watchlist_candidate_check_v1.py`), no dependency, no unresolved
design question — removing the `asset.quote_asset` fallback branch in favor
of the already-present `venue_market`/`quote_currency` path is mechanical.
This audit itself is the "fresh review" gate the backlog required before
filing; having performed it, the scope is no longer blocked and must be
counted (see Section 10). It is not filed as an Issue in this audit per
task instruction (no Issues created here), but it counts toward
`BACKLOG_UNMIGRATED_EXECUTABLE_SCOPE_COUNT`.

## 5. Phase 4 findings — `asset.is_tradeable`, venue-aware market selection

`is_tradeable` appears 43 times across `src/`. Layer-by-layer:

- `src/selection/run_selection_engine_v2.py:170` — `AND a.is_tradeable = 1`
  (bare `asset` table read, **not** `venue_market`-joined). selection_engine
  remains venue-unaware for tradability; Phase 4's stated goal ("selection_engine
  should become venue-aware") is **not yet done**. Critically, this file has
  **no** `account_asset` or `venue_market` reference at all — selection_engine
  is confirmed **account-agnostic** (compliant), just not yet venue-aware
  (incomplete, not a violation).
- `src/advice/run_structural_missing_refresh_v1.py`,
  `src/regime/run_policy_router_preview_v1.py`,
  `src/zone/run_fib_observation_backfill_v1.py`,
  `src/zone/run_execution_zone_context_backfill_v1.py`,
  `src/zone/repository.py`,
  `src/research/run_fib_reaction_profile_v1.py`,
  `src/research/run_market_breath_analysis_v1.py` — all still read
  `asset.is_tradeable` directly (bare column, no venue_market join)
  (ACTIVE_RUNTIME_READ, legacy-compatibility-mode as the design doc
  anticipated: "the column stays on asset in read-only compatibility mode
  until Phase 2 callers are updated").
- `src/reporting/account_wallet_dashboard_v1.py` — already reads
  `vm.is_tradeable` (venue_market-joined) (ACTIVE_RUNTIME_READ,
  already-migrated).
- `src/reporting/account_scoped_short_trader_dashboard_v1.py` — reads
  `a.is_tradeable` (asset-table, account-scoped dashboard display)
  (ACTIVE_RUNTIME_READ, legacy).
- `src/reporting/account_asset_management_v1.py` — operates on a raw dict
  payload's `is_tradeable` key (own view-model field, not a direct column
  read) (ACTIVE_RUNTIME_READ).
- `src/market/run_bitvavo_market_sync_v1.py` — writes
  `venue_market.is_tradeable` from Bitvavo's market status (ACTIVE_RUNTIME_WRITE,
  already venue_market-authoritative for market sync).
- `src/operations/run_runtime_freshness_audit_v1.py` — conditional
  `is_tradeable = 1` filter guarded by a column-existence check
  (ACTIVE_RUNTIME_READ, defensive/ops).

**Boundary verification (explicit):**

```text
selection_engine_account_asset_refs=0
selection_engine_venue_market_refs=0
decision_gate_account_asset_refs=0
decision_gate_venue_market_refs=0
execution_planner_account_asset_refs=0
execution_planner_venue_market_refs=0
executor_account_asset_refs=0
executor_venue_market_refs=0
```

selection_engine is confirmed venue-unaware-but-account-agnostic (compliant
with the hard boundary: "selection_engine MUST NOT depend on account_asset
or other account-specific state"). No `account_asset`-driven market
selection has leaked into selection_engine, decision_gate,
execution_planner, or executor.

**Determination:** Historical Phase 4 remains a real, still-unmigrated gap
(`asset.is_tradeable` is authoritative for selection_engine and most
strategy-facing readers; `venue_market.is_tradeable` is authoritative only
for market_sync writes and the newer account_wallet_dashboard read). It is
the largest of the three flag migrations (matches the original "higher
risk, 19 refs" framing, now ~43 refs after repo growth). It is **not
mechanical** — Phase 4.2 ("Add venue param to selection_engine candidate
fetch... largest refactor") is an architecture decision (how selection_engine
should carry venue context without becoming account-aware) that has not been
made. **Not ready to file as an executable Issue as-is**; the sub-decision
(how venue-awareness is threaded through selection_engine without violating
account-agnosticism) needs to be resolved first, which is design work, not
mechanical migration.

## 6. Phase 5 findings — Hugo / multi-account onboarding

- **5.1 Hugo trading_account row** — `DONE`. Confirmed via Phase 1 reality
  audit (`docs/development/multi_account_asset_foundation_phase_1_reality_audit_v1.md`,
  live-verified 2026-08-09: `trading_account_id=4`,
  `account_code=hugo-bitvavo`). Not re-verified live in this audit (no DB
  access used); resting on the cited prior live evidence, which is recent
  (same day as this audit's date context).
- **5.2 Hugo wallet discovery / account_asset population** — `DONE`. Same
  source: 27 live `account_asset` rows, `source=WALLET_DISCOVERY`.
- **5.3 Hugo open-order discovery** — `PARTIAL`. Current-main code evidence:
  `src/account/run_account_wallet_refresh_v1.py::discover_account_assets`
  implements open-order discovery generically for any
  `trading_account_id` (writes `source="OPEN_ORDER_DISCOVERY"`), driven by
  `--account-profile`/canonical `account_code` resolution (no hard-coded
  account IDs). The runner is account-parametrized, so the *mechanism*
  exists and is not Hugo-specific-missing. The Phase 1 reality audit's live
  snapshot showed `OPEN_ORDER_DISCOVERY=2` rows total across all accounts
  (2026-08-09) — non-zero, so the discovery path has executed in
  production at least once, but whether it has specifically been run for
  Hugo's account (`trading_account_id=4`) with his current open orders is
  not confirmed by this audit (no DB query performed). Classified `PARTIAL`:
  code-complete and demonstrably exercised in production, Hugo-specific
  execution/freshness `UNVERIFIED` without a DB read.
- **5.4 Dashboard account-scope filtering** — `DONE` (code-evidenced).
  Both account-aware dashboards
  (`src/reporting/account_wallet_dashboard_v1.py`,
  `src/reporting/account_scoped_short_trader_dashboard_v1.py`) consistently
  parameterize every account-facing query with
  `WHERE trading_account_id = %s` (or `aa.trading_account_id = %s` for
  `account_asset`-joined queries), resolved via `account_code` lookup
  (`_resolve_trading_account`), never a hard-coded numeric ID.
  `tests/test_account_scope_contract_v1.py` provides positive regression
  coverage for this filtering contract (109 tests pass, see Section 13).

**Determination:** Phase 5 is effectively `DONE` for 5.1/5.2/5.4 (code +
prior live evidence); 5.3 is `PARTIAL` (mechanism complete, Hugo-specific
freshness unverified without a DB read this audit did not perform). No
executable Issue-ready gap remains for 5.1/5.2/5.4. 5.3's only remaining
"gap" is verification, not implementation — a bounded read-only DB check
(count `account_asset` rows with `source=OPEN_ORDER_DISCOVERY` and
`trading_account_id=4`, compare against Hugo's live open orders), not a
code change.

**Reconciliation (program review, 2026-08-09):** this verification task is
**currently executable, unowned scope**, not merely "Issue-ready if filed
later." It has a concrete, bounded read-only check, no dependency, and no
outstanding design question — the only reason it was not performed here was
that this audit's own task instruction scoped out production/DB access, not
because the work itself is blocked. That is a real prerequisite (this
audit was not authorized to query production), but it is not a prerequisite
that prevents an Issue from being *filed and executed* by a future,
DB-authorized task. It counts toward
`BACKLOG_UNMIGRATED_EXECUTABLE_SCOPE_COUNT` (see Section 10).

## 7. Issue #319 overlap

Issue #319 ("Resolve account_id vs trading_account_id identifier
fragmentation (F6)", OPEN) scopes: an explicit, uniquely-constrained
`account_id -> trading_account_id` mapping, required for every
`decision_gate`/`execution_planner` repository call currently accepting a
bare `account_id`.

Current-main evidence confirms this is a live, present-day gap, not a
stale premise:

```text
src/decision_gate/models.py:63,86       account_id: int  (bare, no trading_account_id resolution)
src/decision_gate/decision_gate_v1.py   account_id threaded through ~15 call sites, bare
src/decision_gate/run_decision_gate_v1.py  account_id=args.account_id (bare CLI passthrough)
src/decision_gate/repository.py:221-259 fetch_sleeve_state(account_id: int, ...) bare, no mapping
src/execution_planner/run_execution_planner_contract_preview_v1.py:157  account_id=args.account_id (bare)
```

versus `trading_account_id` used explicitly and correctly elsewhere in the
same `decision_gate` module tree (132 occurrences in `src/decision_gate/*.py`
alone) and consistently in the newer `account_asset`/`venue_market` code
(`src/account/`, `src/reporting/account_*_dashboard_v1.py`). This is exactly
the fragmentation #319 describes: two identifier conventions coexist in
`decision_gate` today.

**Determination:**

- #319 already owns any Phase 2-5 work that would otherwise touch
  `decision_gate`/`execution_planner` account-identifier resolution. No
  Phase 2-5 Issue should duplicate #319's mapping-table/resolver scope.
- None of Phase 2, 3, or 4 as scoped (asset-column migrations, all
  market/venue-side, not account-identifier-side) structurally overlaps
  #319 — they touch different tables (`asset`/`venue_market` vs.
  `account_id`/`trading_account_id` mapping) and different call sites
  (selection/advice/zone/research vs. decision_gate/execution_planner).
  Phase 5.3's verification and #319 both eventually touch
  `account_asset`/`trading_account_id` correctness, but for different
  reasons (open-order backfill completeness vs. identifier mapping) — no
  duplication found.
- No architecture correction is needed to either #319 or the Phase 2-5
  docs from this overlap check; they are already correctly scoped as
  independent.
- Recommendation for any future Phase 2-5 Issue: state an explicit
  "does not depend on #319" or "must land after #319" note per Issue,
  since #319's mapping fix, if implemented, could change how future
  account-aware call sites (e.g. a hypothetical Phase 2 rename/split) pass
  account context. None of the Phase 2-5 findings in this audit are
  currently executable regardless, so this is a forward note only.

## 8. Current consumer matrix

| Concept | Authoritative source today | Primary readers | Primary writers | Runtime significance | Account-aware? | Layer | Legacy/removal status | Future action |
|---|---|---|---|---|---|---|---|---|
| `asset.is_portfolio` (legacy sense) | `asset` table | `run_kite_watchlist_candidate_check_v1.py` | manual/migration inserts | low (research-only) | No | research | LEGACY, low-traffic, matches original Phase 2 scope | Design decision needed before migration (see Section 3) |
| `asset.is_portfolio` (publication-cohort sense) | `asset` table | `held_market_coverage_v1.py`, `canonical_fib_zone_map_v1.py`, health checks | `run_held_market_enrollment_v1.py` | high (gates Fib zone map publication) | No | market_data | ACTIVE, load-bearing, not part of original Phase 2 scope | None — correctly account-agnostic where it lives; possible future rename to disambiguate from legacy sense |
| `asset.quote_asset` / `quote_currency` | `venue_market.quote_currency` for market_data/reporting; `asset.quote_asset` fallback in ~5 research runners | market_data, reporting, research (fallback) | `run_bitvavo_market_sync_v1.py` (venue_market) | medium | No | market_data/reporting/research | MOSTLY_MIGRATED; narrow legacy tail in research | Mechanical follow-up: switch research fallback to venue_market-only, then drop column (not filed here) |
| `asset.is_tradeable` | `asset` table for selection_engine/advice/regime/zone/research; `venue_market.is_tradeable` for market_sync writes and account_wallet_dashboard reads | selection, advice, regime, zone, research (asset); reporting (mixed) | `run_bitvavo_market_sync_v1.py` (venue_market); manual/migration (asset) | high (selection eligibility) | No (asset-table path is account-agnostic) | selection/advice/regime/zone/research/market_data | LARGELY_UNMIGRATED; original design premise still current | Requires selection_engine venue-context design decision before mechanical migration (not filed here) |
| `venue_market` | itself | market_data, reporting, account | `run_bitvavo_market_sync_v1.py`, `run_account_wallet_refresh_v1.py` | high | No | market_data | ACTIVE, Phase 1 skeleton, production-applied | None pending |
| `account_asset` | itself | account, reporting (account-scoped) | `run_account_wallet_refresh_v1.py`, `account_asset_settings_v1.py` | high | Yes | account/reporting | ACTIVE, Phase 1 skeleton, production-applied (drift for 3 settings columns tracked separately by #333) | None pending in this scope |
| `trading_account_id` | `trading_account` table | account, reporting, decision_gate (partial), execution_planner (partial) | account/onboarding runners | high | Yes | account/decision_gate/reporting | ACTIVE, canonical account FK per backlog policy | Continue preferring over bare `account_id` (see #319) |
| `account_code` | `trading_account.account_code` | account/reporting resolvers (`_resolve_trading_account`, `--account-profile`) | onboarding/admin only | high | Yes | account | ACTIVE, canonical human-facing identifier | None pending |

## 9. Architecture boundary audit

```text
ARCHITECTURE_BOUNDARY_VIOLATIONS=0
SELECTION_ACCOUNT_AWARENESS_VIOLATIONS=0
DECISION_GATE_BOUNDARY_VIOLATIONS=0
EXECUTION_PLANNER_BOUNDARY_VIOLATIONS=0
EXECUTOR_BOUNDARY_VIOLATIONS=0
REPORTING_AUTHORITY_VIOLATIONS=0
```

`src/selection/run_selection_engine_v2.py` has zero `account_asset`/
`venue_market` references (grep-confirmed, Section 5). `src/decision_gate/`,
`src/execution_planner/`, `src/executor/` have zero `account_asset`/
`venue_market` references (grep-confirmed). `quote_asset` appears in
`decision_gate`/`execution_planner` only as a field on their own
request/approval records (market-pair identification for an already-approved,
account-aware execution flow), not as a coupling to the `asset` table or an
account-agnostic-layer violation. `reporting` (`account_wallet_dashboard_v1.py`,
`account_scoped_short_trader_dashboard_v1.py`) reads `account_asset`/
`venue_market`/`asset` for account-scoped **display only**; no evidence of
mutation, order calls, or decision logic in these files' matched lines.

## 10. Backlog / R2 determination

`docs/todo/multi_account_asset_foundation_backlog.md` Phase 2/3/4 items and
Phase 5.3/5.4 were all marked `[ ]` (not done) pending "a fresh
architecture/call-site review against current `main`" — this document is
that review.

Findings:
- Phase 2: superseded by an unplanned semantic split (legacy vs.
  publication-cohort). Requires a design decision (disambiguate the two
  semantics), not mechanical migration. **Not executable now** — genuine
  unresolved prerequisite.
- Phase 3: mostly already migrated for dominant consumers; the remaining
  tail (5 named research runners, documented fallback pattern, no
  dependency, no outstanding design question) is **currently executable,
  unowned scope** now that this fresh review has been performed. Counted.
- Phase 4: real gap, but the first step (selection_engine venue-context
  design) is an unresolved architecture question, not mechanical migration.
  **Not executable now** — genuine unresolved prerequisite.
- Phase 5.1/5.2/5.4: done, no executable gap. Phase 5.3: a bounded
  read-only DB verification check (no dependency, no design question) is
  **currently executable, unowned scope**. Counted.

**Program-review correction (2026-08-09):** the initial version of this
audit asserted `BACKLOG_UNMIGRATED_EXECUTABLE_SCOPE_COUNT=0` /
`R2_AFTER=PASS` while simultaneously describing the Phase 3 tail and Phase
5.3 verification as "close to executable" / "mechanical" / "Issue-ready" —
internally inconsistent. Applying the audit's own rule consistently
("future ideas, contingent migrations, design questions... do NOT count as
unmigrated executable scope" — but bounded, dependency-free, mechanical
work does count): Phase 3's tail and Phase 5.3's verification have no
unresolved design prerequisite and are ready to be filed and executed by a
future task. Phase 2 and Phase 4 do have a genuine unresolved prerequisite
(a naming/semantics decision and a selection_engine venue-context design
decision, respectively) and correctly remain excluded.

```text
BACKLOG_UNMIGRATED_EXECUTABLE_SCOPE_COUNT=2
  1. Phase 3 tail: migrate remaining asset.quote_asset research-runner
     fallbacks to venue_market-only (5 named files, no dependency)
  2. Phase 5.3: verify Hugo open-order discovery freshness
     (bounded read-only DB check, no dependency)
BACKLOG_PARTIAL_ISSUE_OWNERSHIP=Issue #319 owns decision_gate/execution_planner account-identifier fragmentation (overlaps none of Phase 2-4; tangential to Phase 5.3 verification only); Issue #333 owns account_asset settings-column production drift (out of Phase 2-5 scope by design)
R2_BEFORE=FAIL
R2_AFTER=FAIL
```

## 11. Proposed future Issue decomposition (not created)

For a later filing round, once the noted design questions are resolved:

1. **"Disambiguate asset.is_portfolio legacy-watchlist vs. publication-cohort
   semantics"** — owning layer: market_data (design) + research (legacy
   caller). Dependency: none blocking; should land before any Phase 2
   `account_asset` migration Issue. Actionable once: a naming/split decision
   is made (e.g., keep `is_portfolio` for the account-agnostic cohort,
   introduce a distinctly-named per-account flag in `account_asset`, migrate
   only the 3 legacy research refs). Non-goals: do not touch
   `held_market_coverage_v1.py`/`canonical_fib_zone_map_v1.py` semantics.
   Does not overlap #319 or #333.

2. **"Migrate remaining asset.quote_asset research-runner fallbacks to
   venue_market"** (counted in `BACKLOG_UNMIGRATED_EXECUTABLE_SCOPE_COUNT`,
   item 1) — owning layer: research. Dependency: none. Actionable:
   yes, mechanical (~4-5 files:
   `run_fibo_target_map_v1.py`, `run_multi_horizon_fib_backtest_v1.py`,
   `run_fib_leg_pair_observation_preview_v1.py`,
   `run_canonical_fib_zone_map_writer_preview_v1.py`,
   `run_kite_watchlist_candidate_check_v1.py`), each already has the
   `venue_market`/`quote_currency` fallback path — remove the `asset.quote_asset`
   branch once confirmed unused. Non-goals: no `asset` column drop in the
   same Issue (drop is a separate, later, verified step). Does not overlap
   #319 or #333.

3. **"Design selection_engine venue-context threading (Phase 4 prerequisite)"**
   — owning layer: selection_engine (architecture design). Dependency: must
   resolve before any `is_tradeable` call-site migration Issue is filed.
   Actionable as a design/RFC task, not a code-change task. Non-goals: no
   selection_engine account-awareness of any kind; must preserve
   account-agnostic hard boundary. Does not overlap #319 (different layer)
   or #333.

4. **"Verify Hugo open-order discovery freshness (Phase 5.3)"** (counted in
   `BACKLOG_UNMIGRATED_EXECUTABLE_SCOPE_COUNT`, item 2) — owning
   layer: account (read-only verification). Dependency: none. Actionable:
   yes, bounded read-only DB check (count `account_asset` rows
   `source=OPEN_ORDER_DISCOVERY` for `trading_account_id=4` vs. live Bitvavo
   open orders for Hugo's account); if a gap is found, re-run the existing
   `run_account_wallet_refresh_v1.py` runner for Hugo's profile (no new code).
   Non-goals: no schema change, no new runner. Does not overlap #319 or
   #333.

```text
FOLLOWUP_ISSUES_CREATED=0
```

## 12. Remaining blockers

- No production/DB access was used in this audit; Phase 5.3's Hugo-specific
  open-order freshness and Phase 5.1/5.2's current row counts rest on the
  2026-08-09 Phase 1 reality audit's live evidence, not re-verified here.
  Filing/executing the Phase 5.3 verification Issue (Section 10, item 2)
  requires a DB-authorized task; that is an execution-permission
  prerequisite, not a design/uncertainty prerequisite, and does not remove
  it from the executable-scope count.
- Phase 2 and Phase 4 both require a design decision before any mechanical
  migration Issue can be filed (see Sections 3, 5, 11) — these remain
  correctly excluded from the executable-scope count.
- Phase 3's tail (Section 10, item 1) and Phase 5.3's verification
  (Section 10, item 2) are executable, unowned scope; per task instruction
  no Issue is filed for either in this audit.
- Issue #333 (account_asset settings-column drift) remains open and
  unrelated to this audit's findings, as instructed.

## 13. Evidence / commands / tests used

```bash
git fetch origin main
git rev-parse origin/main   # d82f7a95ecf94d6153e0c79102b61ea7f9fee21e
git checkout -b docs/multi-account-phase-2-5-current-state-audit-v1 origin/main
gh issue view 319 --json title,body,state,labels,comments
gh issue view 333 --json title,body,state,labels,comments
gh issue view 294 --json title,state
grep -rn "is_portfolio" --include="*.py" src/ tests/ scripts/ apps/
grep -rn "is_tradeable" --include="*.py" src/
grep -rn "quote_asset\b" --include="*.py" src/
grep -rln "quote_currency" --include="*.py" src/*
grep -rln "account_asset" --include="*.py" src/
grep -rln "venue_market" --include="*.py" src/
grep -rn "account_id\b" --include="*.py" src/decision_gate/ src/execution_planner/
grep -rn "trading_account_id\s*=\s*[0-9]" --include="*.py" src/   # 0 hard-coded IDs found
python -m pytest tests/test_account_asset_settings_v1.py \
  tests/test_account_market_scope_v1.py \
  tests/test_account_scope_contract_v1.py \
  tests/test_account_wallet_refresh_v1.py \
  tests/test_bitvavo_market_sync_v1.py \
  tests/test_held_market_coverage_v1.py -q
# 109 passed
```

```text
production_db_access_used=0
production_mutation=0
broker_writes=0
order_submission=0
github_issues_created=0
github_issues_modified=0
code_changes=0
schema_changes=0
```
