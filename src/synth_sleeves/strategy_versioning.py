"""
SYNTH v2
Module: synth_sleeves.strategy_versioning
Purpose:
    Deterministic strategy version hash generation.
Boundary:
    - Pure utility
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def make_strategy_version_hash(strategy_name: str, config_payload: dict[str, Any]) -> str:
    payload = {
        "strategy_name": strategy_name,
        "config_payload": config_payload,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_strategy_version_label(strategy_name: str, version_hash: str) -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{strategy_name}:{now_utc}:{version_hash[:12]}"
