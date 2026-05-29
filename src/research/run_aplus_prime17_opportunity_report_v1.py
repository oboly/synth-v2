from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.breathline.parse_aplus_table1_canonical_v1 import ALLOWED as TABLE1_ALLOWED
from src.breathline.parse_aplus_table2_harmonic_overlay_v1 import ALLOWED as TABLE2_ALLOWED
from src.common.db import get_connection


REPORT_NAME = "aplus_prime17_opportunity_report_v1"
REPORT_VERSION = "1.0"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_INTERVAL = "1d"

PRIME17_TOKENS = [
    "TAO",
    "INJ",
    "RENDER",
    "QNT",
    "BTC",
    "AAVE",
    "LTC",
    "LINK",
    "ETH",
    "NEAR",
    "FET",
    "DOT",
    "XLM",
    "MOG",
    "HYPE",
    "PEPE",
    "SUI",
]

ANOMALY_TOKENS = {"MOG", "HYPE", "PEPE", "SUI", "RENDER"}
SELECTION_CONSTRUCTIVE_STATES = {
    "BUY_READY",
    "PREPARE",
    "WATCHLIST",
    "PRE_ALIGNMENT",
    "EARLY_WATCH",
}
SELECTION_CONSTRUCTIVE_BIASES = {
    "BULLISH",
    "LONG",
    "BUY",
    "LONG_BIAS",
    "WATCH",
    "NEUTRAL_POSITIVE",
}


@dataclass(frozen=True)
class Table1FocusRecord:
    token: str
    aplus_phase: str
    aplus_coherence: str
    aplus_field: str
    aplus_role: str
    aplus_bias: str
    notes: str


@dataclass(frozen=True)
class Table2FocusRecord:
    token: str
    harmonic_phase: str
    phase_state: str
    offset_band: str
    drift_direction: str
    quality: str
    extension_risk: str
    notes: str


@dataclass(frozen=True)
class OpportunityRow:
    token: str
    aplus_phase: str
    aplus_coherence: str
    aplus_field: str
    aplus_role: str
    aplus_bias: str
    harmonic_phase: str
    phase_state: str
    offset_band: str
    drift_direction: str
    quality: str
    extension_risk: str
    selection_state: str
    selection_bias: str
    selection_score: str
    zone_context_summary: str
    volume_context_summary: str
    opportunity_bucket: str
    reason: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only A+ Prime-17 opportunity report combining A+ posture, harmonic phase, "
            "latest Synth selection context, optional fib/zone context, and recent volume/return context."
        )
    )
    parser.add_argument("--table1-raw", required=True)
    parser.add_argument("--table2-raw", required=True)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def clean(value: str) -> str:
    return value.strip().strip("`").strip()


def parse_focus_table1(raw: str) -> dict[str, Table1FocusRecord]:
    out: dict[str, Table1FocusRecord] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped or stripped.upper().startswith("TOKEN |"):
            continue
        token = stripped.split("|", 1)[0].strip()
        if token not in PRIME17_TOKENS:
            continue
        parts = [clean(part) for part in stripped.split("|")]
        if len(parts) != 10:
            raise ValueError(f"{token}: expected 10 pipe-separated fields in table1 focus snapshot")
        phase = parts[1]
        coherence = parts[2]
        field = parts[3]
        structural_role = parts[5]
        strategic_bias = parts[8]
        notes = parts[9].strip('"')
        for key, value in {
            "phase": phase,
            "coherence": coherence,
            "field": field,
            "structural_role": structural_role,
            "strategic_bias": strategic_bias,
        }.items():
            if value not in TABLE1_ALLOWED[key]:
                raise ValueError(f"{token}: invalid table1 {key}={value!r}")
        out[token] = Table1FocusRecord(
            token=token,
            aplus_phase=phase,
            aplus_coherence=coherence,
            aplus_field=field,
            aplus_role=structural_role,
            aplus_bias=strategic_bias,
            notes=notes,
        )
    missing = [token for token in PRIME17_TOKENS if token not in out]
    if missing:
        raise ValueError(f"Missing table1 Prime-17 tokens: {','.join(missing)}")
    return out


