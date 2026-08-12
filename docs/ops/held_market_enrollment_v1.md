# Held-Market Enrollment v1 (Issue #238)

Canonical terminology, ownership, and the union/monotonic load-bearing
invariant for this mechanism are defined in
`docs/architecture/publication_cohort_membership_terminology_contract_v1.md`
§3 — read that first. This doc covers held-market-enrollment-specific
operational detail only (files, cycle sequencing, idempotency, rollback,
activation commands) and does not restate the contract.

## Purpose

Close the gap between "a token is a positive wallet holding" and "the
canonical 4h Fib writer's publication cohort includes it." Before this
change, a wallet-discovered holding (e.g. LIGHTER) could remain
`FIB_MAP_SYMBOL_MISSING` indefinitely: nothing ever set the market-wide
`asset.is_portfolio` flag that
`canonical_fib_zone_map_v1.fetch_tracked_symbols()` and the Profit Plan
selection layer both gate on, so a human had to notice and run a manual CLI.

This mechanism makes enrollment automatic, scheduled, and idempotent, with no
manual `--apply` step required for normal future holdings.

## Ownership

```text
Odroid linked-profile runtime orchestrator (existing, account/render owner)
  -> held-market enrollment phase (Issue #238, this doc)
       -> writes only asset.is_portfolio (market-wide, account-agnostic)

gurkdb canonical 4h Fib writer (existing, market-only owner, unchanged)
  -> scripts/run_chain_4h.sh -> run_canonical_fib_zone_map_v1 --publish
       -> reads asset.is_portfolio/is_core_sensor fresh every run
```

No new systemd unit is introduced. Enrollment is one more phase inside the
already-installed `synth-linked-profile-runtime-refresh.service`/`.timer`
(`docs/ops/systemd/synth-linked-profile-runtime-refresh.service`,
`docs/ops/linked_profile_runtime_orchestrator_v1.md`), which already owns the
account-refresh -> render sequence and already runs every 5 minutes on
Odroid. The canonical 4h Fib writer's own timer
(`deploy/systemd/synth-chain-4h.timer`, gurkdb-bound, `OnCalendar=*-*-*
00,04,08,12,16,20:12:00 UTC`, i.e. every 4 hours) is unchanged and is never
invoked from the Odroid orchestrator -- that would be a cross-host systemd
dependency, which the orchestrator's hard boundaries explicitly forbid (see
`docs/ops/linked_profile_runtime_orchestrator_v1.md`).

## Files

| File | Role |
|------|------|
| `src/market_data/held_market_coverage_v1.py` | Pure resolution/classification logic. No SQL, no DB/broker import. |
| `src/market_data/run_held_market_enrollment_v1.py` | DB-aware CLI. Dry-run by default; `--apply --operator ... --reason ...` to mutate. Writes only `asset.is_portfolio`. |
| `src/market_data/run_held_market_coverage_health_check_v1.py` | Read-only invariant check. Never mutates. |
| `scripts/odroid/run_held_market_enrollment_once.sh` | Locked wrapper invoked by the orchestrator, always with `--apply`. |
| `scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh` | Existing orchestrator; now runs the enrollment phase every cycle. |

## Order of operations (per orchestrator cycle)

1. Disk/log health check.
2. Persisted public-price freshness validation (unchanged, blocks everything
   below on failure).
3. Linked-profile discovery.
4. Per profile: authenticated read-only account refresh (writes
   `trading_account_balance_snapshot`), then wallet/open-order render.
5. **Held-market enrollment** (this doc): runs once, across every linked
   profile's balances from step 4, **only if every profile's account
   refresh in step 4 succeeded this cycle**. Enrolling off partial/stale
   balance data would be non-deterministic, so a partial cycle skips
   enrollment entirely (`result=skipped_account_refresh`) rather than
   enrolling a subset.
6. Per profile: Profit Plan persisted-snapshot render (unchanged sequencing;
   still gated on step 4 succeeding for all profiles, independent of step 5's
   outcome).

Enrollment resolves every distinct positive held currency code (across every
linked account — the union/monotonic invariant that makes this safe is
defined in the canonical contract linked above, not restated here) to
canonical `asset`/`venue_market` identity by an exact `asset.symbol` match
only. Display aliases (e.g. "LIT" for "LIGHTER") are never used as machine
identity -- see
`docs/research/sector_taxonomy_database_seed_v1.md` for the display-alias
note and Issue #245 for display-alias work, which is out of scope here.

## Deterministic publication path

Enrollment does not publish canonical 4h context itself and never invokes
the canonical Fib writer. The guarantee is cadence-based and uses the
existing, separately owned writer timer unchanged:

