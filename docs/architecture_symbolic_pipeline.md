# SYNTH — SYMBOLIC PIPELINE ARCHITECTURE

## 1. PURPOSE

Define the symbolic (breathline / Codex) pipeline as a parallel system
to the market data pipeline.

This pipeline translates symbolic input into structured context
that can influence strategy decisions without directly generating trades.

---

## 2. CORE PIPELINE

raw_codex_input  
→ breathline_compass  
→ breathline_feat  
→ strategy_signal  
→ decision_log  

---

## 3. ROLE OF EACH LAYER

raw_codex_input  
- external symbolic input  
- non-structured  
- human / model generated  

breathline_compass  
- stores raw + normalized symbolic state  
- source of truth  
- time-indexed  

breathline_feat  
- converts symbolic state into numeric features  
- deterministic  
- strategy-readable  

strategy_signal  
- consumes both:
  - market features
  - breathline features  
- produces contextual bias (not raw trades)  

decision_log  
- stores human-readable explanation  
- no raw symbolic data  
- only interpreted meaning  

---

## 4. SEPARATION OF CONCERNS

The symbolic pipeline must remain independent from:

- ETL
- candle normalization
- market feature computation

Integration happens ONLY at:

strategy_signal

---

## 5. HARD RULE

Symbolic input must never directly trigger trades.

It may only influence:

- prioritization  
- confidence  
- filtering  
- bias  

---

## 6. DATA FLOW PRINCIPLE

Codex input is symbolic source material.  
breathline_compass stores it.  
breathline_feat translates it.  
strategy_signal uses it.  
decision_log explains its effect.  

---

## 7. DESIGN GOAL

Keep the symbolic system:

- deterministic in translation  
- interpretable  
- testable  
- optional (can be disabled without breaking system)  

---

## 8. FUTURE EXTENSION

Possible future modules:

- symbolic anomaly detection  
- cross-asset symbolic alignment  
- time-phase clustering  
- symbolic regime overlays  

These must plug into breathline_feat or strategy_signal,
never bypass the pipeline.
