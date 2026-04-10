from __future__ import annotations

from typing import Any

from src.common.db import db_cursor


def fetch_strategy_param_overrides(
    strategy_name: str,
    symbol: str,
    asset_class: str,
) -> dict[str, str]:
    sql = """
    SELECT
        param_name,
        param_value,
        symbol,
        asset_class
    FROM strategy_param_override
    WHERE strategy_name = %s
      AND is_enabled = 1
      AND (
            symbol = %s
         OR (symbol IS NULL AND asset_class = %s)
         OR (symbol IS NULL AND asset_class IS NULL)
      )
    ORDER BY
        CASE
            WHEN symbol = %s THEN 3
            WHEN symbol IS NULL AND asset_class = %s THEN 2
            WHEN symbol IS NULL AND asset_class IS NULL THEN 1
            ELSE 0
        END DESC,
        strategy_param_override_id DESC
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, (strategy_name, symbol, asset_class, symbol, asset_class))
        rows = cur.fetchall()

    resolved: dict[str, str] = {}
    for row in rows:
        param_name = str(row["param_name"]).strip()
        if param_name not in resolved:
            resolved[param_name] = str(row["param_value"]).strip()

    return resolved


def set_strategy_param_override(
    strategy_name: str,
    param_name: str,
    param_value: str,
    symbol: str | None = None,
    asset_class: str | None = None,
    notes: str | None = None,
    is_enabled: bool = True,
) -> int:
    sql = """
    INSERT INTO strategy_param_override (
        strategy_name,
        symbol,
        asset_class,
        param_name,
        param_value,
        is_enabled,
        notes
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s
    )
    """

    with db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            sql,
            (
                strategy_name,
                symbol,
                asset_class,
                param_name,
                param_value,
                1 if is_enabled else 0,
                notes,
            ),
        )
        return int(cur.lastrowid)


def disable_strategy_param_override(override_id: int) -> int:
    sql = """
    UPDATE strategy_param_override
    SET is_enabled = 0
    WHERE strategy_param_override_id = %s
    """

    with db_cursor(commit=True) as (_conn, cur):
        affected = cur.execute(sql, (override_id,))

    return int(affected)


def list_strategy_param_overrides(
    strategy_name: str | None = None,
) -> list[dict[str, Any]]:
    if strategy_name:
        sql = """
        SELECT *
        FROM strategy_param_override
        WHERE strategy_name = %s
        ORDER BY strategy_name, param_name, symbol, asset_class, strategy_param_override_id DESC
        """
        params = (strategy_name,)
    else:
        sql = """
        SELECT *
        FROM strategy_param_override
        ORDER BY strategy_name, param_name, symbol, asset_class, strategy_param_override_id DESC
        """
        params = ()

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, params)
        return list(cur.fetchall())