def parse_focus_table2(raw: str) -> dict[str, Table2FocusRecord]:
    out: dict[str, Table2FocusRecord] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped or stripped.upper().startswith("TOKEN |"):
            continue
        token = stripped.split("|", 1)[0].strip()
        if token not in PRIME17_TOKENS:
            continue
        parts = [clean(part) for part in stripped.split("|")]
        if len(parts) != 8:
            raise ValueError(f"{token}: expected 8 pipe-separated fields in table2 focus snapshot")
        harmonic_phase = parts[1]
        phase_state = parts[2]
        offset_band = parts[3]
        drift_direction = parts[4]
        quality = parts[5]
        extension_risk = parts[6]
        notes = parts[7].strip('"')
        for key, value in {
            "harmonic_phase": harmonic_phase,
            "phase_state": phase_state,
            "offset_band": offset_band,
            "drift_direction": drift_direction,
            "quality": quality,
            "extension_risk": extension_risk,
        }.items():
            if value not in TABLE2_ALLOWED[key]:
                raise ValueError(f"{token}: invalid table2 {key}={value!r}")
        out[token] = Table2FocusRecord(
            token=token,
            harmonic_phase=harmonic_phase,
            phase_state=phase_state,
            offset_band=offset_band,
            drift_direction=drift_direction,
            quality=quality,
            extension_risk=extension_risk,
            notes=notes,
        )
    missing = [token for token in PRIME17_TOKENS if token not in out]
    if missing:
        raise ValueError(f"Missing table2 Prime-17 tokens: {','.join(missing)}")
    return out


def safe_decimal_text(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, Decimal):
        return format(value, "f")
    try:
        return format(Decimal(str(value)), "f")
    except Exception:
        return str(value)


def table_exists(conn: Any, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = %s
            LIMIT 1
            """,
            (table_name,),
        )
        return cur.fetchone() is not None


def table_columns(conn: Any, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = %s
            """,
            (table_name,),
        )
        return {str(row["column_name"]) for row in cur.fetchall()}


def fetch_asset_ids(conn: Any, tokens: list[str]) -> dict[str, int]:
    placeholders = ", ".join(["%s"] * len(tokens))
    sql = f"SELECT symbol, asset_id FROM asset WHERE symbol IN ({placeholders})"
    with conn.cursor() as cur:
        cur.execute(sql, tokens)
        rows = cur.fetchall()
    return {str(row["symbol"]).upper(): int(row["asset_id"]) for row in rows}


