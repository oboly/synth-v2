# Multi-Account Asset Foundation Backlog

## GitHub Issue migration

Status: reality-corrected 2026-08-09 (see `docs/development/multi_account_asset_foundation_phase_1_reality_audit_v1.md`)

Operational status/priority is owned by GitHub Issues.

Section ownership:
- Phase 1 — Skeleton -> Issue #294. **Already implemented and production-applied
  before Issue #294 was created** (repo lineage commit `098f338a`, live-verified
  on gurkdb 2026-08-09: `venue_market`=430 rows, `account_asset`=86 rows, zero
  duplicate identities, zero orphaned FKs). Issue #294's own text was written
  from stale TODO state and contains a factual error: it names
  `trading_account_id=1` as Joost's account. Live verification shows Joost is
  `trading_account_id=3` (`bitvavo_joost_read`); `trading_account_id=1` is
  `paper_sell_only_preview`. No remaining executable Phase 1 scope.
- Phase 2 — `is_portfolio` migration -> the fresh architecture/call-site
  review required below has been done; see
  `docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md`
  (canonical). **Do not reuse the original "3 refs, watchlist-only" claim from
  `docs/research/multi_account_asset_foundation_v1.md` — it is stale and
  materially wrong.** `asset.is_portfolio` is the global, account-agnostic
  publication cohort selector consumed by the canonical Fib cohort query,
  Bitvavo sync, two reporting dashboards, and the held-market enrollment
  chain. The corrected Phase 2 sequence is now tracked by Issues #371–#375.
- Phase 3 — `quote_asset` migration -> no Issue yet; same fresh-review
  requirement as Phase 2. Do not reuse the original 12-ref count without
  re-auditing.
- Phase 4 — `is_tradeable` migration -> no Issue yet; same fresh-review
  requirement as Phase 2. Do not reuse the original 19-ref count without
  re-auditing.
- Phase 5 — Hugo account onboarding -> **partially superseded**. Hugo already
  exists as `trading_account_id=4` (`hugo-bitvavo`) with 27 live
  `account_asset` rows (`WALLET_DISCOVERY` source), i.e. items 5.1 and 5.2
  below already happened outside this backlog's original sequencing. Item 5.3
  (open-order discovery for Hugo) and 5.4 (dashboard account-scope filter
  audit) have not been independently re-verified and are not claimed complete
  here — a fresh review is required before treating Phase 5 as fully done.
- Account table FK policy -> already stated as canonical policy in this file;
  no separate Issue required.
- Separately, a production schema drift **unrelated to Phase 1** was found
  during the #294 investigation: `db/migrations/20260603_account_asset_settings_v1.sql`
  (commit `08f66335`, adds `disabled_reason`/`first_seen_at_utc`/`last_seen_at_utc`
  to `account_asset`) has not been applied to live gurkdb, even though
  `src/account/account_asset_settings_v1.py` already depends on those columns.
  Tracked separately as Issue #333. Not part of Phase 1-5 scope.

Unmigrated executable scope:
- none for Phase 1 (already implemented and production-applied).
- Phase 2 (`is_portfolio`, rename-only — never a drop; see corrected Phase 2
  section below and the canonical audit), Phases 3-4 (`quote_asset` /
  `is_tradeable` column drops), and the remainder of Phase 5 (items 5.3-5.4)
  remain contingent future work. Phase 2's fresh review is done (see the
  canonical audit); Phases 3-4 and Phase 5 items 5.3-5.4 still require one
  (old ref counts predate substantial repo evolution and are not
  authoritative) before a follow-up Issue is filed. See the Phase 2-5 review
  gate below.

