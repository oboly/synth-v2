# Decision Gate v1

## Doel

De `decision_gate` is de account-aware laag tussen `selection_engine` en execution.

Hij bepaalt:

- mag dit account NU iets doen met dit asset?
- zo ja: wat is de execution intent?

Belangrijk:
- GEEN marktlogica hier
- ALLEEN portfolio / account / risk checks

---

## Plaats in pipeline
selection_engine → decision_gate → execution_planner → executor / agent
---

## Input

### Vanuit selection

- selection_state
- selection_score
- priority_rank
- allowed_sleeves

### Vanuit account / portfolio

- bestaande positie
- open orders
- execution plans
- account balance
- sleeve usage
- recente fills (cooldown)

---

## Output

- decision_state
- decision_reason
- execution_intent
- target_notional_eur
- sleeve_code

---

## Decision States

| State | Betekenis |
|------|----------|
| NO_ACTION | selection niet sterk genoeg |
| PREPARE_ALLOWED | plan mag voorbereid worden |
| EXECUTION_ALLOWED | mag richting order |
| BLOCKED_OPEN_ORDER | open order bestaat |
| BLOCKED_ACTIVE_PLAN | execution plan actief |
| BLOCKED_POSITION | positie al aanwezig |
| BLOCKED_COOLDOWN | recent fill |
| BLOCKED_SLEEVE | sleeve vol |
| BLOCKED_BALANCE | onvoldoende balans |
| BLOCKED_POLICY | policy restrictie |

---

## Execution Intent

| Intent | Betekenis |
|-------|----------|
| NONE | niets doen |
| PREPARE_PLAN | plan opbouwen |
| PLACE_PASSIVE_LIMIT | limit order plaatsen |
| ESCALATE_URGENT | naar urgent agent |

---

## Core Rules (v1)

### 1. Selection eligibility
selection_state NOT IN (PREPARE, BUY_READY) → decision_state = NO_ACTION → execution_intent = NONE

---

### 2. Duplicate / execution checks
IF open_order EXISTS → BLOCKED_OPEN_ORDER
IF active_plan EXISTS → BLOCKED_ACTIVE_PLAN
---

### 3. Cooldown
IF recent_fill WITHIN cooldown_window → BLOCKED_COOLDOWN

---

### 4. Sleeve capacity
IF sleeve allocation FULL → BLOCKED_SLEEVE

---

### 5. Balance check
IF available_balance < minimum_required → BLOCKED_BALANCE

---

### 6. Allowed flow
IF selection_state == PREPARE → PREPARE_ALLOWED → execution_intent = PREPARE_PLAN
IF selection_state == BUY_READY → EXECUTION_ALLOWED → execution_intent = PLACE_PASSIVE_LIMIT

---

## Belangrijk ontwerpprincipe
selection_engine = market opportunity decision_gate = account permission
De decision gate her-evalueert NOOIT:

- trend
- setup
- signal kwaliteit

---

## Multi-account voordeel

Dezelfde selection output kan gebruikt worden voor:

- meerdere accounts
- verschillende risk profiles
- verschillende sleeve configuraties

---

## v1 Scope

✔ Implementeren:
- selection filtering
- open order check
- active plan check
- basic balance check

⏳ Later:
- cooldown windows
- dynamic sizing
- advanced sleeve allocation
- multi-account orchestration

---

## SamenvattingPREPARE → plan voorbereiden BUY_READY → plan uitvoeren (passief)

De decision gate zorgt dat execution NIET dubbel gebeurt en account constraints worden gerespecteerd.

