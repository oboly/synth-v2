# Publication Cohort vs. Account Portfolio Membership — Canonical Terminology & Ownership Contract v1

Canonical, permanent rule set. Formalizes what
`docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md`
(evidence/history; keep reading that doc for the verified consumer inventory,
migration sequence, and risk analysis) already established. This doc is the
concise, forward-looking reference other docs and future issues should point
to instead of re-deriving the same rules.

Issue: #371. Depends on: #370 (merged). This is a documentation-only
publication; it does not implement any of the follow-on issues below.

```text
runtime_changes=0
schema_changes=0
migration_changes=0
db_writes=0
broker_writes=0
order_submission=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

---

## 0. Current implementation state (read this before anything else)

- `asset.is_portfolio` is the **legacy compatibility field name** for the
  global publication cohort. Issue #375 introduces the canonical
  `asset.is_publication_cohort` field through separately sequenced additive
  and backfill migrations; production application remains separately
  authorized.
- `account_asset.is_portfolio_member` **exists in schema today** but has
  **no writer** (every insert path sets it to the literal `0`) and **no
  reader** in current code. It is not authoritative at runtime. Giving it a
  real writer/backfill and an operator action is future work (#372); nothing
  in this document implements that writer.
- The reporting badge `PORTFOLIO ASSET` is, **as of today**, still driven by
  the global `asset.is_portfolio` cohort flag, not by
  `account_asset.is_portfolio_member`. Repointing it is future work (#373);
  nothing in this document implements that repoint.
- The reporting inclusion-reason code `PORTFOLIO_MARKER` is, **as of today**,
  still the live code name. Renaming it to `COHORT_PUBLISHED` is future work
  (#374); nothing in this document implements that rename.

Treat every statement in this document as **target contract**, not as a
description of already-shipped behavior, except where explicitly marked
"today".

---

## 1. Canonical terminology

Three distinct, non-overlapping concepts. None of them is "portfolio" alone.

### Publication cohort

- **Current field (legacy name, still in use today):** `asset.is_portfolio`.
- **Target field name (future, via #375 — not yet renamed):**
  `asset.is_publication_cohort`.
- **Scope:** global, account-agnostic, venue-scoped.
- **Meaning:** the set of symbols for which the system publishes canonical
  market context (4h Fib map, zone context, dashboards' market layer).
  Answers: *does the market layer compute and publish for this symbol?*
- **Owning layer:** `market_data` (market-only).

### Core sensor

- **Field:** `asset.is_core_sensor` (name unchanged, no rename planned).
- **Scope:** global, account-agnostic.
- **Meaning:** global market-structure reference symbols (e.g. BTC, ETH)
  always in the publication cohort regardless of any account holding.
- **Owning layer:** `market_data` (market-only).

### #375 compatibility and removal sequence

The column rename is a sequenced compatibility migration, never a direct
destructive rename:

1. Phase A adds `asset.is_publication_cohort` with default `0` only.
2. Phase B backfills exactly
   `is_publication_cohort = is_portfolio`; it never reads or writes
   `account_asset.is_portfolio_member`.
3. During the dual-read window, old-only schemas read `is_portfolio`,
   new-only schemas read `is_publication_cohort`, and schemas with both
   columns require row-level equality before reading the canonical new field.
   A mismatch fails closed with deterministic asset evidence; consumers must
   never OR the two flags.
4. Cutover makes `is_publication_cohort` canonical while retaining the
   explicit removable compatibility path.
5. The legacy column may be removed only after a verified drift-free
   dual-read/cutover window and a separate, explicit production authorization.

No production migration, backfill, or old-column removal is authorized by
this repository change.

### Account portfolio membership

- **Field:** `account_asset.is_portfolio_member`.
- **Scope:** per `(trading_account_id, venue_market_id)` — account-scoped, not
  global.
- **Meaning:** an account operator's declared strategic/rotation focus set.
  Answers: *does this account's operator consider this a portfolio position
  rather than incidental dust?* Independent of current balance.
- **Owning layer:** `account`.
- **Current status:** exists in schema; **not authoritative at runtime today**
  — no code path writes anything but `0`, and no code path reads its value.
  Do not treat any dashboard state as reflecting this field until #372 ships
  a real writer and #373 repoints reporting to read it.

---

## 2. Ownership and writer rules per field

| Field / concept | Owning layer | Sole writer (target contract) | May be read by |
|---|---|---|---|
| `asset.is_portfolio` (target: `is_publication_cohort`) | `market_data` | Held-market enrollment (0→1 only, guarded; see §3); market sync seeds new rows to `0` and never mutates existing rows | `market_data` cohort query, `market_data` health checks, `reporting` (market-layer display only) |
| `asset.is_core_sensor` | `market_data` | Manual / migration only | Same cohort consumers as above |
| `account_asset.is_portfolio_member` | `account` | Account-layer operator action / account-scoped discovery only (target contract for #372; no writer exists today) | Account-scoped `reporting` only, always predicated by `trading_account_id` (see §4) |

Rules, stated explicitly:

- The **publication cohort is written only by the market layer**. No
  account-layer writer may ever set it, directly or indirectly, outside the
  held-market enrollment mechanism in §3.
- **Account portfolio membership is written only by the account layer**
  (operator action or account-scoped discovery). It must never be derived
  from, or backfilled from, `asset.is_portfolio` — doing so would
  permanently bake the current cohort/membership conflation into per-account
  data.
- Neither field may be set from `reporting`. Reporting is read-only for both.

---

## 3. Held-market enrollment invariant (load-bearing)

Held-market enrollment (`docs/ops/held_market_enrollment_v1.md`, Issue #238)
is the **one legitimate account-observation → market-cohort edge** in the
system. It is safe only because it holds three properties simultaneously:

1. **Union across all linked accounts.** Enrollment resolves every distinct
   positive held currency across *every* linked account into one shared,
   market-wide cohort update — never a per-account cohort.
2. **Monotonic 0→1 only.** Enrollment only ever sets
   `asset.is_portfolio` (target: `is_publication_cohort`) from `0` to `1`. It
   never clears the flag.
3. **No single-account removal.** Because the edge is monotonic and
   union-based, no single account's absence of a holding can ever remove
   another account's symbol from the publication cohort.

This is **load-bearing, not incidental**. If a future change "fixes" this
account→market edge into a per-account write — for example, scoping
enrollment or de-enrollment to one account, or making the cohort mutable
per `trading_account_id` — it silently empties or fragments the canonical
Fib publication cohort for every other linked account. This is the exact
failure mode the boundary audit
(`docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md`,
R6) identified. Any change to held-market enrollment's write path must
preserve all three properties above; a change that breaks any one of them is
an architecture violation of this contract, not a routine refactor.

De-enrollment (clearing `is_portfolio` back to `0`) is intentionally manual,
explicit, and reviewed — never automated — for exactly this reason: an
automatic reconciliation job that clears the flag has no way to know whether
another account still needs the symbol published.

---

## 4. Hard boundaries

- No account-layer writer may directly set publication-cohort state outside
  the canonical held-market enrollment mechanism described in §3.
- No market-layer query may read `account_asset`. The publication-cohort
  query never joins `account_asset` and never takes a `trading_account_id`
  parameter.
- Every read of `account_asset.is_portfolio_member` must carry a
  `trading_account_id` predicate. No query may read it without one.
- `selection_engine`, `trade_setup_filter`, `signal_engine`, `advice`,
  `decision_gate`, `execution_planner`, and `executor` read **neither** the
  publication-cohort field nor the account-portfolio-membership field. This
  is currently true on `main` and must stay true — neither field may become
  candidate-eligibility, permission, or execution input.
- Reporting composes cohort state and membership state as **independent
  overlays** on one display surface; it never derives one from the other.
  All four combinations (cohort-only, member-only, both, neither) are legal
  and must render distinctly wherever both are shown.
- Historical rebuilds never use current cohort flags as historical truth.

---

## 5. Display vocabulary

Independent overlays. None is derived from another — each is backed by its
own evidence field, and all four may be true or false independently for a
given symbol/account pair.

| Display term | Backed by | Not backed by |
|---|---|---|
| `WALLET HELD` | Positive balance in `trading_account_balance_snapshot` | Any flag |
| `PORTFOLIO ASSET` | `account_asset.is_portfolio_member` (target; **as of today still wrongly driven by the global `asset.is_portfolio` cohort flag** — see §0 and §6) | Publication-cohort membership |
| `MARKET SELECTED` | Publication-cohort state (`asset.is_portfolio`, target name `asset.is_publication_cohort`) | Account state |
| `CORE SENSOR` | `asset.is_core_sensor` | Account state |

Cohort inclusion-reason codes (reporting-internal; target contract, current
code still uses the legacy name — see §6):

```text
POSITION_HELD      account overlay  (balance > 0)
OPEN_ORDER         account overlay  (open order exists)
PORTFOLIO_MEMBER   account overlay  (account_asset.is_portfolio_member)
COHORT_PUBLISHED   market layer     (publication cohort — target name;
                                     current code name is PORTFOLIO_MARKER)
