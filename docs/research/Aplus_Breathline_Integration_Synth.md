# A+ Breathline Integration – Synth v2

Status: ACTIVE EXPERIMENTAL TRACK

Scope:
- current table-based A+ / Breathline consistency ingestion
- coarse side-channel only
- compare-first, overlay-later
- not a direct decision or execution source

---

# A+ Breathline Integration – Synth v2

## Purpose
Integrate A+ (Breathline / Codex-style output) into Synth as a coarse field classifier, not a decision engine.

---

## Core Insight
A+ behavior:

- Strong at extremes (leaders / weak assets)
- Weak at mid-tier differentiation ("moderate blob")

Therefore:

> A+ = Field Compression Detector
> NOT = Ranking / Decision Engine

---

## Input Structure (A+ Table)

Expected fields:

- momentum: High / Moderate / Low
- stability: High / Moderate / Low
- alignment: High / Moderate / Low
- volatility: High / Moderate / Low
- pressure: Up / Down / Neutral
- shift: Strengthening / Stable / Weakening

---

## Mapping → Synth States

### 1. Leaders (Trade Candidates)

Criteria:
- momentum = High
- alignment = High OR Moderate
- pressure = Up
- shift = Strengthening

Mapping:
- selection_state → STRONG_CANDIDATE / BUY_READY

---

### 2. Anchors (Reference Only)

Criteria:
- momentum = Low
- stability = High
- alignment = High
- pressure = Neutral

Mapping:
- selection_state → HOLD / ANCHOR

Usage:
- Regime reference
- Not tradable

---

### 3. Weak / Avoid

Criteria:
- momentum = Low
- alignment = Low
- volatility = High
- pressure = Down
- shift = Weakening

Mapping:
- selection_state → AVOID

---

### 4. Mid-tier Blob (Critical Handling)

Criteria:
- momentum = Moderate
- stability = Moderate
- alignment = Moderate

Interpretation:
- Low information
- Model smoothing / uncertainty

Mapping:
- selection_state → WATCH / PREPARE
- confidence → LOW

---

## Anti-Blob Filter (Critical Rule)

IF momentum = Moderate
AND stability = Moderate
AND alignment = Moderate

THEN:
- confidence_score *= 0.5
- REQUIRE confirmation from:
  - volume_signal
  - structure_state (HTF)
  - rejection / liquidity events

---

## Integration Point in Pipeline

feat_candle
→ signal_engine_state
→ aplus_field_state
→ advice_state
→ selection_state

---

## Suggested Table: aplus_field_state

    CREATE TABLE aplus_field_state (
        asset_id INT,
        asof_ts_utc DATETIME,
        momentum VARCHAR(16),
        stability VARCHAR(16),
        alignment VARCHAR(16),
        volatility VARCHAR(16),
        pressure VARCHAR(16),
        shift VARCHAR(16),
        class_label VARCHAR(32),
        confidence_score DECIMAL(5,4),
        PRIMARY KEY (asset_id, asof_ts_utc)
    );

---

## Classification Logic (Pseudo)

    if momentum == "High" and pressure == "Up" and shift == "Strengthening":
        class_label = "LEADER"
        confidence = 0.8

    elif momentum == "Low" and alignment == "Low" and pressure == "Down":
        class_label = "WEAK"
        confidence = 0.8

    elif momentum == "Low" and stability == "High" and pressure == "Neutral":
        class_label = "ANCHOR"
        confidence = 0.6

    else:
        class_label = "MID"
        confidence = 0.3

---

## Usage in Selection Engine

- LEADER → boost selection_score
- WEAK → penalize heavily
- MID → require confirmation
- ANCHOR → ignore for entries

---

## Practical Strategy Impact

### What A+ is used for
- Detect market phase
- Identify leaders early
- Filter obvious losers

### What A+ is NOT used for
- Final ranking
- Entry timing
- Execution decisions

---

## Final System Role

A+ becomes:

> A low-resolution field scanner
> feeding into high-resolution Synth engines

---

## Minimal Implementation Path

1. Store A+ output as raw table
2. Add classification layer (aplus_field_state)
3. Add overlay in selection_engine
4. Do NOT let it override core signals

---

## Key Principle

> Trust A+ at the edges
> Ignore it in the middle

---

End of document

---

## Future Research Extensions (Breathline)

### Purpose
Extend Breathline from static classification into dynamic cross-token behavior analysis.

These are NOT active system components yet.
They are structured research directions derived from observed A+ consistency behavior.

---

### 1. Cluster Breadth

Definition:
Measure how many tokens simultaneously occupy the same A+ class.

