from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.common.db import get_db_connection


@dataclass(frozen=True)
class RuntimeComponentSpec:
    component_layer: str
    component_name: str
    component_version: str
    component_mode: str | None
    config: dict[str, Any]
    enabled: bool = True


def utc_now_db() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def resolve_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "UNKNOWN"


def stable_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def stable_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def default_market_chain_components(
    *,
    venue: str,
    interval_code: str,
    chain_name: str,
) -> list[RuntimeComponentSpec]:
    common = {
        "venue": venue,
        "interval_code": interval_code,
        "chain_name": chain_name,
        "runtime_scope": "market_chain",
    }

    return [
        RuntimeComponentSpec(
            component_layer="observation",
            component_name="bitvavo_candles_etl",
            component_version="v1",
            component_mode="bounded_window",
            config={
                **common,
                "source": "Bitvavo OHLCV",
                "writes": ["obs_market_candle"],
                "account_aware": False,
            },
        ),
        RuntimeComponentSpec(
            component_layer="feature",
            component_name="feat_candle",
            component_version="v1",
            component_mode="bounded_window_with_warmup",
            config={
                **common,
                "writes": ["feat_candle"],
                "warmup_bars": 300,
                "account_aware": False,
            },
        ),
        RuntimeComponentSpec(
            component_layer="signal",
            component_name="signal_state_etl",
            component_version="v1",
            component_mode="latest_snapshot",
            config={
                **common,
                "writes": ["signal_engine_state"],
                "account_aware": False,
            },
        ),
        RuntimeComponentSpec(
            component_layer="advice",
            component_name="advice_engine",
            component_version="1.1",
            component_mode="latest_snapshot",
            config={
                **common,
                "writes": ["advice_state"],
                "account_aware": False,
            },
        ),
        RuntimeComponentSpec(
            component_layer="ranking",
            component_name="ranking_engine",
            component_version="v2",
            component_mode="latest_snapshot",
            config={
                **common,
                "writes": ["ranking_state"],
                "account_aware": False,
            },
        ),
        RuntimeComponentSpec(
            component_layer="measurement",
            component_name="asset_interval_quality_snapshot",
            component_version="1.0",
            component_mode="write_db",
            config={
                **common,
                "writes": ["asset_interval_quality_snapshot"],
                "account_aware": False,
            },
        ),
        RuntimeComponentSpec(
            component_layer="selection",
            component_name="selection_engine_v2",
            component_version="2.0",
            component_mode="market_only",
            config={
                **common,
                "writes": ["selection_state"],
                "account_aware": False,
                "forbidden": [
                    "account_id",
                    "balance",
                    "position",
                    "open_order",
                    "execution_plan",
                    "execution_event",
                ],
            },
        ),
        RuntimeComponentSpec(
            component_layer="filter",
            component_name="trade_setup_filter_v1",
            component_version="1.1",
            component_mode="candidate_weak_set",
            config={
                **common,
                "writes": ["trade_setup_filter_observation"],
                "target_horizon": "24H",
                "account_aware": False,
            },
        ),
        RuntimeComponentSpec(
            component_layer="policy_preview",
            component_name="trade_setup_filter_policy_preview_v1",
            component_version="0.1",
            component_mode="read_only_write_db",
            config={
                **common,
                "writes": ["trade_setup_policy_preview_observation"],
                "target_horizon": "24H",
                "policy_effect": "observation_only",
                "selection_impact": False,
                "decision_gate_impact": False,
                "execution_impact": False,
                "account_aware": False,
            },
        ),
    ]


def write_strategy_runtime_snapshot(
    *,
    venue: str,
    interval_code: str,
    chain_name: str,
    runtime_scope: str = "market_chain",
    notes: str | None = None,
    live_trading_enabled: bool = False,
    decision_gate_enabled: bool = False,
    execution_enabled: bool = False,
    git_commit: str | None = None,
) -> int:
    git_commit_value = git_commit if git_commit else resolve_git_commit()
    snapshot_ts = utc_now_db()

    components = default_market_chain_components(
        venue=venue,
        interval_code=interval_code,
        chain_name=chain_name,
    )

    conn = get_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
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
                """,
                (
                    snapshot_ts,
                    git_commit_value,
                    runtime_scope,
                    venue,
                    interval_code,
                    chain_name,
                    int(live_trading_enabled),
                    int(decision_gate_enabled),
                    int(execution_enabled),
                    notes,
                ),
            )

            snapshot_id = int(cur.lastrowid)

            component_rows = []
            for component in components:
                config_json = stable_json(component.config)
                component_rows.append(
                    (
                        snapshot_id,
                        component.component_layer,
                        component.component_name,
                        component.component_version,
                        component.component_mode,
                        stable_hash(component.config),
                        config_json,
                        int(component.enabled),
                    )
                )

            cur.executemany(
                """
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
                """,
                component_rows,
            )

        conn.commit()
        return snapshot_id

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()
