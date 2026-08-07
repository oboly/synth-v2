# TODO — Signal Matrix Dashboard

## Status

Active next dashboard lane for Synth v2.14.

This is the upstream reporting/research lane that should come before more
manual ladder dashboard tuning.

Core rule:

```text
Elke timeframe mag zijn eigen waarheid hebben; het dashboard toont conflicten, het lost ze niet verborgen op.
```

The signal matrix is the transparent signal inventory.
It is not a composed advice surface.
It must not collapse primitive signals into hidden final conclusions.

## Sources

```text
Recent chat handoff for Synth v2.14 signal-matrix direction.
docs/archive/manual_ladder_dashboard.md (archived; see docs/todo/profit_plan_live_ladder.md for active ladder work)
docs/todo/ui_webview.md
docs/research/paper_advice_manual_trading_cockpit_v1.md
```

## Current state / facts

- Current paper/manual dashboard work already renders composed review context.
- That composed layer is useful for later consumption, but it is too downstream
  for transparent signal inventory work.
- Old Paper Advice dashboard should remain parked as a debug/review surface.
- Manual ladder dashboard should become a downstream consumer of the signal
  matrix, not the place where primitive truth is first merged.
- Legacy Synth v1 MTF behavior is a research prior only:
  - `LINK`, `XLM` leaned no-MTF
  - `HBAR`, `HOT` leaned MTF/adaptive
  - `HYPE` looked weak for MTF/adaptive
  - `SUI`, `XRP` need caution/retest framing
- These old observations must not be hardcoded into runtime or report logic.

## Core direction

```text
signal inventory first
composed ladder dashboard second
execution remains off
```

Build:

```text
signal_matrix_static_dashboard_v1
```

Before:

```text
further manual ladder dashboard tuning
```

## Required dashboard layers

The matrix should expose layers separately, not hide one inside another.

Primary reading order:

```text
1. Breath/Fibo frame
2. Primitive signals per timeframe
3. Local pattern candidates per timeframe
4. HTF context shown separately, not as veto/block
5. Regime context
6. External catalyst / dirty squeeze flags
7. Outcome validation readiness fields
8. Debug/source details
```

## Required local pattern candidates

Per timeframe, show pattern candidates explicitly:

- `bullflag_candidate`
- `impulse_candidate`
- `compression_candidate`
- `failed_breakout`

These are matrix rows/fields only.
They are not direct trade actions.

## P0 — Signal Matrix Static Dashboard V1

Implementation target:

```text
src/reporting/run_signal_matrix_static_dashboard_v1.py
docs/research/signal_matrix_dashboard_v1.md
```

Smoke output target:

```text
/tmp/signal_matrix_dashboard_v1.html
```

Later Odroid publish path may exist later, but that is not part of this TODO.

## Required display principles

The dashboard must show primitive market truth per asset and timeframe.

Allowed:

- primitive signal states
- per-timeframe conflicts
- separate HTF and LTF context
- separate regime and catalyst context
- separate source and freshness/debug fields

Not allowed:

- `BUY_READY`
- `AVOID`
- `WATCH_ONLY` as hidden final conclusion
- HTF/LTF veto logic
- hand-made hidden signal combinations
- hidden conflict resolution
- blackbox scoring

The matrix may show:

```text
timeframe A says X
timeframe B says Y
regime says Z
fibo frame says K
```

But it must not silently transform that into:

```text
therefore BUY / AVOID / NO_EDGE
```

## Primitive signal expectations

Each timeframe row should remain readable as its own state surface.

Examples of what belongs here:

- direction / bias
- reclaim / retest state
- support / resistance proximity
- target / extension proximity
- compression / expansion state
- pattern candidate flags
- freshness / source timestamp

The dashboard should expose conflicts directly instead of solving them.

## Open tasks by priority

### P0 — Define signal matrix schema

Tasks:

- Specify matrix rows/columns for asset x timeframe inventory.
- Separate primitive signals from downstream interpretation fields.
- Define how Breath/Fibo frame is shown without collapsing timeframe conflicts.
- Define how regime context is shown as context only.
- Define catalyst / dirty squeeze flags as separate context only.
- Define outcome-validation-readiness fields:
  - sample availability
  - source availability
  - freshness
  - replay-safe/not-replay-safe

### P0 — Keep HTF and LTF separate

Tasks:

- Show HTF context as its own panel/row group.
- Show LTF/pattern candidates independently.
- Do not let HTF implicitly veto LTF in the renderer.
- Do not let LTF implicitly override HTF in the renderer.
- Show disagreement explicitly.

### P1 — Park old paper advice as legacy debug surface

Tasks:

- Keep old Paper Advice dashboard available for debug/reference only.
- Do not use it as the primary design basis for v2.14.
- Keep manual ladder dashboard downstream from the future signal matrix.

### P1 — Research prior handling

Tasks:

- Record old Synth v1 asset-level MTF tendencies as research prior only.
- Keep them out of runtime behavior and out of hidden matrix logic.
- Allow later validation work to compare assets by:
  - no-MTF tendency
  - MTF/adaptive tendency
  - conflict stability
  - regime dependence

### P2 — Outcome validation readiness overlays

Tasks:

- Add display-only readiness fields for whether a primitive signal family has:
  - enough history
  - enough replay-safe context
  - symbol concentration issues
  - regime segmentation availability
- Keep these as debug/research readiness markers, not trade states.

## Blockers / dependencies

- Need a clear primitive signal inventory definition before building the
  composed downstream dashboard.
- Manual ladder dashboard should not continue to absorb hidden interpretation
  logic before the signal matrix exists.
- Existing signal families may need inventory review before matrix rendering:
  - breath/fibo context
  - reclaim/retest context
  - target proximity
  - pattern-candidate flags
  - regime context

## Boundary

```text
reporting/research only
market-only
account-agnostic
no selection_engine changes
no decision_gate changes
no execution_planner changes
no executor changes
no broker calls
no broker writes
no order submission
```

The signal matrix is a transparent reporting surface only.
It must not become hidden policy logic.

## Non-goals

- no live trading
- no paper trading
- no decision permission logic
- no account-aware position logic
- no HTF/LTF veto engine
- no runtime promotion
- no hidden final advice state
- no manual ladder/action commands in this lane

## Downstream relationship

Correct direction:

```text
signal_matrix_static_dashboard_v1
-> manual_ladder_dashboard_v1 consumes matrix/context
-> later research/validation decides what survives
```

Not:

```text
manual ladder dashboard invents hidden signal combinations first
```
