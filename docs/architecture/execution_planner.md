# Synth v2 — Future Execution Planner Note

## Purpose
Add a dedicated execution layer **after** decision, risk, and portfolio targeting.

This layer does **not** decide whether to buy or sell.  
It decides **how** to execute an already-approved target intelligently.

---

## Position in pipeline

Planner cadence is candle-driven and ETL-gated.
A planner run is valid only after the relevant candle is closed and ETL/context refresh for that candle has completed.

Current high-level flow:

ETL → feat → signal / selection → decision → risk → portfolio_target

Future extension:

ETL → feat → signal / selection → decision → risk → portfolio_target
→ execution_planner
→ order_manager
→ exchange_adapter

---

## Why this layer exists

Two systems can have identical signals and target sizes, but very different real-world results depending on execution quality.

Execution quality affects:
- spread capture
- slippage
- fill probability
- average entry price
- average exit price
- partial fill handling
- missed breakout risk

So execution is a separate optimization problem.

---

## Core responsibility

Translate a target like:

- asset = ICP
- target_fraction = 0.12
- action = ENTER_LONG
- urgency = medium

into an execution plan like:

- order_style = BALANCED_LIMIT
- entry_band_pct = 0.8%
- ladder:
  - 30% at level A
  - 40% at level B
  - 30% at level C
- timeout_seconds = 1800
- chase_rule = passive_once_then_reprice
- cancel_rule = if market breaks invalidation

---

## Scope of execution_planner

The execution planner should decide:

- market vs limit vs laddered limit
- number of slices
- price levels
- passive vs aggressive behavior
- timeout and reprice rules
- when to accept worse fill to avoid missing move
- when to step back and wait

It should output a structured execution plan, not place orders directly.

---

## Not in scope

The execution planner should **not** decide:
- which asset to trade
- whether the thesis is valid
- target portfolio weights
- strategic sleeve allocation

Those belong upstream.

---

## Suggested future inputs

### From upstream strategy stack
- asset_id
- sleeve_code
- desired_action
- target_fraction
- urgency
- confidence_score
- signal_state / selection_state

### From market structure / features
- ATR / atr_pct
- local range high / low
- support / resistance zones
- breakout distance
- wick behavior
- recent volatility regime

### From market microstructure
- spread
- top-of-book depth
- order book imbalance
- recent trade flow
- short-term liquidity

### From execution state
- already placed orders
- partial fills
- remaining quantity
- previous reprice count
- elapsed time

---

## Suggested execution modes

### PASSIVE_ACCUMULATE
Use when:
- PREPARE states
- early entries
- low urgency
- mean reversion / zone entries

Behavior:
- place lower / more patient limits
- prioritize price improvement
- do not chase quickly

### BALANCED_LIMIT
Use when:
- standard ENTER_LONG
- moderate urgency
- decent confirmation

Behavior:
- place near fair entry zone
- moderate laddering
- reprice if needed

### AGGRESSIVE_CONFIRM
Use when:
- breakout confirmation
- high urgency
- strong signal + strong participation

Behavior:
- prioritize fill quality less than participation
- tighter ladder or near-touch limit
- faster reprice logic

### EXIT_PASSIVE
Use when:
- non-urgent trim
- taking profit into strength
- scaling out

### EXIT_AGGRESSIVE
Use when:
- invalidation
- risk event
- urgent de-risking

---

## Relationship to current Synth states

### PREPARE
Preferred execution style:
- PASSIVE_ACCUMULATE

Reason:
- early alignment
- no need to chase
- better to harvest spread / local pullbacks

### ENTER_LONG
Preferred execution style:
- BALANCED_LIMIT or AGGRESSIVE_CONFIRM

Reason:
- confirmation exists
- missing the move matters more

### SCALP_ONLY
Preferred execution style:
- fast and opportunistic
- often more aggressive than PREPARE

Reason:
- short horizon
- timing sensitivity is high

---

## Entry band concept

Avoid simplistic fixed logic like “always ±10%”.

Instead use a dynamic execution band based on:
- atr_pct
- spread
- local range size
- zone distance
- urgency

Example concept:

entry_band_pct = f(
    atr_pct,
    local_range_pct,
    spread_pct,
    urgency
)

This allows:
- tighter bands in calm markets
- wider bands in volatile markets

---

## Ladder concept

Instead of one limit order, allow multi-level execution:

Example:
- 25% at support touch
- 50% at deeper value level
- 25% at breakout reclaim

This is especially useful for:
- PREPARE accumulation
- larger target sizes
- volatile assets

---

## Order manager separation

Execution planner should produce the plan.

A later **order_manager** should handle:
- placing orders
- updating orders
- cancel / replace
- partial fills
- final execution logs

So:

execution_planner = brain  
order_manager = hands

---

## Exchange adapter separation

Bitvavo integration should sit below the order manager:

order_manager
→ exchange_adapter_bitvavo

This keeps strategy / execution logic exchange-agnostic.

---

## Future output shape (concept)

Example execution plan object:

- plan_id
- asset_id
- sleeve_code
- desired_action
- execution_mode
- target_fraction
- target_notional_eur
- entry_band_pct
- ladder_json
- max_slippage_pct
- timeout_seconds
- reprice_policy
- cancel_policy
- urgency
- created_ts_utc

---

## Why this matters

This layer can improve results even when upstream signals stay unchanged.

Potential gains:
- better average fills
- less slippage
- more intelligent partial fills
- fewer emotional / impulsive entries
- better fit between PREPARE and ENTER behavior

---

## Implementation timing

This is a **later-phase module**.

Do not prioritize before:
- selection logic is stable
- sleeve logic is stable
- sizing logic is stable
- Bitvavo communication layer exists

---

EXECUTION WORKER V1 VALIDATION COMPLETE

Validated in paper mode:
- monitor branch: confirmed
- passive reprice branch: confirmed
- timeout escalate branch: confirmed
- timeout abort branch: confirmed

Additional confirmed behavior:
- downward repricing now works
- passive_price_eur is synchronized back into execution_plan on reprice
- dedupe issue for active plans was cleaned up
- planner rerun did not recreate duplicate active plan

Observed execution_event evidence:
- PAPER_MONITOR_OK
- PAPER_REPRICE_PASSIVE (direction=down)
- PAPER_ESCALATE_URGENT_LIMIT
- PAPER_ABORT_TIMEOUT

Current conclusion:
- execution worker v1 is now branch-tested end-to-end in paper mode
- safe next step is not immediate full live rollout, but controlled hardening and then tiny-notional live post-only validation


___

## Suggested name

Preferred module name:

`execution_planner`

Reason:
- broad enough for limit logic, laddering, spread capture, urgency, and repricing
- cleaner than overly narrow names

---

## One-line summary

The future `execution_planner` should convert approved target allocations into optimized limit/ladder execution plans that account for spread, zones, volatility, urgency, and fill behavior.
