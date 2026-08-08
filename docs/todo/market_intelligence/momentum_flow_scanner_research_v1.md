# Momentum Flow Scanner Research v1

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- market-only scanner research contract (features, read model, replay/ablation) -> Issue #306
- display-only volume-flow candle classification (narrower, adjacent scope) -> Issue #277 (pre-existing)

Unmigrated executable scope:
- none

## Status

Open P3 research / read-only. Non-blocking for active runtime and execution lanes.

## Ownership

This file is the canonical owner for the market-only scanner research contract previously mixed into `docs/todo/momentum_flow_scanner_matrix_v1.md`.

Owned here:

- deterministic market-feature inputs, including RSI, MFI, volume, trend, map, target-room, liquidity, and freshness evidence;
- market-only candidate states and reason codes;
- read-model construction;
- replay, ablation, control, MFE/MAE, target-before-invalidation, and false-positive validation;
- any later proposal to promote validated market features into `selection_engine`.

Not owned here:

- Profit Plan layout, labels, card order, tooltips, or dashboard rendering;
- account ownership, balances, exposure, permission, or sizing;
- `decision_gate`, execution intent, order handling, or broker access.

## Canonical boundary

```text
market features / canonical map truth
-> research scanner read model
-> replay and shadow validation
-> optional separately reviewed market-only feature-promotion proposal
```

Never:

```text
scanner score -> decision_gate approval -> execution plan -> order
```

## Required research contract

The scanner must remain deterministic, point-in-time reproducible, and fail closed for stale or unavailable inputs. Target room and invalidation risk remain separate. External FFG labels or curated membership may provide provenance or a filtered research view, but cannot set a score, state, or eligibility by themselves.

## Related owners

- Historical umbrella specification: `../momentum_flow_scanner_matrix_v1.md`
- Reporting/presentation owner: `../reporting/profit_plan_opportunity_presentation_v1.md`
- FFG market-classification owner: `ffg_rotation_classification_v1.md`
- Board priority and execution order: `../README.md`

## Definition of done

- canonical market inputs and timestamps are explicit;
- read-model states are deterministic and versioned;
- replay and controls quantify incremental value;
- reporting consumes persisted or canonical values without recomputing them;
- no account, permission, planning, execution, broker, or order authority is introduced.
