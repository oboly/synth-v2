from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.common.db import get_db_connection


@dataclass(frozen=True)
class RuntimeComponent:
    component_layer: str
    component_name: str
    component_version: str
    component_mode: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool = True


@dataclass(frozen=True)
class RuntimeSnapshot:
    snapshot_ts_utc: datetime
    git_commit: str
    runtime_scope: str
    venue: str
    interval_code: str
    chain_name: str
    live_trading_enabled: bool
    decision_gate_enabled: bool
    execution_enabled: bool
    notes: str | None
    components: list[RuntimeComponent]


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def db_ts(value: datetime) -> datetime:
    return normalize_utc(value).replace(tzinfo=None)


def resolve_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def stable_json(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def config_hash(config_json: str | None) -> str | None:
    if config_json is None:
        return None

    return hashlib.sha256(config_json.encode("utf-8")).hexdigest()


def default_market_chain_components(*, interval_code: str) -> list[RuntimeComponent]:
    base_config = {"interval_code": interval_code, "venue": "bitvavo"}

    return [
        RuntimeComponent(
            component_layer="observation",
            component_name="bitvavo_candles_etl",
            component_version="v1",
            component_mode="bounded_window",
            config=base_config,
        ),
        RuntimeComponent(
            component_layer="feature",
            component_name="feat_candle",
            component_version="v1",
            component_mode="bounded_window_with_warmup",
            config={"interval_code": interval_code, "warmup_bars": 300},
        ),
        RuntimeComponent(
            component_layer="signal",
            component_name="signal_state_etl",
            component_version="v1",
            component_mode="latest_snapshot",
            config=base_config,
        ),
        RuntimeComponent(
            component_layer="advice",
            component_name="advice_engine",
            component_version="1.1",
            component_mode="latest_snapshot",
            config=base_config,
        ),
        RuntimeComponent(
            component_layer="ranking",
            component_name="ranking_engine",
            component_version="v2",
            component_mode="latest_snapshot",
            config=base_config,
        ),
        RuntimeComponent(
            component_layer="measurement",
            component_name="asset_interval_quality_snapshot",
            component_version="1.0",
            component_mode="write_db",
            config=base_config,
        ),
        RuntimeComponent(
            component_layer="selection",
            component_name="selection_engine_v2",
            component_version="2.0",
            component_mode="market_only",
            config=base_config,
        ),
        RuntimeComponent(
            component_layer="filter",
            component_name="trade_setup_filter_v1",
            component_version="1.1",
            component_mode="candidate_weak_set",
            config={
                "interval_code": interval_code,
                "venue": "bitvavo",
                "asset_suitability_mode": "candidate_weak_set",
                "limit": 40,
            },
        ),
    ]


def build_market_chain_snapshot(
    *,
    interval_code: str,
    chain_name: str,
    runtime_scope: str = "market_chain",
    venue: str = "bitvavo",
    notes: str | None = None,
) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        snapshot_ts_utc=utc_now(),
        git_commit=resolve_git_commit(),
        runtime_scope=runtime_scope,
        venue=venue,
        interval_code=interval_code,
        chain_name=chain_name,
        live_trading_enabled=False,
        decision_gate_enabled=False,
        execution_enabled=False,
        notes=notes,
        components=default_market_chain_components(interval_code=interval_code),
    )


def insert_runtime_snapshot(conn, snapshot: RuntimeSnapshot) -> int:
    snapshot_sql = """
    INSERT INTO strategy_runtime_snapshot (
        snapshot_ts_utc,
        git_commit,
        runtime_scope,
        venue,
        interval_code,
        chain_name,
        live_trading_enabled,
        decision_gate_enabled,
        execution_enabled,
        notes
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """

    component_sql = """
    INSERT INTO strategy_runtime_component (
        strategy_runtime_snapshot_id,
        component_layer,
        component_name,
        component_version,
        component_mode,
        config_hash,
        config_json,
        enabled
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        component_mode = VALUES(component_mode),
        config_hash = VALUES(config_hash),
        config_json = VALUES(config_json),
        enabled = VALUES(enabled)
    """

    with conn.cursor() as cur:
        cur.execute(
            snapshot_sql,
            (
                db_ts(snapshot.snapshot_ts_utc),
                snapshot.git_commit,
                snapshot.runtime_scope,
                snapshot.venue,
                snapshot.interval_code,
                snapshot.chain_name,
                1 if snapshot.live_trading_enabled else 0,
                1 if snapshot.decision_gate_enabled else 0,
                1 if snapshot.execution_enabled else 0,
                snapshot.notes,
            ),
        )

        snapshot_id = int(cur.lastrowid)

        component_rows = []
        for component in snapshot.components:
            config_json = stable_json(component.config)
            component_rows.append(
                (
                    snapshot_id,
                    component.component_layer,
                    component.component_name,
                    component.component_version,
                    component.component_mode,
                    config_hash(config_json),
                    config_json,
                    1 if component.enabled else 0,
                )
            )

        cur.executemany(component_sql, component_rows)

    conn.commit()
    return snapshot_id


def write_market_chain_snapshot(
    *,
    interval_code: str,
    chain_name: str,
    runtime_scope: str = "market_chain",
    venue: str = "bitvavo",
    notes: str | None = None,
) -> int:
    snapshot = build_market_chain_snapshot(
        interval_code=interval_code,
        chain_name=chain_name,
        runtime_scope=runtime_scope,
        venue=venue,
        notes=notes,
    )

    conn = get_db_connection()
    try:
        return insert_runtime_snapshot(conn, snapshot)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