- A new positive holding is enrolled (`asset.is_portfolio: 0 -> 1`) within
  at most 5 minutes of appearing in a fresh balance snapshot (the
  orchestrator's fixed cadence).
- The already-scheduled `synth-chain-4h.timer` on gurkdb re-reads
  `asset.is_portfolio`/`is_core_sensor` on every run
  (`fetch_tracked_symbols()`), so the newly enrolled symbol is included in
  the very next `run_canonical_fib_zone_map_v1 --publish` run -- at most 4
  hours after enrollment, per the timer's `OnCalendar` schedule.
- Combined worst case: **a new positive holding gets fresh canonical 4h
  context within ~4 hours and 5 minutes of first appearing in a balance
  snapshot**, with no manual step.

## Idempotency and failure behavior

- The enrollment `UPDATE` is guarded
  (`WHERE is_portfolio = 0 AND is_core_sensor = 0`) and applied one row at a
  time, each committed independently. Re-running the same cycle (or retrying
  after a partial failure) only ever touches rows still needing enrollment;
  already-enrolled rows are untouched (`rowcount == 0`, reported as
  "skipped, already enrolled", not as an error).
- A failure applying one symbol's `UPDATE` (e.g. a transient DB error) is
  caught, rolled back for that row, and recorded under `failed_this_run`
  with the error text -- it does not abort enrollment for the remaining
  symbols in the same run, and the script exits non-zero (`FAILED`) so the
  failure is visible, never silently swallowed.
- Every run logs, explicitly: total held symbols, already-enrolled count,
  needing-enrollment count, enrolled this run, skipped-already-enrolled this
  run (races with a concurrent run), non-resolvable symbols with a reason,
  and any failed symbols with the error.
- Orchestrator-level failure (`failed_continuing`) marks the whole cycle
  `overall_result=degraded` -- visible in
  `_runtime/linked_profile_orchestrator_v1/latest_run.json`, never a silent
  partial success -- but does not block the render stages, since enrollment
  only ever affects the market-wide `asset` table, not any render input for
  the current cycle.

## Rollback

Enrollment only ever sets `asset.is_portfolio = 1`. To roll back a specific
enrollment (e.g. a symbol was enrolled in error), an operator runs a manual,
explicit, reviewed:

```sql
UPDATE asset SET is_portfolio = 0 WHERE asset_id = <id> AND is_portfolio = 1;
```

This is intentionally not automated -- de-enrollment is a judgment call
(would it also remove the symbol from other consumers of `is_portfolio`?)
and is out of scope for an automatic reconciliation job. Disabling the
mechanism entirely (e.g. during an incident) is done by not deploying the
updated orchestrator script, or by setting
`SYNTH_HELD_MARKET_ENROLLMENT_SCRIPT=/bin/true` in the timer's
`EnvironmentFile`, which no-ops the phase (`result=ok`, no rows touched)
without disabling the rest of the orchestrator.

## Health-check semantics

`run_held_market_coverage_health_check_v1` reports two separate invariants
so "enrollment worked" and "canonical Fib publication is fully caught up"
are never conflated:

- `--check enrollment` (or the `enrollment` section of any output): passes
  once every resolvable positive holding has `asset.is_portfolio` or
  `asset.is_core_sensor` set. Does not require a published canonical 4h row
  yet -- a symbol enrolled moments ago and still waiting on the next
  chain-4h cycle does not fail this check.
- `--check publication` (or `--check all`, the default; the `publication`
  section of any output): the full original invariant -- every resolvable
  held asset must have fresh, published canonical 4h context. A known,
  separately tracked gap (e.g. SOL/VET reporting
  `CANONICAL_4H_MAP_STATUS_UNAVAILABLE` despite ample candle history) keeps
  failing this check and must never be reported as passing just because
  enrollment succeeded.

## Production activation

Dry-run (no mutation, safe at any time):

```bash
python -m src.market_data.run_held_market_enrollment_v1
```

Manual one-off apply (only needed for immediate/manual remediation; the
scheduled orchestrator does this automatically every cycle once deployed):

```bash
python -m src.market_data.run_held_market_enrollment_v1 \
  --apply --operator <name> --reason "Issue #238 held-asset publication-cohort gap"
```

Backfill publication for newly enrolled symbols immediately, instead of
waiting for the next scheduled chain-4h tick (run on gurkdb, under the
existing writer's ownership/credentials):

```bash
python -m src.market_data.run_canonical_fib_zone_map_v1 --publish
```

Health check (read-only, safe at any time):

```bash
python -m src.market_data.run_held_market_coverage_health_check_v1 --check enrollment
python -m src.market_data.run_held_market_coverage_health_check_v1 --check publication
```

## Production acceptance

- [ ] Updated orchestrator deployed to the host running
      `synth-linked-profile-runtime-refresh.timer`.
- [ ] One orchestrator cycle completes with
      `held_market_enrollment.result=ok`.
- [ ] `run_held_market_coverage_health_check_v1 --check enrollment` exits 0.
- [ ] Within one `synth-chain-4h.timer` cycle, LIGHTER (and the other
      resolvable held symbols found in the Issue #238 audit) has a fresh row
      in `canonical_fib_zone_map_latest_v1`.
- [ ] `run_held_market_coverage_health_check_v1 --check publication` exits 0
      for every held asset except the separately tracked SOL/VET
      map-status-unavailable gap and any non-resolvable symbol.
- [ ] Profit Plan re-render shows LIGHTER with re-entry, target,
      invalidation, and a numeric Planning PPP.
- [ ] `broker_writes=0`, `order_submission=0`, `live_orders=0` unchanged in
      every new script's output.

## Non-goals

- No new writer for canonical 4h context; the existing gurkdb-owned writer
  and its timer are unchanged.
- No cross-host systemd dependency; the Odroid orchestrator never invokes
  anything on gurkdb.
- No account-aware logic added to `selection_engine`.
- No `decision_gate`, `execution_planner`, or `executor` change.
- No broker write, order submission, or live-trading change.
- No display-alias resolution (Issue #245).
