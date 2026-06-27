# Manual Execution Tray + Ladder Profiles v1

## Status

Priority P0 implementation bundle.

This is the first controlled bridge from the current Short Swing UI to buy/sell execution.

The user explicitly selects candidate buy/sell actions and a final trade amount. The system validates, plans, and submits those choices only through the normal account-aware execution chain.

## Scope

Build a user-mediated execution lane:

```text
Short Swing / card UI
→ execution tray
→ user review and explicit Process action
→ decision_gate
→ execution_planner
→ executor
→ exchange reconciliation
```

The UI must never write orders directly to the exchange.

The user may:

* select a BUY or SELL action for one or more assets;
* select a ladder profile;
* accept a configured suggested trade amount or enter a manual quote amount;
* review the resolved legs before submission;
* explicitly press Process.

The system must:

* create an immutable manual execution request;
* run the account-aware decision gate at process time;
* create an immutable execution plan snapshot;
* submit only approved executable legs;
* reconcile resulting exchange orders;
* show accepted, rejected, blocked, submitted, and reconciled states.

## Non-Goals

Do not add:

* autonomous buy or sell execution;
* user-authored free-text formulas;
* any order path that bypasses `decision_gate`, `execution_planner`, or executor;
* changes to `selection_engine` market logic;
* changes to Breathline or FibNavigationMap calculation;
* broker writes directly from UI handlers;
* automatic amendment or cancellation of existing orders when a profile changes.

## Architecture Boundaries

### `selection_engine`

Market-only and account-agnostic.

It may expose PPP, map context, targets, Breathline state, and candidate context. It must not know user trade sizes, account balances, profile rules, ladder legs, or account permissions.

### `decision_gate`

Account-aware permission layer.

It validates the manual execution request at process time, including account state, live/paper mode, user permission, free funds/quantity, open-order conflicts, caps, exchange constraints, and kill-switch state.

### `execution_planner`

Execution intent only.

It resolves the selected ladder profile and final trade amount into immutable order intents. It computes prices, quantities, rounding, minimum-order compliance, and reserves. It must not submit orders.

### Executor / agents

Order handling only.

They submit the planner's approved intents, capture exchange identifiers, and reconcile exchange state. They do not reinterpret UI values or profile logic.

## Trade Amount Ownership

The final trade amount is a **user-controlled quote-notional amount**.

Examples:

```text
€10 fixed manual amount
2% of free EUR balance, suggested by profile
25% of current coin-position quote value, suggested by profile
```

A ladder splits the final selected quote amount over its legs.

It does not decide the final trade size.

For a €10 selected trade amount and two 50/50 legs:

```text
leg 1 quote notional: €5
leg 2 quote notional: €5
```

For sells, base quantity is calculated per leg:

```text
required_base_quantity = leg_quote_notional / leg_limit_price
```

The planner must verify that total required base quantity is available after reservations and exchange constraints.

For buys, the total selected quote amount plus applicable fees must be available in free quote balance.

## Configuration Model

Use these four tables.

Do not store a separate `number_of_trades` column. The number of ladder orders is the number of active leg rows in the selected profile revision.

### 1. `execution_sizing_variable_ref`

Reference vocabulary for permitted sizing variables. This table documents what a variable means. It does not contain live balances or calculation logic.

Required columns:

| Column | Meaning |
|---|---|
| `variable_key` | stable machine key, primary key |
| `display_label` | compact user-facing label |
| `description` | explicit meaning and resolution semantics |
| `value_unit` | `QUOTE_AMOUNT`, `BASE_QUANTITY`, or `PERCENT` where applicable |
| `allowed_side` | `BUY`, `SELL`, or `BOTH` |
| `is_active` | whether new rules may reference this variable |
| `display_order` | deterministic UI order |
| `created_at` | audit timestamp |
| `retired_at` | optional lifecycle timestamp |

Seed exactly these variables for v1:

