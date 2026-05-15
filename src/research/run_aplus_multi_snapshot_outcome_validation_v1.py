from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "aplus_multi_snapshot_outcome_validation_v1"
PARSER_VERSION = "0.1"
SAMPLE_LIMITATION = "LOW_SAMPLE_MULTI_SNAPSHOT"

TABLE1_FIELDS = [
    "table1_phase",
    "table1_coherence",
    "table1_field",
    "table1_geometry",
    "table1_structural_role",
    "table1_expansion_quality",
    "table1_anchor_strength",
    "table1_strategic_bias",
]
TABLE2_FIELDS = [
    "table2_harmonic_phase",
    "table2_phase_state",
    "table2_offset_band",
    "table2_drift_direction",
    "table2_quality",
    "table2_extension_risk",
]

SINGLE_FIELD_GROUPS = [
    "table1_phase",
    "table1_coherence",
    "table1_field",
    "table1_structural_role",
    "table1_strategic_bias",
    "table2_harmonic_phase",
    "table2_phase_state",
    "table2_offset_band",
    "table2_quality",
    "table2_extension_risk",
]

CROSS_FIELD_GROUPS: list[tuple[str, str]] = [
    ("table1_coherence", "table2_quality"),
    ("table1_strategic_bias", "table2_extension_risk"),
    ("table1_phase", "table2_harmonic_phase"),
]

PAIR_META_FIELDS = [
    "pair_reference_ts_utc",
    "table1_prediction_ts_utc",
    "table2_prediction_ts_utc",
    "timestamp_mismatch_minutes",
    "same_snapshot_ts",
    "timestamp_mismatch_allowed",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate A+ Table 1/Table 2 labels against forward market outcomes across multiple normalized snapshots (research-only)."
    )
    parser.add_argument(
        "--joined-paths",
        nargs="+",
        default=[
            "data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260514_1315_1256.jsonl",
            "data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260515_1244.jsonl",
        ],
        help="One or more paths to joined Table 1/Table 2 JSONL files.",
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=[4, 24, 72],
        help="Forward horizons in hours.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/research/aplus_multi_snapshot_outcome_validation_v1",
    )
    parser.add_argument("--output", choices=["table", "json"], default="table")
    parser.add_argument("--write-files", action="store_true")
    return parser.parse_args(argv)


def pair_id_from_path(path: Path) -> str:
    stem = path.stem  # e.g. "table1_table2_joined_20260514_1315_1256"
    prefix = "table1_table2_joined_"
    if stem.startswith(prefix):
        return stem[len(prefix):]
    return stem


def load_joined(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def parse_ts(text: str) -> datetime:
    raw = text.rstrip("Z")
    dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)


def as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def fetch_asset_map(conn, tokens: list[str]) -> dict[str, int]:
    if not tokens:
        return {}
    placeholders = ", ".join(["%s"] * len(tokens))
    sql = f"SELECT asset_id, symbol FROM asset WHERE symbol IN ({placeholders})"
    with conn.cursor() as cur:
        cur.execute(sql, tuple(tokens))
        rows = cur.fetchall()
    out: dict[str, int] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        out[symbol] = int(row["asset_id"])
    return out


def fetch_base_candle(conn, asset_id: int, venue: str, interval: str, asof: datetime) -> dict[str, Any] | None:
    sql = """
        SELECT close_ts_utc, close_price
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
          AND close_ts_utc <= %s
        ORDER BY close_ts_utc DESC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (asset_id, venue, interval, to_naive_utc(asof)))
        row = cur.fetchone()
    return row


def fetch_future_candle(conn, asset_id: int, venue: str, interval: str, target: datetime) -> dict[str, Any] | None:
    sql = """
        SELECT close_ts_utc, close_price
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
          AND close_ts_utc >= %s
        ORDER BY close_ts_utc ASC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (asset_id, venue, interval, to_naive_utc(target)))
        row = cur.fetchone()
    return row


