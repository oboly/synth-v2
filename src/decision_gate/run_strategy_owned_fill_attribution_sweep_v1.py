"""Issue #756 Codex block: operator-facing runner for the decision_gate-owned
strategy-owned fill-attribution sweep (``strategy_owned_fill_attribution_sweep_v1``).

Reads ``executor_execution_leg``/``executor_execution_handoff`` (shared #206
executor substrate) by raw SQL only -- no import of ``src.executor`` (see
that module's docstring for the architecture-guard reasoning) -- and appends
idempotent events to decision_gate's own ``strategy_owned_inventory_ledger_v1``
table. Safe to run repeatedly/on a schedule: a rerun with no new FILLED legs
since the last run is a no-op.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime

from src.common.db import get_db_connection
from src.decision_gate.strategy_owned_fill_attribution_sweep_v1 import (
    StrategyOwnedFillAttributionSweepError,
    run_strategy_owned_fill_attribution_sweep_v1,
)

RUNNER_NAME = "run_strategy_owned_fill_attribution_sweep_v1"


def main() -> int:
    argparse.ArgumentParser(
        description="Attribute canonical FILLED automatic-buy executor legs "
        "into the strategy-owned inventory ledger. No arguments: sweeps every account.",
    ).parse_args()
    started = time.monotonic()
    print(f"STARTED runner={RUNNER_NAME} mode=sweep scope=all_accounts workers=1", flush=True)
    conn = get_db_connection()
    try:
        result = run_strategy_owned_fill_attribution_sweep_v1(conn)
        conn.commit()
    except StrategyOwnedFillAttributionSweepError as exc:
        conn.rollback()
        elapsed = time.monotonic() - started
        print(f"FAILED runner={RUNNER_NAME} reason={exc} elapsed_seconds={elapsed:.3f}", flush=True)
        return 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    elapsed = time.monotonic() - started
    print(
        f"FINISHED runner={RUNNER_NAME} candidates_seen={result.candidates_seen} "
        f"newly_attributed={result.newly_attributed} already_attributed={result.already_attributed} "
        f"elapsed_seconds={elapsed:.3f} finished_ts_utc={datetime.now(UTC).isoformat()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
