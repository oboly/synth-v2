# Exit Policy v1

## Doel

`exit_policy_v1` scant open paper-posities en beslist of een exit-plan moet worden aangemaakt.

Belangrijk:

- GEEN fills hier
- GEEN capital mutation hier
- GEEN position close hier

De policy doet alleen:

- open positie inspecteren
- TP/SL trigger beoordelen
- exit plan laten aanmaken via planner

---

## Plaats in pipeline

selection_engine → decision_gate → execution_planner → executor  
positie open → exit_policy → execution_planner → executor

---

## Scope v1

Alleen paper mode.

Triggers:

- `take_profit_pct`
- `stop_loss_pct`

---

## Input

Bronnen:

- `portfolio_position`
- laatste prijs uit `obs_market_candle`
- bestaande `execution_plan` rows voor duplicate-exit check

---

## Output

Per open positie:

- geen actie
- of nieuwe `CLOSE_POSITION_MARKET_PAPER` planrow

---

## Regels v1

### Take profit

Als:

    current_price >= avg_entry_price * (1 + take_profit_pct)

dan:

- exit trigger
- exit plan aanmaken

### Stop loss

Als:

    current_price <= avg_entry_price * (1 - stop_loss_pct)

dan:

- exit trigger
- exit plan aanmaken

### Duplicate prevention

Als al een actieve exit-plan bestaat voor hetzelfde asset/sleeve/account:

- geen nieuw exit plan

---

## Architectuurgrens

Exit policy mag NIET:

- fills simuleren
- positie sluiten
- pnl boeken
- sleeve capital muteren

Dat hoort downstream in:

- planner
- executor

---

## v1 resultaat

Deze laag maakt de paper engine zelfstandig genoeg om niet alleen entries te openen, maar ook geautomatiseerd exits te plannen.