def fetch_mfe_mae(conn, asset_id: int, venue: str, interval: str, base_ts: datetime, future_ts: datetime) -> dict[str, Any] | None:
    sql = """
        SELECT MAX(high_price) AS max_high, MIN(low_price) AS min_low, COUNT(*) AS n_candles
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
          AND close_ts_utc > %s
          AND close_ts_utc <= %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (asset_id, venue, interval, to_naive_utc(base_ts), to_naive_utc(future_ts)))
        row = cur.fetchone()
    return row


def resolve_alignment_ts(joined_row: dict[str, Any]) -> datetime:
    """Use pair_reference_ts_utc if present; fall back to prediction_ts_utc."""
    ts_str = joined_row.get("pair_reference_ts_utc") or joined_row.get("prediction_ts_utc")
    if not ts_str:
        raise ValueError(f"No alignment timestamp in row for token {joined_row.get('token')}")
    return parse_ts(str(ts_str))


def compute_outcome_row(
    conn,
    joined_row: dict[str, Any],
    snapshot_pair_id: str,
    asset_id: int | None,
    venue: str,
    interval: str,
    alignment_ts: datetime,
    horizon_hours: int,
) -> dict[str, Any]:
    token = str(joined_row["token"]).upper()

    base: dict[str, Any] = {
        "snapshot_pair_id": snapshot_pair_id,
        "pair_reference_ts_utc": joined_row.get("pair_reference_ts_utc"),
        "prediction_ts_utc": joined_row.get("prediction_ts_utc"),
        "same_snapshot_ts": joined_row.get("same_snapshot_ts"),
        "timestamp_mismatch_minutes": joined_row.get("timestamp_mismatch_minutes"),
        "timestamp_mismatch_allowed": joined_row.get("timestamp_mismatch_allowed"),
        "table1_prediction_ts_utc": joined_row.get("table1_prediction_ts_utc"),
        "table2_prediction_ts_utc": joined_row.get("table2_prediction_ts_utc"),
        "token": token,
        "asset_id": asset_id,
        "venue": venue,
        "interval_code": interval,
        "horizon_hours": int(horizon_hours),
        "base_ts_utc": None,
        "future_ts_utc": None,
        "base_price": None,
        "future_price": None,
        "forward_return_pct": None,
        "mfe_pct": None,
        "mae_pct": None,
        "outcome_status": None,
        "source_joined_path": joined_row.get("_source_path"),
        "validation_status": None,
    }
    for field in TABLE1_FIELDS + TABLE2_FIELDS:
        base[field] = joined_row.get(field)

    if asset_id is None:
        base["outcome_status"] = "MISSING_ASSET"
        base["validation_status"] = "MISSING_ASSET"
        return base

    base_candle = fetch_base_candle(conn, asset_id, venue, interval, alignment_ts)
    if base_candle is None or base_candle.get("close_ts_utc") is None:
        base["outcome_status"] = "NO_BASE_CANDLE"
        base["validation_status"] = "NO_BASE_CANDLE"
        return base

    base_ts = base_candle["close_ts_utc"]
    base_price = as_decimal(base_candle["close_price"])
    base["base_ts_utc"] = base_ts.isoformat(sep="T") if isinstance(base_ts, datetime) else str(base_ts)
    base["base_price"] = str(base_price) if base_price is not None else None
    if base_price is None or base_price <= 0:
        base["outcome_status"] = "INVALID_PRICE"
        base["validation_status"] = "INVALID_PRICE"
        return base

    base_ts_dt = base_ts if isinstance(base_ts, datetime) else parse_ts(str(base_ts))
    if base_ts_dt.tzinfo is None:
        base_ts_dt = base_ts_dt.replace(tzinfo=timezone.utc)

    target_ts = base_ts_dt + timedelta(hours=int(horizon_hours))
    future_candle = fetch_future_candle(conn, asset_id, venue, interval, target_ts)
    if future_candle is None or future_candle.get("close_ts_utc") is None:
        base["outcome_status"] = "NO_FUTURE_CANDLE"
        base["validation_status"] = "NO_FUTURE_CANDLE"
        return base

    future_ts = future_candle["close_ts_utc"]
    future_price = as_decimal(future_candle["close_price"])
    base["future_ts_utc"] = future_ts.isoformat(sep="T") if isinstance(future_ts, datetime) else str(future_ts)
    base["future_price"] = str(future_price) if future_price is not None else None
    if future_price is None:
        base["outcome_status"] = "INVALID_PRICE"
        base["validation_status"] = "INVALID_PRICE"
        return base

    forward_return_pct = ((future_price / base_price) - Decimal("1")) * Decimal("100")
    base["forward_return_pct"] = float(forward_return_pct)

    future_ts_dt = future_ts if isinstance(future_ts, datetime) else parse_ts(str(future_ts))
    if future_ts_dt.tzinfo is None:
        future_ts_dt = future_ts_dt.replace(tzinfo=timezone.utc)

    mfe_row = fetch_mfe_mae(conn, asset_id, venue, interval, base_ts_dt, future_ts_dt)
    if mfe_row and mfe_row.get("max_high") is not None and mfe_row.get("min_low") is not None:
        max_high = as_decimal(mfe_row["max_high"])
        min_low = as_decimal(mfe_row["min_low"])
        if max_high is not None and min_low is not None:
            base["mfe_pct"] = float((max_high / base_price - Decimal("1")) * Decimal("100"))
            base["mae_pct"] = float((min_low / base_price - Decimal("1")) * Decimal("100"))

    base["outcome_status"] = "VALID"
    base["validation_status"] = "VALID"
    return base


def aggregate_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    rets = [r["forward_return_pct"] for r in rows if r.get("forward_return_pct") is not None]
    mfes = [r["mfe_pct"] for r in rows if r.get("mfe_pct") is not None]
    maes = [r["mae_pct"] for r in rows if r.get("mae_pct") is not None]
    n_with_return = len(rets)
    avg_return = sum(rets) / n_with_return if n_with_return else None
    med_return = median(rets) if n_with_return else None
    wins = sum(1 for r in rets if r > 0)
    win_rate = (100.0 * wins / n_with_return) if n_with_return else None
    avg_mfe = sum(mfes) / len(mfes) if mfes else None
    avg_mae = sum(maes) / len(maes) if maes else None
    snapshot_ids = {r["snapshot_pair_id"] for r in rows if r.get("snapshot_pair_id")}
    token_ids = {r["token"] for r in rows if r.get("token")}
    return {
        "n_total": n,
        "n_with_return": n_with_return,
        "avg_return_pct": avg_return,
        "median_return_pct": med_return,
        "win_rate_pct": win_rate,
        "avg_mfe_pct": avg_mfe,
        "avg_mae_pct": avg_mae,
        "snapshot_count": len(snapshot_ids),
        "token_count": len(token_ids),
    }


def build_aggregations(outcome_rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    aggregations: dict[str, Any] = {}
    valid_rows = [r for r in outcome_rows if r.get("outcome_status") == "VALID"]

    for horizon in horizons:
        horizon_rows = [r for r in valid_rows if r["horizon_hours"] == horizon]
        per_horizon: dict[str, Any] = {
            "overall": aggregate_group(horizon_rows),
            "single_field": {},
            "crosses": {},
        }

        for field in SINGLE_FIELD_GROUPS:
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in horizon_rows:
                key = str(row.get(field) or "unknown")
                groups.setdefault(key, []).append(row)
            per_horizon["single_field"][field] = {
                value: aggregate_group(rs) for value, rs in sorted(groups.items())
            }

        for field_a, field_b in CROSS_FIELD_GROUPS:
            cross_key = f"{field_a}__x__{field_b}"
            groups2: dict[str, list[dict[str, Any]]] = {}
            for row in horizon_rows:
                key = f"{row.get(field_a) or 'unknown'}|{row.get(field_b) or 'unknown'}"
                groups2.setdefault(key, []).append(row)
            per_horizon["crosses"][cross_key] = {
                value: aggregate_group(rs) for value, rs in sorted(groups2.items())
            }

        aggregations[f"horizon_{horizon}h"] = per_horizon

    return aggregations


def find_best_worst(aggregations: dict[str, Any], horizons: list[int]) -> dict[str, Any]:
    best_worst: dict[str, Any] = {}
    for horizon in horizons:
        per_horizon = aggregations.get(f"horizon_{horizon}h", {})
        candidates: list[dict[str, Any]] = []
        for field, by_value in per_horizon.get("single_field", {}).items():
            for value, metrics in by_value.items():
                if not metrics["n_with_return"]:
                    continue
                if metrics["n_with_return"] < 2:
                    continue
                candidates.append({
                    "group_type": "single_field",
                    "field": field,
                    "value": value,
                    **metrics,
                })
        for cross, by_value in per_horizon.get("crosses", {}).items():
            for value, metrics in by_value.items():
                if not metrics["n_with_return"]:
                    continue
                if metrics["n_with_return"] < 2:
                    continue
                candidates.append({
                    "group_type": "cross",
                    "field": cross,
                    "value": value,
                    **metrics,
                })
        candidates.sort(
            key=lambda r: (r["avg_return_pct"] if r["avg_return_pct"] is not None else 0.0),
            reverse=True,
        )
        best_worst[f"horizon_{horizon}h"] = {
            "top_positive_groups": candidates[:8],
            "weakest_groups": list(reversed(candidates[-8:])) if len(candidates) >= 8 else list(reversed(candidates)),
        }
    return best_worst


def per_snapshot_coverage(
    outcome_rows: list[dict[str, Any]],
    snapshot_pair_ids: list[str],
    snapshot_meta: dict[str, dict[str, Any]],
    horizons: list[int],
) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for pair_id in snapshot_pair_ids:
        snap_rows = [r for r in outcome_rows if r.get("snapshot_pair_id") == pair_id]
        meta = snapshot_meta.get(pair_id, {})
        by_horizon: dict[str, Any] = {}
        for horizon in horizons:
            h_rows = [r for r in snap_rows if r["horizon_hours"] == horizon]
            status_counts: dict[str, int] = {}
            for r in h_rows:
                s = r.get("outcome_status", "UNKNOWN")
                status_counts[s] = status_counts.get(s, 0) + 1
            valid = sum(1 for r in h_rows if r.get("outcome_status") == "VALID")
            no_future = sum(1 for r in h_rows if r.get("outcome_status") == "NO_FUTURE_CANDLE")
            by_horizon[f"horizon_{horizon}h"] = {
                "total": len(h_rows),
                "valid": valid,
                "no_future_candle": no_future,
                "status_counts": status_counts,
            }
        tokens = sorted({r["token"] for r in snap_rows})
        missing_assets = sorted({r["token"] for r in snap_rows if r.get("outcome_status") == "MISSING_ASSET"})
        coverage[pair_id] = {
            "pair_reference_ts_utc": meta.get("pair_reference_ts_utc"),
            "same_snapshot_ts": meta.get("same_snapshot_ts"),
            "timestamp_mismatch_minutes": meta.get("timestamp_mismatch_minutes"),
            "token_count": len(tokens),
            "tokens": tokens,
            "missing_assets": missing_assets,
            "horizons": by_horizon,
        }
    return coverage


def overall_horizon_coverage(outcome_rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for horizon in horizons:
        h_rows = [r for r in outcome_rows if r["horizon_hours"] == horizon]
        status_counts: dict[str, int] = {}
        for r in h_rows:
            s = r.get("outcome_status", "UNKNOWN")
            status_counts[s] = status_counts.get(s, 0) + 1
        valid = sum(1 for r in h_rows if r.get("outcome_status") == "VALID")
        coverage[f"horizon_{horizon}h"] = {
            "total": len(h_rows),
            "valid": valid,
            "status_counts": status_counts,
        }
    return coverage


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def render_table_summary(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"report={REPORT_NAME} version={PARSER_VERSION}")
    lines.append("scope=research-only market-only account-agnostic")
    lines.append("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    lines.append("selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none")
    lines.append(f"sample_limitation={SAMPLE_LIMITATION}")
    lines.append(f"runtime_promotion_allowed=False")
    lines.append(f"venue={summary['venue']}  interval={summary['interval']}")
    lines.append(f"input_snapshots={summary['input_snapshots']}")
    lines.append(f"input_token_rows={summary['input_token_rows']}")
    lines.append(f"horizons={summary['horizons']}")
    lines.append(f"outcome_rows={summary['outcome_rows']}")
    lines.append("")

    lines.append("--- per-snapshot coverage ---")
    for pair_id, cov in summary["per_snapshot_coverage"].items():
        lines.append(
            f"  {pair_id}: pair_ref={cov['pair_reference_ts_utc']} "
            f"same_ts={cov['same_snapshot_ts']} mismatch_min={cov['timestamp_mismatch_minutes']} "
            f"tokens={cov['token_count']} missing_assets={len(cov.get('missing_assets', []))}"
        )
        for h_key, hcov in cov["horizons"].items():
            lines.append(
                f"    {h_key}: total={hcov['total']} valid={hcov['valid']} "
                f"no_future={hcov['no_future_candle']} status={hcov['status_counts']}"
            )
    lines.append("")

    lines.append("--- overall horizon coverage ---")
    for h_key, cov in summary["overall_coverage"].items():
        lines.append(f"  {h_key}: total={cov['total']} valid={cov['valid']} status={cov['status_counts']}")
    lines.append("")

    lines.append("--- per-horizon overall aggregation ---")
    for horizon in summary["horizons"]:
        agg = summary["aggregations"].get(f"horizon_{horizon}h", {}).get("overall", {})
        n = agg.get("n_with_return")
        avg = agg.get("avg_return_pct")
        wr = agg.get("win_rate_pct")
        mfe = agg.get("avg_mfe_pct")
        mae = agg.get("avg_mae_pct")
        snaps = agg.get("snapshot_count")
        toks = agg.get("token_count")
        lines.append(
            f"  horizon_{horizon}h: n={n} snapshots={snaps} tokens={toks} "
            f"avg_return={_fmt(avg)} win_rate={_fmt(wr)} avg_mfe={_fmt(mfe)} avg_mae={_fmt(mae)}"
        )
    lines.append("")

    lines.append("--- top positive groups (per horizon, min n=2) ---")
    for horizon in summary["horizons"]:
        block = summary["best_worst"].get(f"horizon_{horizon}h", {})
        top = block.get("top_positive_groups", [])[:5]
        lines.append(f"  horizon_{horizon}h:")
        for g in top:
            lines.append(
                f"    {g['group_type']}:{g['field']}={g['value']} "
                f"n={g['n_with_return']} snapshots={g['snapshot_count']} "
                f"avg_return={_fmt(g['avg_return_pct'])} win_rate={_fmt(g['win_rate_pct'])}"
            )
    lines.append("")

    lines.append("--- weakest groups (per horizon, min n=2) ---")
    for horizon in summary["horizons"]:
        block = summary["best_worst"].get(f"horizon_{horizon}h", {})
        bottom = block.get("weakest_groups", [])[:5]
        lines.append(f"  horizon_{horizon}h:")
        for g in bottom:
            lines.append(
                f"    {g['group_type']}:{g['field']}={g['value']} "
                f"n={g['n_with_return']} snapshots={g['snapshot_count']} "
                f"avg_return={_fmt(g['avg_return_pct'])} win_rate={_fmt(g['win_rate_pct'])}"
            )
    lines.append("")

    lines.append(f"wrote_files={summary['wrote_files']}")
    if summary["wrote_files"]:
        for k, v in summary["output_paths"].items():
            lines.append(f"  {k}={v}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    joined_paths = [Path(p) for p in args.joined_paths]
    horizons = sorted(set(int(h) for h in args.horizons))
    out_dir = Path(args.output_dir)

    output_paths = {
        "label_outcomes_jsonl": str(out_dir / "label_outcomes_multi_snapshot_v1.jsonl"),
        "validation_summary_json": str(out_dir / "validation_summary_multi_snapshot_v1.json"),
    }

    # Load all joined rows and tag each with its snapshot_pair_id and source path.
    all_joined: list[dict[str, Any]] = []
    snapshot_pair_ids: list[str] = []
    snapshot_meta: dict[str, dict[str, Any]] = {}

    for path in joined_paths:
        if not path.exists():
            print(f"ERROR: joined path not found: {path}")
            return 2
        pair_id = pair_id_from_path(path)
        rows = load_joined(path)
        if not rows:
            print(f"ERROR: joined file is empty: {path}")
            return 2
        first = rows[0]
        snapshot_meta[pair_id] = {
            "pair_reference_ts_utc": first.get("pair_reference_ts_utc") or first.get("prediction_ts_utc"),
            "same_snapshot_ts": first.get("same_snapshot_ts"),
            "timestamp_mismatch_minutes": first.get("timestamp_mismatch_minutes"),
            "timestamp_mismatch_allowed": first.get("timestamp_mismatch_allowed"),
            "source_path": str(path),
        }
        for row in rows:
            row["_source_path"] = str(path)
        snapshot_pair_ids.append(pair_id)
        all_joined.extend([(pair_id, row) for row in rows])

    # Collect all tokens across all snapshots.
    all_tokens = sorted({str(r["token"]).upper() for _, r in all_joined})
    input_token_rows = len(all_joined)

    conn = get_connection()
    try:
        asset_map = fetch_asset_map(conn, all_tokens)

        outcome_rows: list[dict[str, Any]] = []
        for pair_id, joined_row in all_joined:
            token = str(joined_row["token"]).upper()
            asset_id = asset_map.get(token)
            alignment_ts = resolve_alignment_ts(joined_row)
            for horizon in horizons:
                outcome_rows.append(
                    compute_outcome_row(
                        conn,
                        joined_row,
                        pair_id,
                        asset_id,
                        str(args.venue),
                        str(args.interval),
                        alignment_ts,
                        horizon,
                    )
                )
    finally:
        conn.close()

    overall_cov = overall_horizon_coverage(outcome_rows, horizons)
    snap_cov = per_snapshot_coverage(outcome_rows, snapshot_pair_ids, snapshot_meta, horizons)
    aggregations = build_aggregations(outcome_rows, horizons)
    best_worst = find_best_worst(aggregations, horizons)

    tokens_missing_asset = sorted([t for t in all_tokens if t not in asset_map])

    summary: dict[str, Any] = {
        "report": REPORT_NAME,
        "parser_version": PARSER_VERSION,
        "scope": "research-only market-only account-agnostic",
        "sample_limitation": SAMPLE_LIMITATION,
        "runtime_promotion_allowed": False,
        "venue": str(args.venue),
        "interval": str(args.interval),
        "horizons": horizons,
        "input_snapshots": len(snapshot_pair_ids),
        "snapshot_pair_ids": snapshot_pair_ids,
        "snapshot_meta": snapshot_meta,
        "input_token_rows": input_token_rows,
        "all_tokens": all_tokens,
        "tokens_missing_asset": tokens_missing_asset,
        "outcome_rows": len(outcome_rows),
        "overall_coverage": overall_cov,
        "per_snapshot_coverage": snap_cov,
        "aggregations": aggregations,
        "best_worst": best_worst,
        "output_paths": output_paths,
        "wrote_files": bool(args.write_files),
        "safety_markers": {
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "db_writes": 0,
            "selection_engine_changes": 0,
            "advice_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
            "paper_live_logic": "not_allowed",
            "account_state": "not_allowed",
            "research_only": True,
            "market_only": True,
            "account_agnostic": True,
        },
    }

    if args.write_files:
        write_jsonl(Path(output_paths["label_outcomes_jsonl"]), outcome_rows)
        write_json(Path(output_paths["validation_summary_json"]), summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(render_table_summary(summary))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
