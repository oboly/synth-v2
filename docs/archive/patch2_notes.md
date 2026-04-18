# Patch 2 Notes

## Added
- paper execution applier
- FIFO lot reduction
- close all lots on CLOSE target
- transition logging to `state_transition_daily`
- automatic strategy version upsert from config
- wallet equity calculation from:
  - paper cash
  - open lot market value

## Execution policy
- OPEN => create new lot
- ADD => create new lot
- REDUCE => reduce oldest lots first
- CLOSE => close all open lots in sleeve/asset pair

## Important limitation
`state_transition_daily` is aggregate-only.
It is enough for now, but not a raw event log.

If later you want detailed event history, add:
- `state_transition_log`

## Practical result
You now have:
- target generation
- target persistence
- paper lot execution
- snapshots
- trade closure ledger
- strategy version linkage
- aggregated state transitions
