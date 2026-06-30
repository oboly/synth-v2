# Map Invalidation Threshold Validation v1

## Status

Todo / research and evaluation specification.

## Problem

A displayed invalidation price is currently easy to misread as proven market truth.

It is not.

A map invalidation threshold is a model-derived structural boundary. Even when its construction uses familiar ingredients such as swing structure, support/resistance, or Fibonacci ratios, the exact rule remains a testable hypothesis.

Examples of unsupported assumptions:

* a precise computed decimal price is inherently reliable;
* a wick below the level always invalidates a setup;
* a close below the level always invalidates a setup;
* a threshold that looks plausible on one chart is useful across assets and regimes;
* a threshold can be used for execution automation because it appears on the card.

Do not promote map invalidation thresholds into execution logic until they have passed measured outcome validation.

## Scope

Build a research-only validation lane for map invalidation thresholds.

It must answer:

```text
Does this threshold family improve route-failure detection,
drawdown containment, and false-exit behavior compared with simpler alternatives?
```

This work is market-data-only.

Do not change:

* `selection_engine` policy;
* `decision_gate`;
* `execution_planner`;
* executor or broker integration;
* live order placement, cancellation, or amendment;
* account allocation or risk caps;
* user-facing order instructions.

## Required Separation

Keep these questions separate.

### A. Map-evaluator correctness

For a specific card/map:

```text
Did price breach the displayed threshold after this exact map activated,
under the configured invalidation policy?
```

This is an audit question.

### B. Threshold quality

Across many historical maps:

```text
Does this threshold/policy predict meaningful route failure better than alternatives?
```

This is a validation question.

A chart can indicate a possible evaluator bug without proving the threshold itself is good.

## Threshold Provenance Contract

Every rendered invalidation threshold must expose or be traceable to:

```text
map_id / map_cycle_id
map activated_at_utc
threshold price
threshold source family
anchor inputs
formula or rule version
horizon / candle interval
invalidation policy
```

Do not render a bare label such as:

```text
Below €0.4500481
```

without the policy and provenance needed to interpret it.

## Required UI Audit Fields

When a map has an invalidation threshold, the detail card should eventually expose:

```text
Invalidation threshold: €…
Threshold source: <structural rule family>
Policy: <wick / close / acceptance>
Map activated: <timestamp>
Lowest low since activation: €…
Lowest relevant close since activation: €…
Breach status: NONE / WICK / CLOSE / ACCEPTED
Breach first observed: <timestamp or unavailable>
```

Do not imply a `MAP_INVALIDATED` state merely from the latest price being below, near, or above the threshold.

Historical evaluation must use the configured activation boundary and the correct candle interval.

## Candidate Invalidation Policies

Evaluate policies explicitly. Do not hardcode one without comparison.

### 1. Wick breach

```text
minimum_low_since_activation <= threshold
```

Pros:

* fast structural failure detection;
* simple;
* catches decisive flushes.

Risks:

* vulnerable to transient liquidity wicks;
* may create excessive false invalidations for volatile assets.

### 2. Relevant-horizon close breach

```text
minimum_close_on_configured_interval <= threshold
```

Pros:

* avoids some wick noise;
* aligns better with candle-based map logic.

Risks:

* can react late;
* depends strongly on interval choice.

### 3. Acceptance breach

```text
N consecutive configured-horizon closes below threshold
```

or an equivalent duration/acceptance rule.

Pros:

* can reduce one-candle false exits;
* expresses sustained loss of structure.

Risks:

* additional free parameters;
* may allow materially larger adverse movement before invalidation.

### 4. Reclaim-aware breach

A breach is recorded first, then classified by whether price reclaims the threshold within a predetermined window.

This is useful for analysis, not as a retroactive live-state rewrite.

## Candidate Threshold Families

The current map threshold family must be compared with simpler and competing alternatives.

Minimum comparison set:

```text
CURRENT_MAP_INVALIDATION
SWING_LOW_BOUNDARY
STRUCTURAL_RETRACE_BOUNDARY
FIB_0_618
FIB_0_786
ATR_BUFFERED_STRUCTURE_LEVEL
FIXED_PERCENT_FROM_ANCHOR
NO_INVALIDATION_BASELINE
```

Do not assume Fib-derived thresholds are superior merely because Fibonacci ratios are familiar market-analysis tools.

