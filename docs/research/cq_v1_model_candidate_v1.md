# CQ v1 model candidate family v1

Issue: #610
Parent: #568
Status: research-only model freeze

## Freeze evidence

Phase 2D0 accepted the measured Phase 2C coverage artifact before any CQ v1 transform or weight was selected:

```text
coverage artifact = data/research/cq_v1_pit_extractor_v1_full_20260830T133005Z/coverage_summary.json
sha256 = f09a515535dd72c5422cbfea7ad449163132b298d1759f32701f0152c78aff2d
sample_count = 419
MRP available = 203 / 419 = 0.484487
sector available = 419 / 419 = 1.000000
joint available = 203 / 419 = 0.484487
weights_assigned = 0 at measurement
cq_v1_scores_emitted = 0 at measurement
```

The Phase 2D0 gate returned `READY_FOR_MODEL_FREEZE`. No forward-outcome artifact or table was inspected to select the transforms or weights in this contract.

## Source-semantic audit

### CQ v0

CQ v0 is already normalized `0..1` and equals the Phase-1 clamped `trade_quality_score`. The transform is identity plus deterministic six-decimal rounding.

### Market Rotation Pressure v1

The canonical read model `src/reporting/market_rotation_pressure_dashboard_v1.py` defines:

```text
PRESSURE_SCALE_MIN = -100.0
PRESSURE_SCALE_MAX = 100.0
```

and validates aggregate `market_score` against that domain. Therefore the only MRP numeric transform frozen here is:

```text
mrp_market_score_normalized = (market_score + 100) / 200
```

so `-100 -> 0`, `0 -> 0.5`, `+100 -> 1`.

Phase 2C defines MRP family availability as aggregate **and** per-asset rows both present. Candidate support preserves that measured support rule. The per-asset `score_total` itself is deliberately not used: the canonical read model currently validates it as finite but does not publish a hard range. This freeze does not invent a range merely to consume the field.

### Sector Rotation

Sector Rotation `sector-rotation-v1.0.0`, window `4h`, remains an audited replay-safe CQ input family. Measured coverage is 100%. However, the audited/retrieved canonical contracts do not establish a hard numeric domain for `rotation_score` suitable for a semantics-derived `0..1` transform. Phase 2D1 therefore records the family as eligible but does not score it in model-family v1.

That is an intentional negative result, not a request to tune coverage or derive bounds from outcomes. A later model-family version may consume Sector Rotation only after its numeric transform can be pinned to a canonical source contract, never retrofitted after holdout inspection.

## Frozen candidate family

The family is capped at two simple hypotheses rather than a weight grid.

### `cq_v1_mrp_balanced_v1` 1.0.0

```text
CQ v1 = 0.50 * CQ v0 + 0.50 * normalized aggregate MRP market_score
```

This asks whether equal local/cross-market weighting adds ranking utility.

### `cq_v1_mrp_anchor_v1` 1.0.0

```text
CQ v1 = 0.75 * CQ v0 + 0.25 * normalized aggregate MRP market_score
```

This keeps local quality as the explicit anchor and treats aggregate MRP as a smaller contextual modifier.

These are preregistered structural hypotheses, not empirically optimized weights. No third candidate, grid search, quantile fit or learned transform is permitted in v1.

## Support and missingness

Both candidates require:

```text
CQ v0 available
MRP aggregate available, model_version=1.0
MRP per-asset row available, model_version=1.0
```

The per-asset row is required to preserve the Phase 2C measured `mrp_available` support set even though its unbounded `score_total` is not numerically transformed in v1.

States are explicit:

- `AVAILABLE`: all required support exists and values satisfy their frozen domains;
- `INSUFFICIENT_DATA`: a required CQ/MRP observation is absent;
- `BLOCKED`: a present payload violates the frozen model/version/numeric contract.

There is no imputation, current/future fallback, or weight renormalization when a feature is absent.

## Determinism

The scorer in `src/research/cq_v1_model_candidate_v1.py`:

- performs no database query;
- reads no forward outcomes;
- ignores unregistered payload fields;
- returns a `0..1` Decimal rounded to exactly six decimals;
- never changes production selection/ranking.

## Evaluation boundary

After this freeze is merged, the next #568 slice may score immutable Phase 2C observations with these exact candidate versions and join them to the already-preregistered 1h/4h/24h forward labels.

Model-family selection/tuning remains forbidden on the final holdout. Compared baselines must use identical eligible observations or explicitly control/report support differences.

## Frozen state

```text
TRANSFORMS_FROZEN=1
MODEL_FAMILY_FROZEN=1
CANDIDATE_COUNT=2
COVERAGE_ARTIFACT_SHA256=f09a515535dd72c5422cbfea7ad449163132b298d1759f32701f0152c78aff2d
HOLDOUT_OUTCOMES_INSPECTED=0
```
