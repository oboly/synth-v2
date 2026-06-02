## Martee Oracle Touch Semantics TODO

Status: TODO
Scope: research-only

### Purpose

Model how Martee Oracle zones behave when price touches a target/support/shoulder box.

Important:
A single wick/spike into a zone may count as a valid zone touch.
Do not require close-in-zone for all validations.

### Add fields

- target_box_low
- target_box_high
- touch_type
- touch_count
- first_touch_ts
- first_touch_price
- first_touch_candle_high
- first_touch_candle_low
- close_in_zone
- wick_touched_zone
- rejection_after_touch
- acceptance_in_zone
- retouch_after_correction
- retarget_triggered
- next_target_pending
- timeframe_signal_source
- daily_signal_state
- weekly_signal_state
- monthly_signal_state

### touch_type values

- NO_TOUCH
- WICK_TOUCH
- CLOSE_IN_ZONE
- FULL_CANDLE_IN_ZONE
- MULTI_CANDLE_ACCEPTANCE
- REJECTION_FROM_ZONE
- RETOUCH_AFTER_CORRECTION
- RECLAIM_AFTER_CORRECTION

### Oracle timeframe rule

- Monthly = macro map
- Weekly = main trend until it turns
- Daily = short-term pop/correction/bottoming signal

### Validation questions

- Does wick_touch_zone often complete Martee targets?
- Does close_in_zone outperform wick touch?
- Does second touch/reclaim after correction produce reliable next-leg moves?
- Are daily signals only useful when weekly trend agrees?
- Are target boxes better for TP review than fresh entry?

### Strategy interpretation

Target box first touch:
- TP_REVIEW
- CORRECTION_WATCH
- AVOID_FRESH_CHASE

Daily bottoming after correction:
- ADD_BACK_WATCH
- RETEST_ENTRY_CANDIDATE

Second touch / re-entry into target box:
- RETARGET_WATCH
- NEXT_TARGET_PENDING

Boundary:
Research-only. No execution logic.
