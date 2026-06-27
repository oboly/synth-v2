# Breathline UI: Phase, Path, Duration, and History v1

## Status

Todo / UI specification.

## Scope

Make the Breathline state understandable and inspectable on the Short Swing / Profit Plan coin detail card.

This is a presentation and read-model task only.

Do not change:

* Breathline calculation or calibration logic
* market-data ingestion
* FibNavigationMap calculation
* selection_engine
* decision_gate
* execution_planner
* executor or broker writes
* order submission, cancellation, or portfolio allocation logic

The UI must render model output. It must not infer, repair, or invent Breathline states.

## Terminology

Use **Breathline** as the primary user-facing term.

Allowed technical/internal distinction:

* `Breathline` = user-facing cycle, state progression, route, and history
* `Breath Curve` = optional internal/calibration term only

Do not use `Breath Curve` as the card label.

Required card heading:

    BREATHLINE

Do not use:

    BREATH CURVE

## Core Problem

The current card shows a compact state such as:

    IGNITION_PRE_SPIKE · -7

This is ambiguous.

A user cannot determine:

* whether `-7` is time, score, age, confidence, or offset
* how long the current Breathline phase has been active
* what the A+ baseline phase window is when supplied
* whether a per-coin calibration window exists yet
* which phase or checkpoint is expected next
* whether the Breathline recently moved forward, reversed, jumped, or recalibrated
* whether the displayed route is observed history or a current model expectation

The UI must expose these distinctions without turning every coin card into a research report.

## Required Card Module

Replace the current Breath Curve field with a dedicated Breathline module.

Baseline presentation:

    BREATHLINE
    IGNITION · PRE-SPIKE
    Baseline: A+ Prime-17 / 21d average
    Reference: BTC-led
    Offset −7d · active 1d 03h

Definition:

    Offset = the coin template timing offset in days relative to the BTC-led Breathline reference.

Rules:

* phase label is human-readable
* subphase is optional but preferred when known
* `Offset −7d` must be explicitly labelled as an offset
* offset is never displayed as a bare trailing number
* offset is never described as anything other than offset
* `active` is the actual elapsed time since the current Breathline phase began
* phase age must not be derived from price freshness or map age
* missing phase start time must render as `Age unavailable`, not a guessed duration

## Required Breathline Path Ribbon

Show a compact full-width path below the primary card fields.

Example:

    BREATHLINE PATH
    SECOND DIP → IGNITION → MAIN PULSE → EXTENSION
                    ● current

Rules:

* path represents the A+ baseline route for the current active epoch
* the route is the active epoch baseline path, not a generic possible sequence
* current phase is visually distinct
* expected next phase may be shown when supplied by the read model
* `NEXT CHECKPOINT` remains separate from `NEXT PHASE`
* do not silently map a checkpoint to a phase unless the engine explicitly provides that relation

When no route is available:

    BREATHLINE PATH
    Path unavailable · awaiting verified map state

## Required Duration Context

Show active phase age, A+ baseline phase window, and coin calibration window separately.

Example:

    Active phase age         1d 03h
    A+ baseline phase window 8h–2d · median 1d
    Coin calibration window  10h–1d 18h · median 22h · n=31

Required fields when available:

* current phase age
* A+ baseline phase window
* coin calibration window
* median duration where supplied
* comparable-case count for coin calibration where supplied

Rules:

* Active phase age = elapsed current phase time
* A+ baseline phase window = model average when supplied
* Coin calibration window = per-coin historical refinement only when campaign results exist
* the UI may show the A+ baseline phase window without waiting for per-coin historical calibration
* coin calibration statistics must come from measured, validated historical examples
* comparison cohort must be attributable to horizon, symbol/asset group, phase, and regime where available
* do not display a coin calibration window from an empty or insufficient sample
* do not imply that a phase follows a deterministic clock
* do not fabricate durations

When baseline duration is unavailable:

    A+ baseline phase window  Unavailable

When coin calibration is unavailable:

    Coin calibration window  Learning · no coin calibration yet

Do not show fabricated ranges, zero-value statistics, or false precision.

## Required Expandable Breathline History

Provide an expandable history control from the Breathline module.

Label:

    Breathline history

Default state:

* collapsed on card overview
* expanded on explicit user action
* latest transitions first

Each history event must show:

* timestamp
* previous phase → new phase
* transition direction/type
* transition step magnitude where applicable
* engine-provided reason or trigger
* confidence where available
* map revision or epoch identifier where available

Example:

    27 Jun 14:11
    SECOND_DIP_HIGHER_LOW → IGNITION_PRE_SPIKE
    Forward +1
    Reason: higher-low retained + ignition threshold entered
    Confidence: 0.78
    Map revision: 14

Supported transition types:

* `FORWARD`
* `REVERSAL`
* `JUMP`
* `RECALIBRATION`
* `INITIALIZED`

Do not collapse all state changes into generic `updated`.

## Reversal and Route-Change State

When the expected route changes materially, show a compact explicit state.

Example:

    Path changed · reversal detected
    Previous expected phase: MAIN_PULSE_TP_HIGH
    Current expected phase: SECOND_DIP_HIGHER_LOW

Rules:

* route change is informational, not a trade instruction
* reversal must be visually distinguishable from normal forward progression
* recalibration must be visually distinguishable from a market-driven phase transition
* re-anchor events must be visually distinguishable from normal forward progression
* an epoch or map replacement must not be displayed as a normal forward step

## Read-Model Contract

The UI should consume explicit read-model fields equivalent to:

* `breathline_phase`
* `breathline_subphase`
* `breathline_offset_days`
* `breathline_phase_started_at`
* `breathline_expected_path`
* `breathline_expected_next_phase`
* `breathline_baseline_name`
* `breathline_reference_name`
* `breathline_baseline_phase_window`
* `breathline_coin_calibration_window`
* `breathline_transition_history`
* `breathline_map_revision`
* `breathline_epoch_id`

Suggested transition-history fields:

* `transitioned_at`
* `from_phase`
* `to_phase`
* `transition_type`
* `step_delta`
* `reason_code`
* `reason_display`
* `confidence`
* `map_revision`
* `epoch_id`

The UI must not reconstruct transition history from screenshots, card state, timestamps, or inferred previous values.

## Visual Priority

Recommended right-column order:

    SETUP
    REENTRY_SETUP

    BREATHLINE
    IGNITION · PRE-SPIKE
    Baseline: A+ Prime-17 / 21d average
    Reference: BTC-led
    Offset −7d · active 1d 03h

    NEXT CHECKPOINT
    MAIN_PULSE_TP_HIGH

Place the Breathline Path ribbon beneath the primary two-column card grid.

Place detailed duration context and Breathline History behind expansion or in the detail view, unless the card has sufficient width.

## Acceptance Criteria

* card heading uses `BREATHLINE`
* no user-facing `BREATH CURVE` label remains in this module
* offset cannot be mistaken for phase age, score, or confidence
* current phase age is visible when source data exists
* A+ baseline phase window may be shown when supplied even before coin calibration exists
* coin calibration window is shown only with sufficient verified samples
* expected Breathline path is visually distinct from observed transition history
* next checkpoint remains distinct from next Breathline phase
* forward, reversal, jump, recalibration, re-anchor, and initialization are inspectable
* missing data is explicit and never silently synthesized
* no change occurs to market calculation, policy, or execution layers
