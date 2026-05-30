# Breathline 639 Phase Ratio Model V1

## Purpose

`breathline_639_phase_ratio_model_v1` stores the `6:3:9` Breathline model as
a research-only variable phase-ratio scaffold.

It is intended for:

- cycle annotation
- replay interpretation
- phase-window comparison
- later research overlays

It is not:

- a primitive market signal
- a strategy rule
- a timing oracle
- an execution input

## Core Concept

Use `6:3:9` as a variable phase-ratio model, not fixed days.

Phase interpretation:

- `6 units` = expansion / bullish pressure / build
- `3 units` = containment / pause / compression
- `9 units` = release / exhale / correction / overshoot
- `rest` = stillness / reset before next cycle

## Ratio Definition

Total ratio units:

```text
18
```

For any observed `cycle_length`:

```text
expansion_duration   = cycle_length * 6 / 18
containment_duration = cycle_length * 3 / 18
release_duration     = cycle_length * 9 / 18
```

This means the model scales with observed cycle length.
It does not assume a fixed calendar duration.

## Examples

Example: `21-day cycle`

- `6 units` ≈ `7 days`
- `3 units` ≈ `3.5 days`
- `9 units` ≈ `10.5 days`

Example: `18-day cycle`

- `6 units` = `6 days`
- `3 units` = `3 days`
- `9 units` = `9 days`

## Release Phase Interpretation

The `9-unit` release phase is not direction-fixed.

It can resolve differently depending on phase quality:

- clean continuation -> expansion
- overextension -> correction
- late dirty phase -> squeeze then dump
- reset -> chop

This model therefore describes phase proportion, not guaranteed direction.

## Research Boundary

This model is:

- research-only
- cycle scaffold only

This model must not be used as:

- primitive market signal
- direct strategy rule
- hidden timing oracle
- selection policy
- decision permission
- execution trigger

Hard boundaries:

```text
No selection_engine changes
No decision_gate changes
No execution_planner changes
No executor changes
No broker calls
No broker writes
No orders
```

## Validation Requirements

The model should be validated per symbol against:

- observed breath rhythm
- A+ phase labels
- Synth curve/reload context
- catalyst flags
- dirty squeeze flags
- forward returns
- MFE/MAE
- retest / continuation / fade outcomes

The point is not to assume the ratio is true.
The point is to test whether it is a useful annotation scaffold.

## Relationship To Replay And Matrix Work

This model may later annotate:

- `signal_matrix_single_asset_replay_v1`
- `breathline_symbol_timeline_report_v1`
- later phase-aware chart review studies

It must not be embedded into the primitive replay runner as a decision rule.

Correct relationship:

```text
primitive replay
-> optional Breathline phase annotation
-> research comparison
-> validation
```

Forbidden relationship:

```text
Breathline 639 ratio
-> hidden runtime timing rule
-> strategy action
-> order logic
```

## Status

Current status:

```text
research scaffold only
not promoted
not runtime logic
```
