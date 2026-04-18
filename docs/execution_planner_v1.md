# Execution Planner v1

## Doel

De `execution_planner` vertaalt decision output naar een concreet execution plan.

Belangrijk:
- maakt GEEN directe orders
- maakt een "intent plan" dat door execution wordt uitgevoerd

---

## Plaats in pipeline
decision_gate → execution_planner → executor / order agent

---

## Input

- decision_state
- execution_intent
- target_notional_eur
- asset_id
- sleeve

Later:
- signal context
- price data

---

## Output = execution_plan

Nog GEEN order, maar een plan.

---

## Execution Plan Velden

- plan_id
- account_id
- asset_id
- sleeve

- plan_state
- execution_style

- target_notional_eur

- entry_zone_low
- entry_zone_high
- expected_bottom_price

- invalidation_price

- urgency_level

- created_ts_utc

---

## Plan States

| State | Betekenis |
|------|----------|
| DRAFT | net aangemaakt |
| IDLE | wacht op trigger |
| PLACED | order geplaatst |
| MONITORING | actief monitoren |
| ESCALATED | naar urgent flow |
| FILLED | uitgevoerd |
| CANCELLED | gestopt |

---

## Execution Styles

| Style | Betekenis |
|------|----------|
| PASSIVE_LIMIT | normale limit order |
| URGENT | agressieve entry via agent |

---

## PREPARE gedrag
execution_intent = PREPARE_PLAN plan_state = IDLE

Doet:

- entry zones bepalen
- expected bottom bepalen
- sizing bepalen
- nog GEEN order

---

## BUY_READY gedrag
execution_intent = PLACE_PASSIVE_LIMIT execution_style = PASSIVE_LIMIT

Doet:

- limit order plaatsen dicht bij entry zone
- monitoring starten

---

## URGENT gedrag (later)
execution_intent = ESCALATE_URGENT execution_style = URGENT
Doet:

- door naar orderbook-based agent
- agressievere prijsbepaling

---

## Entry Concept

Planner werkt met zones:

- entry_zone_low
- entry_zone_high
- expected_bottom_price

Dit maakt:

- betere limit placement
- flexibiliteit bij volatility
- voorbereiding mogelijk vóór trigger

---

## Funds / Reservatie

v1:

✔ interne reservatie (logisch)
❌ geen echte exchange locking

Later:

- reservering per plan
- allocatie tracking

---

## Belangrijk patroon
PREPARE = thesis bouwen BUY_READY = thesis activeren URGENT = thesis afdwingen

---

## v1 Scope

✔ Implementeren:
- PREPARE → IDLE plan
- BUY_READY → PASSIVE_LIMIT plan

⏳ Later:
- urgent execution
- dynamic repricing
- partial fills
- advanced monitoring

---

## Samenvatting

De planner vertaalt:
"dit is interessant" → "zo willen we het kopen"

Zonder direct orders te plaatsen.

