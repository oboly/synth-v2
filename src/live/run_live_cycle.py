"""
run_live_cycle (retired)

This module previously drove a single monolithic "live cycle" that mixed two
responsibilities that Synth's architecture keeps strictly separate:

- it invoked public market-data writers (candle ETL) to fetch and persist
  public market observations, and
- it invoked account/execution layers (decision, risk, portfolio, execution
  intent) in the same process.

That coupling is an architecture violation. Account/live execution must consume
already-persisted public market state; it must never own, fetch, or repair
public-market data, and it must never sit on the same runtime path as a public
market-data writer.

Public-market writer ownership belongs to the registered writer capabilities in
``deploy/ownership/writer_capability_ownership_v1.json`` and is governed by the
shared authorization library
``src.operations.writer_capability_authorization_v1``. The registered
market-only chain wrappers own the market-only pipeline. Account-aware
permission belongs to ``decision_gate``; execution intent to
``execution_planner``; order handling to ``executor``.

This entrypoint is retired and fails closed. It does not import, reference, or
invoke any public market-data writer or any account/execution layer.

host_mutations=0 database_writes=0 writer_invocations=0 systemctl_mutations=0
broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
"""
from __future__ import annotations

import sys


RETIREMENT_NOTICE = (
    "run_live_cycle is retired. It previously coupled public market-data "
    "writing with account/execution layers, which violates the Synth layer "
    "model. Use the registered market-only chains for public-market pipeline "
    "runs and the decision_gate / execution_planner / executor layers for "
    "account-aware permission, execution intent, and order handling."
)


def main() -> int:
    print(f"RETIRED runner=run_live_cycle reason=architecture_boundary_violation_removed")
    print(RETIREMENT_NOTICE)
    print(
        "host_mutations=0 database_writes=0 writer_invocations=0 "
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "decision_gate=none execution_planner=none executor=none"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
