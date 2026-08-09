# Multi-Account Asset Foundation V1

## Purpose

Separate global asset/market data from per-account asset settings before building
multi-account dashboards and onboarding pages.

The current `asset` table conflates three concerns:

1. **Global identity** — symbol, name, asset_class, sector (immutable, shared)
2. **Venue/market metadata** — quote_asset, is_tradeable (venue-specific)
3. **Account settings** — is_portfolio (per-account membership flag)

When a second account (Hugo) is onboarded, any per-account flag in `asset` creates
a coupling problem: toggling `is_portfolio` for Hugo's view would change Joost's view.

**Hard rule: Hugo settings must never affect Joost settings.**

Account identities are looked up canonically via `trading_account.account_code`
(e.g. `bitvavo_joost_read`, `hugo-bitvavo`); numeric `trading_account_id` values
are deployment data, not a stable contract, and must not be hard-coded by
callers or documentation.

---

## Current Status (2026-08-09)

Phase 1 (this skeleton: `venue_market` + `account_asset` tables, additive) is
**implemented and production-present** — repo lineage commit `098f338a`,
live-verified on gurkdb. A later commit `08f66335` added a per-account asset
*settings* extension (`disabled_reason`/`first_seen_at_utc`/`last_seen_at_utc`
on `account_asset`, plus `src/account/account_asset_settings_v1.py`); that
extension's migration has not been applied to live gurkdb — tracked as a
separate production drift, Issue #333, not part of this Phase 1 design.

A second account (Hugo, `account_code='hugo-bitvavo'`) already exists in
`trading_account` with real `account_asset` rows populated via
`WALLET_DISCOVERY`. Full factual detail:
`docs/development/multi_account_asset_foundation_phase_1_reality_audit_v1.md`.

Phases 2-4 (moving `is_tradeable`/`quote_asset`/`is_portfolio` off `asset`) and
the remainder of Phase 5 (Hugo open-order discovery, dashboard account-scope
filter audit) require a fresh call-site/architecture review against current
`main` before implementation — the ref counts below predate substantial repo
evolution and are not authoritative. See
`docs/todo/multi_account_asset_foundation_backlog.md` for the review gate.

---

## Current `asset` Flag Inventory

| Flag | Refs | Classification | Rationale |
|------|------|----------------|-----------|
| `is_enabled` | 48 | **Keep in `asset`** | System-wide ETL + signal pipeline gate. Not per-account. Disabling it stops all candle ingestion and signal generation globally. |
| `is_core_sensor` | ~4 | **Keep in `asset`** | Signal pipeline input classification. Same meaning for all accounts. |
| `asset_class` | — | **Keep in `asset`** | Global classification (CRYPTO, FX, …). |
| `sector` | — | **Keep in `asset`** | Global sector label. |
| `name` | — | **Keep in `asset`** | Human-readable asset name. |
| `is_tradeable` | 19 | **Move to `venue_market`** | Tradability is per-venue, not per-asset. On Bitvavo, WLD-EUR may be tradeable; on another venue it may not be listed. Also used in selection_engine which should become venue-aware. |
| `quote_asset` | 12 | **Move to `venue_market`** | EUR quote is a venue/market property, not a global identity field. |
| `is_portfolio` | 3 | **Move to `account_asset`** | Portfolio membership is per-account. Used only in watchlist candidate check (3 refs). |

---

## Target Schema

### 1. `asset` (trimmed)

Global identity only. No venue/account specifics.

```sql
-- Keep existing columns:
--   asset_id, symbol, name, sector, asset_class,
--   is_enabled, is_core_sensor,
--   created_ts, updated_ts
--
-- Remove (migrate to venue_market / account_asset):
--   quote_asset    → venue_market.quote_currency
--   is_tradeable   → venue_market.is_tradeable
--   is_portfolio   → account_asset.is_portfolio_member
```

`is_enabled` stays on `asset` because it gates system-wide ETL, not account view.

---

### 2. `venue_market` (new)

One row per (venue, market). Links market metadata to the global asset.

