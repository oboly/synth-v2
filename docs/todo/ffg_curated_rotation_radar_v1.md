# TODO — FFG Curated Rotation Radar V1

## Status

Open research / read-only dashboard lane.

This document records the 2026-07-12 interpretation of the FFG Crypto List dashboard and its useful role inside Synth v2.

It is an integration contract between the existing FFG research universe and the existing momentum/flow scanner work. It does not redefine either source contract.

Canonical related documents:

- `docs/research/ffg_research_universe_v1.md`
- `docs/research/ffg_flow_snapshot_ingest.md`
- `docs/todo/momentum_flow_scanner_matrix_v1.md`
- `docs/architecture/market_observer_contract_v1.md`

## Core interpretation

The FFG `haven't run yet` list must not be interpreted as a generic scan for assets far below all-time high.

Its useful meaning is:

```text
laggards inside a separately curated research universe of projects that FFG expects to remain relevant
```

That prior curation changes the research question from:

```text
Which random depressed token is cheap?
```

to:

```text
Which member of the curated universe has not yet participated, but is now showing measurable early-rotation evidence?
```

FFG membership remains external research metadata. It is not proof that an asset will succeed and must never become automatic trading eligibility.

## Dynamic counts only

Do not hardcode source counts such as `107`, `109`, or a user's current owned count.

The dashboard must derive at render time:

- current canonical FFG research-universe member count;
- currently resolved tradable markets;
- account-owned member count;
- missing/not-owned member count;
- unavailable or unresolved member count.

Historical screenshots and conversations may contain different counts because the source list and identity resolution can change.

## Separation of concerns

```text
FFG research universe = external curated membership metadata
selection_engine       = market-only timing and ranking evidence
account overlay        = owned/not-owned/exposure presentation
Profit Plan            = map, entry, target and invalidation presentation
decision_gate          = account-aware permission layer
execution_planner      = execution intent only
executor / agents      = order handling
```

Required boundaries:

- FFG membership may narrow or label a research view, but does not authorize selection or execution by itself.
- Market classifications must remain account-agnostic.
- `owned`, `not_owned`, quantity, value and portfolio weight are account/reporting overlays only.
- No account field may enter a market-only score.
- No reporting page may bypass `decision_gate`.

## Target product concept

Working title:

```text
FFG ROTATION RADAR
```

Purpose:

```text
Find early rotation and distribution changes within the curated FFG universe, then show whether the current account already owns each asset.
```

The primary value is the combination:

```text
curated membership
+ relative laggard/runner state
+ measured 24h and 7d flow direction
+ flow acceleration/persistence
+ RSI/MFI/volume confirmation
+ structure and target-room context
+ separate account ownership overlay
```

## Market-only classifications

Initial research classifications:

```text
EARLY_ROTATION
CONFIRMED_ROTATION
LAGGARD_IMPROVING
LAGGARD_DORMANT
RUNNER_EXTENDED
DISTRIBUTION_RISK
STRUCTURALLY_WEAK
DATA_UNAVAILABLE
```

Definitions:

### EARLY_ROTATION

Flow or participation improves before a confirmed price expansion.

Typical evidence:

- improving normalized flow;
- positive flow acceleration;
- MFI recovering while RSI remains neutral;
- volume participation improving;
- price not yet extended;
- source timestamps fresh.

### CONFIRMED_ROTATION

Early-flow evidence is followed by measurable price/structure confirmation.

Typical evidence:

- persistent positive flow across multiple snapshots;
- RSI/MFI and volume confirmation;
- relative-strength improvement;
- valid structure reclaim or reset completion;
- sufficient target room remains.

### LAGGARD_IMPROVING

The asset remains behind stronger universe members but its evidence is improving.

This is a research-review state, not a buy state.

### LAGGARD_DORMANT

The asset has not participated and has no convincing recovery evidence.

Being far below ATH is insufficient to escape this bucket.

### RUNNER_EXTENDED

The asset has already materially participated and is no longer an early-entry candidate at the current price/context.

### DISTRIBUTION_RISK

Outflow, weakening MFI participation, divergence or poor follow-through indicates rising distribution risk.

### STRUCTURALLY_WEAK

The asset is depressed and lacks the minimum structure, liquidity, participation or recovery evidence required for a credible rotation thesis.

## `Has not run` guardrail

Distance below ATH is context only.

It must never produce `EARLY_ROTATION`, `LAGGARD_IMPROVING`, or any action implication by itself.

A depressed curated asset requires additional evidence such as:

- adequate and current liquidity;
- improving relative strength;
- positive normalized flow change;
- volume participation returning;
- RSI/MFI recovery or supportive divergence;
- valid market structure or reclaim;
- acceptable dilution/token-supply context when that data becomes canonical;
- sufficient target room and explicit invalidation context.

Preferred user-facing wording:

```text
DEPRESSED — RECOVERY UNCONFIRMED
LAGGARD — FLOW IMPROVING
EARLY ROTATION — STRUCTURE CONFIRMATION PENDING
```

Avoid:

```text
TOP OPPORTUNITY because -86% from ATH
HAS NOT RUN therefore buy
```

## Flow evidence contract

Absolute reported flow amounts are insufficient without scale and provenance.

Required fields where available:

```text
symbol
source_universe_key
observed_ts_utc
window
raw_inflow
raw_outflow
net_flow
net_flow_pct_of_24h_volume
net_flow_pct_of_market_cap
flow_zscore_vs_baseline
flow_direction
flow_acceleration
positive_snapshot_count
snapshot_count
source_confidence
source_id
```

Required horizons:

```text
24h
7d
```

Useful optional horizon:

```text
1h or current-snapshot acceleration
```

No timestamp means no current-flow claim.

