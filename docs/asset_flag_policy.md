# Asset Flags Policy — Synth v2

Defines the minimal and canonical set of asset flags.

---

## Overview

Synth v2 uses four flags to define asset/market participation:

```text
is_enabled
is_tradeable
is_publication_cohort (legacy: is_portfolio)
is_core_sensor
```

`is_portfolio` and `is_core_sensor` are the **publication cohort** and
**core sensor** flags respectively. Their full meaning, ownership, writer
rules, and relationship to the separate, account-scoped
`account_asset.is_portfolio_member` field are defined canonically in
`docs/architecture/publication_cohort_membership_terminology_contract_v1.md`.
This document does not re-derive those rules; it lists all four
asset-participation flags together for one-stop reference and defines the
two universe-gating flags below.

---

## Flags

### `is_enabled`

- **Table:** `asset`.
- **Scope:** global, account-agnostic.
- **Meaning:** master on/off switch for whether Synth considers the asset
  part of its tracked universe at all. An asset with `is_enabled = 0` is
  excluded from cohort queries, held-market enrollment resolution, and
  every downstream market-data consumer, regardless of any other flag.
- **Owning layer:** `market_data` (market-only).

### `is_tradeable`

- **Table:** `asset`.
- **Scope:** global, account-agnostic.
- **Current implementation state:** a legacy, pre-multi-account global
  compatibility field. It is still actively read as the tradability gate by
  several current consumers — including `selection_engine`
  (`src/selection/run_selection_engine_v2.py`), advice, regime, zone, and
  research code, and as a universe-gating precondition alongside
  `is_enabled` (e.g. `src/market_data/held_market_coverage_v1.py`). It is
  **not yet fully migrated** to the venue-specific model: per the current-state
  audit
  (`docs/development/multi_account_asset_foundation_phase_2_5_current_state_audit_v1.md`,
  §5), `selection_engine` reads `asset.is_tradeable` directly with no
  `venue_market` join and remains venue-unaware for tradability today.
- **Target ownership:** venue-specific trading eligibility belongs to
  `venue_market.is_tradeable`, which is already authoritative for market-sync
  writes and for venue-aware account/reporting reads (e.g.
  `account_wallet_dashboard_v1.py`). Migrating the remaining `asset.is_tradeable`
  readers onto `venue_market.is_tradeable` is tracked as future **Phase 4**
  work and is **not implemented by this document or by #371** — it requires a
  prior `selection_engine` venue-context design decision (how venue-awareness
  is threaded through candidate fetch) before any call site can migrate.
- **Boundary:** that future venue-awareness work must make `selection_engine`
  venue-aware, not account-aware — `selection_engine` must remain
  account-agnostic (no `account_asset` or account-scoped reads) even after
  Phase 4 migration.
- **Owning layer:** `market_data` (market-only) for the current `asset`-table
  field; `market_data` also owns `venue_market.is_tradeable` as the
  venue-specific target.

### `is_publication_cohort` (publication cohort — canonical field name)

- **Table:** `asset`.
- **Scope:** global, account-agnostic, venue-scoped.
- **Legacy compatibility name:** `asset.is_portfolio` during the verified
  dual-read window only.
- **Meaning:** the **publication cohort** selector — the flag that decides
  which symbols the canonical 4h Fib writer publishes market context for.
  This is **not** a per-account watchlist or portfolio membership flag,
  despite the name. See the canonical contract doc (§1, "Publication
  cohort") for the full definition, migration sequence, and writer rules.
- **Owning layer:** `market_data` (market-only).
- **Sole writer (target contract):** held-market enrollment (0→1 only,
  guarded) and market sync (seeds new rows to `0` only). See
  `docs/ops/held_market_enrollment_v1.md` for the enrollment mechanism.

### `is_core_sensor`

- **Table:** `asset`.
- **Scope:** global, account-agnostic.
- **Meaning:** marks global market-structure reference symbols (e.g. BTC,
  ETH) that are always in the publication cohort regardless of any account
  holding. See the canonical contract doc (§1, "Core sensor") for the full
  definition.
- **Owning layer:** `market_data` (market-only).

---

## Out of scope for this policy

`account_asset.is_portfolio_member` is a separate, account-scoped field
(per `trading_account_id`/`venue_market_id`), not an `asset`-table flag, and
is therefore not part of the universe-gating policy above. It is defined
in the canonical contract doc (§1, "Account portfolio membership"). As of
this writing it has no writer and is not authoritative at runtime — do not
treat it as an asset participation gate until that changes.

---

## Related documents

| Doc | Role |
|---|---|
| `docs/architecture/publication_cohort_membership_terminology_contract_v1.md` | Canonical terminology, migration contract, ownership, and writer rules for `is_publication_cohort`/`is_core_sensor` vs. `account_asset.is_portfolio_member`. |
| `docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md` | Evidence source and migration sequence. |
| `docs/ops/held_market_enrollment_v1.md` | Operational detail for the mechanism that writes `is_portfolio`. |
