"""
Synth v2.5 research runner: FIB_EXIT_LADDER_BACKTEST_V1.

Layer:
    research/backtest only.

Boundary:
    - Read-only.
    - No account access.
    - No order creation.
    - No writes to decision, execution, account, order, selection, or live tables.

Purpose:
    Backtest long-term bull-run partial sell ladders using deterministic wave/pivot anchors.

Model:
    1. Fetch 1d candles for each symbol.
    2. Detect a deterministic anchor_low -> wave1_high -> wave2_low structure.
    3. Compute fib/round extension targets:
           target = wave2_low + multiplier * (wave1_high - anchor_low)
    4. Turn each target into a front-run target box and sell ladder.
    5. Simulate passive limit sell fills against future candle highs.
    6. Compare against hold-to-end and peak-oracle baselines.

Notes:
    This is not Elliott truth.
    This is deterministic research scaffolding to test whether partial sell ladders
    would have harvested bull-run upside better than emotional holding.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import pymysql

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


READ_ONLY_FORBIDDEN_SQL_PREFIXES = (
    "insert",
    "update",
    "delete",
    "replace",
    "create",
    "alter",
    "drop",
    "truncate",
    "grant",
    "revoke",
    "call",
    "load",
    "rename",
    "lock",
    "unlock",
)


TARGET_FAMILIES: dict[str, tuple[list[Decimal], list[Decimal]]] = {
    "FIB_STANDARD": (
        [Decimal("1.618"), Decimal("2.000"), Decimal("2.618"), Decimal("3.618"), Decimal("4.236")],
        [Decimal("0.15"), Decimal("0.20"), Decimal("0.25"), Decimal("0.25"), Decimal("0.15")],
    ),
    "PRO_3X4X": (
        [Decimal("2.000"), Decimal("2.618"), Decimal("3.000"), Decimal("4.000"), Decimal("4.236")],
        [Decimal("0.20"), Decimal("0.25"), Decimal("0.25"), Decimal("0.20"), Decimal("0.10")],
    ),
    "SUPERCYCLE": (
        [Decimal("2.618"), Decimal("4.236"), Decimal("6.854"), Decimal("11.090")],
        [Decimal("0.25"), Decimal("0.35"), Decimal("0.25"), Decimal("0.15")],
    ),
    "EXPLOSIVE_SUPERCYCLE": (
        [Decimal("4.236"), Decimal("6.854"), Decimal("11.090"), Decimal("17.944")],
        [Decimal("0.20"), Decimal("0.30"), Decimal("0.30"), Decimal("0.20")],
    ),
}


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class Candle:
    open_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class AnchorSet:
    anchor_low_ts: datetime
    anchor_low: Decimal
    wave1_high_ts: datetime
    wave1_high: Decimal
    wave2_low_ts: datetime
    wave2_low: Decimal
    wave1_range: Decimal
    method: str


@dataclass(frozen=True)
class TargetLevel:
    rank: int
    multiplier: Decimal
    sell_fraction: Decimal
    target_price: Decimal
    zone_low: Decimal
    zone_high: Decimal


@dataclass(frozen=True)
class Rung:
    target_rank: int
    multiplier: Decimal
    limit_price: Decimal
    sell_fraction: Decimal


@dataclass(frozen=True)
class Fill:
    target_rank: int
    multiplier: Decimal
    limit_price: Decimal
    sell_fraction: Decimal
    fill_ts: datetime


@dataclass(frozen=True)
class SymbolResult:
    symbol: str
    status: str
    anchor: Optional[AnchorSet]
    entry_ts: Optional[datetime]
    entry_price: Optional[Decimal]
    end_ts: Optional[datetime]
    end_price: Optional[Decimal]
    peak_ts: Optional[datetime]
    peak_price: Optional[Decimal]
    filled_fraction: Decimal
    avg_exit_price: Optional[Decimal]
    realized_return_pct_on_full_position: Optional[Decimal]
    remaining_fraction: Decimal
    remaining_return_pct_on_full_position: Optional[Decimal]
    total_return_pct_with_remaining: Optional[Decimal]
    hold_return_pct: Optional[Decimal]
    peak_oracle_return_pct: Optional[Decimal]
    top_capture_ratio: Optional[Decimal]
    fills: list[Fill]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest fib/round bull-run exit ladders.")
    parser.add_argument("--symbols", default="LINK,SOL,XRP,HBAR,HOT,SUI,XLM")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--from-ts", default="2020-01-01 00:00:00")
    parser.add_argument("--to-ts", default="2022-01-01 00:00:00")
    parser.add_argument("--target-family", choices=sorted(TARGET_FAMILIES), default="PRO_3X4X")
    parser.add_argument("--max-ladder-sell-fraction", default="1.00", help="Maximum total position fraction sold by the ladder. 0.80 leaves 20% moonbag.")
    parser.add_argument("--pivot-threshold-pct", default="0.25")
    parser.add_argument("--min-wave1-gain-pct", default="1.00", help="Minimum wave1 gain as fraction, e.g. 1.00 = +100%.")
    parser.add_argument("--min-wave1-days", type=int, default=14, help="Minimum days between anchor low and wave1 high.")
    parser.add_argument("--min-wave2-days-after-high", type=int, default=3, help="Minimum days between wave1 high and wave2 low.")
    parser.add_argument("--wave2-min-retrace", default="0.236")
    parser.add_argument("--wave2-max-retrace", default="0.886")
    parser.add_argument("--target-zone-low-pct", default="0.04")
    parser.add_argument("--target-zone-high-pct", default="0.04")
    parser.add_argument("--front-run-pct", default="0.08")
    parser.add_argument("--end-pct-of-zone-high", default="0.98")
    parser.add_argument("--rungs-per-target", type=int, default=5)
    parser.add_argument("--distribution", choices=("front_loaded", "equal"), default="front_loaded")
    parser.add_argument("--print-fills", action="store_true")
    parser.add_argument("--env-file", default=None)
    return parser.parse_args()


def parse_datetime(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "").strip())


def parse_symbols(text: str) -> list[str]:
    symbols = [part.strip().upper() for part in text.split(",") if part.strip()]
    if not symbols:
        raise ValueError("At least one symbol is required.")
    return symbols


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


def opt_dec_text(value: Optional[Decimal], places: str = "0.0000") -> str:
    if value is None:
        return ""
    return format(value.quantize(Decimal(places)), "f")


def dec_text(value: Decimal, places: str = "0.0000") -> str:
    return format(value.quantize(Decimal(places)), "f")


def dt_text(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def load_db_config(env_file: Optional[str]) -> DbConfig:
    if load_dotenv is not None:
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

    return DbConfig(
        host=os.getenv("SYNTH_DB_HOST") or os.getenv("DB_HOST") or "127.0.0.1",
        port=int(os.getenv("SYNTH_DB_PORT") or os.getenv("DB_PORT") or "3306"),
        user=os.getenv("SYNTH_DB_USER") or os.getenv("DB_USER") or "root",
        password=os.getenv("SYNTH_DB_PASSWORD") or os.getenv("DB_PASSWORD") or "",
        database=os.getenv("SYNTH_DB_NAME") or os.getenv("DB_NAME") or "synth",
    )


def connect(config: DbConfig):
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def assert_read_only_sql(sql: str) -> None:
    stripped = sql.strip().lower()
    first_word = stripped.split(None, 1)[0] if stripped else ""
    if first_word in READ_ONLY_FORBIDDEN_SQL_PREFIXES:
        raise RuntimeError(f"Forbidden non-read SQL: {first_word}")


def fetch_all(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    assert_read_only_sql(sql)
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def fetch_one(conn, sql: str, params: tuple[Any, ...] = ()) -> Optional[dict[str, Any]]:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None


def detect_candle_columns(conn) -> dict[str, str]:
    rows = fetch_all(conn, "SHOW COLUMNS FROM obs_market_candle")
    available = {str(row["Field"]) for row in rows}

    mapping: dict[str, str] = {}
    for logical, candidates in {
        "open": ("open_price", "open"),
        "high": ("high_price", "high"),
        "low": ("low_price", "low"),
        "close": ("close_price", "close"),
    }.items():
        for candidate in candidates:
            if candidate in available:
                mapping[logical] = candidate
                break
        if logical not in mapping:
            raise RuntimeError(f"Missing candle column for {logical}; tried {candidates}")

    return mapping


def fetch_asset_id(conn, symbol: str) -> Optional[int]:
    row = fetch_one(
        conn,
        """
        SELECT asset_id
        FROM asset
        WHERE symbol = %s
        LIMIT 1
        """,
        (symbol,),
    )
    if row is None:
        return None
    return int(row["asset_id"])


def fetch_candles(
    conn,
    candle_columns: dict[str, str],
    asset_id: int,
    venue: str,
    interval_code: str,
    from_ts: datetime,
    to_ts: datetime,
) -> list[Candle]:
    open_col = candle_columns["open"]
    high_col = candle_columns["high"]
    low_col = candle_columns["low"]
    close_col = candle_columns["close"]

    rows = fetch_all(
        conn,
        f"""
        SELECT
            open_ts_utc,
            `{open_col}` AS open_price,
            `{high_col}` AS high_price,
            `{low_col}` AS low_price,
            `{close_col}` AS close_price
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
          AND open_ts_utc >= %s
          AND open_ts_utc < %s
        ORDER BY open_ts_utc ASC
        """,
        (asset_id, venue, interval_code, from_ts, to_ts),
    )

    return [
        Candle(
            open_ts_utc=row["open_ts_utc"],
            open_price=dec(row["open_price"]),
            high_price=dec(row["high_price"]),
            low_price=dec(row["low_price"]),
            close_price=dec(row["close_price"]),
        )
        for row in rows
    ]


def find_anchor_set(
    candles: list[Candle],
    pivot_threshold_pct: Decimal,
    min_wave1_gain_pct: Decimal,
    min_wave1_days: int,
    min_wave2_days_after_high: int,
    wave2_min_retrace: Decimal,
    wave2_max_retrace: Decimal,
) -> Optional[AnchorSet]:
    if len(candles) < 20:
        return None

    best: Optional[AnchorSet] = None
    best_score: Optional[Decimal] = None

    for low_idx in range(0, max(1, len(candles) - 10)):
        anchor_low = candles[low_idx].low_price
        if anchor_low <= 0:
            continue

        min_wave1_high = max(
            anchor_low * (Decimal("1") + pivot_threshold_pct),
            anchor_low * (Decimal("1") + min_wave1_gain_pct),
        )

        for high_idx in range(low_idx + 1, len(candles) - 5):
            wave1_days = (candles[high_idx].open_ts_utc - candles[low_idx].open_ts_utc).days
            if wave1_days < min_wave1_days:
                continue

            wave1_high = candles[high_idx].high_price
            if wave1_high < min_wave1_high:
                continue

            wave1_range = wave1_high - anchor_low
            if wave1_range <= 0:
                continue

            for wave2_idx in range(high_idx + 1, len(candles) - 1):
                wave2_days_after_high = (candles[wave2_idx].open_ts_utc - candles[high_idx].open_ts_utc).days
                if wave2_days_after_high < min_wave2_days_after_high:
                    continue

                wave2_low = candles[wave2_idx].low_price

                if wave2_low <= anchor_low:
                    continue
                if wave2_low >= wave1_high:
                    continue

                retrace = (wave1_high - wave2_low) / wave1_range
                if retrace < wave2_min_retrace or retrace > wave2_max_retrace:
                    continue

                future_high = max(candle.high_price for candle in candles[wave2_idx + 1 :])
                if future_high <= wave1_high:
                    continue

                expansion = (future_high - wave2_low) / wave1_range
                score = expansion

                if best is None or best_score is None or score > best_score:
                    best = AnchorSet(
                        anchor_low_ts=candles[low_idx].open_ts_utc,
                        anchor_low=anchor_low,
                        wave1_high_ts=candles[high_idx].open_ts_utc,
                        wave1_high=wave1_high,
                        wave2_low_ts=candles[wave2_idx].open_ts_utc,
                        wave2_low=wave2_low,
                        wave1_range=wave1_range,
                        method="deterministic_low_high_retrace_expansion",
                    )
                    best_score = score

    return best


def build_targets(
    anchor: AnchorSet,
    target_family: str,
    max_ladder_sell_fraction: Decimal,
    target_zone_low_pct: Decimal,
    target_zone_high_pct: Decimal,
) -> list[TargetLevel]:
    multipliers, fractions = TARGET_FAMILIES[target_family]
    total_fraction = sum(fractions)
    if total_fraction <= 0:
        raise ValueError(f"Invalid target family fractions for {target_family}")
    scaled_fractions = [
        (fraction / total_fraction) * max_ladder_sell_fraction
        for fraction in fractions
    ]

    targets: list[TargetLevel] = []
    for idx, (multiplier, sell_fraction) in enumerate(zip(multipliers, scaled_fractions), start=1):
        target_price = anchor.wave2_low + multiplier * anchor.wave1_range
        zone_low = target_price * (Decimal("1") - target_zone_low_pct)
        zone_high = target_price * (Decimal("1") + target_zone_high_pct)

        targets.append(
            TargetLevel(
                rank=idx,
                multiplier=multiplier,
                sell_fraction=sell_fraction,
                target_price=target_price,
                zone_low=zone_low,
                zone_high=zone_high,
            )
        )

    return targets


def rung_weights(rungs: int, distribution: str) -> list[Decimal]:
    if rungs <= 0:
        raise ValueError("rungs must be > 0")

    if distribution == "equal":
        return [Decimal("1") / Decimal(str(rungs)) for _ in range(rungs)]

    raw = [Decimal(str(rungs - idx)) for idx in range(rungs)]
    total = sum(raw)
    return [value / total for value in raw]


def ladder_prices(
    zone_low: Decimal,
    zone_high: Decimal,
    rungs: int,
    front_run_pct: Decimal,
    end_pct_of_zone_high: Decimal,
) -> list[Decimal]:
    if zone_high <= zone_low:
        raise ValueError("zone_high must be > zone_low")

    start_price = zone_low * (Decimal("1") - front_run_pct)
    end_price = zone_high * end_pct_of_zone_high

    if rungs == 1:
        return [start_price]

    step = (end_price - start_price) / Decimal(str(rungs - 1))
    return [start_price + step * Decimal(str(idx)) for idx in range(rungs)]


def build_rungs(
    targets: list[TargetLevel],
    rungs_per_target: int,
    front_run_pct: Decimal,
    end_pct_of_zone_high: Decimal,
    distribution: str,
) -> list[Rung]:
    weights = rung_weights(rungs_per_target, distribution)

    rungs: list[Rung] = []
    for target in targets:
        prices = ladder_prices(
            zone_low=target.zone_low,
            zone_high=target.zone_high,
            rungs=rungs_per_target,
            front_run_pct=front_run_pct,
            end_pct_of_zone_high=end_pct_of_zone_high,
        )

        for idx, price in enumerate(prices):
            rungs.append(
                Rung(
                    target_rank=target.rank,
                    multiplier=target.multiplier,
                    limit_price=price,
                    sell_fraction=target.sell_fraction * weights[idx],
                )
            )

    return sorted(rungs, key=lambda rung: rung.limit_price)


def simulate_fills(candles: list[Candle], start_ts: datetime, rungs: list[Rung]) -> list[Fill]:
    active_rungs = list(rungs)
    fills: list[Fill] = []

    for candle in candles:
        if candle.open_ts_utc < start_ts:
            continue

        remaining: list[Rung] = []
        for rung in active_rungs:
            if candle.high_price >= rung.limit_price:
                fills.append(
                    Fill(
                        target_rank=rung.target_rank,
                        multiplier=rung.multiplier,
                        limit_price=rung.limit_price,
                        sell_fraction=rung.sell_fraction,
                        fill_ts=candle.open_ts_utc,
                    )
                )
            else:
                remaining.append(rung)

        active_rungs = remaining
        if not active_rungs:
            break

    return fills


def weighted_avg_exit_price(fills: list[Fill]) -> Optional[Decimal]:
    total_fraction = sum(fill.sell_fraction for fill in fills)
    if total_fraction <= 0:
        return None
    total_value = sum(fill.limit_price * fill.sell_fraction for fill in fills)
    return total_value / total_fraction


def return_pct(exit_price: Decimal, entry_price: Decimal) -> Decimal:
    return ((exit_price - entry_price) / entry_price) * Decimal("100")


def evaluate_symbol(
    symbol: str,
    candles: list[Candle],
    target_family: str,
    max_ladder_sell_fraction: Decimal,
    pivot_threshold_pct: Decimal,
    min_wave1_gain_pct: Decimal,
    min_wave1_days: int,
    min_wave2_days_after_high: int,
    wave2_min_retrace: Decimal,
    wave2_max_retrace: Decimal,
    target_zone_low_pct: Decimal,
    target_zone_high_pct: Decimal,
    front_run_pct: Decimal,
    end_pct_of_zone_high: Decimal,
    rungs_per_target: int,
    distribution: str,
) -> SymbolResult:
    if len(candles) < 20:
        return empty_result(symbol, "INSUFFICIENT_CANDLES")

    anchor = find_anchor_set(
        candles=candles,
        pivot_threshold_pct=pivot_threshold_pct,
        min_wave1_gain_pct=min_wave1_gain_pct,
        min_wave1_days=min_wave1_days,
        min_wave2_days_after_high=min_wave2_days_after_high,
        wave2_min_retrace=wave2_min_retrace,
        wave2_max_retrace=wave2_max_retrace,
    )

    if anchor is None:
        return empty_result(symbol, "NO_ANCHOR_SET_FOUND")

    entry_ts = anchor.wave2_low_ts
    entry_price = anchor.wave2_low

    future_candles = [candle for candle in candles if candle.open_ts_utc >= entry_ts]
    if not future_candles:
        return empty_result(symbol, "NO_FUTURE_CANDLES")

    end_candle = future_candles[-1]
    peak_candle = max(future_candles, key=lambda candle: candle.high_price)

    targets = build_targets(
        anchor=anchor,
        target_family=target_family,
        max_ladder_sell_fraction=max_ladder_sell_fraction,
        target_zone_low_pct=target_zone_low_pct,
        target_zone_high_pct=target_zone_high_pct,
    )
    rungs = build_rungs(
        targets=targets,
        rungs_per_target=rungs_per_target,
        front_run_pct=front_run_pct,
        end_pct_of_zone_high=end_pct_of_zone_high,
        distribution=distribution,
    )
    fills = simulate_fills(candles=future_candles, start_ts=entry_ts, rungs=rungs)

    filled_fraction = sum(fill.sell_fraction for fill in fills)
    if filled_fraction > Decimal("1"):
        filled_fraction = Decimal("1")

    remaining_fraction = Decimal("1") - filled_fraction
    avg_exit = weighted_avg_exit_price(fills)

    realized_return = None
    if fills:
        realized_return = sum(
            fill.sell_fraction * return_pct(fill.limit_price, entry_price)
            for fill in fills
        )

    remaining_return = remaining_fraction * return_pct(end_candle.close_price, entry_price)
    total_return = (realized_return or Decimal("0")) + remaining_return

    hold_return = return_pct(end_candle.close_price, entry_price)
    peak_oracle_return = return_pct(peak_candle.high_price, entry_price)

    top_capture = None
    if peak_oracle_return != 0:
        top_capture = total_return / peak_oracle_return

    return SymbolResult(
        symbol=symbol,
        status="OK",
        anchor=anchor,
        entry_ts=entry_ts,
        entry_price=entry_price,
        end_ts=end_candle.open_ts_utc,
        end_price=end_candle.close_price,
        peak_ts=peak_candle.open_ts_utc,
        peak_price=peak_candle.high_price,
        filled_fraction=filled_fraction,
        avg_exit_price=avg_exit,
        realized_return_pct_on_full_position=realized_return,
        remaining_fraction=remaining_fraction,
        remaining_return_pct_on_full_position=remaining_return,
        total_return_pct_with_remaining=total_return,
        hold_return_pct=hold_return,
        peak_oracle_return_pct=peak_oracle_return,
        top_capture_ratio=top_capture,
        fills=fills,
    )


def empty_result(symbol: str, status: str) -> SymbolResult:
    return SymbolResult(
        symbol=symbol,
        status=status,
        anchor=None,
        entry_ts=None,
        entry_price=None,
        end_ts=None,
        end_price=None,
        peak_ts=None,
        peak_price=None,
        filled_fraction=Decimal("0"),
        avg_exit_price=None,
        realized_return_pct_on_full_position=None,
        remaining_fraction=Decimal("1"),
        remaining_return_pct_on_full_position=None,
        total_return_pct_with_remaining=None,
        hold_return_pct=None,
        peak_oracle_return_pct=None,
        top_capture_ratio=None,
        fills=[],
    )


def print_summary(results: list[SymbolResult], target_family: str) -> None:
    columns = [
        "symbol",
        "status",
        "target_family",
        "anchor_low_ts",
        "anchor_low",
        "wave1_high_ts",
        "wave1_high",
        "wave2_low_ts",
        "wave2_low_entry",
        "wave1_range",
        "end_ts",
        "end_price",
        "peak_ts",
        "peak_price",
        "filled_fraction_pct",
        "remaining_fraction_pct",
        "avg_exit_price",
        "realized_return_pct_on_full_position",
        "remaining_return_pct_on_full_position",
        "total_return_pct_with_remaining",
        "hold_return_pct",
        "peak_oracle_return_pct",
        "top_capture_ratio_pct",
        "fill_count",
    ]

    print("\t".join(columns))

    for result in results:
        anchor = result.anchor
        row = [
            result.symbol,
            result.status,
            target_family,
            dt_text(anchor.anchor_low_ts if anchor else None),
            opt_dec_text(anchor.anchor_low if anchor else None),
            dt_text(anchor.wave1_high_ts if anchor else None),
            opt_dec_text(anchor.wave1_high if anchor else None),
            dt_text(anchor.wave2_low_ts if anchor else None),
            opt_dec_text(result.entry_price),
            opt_dec_text(anchor.wave1_range if anchor else None),
            dt_text(result.end_ts),
            opt_dec_text(result.end_price),
            dt_text(result.peak_ts),
            opt_dec_text(result.peak_price),
            dec_text(result.filled_fraction * Decimal("100")),
            dec_text(result.remaining_fraction * Decimal("100")),
            opt_dec_text(result.avg_exit_price),
            opt_dec_text(result.realized_return_pct_on_full_position),
            opt_dec_text(result.remaining_return_pct_on_full_position),
            opt_dec_text(result.total_return_pct_with_remaining),
            opt_dec_text(result.hold_return_pct),
            opt_dec_text(result.peak_oracle_return_pct),
            opt_dec_text(result.top_capture_ratio * Decimal("100") if result.top_capture_ratio is not None else None),
            str(len(result.fills)),
        ]
        print("\t".join(row))


def print_fills(results: list[SymbolResult]) -> None:
    columns = [
        "symbol",
        "target_rank",
        "multiplier",
        "fill_ts",
        "limit_price",
        "sell_fraction_pct",
    ]

    print("")
    print("[FILLS]")
    print("\t".join(columns))

    for result in results:
        for fill in result.fills:
            row = [
                result.symbol,
                str(fill.target_rank),
                dec_text(fill.multiplier),
                dt_text(fill.fill_ts),
                dec_text(fill.limit_price),
                dec_text(fill.sell_fraction * Decimal("100")),
            ]
            print("\t".join(row))


def main() -> int:
    args = parse_args()

    symbols = parse_symbols(args.symbols)
    from_ts = parse_datetime(args.from_ts)
    to_ts = parse_datetime(args.to_ts)

    max_ladder_sell_fraction = Decimal(str(args.max_ladder_sell_fraction))
    pivot_threshold_pct = Decimal(str(args.pivot_threshold_pct))
    min_wave1_gain_pct = Decimal(str(args.min_wave1_gain_pct))
    min_wave1_days = int(args.min_wave1_days)
    min_wave2_days_after_high = int(args.min_wave2_days_after_high)
    wave2_min_retrace = Decimal(str(args.wave2_min_retrace))
    wave2_max_retrace = Decimal(str(args.wave2_max_retrace))
    target_zone_low_pct = Decimal(str(args.target_zone_low_pct))
    target_zone_high_pct = Decimal(str(args.target_zone_high_pct))
    front_run_pct = Decimal(str(args.front_run_pct))
    end_pct_of_zone_high = Decimal(str(args.end_pct_of_zone_high))

    config = load_db_config(args.env_file)
    conn = connect(config)

    results: list[SymbolResult] = []

    try:
        candle_columns = detect_candle_columns(conn)

        for symbol in symbols:
            asset_id = fetch_asset_id(conn, symbol)
            if asset_id is None:
                results.append(empty_result(symbol, "ASSET_NOT_FOUND"))
                continue

            candles = fetch_candles(
                conn=conn,
                candle_columns=candle_columns,
                asset_id=asset_id,
                venue=args.venue,
                interval_code=args.interval,
                from_ts=from_ts,
                to_ts=to_ts,
            )

            results.append(
                evaluate_symbol(
                    symbol=symbol,
                    candles=candles,
                    target_family=args.target_family,
                    max_ladder_sell_fraction=max_ladder_sell_fraction,
                    pivot_threshold_pct=pivot_threshold_pct,
                    min_wave1_gain_pct=min_wave1_gain_pct,
                    min_wave1_days=min_wave1_days,
                    min_wave2_days_after_high=min_wave2_days_after_high,
                    wave2_min_retrace=wave2_min_retrace,
                    wave2_max_retrace=wave2_max_retrace,
                    target_zone_low_pct=target_zone_low_pct,
                    target_zone_high_pct=target_zone_high_pct,
                    front_run_pct=front_run_pct,
                    end_pct_of_zone_high=end_pct_of_zone_high,
                    rungs_per_target=args.rungs_per_target,
                    distribution=args.distribution,
                )
            )
    finally:
        conn.close()

    print_summary(results, args.target_family)

    if args.print_fills:
        print_fills(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
