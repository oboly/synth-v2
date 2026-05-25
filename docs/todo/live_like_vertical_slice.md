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

Those remain blocked until the shadow path is clear, replayable, and safe.
