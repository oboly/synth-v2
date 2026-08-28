from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime
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


RUNNER_NAME = "entry_quality_shadow_v1"
CQ_MODEL_VERSION = "cq_shadow_v1"
DEFAULT_OUTPUT_CSV = "data/research/entry_quality_shadow_v1/entry_quality_shadow_v1.csv"
ALLOWED_PPP_KINDS = {"PLANNING_PPP", "ACTIONABLE_PPP"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute CQ / Entry Strength shadow observations without changing live ranking"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--ppp-csv", default=None)
    parser.add_argument("--out-csv", default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--write-db", action="store_true")
    return parser.parse_args(argv)


def _load_ppp_csv(path: str | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}

    out: dict[str, dict[str, str]] = {}
    kinds_seen: set[str] = set()
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

            normalized = {key: str(row.get(key) or "").strip() for key in required}
            ppp_kind = normalized["ppp_kind"]
            if ppp_kind not in ALLOWED_PPP_KINDS:
                raise ValueError(
                    f"Unsupported ppp_kind={ppp_kind!r}; expected one of {sorted(ALLOWED_PPP_KINDS)}"
                )
            if not normalized["ppp_pct"] or not normalized["ppp_source_ref"]:
                raise ValueError(f"PPP CSV row for {symbol} is missing value or provenance")

            kinds_seen.add(ppp_kind)
            if len(kinds_seen) > 1:
                raise ValueError(
                    "PPP CSV must contain exactly one PPP kind per run; do not mix Planning and Actionable PPP"
                )

            out[symbol] = normalized
    return out


def _ppp_for_symbol(
    ppp_by_symbol: dict[str, dict[str, str]], symbol: str
) -> tuple[Decimal | None, str | None, str | None]:
    raw = ppp_by_symbol.get(symbol)
    if raw is None:
        return None, None, None

    ppp_kind = raw["ppp_kind"]
    source_ref = raw["ppp_source_ref"]
    return Decimal(raw["ppp_pct"]), ppp_kind, source_ref


def _source_asof(row) -> str | datetime:
    if row.asof_ts_utc is None:
        raise ValueError(f"Missing canonical source as-of timestamp for {row.symbol}")
    return row.asof_ts_utc


def build_shadow_rows(
    *,
    selection_rows,
    ppp_by_symbol: dict[str, dict[str, str]],
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
                "asof_ts_utc": _source_asof(row),
                "selection_engine_name": DEFAULT_ENGINE_NAME,
                "selection_engine_version": DEFAULT_ENGINE_VERSION,
                "cq_model_version": shadow.model_version,
                "trade_quality_score": row.trade_quality_score,
                "selection_score": row.selection_score,
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
        selection_score,
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
        %(selection_score)s,
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
        selection_score = VALUES(selection_score),
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
    mode = "shadow-db" if args.write_db else "shadow-csv"
    started = time.perf_counter()
    print(
        f"STARTED runner={RUNNER_NAME} mode={mode} scope=selection-candidates workers=1",
        flush=True,
    )
    print(
        "SAFETY research_only=1 shadow_only=1 broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0 selection_ranking_changes=0 "
        "decision_gate=none execution_planner=none executor=none",
        flush=True,
    )

    conn = None
    try:
        conn = get_db_connection()
        config = load_selection_config(args.config)

        phase_started = time.perf_counter()
        print(
            f"PHASE_START name=fetch_selection_candidates venue={args.venue} limit={args.limit}",
            flush=True,
        )
        candidates = fetch_selection_candidates(
            conn,
            venue=args.venue,
            asset_id=args.asset_id,
            limit=args.limit,
        )
        selection_rows = rank_candidates(candidates, config)
        print(
            f"PHASE_END name=fetch_selection_candidates candidates={len(candidates)} "
            f"rows={len(selection_rows)} elapsed_s={time.perf_counter() - phase_started:.3f}",
            flush=True,
        )

        phase_started = time.perf_counter()
        print("PHASE_START name=build_shadow", flush=True)
        ppp_by_symbol = _load_ppp_csv(args.ppp_csv)
        rows = build_shadow_rows(
            selection_rows=selection_rows,
            ppp_by_symbol=ppp_by_symbol,
        )
        populated = sum(row["entry_strength"] is not None for row in rows)
        print(
            f"PHASE_END name=build_shadow rows={len(rows)} entry_strength_populated={populated} "
            f"elapsed_s={time.perf_counter() - phase_started:.3f}",
            flush=True,
        )

        phase_started = time.perf_counter()
        print(f"PHASE_START name=write_csv path={args.out_csv}", flush=True)
        write_csv(args.out_csv, rows)
        print(
            f"PHASE_END name=write_csv rows={len(rows)} "
            f"elapsed_s={time.perf_counter() - phase_started:.3f}",
            flush=True,
        )

        written = 0
        if args.write_db:
            phase_started = time.perf_counter()
            print("PHASE_START name=write_db table=research_entry_quality_shadow", flush=True)
            written = write_shadow_rows(conn, rows)
            print(
                f"PHASE_END name=write_db rows={written} "
                f"elapsed_s={time.perf_counter() - phase_started:.3f}",
                flush=True,
            )

        print(
            f"FINISHED runner={RUNNER_NAME} mode={mode} rows={len(rows)} "
            f"db_rows_written={written} csv={args.out_csv} "
            f"entry_strength_populated={populated} production_ranking_changed=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}",
            flush=True,
        )
        return 0
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(
            f"FAILED runner={RUNNER_NAME} mode={mode} "
            f"reason={type(exc).__name__}:{exc} db_writes=0 "
            f"elapsed_s={time.perf_counter() - started:.3f}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
