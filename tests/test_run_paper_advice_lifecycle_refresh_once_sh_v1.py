from __future__ import annotations

import subprocess
from pathlib import Path


SCRIPT_PATH = Path("scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh")


def test_retired_wrapper_has_no_public_market_writer_invocation() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "run_candles_etl" not in source
    assert "run_market_price_snapshot_v1" not in source
    assert "run_chain_4h.sh" not in source
    assert "run_native_short_scope_status_chain" not in source
    assert "ODROID_CANDLE_ETL_OWNERSHIP_RETIRED" in source


def test_retired_wrapper_fails_closed_without_invoking_a_writer() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "database_writes=0" in combined
    assert "writer_invocations=0" in combined
