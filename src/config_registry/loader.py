from __future__ import annotations

"""
ENGINE: config_registry_loader
MODE: latest-only

INPUT:
- synth_bt.config_set
- synth_bt.config_param

OUTPUT:
- in-memory typed config dictionary

CLI:
- imported only

HISTORICAL:
- not applicable

NOTES:
- converts DB config rows into typed Python values
- supports INT, DECIMAL, BOOL, STRING
- returns both structured config and flat snapshot metadata
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.config_registry.models import ConfigParamRow, ConfigSetRow
from src.config_registry.repository import ConfigRegistryRepository


SUPPORTED_VALUE_TYPES = {"INT", "DECIMAL", "BOOL", "STRING"}


def _coerce_value(value_text: str, value_type: str) -> int | Decimal | bool | str:
    normalized = value_type.strip().upper()

    if normalized not in SUPPORTED_VALUE_TYPES:
        raise ValueError(f"Unsupported config value_type: {value_type}")

    if normalized == "INT":
        return int(value_text)

    if normalized == "DECIMAL":
        return Decimal(value_text)

    if normalized == "BOOL":
        truthy = {"1", "true", "yes", "on", "y"}
        falsy = {"0", "false", "no", "off", "n"}
        lowered = value_text.strip().lower()
        if lowered in truthy:
            return True
        if lowered in falsy:
            return False
        raise ValueError(f"Invalid BOOL config value_text: {value_text}")

    return value_text


@dataclass(frozen=True)
class LoadedConfigSet:
    config_set: ConfigSetRow
    config_by_component: dict[str, dict[str, int | Decimal | bool | str]]
    snapshot_json_ready: dict[str, Any]


def build_typed_config(
    *,
    config_set: ConfigSetRow,
    params: list[ConfigParamRow],
) -> LoadedConfigSet:
    config_by_component: dict[str, dict[str, int | Decimal | bool | str]] = {}
    snapshot_json_ready: dict[str, Any] = {
        "config_set_id": config_set.config_set_id,
        "config_name": config_set.config_name,
        "scope": config_set.scope,
        "description": config_set.description,
        "params": {},
    }

    for param in params:
        typed_value = _coerce_value(param.value_text, param.value_type)

        if param.component not in config_by_component:
            config_by_component[param.component] = {}
        config_by_component[param.component][param.parameter_name] = typed_value

        if param.component not in snapshot_json_ready["params"]:
            snapshot_json_ready["params"][param.component] = {}

        if isinstance(typed_value, Decimal):
            snapshot_json_ready["params"][param.component][param.parameter_name] = str(typed_value)
        else:
            snapshot_json_ready["params"][param.component][param.parameter_name] = typed_value

    return LoadedConfigSet(
        config_set=config_set,
        config_by_component=config_by_component,
        snapshot_json_ready=snapshot_json_ready,
    )


def load_config_set(
    *,
    scope: str,
    config_name: str,
    require_active: bool = True,
    repository: ConfigRegistryRepository | None = None,
) -> LoadedConfigSet:
    repo = repository or ConfigRegistryRepository()

    config_set = repo.fetch_config_set(
        scope=scope,
        config_name=config_name,
        require_active=require_active,
    )
    if config_set is None:
        raise ValueError(
            f"Config set not found for scope={scope!r} config_name={config_name!r}"
        )

    params = repo.fetch_config_params(config_set_id=config_set.config_set_id)
    if not params:
        raise ValueError(
            f"No config parameters found for config_set_id={config_set.config_set_id}"
        )

    return build_typed_config(
        config_set=config_set,
        params=params,
    )
