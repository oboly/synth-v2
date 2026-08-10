from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.reporting.market_rotation_pressure_dashboard_v1 import (
    MODEL_VERSION,
    build_dashboard,
    dashboard_to_json_dict,
    render_dashboard_html,
)


REPORT_NAME = "run_market_rotation_pressure_dashboard_v1"
DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")
REQUIRED_TABLES = (
    "market_rotation_pressure_snapshot_v1",
    "market_rotation_pressure_observation_v1",
)
HISTORY_LIMIT = 168
_OUTPUT_MODE = 0o644


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the read-only Synth market rotation pressure dashboard."
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


def fetch_latest_snapshot(conn: Any, *, venue: str, model_version: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pressure_snapshot_id,as_of_ts_utc,venue,model_version,"
            "eligible_asset_count,excluded_missing_pair_count,positive_count,neutral_count,negative_count,"
            "market_score,positive_breadth_ratio,negative_breadth_ratio,acceleration_state,"
            "concentration_state,confirmation_state,market_direction,evidence_light_count "
            "FROM market_rotation_pressure_snapshot_v1 "
            "WHERE venue=%s AND model_version=%s ORDER BY as_of_ts_utc DESC LIMIT 1",
            (venue, model_version),
        )
        return cur.fetchone()


def fetch_snapshot_observations(conn: Any, *, pressure_snapshot_id: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT asset_id,market,score_total,pressure_state,phase_state,"
            "raw_return_24h_pct,raw_return_7d_pct,raw_relative_volume_24h,raw_relative_volume_7d,"
            "score_acceleration,score_persistence "
            "FROM market_rotation_pressure_observation_v1 "
            "WHERE pressure_snapshot_id=%s ORDER BY asset_id",
            (pressure_snapshot_id,),
        )
        return list(cur.fetchall())


def fetch_pressure_history(
    conn: Any, *, venue: str, model_version: str, limit: int = HISTORY_LIMIT
) -> list[dict[str, Any]]:
    """Read persisted aggregate snapshots only; this runner never recomputes pressure."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pressure_snapshot_id,as_of_ts_utc,market_score "
            "FROM market_rotation_pressure_snapshot_v1 "
            "WHERE venue=%s AND model_version=%s "
            "ORDER BY as_of_ts_utc DESC LIMIT %s",
            (venue, model_version, limit),
        )
        return list(cur.fetchall())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_root = Path(args.output_root)
    output_html = Path(args.output_html) if args.output_html else output_root / "rotation-pressure.html"
    output_json = Path(args.output_json) if args.output_json else output_root / "rotation-pressure.json"

    print(
        f"STARTED runner={REPORT_NAME} mode=read_only venue={args.venue} "
        f"model_version={args.model_version} ts={datetime.now(UTC).isoformat()}"
    )
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print("selection_engine=none decision_gate=none execution_planner=none executor=none")

    conn = get_connection()
    try:
        missing = check_schema_ready(conn)
        if missing:
            print(f"FAILED TARGET_SCHEMA_MISSING missing={missing}")
            return 1
        header_row = fetch_latest_snapshot(conn, venue=args.venue, model_version=args.model_version)
        history_rows = fetch_pressure_history(conn, venue=args.venue, model_version=args.model_version)
        observation_rows: list[dict[str, Any]] = []
        if header_row is not None:
            observation_rows = fetch_snapshot_observations(
                conn,
                pressure_snapshot_id=int(header_row["pressure_snapshot_id"]),
            )
    finally:
        conn.close()

    dashboard = build_dashboard(
        header_row,
        observation_rows,
        now_utc=datetime.now(UTC),
        history_rows=history_rows,
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
        header = dashboard.header
        assert header is not None
        print(
            f"PUBLISHED html={output_html} json={output_json} status={dashboard.status} "
            f"freshness={dashboard.freshness_state} direction={header.market_direction} "
            f"score={header.market_score:+.2f} lights={header.evidence_light_count}/5 "
            f"eligible={header.eligible_asset_count}"
        )
    print(f"FINISHED runner={REPORT_NAME} exit_status=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
