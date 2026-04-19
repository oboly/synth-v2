# Executor v1

## Doel

Voert execution_plan uit in paper mode.

---

## Ondersteund

- PREPARE_PLAN
- SPREAD_CAPTURE_PASSIVE

---

## PREPARE

- IDLE → PLANNED
- event: PAPER_PREPARE_ACK
- geen fill
- reservation blijft

---

## PASSIVE FILL

- plan → FILLED
- position open
- reservation → RELEASED
- reserved → deployed

---

## Doet NIET

- live trading
- orderbook logic
- reprice loops

