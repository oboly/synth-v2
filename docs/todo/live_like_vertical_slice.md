## Live-Like Vertical Slice

Status:

- phase 1 contracts/docs defined
- first instance: `near_intraday_retest_reclaim_v1`
- mode: `shadow`

This lane is the first narrow bridge from market-only strategy candidates to account-aware preview layers and read-only shadow output.

## Immediate Next Steps

- add a market-only candidate emitter for `INTRADAY_RETEST_RECLAIM_V1`
- keep candidate generation account-agnostic
- add a decision preview adapter that evaluates account-aware permission without broker writes
- add an execution-plan preview adapter that produces intent only
- add a shadow event log and simple dashboard/report output

## Non-Negotiable Boundaries

- no broker writes
- no order submission
- no live executor path
- no decision gate bypass
- no execution planner bypass
- no strategy-side account sizing
- no symbol-specific NEAR logic beyond config values

## Expansion Path

After NEAR shadow mode is stable:

- add `HYPE` via config only
- add `RENDER` via config only
- keep strategy family generic
- do not fork architecture by symbol

## Open Design Questions

- what exact market-only inputs define reclaim validity on `1h`
- what exact retest-depth thresholds define shallow, normal, and deep on `15m`
- what freshness rules should convert a candidate into `STALE`
- what minimum candidate fields are required for a useful decision preview
- what minimal shadow dashboard is enough before any paper-mode discussion

## Explicitly Later

- paper permission
- live permission
- strategy promotion
- broker connectivity
- executor enablement
- `MACRO_DIP_BUDGET_MODE_V1`

Those remain blocked until the shadow path is clear, replayable, and safe.

## Later Research Note — `MACRO_DIP_BUDGET_MODE_V1`

This vertical slice stays narrow and shadow-only.

`MACRO_DIP_BUDGET_MODE_V1` is a separate future portfolio/research lane, not part of the current live-like shadow chain.

Future concept:

- keep roughly `2/3` survivor exposure
- reserve roughly `1/3` as staged dip budget
- deploy dip budget only into strongest survivor/reclaim candidates after a liquidity shock
- use staged tranches:
  - early dip / first reclaim
  - deeper real dip
  - panic/liquidation dip
  - reclaim reserve after higher low

Discipline:

- `flush -> reclaim -> retest holds`
- do not buy first freefall
- do not wait only for perfect bottom
- do not chase vertical extension

Boundary for this vertical slice:

- no runtime behavior change
- no `selection_engine` change
- no `decision_gate` change
- no `execution_planner` runtime change
- no executor path

If revisited later, macro shock scenario remains dashboard/context/research input only until there is a separate reviewed task for strategy measurement, account permissioning, and passive execution planning.
