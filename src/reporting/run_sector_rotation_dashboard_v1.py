from __future__ import annotations

"""Runner for the Phase C1 Sector Overview publisher.

Read-only: inspects only the newest ``asof_ts_utc`` for the requested
venue/model in ``sector_rotation_snapshot`` (never an older timestamp),
validates it carries exactly the canonical window set and a complete
sector/window cohort, and renders static JSON and HTML from a single view
model. A DATA_UNAVAILABLE result is still published atomically -- it
replaces any previously published output rather than leaving stale files in
place. Performs no scoring, no DB writes, no broker calls, no
execution-layer coupling.
"""

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.reporting.sector_rotation_dashboard_v1 import (
    MODEL_VERSION,
    WINDOWS,
    build_dashboard,
    dashboard_to_json_dict,
    render_dashboard_html,
)


REPORT_NAME = "run_sector_rotation_dashboard_v1"
DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")
REQUIRED_TABLES = ("sector_rotation_snapshot", "sector_definition")
_OUTPUT_MODE = 0o644


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the read-only Synth Sector Overview dashboard."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--model-version", default=MODEL_VERSION)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output-html", default=None)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args(argv)


def atomic_text_write(content: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(dest.parent, 0o755)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=str(dest.parent), suffix=".tmp", delete=False, encoding="utf-8"
        ) as handle:
            temp_path = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), _OUTPUT_MODE)
        os.replace(temp_path, dest)
        temp_path = None
        dir_fd = os.open(str(dest.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise


def check_schema_ready(conn: Any) -> list[str]:
    placeholders = ", ".join(["%s"] * len(REQUIRED_TABLES))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ({placeholders})",
            list(REQUIRED_TABLES),
        )
        found = {str(row["TABLE_NAME"]) for row in cur.fetchall()}
    return [table for table in REQUIRED_TABLES if table not in found]


def fetch_latest_asof(conn: Any, *, venue: str, model_version: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(asof_ts_utc) AS latest_asof_ts_utc FROM sector_rotation_snapshot "
            "WHERE venue=%s AND model_version=%s",
            (venue, model_version),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return row["latest_asof_ts_utc"]


def fetch_active_sector_definitions(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sector_code, display_name FROM sector_definition "
            "WHERE is_active=1 ORDER BY sort_order, sector_code"
        )
        return list(cur.fetchall())


def fetch_snapshot_rows_at(
    conn: Any, *, venue: str, model_version: str, asof_ts_utc: datetime
) -> list[dict[str, Any]]:
    """Fetch every row at the given as-of timestamp, unfiltered by window.

    Intentionally does not restrict ``window_code`` to the canonical set so
    the caller can detect unexpected/non-canonical window codes rather than
    have them silently filtered out.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sector_code, window_code, rotation_score, rotation_state, confidence, "
            "participation_ratio, supporting_flags_json, generated_ts_utc "
            "FROM sector_rotation_snapshot "
            "WHERE venue=%s AND model_version=%s AND asof_ts_utc=%s "
            "ORDER BY sector_code, window_code",
            (venue, model_version, asof_ts_utc),
        )
        return list(cur.fetchall())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_root = Path(args.output_root)
    output_html = Path(args.output_html) if args.output_html else output_root / "sector-overview.html"
    output_json = Path(args.output_json) if args.output_json else output_root / "sector-overview.json"

    print(
        f"STARTED runner={REPORT_NAME} mode=read_only venue={args.venue} "
        f"model_version={args.model_version} ts={datetime.now(UTC).isoformat()}"
    )
    print("db_writes=0 broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print("decision_gate=none execution_planner=none executor=none")

    conn = get_connection()
    try:
        missing = check_schema_ready(conn)
        if missing:
            print(f"FAILED TARGET_SCHEMA_MISSING missing={missing}")
            return 1

        latest_asof_ts_utc = fetch_latest_asof(conn, venue=args.venue, model_version=args.model_version)

        sector_definition_rows: list[dict[str, Any]] = fetch_active_sector_definitions(conn)
        snapshot_rows: list[dict[str, Any]] = []
        if latest_asof_ts_utc is not None:
            snapshot_rows = fetch_snapshot_rows_at(
                conn,
                venue=args.venue,
                model_version=args.model_version,
                asof_ts_utc=latest_asof_ts_utc,
            )
    finally:
        conn.close()

    observed_window_codes = {str(row["window_code"]) for row in snapshot_rows}

    dashboard = build_dashboard(
        sector_definition_rows,
        snapshot_rows,
        venue=args.venue,
        model_version=args.model_version,
        latest_asof_ts_utc=latest_asof_ts_utc,
        observed_window_codes=observed_window_codes,
        now_utc=datetime.now(UTC),
    )

    html_content = render_dashboard_html(dashboard)
    json_content = json.dumps(
        dashboard_to_json_dict(dashboard),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    atomic_text_write(html_content, output_html)
    atomic_text_write(json_content, output_json)

    if dashboard.status == "DATA_UNAVAILABLE":
        print(
            f"PUBLISHED_UNAVAILABLE html={output_html} json={output_json} "
            f"reason={dashboard.reason} asof={dashboard.asof_ts_utc}"
        )
        print(f"FAILED DASHBOARD_DATA_UNAVAILABLE reason={dashboard.reason}")
        print(f"FINISHED runner={REPORT_NAME} exit_status=1")
        return 1

    if args.output == "summary":
        available_cells = sum(
            1 for sector in dashboard.sectors for cell in sector.cells if cell.cell_status == "AVAILABLE"
        )
        total_cells = len(dashboard.sectors) * len(WINDOWS)
        print(
            f"PUBLISHED html={output_html} json={output_json} status={dashboard.status} "
            f"freshness={dashboard.freshness_state} asof={dashboard.asof_ts_utc} "
            f"sectors={len(dashboard.sectors)} windows={len(WINDOWS)} "
            f"cells_available={available_cells}/{total_cells}"
        )
    print(f"FINISHED runner={REPORT_NAME} exit_status=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
