from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConfigSetRow:
    config_set_id: int
    config_name: str
    scope: str
    is_active: bool
    description: str | None
    created_ts_utc: datetime
    updated_ts_utc: datetime


@dataclass(frozen=True)
class ConfigParamRow:
    config_param_id: int
    config_set_id: int
    component: str
    parameter_name: str
    value_text: str
    value_type: str
    created_ts_utc: datetime
    updated_ts_utc: datetime
