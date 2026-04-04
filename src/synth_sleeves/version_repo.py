"""
SYNTH v2
Module: synth_sleeves.version_repo
Purpose:
    Auto-upsert active strategy versions from config payloads.
Boundary:
    - DB only
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from src.synth_sleeves.strategy_versioning import (
    make_strategy_version_hash,
    make_strategy_version_label,
)


class StrategyVersionRepository:
    def __init__(self, connection_params: dict[str, Any]) -> None:
        self._connection_params = connection_params

    def _connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            cursorclass=DictCursor,
            autocommit=False,
            charset="utf8mb4",
            **self._connection_params,
        )

    def upsert_active_version(
        self,
        *,
        strategy_name: str,
        sleeve_code: str,
        config_payload: dict[str, Any],
        notes: str | None = None,
    ) -> int:
        version_hash = make_strategy_version_hash(strategy_name, config_payload)
        version_label = make_strategy_version_label(strategy_name, version_hash)
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        select_sql = """
        SELECT strategy_version_id
        FROM strategy_version
        WHERE strategy_name = %s
          AND version_hash = %s
        LIMIT 1
        """

        insert_sql = """
        INSERT INTO strategy_version (
            strategy_name,
            sleeve_code,
            version_label,
            version_hash,
            config_json,
            notes,
            activated_ts_utc
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s
        )
        """

        import json
        config_json = json.dumps(config_payload, sort_keys=True, separators=(",", ":"))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(select_sql, (strategy_name, version_hash))
                row = cur.fetchone()
                if row:
                    conn.commit()
                    return int(row["strategy_version_id"])

                cur.execute(
                    insert_sql,
                    (
                        strategy_name,
                        sleeve_code,
                        version_label,
                        version_hash,
                        config_json,
                        notes,
                        now_utc,
                    ),
                )
                strategy_version_id = int(cur.lastrowid)
            conn.commit()
            return strategy_version_id

    def build_lookup_from_sleeve_config(
        self,
        *,
        sleeve_config_raw: dict[str, Any],
    ) -> dict[str, int]:
        lookup: dict[str, int] = {}

        sleeves = sleeve_config_raw.get("sleeves", {})
        for sleeve_code, sleeve_cfg in sleeves.items():
            for strategy_name in sleeve_cfg.get("agent_names", []):
                strategy_payload = {
                    "sleeve_code": sleeve_code,
                    "wallet_share": sleeve_cfg.get("wallet_share"),
                    "max_positions": sleeve_cfg.get("max_positions"),
                    "per_position_cap": sleeve_cfg.get("per_position_cap"),
                    "allowed_actions": sleeve_cfg.get("allowed_actions"),
                    "prepare": sleeve_cfg.get("prepare"),
                }
                lookup[strategy_name] = self.upsert_active_version(
                    strategy_name=strategy_name,
                    sleeve_code=sleeve_code,
                    config_payload=strategy_payload,
                    notes="Auto-upsert from portfolio_sleeves.yaml",
                )

        return lookup