Design doc: `docs/research/multi_account_asset_foundation_v1.md` (its
`is_portfolio` sections are superseded — see that doc's correction notice)

Reality audit: `docs/development/multi_account_asset_foundation_phase_1_reality_audit_v1.md`

Canonical `is_portfolio` boundary audit (supersedes the design doc's
`is_portfolio` claims; source of truth for Phase 2):
`docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md`

---

## Phase 1 — Skeleton (IMPLEMENTED, PRODUCTION-APPLIED)

- [x] **1.1** Migration `20260603_multi_account_asset_foundation_v1.sql`
      applied. `venue_market` and `account_asset` exist live on gurkdb.
      Additive only, no asset column drops. (repo: commit `098f338a`)

- [x] **1.2** `venue_market` backfilled from `asset`/Bitvavo market data via
      `src/market/run_bitvavo_market_sync_v1.py`. Live: 430 rows, all
      `venue='bitvavo'`, all `quote_currency='EUR'`, 0 duplicate
      `(venue, market)`, 0 orphaned `base_asset_id`.

- [x] **1.3** `account_asset` backfilled via
      `src/account/run_account_wallet_refresh_v1.py`. Live: 86 rows across 4
      trading accounts, sources `WALLET_DISCOVERY`=78, `MANUAL_ADD`=6,
      `OPEN_ORDER_DISCOVERY`=2, 0 duplicate `(trading_account_id, venue_market_id)`,
      0 orphaned FKs. Joost (`trading_account_id=3`) holds 57 rows.

---

## Phase 2 — `is_portfolio` migration (superseded plan — see below)

**The original "low risk, 3 refs" framing and the steps that were here are
withdrawn.** They instructed switching a handful of `src/research/` refs to
`account_asset.is_portfolio_member` and then dropping `asset.is_portfolio`.
Executing that as written would silently empty the canonical Fib publication
cohort, because `asset.is_portfolio` is the global publication cohort
selector, not per-account watchlist membership, and has real consumers in
`market_data`, `market`, `reporting`, and the held-market enrollment chain —
see the correction notice in `docs/research/multi_account_asset_foundation_v1.md`
and the full inventory in
`docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md`.

The corrected, sequenced plan (owner: that audit, §4 and §7 Issues B-F) is
tracked by the following filed GitHub Issues, in dependency order
#371 → #372 → #373 → #374 → #375:

- #371 — Publish the canonical cohort-vs-membership terminology contract.
- #372 — Give `account_asset.is_portfolio_member` a writer and operator
  action, backfilled from **each account's own positive holdings**, never
  from `asset.is_portfolio`.
- #373 — Repoint reporting's `PORTFOLIO ASSET` badge to the per-account
  column and split out the cohort signal as its own display state.
- #374 — Rename the internal `PORTFOLIO_MARKER` inclusion reason to
  `COHORT_PUBLISHED`.
- #375 — Only then, as a separate sequenced migration with its own
  production authorization: **rename** `asset.is_portfolio` to
  `asset.is_publication_cohort` via additive column + dual-read + backfill +
  cutover + drop-of-the-old-name. `asset.is_portfolio` is
  **never dropped outright** — the concept it holds (the publication cohort)
  is still needed; only the name was wrong.

Issues #371–#375 have been filed for this corrected Phase 2. Do not execute
`ALTER TABLE asset DROP COLUMN is_portfolio` under any circumstance without
first completing the rename sequence above (#375); a drop without a working
replacement collapses the canonical Fib publication cohort.

---

## Phase 3 — `quote_asset` migration (medium risk, 12 refs)

- [ ] **3.1** Add `quote_currency` column to `venue_market` (already in skeleton).
      Verify backfill matches all 12 call sites.

- [ ] **3.2** Update ETL runners to filter on `venue_market.quote_currency`
      instead of `asset.quote_asset`. Requires joining `venue_market` in ETL queries.

- [ ] **3.3** Update research runners. Most have a fallback pattern
      `quote_asset or quote_currency` — switch to `venue_market` join.

- [ ] **3.4** Once all 12 refs are switched: `ALTER TABLE asset DROP COLUMN quote_asset`.

---

## Phase 4 — `is_tradeable` migration (higher risk, 19 refs)

- [ ] **4.1** Audit all 19 `is_tradeable` call sites. Determine which have venue context
      already (can join `venue_market` directly) vs. which are venue-agnostic (need
      decision: use ANY tradeable venue, or require venue param).

- [ ] **4.2** Add `venue` param to selection_engine candidate fetch. This is the
      largest refactor — selection_engine currently has no venue parameter.

- [ ] **4.3** Update advice / policy router to join `venue_market.is_tradeable`
      filtered by venue.

- [ ] **4.4** Update zone backfill runners.

- [ ] **4.5** Once all 19 refs are switched: `ALTER TABLE asset DROP COLUMN is_tradeable`.

---

## Phase 5 — Hugo account onboarding (PARTIALLY SUPERSEDED)

- [x] **5.1** Insert Hugo `trading_account` row. Already done: `trading_account_id=4`,
      `account_code='hugo-bitvavo'`, live-verified 2026-08-09.

- [x] **5.2** Wallet discovery: scan Hugo's Bitvavo balance and create `account_asset`
      rows with `source='WALLET_DISCOVERY'`. Already done: 27 live `account_asset`
      rows for `trading_account_id=4`, live-verified 2026-08-09.

- [ ] **5.3** Open order discovery: scan Hugo's open orders and create `account_asset`
      rows with `source='OPEN_ORDER_DISCOVERY'` for any market not already covered.
      Not independently re-verified — requires fresh review, do not assume complete.

- [ ] **5.4** Dashboard filter: all account-aware dashboard queries must include
      `WHERE account_asset.trading_account_id = ?` to prevent cross-account leakage.
      Not independently re-verified — requires fresh review, do not assume complete.

---

## Phase 2-5 review gate

Before filing any Phase 3, 4, or remaining Phase 5 follow-up Issue, a fresh
architecture/call-site review against current `main` is required, covering:

Phase 2's fresh review has already been done — see
`docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md`. This
satisfies the review requirement below for `is_portfolio` specifically, but
`PHASE_2_AUTHORIZED` stays `0` here: a passed review is not execution
authorization.

- remaining uses of `asset.is_portfolio`, `asset.quote_asset`, `asset.is_tradeable`
  (original ref counts in this file predate substantial repo evolution and are
  not authoritative)
- current `venue_market` consumers
- current `account_asset` consumers
- current Hugo/account onboarding implementation state (5.3/5.4 above)
- interaction with Issue #319 (`account_id` vs `trading_account_id` identifier
  fragmentation)
- whether the original Phase 2/3/4/5 boundaries as designed still make sense
  given what has already shipped ad hoc

```text
PHASE_2_AUTHORIZED=0
PHASE_3_AUTHORIZED=0
PHASE_4_AUTHORIZED=0
PHASE_5_AUTHORIZED=0
```

---

## Out of scope for this backlog

- Hugo API endpoints
- Order proposal execution
- Broker private write calls
- decision_gate changes
- execution_planner changes
- executor changes

---

## Account table FK policy

Going forward: use `trading_account` as the canonical account FK for all new tables.
`exchange_account` is legacy; do not add new FKs to it. Existing FKs
(`account_balance_snapshot → exchange_account`, `open_order_state → exchange_account`)
stay as-is until those tables are refactored.
