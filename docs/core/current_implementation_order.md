# Current Implementation Order

## Doel

Dit document beschrijft de actuele implementatievolgorde van het systeem.

Belangrijk:
- Dit is de ENIGE bron van waarheid voor volgorde
- Geen losse notes / tijdelijke plannen buiten docs/
- Oude plannen worden verwijderd of gearchiveerd

---

## Architectuur overzicht

market data
→ quality layer
→ selection_engine
→ decision_gate
→ execution_planner
→ executor / agents
→ portfolio / account state
→ reporting

---

## Fase 1 — Data & Selection (huidige status: ✔ grotendeels klaar)

- ETL candles stabiliseren
- quality layer stabiliseren
- selection_engine_v2 afronden
- selection states correct krijgen:
  - WATCHLIST
  - PREPARE
  - BUY_READY

---

## Fase 2 — Decision Layer (next)

Implementeren:

### decision_gate

- selection filtering
- open order check
- active execution plan check
- basic balance check

Output:
- decision_state
- execution_intent

---

## Fase 3 — Execution Planning

Implementeren:

### execution_planner

- PREPARE → plan (IDLE)
- BUY_READY → passive limit plan
- plan structuur definiëren

Nog niet:
- urgent agent
- complexe repricing

---

## Fase 4 — Execution & Portfolio

Implementeren:

- paper execution applier
- lots / fills verwerking
- portfolio state
- target vs actual tracking

---

## Fase 5 — Account & Metrics

Implementeren:

- wallet_equity snapshot
- sleeve allocation tracking
- PnL (realized / unrealized)
- metrics en dashboards

---

## Belangrijk ontwerpprincipe

selection_engine = market intelligence
decision_gate = account permission
execution_planner = execution intent
executor = order handling

---

## Richtlijnen

- Geen losse *.txt plannen in root
- Alle architectuur in docs/
- Oude plannen:
  - verwijderen
  - of verplaatsen naar docs/archive/

---

## Samenvatting

PREPARE → voorbereiden
BUY_READY → uitvoeren (passief)
URGENT → later via aparte agent

Dit document wordt actief bijgehouden en vervangt oudere implementation notes.

