# Advice Policy Router Integration Design V1

## Status
Design-only. No implementation.

## Purpose
Define how the advice layer may later consume validated market-only policy router preview context.

The advice layer may surface route context.
The advice layer must not create account permission.
The advice layer must not create execution intent.
The advice layer must not place orders.

## Current validated route
ROUTE_GBMD_4H_BOUNCE_CONTEXT

Evidence:
- ROUTE_VALIDATED_FOR_PREVIEW
- 4h n_ret 3,539
- 4h avg_ret +0.328%
- 4h win_rate 57.5%
- ROUTE_NO_MATCH avg_ret -0.368%
- ROUTE_NO_MATCH win_rate 43.5%
- weekly pass 5/6
- 24h SHORT_WINDOW_ONLY_CONFIRMED
- route_is_permission=false
- route_is_order_intent=false

Meaning:
- short-window bounce context only
- not buy/sell advice
- not permission
- not execution intent
- not a long-horizon hold context

## Layer boundary

Allowed future inputs:
- paper_advice_observation
- policy_router_preview_observation
- active_regime_observation
- selection_state
- trade_setup_filter_observation
- trade_setup_policy_preview_observation
- execution_zone_context as existing market-only context if already used by advice

Forbidden:
- account state
- balances
- positions
- portfolio exposure
- order book write intent
- broker permissions
- paper/live branching
- decision_gate output
- execution_planner output
- executor output

Explicit separation:
- policy_router_preview says: market context route exists
- advice integration says: surface route-context in advice language
- decision_gate says: account permission
- execution_planner says: execution intent
- executor handles orders

## Proposed advice integration semantics

Future advice layer may add route-context fields such as:

policy_route_code
policy_route_status
policy_route_confidence
policy_route_reason_codes_json
policy_route_allowed_family_json
policy_route_blocked_family_json
policy_route_context_label

No migration yet. This is design only.

## Allowed wording

Allowed advice-context wording:
- ROUTE_CONTEXT
- SHORT_WINDOW_BOUNCE_CONTEXT
- WATCH_FOR_RECLAIM_CONFIRMATION
- CONTEXT_ONLY
- NOT_PERMISSION
- NOT_ORDER_INTENT

Forbidden wording:
- BUY
- SELL
- ENTER
- EXIT
- ALLOW_TRADE
- PERMISSION_GRANTED
- EXECUTE
- ORDER
- SIZE
- POSITION

Important:
Existing advice actions may already contain words like BLOCK_NEW_24H_ENTRY or DO_NOT_ADD.
This design must not add new positive permission wording.
For this route, avoid "entry" phrasing unless explicitly negative/blocking.
Prefer "context" and "watch" language.

## Route-to-advice mapping design

For ROUTE_GBMD_4H_BOUNCE_CONTEXT:

If route_status = ROUTE_CANDIDATE:
- advice may add:
  policy_route_context_label = SHORT_WINDOW_BOUNCE_CONTEXT
  policy_route_note = Market-only short-window bounce context detected.
- advice may prefer:
  WATCH_FOR_RECLAIM_CONFIRMATION
- advice must block or caution against:
  LONG_HORIZON_HOLD
  SWING_CONTINUATION_WITHOUT_CONFIRMATION
  BREAKOUT_FOLLOW_WITHOUT_CONFIRMATION

But:
- route candidate must not override setup_filter_state
- route candidate must not override policy_decision
- route candidate must not turn FAIL into PASS
- route candidate must not create allow_trade_flag
- route candidate must not bypass decision_gate

## Route precedence

Route context is advisory/contextual only.

Suggested precedence:
1. Hard avoid / blocked market states remain dominant.
2. setup_filter_state = FAIL remains FAIL.
3. policy_decision blocks remain blocks.
4. route context may only enrich WATCH/CONTEXT outputs.
5. route context may not upgrade anything to trade permission.
6. route context may not turn FAIL into PASS.
7. route context may not bypass decision_gate.

## Suggested future states

If implemented later, possible advice states:
- ROUTE_CONTEXT_ONLY
- WATCH_ROUTE_RECLAIM_CONFIRMATION
- ROUTE_BLOCKED_BY_SETUP
- ROUTE_BLOCKED_BY_POLICY
- ROUTE_NO_MATCH

These are not permissions.

## Required safety metadata

Any future implementation must include source_ref_json:

{
  "scope": "market-only account-agnostic advice route integration preview",
  "broker_calls": 0,
  "broker_writes": 0,
  "order_submission": 0,
  "live_orders": 0,
  "route_is_permission": false,
  "route_is_order_intent": false,
  "advice_is_permission": false,
  "advice_is_order_intent": false,
  "decision_gate_changes": 0,
  "execution_planner_changes": 0,
  "executor_changes": 0,
  "paper_live_logic": "not_allowed",
  "account_state": "not_allowed"
}

## Validation required before implementation

Before any advice integration code:
- confirm policy_router_preview_validation_v1 remains valid after new data
- run latest active_regime_observation
- run latest policy_router_preview
- ensure route candidate rows exist only when H1 context active
- define exact output fields
- decide whether integration writes to paper_advice_observation or a separate preview table
- prefer separate preview table if semantics are not final

## Recommended implementation path

Step 1:
advice_policy_router_integration_design_v1

Step 2:
advice_policy_router_integration_preview_v1 as separate preview table, not modifying canonical paper_advice_observation yet

Step 3:
validate advice-route preview outcomes

Step 4:
only after validation, consider integration into paper_advice_policy_v1

Step 5:
decision_gate remains unchanged

Step 6:
execution remains unchanged

## Non-goals

- no buy/sell
- no account permission
- no execution plan
- no order placement
- no selection score changes
- no policy_router changes
- no live/paper mode
- no broker interaction
