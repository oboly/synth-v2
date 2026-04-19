# Execution Planner v1

## Doel

Zet decision output om naar execution_plan + capital reservation.

---

## Flow

decision → plan → reservation → sleeve update

---

## Wat hij doet

- insert execution_plan
- insert capital_reservation
- update portfolio_sleeve:
  - reserved += amount
  - available -= amount

---

## Intent mapping

PREPARE_PLAN:
- plan_state = IDLE

PLACE_PASSIVE_LIMIT:
- plan_state = PLANNED

---

## Belangrijk

Planner doet GEEN:

- permission checks
- marktlogica
- execution

