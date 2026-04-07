from __future__ import annotations

from src.execution.planner import build_execution_plans, write_execution_plans
from src.execution.worker import process_execution_plans


def main() -> int:
    plans = build_execution_plans()
    plans_written = write_execution_plans(plans)
    worker_summary = process_execution_plans()

    summary = {
        "plans_built": len(plans),
        "plans_written": plans_written,
        **worker_summary,
    }

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
