from __future__ import annotations

"""
ENGINE: run_show_config_set
MODE: latest-only

INPUT:
- synth_bt.config_set
- synth_bt.config_param

OUTPUT:
- stdout only

CLI:
python -m src.config_registry.run_show_config_set \
  --scope BACKTEST \
  --config-name backtest_baseline

HISTORICAL:
- not applicable

NOTES:
- debug/inspection helper for config registry
"""

import argparse
import json
from decimal import Decimal
from typing import Any

from src.config_registry.loader import load_config_set


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show typed DB-backed config set.")
    parser.add_argument("--scope", required=True)
    parser.add_argument("--config-name", required=True)
    parser.add_argument("--include-inactive", action="store_true")
    return parser.parse_args()


def _jsonify(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    return value


def main() -> int:
    args = parse_args()

    loaded = load_config_set(
        scope=args.scope,
        config_name=args.config_name,
        require_active=not args.include_inactive,
    )

    payload = {
        "config_set_id": loaded.config_set.config_set_id,
        "config_name": loaded.config_set.config_name,
        "scope": loaded.config_set.scope,
        "is_active": loaded.config_set.is_active,
        "description": loaded.config_set.description,
        "config": loaded.config_by_component,
    }

    print(json.dumps(_jsonify(payload), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
