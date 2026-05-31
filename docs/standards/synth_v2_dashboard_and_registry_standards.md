# Synth V2 Dashboard And Registry Standards

## Purpose

This document defines the current display and registry standards for Synth
v2.14 dashboard and research surfaces.

The goal is to prevent:

- scattered ALL CAPS labels
- inconsistent badge names
- tooltip chaos
- hidden source ambiguity
- legacy blackbox context leaking into strategy dashboards

## Core Display Rule

Dashboards show conflicts.
They do not secretly resolve them.

Each timeframe or context layer may have its own truth.

## Raw Measurements First

Raw numeric fields are canonical.
Derived category labels are optional display helpers only.

Canonical phrase:

```text
Raw numeric measurement first.
Derived labels only when explicitly needed for display, validation grouping,
or registry-backed UI.
Never replace measurement with category.
```

Examples:

- use `swing_range_pct` as the canonical field
- do not replace `swing_range_pct` with lossy category labels
- if a display band is needed, it must be clearly derived from
  `swing_range_pct`
- derived display helpers must not drive strategy logic

## No Unrequested Abstraction

Do not introduce new ALL CAPS categories, buckets, flags, or state labels
unless:

- the user explicitly requests them
- there is a concrete dashboard display need
- there is a validation/backtest grouping need
- the label is added to a registry with description plus allowed/forbidden
  context

## Machine Keys vs UI Text

ALL CAPS labels are machine keys.

User-facing names and descriptions should come from registries, not from
scattered hardcoded tooltip text.

Standards:

- machine key remains stable
- display name can be humanized
- short description should be registry-backed
- long description should be registry-backed
- badge tone should be registry-backed where practical

Known registries:

- `research_label_registry_v1`
- `research_level_attractor_registry_v1`

## Canonical User-Facing Terms

### Entry Zone

`Entry Zone` is the canonical user-facing term.

Do not use these as dashboard labels:

- reload zone
- rebuy zone
- reload/rebuy zone
- buy dip zone

They may still exist in raw historical/research notes, but not as canonical v2.14
dashboard terms.

## Legacy Paper Context Rule

`paper_advice_observation` is legacy blackbox context only.

It must not drive strategy states in v2.14 strategy dashboards.

It may be shown only as:

- legacy context
- debug context
- source provenance context

It must not be used as the primary source for:

- Entry Zone
- Target
- Invalidation Level
- Current Leg

## Regime Context Rule

`active_regime_observation` is visible market context only.

It may be shown in dashboards as:

- visible regime framing
- visible context badge/text
- research context

It must not become:

- hidden veto logic
- final advice
- decision permission
- execution permission

## Canonical Fib-Zone Map Rule

`canonical_fib_zone_map_v1` is the intended canonical source for:

- Entry Zone
- Target
- Invalidation Level
- Current Leg
- Support / Reaction Zone
 - Anchor / Swing context

It should eventually replace legacy advice dependencies for the
Breath/Fibo-first strategy dashboard.

## Provenance / Missing-Data Rule

Dashboards must show source/provenance/missing data clearly.

Required behavior:

- show source module/file/table when practical
- show missing-source states explicitly
- show freshness explicitly
- do not silently backfill from legacy blackbox context

## Forbidden Final Advice Labels

Do not use these as final v2.14 strategy-dashboard conclusions:

- `BUY_READY`
- `SELL_NOW`
- final `AVOID`
- final `WATCH_ONLY`

Dashboard states must remain descriptive strategy/research hypotheses only.

## Swing Percentage Standard

`swing_range_pct` is the canonical swing-size field.

Raw measured percentages should be used for:

- validation
- backtests
- optimization
- threshold research

If a display helper is needed, `swing_pct_band` may be used as optional
derived metadata only:

- `<8`
- `8-25`
- `25-60`
- `>=60`
- `UNKNOWN`

This helper must not change strategy logic or map-quality logic.

It must not replace the canonical measured field.

## Registry Standards

### `research_label_registry_v1`

Use for:

- label/state metadata
- display names
- tooltip descriptions
- badge tones

### `research_level_attractor_registry_v1`

Use for:

- fibo constants
- natural constants
- prime/harmonic number metadata
- future residual/attractor research labels

## Hardcoding Rule

New dashboard labels, badge meanings, and canonical constant descriptions
should be added to registries and docs, not scattered as local tooltip chaos.

## Writer Preview Standard

Preview writers may generate measured fields and provenance.
They should not invent semantic labels unless needed.

For `canonical_fib_zone_map_writer_preview_v1`:

- keep `swing_range_pct`
- do not add `map_horizon_bucket`
- do not add `dirty_swing_candidate`
- do not add lossy swing category labels unless they are explicitly requested
  later as derived display metadata only

## Boundary

These standards are:

- reporting-only
- research-display only

They do not authorize:

- `selection_engine` logic
- `decision_gate` permission
- `execution_planner` intent
- `executor` behavior
- strategy execution
- broker calls
- broker writes
- order logic
- orders
- account-aware logic
- account-aware sizing
- account-aware allocation