| `variable_key` | `display_label` | `description` | Unit | Side |
|---|---|---|---|---|
| `MANUAL_QUOTE_AMOUNT` | Manual trade amount | Quote amount explicitly entered or confirmed by the user for this request. It is the final requested trade amount unless a hard safety gate blocks or rejects it. | `QUOTE_AMOUNT` | `BOTH` |
| `FIXED_QUOTE_AMOUNT` | Fixed trade amount | Fixed configured quote amount supplied by a sizing rule as a suggested default. The user may override it before processing. | `QUOTE_AMOUNT` | `BOTH` |
| `FREE_QUOTE_BALANCE` | Free quote balance | Quote-currency balance available for new buy orders after open-order reservations and exchange-available-balance rules. | `QUOTE_AMOUNT` | `BUY` |
| `TOTAL_WALLET_QUOTE_VALUE` | Total wallet value | Total account wallet value resolved in the account quote currency using the defined valuation source and timestamp. This is a suggestion input, not a spendable-balance guarantee. | `QUOTE_AMOUNT` | `BOTH` |
| `COIN_POSITION_QUOTE_VALUE` | Coin position value | Current quote-currency value of the selected asset position, using free plus reserved base quantity where defined by the valuation policy. This is a sell-sizing suggestion input, not a free-quantity guarantee. | `QUOTE_AMOUNT` | `SELL` |
| `FREE_BASE_QUANTITY` | Free asset quantity | Base-asset quantity available for new sell orders after active sell reservations and exchange-available-balance rules. This is a hard sell-cap constraint, not a quote sizing amount. | `BASE_QUANTITY` | `SELL` |

The resolver must be code-owned and whitelist only these keys. Database content must never define evaluation behavior.

### 2. `execution_sizing_rule`

A deterministic default quote-sizing rule.

Required columns:

| Column | Meaning |
|---|---|
| `sizing_rule_id` | primary key |
| `account_id` | account scope; nullable only for a system template if that existing schema supports it |
| `rule_code` | stable unique code within account scope |
| `display_label` | user-facing name |
| `description` | explicit user-facing rule meaning |
| `rule_type` | enum-like constrained value |
| `source_variable_key` | nullable FK to `execution_sizing_variable_ref` |
| `multiplier_bps` | deterministic percent multiplier where applicable |
| `fixed_quote_amount` | fixed configured suggestion where applicable |
| `floor_quote_amount` | optional minimum suggested amount |
| `cap_quote_amount` | optional maximum suggested amount |
| `is_enabled` | whether selectable for new requests |
| `version` | immutable config version |
| `created_at` | audit timestamp |
| `retired_at` | optional lifecycle timestamp |

Supported `rule_type` values in v1 only:

```text
MANUAL_ONLY
FIXED_QUOTE
PCT_OF_VARIABLE
```

Resolution rules:

```text
MANUAL_ONLY:
    no derived suggestion required; user must choose a quote amount

FIXED_QUOTE:
    suggested_amount = fixed_quote_amount

PCT_OF_VARIABLE:
    suggested_amount = source_variable_value × multiplier_bps / 10_000
```

Apply optional floor/cap after the primary calculation:

```text
suggested_amount = max(floor_quote_amount, suggested_amount) when floor is present
suggested_amount = min(cap_quote_amount, suggested_amount) when cap is present
```

No free-text formulas. Do not add parser/eval behavior.

### 3. `execution_ladder_profile`

Versioned account/user-selectable profile identity.

Required columns:

| Column | Meaning |
|---|---|
| `ladder_profile_id` | primary key |
| `account_id` | owning account scope |
| `profile_code` | stable unique code within account scope |
| `display_label` | user-facing profile label |
| `description` | explicit intended use |
| `side` | `BUY` or `SELL` |
| `anchor_type` | constrained anchor source |
| `default_sizing_rule_id` | nullable FK to `execution_sizing_rule` |
| `is_enabled` | whether selectable for new requests |
| `current_version` | active immutable profile revision |
| `created_at` | audit timestamp |
| `retired_at` | optional lifecycle timestamp |

Supported `anchor_type` values in v1:

```text
NATIVE_SHORT_ANCHOR_HIGH
```

`NATIVE_SHORT_ANCHOR_HIGH` resolves to `NativeShortContextRow.anchor_high_price` (swing high / breakout gate
price from the active native short map cycle). Its backing DB column is
`native_short_map_v1.anchor_high_price DECIMAL(30,12)`.

