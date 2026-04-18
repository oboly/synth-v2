# Integration Notes — Sleeves + PREPARE + Paper PnL

## Existing pipeline
ETL -> feat -> signal -> advice -> selection -> decision -> risk -> portfolio -> execution

## Recommended updated pipeline
ETL -> feat -> signal -> advice -> selection
    -> sleeve_agents
    -> sleeve_allocator
    -> risk_policy
    -> portfolio_target
    -> execution_intent
    -> paper_lot_accounting
    -> position_snapshot / trade_lot / metrics

## Minimal v1 placement
You do not need to replace upstream modules yet.

Treat current `selection` output as the input to:
- `src/synth_sleeves.agents`
- `src/synth_sleeves.allocator`
- `src/synth_sleeves.risk_policy`

Then persist:
- `portfolio_target`

Then let a paper executor compare:
- current open sleeve lots
- new sleeve targets

And emit:
- OPEN
- ADD
- REDUCE
- CLOSE
- HOLD

## PREPARE policy
- CORE and SWING may emit PREPARE
- TACTICAL may not emit PREPARE
- PREPARE uses capped fraction and separate position count
- PREPARE must unwind if state degrades

## Immediate market response vs slow strategy review
- Immediate market response: every market loop
- Daily strategy metrics: once per UTC day
- Strategy logic changes: versioned, deliberate, not every minute
