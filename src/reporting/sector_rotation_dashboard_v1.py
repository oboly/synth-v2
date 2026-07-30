from __future__ import annotations

"""Phase C1 Sector Overview publisher (read-only).

Renders accepted, persisted ``sector_rotation_snapshot`` rows plus canonical
``sector_definition`` metadata into a deterministic view model, then emits
static JSON and HTML from that same view model. This module performs no
scoring, no state derivation, and no DB writes: it selects and formats
persisted research truth only.

Price/volume-derived rotation state is a proxy, never a measured capital
flow. Rendered surfaces must say so.
"""

import html
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable


MODEL_VERSION = "sector-rotation-v1.0.0"
WINDOWS: tuple[str, ...] = ("1h", "4h", "1d", "7d")
DEFAULT_STALE_AFTER = timedelta(hours=3)
ROTATION_STATES = {
    "LEADING",
    "IMPROVING",
    "NEUTRAL",
    "WEAKENING",
    "LAGGING",
    "ROTATION_INFLOW_PROXY",
    "ROTATION_OUTFLOW_PROXY",
    "MARKET_ACTIVITY_RISING",
    "MARKET_ACTIVITY_COOLING",
    "NO_CONFIRMATION",
    "INSUFFICIENT_PARTICIPATION",
    "DATA_UNAVAILABLE",
}


@dataclass(frozen=True)
class SectorWindowCell:
    window_code: str
    cell_status: str  # AVAILABLE | UNAVAILABLE
    rotation_score: float | None
    rotation_state: str | None
    confidence: float | None
    participation_ratio: float | None
    volume_confirmation: str | None
    generated_ts_utc: datetime | None


@dataclass(frozen=True)
class SectorRow:
    sector_code: str
    display_name: str
    cells: tuple[SectorWindowCell, ...]