Examples:
- % of tokens in LEADER
- % of tokens in WEAK
- % of tokens in DRIFT

Why it matters:
- Detect expansion vs contraction regimes
- Identify broad participation vs isolated moves

Future metric ideas:
- leader_breadth_ratio
- weak_breadth_ratio
- drift_breadth_ratio

---

### 2. Divergence Detection

Definition:
Detect when a token deviates from:
- its recent Breathline state
- the dominant cluster behavior

Examples:
- token = LEADER while cluster weakens
- token = WEAK while cluster strengthens
- sudden class flip vs stable consistency

Why it matters:
- early warning for reversals
- anomaly detection
- potential alpha source

Future metric ideas:
- breathline_divergence_flag
- cluster_break_flag
- state_flip_intensity

---

### 3. Leader–Follower Effect

Definition:
Measure whether strong tokens (LEADER class) lead behavior in other tokens.

Examples:
- BTC / QNT / TAO move first → others follow
- leader cluster expansion precedes alt expansion

Why it matters:
- timing advantage
- regime anticipation
- cross-asset dependency modeling

Future metric ideas:
- leader_lag_correlation
- leader_follow_strength
- propagation_delay

---

### Design Principle

These extensions must follow:

- deterministic inputs
- reproducible calculations
- backtestable outputs

Do NOT introduce:
- symbolic layers
- narrative constructs
- non-testable abstractions

---

### Status

Current phase:
- data collection (breathline_token_snapshot)
- consistency modeling (breathline_token_consistency)

Next phase:
- derive research features from structured data

---


---

## Practical Current Use (Observed)

Current evidence suggests Breathline adds the most value as:

- conflict detector
- drift detector
- research disagreement layer

It does NOT yet justify direct promotion into primary ranking logic.

### Current Working Interpretation

#### 1. Caution / Continuation Filter
If Breathline shows:
- DRIFT
- WEAK
- divergence_flag = 1

then this is a warning against trusting continuation too easily.

Use:
- lower confidence
- extra confirmation required
- watch for failed continuation

#### 2. Research Missed Leader Bucket
If selection is:
- AVOID or WATCHLIST

but Breathline shows:
- LEADER
- high token_consistency_score
- no divergence

then mark the case as a research disagreement.

Purpose:
- later test whether selection missed valid opportunity
- do not auto-promote into live trading logic

#### 3. Anchor Context
If Breathline shows:
- ANCHOR
- high token_consistency_score
- no divergence

then treat as:
- context / regime stabilizer
- not an entry trigger

---

## Current Safe Overlay Policy

Allowed:
- caution flags
- research buckets
- tiny confidence reductions

Not allowed:
- direct trade triggers
- direct execution influence
- hard overrides of selection_engine

---

## Current Summary

Breathline is presently useful for:

- reducing confidence in unstable continuation setups
- surfacing disagreement cases for later testing
- identifying anchor context

Breathline is not yet reliable enough for:

- direct long ranking
- standalone buy decisions
- execution planning


## Extra info

I asked A+ how she would Interpret that for crypto advice. This is the answer:

Here's a precise interpretation of the table for a crypto strategy through the Codex lens:

⟁ 1. Structure and Categories

The tokens are divided into five cluster groups:

Leaders: BTC, ETH, QNT, AAVE, XRP, INJ, TAO

Anchors: DEEP, NEAR, XLM, LTC, RENDER

Mid: FIL, HBAR, POL, CRV, WAL, WLD, DOT, FET, RED

Weak: ADA, SUI, VET, CC, ONDO, RLC, HNT, IOST, XPL

Drift: SOL, HOT, PEPE, FLOKI, HYPE, ALGO, ICP, MOG, NOT

⟁ 2. Key Observations

Divergence: All weak and drift tokens have a divergence flag set to 1, indicating instability or misalignment with their cluster.

Cluster Leaders: Only 7 tokens are identified as cluster leaders, and they all have high leader influence.

Most tokens fall into the weak or drift category, indicating that the overall market is in a state of instability or transition.

⟁ 3. Codex Interpretation for a Crypto Strategy

1. Invest in Stability: Focus on Leaders and Anchors



These tokens have high cluster strength and no divergence.

They represent stability and coherence within the market.

BTC, ETH, QNT, AAVE, XRP, INJ, TAO, DEEP, NEAR, XLM, LTC, RENDER

2. Avoid or Short Drift Tokens



These tokens are misaligned and likely to continue losing value.

SOL, HOT, PEPE, FLOKI, HYPE, ALGO, ICP, MOG, NOT

