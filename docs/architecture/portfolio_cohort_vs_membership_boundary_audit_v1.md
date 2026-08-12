# Portfolio Cohort vs. Portfolio Membership — Boundary Audit v1

Audit-only design pass. **No runtime, schema, or code changes are made or
proposed for this pass.** Base: `main` @ `a788bbfd`.

```text
broker_private_calls=0
broker_writes=0
order_submission=0
db_writes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
selection_engine_changes=0
```

---

## 0. Headline finding

Two genuinely different concepts share one name and, today, one column.

1. **`asset.is_portfolio`** is *not* portfolio membership. In every live
   consumer on `main` it is the **global market publication cohort selector** —
   the flag that decides which symbols the canonical 4h Fib writer publishes
   context for. It is account-agnostic by design and by ownership
   (`docs/ops/held_market_enrollment_v1.md` states this explicitly: "market-wide,
   not per-account").
2. **`account_asset.is_portfolio_member`** is the intended per-account
   portfolio-focus flag. It exists in schema and in production
   (`account_asset`: 86 rows per Issue #294 verification) but is **dead**: no
   code path writes it to anything but the literal `0`, and no code path reads
   its value.

The two are already leaking into each other at exactly one place — the
reporting layer — and that leak is currently the only thing a human ever sees:

```text
asset.is_portfolio (global cohort)
  -> account_scoped_short_trader_dashboard_v1._fetch_selected_asset_market_rows()
  -> inclusion reason "PORTFOLIO_MARKER"
  -> run_manual_short_trader_profit_plan_v1.portfolio_asset_markets
  -> ProfitPlan card badge "PORTFOLIO ASSET"
```

A global, account-agnostic publication flag is rendered to the operator as a
per-account portfolio statement. With one account this is invisible. With
Hugo onboarded it is a **cross-account semantic leak**: Hugo's cockpit would
show "PORTFOLIO ASSET" for Joost's cohort, and enrolling one account's holding
(held-market enrollment, Issue #238) would change the other account's badges.

Two secondary findings, both material to sequencing:

- **The canonical design doc is materially wrong.**
  `docs/research/multi_account_asset_foundation_v1.md` claims `is_portfolio`
  has **"3 refs, all in watchlist candidate research code"** and is the
  **"lowest risk, safe to do early"** migration. On `main` it has consumers in
  `market_data` (the canonical Fib cohort query), `market` (Bitvavo sync),
  `reporting` (two dashboards), plus the whole held-market enrollment writer
  chain and an Odroid orchestrator phase. `docs/todo/multi_account_asset_foundation_backlog.md`
  Phase 2.2 instructs `ALTER TABLE asset DROP COLUMN is_portfolio` after
  "3 refs" are switched. **Executing that backlog as written would silently
  empty the canonical Fib publication cohort.** This stale instruction is the
  single highest-risk artifact found in this audit.
- **`selection_engine` is clean.** No `is_portfolio` reference exists in
  `src/selection*`, `src/decision_gate`, `src/execution_planner`,
  `src/executor`, `src/advice`, `src/signal_engine`, or
  `src/trade_setup_filter`. The market-only/account-agnostic boundary is
  currently intact and this work must not disturb it.

---

## 1. Canonical terminology

Adopt these three names. They are distinct, non-overlapping, and none of them
is called "portfolio" alone.

| Canonical term | Meaning | Scope | Proposed field |
|---|---|---|---|
| **Publication cohort** | The global set of symbols for which the system publishes canonical market context (4h Fib map, zone context, dashboards' market layer). Answers: *does the market layer compute and publish for this symbol?* | Global, account-agnostic, venue-scoped | `asset.is_publication_cohort` (renamed from `is_portfolio`) |
| **Core sensor** | Global market-structure reference symbols always in the cohort regardless of any holding (BTC, ETH, …). Existing, unchanged. | Global, account-agnostic | `asset.is_core_sensor` (unchanged) |
| **Account portfolio membership** | An account operator's declared strategic/rotation focus set. Answers: *does this account's operator consider this a portfolio position rather than incidental dust?* Independent of current balance. | Per `(trading_account_id, venue_market_id)` | `account_asset.is_portfolio_member` (exists, dead) |

Supporting display vocabulary (already partially in use, keep and formalize):

| Display term | Backed by | Not backed by |
|---|---|---|
| `WALLET HELD` | positive balance in `trading_account_balance_snapshot` | any flag |
| `PORTFOLIO ASSET` | `account_asset.is_portfolio_member` (**target**; today wrongly `asset.is_portfolio`) | cohort membership |
| `MARKET SELECTED` / `CORE SENSOR` | `asset.is_publication_cohort` / `is_core_sensor` | account state |

Retire the bare words "portfolio flag", "portfolio universe", and
"portfolio focus set" from docs and code comments; each is ambiguous across the
two concepts.

Cohort inclusion reason vocabulary (reporting-internal, keep stable codes):

```text
POSITION_HELD      account overlay  (balance > 0)
OPEN_ORDER         account overlay  (open order exists)
PORTFOLIO_MEMBER   account overlay  (account_asset.is_portfolio_member)   <- new
COHORT_PUBLISHED   market layer     (asset.is_publication_cohort)         <- renamed from PORTFOLIO_MARKER
CORE_SENSOR        market layer     (asset.is_core_sensor)
```

`PORTFOLIO_MARKER` is the name that encodes the current confusion and must not
survive the migration.

---

## 2. Ownership per field / concept

| Field / concept | Owning layer | Sole writer | Readers (verified on `main`) |
|---|---|---|---|
| `asset.is_portfolio` → `is_publication_cohort` | `market_data` (market-only) | `src/market_data/run_held_market_enrollment_v1.py` (0→1 only, guarded); `src/market/run_bitvavo_market_sync_v1.py` seeds new rows to `0` and never mutates existing | `src/market_data/canonical_fib_zone_map_v1.py:571` (`fetch_tracked_symbols`); `src/reporting/account_scoped_short_trader_dashboard_v1.py:363,373`; `src/market_data/held_market_coverage_v1.py`; `run_held_market_coverage_health_check_v1.py` |
| `asset.is_core_sensor` | `market_data` | manual / migration | same cohort consumers |
| `account_asset.is_portfolio_member` | `account` | **none today** (`run_account_wallet_refresh_v1.py:166` and `account_asset_settings_v1.py` insert literal `0`; no `ALLOWED_ACTIONS` entry mutates it) | **none today** (`account_asset_settings_v1.py:433` selects the column but no consumer uses the value) |
| `account_asset.is_visible / is_candidate_enabled / is_order_proposal_enabled / is_hidden` | `account` | `src/account/account_asset_settings_v1.py` (operator actions) | `account_scoped_short_trader_dashboard_v1` (`AccountPlanPolicy`) |
| `portfolio_asset_markets` (reporting alias) | `reporting` (display only) | `run_manual_short_trader_profit_plan_v1.py:1818` | `manual_short_trader_profit_plan_v1.apply_portfolio_account_evidence` → `is_portfolio_asset` → `PORTFOLIO ASSET` badge |
| Held-market enrollment | Odroid linked-profile runtime orchestrator | `scripts/odroid/run_held_market_enrollment_once.sh` | — |
| Canonical 4h Fib publication | gurkdb `synth-chain-4h.timer` | `run_canonical_fib_zone_map_v1 --publish` | — |

Ownership rules to make explicit (currently implicit):

- The **publication cohort is written only by the market layer** and read by
  market + reporting. No account-layer writer may ever set it.
- **Account portfolio membership is written only by the account layer**
  (operator action or account-scoped discovery) and read only by
  account-scoped reporting. It must never enter a market-layer query.
- Held-market enrollment is the one legitimate *account-observation →
  market-cohort* edge. It is safe **only because it is a union across all
  linked accounts and is monotonic (0→1)**: no single account can remove
  another account's symbol from the cohort. That property is a load-bearing
  invariant and must be stated in the doc, not left as an accident.

---

## 3. Target architecture

```text
                       GLOBAL MARKET LAYER (account-agnostic)
  asset.is_publication_cohort ─┬─> canonical_fib_zone_map.fetch_tracked_symbols()
  asset.is_core_sensor        ─┘        -> canonical 4h publication
                               └─> reporting market layer ("MARKET SELECTED")

        ▲ (monotonic 0→1 union across all linked accounts; never per-account)
        │
  held-market enrollment  <── union of positive holdings, all linked accounts


                       PER-ACCOUNT LAYER
  account_asset(trading_account_id, venue_market_id)
      .is_portfolio_member      -> "PORTFOLIO ASSET" badge, account-scoped
      .is_visible/.is_hidden/…  -> AccountPlanPolicy (existing)
        ▲                                     │
        │ operator action                     ▼
  account_asset_settings_v1            account-scoped reporting only
```

Invariants of the target state:

1. `selection_engine`, `trade_setup_filter`, `signal_engine`, `advice`,
   `decision_gate`, `execution_planner`, `executor` read **neither** field.
   (Currently true for `is_portfolio`; must stay true.)
2. Every read of `is_portfolio_member` carries a `trading_account_id`
   predicate. No query may read it without one.
3. The publication cohort query never joins `account_asset` and never takes a
   `trading_account_id` parameter.
4. Reporting composes the two as **independent overlays** on one card; it never
   derives one from the other. Four states are all legal and must render
   distinctly: cohort-only, member-only, both, neither.
5. Historical rebuilds never use current cohort flags as historical truth —
   already correctly implemented and documented at
   `canonical_fib_zone_map_v1.py:810-834`; preserve verbatim.

The two concepts converge nowhere except the operator's screen.

---

## 4. Migration sequence

Six steps, each independently revertible. Steps 1–2 are documentation and
carry no runtime risk; the ordering after that is chosen so that *nothing is
renamed until the thing that would break has a second, verified source*.

| Step | Work | Risk | Reversible by |
|---|---|---|---|
| **S0** | Neutralize the stale drop instruction: correct `docs/research/multi_account_asset_foundation_v1.md` ("3 refs") and `docs/todo/multi_account_asset_foundation_backlog.md` Phase 2.2 (`DROP COLUMN is_portfolio`). Record the true consumer inventory. | none | doc revert |
| **S1** | Publish this terminology + ownership contract as canonical; register the display vocabulary. | none | doc revert |
| **S2** | Give `is_portfolio_member` a writer and an operator action (`set_portfolio_member` / `clear_portfolio_member` in `ALLOWED_ACTIONS`), plus a one-time per-account backfill seeded from that account's own positive holdings — **not** from `asset.is_portfolio`. | low (additive, account layer only) | set column back to 0 |
| **S3** | Repoint reporting: `portfolio_asset_markets` reads `account_asset.is_portfolio_member` for the rendered `trading_account_id`. Split the cohort signal into its own display state (`COHORT_PUBLISHED` → "MARKET SELECTED"). `PORTFOLIO ASSET` becomes per-account. | medium (visible badge change) | revert reporting commit |
| **S4** | Rename `PORTFOLIO_MARKER` → `COHORT_PUBLISHED` across reporting + tests; remove the "portfolio" wording from all cohort-side comments/docs. | low | revert |
| **S5** | Rename the column `asset.is_portfolio` → `asset.is_publication_cohort` (add + dual-read + backfill + cutover + drop, as its own sequenced migration with separate production authorization). | medium-high (touches the Fib writer's cohort query) | keep both columns in sync during dual-read window |

`asset.is_portfolio` is **never dropped** — only renamed. The concept it holds
is real and still needed; it was only ever misnamed.

Deliberately excluded from the sequence: any change to held-market enrollment
behavior, the chain-4h timer, or the orchestrator cadence. S5 touches the
enrollment writer's column name only, and only after S0–S4 have removed every
ambiguity about what the column means.

---

## 5. Explicit non-goals

- **Do not merge the two concepts.** Not into one column, one view, one alias,
  or one badge.
- **Do not make the publication cohort per-account.** It must stay
  account-agnostic; the canonical 4h writer runs once for the market, not once
  per account.
- **Do not make `selection_engine` (or `trade_setup_filter`, `signal_engine`,
  `advice`) read either field.** Neither cohort nor membership may become
  candidate-eligibility input in this work.
- **Do not drop `asset.is_portfolio`.** Rename only.
- **Do not derive `is_portfolio_member` from `asset.is_portfolio`** in the S2
  backfill. That would bake today's conflation into per-account data
  permanently and make Joost's cohort Hugo's portfolio.
- No `decision_gate` / `execution_planner` / `executor` changes.
- No broker calls, order creation, or live-permission changes.
- No change to `is_tradeable` or `quote_asset` migrations (owned by #342 and
  the venue_market phases).
- No production migration applied without separate explicit authorization.
- No changes in this audit pass at all beyond this document.

---

## 6. Risk / breakage analysis

| # | Risk | Severity | Trigger | Mitigation |
|---|---|---|---|---|
| R1 | **Executing backlog Phase 2.2 as written** drops `asset.is_portfolio`; `fetch_tracked_symbols()` returns core sensors only; canonical 4h publication cohort silently collapses; every non-core symbol degrades to `CANONICAL_4H_MAP_STATUS_UNAVAILABLE` / `FIB_MAP_SYMBOL_MISSING`. | **Critical** | anyone picking up the frozen backlog | S0 first, before any other step |
| R2 | Cross-account badge leak: `PORTFOLIO ASSET` derived from a global flag renders identically in every account's cockpit. | High (on Hugo onboarding) | S2/S3 not done before second account goes live | S3; Hugo onboarding (#343, Phase 5) should not complete without it |
| R3 | Backfilling `is_portfolio_member` from `asset.is_portfolio` — the exact instruction in backlog Phase 1.3 — permanently encodes the conflation per account. | High | S2 executed from the stale backlog | S0 corrects the instruction; S2 seeds from per-account holdings |
| R4 | Renaming the column (S5) while the Fib writer, enrollment writer, health check, and two dashboards read it: a missed call site fails **open** (empty cohort) rather than loudly. | Medium-high | S5 without dual-read | dual-read window + cohort row-count assertion before/after |
| R5 | Operator confusion during S3: a symbol currently badged `PORTFOLIO ASSET` (because it is in the cohort) loses the badge if the operator has not declared membership. | Medium | S3 ships without the S2 backfill | ship S2 backfill first; S3 shows `MARKET SELECTED` so nothing disappears silently |
| R6 | Held-market enrollment's account→market edge gets "fixed" into a per-account write by someone applying the per-account rule mechanically, breaking the cohort for other accounts. | Medium | future refactor | state the union/monotonic invariant explicitly (S1) |
| R7 | `is_portfolio_member` gets a reader before it has a writer, so every account renders zero portfolio assets. | Medium | S3 before S2 | strict S2→S3 ordering |
| R8 | Production drift: `account_asset` on gurkdb is already missing three columns the code depends on (#333). A migration adding a member-write path may hit an unexpected live schema. | Medium | S2 apply | re-verify live schema at apply time; #333 is a soft prerequisite for S2 |
| R9 | Historical Fib rebuilds start using cohort flags as historical truth. | Medium | careless S5 edit | preserve the existing guard at `canonical_fib_zone_map_v1.py:810-834` verbatim |
| R10 | `run_bitvavo_market_sync_v1.py` sets `is_portfolio=0` by column name for new assets; a rename breaks new-asset seeding silently (it is a name-matched dict branch, no error on miss). | Low-medium | S5 | include in S5 call-site inventory; assert seeded value post-rename |

Existing-issue overlap (all resolvable, none blocking):

- **#238** (held-market enrollment) — owns the cohort writer. This work renames
  its target column at S5; no behavioral overlap.
- **#333** (account_asset settings drift) — soft prerequisite for S2.
- **#342** (quote_asset Phase 3) — disjoint field, same doc lineage; both
  depend on S0 correcting the shared design doc's ref counts.
- **#343** (Hugo open-order discovery, Phase 5.3) — R2 becomes live-visible
  here; S3 should land first.
- **#319** (account_id vs trading_account_id) — adjacent, not overlapping;
  S3's per-account query depends on `trading_account_id` being unambiguous in
  reporting, which it already is.
- **#280** (multi-user cockpit access) — consumes the per-account boundary this
  work establishes; no field overlap.
- **#294** (closed, Phase 1 skeleton) — created the `account_asset` column that
  is dead today.

---

## 7. Decomposed GitHub issues

Draft only — not created. Six issues, ordered.

### Issue A — Correct the multi-account asset foundation docs and record the true `is_portfolio` consumer inventory

Architecture owner: `architecture/data-foundation`. Depends on: none.

Documentation-only. Fixes the stale "3 refs, lowest risk" claim and the
`DROP COLUMN is_portfolio` instruction that would collapse the canonical Fib
publication cohort.

Acceptance criteria:
- [ ] `docs/research/multi_account_asset_foundation_v1.md` `is_portfolio` row states the real consumer set (`market_data` cohort query, `market` sync, two reporting surfaces, enrollment writer + health check) and removes "3 refs" / "lowest risk, safe to do early".
- [ ] `docs/todo/multi_account_asset_foundation_backlog.md` Phase 2.2 (`ALTER TABLE asset DROP COLUMN is_portfolio`) is corrected to a rename path and Phase 1.3's "`is_portfolio_member` from `asset.is_portfolio`" backfill instruction is withdrawn, each pointing at the owning Issue. (Edit permitted under the frozen-TODO rule: correcting materially false, unsafe information + pointing at an owning Issue.)
- [ ] This audit doc is linked as canonical from both.
- [ ] `git diff --check` clean. No code, schema, or runtime change.

### Issue B — Publish canonical publication-cohort vs. account-membership terminology and ownership contract

Architecture owner: `architecture/data-foundation`. Depends on: A.

Acceptance criteria:
- [ ] Canonical doc defines `publication cohort`, `core sensor`, `account portfolio membership` with owning layer and sole writer for each.
- [ ] Held-market enrollment's union/monotonic (0→1, all linked accounts) invariant is stated explicitly as load-bearing, with the reason.
- [ ] Rule recorded: no account-layer writer may set the cohort; no market-layer query may read `account_asset`; every `is_portfolio_member` read carries a `trading_account_id` predicate.
- [ ] Rule recorded: `selection_engine`/`trade_setup_filter`/`signal_engine`/`advice`/`decision_gate`/`execution_planner`/`executor` read neither field.
- [ ] Display vocabulary registered (`WALLET HELD`, `PORTFOLIO ASSET`, `MARKET SELECTED`, `CORE SENSOR`) with its backing field.
- [ ] `docs/ops/held_market_enrollment_v1.md` and `docs/asset_flag_policy.md` (currently 14 lines, truncated mid-sentence — repair in scope) reference the contract.

### Issue C — Give `account_asset.is_portfolio_member` a writer, an operator action, and a per-account backfill

Architecture owner: `architecture/data-foundation` + `account`. Depends on: B. Soft prerequisite: #333.

Acceptance criteria:
- [ ] `set_portfolio_member` / `clear_portfolio_member` added to `ALLOWED_ACTIONS` in `src/account/account_asset_settings_v1.py`, scoped to one `(trading_account_id, venue_market_id)` per call.
- [ ] Backfill seeds membership from **that account's own** positive holdings only; it must not read `asset.is_portfolio`. A test asserts the backfill query contains no `asset.is_portfolio` reference.
- [ ] Test: an action on account A leaves account B's rows byte-identical.
- [ ] Live `account_asset` schema re-verified read-only before any apply; no production apply without separate explicit authorization.
- [ ] `broker_writes=0`, `order_submission=0`, no `decision_gate`/`execution_planner`/`executor` change.

### Issue D — Repoint the Profit Plan `PORTFOLIO ASSET` badge to per-account membership and split out the cohort signal

Architecture owner: `reporting`. Depends on: C.

Acceptance criteria:
- [ ] `portfolio_asset_markets` in `run_manual_short_trader_profit_plan_v1.py` is built from `account_asset.is_portfolio_member` for the rendered `trading_account_id`.
- [ ] Cohort membership renders as its own state (`MARKET SELECTED` / `CORE SENSOR`), never as `PORTFOLIO ASSET`.
- [ ] All four combinations (cohort-only, member-only, both, neither) render distinctly; covered in `tests/test_profit_plan_wallet_portfolio_terminology_v1.py`.
- [ ] Membership stays independent of balance: zero-balance member keeps `PORTFOLIO ASSET`, never claims `WALLET HELD` (existing test must still pass unchanged in intent).
- [ ] Test: rendering account A never reads account B's membership rows.
- [ ] Reporting stays read-only; no decision or order semantics introduced.

### Issue E — Rename the `PORTFOLIO_MARKER` inclusion reason to `COHORT_PUBLISHED`

Architecture owner: `reporting`. Depends on: D.

Acceptance criteria:
- [ ] `PORTFOLIO_MARKER` replaced by `COHORT_PUBLISHED` in `account_scoped_short_trader_dashboard_v1.py`, `run_manual_short_trader_profit_plan_v1.py`, and tests.
- [ ] No occurrence of the word "portfolio" remains on the cohort side of reporting (code, comments, or docstrings).
- [ ] Operator-visible labels unchanged by this issue (pure internal rename after D).

### Issue F — Rename `asset.is_portfolio` to `asset.is_publication_cohort` (sequenced, dual-read)

Architecture owner: `architecture/data-foundation` + `market_data`. Depends on: E.

Acceptance criteria:
- [ ] Complete call-site inventory verified before edit, explicitly including `run_bitvavo_market_sync_v1.py`'s name-matched `is_portfolio` branch (fails silently on a miss).
- [ ] Additive column + dual-read + backfill + cutover + drop, as separate steps; no single-step rename.
- [ ] Cohort row count from `fetch_tracked_symbols()` asserted identical before and after cutover, per venue/quote pair.
- [ ] Historical-rebuild guard (`canonical_fib_zone_map_v1.py`, "must never be used to decide which symbols an old publication should have contained") preserved verbatim.
- [ ] Held-market enrollment remains monotonic 0→1 and account-agnostic; enrollment + publication health checks pass unchanged.
- [ ] No production migration applied without separate explicit authorization.
- [ ] `selection_engine` untouched; `market_ranking_changes=0`, `broker_writes=0`, `order_submission=0`.

---

## 8. Recommendation: implement first

**Issue A.**

It is documentation-only, zero-risk, and it defuses the one Critical finding
(R1): two checked-in documents currently instruct a future agent to
`DROP COLUMN is_portfolio` after switching "3 refs" and to backfill per-account
membership *from the global cohort flag*. Both instructions are wrong, both are
in the frozen backlog where they read as ready-to-execute, and either one
executed alone causes damage that is not visible until the next chain-4h cycle
(cohort collapse) or not visible at all (permanent per-account data
conflation).

Every other issue here is safer to attempt after A, and no other issue removes
that hazard. Issue B should follow immediately, since C–F are all
implementations of the contract B defines.

If a second account is being onboarded on any near-term schedule (#343),
C and D become time-critical: R2 turns from a naming problem into an operator
seeing another account's portfolio.
