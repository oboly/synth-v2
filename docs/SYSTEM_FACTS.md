# Synth v2 System Facts

## 1. Purpose and authority

This file is **mandatory orientation** before designing, implementing, or
reviewing any lane in this repository, for humans and AI agents alike.

It is not a duplicate architecture document, not a current-status dashboard,
not a TODO list, and not a substitute for reading the actual code, tests, and
schema/migrations for the lane you are touching.

Authority order when something conflicts:

```text
1. code, tests, schema/migrations (as they exist on current origin/main)
2. canonical TODO/contract docs for the lane in question
3. this file
```

If this file and the code disagree, the code is right and this file is
stale — fix this file, do not silently trust it.

Facts recorded here must be backed by repository evidence (code, schema,
tests, or a canonical doc) or explicitly labelled as an operational decision.
Do not rely on chat memory alone for any statement in this file.

Labels used throughout:

- **Verified system invariant** — checked directly against current code/schema.
- **Current approved scope** — an explicit, current operational boundary; may
  change by explicit decision.
- **Known open correction** — a confirmed gap or wrong assumption that must be
  fixed before dependent work proceeds; not yet fixed.
- **Do not assume** — a capability or property that does not exist and must
  not be inferred.
- **Required architecture/data-integrity boundary** — a non-negotiable
  required behavior; current implementation may be incomplete and must be
  explicitly linked to its open correction.
- **Current approved replay-validation boundary** — the approved standard
  for validating replay claims; it does not assert supporting infrastructure
  is implemented.

## 2. System scope facts

**Verified system invariant.**

```text
Database: MariaDB. Do not describe Synth as PostgreSQL.
```

**Current approved scope.**

```text
Current approved live/runtime venue scope:
Bitvavo spot markets quoted in EUR.
```

This does not imply every research artifact or historical dataset is
Bitvavo-only. **Do not assume** derivative, perpetual, funding, margin, or
carry capability anywhere in this system.

See `docs/database/README.md` for the canonical table-family/schema reference.

## 3. Native SHORT glossary

**Verified system invariant.**

```text
SHORT is a tactical trading-horizon label:
primary interval = 4h
supporting interval = 1h

SHORT does not mean bearish direction, a short sale, derivatives, perps,
funding, carry, or margin.

Current native SHORT maps are spot long-side breakout/reclaim maps:
low -> high anchors
upside targets
invalidation below the anchor low
```

Canonical definition: `docs/architecture/native_short_fib_context_bridge_v1.md`.
Canonical ledger contract: `docs/ops/native_short_map_materializer_canary_v1.md`,
`docs/ops/native_short_map_ledger_health_report_v1.md`.

**Do not assume:**

- no bearish short-archetype strategy;
- no derivatives/perps;
- no funding/carry;
- no automatic interpretation of `SHORT` as sell/short.

## 4. Layer ownership facts

**Verified system invariant.**

```text
selection_engine     = market-only, account-agnostic
decision_gate         = account-aware permission/conflict layer
execution_planner     = immutable execution intent only
executor / agents     = broker order handling only
broker client         = exchange transport only
UI/dashboard/reporting = read-only; never direct broker calls
```

Explicit prohibitions:

- no UI-to-broker shortcut;
- a renderer reads persisted snapshots only;
- `decision_gate` consumes persisted observations or pure freshness
  evaluation, never renderer HTML/JSON as authority;
- no account state in `selection_engine`;
- no execution behavior in `decision_gate`.

See `docs/README.md` §1 and §5 and `AGENTS.md` at repo root for the full
pipeline and the research/live separation rule. `AGENTS.md` is the canonical
owner; `CLAUDE.md` and `CODEX.md` hold provider integration rules only.

## 5. Time, replay, and provenance facts

**Verified system invariant.**

```text
All operational timestamps are UTC.

now_utc is already injected through the relevant native-map materialization/
context path (passed in explicitly, not read from the wall clock at
arbitrary points inside that path).
```

**Required architecture/data-integrity boundary.**

```text
Fetched persisted timestamps must fail closed when absent.
They must not silently become datetime.now(UTC) or utcnow() fallbacks.
```

Current compliance is incomplete: the historical timestamp-integrity
correction below remains open.

**Known open correction — historical timestamp integrity.**

Historical native-map reconstruction must fail closed when a required
persisted timestamp is absent. It must not synthesize a timestamp from
wall-clock time.

Current implementation paths requiring correction must be verified from
current `main` at implementation time; do not rely on stale line numbers in
this file. Canonical replay contract: `docs/research/short_swing_map_outcome_baseline_v1.md`.

**Known open correction — Profit Plan map identity.**

Profit Plan currently derives `map_cycle_id` from a market-context/fib path,
while the native SHORT ledger has its own DB-backed lifecycle identity.

