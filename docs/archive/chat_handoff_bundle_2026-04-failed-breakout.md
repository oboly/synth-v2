# Chat Handoff Bundle - Failed Breakout / Research Architecture

## Main outcomes from this chat

### 1. Research architecture clarified

Confirmed research structure:

src/research/
    pattern_families/
    trigger_tests/
    evaluation/

Canonical workflow:

Known Pattern Family
-> State Definition
-> Trigger Definition
-> Forward Return Evaluation
-> Regime Split
-> Keep / Kill / Refine

### 2. Pattern family verdicts

#### KEEP / PRIORITY
- FAILED_BREAKOUT_4H_V1

Recent-window result:
- count: 389
- avg next_return_4h: -0.020247
- median next_return_4h: -0.018464
- OTHER avg next_return_4h: 0.000170

Interpretation:
- bearish post-failure family
- useful first as avoid-long / bearish context / anti-breakout-chase overlay
- not yet first deployed as direct short execution family

#### REFINE
- TREND_PULLBACK_CONTINUATION_4H_V1
- VOLATILITY_COMPRESSION_BREAKOUT_4H_V1

#### KILL
- REVERSION_EXTREME_* direct family variants
- REVERSION_EXTREME + low participation
- REVERSION_EXTREME + ATR filter
- REVERSION_EXTREME + liquid/watchlist filter
- REVERSION_EXTREME + T+1 / T+2 timing

### 3. strategy_signal_context integration added

Confirmed table now includes:
- failed_breakout_flag_4h
- breakout_failure_state
- bearish_failure_context_score
- avoid_long_overlay_flag

Publish bridge works.

Observed published context summary:
- failed_breakout rows: 389
- neutral rows: 22446

### 4. Important schema lesson

Do not publish into existing tables by assumption.

Always inspect target schema first.

For strategy_signal_context, actual unique key / anchor is:
- asset_id
- interval_code
- context_ts_utc

There is no venue column in that table.

### 5. Important context join lesson

Exact timestamp join was too strict.

Correct context consumption requires an as-of join:

latest strategy_signal_context.context_ts_utc
<= anchor timestamp

For the current overlay use-case, the relevant anchor is:
- selection_state.advice_ts_4h_utc

not necessarily:
- selection_state.asof_ts_utc

### 6. First consumer implemented conceptually

Selection/advice overlay created via:
- v_selection_with_failed_breakout_overlay

Current heuristic:

If:
- failed_breakout_flag_4h = 1
- avoid_long_overlay_flag = 1
- selection_bias IN ('BULLISH', 'LONG', 'BUY', 'LONG_BIAS')

Then:
- selection_score_after_overlay = selection_score - 0.10

Else:
- unchanged

Observed impacted example:
- ICP STRONG_CANDIDATE LONG_BIAS
- 0.560100 -> 0.460100

Interpretation:
- first deployment role is valid as avoid-long overlay / anti-breakout-chase filter

### 7. Current deployment semantics for FAILED_BREAKOUT_4H_V1

Recommended order:

#### Phase 1
- avoid-long overlay
- bearish context modifier
- anti-breakout-chase filter

#### Phase 2
- promote as bearish context state in strategy_signal_context / interpreter-consumable logic

#### Phase 3
- later test as dedicated short candidate family

### 8. Docs updated in this chat

Relevant docs/files touched:
- docs/architecture/pattern_family_research.md
- docs/architecture/research_architecture_closeout.md
- docs/architecture/failed_breakout_deployment_plan.md
- docs/todo/research_flow_next_steps.md
- docs/todo/failed_breakout_next_steps.md
- docs/todo/research_registry_template.md
- docs/todo/chat_handoff_bundle_2026-04-failed-breakout.md

### 9. Recommended next step in next chat

Most logical next step:

Decide where the failed breakout overlay should be made visible first in real outputs:
- advice/reporting layer
- selection enriched view
- ranking visibility

After that:
- decide whether to keep overlay heuristic at fixed -0.10
- or evolve toward explicit advice semantics / context-weighted penalty

## Working principles retained

- known families first, not rediscovery
- family != signal
- context != entry
- trigger layer is essential
- explicit forward return naming is mandatory
- top examples are not enough
- hard verdicts save time
- context joins often need as-of semantics

