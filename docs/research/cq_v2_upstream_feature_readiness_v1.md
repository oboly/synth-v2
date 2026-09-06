# CQ v2 upstream feature readiness audit v1

Issue: #777 Phase B  
Status: research-only, market-only, no CQ v2 candidate selection

## Purpose

Audit which canonical market-only contexts are ready to be consumed by a future CQ v2 preregistration. This is a provenance/readiness audit only. It does not scan weights, select features by #684 outcomes, define a replacement score, or authorize production ranking changes.

Audit base: `main` at `520b31a0030a84a13cfee660214f7a7a93100320` on 2026-09-06. Runtime coverage facts below were read-only observations from gurkdb; no rows were written.

## Eligibility rule

`eligible_for_future_CQ_v2=1` means the context already has a canonical, account-agnostic, point-in-time/replayable owner with deterministic source identity and enough persisted temporal history to be used as an upstream input without ad-hoc recomputation inside a future evaluator. It does **not** mean that the feature is predictive or should be selected.

Unknown effective horizon, missing producer-owned freshness, absent provenance, rejected research status, or insufficient persisted temporal coverage keeps the context at `0` until its owner closes that gap.

## Readiness matrix

| Candidate context | Owner | Version / contract | PIT / replayable status | Historical coverage observed on gurkdb | Numeric / semantic domain | Missingness semantics | eligible_for_future_CQ_v2 |
| --- | --- | --- | --- | --- | --- | --- | ---: |
| CQ v0 / local baseline | #568 CQ baseline; frozen #684 population contract | CQ v0 as carried in frozen CQ observations | PIT value carried with immutable CQ observation identity; no future lookup needed | #684 already materialized the canonical temporal population; future CQ v2 must create a later cohort | `[0,1]` | null CQ v0 => `INSUFFICIENT_DATA` | 1 |
| Aggregate Market Rotation Pressure V1 | #676 / #547, `market_rotation_pressure_v1` | model `1.0`; effective horizon `REGIME`; producer freshness 90m | canonical persisted rows, exact venue, `as_of_ts_utc <= observation_asof`; no current-truth fallback | 596 snapshot as-ofs, 2026-07-13 22:00Z through 2026-09-06 19:00Z; 74,787 per-asset rows | `market_score [-100,100]`; breadth ratios; categorical evidence states | missing row/version => unavailable; stale >90m => stale; future/malformed fails closed | 1 |
| Fast / multi-horizon per-asset Rotation (#593 C1/C2/C3) | #593 | research candidates only; C1 final holdout rejected; C2 rejected pre-holdout; C3 insufficient | research replay exists, but no accepted canonical fast variant was promoted | no canonical `fast_rotation_c1_history` production table exists on gurkdb | candidate-specific research scores | rejected/insufficient candidates remain non-canonical; dormant writer capability is not evidence ownership | 0 |
| Sector Rotation / sector leadership context | sector rotation owner; frozen CQ v1 extractor contract | `sector-rotation-v1.0.0`; CQ extractor freezes `window_code=4h` | persisted PIT snapshot plus PIT PRIMARY sector-membership join; deterministic `input_hash` and taxonomy provenance | 48,256 rows, 416 distinct as-ofs, 2026-07-16 18:00Z through 2026-09-06 19:00Z | `rotation_score [-100,100]`; participation, BTC/ETH relative strength, volume share, persistence, coverage | explicit `INSUFFICIENT_PARTICIPATION` / `DATA_UNAVAILABLE`; no current membership backfill | 1 |
| Canonical BTC/global regime alignment | active regime observation owner | `active_regime_observation`; versioned global/class regime fields | contract is PIT/replayable by venue + interval + asset class + latest row at/before event as-of | only 8 rows at one distinct as-of (`2026-05-14T18:09:53.918851Z`) | categorical `global_regime`, `asset_class_regime`, validation status | source docs allow `regime_freshness=UNKNOWN`; no historical freshness threshold | 0 |
| MA breadth / participation | #310, `ma_breadth_snapshot_v1` | modelled canonical raw SMA50 breadth snapshot; input `4h`, lookback `50 bars`; effective horizon `UNKNOWN`, freshness `UNKNOWN` | producer is deterministic exact-asof and replay-safe in code, but production persistence is not materialized | target table `ma_breadth_snapshot_v1` absent on gurkdb at audit time | above-SMA50 count and percentage, coverage | stale/missing exact-asof constituents and insufficient history are explicit; owner freshness remains unknown | 0 |
| Symbol relative behavior vs BTC | no accepted symbol-vs-BTC owner | existing `relative_strength_snapshot` is cross-sectional rank, not BTC-relative; MRP `raw_market_relative_pct` is market-relative, not BTC-specific | no canonical replayable symbol-vs-BTC producer identified | `relative_strength_snapshot`: 76 rows at one as-of only; not BTC-specific | N/A for requested BTC-relative semantics | must remain unavailable; do not relabel market-relative or sector-relative fields as symbol-vs-BTC | 0 |
| PRICE_STRUCTURE / RECLAIM relative-strength evidence | structure / relative-strength evidence contracts | structure engine `1.2`; cross-sectional rank provenance caller-supplied | mapping layer is replay-safe when exact producer row is supplied | `structure_state`: 351 rows / 4 as-ofs; `relative_strength_snapshot`: 76 rows / 1 as-of | structure/reclaim states and scores; cross-sectional rank | both currently fail closed at evidence level because effective horizon is `UNKNOWN`; producer freshness also unresolved | 0 |
| ETH/BTC leadership raw context | #305 semantic owner, #721 raw producer | `eth_btc_leadership_snapshot` `1.0`; effective horizon `UNKNOWN` | deterministic exact-boundary replay producer exists | target table absent on gurkdb at audit time | BTC/ETH 24h returns, ETH-minus-BTC return, ratio change | exact-boundary missing/stale/future rules explicit; `UNMAPPED_HORIZON` remains | 0 |

## Important boundaries

### #593 does not become CQ input by existence of code

The final #593 result rejected C1 on the frozen final holdout. Its dormant history/writer infrastructure therefore does not establish a canonical CQ v2 input. A future C1-v2 research family must remain separately versioned and must earn its own fresh validation before this matrix can mark a fast Rotation family eligible.

### Sector evidence is eligible, not selected

Sector Rotation is the clearest new replayable context that was not part of the frozen CQ v1 formula family. Its canonical history and PIT membership semantics are sufficient for future preregistration, but this audit makes **no claim** that sector evidence improves CQ. Feature choice, transformations and weights belong to a later frozen candidate-family issue and must be fixed before new outcome labels are opened.

### BTC/global regime is contractually replayable but not temporally ready

`active_regime_observation` has the right PIT identity and versioned semantics, but the production table currently contains only one distinct as-of. It therefore cannot support a fresh chronological CQ v2 cohort today without first materializing canonical historical/new observations under its owner contract.

### Freshness/coherence fields

Only use freshness/coherence as CQ inputs when the upstream owner defines them as replayable truth. Rotation Pressure now has a producer-owned 90-minute freshness boundary. MA breadth, structure/relative-strength and active-regime historical joins do not currently provide an equivalent complete freshness contract, so a CQ evaluator must not invent one.

## Phase B conclusion

Ready upstream contexts today:

```text
CQ v0 baseline
Market Rotation Pressure V1 broad/regime evidence
Sector Rotation 4h evidence through PIT sector membership
```

Not ready today:

```text
#593 fast Rotation candidates
BTC/global regime as a temporal feature (coverage insufficient)
MA breadth (not materialized; horizon/freshness unresolved)
symbol-vs-BTC relative behavior (no canonical owner)
PRICE_STRUCTURE / cross-sectional relative strength (unmapped horizon/freshness + sparse history)
ETH/BTC leadership (not materialized; horizon unresolved)
```

The correct next-step state after Phase B is:

```text
FRESH_DATA_REQUIRED
```

Reason: the consumed #684 cohort ends at `2026-08-31T00:00:00Z` and cannot be reused for CQ v2 validation/holdout. A future candidate family may only be evaluated on a new, later immutable cohort. Phase C should specify that cohort and keep its final holdout unopened until after candidate-family freeze.

## Safety

```text
research_only=1
market_only=1
account_awareness=0
db_writes=0
model_retuning=0
candidate_selection=0
production_ranking_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation=0
```
