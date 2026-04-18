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
