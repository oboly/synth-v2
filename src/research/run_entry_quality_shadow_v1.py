from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.research.entry_quality_shadow_v1 import (
    EntryQualityInput,
    compute_entry_quality_shadow,
    compute_entry_strength,
)
from src.selection.run_selection_engine_v2 import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_ENGINE_NAME,
    DEFAULT_ENGINE_VERSION,
    fetch_selection_candidates,
)
from src.selection.selection_engine_v2 import load_selection_config, rank_candidates


CQ_MODEL_VERSION = "cq_shadow_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute CQ / Entry Strength shadow observations without changing live ranking"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--ppp-csv", default=None)
    parser.add_argument("--out-csv", default=None)
    parser.add_argument("--write-db", action="store_true")
    return parser.parse_args()


def _load_ppp_csv(path: str | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}

    out: dict[str, dict[str, str]] = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "ppp_pct", "ppp_kind", "ppp_source_ref"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError(
                "PPP CSV requires symbol,ppp_pct,ppp_kind,ppp_source_ref columns"
            )
        for row in reader:
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                continue
            out[symbol] = {key: str(row.get(key) or "").strip() for key in required}
    return out


def _ppp_for_symbol(
    ppp_by_symbol: dict[str, dict[str, str]], symbol: str
) -> tuple[Decimal | None, str | None, str | None]:
    raw = ppp_by_symbol.get(symbol)
    if raw is None:
        return None, None, None

    ppp_kind = raw.get("ppp_kind") or None
    source_ref = raw.get("ppp_source_ref") or None
    if not ppp_kind or not source_ref:
        return None, ppp_kind, source_ref

    ppp_text = raw.get("ppp_pct") or ""
    if not ppp_text:
        return None, ppp_kind, source_ref

    return Decimal(ppp_text), ppp_kind, source_ref


def build_shadow_rows(
    *,
    selection_rows,
    ppp_by_symbol: dict[str, dict[str, str]],
    run_asof_ts_utc: datetime,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for row in selection_rows:
        shadow = compute_entry_quality_shadow(
            EntryQualityInput(
                trade_quality_score=row.trade_quality_score,
                timing_refinement_score=row.timing_refinement_score,
                quality_penalty=row.quality_penalty,
                quality_status_1d=row.quality_status_1d,
                quality_status_4h=row.quality_status_4h,
                quality_status_1h=row.quality_status_1h,
            )
        )

        ppp_pct, ppp_kind, ppp_source_ref = _ppp_for_symbol(ppp_by_symbol, row.symbol)
        entry_strength = compute_entry_strength(
            ppp_pct=ppp_pct,
            entry_quality_score=shadow.entry_quality_score,
        )

        out.append(
            {
                "asset_id": row.asset_id,
                "symbol": row.symbol,
                "venue": row.venue,
                "asof_ts_utc": run_asof_ts_utc,
                "selection_engine_name": DEFAULT_ENGINE_NAME,
                "selection_engine_version": DEFAULT_ENGINE_VERSION,
                "cq_model_version": shadow.model_version,
                "trade_quality_score": row.trade_quality_score,
                "timing_refinement_score": row.timing_refinement_score,
                "quality_penalty": row.quality_penalty,
                "quality_status_1d": row.quality_status_1d,
                "quality_status_4h": row.quality_status_4h,
                "quality_status_1h": row.quality_status_1h,
                "entry_quality_score": shadow.entry_quality_score,
                "entry_quality_state": shadow.entry_quality_state,
                "reasons_json": json.dumps(shadow.reasons),
                "blockers_json": json.dumps(shadow.blockers),
                "ppp_pct": ppp_pct,
                "ppp_kind": ppp_kind,
                "ppp_source_ref": ppp_source_ref,
                "entry_strength": entry_strength,
            }
        )

    return out


def write_shadow_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO research_entry_quality_shadow (
        asset_id,
        venue,
        asof_ts_utc,
        selection_engine_name,
        selection_engine_version,
        cq_model_version,
        trade_quality_score,
        timing_refinement_score,
        quality_penalty,
        quality_status_1d,
        quality_status_4h,
        quality_status_1h,
        entry_quality_score,
        entry_quality_state,
        reasons_json,
        blockers_json,
        ppp_pct,
        ppp_kind,
        ppp_source_ref,
        entry_strength
    ) VALUES (
        %(asset_id)s,
        %(venue)s,
        %(asof_ts_utc)s,
        %(selection_engine_name)s,
        %(selection_engine_version)s,
        %(cq_model_version)s,
        %(trade_quality_score)s,
        %(timing_refinement_score)s,
        %(quality_penalty)s,
        %(quality_status_1d)s,
        %(quality_status_4h)s,
        %(quality_status_1h)s,
        %(entry_quality_score)s,
        %(entry_quality_state)s,
        %(reasons_json)s,
        %(blockers_json)s,
        %(ppp_pct)s,
        %(ppp_kind)s,
        %(ppp_source_ref)s,
        %(entry_strength)s
    )
    ON DUPLICATE KEY UPDATE
        trade_quality_score = VALUES(trade_quality_score),
        timing_refinement_score = VALUES(timing_refinement_score),
        quality_penalty = VALUES(quality_penalty),
        quality_status_1d = VALUES(quality_status_1d),
        quality_status_4h = VALUES(quality_status_4h),
        quality_status_1h = VALUES(quality_status_1h),
        entry_quality_score = VALUES(entry_quality_score),
        entry_quality_state = VALUES(entry_quality_state),
        reasons_json = VALUES(reasons_json),
        blockers_json = VALUES(blockers_json),
        ppp_pct = VALUES(ppp_pct),
        ppp_kind = VALUES(ppp_kind),
        ppp_source_ref = VALUES(ppp_source_ref),
        entry_strength = VALUES(entry_strength)
    """

    db_rows = [{k: v for k, v in row.items() if k != "symbol"} for row in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, db_rows)
    conn.commit()
    return len(db_rows)


def write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output.write_text("", encoding="utf-8")
        return

    serialized: list[dict[str, Any]] = []
    for row in rows:
        serialized.append(
            {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in row.items()
            }
        )

    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(serialized[0].keys()))
        writer.writeheader()
        writer.writerows(serialized)


def run(args: argparse.Namespace) -> int:
    conn = get_db_connection()
    try:
        config = load_selection_config(args.config)
        candidates = fetch_selection_candidates(
            conn,
            venue=args.venue,
            asset_id=args.asset_id,
            limit=args.limit,
        )
        selection_rows = rank_candidates(candidates, config)
        ppp_by_symbol = _load_ppp_csv(args.ppp_csv)
        run_asof = datetime.now(UTC)
        rows = build_shadow_rows(
            selection_rows=selection_rows,
            ppp_by_symbol=ppp_by_symbol,
            run_asof_ts_utc=run_asof,
        )

        if args.out_csv:
            write_csv(args.out_csv, rows)

        if args.write_db:
            written = write_shadow_rows(conn, rows)
            print(f"SHADOW_DB_ROWS_WRITTEN={written}")
        else:
            print("SHADOW_DB_ROWS_WRITTEN=0")

        print(f"SHADOW_ROWS={len(rows)}")
        print(f"CQ_MODEL_VERSION={CQ_MODEL_VERSION}")
        print(f"ENTRY_STRENGTH_POPULATED={sum(row['entry_strength'] is not None for row in rows)}")
        print("PRODUCTION_RANKING_CHANGED=0")
        return len(rows)
    finally:
        conn.close()


def main() -> None:
    args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
