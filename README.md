# Synth v2

A structured, modular trading system focused on robustness, explainability, and strict separation of concerns.

Product direction and priorities: `docs/strategy/synth_v2_outcome_and_priorities.md`.

---

## Core Philosophy

The system is designed around clear functional layers:

- observe
- interpret
- strategize
- decide
- execute

Each layer has a strict responsibility and must not leak into others.

---

## Architecture (Critical)
selection_engine   = market opportunity (account-agnostic) decision_gate      = account permission (account-aware) execution_planner  = execution intent executor / agents  = order handling
### Rules

- Never mix responsibilities between layers
- No shortcuts that bypass layers
- No account logic inside selection_engine
- No execution logic inside decision_gate

---

## Selection Semantics

### States

- WATCHLIST → interesting but not actionable
- PREPARE → setup almost ready, waiting for confirmation
- BUY_READY → ready for execution planning

### PREPARE

PREPARE means:
- thesis is forming
- waiting for final signal
- may pass through decision_gate
- may produce PREPARE_PLAN
- must NOT directly execute

---

## Execution Intent (v1)

- NONE
- PREPARE_PLAN
- PLACE_PASSIVE_LIMIT
- (future) ESCALATE_URGENT

Definitions:

- PREPARE_PLAN → prepare capital / intent
- PLACE_PASSIVE_LIMIT → place limit order near expected entry
- ESCALATE_URGENT → handled by separate agent (not in v1)

---

## Candle & Data Policy

- No synthetic candles
- No zero-volume fillers
- No forward-filled prices
- Missing candles:
  - detect
  - log
  - expose in quality layer
  - do NOT penalize calculations directly

Future:
- optional low-volume heuristics

---

## Portfolio Separation

Selection is always account-agnostic.

The following belong to decision_gate:

- open orders
- active execution plans
- cooldowns
- sleeve constraints
- balance checks
- existing positions

---

## Current Focus

The system currently focuses on:

- data collection (ETL)
- feature computation
- market interpretation
- selection generation
- decision scaffolding
- execution planning (v1)
- explainability

Execution agents and advanced order logic are intentionally simplified.

---

## Repository Structure

- `docs/` → canonical architecture & design
- `configs/` → configuration and thresholds
- `src/` → system implementation
- `scripts/` → execution helpers
- `database/` → schema and migrations

No temporary notes or planning files outside `docs/`.

---

## Documentation Rules

- All architecture lives in `docs/`
- No loose `.txt` notes in root
- Obsolete docs must be:
  - removed, or
  - moved to `docs/archive/`
- `current_implementation_order.md` is the single source of truth

---

## Design Principles

- robustness > cleverness
- clarity > speed
- explicit > implicit
- deterministic behavior preferred
- separation of concerns is critical

---

## System Direction
PREPARE   → build thesis BUY_READY → activate thesis URGENT    → future specialized execution path

---

## Notes

- All timestamps in UTC
- Asset table is the master universe
- System is built for multi-account future usage

