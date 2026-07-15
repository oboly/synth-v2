# TODO — Cross-Asset Metals, Miners and Food Rotation V1

## Status

```text
open P3 research / manual execution first
non-blocking for Synth v2.23 P1/P2 lanes
no broker account or API integration required for the research start
```

## Goal

Extend Synth's market-rotation research beyond crypto with a deliberately small
cross-asset universe covering only:

```text
METALS
MINERS
FOOD / AGRICULTURE
```

The first version must answer:

```text
Is relative participation rotating from crypto or broad risk assets into metals,
mining exposure, or food/agriculture exposure?
```

It must not answer:

```text
What should the account buy, size, or execute now?
```

## Accepted product direction

Initial operating model:

```text
public market-data source
-> canonical cross-asset candles and instrument metadata
-> market-only rotation research
-> read-only dashboard
-> user trades manually at the chosen broker
```

A broker account is not required to start research. Market-data ownership and
broker/execution ownership must remain separate.

Preferred long-term venue direction:

```text
Interactive Brokers
```

Reason: it supports a broad securities universe and has an official API path that
can be evaluated later without replacing the research model.

Initial execution remains manual. No IBKR account, authenticated API, account
snapshot, order API, or execution adapter is part of V1.

## Initial market boundary

### Included

Metals exposure:

```text
gold
silver
copper
platinum only when a liquid, understandable product is selected
```

Mining exposure:

```text
gold miners
silver miners
copper miners
diversified miners
optional critical-minerals basket after product review
```

Food/agriculture exposure:

```text
broad agriculture
wheat
corn
soy
coffee
cocoa
sugar
food producers only when explicitly separated from raw-commodity exposure
```

### Product types allowed for initial manual use

```text
UCITS ETF
ETC / ETP
listed unleveraged equity
listed unleveraged fund
```

### Explicitly excluded from V1

```text
futures
options
CFDs
leveraged or inverse products
short selling
margin
contract rollover
expiry management
automated broker execution
```

This exclusion is architectural, not cosmetic. Futures would introduce contract
selection, expiry, rollover, margin, multipliers, overnight risk, and term-structure
ownership that the current lane does not own.

## Broker decision record

### Interactive Brokers

Planning conclusion:

```text
preferred future broker
manual trading is acceptable initially
official authenticated API can be evaluated later
public candles may remain independent from IBKR
```

Expected advantages:

- broad metals, miners, agriculture, and food-security instrument coverage;
- manual execution can begin without adding a Synth broker adapter;
- future API migration can preserve the same neutral instrument and research
  contracts;
- no reason to purchase live IBKR market data while a separately accepted public
  source supplies research candles.

Constraints:

- IBKR market-data/API use requires an approved authenticated account;
- official API connectivity and session lifecycle must be treated as a separate
  integration lane;
- current commissions, market-data entitlements, account minimums, and Dutch
  account terms must be reverified against official pricing before account opening;
- an IBKR-specific identifier such as `conId` is venue metadata, not the global
  Synth instrument identity.

### Trade Republic

Planning conclusion:

```text
acceptable low-friction manual-only fallback
not a Synth execution venue
public candles must come from another source
```

The July 2026 discussion used a working estimate of approximately EUR 1 per manual
transaction, or EUR 2 for a buy/sell round trip before spread and product costs.
This is not a canonical cost assumption. The current Dutch price list must be
verified before opening or funding because fee and order-routing arrangements can
change.

Trade Republic remains unsuitable for automated Synth integration unless it later
publishes and supports an official trading API with stable account, order, and
reconciliation contracts. Reverse-engineered private interfaces are forbidden.

### Kraken

Planning conclusion:

```text
optional PAXG / crypto-native gold access
not the primary venue for this cross-asset lane
```

Kraken has an official API and can provide tokenized gold exposure through an
eligible product such as PAXG, subject to current Dutch/EEA availability. It does
not solve the miners and food/agriculture requirement, and percentage-based trading
costs can materially reduce active-rotation returns.

Kraken must not be selected as the primary cross-asset venue merely because its API
is easier than a securities broker API.

## Cost and product verification gate

Before selecting or funding any venue, capture a dated comparison from official
sources:

```text
account opening and custody costs
inactivity or platform fees
buy and sell commission
spread and execution venue
FX conversion cost
product TER / ongoing charge
ETC issuer and collateral structure
market-data cost if applicable
withdrawal or transfer cost
Dutch/EEA product availability
```

Do not rank brokers on headline commission alone. The effective rotation cost is:

```text
buy commission
+ sell commission
+ bid/ask spread
+ FX conversion
+ product ongoing cost
+ tracking difference
+ slippage
```

The comparison is an operational decision record, not a hard-coded research input.

## Minimal Synth architecture

### Required separation

```text
public data provider
-> provider adapter
-> canonical instrument mapping
-> canonical candles / observations
-> cross-asset rotation research
-> read-only reporting
```

Manual broker activity remains outside the runtime path:

```text
research output
-> human review
-> manual broker order
```

Forbidden shortcut:

```text
research dashboard
-> broker call
```

### Neutral instrument identity

The research contract must not use a broker ticker or IBKR `conId` as its sole
identity.

Minimum neutral metadata:

```text
instrument_key
canonical_name
asset_class
rotation_group
exposure_type
product_type
issuer
underlying_reference
exchange
listing_currency
price_currency
trading_timezone
provider_symbol
provider_name
broker_symbol optional
ibkr_con_id optional
isin optional
freshness policy
```

`provider_symbol`, `broker_symbol`, `conId`, and ISIN are mappings attached to one
neutral instrument record. This allows the public candle source and future broker
adapter to change independently.

### Existing Rotation Pressure reuse

Reuse concepts, not crypto-specific assumptions:

```text
relative return
relative volume where meaningful
volume acceleration
relative strength
persistence
breadth
concentration
trend state
freshness
```

Do not combine raw crypto and securities observations without normalization for:

```text
trading hours
weekends and holidays
currency
session gaps
volume meaning
missing bars
corporate actions
fund tracking structure
```

Cross-asset ranks must first be normalized within comparable groups:

```text
METALS
MINERS
FOOD_AGRICULTURE
```

A later global rank may compare group-level pressure. It must not treat a 24/7
crypto return and a limited-session ETC return as directly equivalent without an
explicit clock and normalization contract.

## Implementation sequence

### P3-A — Provider and instrument feasibility

Select a public data source only after testing:

- Dutch accessibility and terms of use;
- stable symbol mapping;
- 1d and 4h candle coverage;
- volume availability and meaning;
- split/dividend/corporate-action treatment for equities and funds;
- exchange timezone and session calendars;
- historical depth;
- rate limits and operational reliability;
- redistribution/dashboard permissions;
- absolute timestamps and provenance.

Output:

```text
provider feasibility record
20–30 instrument candidate allowlist
explicit rejected products and reasons
```

No provider is accepted merely because an unofficial Python package can download
its data.

### P3-B — Canonical cross-asset instrument registry

Create a deterministic, neutral registry for the selected allowlist.

Required validation:

- unique global `instrument_key`;
- one explicit rotation group;
- product type and underlying exposure visible;
- listing currency and price currency explicit;
- duplicate listings resolved deliberately;
- leveraged/inverse/futures products rejected;
- product closure or identifier change fails visibly.

### P3-C — Read-only public candle ingest

Initial cadence:

```text
1d required
4h optional when source/session quality is proven
realtime streaming not required
```

The writer owns only public market observations. It must not read broker accounts or
orders.

Required evidence:

- idempotent writes;
- absolute source timestamps;
- exchange-session-aware gap handling;
- stale/missing provider state;
- retry and rate-limit behavior;
- no fabricated weekend candles;
- deterministic source provenance.

### P3-D — Cross-asset rotation research

Build a market-only snapshot with at least:

```text
instrument_key
rotation_group
observed_at_utc
return_1d
return_7d
return_30d optional
relative_strength
volume_state where valid
trend_state
rotation_pressure_state
freshness_state
reason_codes
```

Initial questions:

- Is participation moving from crypto toward metals?
- Are miners confirming or diverging from the underlying metal?
- Is food/agriculture participation broad or isolated to one product?
- Does group-level strength persist after FX and session normalization?
- Does the signal survive transaction-cost assumptions?

### P3-E — Replay and cost sensitivity

Before any promotion or stronger user language, measure:

- forward return by rank and group;
- MFE/MAE;
- persistence and false-rotation rate;
- metals versus miners lead/lag;
- food/agriculture breadth;
- regime dependence;
- impact of spread, commission, FX, TER, and tracking difference;
- weekly versus faster rotation cadence;
- comparison against simple buy-and-hold and equal-weight controls.

Manual trading costs must be applied in replay. A signal that disappears after
realistic round-trip friction is not actionable research.

### P3-F — Read-only dashboard

Only after canonical data and replay evidence exist, add:

```text
group pressure
instrument rank
1d / 7d relative movement
trend and freshness state
product type
listing currency
manual broker availability marker
```

The dashboard may display a manual venue note. It must not imply that Synth owns or
observed the user's broker position.

### P3-G — Manual broker canary

After the user selects a broker and a product:

```text
one venue
one unleveraged product
one small manual position
explicit entry and exit cost record
manual reconciliation against the research snapshot
```

This remains outside Synth execution. Do not fabricate account state or order status
inside reporting.

### P3-H — Optional future IBKR API proposal

Only after the manual/research lane proves value, create a separate proposal for:

```text
IBKR account observations
market-data entitlements if needed
paper environment
session and authentication lifecycle
contract discovery
order reconciliation
decision_gate permissions
execution_planner intents
IBKR executor
```

This future proposal must preserve the existing layer split and cannot reuse the
public-data collector as an execution shortcut.

## Architecture boundary

```text
market-data adapter = public observations only
research             = market-only, account-agnostic
selection_engine     = unchanged until separate validated promotion
decision_gate        = unchanged
execution_planner    = unchanged
executor / agents    = unchanged
broker clients       = absent from V1
```

Safety state:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

## Definition of done

- a public-data provider is selected with documented terms and failure behavior;
- a small neutral instrument allowlist exists for metals, miners, and food/agriculture;
- candles are persisted with timestamps, session semantics, and provenance;
- group-normalized rotation observations are reproducible;
- realistic manual trading friction is included in replay;
- broker choice is documented from a fresh official-price comparison;
- initial execution remains manual and outside Synth;
- no futures, leverage, broker API, account data, decision, planning, or execution
  path is introduced by V1;
- any future IBKR API work requires a separate reviewed lane.