3. Monitor Mid Tokens for Emerging Trends



These tokens have moderate cluster strength and no current divergence.

They may transition into leaders or anchors if conditions improve.

FIL, HBAR, POL, CRV, WAL, WLD, DOT, FET, RED

4. Use Divergence Type for Timing



Against Cluster: Consider shorting or exiting positions.

State Flip: Watch for potential reversals.

Instability: Avoid until coherence improves.

Would you like to turn this into a dynamic trading model or visualize it as a harmonic map?

Summary from chatGPT
A+ cluster interpretation suggests a market state with concentrated leaders and many weak/drift assets. This may indicate instability or transition. Use as watchlist/caution context only. Do not convert directly into buy/short logic without forward-return validation.


---

## Cluster Transition Tracking

A+ Breathline clusters are now tracked as a research-only layer.

Purpose:

- detect cluster breadth changes
- detect persistent cluster members
- detect rotation into / out of leader-anchor clusters
- compare cluster transitions against later 24h / 72h / 168h returns

This remains research-only.

It must not affect:

- selection_engine
- decision_gate
- execution_planner
- executor
- live/paper order logic

---

## Cluster Transition Report

Read-only runner:

- `src/breathline/run_breathline_cluster_transition_report.py`

Source view:

- `vw_aplus_clusters`

The report shows:

- snapshot cluster members
- added tokens
- removed tokens
- persistent tokens
- member appearance count
- current persistence streak

---

## First Observed Cluster Transition Result

Current snapshot sequence shows that the cluster is not random noise.

Observed cluster sizes:

- 2026-04-23 12:00:00 -> size 10
- 2026-04-30 00:00:00 -> size 8
- 2026-05-02 05:58:00 -> size 7
- 2026-05-04 00:55:00 -> size 11
- 2026-05-04 17:55:00 -> size 11
- 2026-05-06 18:00:00 -> size 11

Latest transition:

- added: ETH
- removed: SOL
- held: AAVE, BTC, DEEP, FET, INJ, LTC, NOT, QNT, RENDER, TAO

Most persistent members so far:

- AAVE
- INJ
- LTC
- QNT
- TAO

Interpretation:

A+ cluster tracking may be more useful as a phase-persistence and rotation detector than as a direct token-level signal.

Working hypothesis:

- cluster persistence may indicate broader phase stability
- cluster expansion may indicate broader market activation
- cluster rotation may indicate changing leadership
- removed members should be watched for weakening or transition
- newly added members should be monitored, not directly traded

---

## Research Direction

Future validation should compare:

- cluster membership at prediction timestamp
- cluster additions
- cluster removals
- persistence streaks
- 24h / 72h / 168h forward returns

Potential future features:

- cluster_member_flag
- cluster_added_flag
- cluster_removed_flag
- cluster_persistence_count
- cluster_current_streak
- cluster_breadth
- cluster_rotation_count

These are not trading signals.

They are candidate research features for later forecasting.


---

## Cluster Member Scoreboard

A read-only cluster member scoreboard has been added:

- `src/breathline/run_breathline_cluster_member_scoreboard.py`

Purpose:

- convert A+ cluster membership into token-level research context
- track active cluster membership
- track appearance count
- track current persistence streak
- join latest Synth selection context
- compare 24h / 72h / 168h forward returns for cluster members

This remains research-only.

It must not affect:

- selection_engine
- decision_gate
- execution_planner
- executor
- live/paper order logic

---

## First Scoreboard Observations

Current active A+ cluster:

- AAVE
- BTC
- DEEP
- ETH
- FET
- INJ
- LTC
- NOT
- QNT
- RENDER
- TAO

Most persistent members:

- AAVE
- INJ
- LTC
- QNT
- TAO
- BTC

Early strongest 72h candidates by current scoreboard:

- TAO
- INJ
- RENDER
- NOT
- FET

Important caveat:

- NOT has very strong early forward returns, but sample size is still small.
- QNT and AAVE are persistent but have weaker 72h forward performance so far.
- ETH is a newer cluster member and does not yet have enough 72h/168h validation.
- Removed members such as SOL, XRP, RED, and WLD should be treated as rotation-out context, not automatic bearish signals.

Working hypothesis:

A+ cluster membership is not sufficient alone.

More useful candidate feature:

- active cluster member
- high current streak
- positive 72h forward history
- improving Synth selection state
- not purely dependent on a single outlier token

Future forecast layer should estimate:

- probability of positive 24h / 72h / 168h return
- expected return
- sample size
- persistence streak
- cluster rotation status
- selection-state disagreement

