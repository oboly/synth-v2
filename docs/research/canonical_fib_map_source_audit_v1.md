# Canonical Fib Map Source Audit V1

## Purpose

`canonical_fib_map_source_audit_v1` is a read-only discovery audit for the
next Synth v2.14 strategy-map layer.

It exists because `breath_fibo_strategy_static_dashboard_v1` is now honest:

- `paper_advice_observation` is legacy blackbox advice context only
- `strategy_states_from_legacy_context=0`
- canonical fib-map coverage is currently low
- most assets degrade to `NO_STRATEGY_CONTEXT` or `MAP_INCOMPLETE`

That is correct behavior, but it means the repo still needs a stronger
canonical source for:

- Entry Zone
- Target
- Invalidation Level
- Current Leg
- Support / Reaction Zone
- Anchor / Swing context
- source timestamp / freshness provenance

## Why This Audit Exists

The immediate question is not "build a new strategy".

The immediate question is:

```text
What sources already exist, where are they, how fresh are they,
and which of them are acceptable canonical strategy-map inputs?
```

This audit answers that question without changing dashboard logic, strategy
logic, decision logic, or execution logic.

## Read-Only Boundary

This audit is:

- research-only
- read-only
- market-only
- account-agnostic

It must not:

- write to the DB
- call broker private APIs
- submit orders
- change `selection_engine`
- change `decision_gate`
- change `execution_planner`
- change `executor`

## Scope

The runner audits four source classes:

1. DB table/column discovery through `information_schema`
2. DB row-count / freshness checks for likely candidate tables
3. local research/reporting/docs file discovery
4. explicit audit of `data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv`

It also audits `active_regime_observation` separately because regime context is
allowed as visible market context.

## Paper Advice Rule

`paper_advice_observation` is legacy blackbox advice context.

It may appear in the audit as:

- `LEGACY_ONLY`
- `CONTAMINATION_RISK`
- visible as a discovery source

It must not be recommended as the canonical primary source for:

- Entry Zone
- Target
- Invalidation Level
- Current Leg

## Regime Rule

`active_regime_observation` is allowed as visible market context only.

It may be used for:

- visible regime badges
- visible context lines
- visible market framing

It must not become:

- hidden veto logic
- final advice
- execution permission

Recommendation state for regime in this audit is:

`KEEP_AS_VISIBLE_CONTEXT_ONLY`

## What A Canonical Fib Map Source Must Provide

A canonical strategy-map source should provide, with explicit provenance:

- symbol / venue / interval
- Entry Zone low/high
- one or more target fields
- invalidation level
- current leg / leg direction
- support / reaction context
- anchor / swing context
- source timestamp / freshness timestamp
- clear source module / source method

If these are incomplete, missing, or only present in legacy advice tables, the
source is not canonical-ready.

## Candidate Status Labels

Per canonical field, the audit classifies current source status as one of:

- `CANONICAL_READY`
- `PARTIAL_SOURCE_EXISTS`
- `LEGACY_ONLY`
- `MISSING`
- `CONTAMINATION_RISK`
- `NEEDS_NEW_DERIVED_TABLE`
- `VISIBLE_CONTEXT_ONLY`

These are research metadata labels, not trading signals.

## File Outputs

When `--write-files` is used, the runner writes:

- `table_column_candidates.csv`
- `table_freshness_summary.csv`
- `file_candidates.csv`
- `canonical_field_recommendations.csv`
- `summary.json`

under:

`data/research/canonical_fib_map_source_audit_v1/`

## Source Freshness / Provenance Requirements

Any future canonical strategy-map source should make these questions explicit:

- what table/file produced the value
- which field produced the value
- when that source row was observed
- whether the source is point-in-time safe
- whether the source is operational, research-only, or legacy

Without this provenance, dashboard labels become untrustworthy.

## Relationship To Current Dashboard Work

This audit supports:

- `breath_fibo_strategy_static_dashboard_v1`

It does not change the dashboard.

It identifies whether the next step should be:

- reuse an existing DB table
- promote an existing research CSV into a canonical DB-backed source
- build a new `fib_zone_map_v1`-style canonical table
- ignore legacy sources

## Future Relationship To Later Research

This audit is upstream of any later:

- fib/zone reaction validation
- residual near-miss analysis
- canonical fib-zone map promotion
- source registry / tooltip registry usage

It can also inform later work such as
`fibo_natural_reaction_zone_analysis_v1`, but does not implement that lane.

## Anti-Contamination Rule

Operational tables with historical leakage risk or blackbox logic must be
flagged clearly.

Examples:

- legacy advice tables
- operational execution context tables
- latest-only context joined onto historical analysis

No historical or research backfill should write into operational execution or
advice context tables.

## Next Likely Implementation Step

The expected next step after this audit is one of:

1. promote `fibo_target_map_v1` outputs into a DB-backed canonical fib-zone map
   with coverage/freshness guarantees
2. or build a new canonical derived table if existing sources are too sparse or
   contaminated

That next step should still remain:

- market-only
- explicit-source
- explicit-provenance
- no legacy blackbox advice dependence
