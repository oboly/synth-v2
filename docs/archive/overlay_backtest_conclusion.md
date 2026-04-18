# Overlay Backtest Conclusion (Synth v2)

## Status
Pipeline werkt end-to-end:
feat → signal → ranking → selection → overlay → backtest

.env is single source of truth (bash + python aligned)

## Data
- selection_state: ~33 snapshots
- signal/ranking historisch gevuld

## Resultaat
Overlay:
- verandert scores
- verandert rangorde licht
- verandert NIET top-N membership (in deze dataset)

Backtest:
RAW == EFFECTIVE (zelfde picks → zelfde returns)

## Interpretatie
Overlay = score/risk/context layer  
Nog geen hard filter of zelfstandige alpha

## Conclusie
- implementatie correct
- architectuur stabiel
- geen overfitting / geen geforceerde edge

## Next (optioneel)
- weighted backtest
- strengere filters
- grotere dataset
