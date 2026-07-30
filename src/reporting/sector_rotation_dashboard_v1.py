from __future__ import annotations

"""Phase C1 Sector Overview publisher (read-only).

Renders accepted, persisted ``sector_rotation_snapshot`` rows plus canonical
``sector_definition`` metadata into a deterministic view model, then emits
static JSON and HTML from that same view model. This module performs no
scoring, no state derivation, and no DB writes: it selects and formats
persisted research truth only.

Cohort selection inspects only the newest ``asof_ts_utc`` for the requested
venue/model. It never falls back to an older timestamp: if the newest
timestamp does not carry exactly the canonical window set, or is missing a
required sector/window cell, the whole cohort is DATA_UNAVAILABLE.

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
_CANONICAL_WINDOWS = frozenset(WINDOWS)
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
SAFETY_MARKERS: dict[str, Any] = {
    "db_writes": 0,
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
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


def select_coherent_cohort(
    latest_asof_ts_utc: datetime | None,
    observed_window_codes: Iterable[str],
) -> tuple[datetime | None, str | None]:
    """Validate only the newest asof_ts_utc; never search older timestamps.

    Returns ``(asof_ts_utc, reason)``. ``asof_ts_utc`` is non-None only when
    the newest timestamp carries exactly the canonical window set
    (``1h``, ``4h``, ``1d``, ``7d`` -- no fewer, no extra/unexpected codes).
    When unavailable, ``reason`` explains why and ``asof_ts_utc`` is ``None``
    (the caller retains the attempted ``latest_asof_ts_utc`` separately for
    display).
    """
    if latest_asof_ts_utc is None:
        return None, "NO_COHORT_CANDIDATES"
    observed = frozenset(str(code) for code in observed_window_codes)
    if observed != _CANONICAL_WINDOWS:
        return None, "INCOMPLETE_LATEST_COHORT"
    return _utc_naive(latest_asof_ts_utc), None


def build_dashboard(
    sector_definition_rows: Iterable[dict[str, Any]],
    snapshot_rows: Iterable[dict[str, Any]],
    *,
    venue: str,
    model_version: str,
    latest_asof_ts_utc: datetime | None,
    observed_window_codes: Iterable[str],
    now_utc: datetime,
) -> SectorOverviewDashboard:
    generated = _utc_naive(now_utc)
    attempted_asof = _utc_naive(latest_asof_ts_utc) if latest_asof_ts_utc is not None else None
    attempted_age_seconds = (
        (generated - attempted_asof).total_seconds() if attempted_asof is not None else None
    )

    selected_asof, cohort_reason = select_coherent_cohort(latest_asof_ts_utc, observed_window_codes)
    if selected_asof is None:
        return SectorOverviewDashboard(
            status="DATA_UNAVAILABLE",
            freshness_state="DATA_UNAVAILABLE",
            generated_at_utc=generated,
            venue=venue,
            model_version=model_version,
            asof_ts_utc=attempted_asof,
            age_seconds=attempted_age_seconds,
            sectors=(),
            reason=cohort_reason,
        )

    sector_defs = list(sector_definition_rows)
    if not sector_defs:
        return SectorOverviewDashboard(
            status="DATA_UNAVAILABLE",
            freshness_state="DATA_UNAVAILABLE",
            generated_at_utc=generated,
            venue=venue,
            model_version=model_version,
            asof_ts_utc=selected_asof,
            age_seconds=attempted_age_seconds,
            sectors=(),
            reason="NO_ACTIVE_SECTORS",
        )

    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in snapshot_rows:
        key = (str(row["sector_code"]), str(row["window_code"]))
        by_key[key] = row

    expected_keys = {
        (str(sector_def["sector_code"]), window_code)
        for sector_def in sector_defs
        for window_code in WINDOWS
    }
    missing_keys = expected_keys - set(by_key.keys())
    if missing_keys:
        return SectorOverviewDashboard(
            status="DATA_UNAVAILABLE",
            freshness_state="DATA_UNAVAILABLE",
            generated_at_utc=generated,
            venue=venue,
            model_version=model_version,
            asof_ts_utc=selected_asof,
            age_seconds=attempted_age_seconds,
            sectors=(),
            reason="INCOMPLETE_LATEST_COHORT",
        )

    sectors: list[SectorRow] = []
    for sector_def in sector_defs:
        sector_code = str(sector_def["sector_code"])
        cells = tuple(
            _cell_from_row(by_key[(sector_code, window_code)]) for window_code in WINDOWS
        )
        sectors.append(
            SectorRow(
                sector_code=sector_code,
                display_name=str(sector_def["display_name"]),
                cells=cells,
            )
        )

    freshness = classify_freshness(selected_asof, generated)
    age_seconds = (generated - selected_asof).total_seconds()
    status = "DEGRADED" if freshness in ("STALE", "FUTURE_TIMESTAMP") else "AVAILABLE"

    return SectorOverviewDashboard(
        status=status,
        freshness_state=freshness,
        generated_at_utc=generated,
        venue=venue,
        model_version=model_version,
        asof_ts_utc=selected_asof,
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
        "safety": dict(SAFETY_MARKERS),
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


def _fmt_age(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "unknown"
    sign = "-" if age_seconds < 0 else ""
    total_seconds = int(abs(age_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours}h{minutes:02d}m"


def _state_label(state: str | None) -> str:
    if state is None:
        return "UNAVAILABLE"
    return state.replace("_", " ")


def _safety_line() -> str:
    return " ".join(f"{key}={value}" for key, value in SAFETY_MARKERS.items())


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


def _asof_text(dashboard: SectorOverviewDashboard) -> str:
    return _iso_z(dashboard.asof_ts_utc) if dashboard.asof_ts_utc is not None else "unknown"


def render_dashboard_html(dashboard: SectorOverviewDashboard) -> str:
    if dashboard.status == "DATA_UNAVAILABLE":
        main = f"""
<section class='unavailable'>
  <h1>Sector Overview</h1>
  <p class='reason'>DATA UNAVAILABLE — {html.escape(dashboard.reason or 'UNKNOWN')}</p>
  <div class='meta'>
    <span>Attempted as of {html.escape(_asof_text(dashboard))}</span>
    <span>Age {html.escape(_fmt_age(dashboard.age_seconds))}</span>
    <span>Generated {html.escape(_iso_z(dashboard.generated_at_utc))}</span>
  </div>
  <div class='safety'>{html.escape(_safety_line())}</div>
</section>
"""
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
  <span>As of {html.escape(_asof_text(dashboard))}</span>
  <span>Age {html.escape(_fmt_age(dashboard.age_seconds))}</span>
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
.unavailable .meta {{ margin-top:10px; background:none; border:0; padding:0; }}
.unavailable .safety {{ margin-top:10px; font-size:.7rem; color:#8fa5bf; }}
</style>
</head>
<body>
{main}
<footer><small>Generated {_iso_z(dashboard.generated_at_utc)} · market-only · rotation score, state, and volume confirmation are price/volume-derived proxies, not measured capital inflow or outflow</small></footer>
</body>
</html>"""
