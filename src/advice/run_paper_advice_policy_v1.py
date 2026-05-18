from __future__ import annotations

import argparse
import glob
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.advice.paper_advice_policy_v1 import (
    POLICY_NAME,
    POLICY_VERSION,
    classify_aplus_table1,
    evaluate_paper_advice,
)


TABLE_NAME = "paper_advice_observation"


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _latest_file(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file matched pattern: {pattern}")
    return Path(matches[-1])


def _parse_aplus_prediction_ts(text: str) -> str | None:
    m = re.search(r"prediction_ts_utc\s*=\s*([0-9T:\-]+Z)", text)
    if not m:
        return None
    return m.group(1)



def fetch_latest_aplus_table1_db() -> tuple[str | None, dict[str, dict[str, str]]]:
    """Fetch latest normalized A+ Table 1 snapshot from DB.

    Raw A+ files are archive/audit material. Runtime paper advice should consume
    normalized DB rows so parsing rules are centralized in the A+ loader.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    aplus_table1_report_id,
                    source_file_path,
                    prediction_ts_utc,
                    parser_version,
                    row_count
                FROM aplus_table1_report
                WHERE row_count > 0
                ORDER BY prediction_ts_utc DESC, aplus_table1_report_id DESC
                LIMIT 1
                """
            )
            report = cur.fetchone()

            if not report:
                return None, {}

            report_id = int(report["aplus_table1_report_id"])

            cur.execute(
                """
                SELECT
                    token,
                    phase,
                    coherence,
                    field,
                    geometry,
                    structural_role,
                    expansion_quality,
                    anchor_strength,
                    strategic_bias,
                    notes
                FROM aplus_table1_row
                WHERE aplus_table1_report_id = %s
                  AND validation_status = 'VALID'
                ORDER BY token
                """,
                (report_id,),
            )
            db_rows = list(cur.fetchall())

    finally:
        conn.close()

    rows: dict[str, dict[str, str]] = {}
    for raw in db_rows:
        token = str(raw["token"]).upper()
        rows[token] = {
            "token": token,
            "phase": str(raw.get("phase") or "").lower(),
            "coherence": str(raw.get("coherence") or "").lower(),
            "field": str(raw.get("field") or "").lower(),
            "geometry": str(raw.get("geometry") or "").lower(),
            "structural_role": str(raw.get("structural_role") or "").lower(),
            "expansion_quality": str(raw.get("expansion_quality") or "").lower(),
            "anchor_strength": str(raw.get("anchor_strength") or "").lower(),
            "strategic_bias": str(raw.get("strategic_bias") or "").lower(),
            "notes": str(raw.get("notes") or ""),
        }

    prediction_ts = report.get("prediction_ts_utc")
    prediction_ts_text = None if prediction_ts is None else str(prediction_ts)

    return prediction_ts_text, rows


def parse_aplus_table1(path: Path) -> tuple[str | None, dict[str, dict[str, str]]]:
    path_text = str(path)
    if path_text in {"db:/latest", "db://latest", "DB_LATEST_APLUS_TABLE1"}:
        return fetch_latest_aplus_table1_db()

    text = path.read_text(encoding="utf-8")
    prediction_ts = _parse_aplus_prediction_ts(text)

    allowed_phase = {"early", "forming", "confirmed", "late", "exhaustion", "reset", "neutral"}
    rows: dict[str, dict[str, str]] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Generated ") or line.startswith("Note:"):
            continue
        if line.startswith("TABLE ") or line.startswith("TOKEN "):
            continue

        parts = line.split()
        if len(parts) < 9:
            continue

        token = parts[0].upper()
        phase = parts[1].lower()

        if phase not in allowed_phase:
            continue

        rows[token] = {
            "token": token,
            "phase": parts[1].lower(),
            "coherence": parts[2].lower(),
            "field": parts[3].lower(),
            "geometry": parts[4].lower(),
            "structural_role": parts[5].lower(),
            "expansion_quality": parts[6].lower(),
            "anchor_strength": parts[7].lower(),
            "strategic_bias": parts[8].lower(),
            "notes": " ".join(parts[9:]),
        }

    return prediction_ts, rows


