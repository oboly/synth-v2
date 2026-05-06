# Fib Exit Visual Validation V1

Status: research note  
Scope: Synth v2.6 fib/exit ladder research  
Live trading permission: NOT_GRANTED  

## Core finding

The fib exit ladder scoreboard is useful, but it is not sufficient by itself.

A high numerical return can come from:

- real fib/target responsiveness
- lucky ladder placement inside a bull trend
- a broad target family that happened to fill
- remaining moonbag exposure carrying the result

Therefore:

scoreboard_best_profile
≠
validated_exit_profile

The chart must visually confirm whether the detected anchor / target ladder actually maps meaningful tops.

## Visual validation labels

- VISUAL_PASS
- VISUAL_PASS_BUT_EARLY
- VISUAL_WEAK
- VISUAL_AMBIGUOUS
- VISUAL_FAIL

## Preliminary asset reads

| Symbol | Scoreboard best profile | Visual validation | Current interpretation |
|---|---|---|---|
| LINK | PRO_3X4X, max sell 0.80 | VISUAL_PASS_BUT_EARLY | Fib targets catch the main peaks well, but sell distribution should be more top-heavy. |
| XLM | PRO_3X4X, max sell 0.80 | VISUAL_PASS | Fib targets catch the three peaks very cleanly. Strong controlled fib-exit candidate. |
| HOT | EXPLOSIVE_SUPERCYCLE, max sell 0.40 | VISUAL_PASS_BUT_EARLY | Fib targets catch peak zones, but the asset keeps extending. Needs late/top-heavy ladder and large moonbag. |
| SOL | SUPERCYCLE, max sell 0.80 | VISUAL_WEAK | Scoreboard result looked good, but visual fib structure did not look convincing. Do not validate profile yet. |
| XRP | EXPLOSIVE_SUPERCYCLE, max sell 0.80 | VISUAL_AMBIGUOUS | Hard to judge visually. Needs alternative anchor/pivot tests before profile assignment. |

## Emerging profile hints

### CONTROLLED_3X4X_TOP_HEAVY

Candidate symbols:

- LINK
- XLM

Behavior:

- fib target family appears structurally meaningful
- multiple local or cycle peaks align with target zones
- early ladder rungs should be lighter
- upper rungs should carry more sell weight
- moonbag reserve remains useful, but does not need to dominate the whole profile

### EXPLOSIVE_SUPERCYCLE_LATE_MOONBAG

Candidate symbols:

- HOT

Behavior:

- fib target zones matter, but early exits miss large later extension
- ladder should start later / higher
- sell fraction should stay lower
- moonbag reserve should be large
- asset can continue far beyond standard target zones

### UNCONFIRMED_SUPERCYCLE

Candidate symbols:

- SOL
- XRP

Behavior:

- numerical result may be acceptable
- visual fib confirmation is weak or ambiguous
- requires alternative anchor logic before assigning a validated profile

## Diagnostic columns needed next

Future scoreboard/research output should include:

- scoreboard_profile_hint
- visual_validation_status
- validated_exit_profile_hint
- fib_exit_responsiveness_class
- ladder_timing_class
- distribution_hint
- moonbag_need_class
- early_sell_drag_pct
- post_ladder_peak_extension_pct
- top_cluster_capture_score

Suggested classes:

fib_exit_responsiveness_class:
- LOW
- MEDIUM
- HIGH

ladder_timing_class:
- TOO_EARLY
- GOOD
- TOO_LATE

distribution_hint:
- FRONT_LOADED
- BALANCED
- TOP_HEAVY
- LATE_TOP_HEAVY

moonbag_need_class:
- LOW
- MEDIUM
- HIGH
- EXTREME

## Architecture rule

This remains research-only.

Correct path:

research fib/target maps
-> asset exit profile candidate
-> decision_gate checks real position and permission
-> execution_planner creates passive limit sell ladder
-> executor places/monitors orders

Do not turn pro charts or fib ladders into direct buy/sell orders.  
Do not bypass decision_gate.  
Do not put ladder intelligence in executor.

## Core sentence

Pro charts are not the buy button; they are the harvest map.
