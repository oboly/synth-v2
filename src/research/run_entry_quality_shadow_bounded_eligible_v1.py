from __future__ import annotations

import argparse
import signal
import time
from typing import Any

from src.common.db import get_db_connection
from src.research.run_entry_quality_shadow_bounded_v1 import (
    RUNNER_NAME as BASE_RUNNER_NAME,
    _Interrupted,
    fetch_bounded_evidence_timestamps,
    fetch_bounded_selection_candidates,
)
from src.research.run_entry_quality_shadow_v1 import (
    DEFAULT_OUTPUT_CSV,
    EVIDENCE_FIELDS,
    _load_ppp_csv,
    build_shadow_rows,
    write_csv,
    write_shadow_rows,
)
from src.selection.run_selection_engine_v2 import DEFAULT_CONFIG_PATH
from src.selection.selection_engine_v2 import load_selection_config, rank_candidates

RUNNER_NAME = "entry_quality_shadow_bounded_eligible_v1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded research-only CQ shadow population runner with explicit evidence eligibility"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--asset-id", type=int, default=None)
    parser.add_argument("--ppp-csv", default=None)
    parser.add_argument("--out-csv", default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--write-db", action="store_true")
    return parser.parse_args(argv)


def split_evidence_eligible(
    selection_rows: list[Any],
    evidence_by_asset: dict[int, dict[str, str | None]],
) -> tuple[list[Any], list[dict[str, Any]]]:
    eligible: list[Any] = []
    excluded: list[dict[str, Any]] = []
    for row in selection_rows:
        evidence = evidence_by_asset.get(row.asset_id)
        missing = (
            list(EVIDENCE_FIELDS)
            if evidence is None
            else [field for field in EVIDENCE_FIELDS if evidence.get(field) is None]
        )
        if missing:
            excluded.append(
                {
                    "asset_id": row.asset_id,
                    "symbol": row.symbol,
                    "missing_evidence": tuple(missing),
                }
            )
        else:
            eligible.append(row)
    return eligible, excluded


def run(args: argparse.Namespace) -> int:
    mode = "shadow-db" if args.write_db else "shadow-csv"
    started = time.perf_counter()
    print(
        f"STARTED runner={RUNNER_NAME} base_runner={BASE_RUNNER_NAME} mode={mode} bounded_assets=1 workers=1",
        flush=True,
    )
    print(
        "SAFETY research_only=1 shadow_only=1 broker_private_calls=0 broker_writes=0 "
        "order_submission=0 live_orders=0 selection_ranking_changes=0 decision_gate=none "
        "execution_planner=none executor=none",
        flush=True,
    )

    conn = None
    previous_handlers: dict[int, Any] = {}

    def _handle_signal(signum: int, _frame: Any) -> None:
        raise _Interrupted(signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_signal)

        conn = get_db_connection()
        config = load_selection_config(args.config)

        phase = time.perf_counter()
        print(
            f"PHASE_START name=fetch_bounded_selection_candidates venue={args.venue} "
            f"asset_id={args.asset_id if args.asset_id is not None else 'ALL'} limit={args.limit}",
            flush=True,
        )
        candidates = fetch_bounded_selection_candidates(
            conn, venue=args.venue, asset_id=args.asset_id, limit=args.limit
        )
        print(
            f"PHASE_END name=fetch_bounded_selection_candidates rows={len(candidates)} "
            f"elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        phase = time.perf_counter()
        print(f"PHASE_START name=rank_candidates input_rows={len(candidates)}", flush=True)
        selection_rows = rank_candidates(candidates, config)
        print(
            f"PHASE_END name=rank_candidates rows={len(selection_rows)} "
            f"elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        phase = time.perf_counter()
        print(
            f"PHASE_START name=fetch_bounded_evidence_timestamps assets={len(selection_rows)}",
            flush=True,
        )
        evidence = fetch_bounded_evidence_timestamps(
            conn, venue=args.venue, asset_ids=[row.asset_id for row in selection_rows]
        )
        print(
            f"PHASE_END name=fetch_bounded_evidence_timestamps rows={len(evidence)} "
            f"elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        eligible_rows, excluded = split_evidence_eligible(selection_rows, evidence)
        missing_counts: dict[str, int] = {}
        for item in excluded:
            for field in item["missing_evidence"]:
                missing_counts[field] = missing_counts.get(field, 0) + 1
        missing_summary = ",".join(
            f"{field}:{missing_counts[field]}" for field in sorted(missing_counts)
        ) or "none"
        print(
            f"ELIGIBILITY total={len(selection_rows)} eligible={len(eligible_rows)} "
            f"excluded_missing_evidence={len(excluded)} missing_by_field={missing_summary}",
            flush=True,
        )
        for item in excluded:
            print(
                f"EXCLUDED asset_id={item['asset_id']} symbol={item['symbol']} "
                f"reason=MISSING_CANONICAL_EVIDENCE fields={','.join(item['missing_evidence'])}",
                flush=True,
            )

        phase = time.perf_counter()
        print(f"PHASE_START name=build_shadow rows={len(eligible_rows)}", flush=True)
        rows = build_shadow_rows(
            selection_rows=eligible_rows,
            ppp_by_symbol=_load_ppp_csv(args.ppp_csv),
            evidence_by_asset=evidence,
        )
        print(
            f"PHASE_END name=build_shadow rows={len(rows)} "
            f"elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        phase = time.perf_counter()
        print(f"PHASE_START name=write_csv path={args.out_csv}", flush=True)
        write_csv(args.out_csv, rows)
        print(
            f"PHASE_END name=write_csv rows={len(rows)} elapsed_s={time.perf_counter()-phase:.3f}",
            flush=True,
        )

        written = 0
        if args.write_db:
            phase = time.perf_counter()
            print("PHASE_START name=write_db table=research_entry_quality_shadow", flush=True)
            written = write_shadow_rows(conn, rows)
            print(
                f"PHASE_END name=write_db rows={written} elapsed_s={time.perf_counter()-phase:.3f}",
                flush=True,
            )

        print(
            f"FINISHED runner={RUNNER_NAME} mode={mode} candidates={len(selection_rows)} "
            f"eligible={len(eligible_rows)} excluded_missing_evidence={len(excluded)} rows={len(rows)} "
            f"db_rows_written={written} production_ranking_changed=0 elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 0
    except _Interrupted as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(
            f"INTERRUPTED runner={RUNNER_NAME} mode={mode} signal={exc.signum} "
            f"resumable=1 elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 130
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(
            f"FAILED runner={RUNNER_NAME} mode={mode} reason={type(exc).__name__}:{exc} "
            f"elapsed_s={time.perf_counter()-started:.3f}",
            flush=True,
        )
        return 1
    finally:
        if conn is not None:
            conn.close()
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
