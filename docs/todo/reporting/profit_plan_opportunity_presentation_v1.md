# Profit Plan Opportunity Presentation v1

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- compact field, tooltip registry, duplicate-tile removal, alignment -> Issue #233 (pre-existing)
- Sort-PPP null-last ordering and deterministic tie-breaks -> Issue #256 (pre-existing, closed)
- Opportunity Rank, actionable-candidate counts, zero-actionable/stale-state presentation -> Issue #313

Unmigrated executable scope:
- none

## Status

Open P3 reporting follow-up. Read-only.

## Ownership

This file owns presentation of canonical market-opportunity and scanner values in Profit Plan and related list/dashboard surfaces.

Owned here:

- `Actionable PPP` as the primary user scan value;
- optional separately validated `Opportunity Rank` display and sort;
- null-last sorting, deterministic tie-breaks, actionable-candidate counts, labels, tooltips, compact rows, filters, and evidence links;
- stale/unavailable and zero-actionable-candidate presentation.

Not owned here:

- PPP, target lifecycle, scanner, Rotation Pressure, trend, timing, liquidity, or risk computation;
- market-feature promotion into `selection_engine`;
- account permission, sizing, execution intent, order handling, or broker access.

## Consumption rule

Reporting must consume one canonical persisted or neutral read-model field for every displayed value. It must not reimplement scanner or Profit Plan market semantics in renderer-specific code.

Default ordering remains:

```text
1. cards with Actionable PPP, descending
2. cards without Actionable PPP
3. deterministic neutral tie-break
```

Opportunity Rank may become a secondary research sort only after replay validation. It cannot rescue unavailable or invalid market truth.

## Related owners

- Scanner research: `../market_intelligence/momentum_flow_scanner_research_v1.md`
- Historical umbrella specification: `../momentum_flow_scanner_matrix_v1.md`
- Board priority: `../README.md`

## Boundary

```text
reporting-only
read-only
no broker calls
no account permission
no execution intent
no order handling
```
