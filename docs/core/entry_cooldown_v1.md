# Entry Cooldown v1

## Doel

`entry_cooldown_v1` voorkomt directe re-entry in hetzelfde asset kort na een close.

Dit voorkomt simpele churn zoals:

    close
    → volgende cycle
    → direct opnieuw buy

---

## Plaats in pipeline

selection_engine → decision_gate → entry_cooldown → execution_planner

---

## Scope v1

Cooldown wordt toegepast in de live paper loop als extra policy overlay vóór planner write.

Belangrijk:

- selection blijft market-only
- planner blijft planner-only
- cooldown beïnvloedt alleen of een entry mag doorstromen

---

## Werking

De policy kijkt naar:

- laatste `PAPER_FILL_CLOSE`
- aantal gesloten 1h candles sinds die close

Als:

    candles_since_close < cooldown_candles_after_close

dan wordt entry geblokkeerd.

---

## Input

Bronnen:

- `execution_event`
- `obs_market_candle`

---

## Output

Per asset:

- `cooldown_blocked = True/False`
- reden:
  - `NO_RECENT_CLOSE`
  - `ENTRY_COOLDOWN_ACTIVE`
  - `ENTRY_COOLDOWN_CLEARED`

---

## Waarom dit nodig is

Zonder cooldown kan een simpele engine onrustig worden in zijwaartse marktstructuur.

Met cooldown wordt entry-flow rustiger en realistischer.

---

## Toekomst

In een latere versie kan cooldown verplaatst worden naar een formelere account-aware permission laag of policy matrix.
