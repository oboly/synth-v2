# Multi-Account Asset Foundation Backlog

Design doc: `docs/research/multi_account_asset_foundation_v1.md`

---

## Phase 1 — Skeleton (safe now)

- [ ] **1.1** Run migration `20260603_multi_account_asset_foundation_v1.sql`
      Creates `venue_market` and `account_asset`. Additive only, no asset column drops.

- [ ] **1.2** Backfill `venue_market` from existing `asset` rows
      For each row in `asset`: insert one `venue_market` row with `venue='bitvavo'`,
      `market=<symbol>-<quote_asset>`, `is_tradeable=asset.is_tradeable`,
      `quote_currency=asset.quote_asset`. Script: one-time Python or SQL INSERT-SELECT.

- [ ] **1.3** Backfill `account_asset` from existing Joost account data
      For each position/balance held by `trading_account_id=1` (Joost):
      insert `account_asset` rows with `source='WALLET_DISCOVERY'` or `'OPEN_ORDER_DISCOVERY'`,
      `is_portfolio_member` from `asset.is_portfolio`.

---

## Phase 2 — `is_portfolio` migration (low risk, 3 refs)

- [ ] **2.1** Update 3 `is_portfolio` refs in `src/research/` to join through
      `account_asset.is_portfolio_member` filtered by `trading_account_id`.
      Requires passing account context into the 3 call sites.

- [ ] **2.2** Once all 3 refs are switched: `ALTER TABLE asset DROP COLUMN is_portfolio`.

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

## Phase 5 — Hugo account onboarding

- [ ] **5.1** Insert Hugo `trading_account` row.

- [ ] **5.2** Wallet discovery: scan Hugo's Bitvavo balance and create `account_asset`
      rows with `source='WALLET_DISCOVERY'`.

- [ ] **5.3** Open order discovery: scan Hugo's open orders and create `account_asset`
      rows with `source='OPEN_ORDER_DISCOVERY'` for any market not already covered.

- [ ] **5.4** Dashboard filter: all account-aware dashboard queries must include
      `WHERE account_asset.trading_account_id = ?` to prevent cross-account leakage.

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