@dataclass(frozen=True)
class SectorOverviewDashboard:
    status: str
    freshness_state: str
    generated_at_utc: datetime
    venue: str | None
    model_version: str | None
    asof_ts_utc: datetime | None
    age_seconds: float | None
    sectors: tuple[SectorRow, ...]
    reason: str | None = None


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def classify_freshness(
    asof_ts_utc: datetime | None,
    now_utc: datetime,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> str:
    if asof_ts_utc is None:
        return "DATA_UNAVAILABLE"
    as_of = _utc_naive(asof_ts_utc)
    now = _utc_naive(now_utc)
    age = now - as_of
    if age < timedelta(minutes=-5):
        return "FUTURE_TIMESTAMP"
    if age > stale_after:
        return "STALE"
    return "FRESH"


def _require_finite_float(value: Any, field: str) -> float:
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be finite")
    return result


def _volume_confirmation_label(supporting_flags_json: Any) -> str:
    flags = supporting_flags_json
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except (TypeError, ValueError):
            flags = {}
    if not isinstance(flags, dict):
        flags = {}
    if flags.get("rotation_inflow_proxy"):
        return "ROTATION_INFLOW_PROXY_CONFIRMED"
    if flags.get("rotation_outflow_proxy"):
        return "ROTATION_OUTFLOW_PROXY_CONFIRMED"
    if flags.get("no_confirmation"):
        return "NO_CONFIRMATION"
    return "NOT_CONFIRMED"


def _cell_from_row(row: dict[str, Any]) -> SectorWindowCell:
    rotation_state = str(row["rotation_state"])
    if rotation_state not in ROTATION_STATES:
        raise ValueError(f"unsupported rotation_state: {rotation_state}")
    return SectorWindowCell(
        window_code=str(row["window_code"]),
        cell_status="AVAILABLE",
        rotation_score=_require_finite_float(row["rotation_score"], "rotation_score"),
        rotation_state=rotation_state,
        confidence=_require_finite_float(row["confidence"], "confidence"),
        participation_ratio=_require_finite_float(row["participation_ratio"], "participation_ratio"),
        volume_confirmation=_volume_confirmation_label(row.get("supporting_flags_json")),
        generated_ts_utc=_utc_naive(row["generated_ts_utc"]) if row.get("generated_ts_utc") else None,
    )


def _unavailable_cell(window_code: str) -> SectorWindowCell:
    return SectorWindowCell(
        window_code=window_code,
        cell_status="UNAVAILABLE",
        rotation_score=None,
        rotation_state=None,
        confidence=None,
        participation_ratio=None,
        volume_confirmation=None,
        generated_ts_utc=None,
    )


def select_coherent_cohort(
    cohort_candidates: Iterable[dict[str, Any]],
) -> datetime | None:
    """Pick the latest asof_ts_utc that has all required windows present.

    ``cohort_candidates`` rows must contain ``asof_ts_utc`` and
    ``window_count`` (distinct window codes observed at that timestamp),
    pre-grouped and ordered by ``asof_ts_utc`` descending by the caller.
    """
    for candidate in cohort_candidates:
        if int(candidate["window_count"]) >= len(WINDOWS):
            return _utc_naive(candidate["asof_ts_utc"])
    return None


def build_dashboard(
    sector_definition_rows: Iterable[dict[str, Any]],
    snapshot_rows: Iterable[dict[str, Any]],
    *,
    venue: str,
    model_version: str,
    asof_ts_utc: datetime | None,
    now_utc: datetime,
) -> SectorOverviewDashboard:
    generated = _utc_naive(now_utc)
    sector_defs = list(sector_definition_rows)

    if asof_ts_utc is None:
        return SectorOverviewDashboard(
            status="DATA_UNAVAILABLE",
            freshness_state="DATA_UNAVAILABLE",
            generated_at_utc=generated,
            venue=venue,
            model_version=model_version,
            asof_ts_utc=None,
            age_seconds=None,
            sectors=(),
            reason="NO_COHERENT_COHORT",
        )

    if not sector_defs:
        return SectorOverviewDashboard(
            status="DATA_UNAVAILABLE",
            freshness_state="DATA_UNAVAILABLE",
            generated_at_utc=generated,
            venue=venue,
            model_version=model_version,
            asof_ts_utc=_utc_naive(asof_ts_utc),
            age_seconds=None,
            sectors=(),
            reason="NO_ACTIVE_SECTORS",
        )

    asof = _utc_naive(asof_ts_utc)
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in snapshot_rows:
        key = (str(row["sector_code"]), str(row["window_code"]))
        by_key[key] = row

    sectors: list[SectorRow] = []
    missing_cells = 0
    for sector_def in sector_defs:
        sector_code = str(sector_def["sector_code"])
        cells: list[SectorWindowCell] = []
        for window_code in WINDOWS:
            row = by_key.get((sector_code, window_code))
            if row is None:
                cells.append(_unavailable_cell(window_code))
                missing_cells += 1
            else:
                cells.append(_cell_from_row(row))
        sectors.append(
            SectorRow(
                sector_code=sector_code,
                display_name=str(sector_def["display_name"]),
                cells=tuple(cells),
            )
        )

    freshness = classify_freshness(asof, generated)
    age_seconds = (generated - asof).total_seconds()

    if freshness in ("STALE", "FUTURE_TIMESTAMP"):
        status = "DEGRADED"
    elif missing_cells > 0:
        status = "DEGRADED"
    else:
        status = "AVAILABLE"

    return SectorOverviewDashboard(
        status=status,
        freshness_state=freshness,
        generated_at_utc=generated,
        venue=venue,
        model_version=model_version,
        asof_ts_utc=asof,
        age_seconds=age_seconds,
        sectors=tuple(sectors),
    )


def _iso_z(value: datetime) -> str:
    return _utc_naive(value).isoformat(timespec="seconds") + "Z"


def dashboard_to_json_dict(dashboard: SectorOverviewDashboard) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "report_name": "sector_rotation_dashboard_v1",
        "report_version": "1.0",
        "status": dashboard.status,
        "freshness_state": dashboard.freshness_state,
        "reason": dashboard.reason,
        "generated_at_utc": _iso_z(dashboard.generated_at_utc),
        "venue": dashboard.venue,
        "model_version": dashboard.model_version,
        "asof_ts_utc": _iso_z(dashboard.asof_ts_utc) if dashboard.asof_ts_utc else None,
        "age_seconds": dashboard.age_seconds,
        "windows": list(WINDOWS),
        "sectors": [],
        "rotation_proxy_disclaimer": (
            "Rotation score, state, and volume confirmation are price/volume-derived "
            "proxies, not measured capital inflow or outflow."
        ),
        "safety": {
            "db_writes": 0,
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
        },
    }
    for sector in dashboard.sectors:
        cell_payload = {}
        for cell in sector.cells:
            cell_dict = asdict(cell)
            cell_dict["generated_ts_utc"] = (
                _iso_z(cell.generated_ts_utc) if cell.generated_ts_utc else None
            )
            cell_payload[cell.window_code] = cell_dict
        payload["sectors"].append(
            {
                "sector_code": sector.sector_code,
                "display_name": sector.display_name,
                "windows": cell_payload,
            }
        )
    return payload


def _fmt_score(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.1f}"


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0%}"


def _state_label(state: str | None) -> str:
    if state is None:
        return "UNAVAILABLE"
    return state.replace("_", " ")