def fetch_latest_selection_context(
    conn: Any,
    *,
    tokens: list[str],
    venue: str,
) -> dict[str, dict[str, Any]]:
    if not table_exists(conn, "selection_state"):
        return {}
    placeholders = ", ".join(["%s"] * len(tokens))
    sql = f"""
        SELECT
            a.symbol,
            s.selection_state,
            s.selection_bias,
            s.selection_score,
            s.priority_rank,
            s.asof_ts_utc
        FROM selection_state s
        JOIN asset a ON a.asset_id = s.asset_id
        WHERE s.venue = %s
          AND a.symbol IN ({placeholders})
        ORDER BY a.symbol ASC, s.asof_ts_utc DESC, s.priority_rank IS NULL, s.priority_rank ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, [venue, *tokens])
        rows = cur.fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        if symbol not in out:
            out[symbol] = row
    return out


def fetch_latest_zone_context(
    conn: Any,
    *,
    tokens: list[str],
    venue: str,
    asset_ids: dict[str, int],
) -> dict[str, dict[str, Any]]:
    if not table_exists(conn, "execution_zone_context"):
        return {}
    columns = table_columns(conn, "execution_zone_context")
    ts_col = next((name for name in ("asof_ts_utc", "context_ts_utc", "updated_ts_utc", "created_ts_utc") if name in columns), None)
    if "asset_id" not in columns or "venue" not in columns or ts_col is None:
        return {}
    selected_cols = [col for col in [
        "asset_id",
        "venue",
        ts_col,
        "entry_zone_low",
        "entry_zone_high",
        "tp_zone_low",
        "tp_zone_high",
        "invalidation_price",
        "setup_fail_reason",
        "reclaim_state",
        "retest_state",
        "zone_context_summary",
    ] if col in columns]
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT {", ".join(selected_cols)}
        FROM execution_zone_context
        WHERE venue = %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id ASC, {ts_col} DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, [venue, *asset_ids.values()])
        rows = cur.fetchall()
    reverse_asset = {asset_id: symbol for symbol, asset_id in asset_ids.items()}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = reverse_asset.get(int(row["asset_id"]))
        if symbol and symbol not in out:
            out[symbol] = row
    return out


def fetch_recent_candle_context(
    conn: Any,
    *,
    asset_ids: dict[str, int],
    venue: str,
    interval: str,
) -> dict[str, dict[str, Any]]:
    if not table_exists(conn, "obs_market_candle"):
        return {}
    columns = table_columns(conn, "obs_market_candle")
    required = {"asset_id", "venue", "interval_code", "close_ts_utc", "close_price"}
    if not required.issubset(columns):
        return {}
    volume_col = "volume_quote_eur" if "volume_quote_eur" in columns else None
    selected_cols = ["asset_id", "close_ts_utc", "close_price"]
    if volume_col:
        selected_cols.append(volume_col)
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT {", ".join(selected_cols)}
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id ASC, close_ts_utc DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, [venue, interval, *asset_ids.values()])
        rows = cur.fetchall()
    reverse_asset = {asset_id: symbol for symbol, asset_id in asset_ids.items()}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = reverse_asset.get(int(row["asset_id"]))
        if symbol is None:
            continue
        bucket = grouped.setdefault(symbol, [])
        if len(bucket) < 5:
            bucket.append(row)
    out: dict[str, dict[str, Any]] = {}
    for symbol, bucket in grouped.items():
        if not bucket:
            continue
        latest = bucket[0]
        latest_close = float(latest["close_price"])
        prev_close = float(bucket[1]["close_price"]) if len(bucket) > 1 and bucket[1]["close_price"] is not None else None
        ret_1 = None if prev_close in (None, 0.0) else round(((latest_close / prev_close) - 1.0) * 100.0, 3)
        vol_ratio = None
        if volume_col and len(bucket) >= 3:
            latest_vol = float(latest[volume_col] or 0.0)
            history = [float(row[volume_col] or 0.0) for row in bucket[1:] if row.get(volume_col) is not None]
            avg_hist = sum(history) / len(history) if history else 0.0
            if avg_hist > 0:
                vol_ratio = round(latest_vol / avg_hist, 3)
        close_ts = latest["close_ts_utc"]
        if isinstance(close_ts, datetime):
            close_ts_text = close_ts.astimezone(UTC).isoformat().replace("+00:00", "Z")
        else:
            close_ts_text = str(close_ts)
        out[symbol] = {
            "return_1_interval_pct": ret_1,
            "volume_ratio": vol_ratio,
            "close_ts_utc": close_ts_text,
        }
    return out


def format_zone_summary(row: dict[str, Any] | None) -> str:
    if not row:
        return "unavailable"
    if row.get("zone_context_summary"):
        return str(row["zone_context_summary"])
    parts: list[str] = []
    entry_low = row.get("entry_zone_low")
    entry_high = row.get("entry_zone_high")
    if entry_low is not None or entry_high is not None:
        parts.append(f"entry={entry_low}-{entry_high}")
    tp_low = row.get("tp_zone_low")
    tp_high = row.get("tp_zone_high")
    if tp_low is not None or tp_high is not None:
        parts.append(f"tp={tp_low}-{tp_high}")
    if row.get("invalidation_price") is not None:
        parts.append(f"invalid={row['invalidation_price']}")
    if row.get("reclaim_state"):
        parts.append(f"reclaim={row['reclaim_state']}")
    if row.get("retest_state"):
        parts.append(f"retest={row['retest_state']}")
    if row.get("setup_fail_reason"):
        parts.append(f"fail={row['setup_fail_reason']}")
    return "; ".join(parts) if parts else "unavailable"


def format_volume_summary(row: dict[str, Any] | None) -> str:
    if not row:
        return "unavailable"
    parts: list[str] = []
    if row.get("return_1_interval_pct") is not None:
        parts.append(f"ret1={float(row['return_1_interval_pct']):+.3f}%")
    if row.get("volume_ratio") is not None:
        parts.append(f"vol_ratio={float(row['volume_ratio']):.3f}x")
    if row.get("close_ts_utc"):
        parts.append(f"asof={row['close_ts_utc']}")
    return "; ".join(parts) if parts else "unavailable"


def selection_is_constructive(selection_row: dict[str, Any] | None) -> bool:
    if not selection_row:
        return False
    state = str(selection_row.get("selection_state") or "").upper()
    bias = str(selection_row.get("selection_bias") or "").upper()
    score = selection_row.get("selection_score")
    try:
        score_ok = score is not None and float(score) >= 0.45
    except Exception:
        score_ok = False
    return state in SELECTION_CONSTRUCTIVE_STATES or (bias in SELECTION_CONSTRUCTIVE_BIASES and score_ok)


def selection_confirmed(selection_row: dict[str, Any] | None) -> bool:
    if not selection_row:
        return False
    state = str(selection_row.get("selection_state") or "").upper()
    return state != "AVOID" and selection_is_constructive(selection_row)


def zone_valid(zone_summary: str) -> bool:
    normalized = zone_summary.strip().lower()
    if normalized == "unavailable":
        return False
    if normalized.startswith("invalid="):
        return False
    if "invalid=" in normalized:
        return False
    if "fail=" in normalized:
        return False
    return True


def volume_confirmed(volume_row: dict[str, Any] | None) -> bool:
    if not volume_row:
        return False
    ret_value = volume_row.get("return_1_interval_pct")
    vol_ratio = volume_row.get("volume_ratio")
    return bool(
        (ret_value is not None and float(ret_value) > 0)
        or (vol_ratio is not None and float(vol_ratio) >= 1.05)
    )


def classify_bucket(
    *,
    token: str,
    t1: Table1FocusRecord,
    t2: Table2FocusRecord,
    selection_row: dict[str, Any] | None,
    zone_summary: str,
    volume_row: dict[str, Any] | None,
) -> tuple[str, str]:
    constructive = (
        t1.aplus_phase in {"forming", "confirmed"}
        and t1.aplus_coherence in {"high", "moderate"}
        and t1.aplus_bias in {"accumulation", "continuation"}
    )
    deterioration = (
        t1.aplus_phase in {"late", "exhaustion", "reset"}
        or t1.aplus_bias in {"caution", "avoid"}
        or t2.harmonic_phase in {"late_extension", "reset"}
        or t2.phase_state in {"late", "exhausted"}
        or t2.quality == "dirty"
        or t2.extension_risk == "high"
    )
    selection_yes = selection_confirmed(selection_row)
    zone_yes = zone_valid(zone_summary)
    volume_yes = volume_confirmed(volume_row)
    synth_confirmation = selection_yes or zone_yes or volume_yes
    harmonic_safe = (
        t2.quality in {"clean", "mixed"}
        and t2.extension_risk in {"low", "moderate"}
        and t2.harmonic_phase not in {"late_extension", "reset", "unclear"}
        and t2.phase_state not in {"late", "exhausted"}
    )
    if deterioration:
        return "CAUTION_DETERIORATION", (
            f"phase={t1.aplus_phase}; bias={t1.aplus_bias}; harmonic={t2.harmonic_phase}; "
            f"risk={t2.extension_risk}; quality={t2.quality}"
        )
    if constructive and harmonic_safe and synth_confirmation:
        return "A_PLUS_CORE_CONTINUATION", (
            f"constructive_a_plus; harmonic_safe; "
            f"selection={'yes' if selection_yes else 'no'}; "
            f"zone_valid={'yes' if zone_yes else 'no'}; "
            f"volume_confirmed={'yes' if volume_yes else 'no'}"
        )
    if token in ANOMALY_TOKENS and (zone_yes or volume_yes) and (
        t2.extension_risk == "high"
        or t2.quality in {"mixed", "dirty"}
        or t1.aplus_role in {"speculative"}
    ):
        return "FIB_EXPLOSION_CANDIDATE", (
            f"anomaly_candidate; role={t1.aplus_role}; harmonic={t2.harmonic_phase}; risk={t2.extension_risk}; "
            f"zone_valid={'yes' if zone_yes else 'no'}; volume_confirmed={'yes' if volume_yes else 'no'}"
        )
    if constructive and harmonic_safe:
        return "WATCH_ONLY_NEEDS_SYNTH_CONFIRMATION", (
            f"constructive_a_plus_without_synth_confirmation; selection={'yes' if selection_yes else 'no'}; "
            f"zone_valid={'yes' if zone_yes else 'no'}; volume_confirmed={'yes' if volume_yes else 'no'}; "
            f"zone={zone_summary}; volume={format_volume_summary(volume_row)}"
        )
    return "NO_SETUP", "insufficient_data_or_no_constructive_alignment"


def fetch_optional_context(
    *,
    tokens: list[str],
    venue: str,
    interval: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    meta = {
        "db_access": "unavailable",
        "selection_context": "unavailable",
        "zone_context": "unavailable",
        "volume_context": "unavailable",
        "db_error": None,
    }
    try:
        conn = get_connection()
    except Exception as exc:
        meta["db_error"] = f"{type(exc).__name__}: {exc}"
        return {}, {}, {}, meta
    try:
        asset_ids = fetch_asset_ids(conn, tokens)
        selection_map = fetch_latest_selection_context(conn, tokens=tokens, venue=venue)
        zone_map = fetch_latest_zone_context(conn, tokens=tokens, venue=venue, asset_ids=asset_ids) if asset_ids else {}
        volume_map = fetch_recent_candle_context(conn, asset_ids=asset_ids, venue=venue, interval=interval) if asset_ids else {}
        meta["db_access"] = "available"
        meta["selection_context"] = "available" if selection_map else "unavailable"
        meta["zone_context"] = "available" if zone_map else "unavailable"
        meta["volume_context"] = "available" if volume_map else "unavailable"
        return selection_map, zone_map, volume_map, meta
    except Exception as exc:
        meta["db_error"] = f"{type(exc).__name__}: {exc}"
        return {}, {}, {}, meta
    finally:
        conn.close()


def build_rows(
    *,
    table1: dict[str, Table1FocusRecord],
    table2: dict[str, Table2FocusRecord],
    selection_map: dict[str, dict[str, Any]],
    zone_map: dict[str, dict[str, Any]],
    volume_map: dict[str, dict[str, Any]],
) -> list[OpportunityRow]:
    rows: list[OpportunityRow] = []
    for token in PRIME17_TOKENS:
        t1 = table1[token]
        t2 = table2[token]
        selection_row = selection_map.get(token)
        zone_summary = format_zone_summary(zone_map.get(token))
        volume_summary = format_volume_summary(volume_map.get(token))
        bucket, reason = classify_bucket(
            token=token,
            t1=t1,
            t2=t2,
            selection_row=selection_row,
            zone_summary=zone_summary,
            volume_row=volume_map.get(token),
        )
        rows.append(
            OpportunityRow(
                token=token,
                aplus_phase=t1.aplus_phase,
                aplus_coherence=t1.aplus_coherence,
                aplus_field=t1.aplus_field,
                aplus_role=t1.aplus_role,
                aplus_bias=t1.aplus_bias,
                harmonic_phase=t2.harmonic_phase,
                phase_state=t2.phase_state,
                offset_band=t2.offset_band,
                drift_direction=t2.drift_direction,
                quality=t2.quality,
                extension_risk=t2.extension_risk,
                selection_state=str(selection_row.get("selection_state")) if selection_row else "unavailable",
                selection_bias=str(selection_row.get("selection_bias")) if selection_row else "unavailable",
                selection_score=safe_decimal_text(selection_row.get("selection_score") if selection_row else None),
                zone_context_summary=zone_summary,
                volume_context_summary=volume_summary,
                opportunity_bucket=bucket,
                reason=reason,
            )
        )
    return rows


def print_table(rows: list[OpportunityRow]) -> None:
    columns = [
        "token",
        "aplus_phase",
        "aplus_coherence",
        "aplus_field",
        "aplus_role",
        "aplus_bias",
        "harmonic_phase",
        "phase_state",
        "offset_band",
        "drift_direction",
        "quality",
        "extension_risk",
        "selection_state",
        "selection_bias",
        "selection_score",
        "zone_context_summary",
        "volume_context_summary",
        "opportunity_bucket",
        "reason",
    ]
    print("\t".join(columns))
    for row in rows:
        payload = asdict(row)
        print("\t".join(str(payload[col]) for col in columns))


def print_json(rows: list[OpportunityRow], meta: dict[str, Any]) -> None:
    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "row_count": len(rows),
        "safety": {
            "db_writes": 0,
            "broker_calls": 0,
            "broker_writes": 0,
            "order_logic": 0,
            "selection_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
        },
        "context_meta": meta,
        "rows": [asdict(row) for row in rows],
    }
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    table1_raw = Path(args.table1_raw).read_text(encoding="utf-8")
    table2_raw = Path(args.table2_raw).read_text(encoding="utf-8")
    table1 = parse_focus_table1(table1_raw)
    table2 = parse_focus_table2(table2_raw)
    selection_map, zone_map, volume_map, meta = fetch_optional_context(
        tokens=PRIME17_TOKENS,
        venue=args.venue,
        interval=args.interval,
    )
    rows = build_rows(
        table1=table1,
        table2=table2,
        selection_map=selection_map,
        zone_map=zone_map,
        volume_map=volume_map,
    )
    if args.output == "json":
        print_json(rows, meta)
    else:
        print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