def fetch_latest_inputs(conn: Any, venue: str, interval_code: str, limit: int | None) -> list[dict[str, Any]]:
    sql = """
    WITH latest_selection AS (
        SELECT MAX(asof_ts_utc) AS asof_ts_utc
        FROM selection_state
        WHERE venue = %(venue)s
    ),
    latest_policy AS (
        SELECT MAX(asof_ts_utc) AS asof_ts_utc
        FROM trade_setup_policy_preview_observation
        WHERE venue = %(venue)s
    ),
    latest_zone AS (
        SELECT MAX(asof_ts_utc) AS asof_ts_utc
        FROM execution_zone_context
        WHERE venue = %(venue)s
          AND interval_code = %(interval_code)s
    )
    SELECT
        s.asset_id,
        a.symbol,
        s.venue,
        s.asof_ts_utc,
        s.selection_state,
        s.selection_bias,
        s.selection_score,
        s.priority_rank,

        f.setup_filter_state,
        f.setup_filter_reason,
        f.target_horizon AS current_target_horizon,

        p.policy_decision,
        p.suggested_horizon,
        p.allowed_now,
        p.policy_reason,

        z.asof_ts_utc AS zone_asof_ts_utc,
        z.leg_direction,
        z.entry_zone_low,
        z.entry_zone_high,
        z.entry_zone_type,
        z.tp_zone_low,
        z.tp_zone_high,
        z.tp_zone_type,
        z.invalidation_price,
        z.zone_confidence_score,
        z.zone_alignment_score

    FROM selection_state s
    JOIN latest_selection ls
      ON ls.asof_ts_utc = s.asof_ts_utc
    JOIN asset a
      ON a.asset_id = s.asset_id

    LEFT JOIN trade_setup_filter_observation f
      ON f.asset_id = s.asset_id
     AND f.venue = s.venue
     AND f.asof_ts_utc = s.asof_ts_utc
     AND f.filter_name = 'trade_setup_filter_v1'
     AND f.filter_version = '1.1'
     AND f.asset_suitability_mode = 'candidate_weak_set'

    LEFT JOIN latest_policy lp
      ON 1 = 1
    LEFT JOIN trade_setup_policy_preview_observation p
      ON p.asset_id = s.asset_id
     AND p.venue = s.venue
     AND p.asof_ts_utc = lp.asof_ts_utc

    LEFT JOIN latest_zone lz
      ON 1 = 1
    LEFT JOIN vw_paper_advice_execution_zone_context_v1 z
      ON z.asset_id = s.asset_id
     AND z.venue = s.venue
     AND z.interval_code = %(interval_code)s
     AND z.asof_ts_utc = lz.asof_ts_utc

    WHERE s.venue = %(venue)s

    ORDER BY
        s.priority_rank IS NULL,
        s.priority_rank ASC,
        s.selection_score DESC,
        a.symbol ASC
    """

    params: dict[str, Any] = {
        "venue": venue,
        "interval_code": interval_code,
    }

    if limit is not None:
        sql += "\nLIMIT %(limit)s"
        params["limit"] = int(limit)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _allowed_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if str(value).strip().upper() in {"1", "Y", "YES", "TRUE", "ALLOW", "ALLOWED"} else 0


