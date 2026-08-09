# FFG Mega-Run Target Scenarios V1

Archived from `docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md`
in Batch 6F2 (`docs/development/docs_todo_cleanup_batch_6f2_v1.md`). Historical
record only; not current operational authority. This is speculative external
target-narrative tracking, deliberately unfiled, with no executable scope. If
this narrative is ever ingested as data, use the canonical
`docs/research/external_forecast_event_registry_v1.md` contract rather than
reviving this table.

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- speculative external target-narrative tracking -> no Issue required; parked as non-executable external narrative. If this specific narrative is ever ingested as data, use the existing canonical `docs/research/external_forecast_event_registry_v1.md` contract rather than creating a bespoke scenario table.

Unmigrated executable scope:
- none

Status: TODO
Scope: research-only, market-only, account-agnostic
Runtime impact: none

## Hypothesis

FFG targets for INJ, ENA, and MORPHO may be reachable during a broad crypto mega-run, provisionally expected around September-November 2026, if global adoption, institutional liquidity, regulation, tokenization, and altcoin rotation accelerate together.

The working interpretation is not that worldwide crypto migration completes within three months. The hypothesis is that markets may rapidly reprice infrastructure tokens once collective recognition of the ongoing transition becomes dominant.

## Required scenario semantics

Do not store one external target as a single deterministic fair-value estimate.

Represent staged targets as separate research scenarios:

- `BASE_RUN_TARGET`
- `MEGA_RUN_TARGET`
- `BLOW_OFF_TARGET`

These are external outcome hypotheses, not selection-engine truth, account permission, execution intent, or orders.

## Initial target mapping

| Asset | Base run | Mega run | Blow-off |
|---|---:|---:|---:|
| INJ | $52 | $78-$136 | $200-$276 |
| ENA | $0.87 | $1.19-$1.90 | $2.54 |
| MORPHO | $4.17-$6.43 | $9.93 | TBD |

## Asset-specific validation conditions

### INJ

- financial-L1 narrative returns;
- network and exchange volume recover;
- fee burn accelerates materially;
- tokenized-asset or RWA usage expands.

### ENA

- USDe supply and distribution continue growing;
- peg mechanics survive further stress;
- no destructive counterparty or funding-regime failure;
- ENA value capture or fee distribution becomes credible or live.

### MORPHO

- DeFi lending expands;
- embedded integrations and user reach continue growing;
- fee-switch path becomes concrete or live;
- token value capture strengthens without hidden equity-layer leakage.

## Proposed research fields

- `source_target_type`
- `scenario_class`
- `target_price`
- `quote_currency`
- `forecast_window_start`
- `forecast_window_end`
- `regime_assumption`
- `required_catalysts`
- `invalidation_conditions`
- `source_confidence_prior`
- `user_confidence_prior`
- `validation_status`

## Architecture boundaries

Allowed path:

external FFG target
→ timestamped external forecast/outcome scenario
→ regime and catalyst validation
→ post-window scoring
→ optional research feature candidate after evidence

Never:

external FFG target
→ selection-engine score override
→ decision-gate permission
→ execution-planner intent
→ executor order

The `selection_engine` remains market-only and deterministic. Any later account-specific positioning remains exclusively within `decision_gate` and downstream layers.

## Follow-up

- Align these target scenarios with `docs/research/external_forecast_event_registry_v1.md`.
- Decide whether scenario classes belong in the event registry itself or in a separate external target/outcome table.
- Preserve exact FFG source date, publication date, recording date, target range, and source rationale.
- Validate target hits, timing, maximum drawdown before hit, and whether the required market regime actually occurred.