**PPP (Profit Plan Potential Pct) is a calculated percentage, not a price.**
Do not use `PPP_PRICE` or `ProfitPlanCard.active_target` as a ladder anchor.
`active_target` is the first unhit fib extension level (ext_1_272 / ext_1_618), which is above
the buy zone and is not appropriate for recovery exits below the plan entry reference.
The anchor resolver is blocked when `context_status != NATIVE_SHORT_CONTEXT_AVAILABLE` or when
`anchor_high_price` is null.

Do not add `ENTRY_PRICE`, `PPP_PRICE`, `ACTIVE_SELL_TARGET_PRICE`, manual anchors, or other
anchor sources until a separate requirement exists.

### 4. `execution_ladder_leg`

Versioned ladder legs. Active leg count defines order count.

Required columns:

| Column | Meaning |
|---|---|
| `ladder_leg_id` | primary key |
| `ladder_profile_id` | FK to profile |
| `profile_version` | immutable profile revision the leg belongs to |
| `leg_number` | deterministic ascending leg sequence |
| `price_offset_bps` | signed offset from anchor, in basis points |
| `allocation_bps` | quote-notional share of final trade amount |
| `order_type` | constrained to `LIMIT` in v1 |
| `time_in_force` | exchange-supported explicit value |
| `is_enabled` | whether leg is active in that profile version |
| `created_at` | audit timestamp |

Required constraints:

* unique `(ladder_profile_id, profile_version, leg_number)`;
* `leg_number > 0`;
* `allocation_bps > 0`;
* active legs for a profile version must sum to exactly `10_000` bps;
* profile version with no active legs is invalid for selection;
* `order_type = LIMIT` in v1;
* no mutation of active historical profile revisions; create a new version instead.

## Initial Seed Configuration

Create exactly one default profile for each account that is eligible for manual execution, subject to existing account-status controls.

### Default profile

```text
profile_code: SELL_PPP_RECOVERY_V1
display_label: Sell PPP recovery ladder
description: Split a user-selected sell trade amount into two equal limit sells below the Native Short anchor high price. Intended for user-confirmed recovery exits only.
side: SELL
anchor_type: NATIVE_SHORT_ANCHOR_HIGH
default sizing rule: MANUAL_ONLY
version: 1
```

### Default ladder legs

```text
leg 1
price_offset_bps: -600
allocation_bps: 5000
order_type: LIMIT

leg 2
price_offset_bps: -200
allocation_bps: 5000
order_type: LIMIT
```

For a user-selected trade amount of €10 and Native Short anchor high price of €1.00 (`NativeShortContextRow.anchor_high_price`):

```text
leg 1: €5.00 limit sell at €0.94
leg 2: €5.00 limit sell at €0.98
```

The planner must derive base quantity per leg from its own resolved limit price. Do not allocate base quantity 50/50 unless a later profile explicitly uses a base-quantity sizing basis.

## Manual Execution Request Contract

Create a persistent request before planning.

Suggested required fields:

| Field | Meaning |
|---|---|
| `manual_execution_request_id` | primary key |
| `account_id` | target account |
| `requested_by_user_id` | authenticated user identity |
| `asset_id` / symbol fields | selected market instrument |
| `side` | `BUY` or `SELL` |
| `ladder_profile_id` | selected profile |
| `ladder_profile_version` | resolved immutable selected version |
| `sizing_rule_id` | selected/default sizing rule, nullable for pure manual entry |
| `suggested_quote_amount` | derived suggestion, nullable |
| `requested_quote_amount` | final user-confirmed amount |
| `trade_amount_source` | `MANUAL_OVERRIDE`, `PROFILE_DEFAULT`, or `USER_CONFIRMED_SUGGESTION` |
| `anchor_type` | copied snapshot — `NATIVE_SHORT_ANCHOR_HIGH` for v1 |
| `anchor_price` | resolved `anchor_high_price` snapshot from native short context at request time |
| `source_map_cycle_id` | `NativeShortContextRow.map_cycle_id` — compound string `"{symbol}\|SHORT\|4h\|{start}\|{end}"` |
| `source_native_map_id` | `native_short_map_v1.map_id` if resolvable at request time; NULL otherwise |
| `status` | explicit lifecycle status |
| `created_at` | audit timestamp |
| `processed_at` | processing timestamp |
| `rejection_code` | explicit failure reason when applicable |
| `rejection_detail` | safe user-visible detail when applicable |