def build_output_rows(
    rows: list[dict[str, Any]],
    aplus_rows: dict[str, dict[str, str]],
    interval_code: str,
    aplus_raw_path: Path,
    aplus_prediction_ts: str | None,
) -> list[dict[str, Any]]:
    now = datetime.now(UTC).replace(tzinfo=None)
    out: list[dict[str, Any]] = []

    for row in rows:
        symbol = str(row["symbol"]).upper()
        aplus = aplus_rows.get(symbol)
        aplus_bucket = classify_aplus_table1(aplus)
        advice = evaluate_paper_advice(row, aplus_bucket)

        source_ref = {
            "selection_asof_ts_utc": str(row.get("asof_ts_utc")),
            "zone_asof_ts_utc": str(row.get("zone_asof_ts_utc")),
            "aplus_raw_path": str(aplus_raw_path),
            "aplus_prediction_ts_utc": aplus_prediction_ts,
            "policy_reason": row.get("policy_reason"),
        }

        out.append(
            {
                "policy_name": POLICY_NAME,
                "policy_version": POLICY_VERSION,
                "asset_id": int(row["asset_id"]),
                "symbol": symbol,
                "venue": str(row["venue"]),
                "interval_code": interval_code,
                "asof_ts_utc": row["asof_ts_utc"],
                "context_ts_utc": now,

                "selection_state": row.get("selection_state"),
                "selection_bias": row.get("selection_bias"),
                "selection_score": _to_decimal(row.get("selection_score")),
                "priority_rank": row.get("priority_rank"),

                "setup_filter_state": row.get("setup_filter_state"),
                "setup_filter_reason": row.get("setup_filter_reason"),
                "current_target_horizon": row.get("current_target_horizon"),
                "policy_decision": row.get("policy_decision"),
                "suggested_horizon": row.get("suggested_horizon"),
                "allowed_now": _allowed_int(row.get("allowed_now")),

                "aplus_bucket": aplus_bucket,
                "aplus_phase": None if not aplus else aplus.get("phase"),
                "aplus_coherence": None if not aplus else aplus.get("coherence"),
                "aplus_field": None if not aplus else aplus.get("field"),
                "aplus_geometry": None if not aplus else aplus.get("geometry"),
                "aplus_structural_role": None if not aplus else aplus.get("structural_role"),
                "aplus_expansion_quality": None if not aplus else aplus.get("expansion_quality"),
                "aplus_anchor_strength": None if not aplus else aplus.get("anchor_strength"),
                "aplus_strategic_bias": None if not aplus else aplus.get("strategic_bias"),

                "leg_direction": row.get("leg_direction"),
                "entry_zone_low": _to_decimal(row.get("entry_zone_low")),
                "entry_zone_high": _to_decimal(row.get("entry_zone_high")),
                "entry_zone_type": row.get("entry_zone_type"),
                "tp_zone_low": _to_decimal(row.get("tp_zone_low")),
                "tp_zone_high": _to_decimal(row.get("tp_zone_high")),
                "tp_zone_type": row.get("tp_zone_type"),
                "invalidation_price": _to_decimal(row.get("invalidation_price")),
                "zone_confidence_score": _to_decimal(row.get("zone_confidence_score")),
                "zone_alignment_score": _to_decimal(row.get("zone_alignment_score")),

                "advice_state": advice.advice_state,
                "advice_action": advice.advice_action,
                "confidence_score": advice.confidence_score,
                "risk_label": advice.risk_label,

                "reason_codes_json": json.dumps(advice.reason_codes, ensure_ascii=False),
                "source_ref_json": json.dumps(source_ref, ensure_ascii=False, default=_json_default),
            }
        )

    return out