CORE_SENSOR        market layer     (asset.is_core_sensor)
```

Retire the bare, ambiguous words "portfolio flag", "portfolio universe", and
"portfolio focus set" from new docs and code comments; each is ambiguous
across the publication-cohort and account-membership concepts this contract
disambiguates.

---

## 6. What this document does not do

This document publishes terminology and ownership rules only. It does not:

- rename `asset.is_portfolio` to `asset.is_publication_cohort` (future: #375);
- give `account_asset.is_portfolio_member` a writer, operator action, or
  backfill (future: #372);
- repoint the `PORTFOLIO ASSET` badge to read account membership instead of
  the global cohort flag (future: #373);
- rename the `PORTFOLIO_MARKER` inclusion-reason code to `COHORT_PUBLISHED`
  (future: #374);
- change held-market enrollment behavior, the chain-4h publication timer, or
  the Odroid orchestrator cadence;
- touch `selection_engine`, `decision_gate`, `execution_planner`, `executor`,
  or any broker/order path;
- apply any schema, migration, or runtime change.

See `docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md`
§4 for the full sequenced migration path (#372–#375) and §6 for the detailed
risk analysis behind each ordering constraint.

---

## 7. Related documents

| Doc | Role |
|---|---|
| `docs/architecture/portfolio_cohort_vs_membership_boundary_audit_v1.md` | Evidence source: verified consumer inventory, target architecture diagram, migration sequence, risk analysis. Historical/audit record — do not duplicate its content here. |
| `docs/ops/held_market_enrollment_v1.md` | Operational detail for the held-market enrollment mechanism (§3 above summarizes its load-bearing invariant only). |
| `docs/asset_flag_policy.md` | Full asset-flag inventory (`is_enabled`, `is_tradeable`, `is_portfolio`, `is_core_sensor`); points here for the cohort/membership distinction rather than re-deriving it. |
| `docs/research/multi_account_asset_foundation_v1.md` | Corrected multi-account foundation design doc (Issue #370). |
| `docs/todo/multi_account_asset_foundation_backlog.md` | Corrected backlog, points at Issues #371–#375. |
