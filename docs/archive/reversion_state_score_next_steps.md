# Reversion State Score - Next Steps

## Goal

Move from legacy proxy label (`rejected_htf_4h`) toward an explicit state primitive (`reversion_state_score`).

## Confirmed so far

- LOW bucket is negative
- MID bucket is mildly positive
- HIGH bucket is strongest
- VERY_HIGH remains positive but undersampled

## Next tasks

1. Validate score behavior on:
   - rejected_htf_top10_4h
   - strong_candidate_4h
   - watch_4h

2. Test whether EMA50 terms add real predictive lift

3. Decide target integration point:
   - signal_engine_state
   - interpreter_state
   - separate state snapshot layer

4. Decide whether to materialize:
   - reversion_state_score
   - reversion_state_bucket

5. Keep `rejected_htf_4h` as legacy comparison policy until replacement is validated

## Non-goals for now

- do not remove event tables
- do not mass-rename legacy files
- do not replace live logic prematurely