## Dataset and Cohort Rules

### Unit of analysis

One eligible historical map activation.

Each record must include:

```text
asset / market
venue
horizon
map_id or stable map_cycle_id
map activation timestamp
map anchors and threshold
policy version
candle sequence after activation
original route / target definitions
```

### Sampling

Use sufficiently broad samples across:

* assets;
* market-cap/liquidity groups where available;
* volatile and quiet regimes;
* trend, range, and drawdown contexts;
* distinct time periods.

Do not validate only on visually selected examples or only on successful maps.

### Time discipline

* Split development and holdout periods before tuning.
* Keep event windows non-overlapping where relevant.
* Use the state available at map activation only.
* Do not use future target completion or later price action to redefine the original threshold.
* Preserve map version and policy version.

## Required Outcomes

For each threshold family and policy, measure at minimum:

```text
route_failure_rate_after_breach
false_invalidation_rate
post_breach_target_hit_rate
post_breach_return_distribution
maximum_adverse_excursion_before_target_or_terminal_state
maximum_favourable_excursion_after_breach
median_time_to_breach
median_time_from_breach_to_terminal_outcome
coverage_count
```

Definitions must be frozen before result comparison.

### Core interpretation

A useful invalidation rule should ideally:

* flag materially failed routes earlier than alternatives;
* reduce adverse excursion relative to no invalidation;
* avoid excessive cases where a breached map still reaches its original target route;
* work with adequate sample size;
* retain performance on held-out data.

No single metric decides quality.

## Required Baselines

Every result must include comparison with:

```text
No invalidation
Current map threshold with wick policy
Current map threshold with close policy
Current map threshold with acceptance policy
At least one simple structural baseline
At least one volatility-aware baseline
```

Report both aggregate results and per-asset/per-regime dispersion. A rule that works only on one asset or one historic regime must not be called universal.

## Local Card Audit: SLX-Type Case

Before declaring an individual map invalidated, produce a deterministic audit record:

```text
symbol / market
map identifier
map activation timestamp
threshold price
policy
first wick breach after activation
first close breach after activation
first acceptance breach after activation
minimum low since activation
minimum close since activation
current map state
reason for current state
```

Decision rule:

```text
If the displayed historical low occurred before map activation,
it cannot invalidate that map.

If it occurred after activation, evaluator state must be checked against the
configured policy before labelling the map invalidated.
```

Do not use current price proximity as a substitute for historical breach evaluation.

## Output Requirements

### Research report

Produce a versioned report containing:

* threshold family and policy definitions;
* cohort construction;
* event counts;
* aggregate outcomes;
* asset/regime breakdowns;
* holdout results;
* baseline comparisons;
* limitations and sample-quality warnings.

### Card/read-model diagnostics

Expose compact diagnostics only after the audit data exists:

```text
threshold source
policy
breach state
map activation time
first breach time where present
```

Do not expose an unvalidated threshold as a buy/sell instruction.

## Promotion Criteria

A threshold/policy family may be considered for later decision-gate research only when all are true:

* provenance and map activation boundary are explicit;
* policy is deterministic and tested;
* outcome definitions are predeclared;
* performance is measured against required baselines;
* results hold on out-of-sample data;
* false-invalidation behavior is acceptable for the relevant horizon;
* asset/regime limitations are documented;
* no execution behavior is enabled automatically.

## Acceptance Criteria

* Every invalidation threshold can be traced to a map/version, inputs, and policy.
* A card audit distinguishes historical wick, close, and acceptance breaches.
* Map activation timestamp bounds all breach evaluation.
* Current price alone cannot silently determine historical invalidation state.
* Current threshold family is compared against at least the required baselines.
* Results include false invalidations, route failures, post-breach target outcomes, and excursion metrics.
* Development and holdout samples are separated.
* Results identify asset/regime limitations rather than claiming universal validity.
* No execution, policy, or broker behavior changes occur in this work.

## Delivery Sequence

1. Implement deterministic per-map invalidation audit output.
2. Build historical cohort extraction with map activation boundaries.
3. Run policy and threshold-family comparison against frozen outcomes.
4. Publish research report and card diagnostics.
5. Decide whether any threshold family merits later promotion research.

Do not skip directly from a visually convincing threshold to automated use.
