# SYNTH — MODULE ARCHITECTURE

## 1. CORE PRINCIPLE

Synth is designed as a full modular system.

Modules may be unimplemented,
but must never be undefined.

The architecture defines all modules up front.
Implementation follows in phases.

---

## 2. DESIGN-FIRST RULE

All major modules must exist in the design,
even if not implemented yet.

---

## 3. REQUIRED MODULES

- alt_market_phase_detector  
- wave_rotation_classifier  
- breathline_feat  
- thesis_bias  
- trend_volume_classifier  

---

## 4. MODULE LAYERS

OBSERVATION  
FEATURE  
INTERPRETATION  
PROJECTION  

---

## 5. EXAMPLE PLACEMENT

alt_market_phase_detector → INTERPRETATION  
wave_rotation_classifier → INTERPRETATION  
breathline_feat → FEATURE  
thesis_bias → PROJECTION  
trend_volume_classifier → INTERPRETATION  

---

## 6. MODULE CONTRACT

Each module defines:

- purpose  
- inputs  
- outputs  
- dependencies  
- layer  
- status  

---

## 7. STATUS TYPES

implemented  
planned_v1_next  
planned_future  

---

## 8. HARD RULE

Do not design based on what exists.  
Design based on what must exist.  

---

## 9. IMPLEMENTATION MODEL

Phase-based:

Phase 1  
- ETL  
- base features  

Phase 2  
- structure  
- zones  

Phase 3  
- alignment  
- advanced interpreters  

Phase 4  
- optimization / ML  

---

## 10. SUMMARY

Design breadth first.  
Implement in phases.  
Do not let v1 constrain the system.  