External FFG values with unclear methodology remain low-confidence research metadata. Synth-native measured flow must be kept distinct from copied FFG presentation values.

## Composite score research shape

A transparent research score may combine market-only components:

```text
flow_24h_score
flow_7d_score
flow_acceleration_score
flow_persistence_score
mfi_confirmation_score
rsi_structure_score
volume_participation_score
relative_strength_score
liquidity_quality_score
structure_confirmation_score
target_room_score
```

Candidate display range:

```text
FLOW_ROTATION_SCORE = -10 .. +10
```

Requirements:

- every component remains inspectable;
- missing inputs do not silently become zero-quality evidence;
- weights are versioned;
- account ownership is excluded from the score;
- FFG membership itself is a universe label, not a positive score contribution;
- backtest/replay is required before promotion to `selection_engine` ranking.

## Account overlay

The same market classification may be presented through account-specific groups:

```text
OWNED — EARLY ROTATION
OWNED — LAGGARD IMPROVING
NOT OWNED — EARLY ROTATION
NOT OWNED — LAGGARD IMPROVING
OWNED — RUNNER EXTENDED
OWNED — DISTRIBUTION RISK
```

Account overlay fields:

```text
owned_state
quantity
current_value
portfolio_weight_pct
unrealized_return_pct
account_snapshot_ts_utc
```

These fields belong to reporting/account context only and must not mutate the market classification.

## Dashboard contract

### Top attention strip

Show a compact maximum of approximately three to five items requiring review.

Example:

```text
ARB      EARLY ROTATION       flow improving · MFI confirms · structure pending
VIRTUAL  CONFIRMED ROTATION   persistent inflow · volume expansion
SYRUP    DISTRIBUTION RISK    outflow accelerating · weak participation
```

Each item must expose:

- classification;
- concise reason;
- observed timestamp/freshness;
- source confidence;
- link to inspect full evidence.

### Market breadth bar

Suggested summary:

```text
FFG universe: <dynamic count>
Early rotation: N
Confirmed rotation: N
Dormant laggards: N
Extended runners: N
Distribution risk: N
Data unavailable: N
```

For an account-scoped page, add separately:

```text
Owned: N
Not owned: N
Unresolved: N
```

### Main groups

```text
EARLY ROTATION
CONFIRMED ROTATION
LAGGARDS IMPROVING
DORMANT / UNCONFIRMED
RUNNERS / EXTENDED
DISTRIBUTION RISK
```

### Filters

```text
owned / not owned
classification
24h flow direction
7d flow direction
flow improving
RSI/MFI confirmation
minimum target room
map freshness
source confidence
data freshness
```

### Per-row evidence

```text
symbol
owned_state (account view only)
classification
flow rotation score
24h flow
7d flow
acceleration
persistence
RSI/MFI regime
volume participation
relative strength
structure state
target room
confidence
observed timestamps
reason codes
```

## Relationship with Profit Plan

The Rotation Radar identifies research candidates and review priorities.

It must not recreate Profit Plan map logic.

The handoff is:

```text
Rotation Radar candidate
-> inspect canonical Profit Plan map
-> inspect entry, target, invalidation and freshness
-> decision_gate evaluates account-aware permission
-> execution layers remain unchanged
```

A strong rotation score with no valid current map remains research context only.

## Validation questions

Before any promotion beyond read-only research:

```text
Do curated-universe laggards with improving flow outperform dormant curated laggards?
Does 7d improvement plus 24h acceleration outperform either horizon alone?
Does MFI add predictive value beyond RSI, volume and OBV?
Do EARLY_ROTATION assets reach valid targets before invalidation more often than controls?
How often does RUNNER_EXTENDED prevent late entries?
How often does ATH-distance add useful information after flow, structure and liquidity are known?
Does FFG-universe membership add out-of-sample value versus a liquidity-matched non-FFG control universe?
```

Minimum result breakdowns:

```text
classification counts
forward returns
MFE / MAE
target-before-invalidation rate
time to target
false-positive rate
owned versus not-owned presentation only, never score training
symbol and liquidity bands
FFG universe versus matched control universe
```

## Implementation sequence

```text
1. Confirm current canonical FFG universe membership and identity resolution.
2. Define Synth-native flow measurements and source provenance.
3. Add deterministic MFI feature through the existing feature lane.
4. Build versioned, market-only rotation classification/read model.
5. Backtest classifications and score components against controls.
6. Add read-only market Rotation Radar UI.
7. Add separate account ownership overlay without changing classifications.
8. Link candidates to existing Profit Plan details.
9. Consider selection_engine promotion only through a later validated contract.
```

## Hard boundaries

```text
selection_engine   = unchanged until separately validated promotion
decision_gate      = unchanged
execution_planner  = unchanged
executor / agents  = unchanged
broker calls       = none
broker writes      = none
order submission   = none
live trading       = none
```

Forbidden:

- treating FFG membership as certainty that an asset will succeed;
- treating ATH drawdown as an opportunity signal;
- mixing account ownership into market scoring;
- copying unverified FFG flow numbers into native measured-flow fields;
- `BUY_READY`, `AUTO_BUY`, `EXECUTE`, or equivalent labels;
- reporting-side bypass of map freshness or `decision_gate`;
- hardcoded universe or owned counts;
- source claims without absolute observed timestamps.

## Definition of done

```text
The current FFG research universe is loaded dynamically.
Market-only rotation classifications are deterministic and versioned.
24h and 7d flow evidence is normalized and timestamped.
RSI/MFI/volume/structure evidence remains inspectable.
ATH drawdown remains context-only.
Account ownership is a separate presentation overlay.
The dashboard exposes attention, breadth, groups, filters and source confidence.
Backtest evidence exists before any selection_engine promotion.
No trading or execution authority is introduced.
```