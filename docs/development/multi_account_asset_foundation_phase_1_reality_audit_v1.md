# Multi-Account Asset Foundation Phase 1 — Reality Audit

Factual implementation/production evidence. Not a new architecture contract —
see `docs/research/multi_account_asset_foundation_v1.md` for the canonical
design. This document exists because Issue #294 asked for Phase 1 to be
implemented as though it did not yet exist; investigation found it was already
implemented and production-applied before the Issue was filed.

## 1. Repository lineage

- `098f338a1d8bcb359bd8a8896f714a5d01e30498` — "Add multi-account asset
  foundation and wallet refresh" (2026-06-03). Adds:
  - `db/migrations/20260603_multi_account_asset_foundation_v1.sql` (`venue_market`, `account_asset`)
  - `db/migrations/20260603_account_open_order_snapshot_v1.sql`
  - `src/market/run_bitvavo_market_sync_v1.py` (`venue_market` backfill)
  - `src/account/run_account_wallet_refresh_v1.py` (`account_asset` backfill)
  - `src/account/account_snapshot_models_v1.py`
  - `docs/ops/bitvavo_market_sync_v1.md`, `docs/ops/multi_account_wallet_refresh_v1.md`
  - `docs/research/multi_account_asset_foundation_v1.md`, `docs/todo/multi_account_asset_foundation_backlog.md`
  - `tests/test_account_wallet_refresh_v1.py`, `tests/test_bitvavo_market_sync_v1.py`
- `08f66335d56a6e6dd8c06ad01de66d7f2598ce4f` — "Add account asset management
  controls". Adds:
  - `db/migrations/20260603_account_asset_settings_v1.sql` (ALTER `account_asset`:
    `disabled_reason`, `first_seen_at_utc`, `last_seen_at_utc`)
  - `src/account/account_asset_settings_v1.py`, `src/account/run_account_asset_settings_v1.py`
  - `tests/test_account_asset_settings_v1.py`

Both commits are on `origin/main`. Issue #294 was filed later, retroactively,
during the TODO-to-Issues migration (Batch 6C, see
`docs/development/docs_todo_issue_migration_batch_6c_v1.md`), without checking
current repo/production state.

## 2. Live verification (LIVE_VERIFIED, read-only, gurkdb/synth, 2026-08-09)

Queries run: `SHOW CREATE TABLE`, `COUNT(*)`, `GROUP BY` duplicate/orphan
checks. No writes issued.

```text
venue_market_rows=430
account_asset_rows=86
joost_trading_account_id=3          (account_code=bitvavo_joost_read)
joost_account_asset_rows=57
hugo_trading_account_id=4           (account_code=hugo-bitvavo)
hugo_account_asset_rows=27
duplicate_venue_market=0
duplicate_account_asset=0
orphan_venue_market_fk=0
orphan_account_asset_fk=0
```

`account_asset.source` distribution:

```text
WALLET_DISCOVERY=78
MANUAL_ADD=6
OPEN_ORDER_DISCOVERY=2
```

`trading_account` (4 rows, all `venue=bitvavo`):

```text
trading_account_id=1  account_code=paper_sell_only_preview  account_mode=paper
trading_account_id=2  account_code=bitvavo_synth_read        account_mode=live
trading_account_id=3  account_code=bitvavo_joost_read         account_mode=live
trading_account_id=4  account_code=hugo-bitvavo                account_mode=paper
```

`venue_market`: 430 rows, all `venue='bitvavo'`, all `quote_currency='EUR'`,
428 `is_tradeable=1`, 0 orphaned `base_asset_id`.

Live `SHOW CREATE TABLE venue_market` and `account_asset` match
`db/migrations/20260603_multi_account_asset_foundation_v1.sql` exactly (see
Section 3).

## 3. Migration drift comparison

