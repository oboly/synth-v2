from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any


REPORT_NAME = "multi_horizon_fib_backtest_v1"
ANALYSIS_VERSION = "1.0"
ALGORITHM_VERSION = "1.0"
PARAMETER_PROFILE_ID = "default_v1"

FIB_TRADING_HORIZONS: tuple[str, ...] = ("SHORT", "MEDIUM", "LONG")
INTERVAL_ROLE_PRIMARY = "PRIMARY"
INTERVAL_ROLE_SUPPORT = "SUPPORT"
INTERVAL_ROLES: tuple[str, ...] = (INTERVAL_ROLE_PRIMARY, INTERVAL_ROLE_SUPPORT)

UNKNOWN_CONTEXT = "UNKNOWN"
STATUS_READY = "READY"
STATUS_SKIPPED = "SKIPPED"
STATUS_FAILED = "FAILED"

SKIP_MISSING_INTERVAL_HISTORY = "MISSING_INTERVAL_HISTORY"
SKIP_ZONE_SOURCE_MISSING = "ZONE_SOURCE_MISSING"
SKIP_UNSUPPORTED_INTERVAL = "UNSUPPORTED_INTERVAL"

DEFAULT_OUTPUT_DIR = "data/research/multi_horizon_fib_backtest_v1"
DEFAULT_OVERLAP_CANDLES = 8
DEFAULT_FEE_BPS_PER_SIDE = Decimal("25")
DEFAULT_PIVOT_SPAN = 3
DEFAULT_SUPPORT_LOOKAHEAD = 24

RETRACE_LEVELS: tuple[Decimal, ...] = (
    Decimal("0.382"),
    Decimal("0.500"),
    Decimal("0.618"),
    Decimal("0.786"),
)
EXTENSION_LEVELS: tuple[Decimal, ...] = (
    Decimal("1.272"),
    Decimal("1.618"),
    Decimal("2.000"),
    Decimal("2.618"),
    Decimal("3.618"),
    Decimal("4.236"),
)

INTERVAL_TO_DELTA = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
}

HORIZON_MATRIX: dict[str, dict[str, Any]] = {
    "SHORT": {
        "primary_interval": "4h",
        "supporting_intervals": ("1h",),
        "parent_horizon": "MEDIUM",
        "child_horizon": None,
        "live_window_days": 60,
    },
    "MEDIUM": {
        "primary_interval": "1d",
        "supporting_intervals": ("4h",),
        "parent_horizon": "LONG",
        "child_horizon": "SHORT",
        "live_window_days": 365,
    },
    "LONG": {
        "primary_interval": "1w",
        "supporting_intervals": ("1d",),
        "parent_horizon": None,
        "child_horizon": "MEDIUM",
        "live_window_days": 365 * 4,
    },
}


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso_z(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def decimal_text(value: Decimal | None, places: str = "0.00000001") -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(places)), "f")


@dataclass(frozen=True)
class Candle:
    symbol: str
    venue: str
    quote: str
    interval_code: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class ContextRow:
    symbol: str
    sample_ts_utc: datetime
    market_regime: str = UNKNOWN_CONTEXT
    symbol_regime: str = UNKNOWN_CONTEXT
    breath_phase: str = UNKNOWN_CONTEXT
    breath_alignment: str = UNKNOWN_CONTEXT


@dataclass(frozen=True)
class HorizonDefinition:
    fib_trading_horizon: str
    primary_interval: str
    supporting_intervals: tuple[str, ...]
    parent_horizon: str | None
    child_horizon: str | None
    live_window_days: int


def get_horizon_definition(fib_trading_horizon: str) -> HorizonDefinition:
    payload = HORIZON_MATRIX[fib_trading_horizon]
    return HorizonDefinition(
        fib_trading_horizon=fib_trading_horizon,
        primary_interval=str(payload["primary_interval"]),
        supporting_intervals=tuple(payload["supporting_intervals"]),
        parent_horizon=payload["parent_horizon"],
        child_horizon=payload["child_horizon"],
        live_window_days=int(payload["live_window_days"]),
    )


@dataclass
class FibCheckpoint:
    symbol: str
    venue: str
    quote: str
    fib_trading_horizon: str
    primary_interval: str
    supporting_intervals: list[str]
    analysis_version: str
    algorithm_version: str
    parameter_profile_id: str
    last_processed_primary_close_ts: str | None
    last_processed_support_close_ts: str | None
    last_confirmed_pivot_ts: str | None
    active_swing_id: str | None
    active_swing_low: str | None
    active_swing_high: str | None
    active_swing_low_ts: str | None
    active_swing_high_ts: str | None
    active_swing_state: str | None
    active_fib_levels: dict[str, str]
    completed_swing_count: int
    overlap_candles: int
    updated_ts: str
    source_refs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FibCheckpoint":
        return cls(**payload)


SAFETY_MARKERS = {
    "db_writes": 0,
    "db_reads": "candle_read_only",
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "account_tables_used": False,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "research_only": True,
}
