# Multi-TF Conviction Contract v1

Status: Permanent architecture contract (strategy-owned interpretation)
Canonical location: `docs/architecture/multi_tf_conviction_contract_v1.md`
Scope: LONG/MID/SHORT horizon-role composition for per-asset conviction
Runtime impact: none (pure composition module, no wiring to production evidence yet)
Issue: #591
Upstream owner: #243 (`docs/architecture/multi_horizon_signal_contract_v1.md`)

## 1. Purpose

Profit Potential Percentage (PPP) expresses upside to a profit-plan target,
not whether this is a good moment to allocate capital. A single scalar
conviction/regime score is also too binary: short-term weakness can coexist
with an intact long-term thesis. This contract defines the strategy-owned
horizon-role interpretation that keeps those three questions separate:

```text
LONG  = thesis continuity / capital-floor semantics
MID   = tactical exposure / allocation-weight semantics
SHORT = entry/add timing semantics
```

Core invariant: the same asset may simultaneously be LONG strong, MID
weak/neutral, and SHORT weak, without collapsing those horizons into one
opaque scalar.

This is exactly the strategy interpretation `docs/architecture/multi_horizon_signal_contract_v1.md`
(#243) section 6 reserves to a downstream strategy: *"LONG = thesis, MID =
exposure, SHORT = entry timing is a strategy interpretation, not a generic
truth created by this contract."* #591 is that strategy, and this document
is its reviewed contract.

## 2. Repository audit (as of this implementation)

Before implementing, the repository was searched for an existing canonical,
production (non-research), per-asset evidence producer that already exposes
the full `SignalHorizonV1` contract (`effective_horizon`, `freshness`,
`asof_ts`, `model_id`/`model_version`, `provenance`) per #243 section 3.

Findings:

- `effective_horizon` as a literal field exists only in the #243 contract
  document itself and in `src/research/multi_horizon_rotation_replay_v1.py`
  (Issue #593), which is research-only and explicitly excluded from
  production use by this contract.
- `src/signal_engine/signal_engine.py` and `src/signal_engine/expansion_rotation.py`
  (the existing composition-primitive precedent this module follows
  structurally) interpret trend/volume/phase/compass/rotation/setup/risk
  signal strings into one opaque `conviction_total`-style scalar. No
  per-signal horizon, freshness, or provenance metadata is exposed, and the
  output is a single blended score — the exact pattern #243 and this
  contract forbid for new work.
- `src/market_context/` (`market_context_builder_v1.py`,
  `local_ma_atr_context_v1.py`, `impulse_health_state_v1.py`) is a
  production, per-symbol, deterministic composition module with real
  freshness-like sentinel states and an as-of timestamp. It is scoped to
  *short-selling exit* context ("Manual SHORT Trader Profit Plan"), a
  different sense of "SHORT" than the #591 SHORT-time-horizon sense. Reusing
  it here would silently conflate two unrelated meanings of "SHORT" and was
  rejected for that reason.
- Market Rotation Pressure V1 (#243 section 7.1) is the one canonical,
  accepted, versioned, persisted per-asset lane with real `asof_ts` and
  `model_version`. Its canonical `effective_horizon` is `REGIME` (single
  horizon, 24h+168h composed), not separable into independent LONG/MID/SHORT
  observations without inventing a mapping #243 does not authorize.
- Issue #617 (regime evidence matrix / multi-TF momentum-trend reporting) —
  the most likely future source of genuinely independent per-horizon
  evidence — is open with no implementation on `main`.
- Issue #593's per-asset multi-horizon Rotation variants are research-only
  and, per the #591 task contract, must not be consumed as production truth
  here.

Conclusion: **no existing production module currently satisfies the
`SignalHorizonV1` contract for LONG, MID, and SHORT independently.** Per
#243 section 5 ("Where deterministic relation semantics have not yet been
validated for a producer pair, preserve the raw signals and emit
`NOT_COMPARABLE` or `INSUFFICIENT_DATA`") and the #591 task contract's own
instruction ("if no accepted/replay-safe input exists for a horizon,
preserve that horizon as `INSUFFICIENT_DATA` rather than inventing logic"),
this first slice implements the deterministic **composition contract only**.
It does not wire any concrete evidence source. Every horizon without a
supplied, fresh, replay-safe `HorizonEvidenceV1` fails closed to
`CONVICTION_INSUFFICIENT_DATA`. Wiring a real per-horizon evidence adapter is
explicitly deferred to a follow-up issue once a canonical producer exists for
that horizon (most plausibly #617 for MID/SHORT, and a to-be-identified
structural/macro-cycle owner for LONG).

## 3. Module

`src/signal_engine/multi_tf_conviction_v1.py`

Chosen home: `signal_engine`, per `AGENTS.md`'s layer table ("market
interpretation from features"). This module interprets already-produced,
already-interpreted per-horizon evidence; it does not compute features
itself and does not touch `selection_engine`, `decision_gate`,
`execution_planner`, or `executor`.

Structural precedent: `src/signal_engine/expansion_rotation.py` (typed,
frozen-dataclass `Input`/`Output`, pure function, no I/O, no DB, tested via
injected fixtures). This module follows the same shape, but keeps the three
horizons independent instead of blending them.

### 3.1 Input: `HorizonEvidenceV1`

A deliberately reduced, honestly-scoped subset of `SignalHorizonV1`:

```text
horizon         LONG | MID | SHORT
state           EVIDENCE_STATE_* (already-interpreted, caller-owned)
freshness       FRESH | STALE | INSUFFICIENT_DATA | UNKNOWN   (#243 §3.5 vocabulary)
asof_ts         datetime | None
replay_safe     bool  -- False means research-only / not yet accepted; fails closed
model_id        str
model_version   str
provenance      str
confidence      float | None
reason_codes    tuple[str, ...]
```

The caller (a future, separately reviewed adapter task) is responsible for
mapping whatever canonical per-horizon evidence it owns into the small
`EVIDENCE_STATE_*` vocabulary (`STRONG_POSITIVE`, `POSITIVE`, `NEUTRAL`,
`NEGATIVE`, `INVALIDATING`) before calling this module. This module never
sees raw candles or indicators and never recomputes them.

### 3.2 Output: `HorizonConvictionResultV1` / `MultiTFConvictionV1`

Per horizon: `conviction_state` (`STRONG | MODERATE | WEAK | INVALIDATED |
INSUFFICIENT_DATA`), deterministic `reason_code`, a horizon-scoped derived
advisory state (`capital_floor_state` for LONG, `exposure_state` for MID,
`entry_add_timing_state` for SHORT), plus `confidence`, `freshness`,
`asof_ts`, `model_id`, `model_version`, `provenance`, and the evidence's own
`reason_codes` — all preserved even in the fail-closed case, per #243
section 9 ("operator detail must preserve model/version and as-of
provenance").

`MultiTFConvictionV1` bundles `conviction_long`, `conviction_mid`,
`conviction_short` for one `symbol` at one `generated_at_utc`. There is no
aggregate/average/overall field anywhere in this contract, and
`compose_multi_tf_conviction_v1` structurally cannot produce one: it is
three independent calls to `evaluate_horizon_conviction_v1`, one per
horizon, with no shared state.

### 3.3 Derived advisory semantics

Advisory/market-interpretation labels only. They grant no permission and
create no execution intent; nothing in this module reaches `decision_gate`,
`execution_planner`, or `executor`. No BUY/SELL language.

```text
LONG  -> capital_floor_state:      CORE_INTACT | CORE_AT_RISK | CORE_COLLAPSED | UNKNOWN
MID   -> exposure_state:           EXPAND_EXPOSURE | MAINTAIN_EXPOSURE | REDUCE_EXPOSURE | SUPPRESS_EXPOSURE | UNKNOWN
SHORT -> entry_add_timing_state:   FAVORABLE_ADD_TIMING | NEUTRAL_TIMING | UNFAVORABLE_TIMING | BLOCK_ADD_TIMING | UNKNOWN
```

Each derived state is computed only from that same horizon's own
`conviction_state` — never from another horizon's evidence or result.

## 4. Fail-closed rules

In evaluation order, any of the following forces `CONVICTION_INSUFFICIENT_DATA`
before a real conviction state is ever derived:

1. missing evidence (`EVIDENCE_MISSING`);
2. evidence bound to the wrong horizon slot (`EVIDENCE_HORIZON_MISMATCH`);
3. `replay_safe=False`, i.e. research-only / not yet accepted (`EVIDENCE_NOT_REPLAY_SAFE`);
4. `asof_ts=None`, i.e. no as-of timestamp regardless of claimed freshness (`EVIDENCE_ASOF_MISSING`);
5. `freshness=STALE` (`EVIDENCE_STALE`);
6. `freshness=INSUFFICIENT_DATA` (`EVIDENCE_INSUFFICIENT_DATA`);
7. any other non-`FRESH` freshness, including `UNKNOWN` (`EVIDENCE_FRESHNESS_UNKNOWN`);
8. an evidence `state` outside the known vocabulary (`EVIDENCE_STATE_UNRECOGNIZED`).

## 5. Non-goals of this slice

- No wiring of any concrete production evidence source (see §2).
- No reporting/dashboard/UI changes. No Profit Plan integration.
- No `selection_engine`, `decision_gate`, `execution_planner`, or `executor`
  changes.
- No account awareness, no broker calls, no order submission.
- No CQ weighting changes, no PPP semantic changes.
- No DB schema changes, no DB writes.
- No numeric conviction score — no existing canonical numeric conviction
  scale exists to justify one, so this slice uses a discrete, inspectable
  state enum instead of inventing a new opaque number.

## 6. Acceptance mapping

| #591 acceptance criterion | Where proven |
|---|---|
| Same asset simultaneously LONG strong / MID weak / SHORT weak | `test_long_strong_mid_weak_short_weak_remains_three_distinct_states` |
| SHORT deterioration does not invalidate LONG | `test_short_deterioration_alone_does_not_change_long` |
| MID deterioration changes only MID/exposure | `test_mid_deterioration_changes_only_mid_semantics` |
| SHORT recovery reopens timing, LONG continuity intact | `test_short_recovery_transitions_timing_upward_while_long_continuity_intact` |
| LONG invalidation collapses only LONG/capital-floor | `test_long_invalidation_collapses_only_long_semantics` |
| Stale input -> explicit insufficient state | `test_stale_evidence_yields_explicit_insufficient_state` and related |
| Missing input -> explicit insufficient state | `test_missing_evidence_yields_explicit_insufficient_state` |
| Conflicting horizon evidence stays visible | `test_conflicting_horizon_evidence_remains_visible_not_forced_to_consensus` |
| No opaque cross-horizon average | `test_output_has_no_aggregate_or_average_field` |
| Research-only upstream fails closed | `test_research_only_evidence_fails_closed` |
| Missing `asof_ts` fails closed despite `freshness=FRESH` | `test_missing_asof_ts_fails_closed_even_when_freshness_claims_fresh` |
| Deterministic reason codes / provenance survive output | `test_healthy_evidence_carries_deterministic_provenance`, `test_composition_is_deterministic_across_repeated_calls` |

## 7. Safety

```text
market_only=1
account_awareness=0
selection_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_evidence_wired=0
production_deploy=0
```

## 8. Related documents / issues

- `docs/architecture/multi_horizon_signal_contract_v1.md` (#243, canonical upstream owner)
- #591 Multi-TF Conviction
- #593 multi-horizon per-asset Rotation research/history (research-only input, not consumed here)
- #617 regime evidence matrix / multi-TF momentum-trend reporting (not yet implemented; future evidence source candidate)
- `src/signal_engine/expansion_rotation.py` (structural precedent)
