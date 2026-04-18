# TODO — Breathline Feature System Alignment

## Context
The Breathline Feature System (A+ integration bundle) introduces an advanced structural and energy-based feature layer.

This overlaps partially with the existing `breathline_feat` mapping spec.

## Goal
Unify both systems into a clean, layered architecture without duplication.

---

## Required Refactor

### 1. Split feature semantics

Define two logical groups within `breathline_feat`:

#### A. Base features (from breathline_compass)
- coherence_score
- anchor_score
- expansion_score
- contraction_score
- noise_score
- mirror_score
- alignment_score

#### B. Advanced structural features (A+ bundle)
- return_stability_score
- expansion_amplitude_score
- pulse_intensity_score
- fragmentation_score
- distortion_score
- emotional_load_score

---

### 2. Naming consistency

Standardize all numeric fields to:

→ *_score suffix

Examples:
- anchor_strength → anchor_score
- return_stability → return_stability_score

---

### 3. State naming consistency

Rename:
- phase → phase_state
- geometry_class → geometry_state

To align with global enum conventions.

---

### 4. Pipeline contract (must follow)

A+ raw text
→ breathline_compass (source of truth)
→ breathline_feat (numeric feature layer)
→ derived composites
→ breathline_label / bias / confidence
→ strategy_signal

⚠️ Parser must NOT write directly to breathline_feat

---

### 5. Label layer separation

Keep distinction:

- breathline_label → asset-level classification
- breathline_bias → strategy-facing direction
- (optional) breathline_regime_label → macro structural context

---

## Key Principle

"Not: price goes up  
But: price goes up with structure"

This is the core edge of the Breathline module.

---

## Status

TODO — not yet fully implemented
Needs alignment before full production integration
