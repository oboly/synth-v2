# External Forecast Event Registry TODO

Status: TODO
Scope: research-only
Runtime impact: none

## Core principle

External forecasts are not signals; they are timestamped hypotheses waiting to be scored.

Purpose:

Convert paid/pro/RV/Martee/A+/macro forecast windows into structured, timestamped forecast events that can later be validated against market outcomes.

This prevents external research from becoming hidden trade logic.

## Hard boundaries

External forecast events must not directly become:

- SELL_BTC
- BUY_READY
- BLOCK_BUYS
- RISK_OFF
- decision_gate permission
- execution_planner intent
- executor order logic

Allowed research labels:

- BTC_PEAK_WINDOW_WATCH
- TP_REVIEW_WINDOW
- ALT_ROTATION_WATCH
- BREATH_FIBO_TIMING_MARKER
- MACRO_STRESS_WINDOW
- CATALYST_WINDOW
- EVENT_VALIDATION_TARGET

## Why this exists

External sources often provide timing windows, such as:

- BTC peak window around a date
- alt rotation after BTC cools
- policy/catalyst windows
- RV event windows
- Martee support/shoulder timing
- Breath/Fibo timing markers

These are useful only if stored with:

- source timestamp
- forecast timestamp
- expected event window
- expected market behavior
- validation metrics
- post-window score

## Proposed doc/data lane

Initial document:

- docs/todo/external_forecast_event_registry.md

Later optional data files:

- data/research/external_forecast_event/external_forecast_event_seed_v1.jsonl
- data/research/external_forecast_event/external_forecast_validation_result_v1.jsonl

Later optional DB tables:

- external_forecast_event
- external_forecast_validation_result

## Proposed external_forecast_event fields

Required:

- forecast_id
- source_id
- source_name
- source_type
- source_date
- input_ts_utc
- forecast_created_ts_utc
- forecast_window_start
- forecast_window_end
- asset
- asset_group
- category
- forecast_type
- expected_behavior
- source_confidence_prior
- user_confidence_prior
- actionability
- architecture_boundary
- notes

Optional:

- related_indicator_code
- related_level_id
- related_catalyst_id
- related_macro_score_snapshot_id
- expected_direction
- expected_peak_date
- expected_pullback_date
- expected_rotation_window_start
- expected_rotation_window_end
- source_quote_currency
- runtime_quote_currency
- fx_conversion_required
- tags

## category values

- CRYPTO_MARKET
- BTC_TIMING
- ALT_ROTATION
- MACRO_BOND
- GEOPOLITICAL
- ENERGY
- TOKENIZATION
- REGULATION
- AI_INFRA
- DIGITAL_IDENTITY
- WEATHER_INFRA
- SPACE_DISCLOSURE
- SUPPLY_CHAIN
- PUBLIC_HEALTH

## forecast_type values

- PEAK_WINDOW
- PULLBACK_WINDOW
- ROTATION_WINDOW
- CATALYST_WINDOW
- EVENT_WINDOW
- SUPPORT_REACTION_WINDOW
- SHOULDER_BREAK_WINDOW
- TP_REVIEW_WINDOW
- MACRO_STRESS_WINDOW
- RANGE_EXPECTATION
- DIRECTIONAL_BIAS

## expected_behavior examples

- BTC peaks or exhausts near forecast window
- BTC cools after peak while alts rotate
- alts show relative strength after BTC stalls
- risk assets sell off due to macro shock
- oil rises on geopolitical stress
- target asset shows idiosyncratic catalyst squeeze
- asset enters TP review zone
- price reacts around support/shoulder zone

## Validation after event window

For BTC peak windows, measure:

- BTC return +1d
- BTC return +3d
- BTC return +7d
- BTC return +14d
- wick behavior
- volume behavior
- exhaustion behavior
- distance to fib target
- BTC dominance move
- alt relative strength after window
- whether alts rotate while BTC cools

For broader event windows, measure:

- did event occur
- first matching event timestamp
- severity score
- market response
- false positive notes
- partial hit notes
- public anchor quality

## Proposed external_forecast_validation_result fields

Required:

- validation_id
- forecast_id
- validation_asof_ts_utc
- validation_window_completed
- validation_status
- hit_score
- timing_score
- market_response_score
- notes

BTC-specific:

- btc_return_1d_pct
- btc_return_3d_pct
- btc_return_7d_pct
- btc_return_14d_pct
- btc_wick_score
- btc_volume_exhaustion_score
- btc_distance_to_fib_target_pct
- btc_dominance_change_pct
- alt_relative_strength_after_window
- alt_rotation_confirmed

Allowed validation_status:

- PENDING
- HIT
- PARTIAL_HIT
- MISS
- EXPIRED
- INSUFFICIENT_DATA

## Example: BTC 19 June peak window

Forecast labels:

- BTC_PEAK_WINDOW_WATCH
- TP_REVIEW_WINDOW
- ALT_ROTATION_WATCH
- BREATH_FIBO_TIMING_MARKER

Forecast hypothesis:

BTC may form a local peak or exhaustion window around 2026-06-19. After the window, validate whether BTC cools and whether alts rotate while BTC dominance weakens.

Validation after 2026-06-19:

- BTC return +1d / +3d / +7d / +14d
- wick / volume / exhaustion behavior
- distance to fib target
- BTC dominance move
- alt relative strength after window
- whether alts rotate while BTC cools

Hard boundary:

This forecast must not directly become SELL_BTC, BLOCK_BUYS, or RISK_OFF.

Allowed use:

- BTC_PEAK_WINDOW_WATCH
- TP_REVIEW_WINDOW
- ALT_ROTATION_WATCH
- BREATH_FIBO_TIMING_MARKER

## Example JSONL seed

Example only, not a committed seed file yet:

{"forecast_id":"BTC_2026_06_19_PEAK_WINDOW_WATCH","source_name":"external PRO / Breath-Fibo timing","source_type":"EXTERNAL_FORECAST","source_date":"2026-05-30","forecast_window_start":"2026-06-18","forecast_window_end":"2026-06-20","asset":"BTC","asset_group":"CRYPTO","category":"BTC_TIMING","forecast_type":"PEAK_WINDOW","expected_behavior":"BTC may form local peak/exhaustion around 2026-06-19; after window measure whether BTC cools and alts rotate.","source_confidence_prior":"HIGH","user_confidence_prior":"HIGH","actionability":"WATCH_ONLY","architecture_boundary":"research-only; not SELL_BTC, not BLOCK_BUYS, not RISK_OFF","tags":["BTC","peak-window","breath-fibo","alt-rotation"]}

## Correct path

external forecast note
→ external_forecast_event
→ post-window validation
→ validation report
→ optional research feature candidate only after evidence

Never:

external forecast note
→ trade signal
→ decision permission
→ execution intent