| Source | Classification |
|---|---|
| `20260603_multi_account_asset_foundation_v1.sql` vs live schema | `ORIGINAL_PHASE_1`, no drift — exact match |
| `venue_market`/`account_asset` row population vs backfill contract | `ORIGINAL_PHASE_1`, no drift — backfill contract satisfied |
| `20260603_account_asset_settings_v1.sql` (3 extra `account_asset` columns) vs live schema | `DRIFT_REQUIRING_REPAIR` — columns present in repo migration and consumed by `account_asset_settings_v1.py`, absent on live gurkdb. **Not part of Phase 1 / Issue #294 scope.** Tracked as Issue #333. Not repaired in this document/PR. |
| `AUTO_INCREMENT` gaps (e.g. `account_asset` AUTO_INCREMENT far exceeds row count) | `EXPECTED_PRODUCTION_METADATA` — consistent with normal `INSERT ... ON DUPLICATE KEY UPDATE` / retried-insert churn from periodic backfill runs; not evidence of data loss (duplicate/orphan checks above are all zero) |
| Hugo (`trading_account_id=4`) account_asset rows | `LATER_ADDITIVE_EXTENSION` relative to the original 5-phase plan's sequencing (plan assumed Phase 5 would follow Phase 1 review; in reality it happened concurrently/ahead) — not a defect |
| `account_asset_settings_v1.py` control surface (add/hide/pause/disable/reenable) | `LATER_ADDITIVE_EXTENSION` on top of the Phase 1 skeleton — not a defect, but its migration is the drift noted above |

## 4. Original Phase 1 acceptance

```text
PHASE_1_REPOSITORY_IMPLEMENTED=1
PHASE_1_PRODUCTION_APPLIED=1
PHASE_1_BACKFILL_COMPLETE=1
PHASE_1_ACCEPTANCE_SATISFIED=1
```

## 5. Legacy compatibility

```text
asset.is_portfolio_present=1
asset.quote_asset_present=1
asset.is_tradeable_present=1
```

Verified live via `SHOW COLUMNS FROM asset` on gurkdb, 2026-08-09.

## 6. Architecture

```text
architecture_violations=0
```

No references to `venue_market` or `account_asset` found in
`src/selection_engine/`, `src/decision_gate/`, `src/execution_planner/`, or
`src/executor/`.

## 7. Stale Issue #294 findings

- "`venue_market` and `account_asset` tables do not exist yet" — **stale**.
  Both exist and are populated; implemented before the Issue was filed.
- "Backfill `account_asset` from existing Joost (`trading_account_id=1`)" —
  **factually wrong**, not just stale. Live data shows `trading_account_id=1`
  is `paper_sell_only_preview`; Joost is `trading_account_id=3`. Had this
  Issue's literal text been implemented, Joost's holdings would have been
  misattributed to the wrong account.
- "Phase 5 (Hugo account onboarding) — no Issue yet; deferred" (implying wholly
  future) — **stale**. Hugo (`trading_account_id=4`) already exists with 27
  real `account_asset` rows.
- Acceptance criteria ("tables exist with additive migration applied",
  "Backfill matches existing asset rows and Joost's existing
  positions/balances with zero mismatch", "No asset column is dropped and no
  existing call site is changed") — all satisfied by pre-existing production
  state, verified live in Section 2/4/5/6 above.

## 8. Test evidence

```text
$ pytest tests/test_account_asset_settings_v1.py tests/test_account_market_scope_v1.py \
    tests/test_account_scope_contract_v1.py tests/test_account_wallet_refresh_v1.py \
    tests/test_bitvavo_market_sync_v1.py -q
85 passed
```

No source, runtime, or schema changes were made as part of this audit or the
accompanying documentation-correction PR.

## 9. Production status

```text
production_migration_applied_this_pr=0
gurkdb_changed_this_pr=0
broker_writes=0
order_submission=0
```

(Phase 1's original migration was applied to gurkdb prior to this PR, under
commit `098f338a` — not by this PR.)

## 10. Issue disposition

```text
ISSUE_294_PREMISE=PARTIALLY_STALE
ISSUE_294_ACCEPTANCE_SATISFIED=1
ISSUE_294_CLOSE_READY=1
REMAINING_ACCEPTANCE=none
DRIFT_ISSUE=#333 (separate scope: account_asset_settings_v1.sql columns unapplied on gurkdb)
```

#294 is not closed by this PR — see PR description. It should be closed
separately, after this documentation correction is reviewed, with a link back
to this evidence.

## 11. Phase 2-5 gate

```text
PHASE_2_AUTHORIZED=0
PHASE_3_AUTHORIZED=0
PHASE_4_AUTHORIZED=0
PHASE_5_AUTHORIZED=0
```

No Phase 2-5 Issues are created by this PR. Next step: a fresh
architecture/call-site review against current `main` (see
`docs/todo/multi_account_asset_foundation_backlog.md`, "Phase 2-5 review
gate") before any follow-up Issue is filed.
