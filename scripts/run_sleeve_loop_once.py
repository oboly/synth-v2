"""
SYNTH v2
Script: run_sleeve_loop_once
Purpose:
    Manual one-shot sleeve pipeline runner using real DB selection_state rows.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

from src.synth_sleeves.db_repository import SleeveRepository
from src.synth_sleeves.pipeline import run_sleeve_pipeline_once
from src.synth_sleeves.selection_adapter import SelectionStateAdapter


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
    conn_params = make_conn_params()
    repo = SleeveRepository(conn_params)
    adapter = SelectionStateAdapter(conn_params)

    selection_rows = adapter.load_agent_signal_rows()
    if not selection_rows:
        raise RuntimeError("No selection rows loaded from selection_state.")

    summary = run_sleeve_pipeline_once(
        selection_rows=selection_rows,
        paper_cash_eur=Decimal("10000"),
        config_path="configs/portfolio_sleeves.yaml",
        repository=repo,
        min_trade_fraction=Decimal("0.0050"),
        snapshot_every_loop=True,
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
