# FFG Rotation Radar Presentation v1

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- read-only presentation of market classification + account overlay -> Issue #311

Unmigrated executable scope:
- none

## Status

Open P3 reporting / account-overlay follow-up. Read-only.

## Ownership

This file owns presentation of canonical FFG-universe rotation classifications and a separately typed account overlay.

Owned here:

- attention strip, breadth summary, groups, filters, row layout, timestamps, confidence, reason codes, and links to evidence;
- account overlay fields such as owned/not-owned, quantity, current value, portfolio weight, unrealized return, and account snapshot timestamp;
- explicit distinction between market classification and account context.

Not owned here:

- FFG universe membership provenance;
- market classification, scoring, normalized flow, RSI/MFI, structure, liquidity, target-room, or confidence computation;
- Profit Plan map computation;
- `decision_gate`, sizing, execution intent, order handling, or broker access.

## Consumption rule

The same market classification must remain unchanged across accounts. Account fields may group or annotate rows but may never mutate market score, classification, ranking, or eligibility.

Required handoff:

```text
canonical FFG membership metadata
+ canonical market-only classification
+ separate account snapshot
-> read-only radar presentation
```

A strong classification with no valid current map remains research context only. Reporting cannot bypass map freshness or `decision_gate`.

## Related owners

- Market classification: `../market_intelligence/ffg_rotation_classification_v1.md`
- External membership/provenance: `../external_research/ffg_universe_metadata_v1.md`
- Historical umbrella specification: `../ffg_curated_rotation_radar_v1.md`
- Board priority: `../README.md`

## Boundary

```text
reporting/account overlay only
market classification immutable
no broker calls
no permission grants
no execution intent
no order handling
```
