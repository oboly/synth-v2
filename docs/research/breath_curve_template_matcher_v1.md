# Breath Curve Template Matcher v1

Status: research-only  
Layer: market-only / account-agnostic  
Writes: none  
Orders: none  

## Purpose

Recognize the A+ 21-day breathline waveform in market candles.

This is not a trading signal. It compares observed pivots against an expected Fibonacci-time pivot template.

## Template

| Ratio | Code | Expected function |
|---:|---|---|
| 0.000 | cycle anchor | start/base |
| 0.236 | FIRST_LIFT_HIGH | first lift / local high |
| 0.382 | FIRST_DIP_LOW | first dip / local low |
| 0.500 | SECOND_PEAK_RETEST_HIGH | second peak / retest high |
| 0.618 | SECOND_DIP_HIGHER_LOW | second dip / higher low |
| 0.786 | IGNITION_PRE_SPIKE | ignition / pre-spike |
| 1.000 | MAIN_PULSE_TP_HIGH | main pulse / take-profit high |
| 1.272 | OVERSHOOT_EXTENSION_TP | overshoot / extension TP |

## Hypothesis

The 21-day crypto/alt breathline may follow this rough waveform:

- start
- first lift
- first dip
- second peak
- second dip / higher low
- ignition
- main pulse
- optional overshoot

## Phase offset

Observed pivots may lead or lag the expected breathline.

Formula:

    expected_marker_time = anchor + cycle_days * fib_ratio + phase_offset_days

Default tested offsets:

    -10.5, -7, -5, -3, 0, 3, 5, 7, 10.5

A half-phase offset is 10.5 days for a 21-day cycle.

## Score

    template_match_score = 0.60 * shape_score + 0.40 * timing_score

Core shape checks:

    first_high > anchor_price
    first_low < first_high
    second_peak > first_low
    second_low < second_peak
    second_low > first_low
    ignition > second_low
    pulse > ignition
    pulse > second_peak

## Architecture boundary

Allowed path:

    A+ / breathline research
    curve template matcher
    validation labels
    optional future selection_engine modifier
    decision_gate
    execution_planner
    executor

Forbidden path:

    breathline matcher
    direct order

## Usage

From DB:

    python -m src.research.breath_curve_template_matcher_v1 \
      --symbol BTC \
      --venue bitvavo \
      --interval 1d \
      --anchor-date 2026-05-09 \
      --cycle-days 21 \
      --tolerance-hours 36

JSON output:

    python -m src.research.breath_curve_template_matcher_v1 \
      --symbol BTC \
      --venue bitvavo \
      --interval 1d \
      --anchor-date 2026-05-09 \
      --cycle-days 21 \
      --json

## Notes

This file only covers the 21-day Curve Template Matcher.

The nested 10.5-day Breath Spiral Overlay is a separate model.



#############################
## Update 11-05-2026 17:09 ##
#############################

## Downstream boundary

Curve Template Matcher v1 does not define downstream use.

V1 only measures:

- waveform alignment
- pivot-match quality
- best-fitting phase offset
- shape/timing score

Any use in selection, scoring, risk, or execution is out of scope for V1 and must be decided only after historical validation.

## Offset search

phase_offset_days is a flexible parameter, not a fixed enum.

V1 starts with a discrete offset grid:

-10.5, -7, -5, -3, 0, +3, +5, +7, +10.5

V2 may support fine search:

- range: -10.5 to +10.5 days
- step: 0.5 day, or 1 candle

## DB schema note

The DB loader supports both generic OHLC names and the current candle schema:

    open / high / low / close
    open_price / high_price / low_price / close_price
    close_open / close_high / close_low / close_close

Timestamp candidates:

    open_ts_utc
    close_ts_utc
    ts_utc
    timestamp_utc