def _cell_html(cell: SectorWindowCell) -> str:
    if cell.cell_status == "UNAVAILABLE":
        return (
            "<td class='cell unavailable' data-window='" + html.escape(cell.window_code) + "'>"
            "<span class='badge unavailable'>DATA UNAVAILABLE</span>"
            "</td>"
        )
    return (
        "<td class='cell' data-window='" + html.escape(cell.window_code) + "'>"
        f"<div class='score'>{_fmt_score(cell.rotation_score)}</div>"
        f"<div class='state'>{html.escape(_state_label(cell.rotation_state))}</div>"
        f"<div class='meta'>conf {_fmt_ratio(cell.confidence)} · "
        f"part {_fmt_ratio(cell.participation_ratio)}</div>"
        f"<div class='volume'>{html.escape(cell.volume_confirmation or '—')}</div>"
        "</td>"
    )


def render_dashboard_html(dashboard: SectorOverviewDashboard) -> str:
    if dashboard.status == "DATA_UNAVAILABLE":
        main = (
            "<section class='unavailable'>"
            "<h1>Sector Overview</h1>"
            f"<p>DATA UNAVAILABLE — {html.escape(dashboard.reason or 'UNKNOWN')}</p>"
            "</section>"
        )
        title = "Sector Overview — unavailable"
    else:
        header_cells = "".join(f"<th>{html.escape(window)}</th>" for window in WINDOWS)
        body_rows = "".join(
            "<tr>"
            f"<td class='sector'><strong>{html.escape(sector.display_name)}</strong>"
            f"<span class='code'>{html.escape(sector.sector_code)}</span></td>"
            + "".join(_cell_html(cell) for cell in sector.cells)
            + "</tr>"
            for sector in dashboard.sectors
        )
        main = f"""
<section class='meta'>
  <span>Venue {html.escape(dashboard.venue or '')}</span>
  <span>Model {html.escape(dashboard.model_version or '')}</span>
  <span>As of {_iso_z(dashboard.asof_ts_utc)}</span>
  <span class='freshness {dashboard.freshness_state.lower()}'>{html.escape(dashboard.freshness_state)}</span>
  <span>Sectors {len(dashboard.sectors)}</span>
</section>
<section class='table-wrap'>
<table>
<thead><tr><th>Sector</th>{header_cells}</tr></thead>
<tbody>{body_rows}</tbody>
</table>
</section>
"""
        title = "Sector Overview"

    return f"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<meta http-equiv='refresh' content='300'>
<title>{html.escape(title)}</title>
<style>
:root {{ color-scheme: dark; font-family: Inter, system-ui, sans-serif; background:#07111f; color:#e7eef8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:18px; background:linear-gradient(180deg,#081524,#050b13); min-height:100vh; }}
.meta {{ display:flex; flex-wrap:wrap; gap:8px; padding:10px 14px; border:1px solid #24364d; border-radius:14px; background:#0b1827; }}
.meta span {{ padding:6px 9px; border-radius:999px; background:#15263a; color:#c8d6e8; font-size:.78rem; }}
.freshness.fresh {{ color:#74efa8; }} .freshness.stale,.freshness.future_timestamp {{ color:#ff8790; }}
.table-wrap {{ margin-top:16px; overflow:auto; border:1px solid #24364d; border-radius:14px; background:#0b1827; padding:0; }}
table {{ width:100%; border-collapse:collapse; min-width:900px; }}
th,td {{ padding:10px 12px; border-bottom:1px solid #182a3e; text-align:left; font-size:.8rem; vertical-align:top; }}
th {{ position:sticky; top:0; background:#102238; color:#a9bdd3; }}
.sector .code {{ display:block; color:#71869f; font-size:.7rem; }}
.cell .score {{ font-weight:700; font-variant-numeric:tabular-nums; }}
.cell .state {{ color:#a9bdd3; font-size:.72rem; }}
.cell .meta {{ color:#71869f; font-size:.7rem; border:0; padding:0; background:none; }}
.cell .volume {{ margin-top:4px; font-size:.68rem; color:#8fa5bf; }}
.badge.unavailable {{ display:inline-block; padding:3px 8px; border-radius:6px; background:#3a1b22; color:#ff9da4; font-size:.68rem; }}
.unavailable {{ max-width:760px; margin:10vh auto; color:#ff9da4; border:1px solid #24364d; border-radius:14px; background:#0b1827; padding:16px; }}
</style>
</head>
<body>
{main}
<footer><small>Generated {_iso_z(dashboard.generated_at_utc)} · market-only · rotation score, state, and volume confirmation are price/volume-derived proxies, not measured capital inflow or outflow</small></footer>
</body>
</html>"""