def write_rows(conn: Any, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    columns = [
        "policy_name",
        "policy_version",
        "asset_id",
        "symbol",
        "venue",
        "interval_code",
        "asof_ts_utc",
        "context_ts_utc",
        "selection_state",
        "selection_bias",
        "selection_score",
        "priority_rank",
        "setup_filter_state",
        "setup_filter_reason",
        "current_target_horizon",
        "policy_decision",
        "suggested_horizon",
        "allowed_now",
        "aplus_bucket",
        "aplus_phase",
        "aplus_coherence",
        "aplus_field",
        "aplus_geometry",
        "aplus_structural_role",
        "aplus_expansion_quality",
        "aplus_anchor_strength",
        "aplus_strategic_bias",
        "leg_direction",
        "entry_zone_low",
        "entry_zone_high",
        "entry_zone_type",
        "tp_zone_low",
        "tp_zone_high",
        "tp_zone_type",
        "invalidation_price",
        "zone_confidence_score",
        "zone_alignment_score",
        "advice_state",
        "advice_action",
        "confidence_score",
        "risk_label",
        "reason_codes_json",
        "source_ref_json",
    ]

    placeholders = ", ".join(f"%({c})s" for c in columns)
    col_sql = ", ".join(columns)
    updates = ", ".join(
        f"{c} = VALUES({c})"
        for c in columns
        if c not in {"policy_name", "policy_version", "venue", "interval_code", "asof_ts_utc", "asset_id"}
    )

    sql = f"""
    INSERT INTO {TABLE_NAME} ({col_sql})
    VALUES ({placeholders})
    ON DUPLICATE KEY UPDATE
        {updates},
        updated_ts_utc = CURRENT_TIMESTAMP(6)
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


def print_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "rank",
        "symbol",
        "selection",
        "setup",
        "policy",
        "A+",
        "advice",
        "action",
        "conf",
        "risk",
        "entry",
        "tp",
        "invalidation",
    ]

    printable: list[list[str]] = []
    for row in rows:
        entry = ""
        if row.get("entry_zone_low") is not None and row.get("entry_zone_high") is not None:
            entry = f"{row['entry_zone_low']}..{row['entry_zone_high']}"

        tp = ""
        if row.get("tp_zone_low") is not None and row.get("tp_zone_high") is not None:
            tp = f"{row['tp_zone_low']}..{row['tp_zone_high']}"

        printable.append(
            [
                "" if row.get("priority_rank") is None else str(row.get("priority_rank")),
                str(row.get("symbol", "")),
                str(row.get("selection_state") or ""),
                str(row.get("setup_filter_state") or ""),
                str(row.get("policy_decision") or ""),
                str(row.get("aplus_bucket") or ""),
                str(row.get("advice_state") or ""),
                str(row.get("advice_action") or ""),
                str(row.get("confidence_score") or ""),
                str(row.get("risk_label") or ""),
                entry,
                tp,
                "" if row.get("invalidation_price") is None else str(row.get("invalidation_price")),
            ]
        )

    widths = [len(h) for h in headers]
    for row in printable:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))

    def fmt(row: list[str]) -> str:
        return " | ".join(value.ljust(widths[i]) for i, value in enumerate(row))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for row in printable:
        print(fmt(row))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run market-only paper advice policy v1.")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument(
        "--aplus-raw",
        default="db://latest",
        help="A+ Table 1 source. Default db://latest reads normalized DB rows; raw file path/glob remains legacy fallback.",
    )
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json", "none"), default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    aplus_path = Path(args.aplus_raw)
    if any(ch in args.aplus_raw for ch in "*?[]"):
        aplus_path = _latest_file(args.aplus_raw)

    aplus_prediction_ts, aplus_rows = parse_aplus_table1(aplus_path)

    conn = get_connection()
    try:
        input_rows = fetch_latest_inputs(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            limit=args.limit,
        )
        output_rows = build_output_rows(
            input_rows,
            aplus_rows=aplus_rows,
            interval_code=args.interval,
            aplus_raw_path=aplus_path,
            aplus_prediction_ts=aplus_prediction_ts,
        )

        written = 0
        if args.write_db:
            written = write_rows(conn, output_rows)

    finally:
        conn.close()

    print(f"report={POLICY_NAME} version={POLICY_VERSION}")
    print("scope=market-only account-agnostic paper-navigation")
    print("broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print("decision_gate=none execution_planner=none executor=none")
    print(f"venue={args.venue} interval={args.interval}")
    print(f"aplus_raw={aplus_path}")
    print(f"aplus_prediction_ts_utc={aplus_prediction_ts}")
    print(f"aplus_rows={len(aplus_rows)} input_rows={len(input_rows)} output_rows={len(output_rows)} db_written={written}")
    print()

    states: dict[str, int] = {}
    for row in output_rows:
        states[str(row["advice_state"])] = states.get(str(row["advice_state"]), 0) + 1

    print("--- advice state counts ---")
    for state, count in sorted(states.items(), key=lambda item: (-item[1], item[0])):
        print(f"{state}={count}")

    if args.output == "table":
        print()
        print("--- paper advice ---")
        print_table(output_rows)
    elif args.output == "json":
        print(json.dumps(output_rows, indent=2, ensure_ascii=False, default=_json_default))

    print()
    print("[DONE] broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
