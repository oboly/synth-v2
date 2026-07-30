from __future__ import annotations

"""Runner for the Phase C1 Sector Overview publisher.

Read-only: selects one internally coherent accepted
``sector_rotation_snapshot`` cohort (one venue, one model version, one
as-of timestamp, all required windows) plus canonical ``sector_definition``
rows, and renders static JSON and HTML from the same view model. Performs
no scoring, no DB writes, no broker calls, no execution-layer coupling.
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
    select_coherent_cohort,
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


def fetch_cohort_candidates(conn: Any, *, venue: str, model_version: str) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT asof_ts_utc, COUNT(DISTINCT window_code) AS window_count "
            "FROM sector_rotation_snapshot WHERE venue=%s AND model_version=%s "
            "GROUP BY asof_ts_utc ORDER BY asof_ts_utc DESC",
            (venue, model_version),
        )
        return list(cur.fetchall())


def fetch_active_sector_definitions(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sector_code, display_name FROM sector_definition "
            "WHERE is_active=1 ORDER BY sort_order, sector_code"
        )
        return list(cur.fetchall())


def fetch_cohort_snapshot_rows(
    conn: Any, *, venue: str, model_version: str, asof_ts_utc: datetime
) -> list[dict[str, Any]]:
    placeholders = ", ".join(["%s"] * len(WINDOWS))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sector_code, window_code, rotation_score, rotation_state, confidence, "
            "participation_ratio, supporting_flags_json, generated_ts_utc "
            "FROM sector_rotation_snapshot "
            f"WHERE venue=%s AND model_version=%s AND asof_ts_utc=%s AND window_code IN ({placeholders}) "
            "ORDER BY sector_code, window_code",
            (venue, model_version, asof_ts_utc, *WINDOWS),
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

        cohort_candidates = fetch_cohort_candidates(
            conn, venue=args.venue, model_version=args.model_version
        )
        asof_ts_utc = select_coherent_cohort(cohort_candidates)

        sector_definition_rows: list[dict[str, Any]] = []
        snapshot_rows: list[dict[str, Any]] = []
        if asof_ts_utc is not None:
            sector_definition_rows = fetch_active_sector_definitions(conn)
            snapshot_rows = fetch_cohort_snapshot_rows(
                conn,
                venue=args.venue,
                model_version=args.model_version,
                asof_ts_utc=asof_ts_utc,
            )
    finally:
        conn.close()

    dashboard = build_dashboard(
        sector_definition_rows,
        snapshot_rows,
        venue=args.venue,
        model_version=args.model_version,
        asof_ts_utc=asof_ts_utc,
        now_utc=datetime.now(UTC),
    )
    if dashboard.status == "DATA_UNAVAILABLE":
        print(f"FAILED DASHBOARD_DATA_UNAVAILABLE reason={dashboard.reason}")
        return 1

    html_content = render_dashboard_html(dashboard)
    json_content = json.dumps(
        dashboard_to_json_dict(dashboard),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    atomic_text_write(html_content, output_html)
    atomic_text_write(json_content, output_json)

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
