from __future__ import annotations

from src.common.db_env_v1 import load_database_environment


load_database_environment()


from src.common.db_core_v1 import get_connection  # noqa: E402
from src.executor.executor_v1 import execute_plan_paper  # noqa: E402
from src.executor.repository import ExecutorRepository  # noqa: E402


def run() -> None:
    repo = ExecutorRepository(connection_factory=get_connection)
    plans = repo.fetch_open_plans(limit=50)
    if not plans:
        print("[EXECUTION] No canonical PAPER plans found.")
        return

    print(f"[EXECUTION] Found {len(plans)} canonical PAPER plans")
    for plan in plans:
        execute_plan_paper(plan, repo)
    print("[EXECUTION] Done.")


if __name__ == "__main__":
    run()
