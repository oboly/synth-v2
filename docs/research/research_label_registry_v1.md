# Research Label Registry V1

## Purpose

`research_label_registry_v1` is the canonical metadata registry for ALL CAPS
dashboard and research labels.

It exists to prevent:

- scattered undocumented labels
- inconsistent badge names across reports
- tooltip chaos
- duplicated or drifting label meaning
- raw machine labels leaking directly into user-facing text

This registry is metadata only.

It does not:

- create strategy logic
- create signals
- create permissions
- create orders
- change runtime behavior

## Core Rule

```text
ALL CAPS is the machine key.
UI text comes from the registry.
```

Dashboards and research reports may later use this table for:

- display names
- badge tones
- short tooltip text
- long descriptions
- severity ordering
- allowed/forbidden usage hints

They should not keep inventing label descriptions ad hoc in each renderer.

## Table

Canonical table:

```text
research_label_registry_v1
```

This is a research/display metadata table only.

## Columns

- `label_key`
  - stable machine key, usually ALL CAPS
- `label_type`
  - high-level type, such as:
    - `STRATEGY_STATE`
    - `SOURCE_STATUS`
    - `FRESHNESS_STATE`
    - `MAP_STATE`
    - `VALIDATION_STATE`
    - `REACTION_ROLE`
- `category`
  - broader functional bucket
- `family`
  - subgroup within the category
- `display_name`
  - human-facing canonical text
- `short_description`
  - compact tooltip or badge help text
- `long_description`
  - fuller research/dashboard explanation
- `ui_tone`
  - suggested visual tone such as:
    - `ok`
    - `warn`
    - `bad`
    - `context`
    - `muted`
- `severity_rank`
  - deterministic sorting / importance hint
- `research_status`
  - defaults to `DISPLAY_ONLY`
- `allowed_context`
  - where the label may be shown later
- `forbidden_context`
  - where the label must not be used
- `is_terminal`
  - whether the label is a terminal display state
- `is_actionable`
  - whether the label implies action
  - all initial seeded rows set this to `0`
- `is_enabled`
  - metadata enable flag
- `sort_order`
  - deterministic display ordering
- `created_at_utc`
  - creation timestamp

## Seeded Label Types

Initial seeded types:

- `STRATEGY_STATE`
- `SOURCE_STATUS`
- `FRESHNESS_STATE`
- `MAP_STATE`
- `VALIDATION_STATE`
- `REACTION_ROLE`

These are all seeded as metadata only.

## Why This Exists

Research dashboards now use many machine labels such as:

- `ENTRY_ZONE_NEAR`
- `INVALIDATION_NEAR`
- `TARGET_TOUCHED_TP_REVIEW`
- `FIB_MAP_UNKNOWN`
- `MISSING_SOURCE`
- `FRESH`

Without a canonical registry, every new dashboard risks:

- inventing slightly different human wording
- using inconsistent tones
- losing the exact meaning of old labels
- showing machine keys without proper explanation

This table provides a single source of truth for future display metadata.

## Research Boundary

This lane is:

- research-only
- display-metadata-only
- account-agnostic

Forbidden:

- runtime signal generation
- strategy routing
- decision permission
- execution intent
- broker integration
- order logic

Hard boundaries:

```text
No dashboard runtime wiring required yet
No strategy logic
No account-aware logic
No broker calls
No broker writes
No orders
No decision_gate changes
No execution_planner changes
No executor changes
No selection_engine changes
```

## Relationship To Dashboards And Reports

Later dashboards should use this registry for:

- canonical badge display names
- tone styling hints
- short hover/help text
- long explanation text
- deterministic grouping and ordering

Likely consumers later:

- `breath_fibo_strategy_static_dashboard_v1`
- future signal-matrix dashboards
- reaction-zone validation reports
- residual / attractor analysis reports

## Relationship To Validation Work

The validation labels seeded here:

- `FIBO_EXPLAINED`
- `FIBO_NEAR_MISS`
- `NON_FIBO_REACTION`
- `NATURAL_EXPLAINED_RESIDUAL`
- `PRIME_EXPLAINED_RESIDUAL`
- `RANDOM_EQUIVALENT`
- `UNEXPLAINED`

are intended for later research reporting only.

They must not become runtime logic until the underlying validation lanes exist
and beat proper baselines.

## Anti-Tooltip-Chaos Rule

Research dashboards should not hardcode tooltip explanations separately in many
places when the same label already exists in the registry.

Correct later pattern:

```text
machine label
-> registry lookup
-> display name + tone + tooltip text
```

Wrong pattern:

```text
same label copied into many dashboards with slightly different meaning
```