Do not treat a reporting-generated or render-scoped identifier as
authoritative for server-side ladder repair, decision, planning, or
execution.

A single market-owned map identity contract must be established before
deterministic ladder-row identity or authenticated repair preview is
promoted. Canonical context: `docs/todo/profit_plan_live_ladder.md`,
`docs/architecture/native_short_fib_context_bridge_v1.md`.

**Known open correction — Profit Plan delta freshness and runtime ownership.**

The runtime Profit Plan writer renders without a previous canonical snapshot,
so every card shows `delta_status=NO_PREVIOUS_SNAPSHOT` and no
`UPDATED_NOW`/`UNCHANGED` freshness. Proven (2026-07-15 read-only audit): the
live writer is the legacy **user-level** `synth-account-wallet-dashboard@`
render path (builds native SHORT in-render, calls the writer without
`--previous-json`), running in parallel with the safe system-level orchestrator
that intentionally excludes Profit Plan.

The fix is not a renderer-side shortcut: a market-only persisted native SHORT
snapshot (PR A) plus a safe single-owner Profit Plan renderer that loads the
previous canonical `profit-plan.json` and records delta counts (PR B). Canonical
plan: `docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md`.

The repository now defines PR A's market-owned persisted contract in
`docs/architecture/native_short_fib_context_snapshot_contract_v1.md` and
publishes it from the existing 4h owner after the native SHORT scope/map-level
projections. PR B remains a separate dependency and must resolve the immutable
CSV only through the snapshot manifest; this does not authorize host activation
or retirement of the legacy user-level writers.

**Known open correction — runtime/research import boundary.**

Market runtime and native-map materialization must not import `src.research`.

Pure shared market-geometry helpers belong in a non-research module with an
explicit typed contract and focused tests.

**Current approved replay-validation boundary.**

```text
Historical reconstruction alone cannot prove replay parity.
Parity requires captured live shadow-recording inputs, timestamps,
provenance, decisions, and outputs for comparison.
```

Shadow recording and comparison are required before any parity claim and
are not implemented by this document.

**Required architecture boundary.**

```text
Future-aware research/backtest data may exist only in clearly separated
research/backtest lanes and must not leak into market runtime, decision_gate,
execution_planner, executor, or live inference.
```

Current compliance is incomplete until the `src.research` fib/geometry
import is removed from market runtime/materialization (see the runtime/
research import boundary correction above).

See `docs/README.md` §5 and `docs/database/README.md` §2 for the canonical
research/backtest namespace boundary.

Machine-enforced guards for the clock-fallback and research-import
corrections above are a **required/pending guard**, not an implemented one.
Do not claim CI enforcement exists until it is added and verified in the
test suite.

## 6. Live execution facts

**Current approved scope.**

- Live execution is not a UI capability.
- Current live-limit canary work is governed by
  `docs/todo/profit_plan_live_ladder.md`.
- No broker writes, order submission, or executor activation without
  explicit canary approval.
- First canary scope: one allowlisted account, one allowlisted Bitvavo EUR
  market, low cap, passive limit order only.

**Do not assume:**

- market orders;
- automated cancellation;
- autonomous trading;
- stop automation;
- OCO;
- trailing stops;
- multi-account expansion.

**Verified system invariant.**

```text
Client-submitted ladder row identifiers, prices, quantities, map identities,
and freshness claims are untrusted input.

The server must reload canonical persisted observations and validate every
selected row against the current market/account contract before producing a
preview, decision, plan, or execution request.
```

Do not claim broker WebSocket, native stops, OCO, trailing, reduce-only, or
any other exact broker functionality exists unless verified directly against
current code and official Bitvavo API documentation.

## 7. Runtime and freshness facts

- Dashboard rendering is separate from canonical collection/account
  ingestion.
- Renderers never privately poll Bitvavo.
- Stale output must never appear fresh.
- Runtime/logging work must preserve bounded logs, disk-pressure visibility,
  and freshness observability.
- Do not casually re-enable or alter production timers.

These are durable facts, not a current host-status report. For live
incident/backlog state, see the current runtime/ops docs under
`docs/todo/` and `docs/ops/` — that status is time-bound and must not be
copied into this file.

## 8. Design/review checklist

Before designing, implementing, or reviewing any lane:

- [ ] read this file;
- [ ] inspect current `origin/main`;
- [ ] inspect the canonical TODO/contract for the lane;
- [ ] verify the schema is MariaDB;
- [ ] verify venue/product capability from the repo plus official Bitvavo
      documentation;
- [ ] confirm layer ownership for every module touched;
- [ ] identify whether each statement you rely on is verified fact, an open
      gap, or a proposal;
- [ ] never infer a broker capability from a dashboard or an old code path.
