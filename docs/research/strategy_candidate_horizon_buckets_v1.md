# Strategy Candidate Horizon Buckets V1

## Status
- Research / design note only.
- No implementation. No runtime wiring. No DB schema changes. No code changes.
- Market-only concept. Account-agnostic throughout.
- Not a buy/sell signal. Not an order. Not an execution intent.

---

## Problem: asset-level ranking is too blunt

A selection engine that ranks bare assets — "BTC rank 1, AVAX rank 2, APT rank 3" — conflates independent signals that operate on different horizons, setup contexts, and validation states.

The same asset can simultaneously be:
- a strong long-term institutional cycle candidate
- a weak or neutral short-term momentum candidate
- an active breath curve extension signal
- off-limits for a moonshot asymmetry setup because tokenomics have not cleared

Treating these as a single score forces a false choice: either rank the asset high (and implicitly endorse every setup) or rank it low (and implicitly discard every setup). Neither is correct.

---

## Design Rule: Asset ≠ Strategy

The correct unit of selection ranking is a **strategy candidate**, not an asset.

```
candidate = (
    asset,
    strategy_family,
    horizon_bucket,
    setup_context,
    validation_state,
)
```

A candidate represents one specific thesis about one asset at one horizon. Multiple candidates for the same asset can coexist, be ranked independently, and resolve to conflicting or reinforcing positions only at the decision_gate / portfolio layer — where account state, sleeve exposure, and permission are finally introduced.

---

## Horizon Buckets

### SHORT_TERM_SPIKE
Timeframe: hours to a few days.
Thesis: rotational burst, momentum continuation, or news-driven impulse.
Example: APT catching an alt-rotation burst off BTC consolidation.
Notes: typically lower conviction, higher velocity. Breath curve short-burst setups may qualify here.

### MEDIUM_TERM_SWING
Timeframe: days to weeks.
Thesis: TA structure, breakout-retest, range expansion, or regime continuation.
Example: AVAX reclaiming a legacy L1 structural level with target ladders above.
Notes: standard TA and PRO zone levels are the primary input signals.

### LONG_TERM_CYCLE
Timeframe: weeks to months.
Thesis: macro cycle participation, institutional accumulation phase, or sector rotation target.
Example: APT as an RWA / institutional tokenization cycle candidate.
Notes: shoulder-zone levels are target zones and reaction zones, not late buy-confirmation triggers.

### MOONSHOT_ASYMMETRY
Timeframe: open-ended; entry is an asymmetric position in a low-cap or high-risk token.
Thesis: outsized return potential relative to size, with known binary risk (e.g. unlock cliff, tokenomics event, sector adoption).
Example: SXT — high-asymmetry long-term moonshot, but elevated unlock / tokenomics risk.
Notes: validation state must explicitly flag open risk factors. Not compatible with large sleeve sizing.

### MACRO_REGIME_ANCHOR
Timeframe: macro; not traded tactically.
Thesis: asset serves as a regime reference or safe-harbor anchor rather than an active rotational target.
Example: BTC as MACRO_REGIME_ANCHOR during altcoin accumulation phases.
Notes: ranking reflects regime health, not momentum. Execution intent from this bucket is rare.

### BREATH_CURVE_RESEARCH
Timeframe: snapshot-driven; horizon is the snapshot validation window.
Thesis: A+ Breathline / harmonic phase label correlates with forward outcome at a specific horizon.
Example: RENDER / BREATH_CURVE_EXTENSION / 0.786_IGNITION — breath curve coherence signal at harmonic ignition zone.
Notes: research-only until label-outcome validation accumulates enough snapshots. No runtime promotion without validated label set.

---

## Candidate Examples

