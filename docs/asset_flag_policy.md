# Asset Flags Policy — Synth v2

Defines the minimal and canonical set of asset flags.

---

## Overview

Synth v2 uses four flags to define asset/market participation:

```text
is_enabled
is_tradeable
is_portfolio
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

- **Table:** `asset` (also read alongside the venue-level
  `venue_market.is_tradeable`/`is_market_data_enabled` columns, which gate
  venue-specific execution eligibility separately).
- **Scope:** global, account-agnostic.
- **Meaning:** whether the asset is currently eligible for trading
  consideration on its venue, independent of whether it is currently
  published in the cohort. Used alongside `is_enabled` as a universe-gating
  precondition (e.g. `src/market_data/held_market_coverage_v1.py` requires
  both `is_enabled` and `is_tradeable` before resolving a held symbol).
- **Owning layer:** `market_data` (market-only).

### `is_portfolio` (publication cohort — legacy field name)

- **Table:** `asset`.
- **Scope:** global, account-agnostic, venue-scoped.
- **Meaning:** the **publication cohort** selector — the flag that decides
  which symbols the canonical 4h Fib writer publishes market context for.
  This is **not** a per-account watchlist or portfolio membership flag,
  despite the name. See the canonical contract doc (§1, "Publication
  cohort") for the full definition, target rename
  (`asset.is_publication_cohort`, not yet applied), and writer rules.
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
| `docs/architecture/publication_cohort_membership_terminology_contract_v1.md` | Canonical terminology, ownership, and writer rules for `is_portfolio`/`is_core_sensor` vs. `account_asset.is_portfolio_member`. |
| `docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md` | Evidence source and migration sequence. |
| `docs/ops/held_market_enrollment_v1.md` | Operational detail for the mechanism that writes `is_portfolio`. |
