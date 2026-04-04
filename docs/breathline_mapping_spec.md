# SYNTH — BREATHLINE MAPPING SPEC

## 1. PURPOSE

This mapping layer converts symbolic Codex / breathline readings into structured fields
that Synth can use downstream.

Goal:

raw Codex-style input  
→ normalized breathline_compass record  
→ derived breathline_feat values  
→ strategy_signal context  

This layer does NOT produce trades directly.

It only translates symbolic field language into structured machine-usable context.

---

## 2. POSITION IN THE PIPELINE

raw_codex_input  
→ breathline_compass  
→ breathline_feat  
→ strategy_signal  
→ decision_log  

Where:

- breathline_compass = stored normalized raw reading  
- breathline_feat = derived feature-style scores usable by strategies  

---

## 3. RAW INPUT FORMAT

Typical raw input may contain fields like:

- token  
- phase  
- coherence  
- symbolic_geometry  
- current_field  
- codex_note  

Example:

token = CC  
phase = 9D  
coherence = High  
symbolic_geometry = Codex node  
current_field = Reflective  
codex_note = mirror phase, stable breathline  

---

## 4. breathline_compass (NORMALIZED STORAGE)

### Raw fields (source of truth)

- asset_id  
- prediction_ts_utc  
- source_name  
- source_type  
- raw_phase_label  
- raw_coherence_label  
- raw_geometry_label  
- raw_field_label  
- raw_note  

### Normalized fields

- phase_state  
- coherence_state  
- field_state  
- geometry_state  

---

## 5. NORMALIZED STATE ENUMS

### phase_state

CONVERGENCE  
COMPRESSION  
EXPANSION  
INTEGRATION  
MIRROR  
ANCHOR  
CONTRACTION  
REACTIVE  
STABLE  

---

### coherence_state

VERY_HIGH  
HIGH  
MODERATE  
LOW  
FRAGMENTED  
STABLE  
RISING  

---

### field_state

EXPANDING  
STABILIZING  
REFLECTIVE  
DISTORTED  
NEUTRAL  
CONTRACTING  
REACTIVE  

---

### geometry_state

ANCHOR_NODE  
CODEX_NODE  
AI_RECURSION  
TIME_RECURSION  
SUPPLY_CHAIN_LATTICE  
EMOTIONAL_VOLATILITY  
UNDEFINED  

---

## 6. MAPPING RULES — RAW → NORMALIZED

### Phase mappings

8.5D → CONVERGENCE / MIRROR / TRANSITIONAL  
9D   → ANCHOR / MIRROR  
8D   → STABLE / NEUTRAL  
7D   → REACTIVE / LOW_ORDER  

---

### Field mappings

Expanding    → EXPANDING  
Stabilizing  → STABILIZING  
Reflective   → REFLECTIVE  
Distorted    → DISTORTED  
Reactive     → REACTIVE  
Contracting  → CONTRACTING  

---

### Geometry mappings

Anchor node              → ANCHOR_NODE  
Codex node               → CODEX_NODE  
AI recursion             → AI_RECURSION  
Time recursion           → TIME_RECURSION  
Memory loops             → TIME_RECURSION  
Supply chain lattice     → SUPPLY_CHAIN_LATTICE  
Emotional volatility     → EMOTIONAL_VOLATILITY  
Undefined                → UNDEFINED  

---

## 7. breathline_feat — DERIVED FEATURES

Minimum V1 fields:

- phase_bias_score  
- coherence_score  
- anchor_score  
- expansion_score  
- contraction_score  
- noise_score  
- mirror_score  
- alignment_score  

Optional:

- strategic_patience_bias  
- sell_resistance_bias  
- add_on_weakness_bias  
- watch_priority_score  

---

## 8. SCORE INTERPRETATION (GUIDELINES)

### Strong structured expansion

phase_bias_score     ≈ +0.8  
coherence_score      ≈ +0.8  
expansion_score      ≈ +0.9  
alignment_score      ≈ +0.8  

---

### Mirror / reflective stability

phase_bias_score     ≈ +0.4  
coherence_score      ≈ +0.9  
mirror_score         ≈ +0.8  
anchor_score         ≈ +0.6  
strategic_patience   ≈ +0.8  

---

### Fragmented / distorted

phase_bias_score     ≈ -0.5  
coherence_score      ≈ -0.7  
contraction_score    ≈ +0.6  
noise_score          ≈ +0.4  
alignment_score      ≈ -0.7  

---

### Reactive / emotional volatility

phase_bias_score     ≈ -0.4  
coherence_score      ≈ -0.8  
noise_score          ≈ +0.9  
strategic_patience   ≈ -0.5  

---

### Stable / neutral

phase_bias_score     ≈ 0.0  
coherence_score      ≈ +0.4  
alignment_score      ≈ +0.2  

---

## 9. STRATEGY USAGE RULES

Strategies must NOT consume raw Codex text.

They consume only breathline_feat.

### Examples

breakout_strategy  
- prefer:
  - high expansion_score  
  - high coherence_score  
- avoid:
  - high contraction_score  
  - high noise_score  

swing_rotation_strategy  
- prefer:
  - positive phase_bias_score  
  - high coherence_score  
  - high watch_priority_score  

parking_rotation_strategy  
- prefer:
  - anchor-like states  
  - stable coherence  
  - low noise  

volatility_strategy  
- allow:
  - reactive states  
- but classify:
  - non-anchor  
  - high-risk  

---

## 10. decision_log USAGE

Do NOT store raw breathline values.

Use interpreted summaries:

Examples:

"Strong breathline alignment supports continuation"  

"Mirror phase → patience, no aggressive positioning"  

"Contraction detected → reduced priority"  

"Reactive / noisy → lower trust"  

---

## 11. DASHBOARD FIELDS

Per asset:

- breathline_phase_state  
- coherence_state  
- field_state  
- geometry_state  
- alignment_score  
- watch_priority_score  

Example:

BTC  
Phase: ANCHOR  
Coherence: STABLE  
Alignment: STRONG  
Role: Strategic anchor  

---

## 12. ENGINEERING RULES

Rule 1  
Raw Codex language must be preserved in breathline_compass.  

Rule 2  
Normalized states must be finite and explicit.  

Rule 3  
Derived scores must be deterministic.  

Rule 4  
Strategies consume breathline_feat only.  

Rule 5  
decision_log receives only interpreted summaries.  

---

## 13. MINIMAL V1 IMPLEMENTATION

Store:

- breathline_compass (raw + normalized)  
- breathline_feat (scores)  
- strategy_signal (context)  

Minimum fields:

- phase_bias_score  
- coherence_score  
- anchor_score  
- expansion_score  
- contraction_score  
- noise_score  
- alignment_score  

---

## 14. GOLDEN RULE

Codex input is symbolic source material.  
breathline_compass stores it.  
breathline_feat translates it.  
strategy_signal uses it.  
decision_log explains its effect.