Suggested status lifecycle:

```text
DRAFT
READY_FOR_REVIEW
PROCESSING
GATE_BLOCKED
PLANNED
SUBMITTED
PARTIALLY_SUBMITTED
RECONCILED
FAILED
CANCELLED
```

A request must become immutable once processing starts. Any user change creates a replacement request, not a mutation of an in-flight request.

## Plan Snapshot Requirements

When a request passes the gate and reaches the planner, persist a deterministic snapshot per leg:

```text
profile_id
profile_version
leg_number
anchor_type
anchor_price
price_offset_bps
limit_price
allocated_quote_notional
computed_base_quantity
rounded_base_quantity
exchange_minimum_validation
available_balance_snapshot
source_map_cycle_id
source_native_map_id
```

A later configuration edit, anchor map rotation, or UI refresh must never alter the planned or submitted orders.

## Gate Requirements

At Process time, `decision_gate` must re-evaluate:

* account eligibility and execution mode;
* authenticated user permission;
* global/account kill-switch state;
* selected profile still enabled for new requests;
* request-side/profile-side consistency;
* current free quote balance for buys;
* current free base quantity for sells;
* open-order reservations;
* duplicate request/idempotency protection;
* exchange minimum amount and quantity constraints;
* price tick and quantity step rounding;
* marketable-limit guard;
* per-account limits that already exist or are explicitly configured.

### Marketable-limit guard

Do not silently submit a limit order that is immediately executable because the current price has crossed the resolved limit level.

For the initial sell profile, when current executable price makes one or more resolved sell limits marketable, the request must stop for review with an explicit status/reason. It must not convert itself into a market order and must not quietly reprice.

## UI Requirements

### Card action

Cards may expose a non-executing action:

```text
Add SELL ladder
```

The card uses the selected/default profile only to render an estimate. It creates no exchange order.

### Trade amount

Show:

```text
Trade amount
[ €10.00 ]
Sizing profile: Manual amount
```

The trade amount input is the final user-controlled quote-notional amount.

Future sizing rules may populate a suggestion, but the user may override it before request creation.

### Preview

Before adding to tray, show at least:

```text
anchor price (NATIVE_SHORT_ANCHOR_HIGH — NativeShortContextRow.anchor_high_price)
profile label and version
selected trade amount
per-leg quote allocation
per-leg limit price
per-leg estimated base quantity
estimated total base reservation
available free base quantity for sells, or free quote for buys
warnings / blockers
```

### Execution tray

Tray rows must show:

```text
asset / market
side
profile
final trade amount
number of legs
status
warnings
```

The tray action is:

```text
Review & process
```

The final user action is explicit:

```text
Submit N limit orders
```

At this stage, no UI element may claim execution succeeded until executor receipt and reconciliation state are recorded.

## Tests

Minimum tests:

* seed variable reference rows include display label and description;
* only whitelisted sizing variables resolve;
* unsupported rule types are rejected;
* no free-text formula evaluation exists;
* initial profile has exactly two active legs;
* initial legs sum to `10_000` allocation bps;
* €10 request resolves to €5 + €5 quote allocations;
* sell base quantity derives from each leg's own limit price;
* insufficient free base quantity blocks before submission;
* profile edit creates a new version and does not change existing request/plan snapshots;
* manual request cannot bypass `decision_gate`;
* duplicate process action is idempotent;
* marketable sell limits stop for review rather than silently submit;
* UI estimate cannot be mistaken for a submitted order;
* executor receipts and reconciliation are persisted and surfaced.

## Rollout

1. Create schema, seed reference variables, seed one default sell ladder, and add read-only profile/preview API.
2. Add UI selection, manual trade amount, and execution tray in `OBSERVE_ONLY`; persist requests but do not plan/submit.
3. Enable planner and gate with paper execution; reconcile full lifecycle.
4. Enable explicit user-confirmed live processing only after paper reconciliation is reliable.

Do not enable autonomous execution as part of this work.
