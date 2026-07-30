# TODO — Profit Plan Target Lifecycle History Truth V1

## Status

```text
CONTAINED / COMPLETED (original IOST defect)
Contained by: PR #105 (fail-closed when canonical map truth is unavailable)
Active implementation PR: none justified
Future work: canonical monotonic-lifecycle hardening — PARKED, evidence-gated
Target release: Synth v2.23
Owner: market-data history truth + reporting consumption
```

This lane is no longer an active P1 correctness lane. The original IOST target
"regression" was proven to be a non-canonical reporting-presentation symptom,
not a canonical map lifecycle defect, and it is now contained by PR #105. No
canonical IOST lifecycle bug remains open. Future monotonic-lifecycle hardening
stays parked until real canonical evidence appears (see "Future monotonic
invariant").

## Sources

- User-observed IOST/EUR Profit Plan card and chart on 2026-07-11.
- Accepted read-only forensic audit of the canonical MariaDB native SHORT tables (2026-07-16).
- Read-only live Odroid Profit Plan artifact verification (2026-07-16).
- `src/reporting/manual_short_trader_profit_plan_v1.py`
- `src/reporting/run_manual_short_trader_profit_plan_v1.py`
- `tests/test_manual_short_trader_profit_plan_v1.py`
- `tests/test_profit_plan_action_truth_v1.py`
- `docs/architecture/native_short_map_level_status_contract_v1.md`
- `docs/todo/native_short_map_level_status_v1.md`

## 1. Historical observation (retained as historical evidence)

Original observed card state on 2026-07-11:

```text
market: IOST-EUR
target: 0.0006392232
lifecycle: UPCOMING
guidance: missing sell @ 0.0006392232
```

The chart context showed candles above that target followed by a pullback below
it.

This was a **real historical presentation symptom**: the card did display an
`UPCOMING` target and a `missing sell` guidance line derived from that target.
It was **not canonical lifecycle evidence**. Chart appearance is diagnostic
only and is never runtime authority. The displayed target originated from
transient/research bridge context, not from a persisted canonical map cycle.

## 2. Canonical forensic result

The accepted read-only audit of the canonical native SHORT tables established,
for IOST-EUR:

- zero `native_short_map_scope_v1` rows;
- zero `native_short_scope_support_event_v1` (scope support) events;
- zero `native_short_map_v1` rows;
- zero `native_short_map_generation_event_v1` (generation) events;
- zero `native_short_map_lifecycle_event_v1` (lifecycle) events;
- zero `native_short_scope_status_v1` (scope-status) rows;
- zero `native_short_map_level_status_v1` (map-level status) rows;
- no canonical map ID;
- no canonical map cycle ID;
- no canonical activation boundary (`anchor_end_ts_utc` / `ACTIVATED`);
- no canonical lifecycle state that was ever capable of regressing.

IOST has therefore **never** had a canonical native SHORT scope or map. There
was no canonical activation, so questions such as "did the crossing precede
activation" or "did a `REACHED`/`PASSED` row regress" are moot — no canonical
lifecycle row ever existed for IOST.

**BTC was the sole canonical control scope during the audit** and showed no
equivalent regression: its single active map carried an intact `ACTIVATED`
lifecycle state with a valid map ID and map cycle ID, and no `REACHED`/`PASSED`
state reverted.

## 3. Root cause and classification

- The displayed IOST target (~`0.0006392232`) originated from **transient /
  research bridge context** — the market-only SHORT fib-context bridge / union
  input the Profit Plan reporting surface consumed — not from a persisted
  `native_short_map_v1` row.
- Reporting previously treated this **non-canonical** bridge context as if it
  carried canonical lifecycle and action authority, so a bridge-derived level
  could render as an `UPCOMING` target with a `missing sell` instruction.
- **PR #105 contains this defect.** Reporting now requires real canonical
  status **plus** a real canonical map ID **plus** a real canonical map cycle
  id before applying any canonical lifecycle semantics. When that canonical
  truth is unavailable, the card fails closed to `CONTEXT_UNAVAILABLE` /
  `REVIEW_CONTEXT`, and bridge geometry is disclosed as transient non-canonical
  reference only.

Accepted classification:

```text
NON_CANONICAL_REPORTING_DEFECT_CONTAINED_BY_PR105
```

This is **not** an unresolved canonical IOST lifecycle bug. It was a
non-canonical reporting-presentation defect, now contained.

## 4. Live acceptance evidence (read-only, 2026-07-16)

Canonical published artifact (Odroid runtime host):

```text
artifact: /var/www/html/synth/accounts/joost/profit-plan.json
owner/mode: theone:theone / 644
mtime (UTC): 2026-07-16 20:16:40
generated_ts_utc: 2026-07-16T20:16:40 UTC
top-level render_id: 79d215e2-8790-4b39-9dc0-fef75a58540a
report / version: manual_short_trader_profit_plan_v1 / 0.1
runtime checkout commit: 6b5f3ee (post-PR #105; containment deployed)
```

Current IOST card — fail-closed, canonical semantics withheld:

```text
scenario_type      = CONTEXT_UNAVAILABLE
action_label       = REVIEW_CONTEXT
effective_action   = REVIEW CONTEXT
event_state        = CONTEXT_UNAVAILABLE
actionability_state= CONTEXT_UNAVAILABLE
native_map_status  = DATA_UNAVAILABLE
native map ID      = absent (no canonical map identity)
map cycle ID       = absent (no canonical cycle identity)
active_target      = None (active_target_display = DATA_UNAVAILABLE)
actionable PPP     = actionable_ppp_available=false, pct=None, display=DATA_UNAVAILABLE
target_level_statuses / sell_zone = empty
short_context_display_state = TRANSIENT_NON_CANONICAL_SHORT_CONTEXT
```

No `UPCOMING` target-lifecycle claim and no `missing sell` instruction are
derived from transient context; the card explicitly discloses that canonical
native SHORT map and scope-status truth is unavailable and that displayed
bridge levels are transient non-canonical reference context only.

## 5. Future monotonic invariant (PARKED — evidence-gated)

Preserved as future hardening, not active work. When canonical lifecycle
evidence exists, reporting consumption of canonical map-level status must
uphold:

```text
authoritative post-activation target touch      -> at least REACHED
qualifying authoritative closed-candle continuation where the canonical
    contract defines it                          -> PASSED
REACHED / PASSED / COMPLETED never regress to ACTIVE / NEAR / UPCOMING
    after a pullback
```

A `REACHED` / `PASSED` / `COMPLETED` target must not:

- return as an `active_target`;
- return as actionable upside;
- contribute upcoming-target PPP or urgency;
- produce a `missing sell` instruction as though still ahead.

Implementation is justified **only** when real canonical evidence exists:

- a BTC canonical `REACHED`/`PASSED`-then-pullback case; **or**
- another explicitly approved canonical scope producing equivalent evidence.

Multi-asset rollout is one possible source of such evidence but is **not** the
sole trigger. A single canonical BTC case is sufficient to reopen this
hardening.

## 6. Architecture boundary (retained)

- market-data history truth owns canonical lifecycle evidence;
- reporting consumes that evidence read-only;
- reporting must never reconstruct canonical lifecycle from browser charts or
  transient bridge geometry;
- no `selection_engine` change;
- no `decision_gate` change;
- no `execution_planner` change;
- no executor/agent change;
- no broker calls or writes.

## Addendum (2026-07-31): Separately authorized prospective target-event history

This addendum records a **separate, narrower authorization** layered
alongside this lane's conclusions. It does not reopen, reverse, or weaken
anything above.

Recorded facts, unchanged:

1. The original BTC/IOST canonical evidence gate documented in this file
   remains factually correct: IOST never had a canonical map/scope/lifecycle,
   and BTC (the sole canonical control scope during the audit) showed no
   REACHED/PASSED regression.
2. No qualifying regression evidence has since been found. No BTC canonical
   `REACHED`/`PASSED`-then-pullback case exists, and no other canonical scope
   producing equivalent evidence has been identified.

Newly authorized, separately:

3. Implementation of append-only, **prospective** REACHED/PASSED target-event
   history for native SHORT V1 SELL levels is now authorized under the
   Synth Outcome & Reliability Program, as a required foundation for
   reproducible attribution of *future* target outcomes -- not as a response
   to any lifecycle defect. See
   `docs/architecture/native_short_map_level_status_contract_v1.md`
   ("Addendum: Prospective Target-Event Lifecycle History") for the full
   event-identity, causality, projection, and coverage-boundary contract, and
   `native_short_map_level_target_event_v1.py` for the explicit authorization
   boundary recorded in code.

```text
NO_CANONICAL_REGRESSION_EVIDENCE_FOUND=true
IMPLEMENTATION_JUSTIFICATION=PROSPECTIVE_OUTCOME_EVIDENCE
HISTORICAL_BACKFILL_AUTHORIZED=false
```

4. Historical backfill remains unavailable. Maps published before an
   explicit, operator-chosen coverage watermark are `LEGACY_UNAVAILABLE` for
   target-event purposes; no existing REACHED/PASSED projection row is
   converted into a synthetic historical event without independently proven
   lossless causal-candle evidence, and no such proof has been attempted or
   claimed here.
5. `EXPIRED` target-level detection and `PostTargetReentryProjection` remain
   explicitly deferred and out of scope for this addendum.

This addendum does not change the Status block above, does not reopen the
"Future monotonic invariant" hardening described in Section 5 (that remains
parked, evidence-gated, exactly as written), and does not assert that any
canonical monotonic-regression hardening trigger has occurred.

## Non-goals

- reopening this lane on chart appearance or transient bridge geometry;
- treating TradingView or any browser chart as runtime authority;
- carrying target evidence across unrelated map cycles;
- solving a future regression by changing only the visible label;
- duplicating the multi-asset rollout contract
  (`native_short_multi_asset_rollout_contract_v1.md`) here.