| Asset  | Strategy Family        | Setup Context              | Notes |
|--------|------------------------|----------------------------|-------|
| APT    | LONG_TERM_CYCLE        | PRO_DIP_ACCUMULATION       | RWA / institutional thesis; shoulder zones are target levels |
| APT    | SHORT_TERM_SPIKE       | ALT_ROTATION_BURST         | Independent short-term setup; does not inherit long-term conviction |
| SXT    | MOONSHOT_ASYMMETRY     | PRO_DIP_ACCUMULATION       | High asymmetry; tokenomics / unlock risk must be flagged in validation_state |
| AVAX   | MEDIUM_TERM_SWING      | LEGACY_L1_RECLAIM          | $143–$146 PRO shoulder = major resistance / target / reaction zone |
| AVAX   | LONG_TERM_CYCLE        | CYCLE_TARGET_LADDER        | Shoulder zones as progression targets, not entry signals |
| RENDER | BREATH_CURVE_RESEARCH  | 0.786_IGNITION             | Breath curve / harmonic phase label; research-only until validated |
| BTC    | MACRO_REGIME_ANCHOR    | BREAKOUT_RETEST            | Regime reference; execution intent rare |

---

## Shoulder-Zone Interpretation

External PRO research often marks key shoulder lines:
- AVAX: $143–$146
- APT: $20.51
- SXT: $0.16

**These levels are primarily major resistance / target / reaction zones** — not necessarily late buy-confirmation triggers.

After price reaches such a zone, a period of dip or horizontal consolidation is expected before any continuation. A candidate with a LONG_TERM_CYCLE or CYCLE_TARGET_LADDER setup context should model the shoulder zone as a progression waypoint, not a chasing signal. The correct interpretation is:

> "If price reaches $143–$146 on AVAX, a reaction dip or consolidation is likely. That dip may be the next accumulation window — not the moment to chase the breakout."

This applies to all PRO-sourced shoulder levels ingested by the system.

---

## Architecture Boundaries

| Layer              | Responsibility                                                  | May touch candidates? |
|--------------------|------------------------------------------------------------------|----------------------|
| selection_engine   | Rank strategy candidates. Market-only. Account-agnostic.        | Yes — rank only      |
| decision_gate      | Account-aware permission. Sleeve / exposure / bucket conflicts. | Yes — resolve only   |
| execution_planner  | Convert granted permission into execution plan.                  | No candidate logic   |
| executor / agents  | Order operations only.                                           | No candidate logic   |

The selection_engine ranks candidates. It does not resolve:
- capital allocation
- account exposure or portfolio bucket conflicts
- position sizing
- account permissions
- order intent

Those are decision_gate responsibilities.

---

## Non-Goals

- No live trading from this design note.
- No BUY_READY signals.
- No sizing or capital allocation logic.
- No account state or sleeve awareness in the selection layer.
- No execution logic.
- No broker calls.
- No DB writes from this document.
- The BREATH_CURVE_RESEARCH bucket is research-only until validated; it does not feed runtime selection.

---

## Future Validation Questions

1. **Can one asset hold multiple active candidates simultaneously?**
   Likely yes — the design explicitly allows it. The open question is how the decision_gate surfaces and resolves them when sleeve capacity is limited.

2. **How do candidates conflict or reinforce each other?**
   A LONG_TERM_CYCLE and a SHORT_TERM_SPIKE candidate for the same asset may coexist in the selection layer but require explicit conflict / reinforcement logic at the decision_gate (e.g. same-direction reinforces position; opposite-direction requires a tiebreak rule).

3. **Should selection_engine rank per horizon bucket independently?**
   Probably yes — a single cross-bucket score obscures the signal. A per-bucket rank preserves the independence of each thesis.

4. **How should decision_gate resolve exposure when multiple active candidates target the same asset?**
   Open design question. Likely resolved by sleeve budget, existing position, and candidate priority ordering — but the policy has not been specified.

5. **When does a BREATH_CURVE_RESEARCH candidate graduate to a runtime-eligible bucket?**
   After the label-outcome validation lane accumulates sufficient snapshots and the label group shows consistent forward return correlation. The graduation path runs through its own preview table and must never bypass decision_gate.

---

## Summary Rule

> An asset is not a strategy.
>
> The selection engine ranks (asset, strategy_family, horizon, setup_context, validation_state) tuples — not raw assets.
>
> One asset may have multiple independent active candidates at the same time. Their conflicts and capital allocation are resolved by the decision_gate, not the selection engine.
>
> PRO shoulder zones are resistance / target / reaction levels, not late buy-confirmation triggers.
