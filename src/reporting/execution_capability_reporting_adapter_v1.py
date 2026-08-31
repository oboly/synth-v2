"""Read-only reporting adapter for canonical instrument execution capability.

Issue #642. This module bridges ``asset.execution_mode`` into reporting-only
per-symbol overlays. It performs no broker calls and no DB writes.
"""
from __future__ import annotations

from typing import Any

from src.execution_capability.execution_capability_v1 import normalize_execution_mode


def fetch_execution_mode_by_symbol(
    conn: Any,
    *,
    symbols: list[str] | tuple[str, ...] | set[str],
) -> dict[str, str]:
    normalized_symbols = sorted({str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()})
    if not normalized_symbols:
        return {}

    placeholders = ",".join(["%s"] * len(normalized_symbols))
    sql = f"""
    SELECT symbol, execution_mode
    FROM asset
    WHERE symbol IN ({placeholders})
    """
    with conn.cursor() as cur:
        cur.execute(sql, normalized_symbols)
        rows = list(cur.fetchall())

    out: dict[str, str] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        out[symbol] = normalize_execution_mode(row.get("execution_mode"))
    return out
