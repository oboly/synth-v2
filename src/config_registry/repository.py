from __future__ import annotations

"""
ENGINE: config_registry_repository
MODE: latest-only

INPUT:
- synth_bt.config_set
- synth_bt.config_param

OUTPUT:
- in-memory config rows

CLI:
- imported only

HISTORICAL:
- not applicable

NOTES:
- DB-backed configuration registry
- reads from synth_bt
- reads only active config sets by default
"""

from dataclasses import dataclass

from src.common.db import get_connection
from src.config_registry.models import ConfigParamRow, ConfigSetRow


CONFIG_DB_NAME = "synth_bt"


@dataclass
class ConfigRegistryRepository:
    def fetch_config_set(
        self,
        *,
        scope: str,
        config_name: str,
        require_active: bool = True,
    ) -> ConfigSetRow | None:
        clauses = [
            "scope = %s",
            "config_name = %s",
        ]
        params: list[object] = [scope, config_name]

        if require_active:
            clauses.append("is_active = 1")

        sql = f"""
        SELECT
            config_set_id,
            config_name,
            scope,
            is_active,
            description,
            created_ts_utc,
            updated_ts_utc
        FROM config_set
        WHERE {" AND ".join(clauses)}
        LIMIT 1
        """

        conn = get_connection(database=CONFIG_DB_NAME)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            return None

        return ConfigSetRow(
            config_set_id=int(row["config_set_id"]),
            config_name=str(row["config_name"]),
            scope=str(row["scope"]),
            is_active=bool(row["is_active"]),
            description=None if row["description"] is None else str(row["description"]),
            created_ts_utc=row["created_ts_utc"],
            updated_ts_utc=row["updated_ts_utc"],
        )

    def fetch_config_params(
        self,
        *,
        config_set_id: int,
    ) -> list[ConfigParamRow]:
        sql = """
        SELECT
            config_param_id,
            config_set_id,
            component,
            parameter_name,
            value_text,
            value_type,
            created_ts_utc,
            updated_ts_utc
        FROM config_param
        WHERE config_set_id = %s
        ORDER BY component, parameter_name
        """

        conn = get_connection(database=CONFIG_DB_NAME)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [config_set_id])
                rows = cur.fetchall() or []
        finally:
            conn.close()

        out: list[ConfigParamRow] = []
        for row in rows:
            out.append(
                ConfigParamRow(
                    config_param_id=int(row["config_param_id"]),
                    config_set_id=int(row["config_set_id"]),
                    component=str(row["component"]),
                    parameter_name=str(row["parameter_name"]),
                    value_text=str(row["value_text"]),
                    value_type=str(row["value_type"]),
                    created_ts_utc=row["created_ts_utc"],
                    updated_ts_utc=row["updated_ts_utc"],
                )
            )
        return out
