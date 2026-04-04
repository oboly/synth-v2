"""
SYNTH v2
Script: run_momentum_persistence_snapshot
Purpose:
    Compute and write 7d / 14d momentum persistence snapshots.
Usage:
    python -m scripts.run_momentum_persistence_snapshot
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from src.features.momentum_persistence_snapshot import MomentumPersistenceSnapshotService


load_dotenv(".env")


def make_conn_params() -> dict[str, Any]:
    params = {
        "host": os.getenv("DB_HOST"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME"),
    }

    missing = [k for k, v in params.items() if v in (None, "")]
    if missing:
        raise RuntimeError(f"Missing DB config keys: {missing}")

    return params


def main() -> int:
    service = MomentumPersistenceSnapshotService(make_conn_params())
    summary = service.run(lookbacks=[7, 14])
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
