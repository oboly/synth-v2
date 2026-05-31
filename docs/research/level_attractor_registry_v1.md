# Level Attractor Registry V1

## Purpose

`research_level_attractor_registry_v1` is the canonical metadata registry for
level-attractor hypotheses used in later research.

It exists to prevent:

- scattered hardcoded level descriptions
- tooltip chaos across research dashboards
- duplicate natural/fibo/prime constant definitions
- undocumented residual-level experiments

This registry is metadata only.

It does not:

- create signals
- rank assets
- route decisions
- generate orders
- change runtime logic

## Research Boundary

This lane is:

- research-only
- metadata-only
- account-agnostic
- dashboard/reporting support only

It must not be used directly by:

- `selection_engine`
- `decision_gate`
- `execution_planner`
- `executor`
- broker code
- order logic

Hard boundary:

```text
No strategy logic
No dashboard logic changes required yet
No selection_engine changes
No decision_gate changes
No execution_planner changes
No executor changes
No broker calls
No broker writes
No orders
No account-aware logic
```

## Table

Canonical table name:

```text
research_level_attractor_registry_v1
```

This table stores canonical labels, numeric values, expressions, descriptions,
and intended test contexts for later research lanes.

## Columns

- `attractor_key`
  - stable canonical key
- `display_name`
  - human-readable label for dashboards/tooltips
- `category`
  - top-level group such as `STANDARD_FIBO` or `PRIME_RATIO`
- `family`
  - subgroup such as `RETRACEMENT`, `EXTENSION`, `PRIME_OFFSET`
- `numeric_value`
  - deterministic numeric form when one exists
- `value_expression`
  - textual form such as `phi`, `3/2`, or `137_bps`
- `unit_type`
  - semantic unit such as:
    - `MULTIPLIER`
    - `RATIO`
    - `BPS`
    - `CANDLE_COUNT`
    - `OFFSET`
- `description`
  - what the level is
- `intended_test_context`
  - how later research should test it
- `validation_status`
  - default `UNVALIDATED_RESEARCH`
- `is_enabled`
  - metadata enable/disable flag
- `sort_order`
  - deterministic display ordering
- `created_at_utc`
  - registry row creation timestamp

## Seeded Categories

Initial seeded categories:

- `STANDARD_FIBO`
- `WHOLE_HALF`
- `PHI_PI_E`
- `SQRT_CONSTANT`
- `HARMONIC_NUMBER`
- `PRIME_RAW`
- `PRIME_BPS_OFFSET`
- `PRIME_CANDLE_WINDOW`
- `PRIME_RATIO`

## Why Standard Fibo Comes First

Standard fibo is the first validated lane.

It must remain the first comparison set for:

- support / resistance
- retest levels
- entry zone edges
- target magnets
- overshoot margins

Natural constants, prime-derived levels, and harmonic-number offsets are later
residual hypotheses only.

Correct progression:

```text
standard fibo validation first
-> identify fibo near-miss / non-fibo reaction residuals
-> compare natural/prime/harmonic candidates
-> compare against null/random baselines
-> only then consider promotion
```

## Dashboard / Tooltip Use Later

Later research dashboards may use this table as the canonical source for:

- level display names
- tooltip text
- category/family grouping
- test-context descriptions
- validation-status display

That avoids hardcoding descriptions across multiple dashboard runners.

It does not mean dashboards should treat these rows as valid market truth.

## Future Relationship

This registry is intended to support later work such as:

```text
fibo_natural_reaction_zone_analysis_v1
```

and related residual / reaction-zone validation lanes.

Likely future roles:

- candidate reaction level registry
- residual near-miss comparator source
- tooltip/legend source for research charts
- canonical attractor taxonomy across studies

## Anti-Pareidolia Rule

Attractors are hypotheses, not truths.

No attractor may become strategy input until it beats:

- random baselines
- null baselines
- naive round-number comparators
- standard fib baselines where applicable

Required principle:

```text
interesting visual fit is not enough
```

The registry is specifically designed to stop pattern-recognition drift from
becoming hidden logic.

## Level Roles To Test Later

Future research may test each attractor in roles such as:

- support
- resistance
- retest level
- entry zone edge
- target magnet
- fakeout zone
- overshoot margin
- no reaction

Those roles are later validation targets only.
They are not implied by the registry itself.
