# Dashboard / Mission Control Design

## Purpose

The dashboard should expose the bot's reasoning.

Not just charts.

It should make visible:
- what is happening
- what it means
- what the bot wants to do
- what prevents action

## Suggested panels

### 1. Market Overview
Display current high-level state:
- market regime
- altseason phase
- fear / greed
- breathline compass state
- volatility state
- risk state

### 2. Portfolio State
Per asset:
- current phase
- signal strength
- role / strategy relevance
- action bias
- blocked / unblocked

### 3. Trigger Board
Per strategy:
- conditions met
- conditions missing
- trigger state
- last update

Example:

```text
Breakout strategy
compression: yes
confirmation: no
risk okay: yes
trigger: not armed
```

### 4. Strategy Board
Show:
- primary active strategy
- secondary strategy
- disabled strategies
- reason summary

### 5. Predictions / Compass Panel
Use for weekly or larger horizon only.

Show:
- breathline weekly rank
- sentiment monthly path
- anchor cluster
- likely next rotation cluster

Important:
This panel is a compass, not a timing tool.

### 6. Explainability / Why panel
This is crucial.

For every meaningful decision, show:
- why enter
- why not enter
- why exit
- why rotate
- what blocked action

## Top status line idea

A single human-readable summary line is recommended.

Example:

```text
Current Mode: selective alt expansion
Dominant Strategy: rotation swing
Compass Bias: favor phase 3→4 leaders
Risk Status: medium
Action: hold active winners, watch pressure candidates, block low-quality noise
```

## Design rule

Build the state model and explainability first.
UI polish comes later.
