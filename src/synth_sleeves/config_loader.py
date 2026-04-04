"""
SYNTH v2
Module: synth_sleeves.config_loader
Purpose:
    Load sleeve configuration from YAML into typed config objects.
Boundary:
    - File I/O allowed
    - No DB I/O
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from src.synth_sleeves.models import DecisionAction, SleeveCode, SleeveConfig


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def load_sleeve_config(config_path: str | Path) -> dict[SleeveCode, SleeveConfig]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    result: dict[SleeveCode, SleeveConfig] = {}
    for sleeve_name, sleeve_raw in raw["sleeves"].items():
        sleeve_code = SleeveCode(sleeve_name)
        result[sleeve_code] = SleeveConfig(
            sleeve_code=sleeve_code,
            wallet_share=_to_decimal(sleeve_raw["wallet_share"]),
            max_positions=int(sleeve_raw["max_positions"]),
            per_position_cap=_to_decimal(sleeve_raw["per_position_cap"]),
            allowed_actions={DecisionAction(x) for x in sleeve_raw["allowed_actions"]},
            agent_names=list(sleeve_raw["agent_names"]),
            prepare_enabled=bool(sleeve_raw["prepare"]["enabled"]),
            prepare_cap=_to_decimal(sleeve_raw["prepare"]["cap"]),
            prepare_max_positions=int(sleeve_raw["prepare"]["max_positions"]),
        )

    wallet_total = sum((cfg.wallet_share for cfg in result.values()), start=Decimal("0"))
    if wallet_total != Decimal("1.00"):
        raise ValueError(f"Expected total wallet_share == 1.00, got {wallet_total}")

    return result


def load_sleeve_config_raw(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)
