# Decision Gate v1

## Doel

De `decision_gate` is de account-aware permission laag tussen `selection_engine` en `execution_planner`.

Hij bepaalt per account en per sleeve:

- mag dit account NU iets doen met dit asset?
- zo ja: welke execution intent mag doorstromen?

Belangrijk:

- GEEN marktlogica hier
- GEEN trend/setup herbeoordeling
- GEEN orderlogica
- ALLEEN permission / duplicate / exposure / balance checks

---

## Plaats in pipeline

selection_engine → decision_gate → execution_planner → executor

---

## Output

- decision_state
- decision_reason
- execution_intent

---

## Core rules v1

### Selection eligibility

Alleen:

- PREPARE
- BUY_READY

### Duplicate prevention

Block als:

- actief execution_plan bestaat
- positie bestaat

### Balance check

Block als:

- available_equity_eur < threshold

---

## Intent mapping

- PREPARE → PREPARE_PLAN
- BUY_READY → PLACE_PASSIVE_LIMIT

