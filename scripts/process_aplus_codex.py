from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from scripts.aplus_parse_codex import build_parsed_payload, write_parsed_json
from scripts.aplus_upsert_compass import (
    log_etl,
    sha256_text,
    upsert_compass_and_feat,
    validate_payload,
)
from src.common.db import get_db_connection


RAW_DIR = Path("data/aplus_raw")
PARSED_DIR = Path("data/aplus_parsed")
REJECTED_DIR = Path("data/aplus_rejected")
PROCESS_NAME = "process_aplus_codex"
SOURCE_NAME = "aplus_codex"
SOURCE_TYPE = "codex_table"


def utc_now() -> datetime:
    return datetime.now(UTC)


def infer_prediction_ts_from_filename(filename: str) -> str:
    prefix = filename.split("_", 1)[0]
    dt = datetime.strptime(prefix, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=UTC)
    return dt.isoformat().replace("+00:00", "Z")


def already_processed_successfully(conn, file_hash: str) -> bool:
    sql = """
    SELECT COUNT(*) AS cnt
    FROM etl_log
    WHERE file_hash = %s
      AND status = 'COMPLETED'
    """
    with conn.cursor() as cur:
        cur.execute(sql, (file_hash,))
        row = cur.fetchone()

    if isinstance(row, dict):
        return int(row["cnt"]) > 0
    return int(row[0]) > 0


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()

    try:
        for raw_file in sorted(RAW_DIR.glob("*.txt")):
            started = utc_now()
            batch_id = uuid.uuid4().hex
            raw_text = raw_file.read_text(encoding="utf-8")
            file_hash = sha256_text(raw_text)

            if already_processed_successfully(conn, file_hash):
                log_etl(
                    conn,
                    batch_id=batch_id,
                    process_name=PROCESS_NAME,
                    source_name=SOURCE_NAME,
                    source_filename=raw_file.name,
                    file_hash=file_hash,
                    status="SKIPPED",
                    stage="FILE_SCAN",
                    severity="INFO",
                    message="File hash already processed successfully",
                    started_ts_utc=started,
                    finished_ts_utc=utc_now(),
                )
                continue

            log_etl(
                conn,
                batch_id=batch_id,
                process_name=PROCESS_NAME,
                source_name=SOURCE_NAME,
                source_filename=raw_file.name,
                file_hash=file_hash,
                status="STARTED",
                stage="FILE_SCAN",
                severity="INFO",
                started_ts_utc=started,
            )

            prediction_ts_utc = infer_prediction_ts_from_filename(raw_file.name)

            parsed_payload = build_parsed_payload(
                source_filename=raw_file.name,
                source_name=SOURCE_NAME,
                source_type=SOURCE_TYPE,
                prediction_ts_utc=prediction_ts_utc,
                raw_text=raw_text,
            )

            log_etl(
                conn,
                batch_id=batch_id,
                process_name=PROCESS_NAME,
                source_name=SOURCE_NAME,
                source_filename=raw_file.name,
                file_hash=file_hash,
                status="PARSED",
                stage="PARSE",
                severity="INFO",
                row_count=parsed_payload["meta"]["row_count"],
                expected_row_count=None,
                details_json={"parser_version": parsed_payload["meta"]["parser_version"]},
                started_ts_utc=started,
                finished_ts_utc=utc_now(),
            )

            valid, validation_details = validate_payload(conn, parsed_payload)

            if not valid:
                rejected_path = REJECTED_DIR / raw_file.name
                shutil.move(str(raw_file), str(rejected_path))

                log_etl(
                    conn,
                    batch_id=batch_id,
                    process_name=PROCESS_NAME,
                    source_name=SOURCE_NAME,
                    source_filename=raw_file.name,
                    file_hash=file_hash,
                    status="REJECTED",
                    stage="VALIDATE",
                    severity="ERROR",
                    row_count=parsed_payload["meta"]["row_count"],
                    expected_row_count=validation_details.get("expected_row_count"),
                    message="Validation failed",
                    details_json=validation_details,
                    started_ts_utc=started,
                    finished_ts_utc=utc_now(),
                )
                continue

            parsed_path = PARSED_DIR / f"{raw_file.stem}.json"
            write_parsed_json(parsed_payload, parsed_path)

            log_etl(
                conn,
                batch_id=batch_id,
                process_name=PROCESS_NAME,
                source_name=SOURCE_NAME,
                source_filename=raw_file.name,
                file_hash=file_hash,
                status="VALIDATED",
                stage="VALIDATE",
                severity="INFO",
                row_count=parsed_payload["meta"]["row_count"],
                expected_row_count=validation_details.get("expected_row_count"),
                details_json=validation_details,
                started_ts_utc=started,
                finished_ts_utc=utc_now(),
            )

            inserted_rows = upsert_compass_and_feat(
                conn,
                batch_id=batch_id,
                parsed_payload=parsed_payload,
            )

            log_etl(
                conn,
                batch_id=batch_id,
                process_name=PROCESS_NAME,
                source_name=SOURCE_NAME,
                source_filename=raw_file.name,
                file_hash=file_hash,
                status="COMPLETED",
                stage="FINALIZE",
                severity="INFO",
                row_count=inserted_rows,
                expected_row_count=validation_details.get("expected_row_count"),
                message="Compass and feat upsert completed",
                details_json={"parsed_json": str(parsed_path)},
                started_ts_utc=started,
                finished_ts_utc=utc_now(),
            )

        return 0

    except Exception as exc:
        conn.rollback()
        batch_id = uuid.uuid4().hex
        log_etl(
            conn,
            batch_id=batch_id,
            process_name=PROCESS_NAME,
            source_name=SOURCE_NAME,
            source_filename=None,
            file_hash=None,
            status="FAILED",
            stage="FINALIZE",
            severity="ERROR",
            message=str(exc),
            details_json={"exception_type": type(exc).__name__},
            started_ts_utc=utc_now(),
            finished_ts_utc=utc_now(),
        )
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