```sql
CREATE TABLE IF NOT EXISTS venue_market (
    venue_market_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    venue            VARCHAR(32)  NOT NULL COMMENT 'e.g. bitvavo',
    market           VARCHAR(32)  NOT NULL COMMENT 'e.g. WLD-EUR',
    base_asset_id    INT(11)      NOT NULL,
    quote_currency   VARCHAR(8)   NOT NULL DEFAULT 'EUR',

    is_tradeable              TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Asset eligible for trading decisions on this venue',
    is_market_data_enabled    TINYINT(1) NOT NULL DEFAULT 1
        COMMENT 'Candle/ticker ETL enabled for this market',

    -- Precision metadata (optional, populated from venue API)
    price_precision   SMALLINT UNSIGNED DEFAULT NULL,
    qty_precision     SMALLINT UNSIGNED DEFAULT NULL,
    min_order_qty     DECIMAL(20,10)    DEFAULT NULL,

    created_ts  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_venue_market (venue, market),
    KEY idx_venue_market_asset (base_asset_id),
    CONSTRAINT fk_venue_market_asset
        FOREIGN KEY (base_asset_id) REFERENCES asset (asset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Backfill source:** `asset.quote_asset` and `asset.is_tradeable` for existing assets on
Bitvavo. Market name constructed as `<symbol>-<quote_asset>`.

---

### 3. `account_asset` (new)

One row per (account, venue_market). Stores all per-account asset settings.

```sql
CREATE TABLE IF NOT EXISTS account_asset (
    account_asset_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,

    trading_account_id  BIGINT UNSIGNED NOT NULL,
    venue_market_id     BIGINT UNSIGNED NOT NULL,

    -- Visibility / candidate gates (per-account)
    is_visible                  TINYINT(1) NOT NULL DEFAULT 1
        COMMENT 'Show in account dashboard',
    is_candidate_enabled        TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Eligible for signal-driven candidate selection for this account',
    is_order_proposal_enabled   TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Order proposals allowed for this account',
    is_portfolio_member         TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Asset part of this account\'s portfolio focus set',
    is_hidden                   TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Suppressed from all views (e.g. dust position)',

    disabled_until_utc  DATETIME DEFAULT NULL
        COMMENT 'Temporarily suppress candidate eligibility until this timestamp',

    -- How this row was created
    source  VARCHAR(32) NOT NULL DEFAULT 'MANUAL_ADD'
        COMMENT 'WALLET_DISCOVERY | OPEN_ORDER_DISCOVERY | MANUAL_ADD',

    created_ts  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_ts  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_account_asset (trading_account_id, venue_market_id),
    KEY idx_account_asset_vm (venue_market_id),
    CONSTRAINT fk_account_asset_ta
        FOREIGN KEY (trading_account_id) REFERENCES trading_account (trading_account_id),
    CONSTRAINT fk_account_asset_vm
        FOREIGN KEY (venue_market_id) REFERENCES venue_market (venue_market_id),
    CONSTRAINT chk_account_asset_source
        CHECK (source IN ('WALLET_DISCOVERY', 'OPEN_ORDER_DISCOVERY', 'MANUAL_ADD'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 4. Snapshot Tables (existing — keep, reconcile FK direction)

Two balance snapshot tables currently exist with different FK roots:

| Table | FK | Purpose |
|-------|----|---------|
| `account_balance_snapshot` | → `exchange_account` | Older balance snapshots |
| `trading_account_balance_snapshot` | → `trading_account` | Newer balance snapshots |

**Recommendation:** Standardize on `trading_account` as the canonical account FK going
forward. `exchange_account` is the older table; `trading_account` has the richer
schema (account_mode, live_trading_enabled gate). New snapshot tables should FK to
`trading_account`.

No structural change to snapshot tables is required in this migration. Only document
the policy preference.

---

## Flag Migration Path

### `is_tradeable` (19 refs)

Currently read as `asset.is_tradeable` throughout selection_engine, advice, zone
backfills, and policy router. All current callers assume a single global tradability
value per symbol.

Migration path (two-phase, not in this skeleton):
1. Add `venue_market.is_tradeable`, backfill from `asset.is_tradeable`
2. Update callers to join via `venue_market` (requires venue context in call site)
3. Drop `asset.is_tradeable` once all refs are migrated

**Do not change existing `asset.is_tradeable` reads in this skeleton.** The column
stays on `asset` in read-only compatibility mode until Phase 2 callers are updated.

### `quote_asset` (12 refs)

Same two-phase approach. Callers use it as a market filter (`WHERE quote_asset = 'EUR'`).
Once `venue_market.quote_currency` is backfilled, callers can switch to a join. Until
then, `asset.quote_asset` is read in compatibility mode.

### `is_portfolio` (3 refs)

Low-impact: 3 refs, all in watchlist candidate research code. Safe to migrate once
`account_asset` is created and backfilled. Existing refs can be switched to a join
without any callers requiring venue context.

---

## Source Impact Summary

### Files referencing `is_enabled` (keep in `asset` — no change needed)

- Signal pipeline: `src/signal/`, `src/etl/`, `src/ranking/`
- Selection engine: `src/selection_engine/`
- Research runners: `src/research/`
- Advice: `src/advice/`

### Files referencing `is_tradeable` (future venue_market migration)

- `src/selection_engine/` — candidate eligibility
- `src/advice/` — advice filter
- DB-backed zone backfills and policy routers

### Files referencing `is_portfolio` (future account_asset migration)

- `src/research/` — watchlist candidate check (3 refs only)

### Files referencing `quote_asset` (future venue_market migration)

- ETL runners: market filter
- Research runners: market filter (with fallback to `quote_currency`)

---

## Backwards Compatibility

This migration creates two new tables and adds no columns to `asset`. The existing
`asset` table is unchanged by the skeleton — all current reads continue to work.

The migration is **additive only**:
- No `ALTER TABLE asset DROP COLUMN`
- No data migration scripts (those belong in Phase 2 per-flag migrations)
- No FK changes on existing tables

Column removal from `asset` requires a separate, sequenced migration per flag after
all callers are verified switched.

---

## Verdict

The skeleton (table creation only) **has been implemented and applied to
production** — see Current Status above. The original verdict below is kept
for historical context; it is no longer a pending recommendation.

**Implementation is safe to proceed** for the skeleton (table creation only).

Risk areas deferred to Phase 2-4 (require a fresh call-site review against
current `main` before implementation — original ref counts below are not
authoritative):
- `is_tradeable` caller migration (selection_engine, advice — requires venue context)
- `quote_asset` caller migration (ETL, research — lower risk, simpler join)
- `is_portfolio` caller migration (3 refs — lowest risk, safe to do early)

---

## Safety Markers

```
broker_writes=0
order_submission=0
db_writes=skeleton_only
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```
