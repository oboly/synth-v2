# Paper Advice Manual Trading Cockpit V1

## Purpose

Turn the existing paper-advice dashboard into a practical manual-trading cockpit
for read-only review of:

- entries
- reloads
- trims
- holds
- wait/avoid states

This lane is manual decision support only. It does not enable live execution.

## Scope

The cockpit remains inside the paper-advice / reporting path.

It adds display-only interpretation on top of existing paper-advice rows so a
human can scan:

- current paper action
- strongest why/context
- invalidation or block reason
- target/reaction zone
- trim/reload hint
- freshness
- missing inputs

## Inputs

Current manual-cockpit readout may use these existing read-only sources:

- `paper_advice_observation`
- `market_price_snapshot`
- `execution_zone_context` fields already embedded in paper advice
- market-breath context bridge rows
- intrabar lifecycle context rows
- setup-filter state/reason
- advice/policy/lifecycle display overlays already derived in reporting

It does not invent new strategy signals. If context is unavailable, the
dashboard must show it as missing.

## Manual Labels

Primary display-only action labels:

- `BUY_REVIEW`
- `RELOAD_REVIEW`
- `TRIM_REVIEW`
- `HOLD`
- `WAIT`
- `AVOID`
- `INVALIDATED`

Direction-first display labels:

- `bullish short-term`
- `bullish medium-term`
- `neutral / wait`
- `bearish risk`
- `trim candidate`
- `reload candidate`

These are read-only dashboard semantics. They do not change paper-advice policy
state and they are not order permission.

## Interpretation

Use the cockpit as:

```text
market/setup/context review -> manual human decision outside Synth execution
```

Not:

```text
dashboard label -> automatic order
```

Practical interpretation:

- `BUY_REVIEW`: current market/setup map is constructive enough for manual buy review
- `RELOAD_REVIEW`: constructive retest/reaction context for manual reload review
- `TRIM_REVIEW`: mapped target/extension context favors trim/harvest review
- `HOLD`: no stronger manual action is surfaced from current inputs
- `WAIT`: context is neutral, incomplete, or not actionable yet
- `AVOID`: current context blocks new exposure review
- `INVALIDATED`: current map is stale/invalidated and needs upstream recompute

## Strongest Reasons

The cockpit should prefer these reasons when available:

- fib/zone context
- reclaim/retest context
- market-breath / regime context
- setup-fail reason
- lifecycle or recompute context
- target/extension context

If any of these are missing, the dashboard should say so explicitly rather than
pretending the missing input is neutral.

## Boundaries

Architecture remains unchanged:

- `selection_engine` stays market-only and account-agnostic
- paper advice remains read-only review context
- no `decision_gate` bypass
- no `execution_planner` changes
- no `executor` changes
- no broker writes
- no order submission
- no live trading

Required safety markers stay visible:

```text
broker_writes=0
order_submission=0
executor=none
live_trading=false
paper/manual only
```

## Non-Goals

- no live executor work
- no fake fill engine
- no account-aware position sizing inside paper advice
- no new selection logic
- no direct use of heartbeat as an entry edge

Heartbeat remains a readout/stability aid, not a proven standalone
`ENTRY_CANDIDATE` edge.
