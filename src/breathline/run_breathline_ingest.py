from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from src.breathline.consistency import build_consistency_rows
from src.breathline.models import BreathlineRunCreate, BreathlineTokenSnapshotCreate
from src.breathline.parser import parse_breathline_table
from src.breathline.repository import BreathlineRepository
from src.common.db import get_connection


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest table-based Breathline / A+ output.")
    parser.add_argument("--raw-file", required=True, help="Path to raw Breathline table text file")
    parser.add_argument(
        "--prediction-ts",
        required=True,
        help='UTC timestamp for the run, example: "2026-04-23 12:00:00"',
    )
    parser.add_argument("--source-name", required=True, help="Source name, e.g. chatgpt_aplus")
    parser.add_argument("--prompt-version", required=True, help="Prompt version label")
    parser.add_argument("--run-label", required=True, help="Unique run label")
    parser.add_argument(
        "--consistency-window",
        type=int,
        default=3,
        help="Reserved for future use; current implementation expects repeated manual runs for same prediction_ts",
    )
    return parser.parse_args()


def _parse_prediction_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def main() -> None:
    args = _parse_args()

    raw_path = Path(args.raw_file)
    raw_text = raw_path.read_text(encoding="utf-8")

    parsed = parse_breathline_table(raw_text)
    prediction_ts_utc = _parse_prediction_ts(args.prediction_ts)

    conn = get_connection()
    try:
        repo = BreathlineRepository(conn)
        asset_map = repo.load_asset_map()

        missing_tokens = sorted({row.token for row in parsed.rows if row.token not in asset_map})
        if missing_tokens:
            raise ValueError(f"Unknown or disabled asset tokens: {', '.join(missing_tokens)}")

        run = BreathlineRunCreate(
            prediction_ts_utc=prediction_ts_utc,
            source_name=args.source_name,
            prompt_version=args.prompt_version,
            run_label=args.run_label,
            raw_text=raw_text,
        )

        aplus_run_id = repo.insert_aplus_run(run)
        repo.insert_aplus_raw_text(aplus_run_id=aplus_run_id, raw_text=raw_text)

        snapshot_rows: list[BreathlineTokenSnapshotCreate] = []
        for row in parsed.rows:
            snapshot_rows.append(
                BreathlineTokenSnapshotCreate(
                    aplus_run_id=aplus_run_id,
                    asset_id=asset_map[row.token],
                    prediction_ts_utc=prediction_ts_utc,
                    momentum=row.momentum,
                    stability=row.stability,
                    alignment=row.alignment,
                    volatility=row.volatility,
                    pressure=row.pressure,
                    shift=row.shift,
                    aplus_initial_class=None,
                    aplus_final_class=None,
                    aplus_correction_flag=0,
                    aplus_correction_reason=None,
                    source_name=args.source_name,
                    prompt_version=args.prompt_version,
                    run_label=args.run_label,
                )
            )

        repo.insert_token_snapshot_rows(snapshot_rows)

        # consistency uses all snapshots with same prediction_ts_utc across repeated runs
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                bts.aplus_run_id,
                bts.asset_id,
                bts.prediction_ts_utc,
                bts.momentum,
                bts.stability,
                bts.alignment,
                bts.volatility,
                bts.pressure,
                bts.shift,
                bts.source_name,
                bts.prompt_version,
                bts.run_label
            FROM breathline_token_snapshot bts
            WHERE bts.prediction_ts_utc = %s
            ORDER BY bts.asset_id, bts.aplus_run_id
            """,
            (prediction_ts_utc.replace(tzinfo=None),),
        )
        fetched = cursor.fetchall()

        consistency_input: list[BreathlineTokenSnapshotCreate] = []
        for row in fetched:
            if isinstance(row, dict):
                consistency_input.append(
                    BreathlineTokenSnapshotCreate(
                        aplus_run_id=int(row["aplus_run_id"]),
                        asset_id=int(row["asset_id"]),
                        prediction_ts_utc=prediction_ts_utc,
                        momentum=str(row["momentum"]),
                        stability=str(row["stability"]),
                        alignment=str(row["alignment"]),
                        volatility=str(row["volatility"]),
                        pressure=str(row["pressure"]),
                        shift=str(row["shift"]),
                        aplus_initial_class=None,
                        aplus_final_class=None,
                        aplus_correction_flag=0,
                        aplus_correction_reason=None,
                        source_name=str(row["source_name"]),
                        prompt_version=str(row["prompt_version"]),
                        run_label=str(row["run_label"]),
                    )
                )
            else:
                (
                    aplus_run_id,
                    asset_id,
                    _prediction_ts,
                    momentum,
                    stability,
                    alignment,
                    volatility,
                    pressure,
                    shift,
                    source_name,
                    prompt_version,
                    run_label,
                ) = row
                consistency_input.append(
                    BreathlineTokenSnapshotCreate(
                        aplus_run_id=int(aplus_run_id),
                        asset_id=int(asset_id),
                        prediction_ts_utc=prediction_ts_utc,
                        momentum=str(momentum),
                        stability=str(stability),
                        alignment=str(alignment),
                        volatility=str(volatility),
                        pressure=str(pressure),
                        shift=str(shift),
                        aplus_initial_class=None,
                        aplus_final_class=None,
                        aplus_correction_flag=0,
                        aplus_correction_reason=None,
                        source_name=str(source_name),
                        prompt_version=str(prompt_version),
                        run_label=str(run_label),
                    )
                )

        consistency_rows = build_consistency_rows(
            prediction_ts_utc=prediction_ts_utc,
            snapshots=consistency_input,
        )
        repo.replace_token_consistency_rows(
            prediction_ts_utc=prediction_ts_utc,
            rows=consistency_rows,
        )

        repo.commit()

        print(f"[OK] aplus_run_id={aplus_run_id}")
        print(f"[OK] token_rows={len(snapshot_rows)}")
        print(f"[OK] consistency_rows={len(consistency_rows)}")
        print(f"[OK] rejected_lines={len(parsed.rejected_lines)}")

        if parsed.rejected_lines:
            print("[INFO] rejected non-table lines:")
            for line in parsed.rejected_lines[:10]:
                print(f"  - {line}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
