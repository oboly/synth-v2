# Selection Engine v2

## Purpose
Select assets that are:
- structurally valid
- data-quality safe
- competitively strong
- suitable for allocation

This layer decides:
"which assets are allowed to compete for capital?"

---

## Inputs
- signal_engine_state
- advice_state
- asset_interval_quality_v2
- asset

---

## Outputs
Table: selection_state

Core fields:
- selection_state (BUY_READY, PREPARE, WATCHLIST, NEUTRAL, AVOID)
- selection_score
- priority_rank
- allow_trade_flag
- allowed_sleeves
- blocked_reason

---

## Quality gating

### 1d
- BLOCKED → AVOID
- NEW → max PREPARE
- DEGRADED → allowed with penalty
- TRUSTED → no penalty

### 4h
- BLOCKED → AVOID
- DEGRADED → no BUY_READY unless strong
- TRUSTED → normal

### 1h
- BLOCKED → no refinement
- DEGRADED → weak refinement
- TRUSTED → full refinement

---

## Structure gating

### 1d
Defines macro bias:
- bullish → proceed
- bearish → no BUY_READY

### 4h
Defines readiness:
- strong → PREPARE / BUY_READY
- weak → WATCHLIST / NEUTRAL

---

## Scoring model

trade_quality_score =
  0.35 * context_score +
  0.20 * pullback_quality +
  0.20 * expansion_position +
  0.15 * signal_confidence +
  0.10 * relative_strength

timing_refinement_score:
- +0.03 confirming
-  0.00 neutral
- -0.05 lagging

selection_score =
  trade_quality_score +
  timing_refinement_score -
  quality_penalty

---

## Ranking

Assets are ranked by selection_score.

Rules:
- rank alone is insufficient
- absolute threshold required

---

## State assignment

BUY_READY:
- strong 1d + 4h
- high score
- top rank

PREPARE:
- good structure
- not fully confirmed

WATCHLIST:
- interesting but early

NEUTRAL:
- no edge

AVOID:
- blocked or invalid

---

## Sleeve compatibility

CORE_STRUCTURAL:
- requires 1d TRUSTED + 4h TRUSTED

SWING_STRUCTURAL:
- allows 1d TRUSTED / NEW / DEGRADED

TACTICAL_PULSE:
- tolerant to noise

EXPERIMENTAL:
- most permissive

---

## Block reasons

Examples:
- BLOCKED_1D_QUALITY
- BLOCKED_4H_QUALITY
- BLOCKED_SCORE_TOO_LOW
- BLOCKED_PRIORITY_TOO_LOW

---

## Summary field

Example:
"1d trusted bullish, 4h strong, 1h blocked, rank=3, score=0.61"

---

## Version
v2

## Status
draft

## Depends on
- asset_interval_quality_v2
- signal_engine_state

---

## Open questions
- dynamic thresholds?
- rank window size?
- 4h degraded tolerance?
