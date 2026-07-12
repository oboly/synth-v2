from __future__ import annotations

import html
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable


MODEL_VERSION = "1.0"
DEFAULT_STALE_AFTER = timedelta(hours=2, minutes=30)
DIRECTIONS = {"ROTATION_IN", "ROTATION_OUT", "MIXED"}


@dataclass(frozen=True)
class RotationPressureHeader:
    pressure_snapshot_id: int
    as_of_ts_utc: datetime
    venue: str
    model_version: str
    eligible_asset_count: int
    excluded_missing_pair_count: int
    positive_count: int
    neutral_count: int
    negative_count: int
    market_score: float
    positive_breadth_ratio: float
    negative_breadth_ratio: float
    acceleration_state: str
    concentration_state: str
    confirmation_state: str
    market_direction: str
    evidence_light_count: int


@dataclass(frozen=True)
class RotationPressureRow:
    asset_id: int
    market: str
    score_total: float
    pressure_state: str
    phase_state: str
    raw_return_24h_pct: float
    raw_return_7d_pct: float
    raw_relative_volume_24h: float
    raw_relative_volume_7d: float
    score_acceleration: float
    score_persistence: float


@dataclass(frozen=True)
class RotationPressureDashboard:
    status: str
    freshness_state: str
    generated_at_utc: datetime
    header: RotationPressureHeader | None
    rows: tuple[RotationPressureRow, ...]
    reason: str | None = None


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def classify_freshness(
    as_of_ts_utc: datetime | None,
    now_utc: datetime,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> str:
    if as_of_ts_utc is None:
        return "DATA_UNAVAILABLE"
    as_of = _utc_naive(as_of_ts_utc)
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


def header_from_mapping(row: dict[str, Any]) -> RotationPressureHeader:
    direction = str(row["market_direction"])
    if direction not in DIRECTIONS:
        raise ValueError(f"unsupported market_direction: {direction}")
    lights = int(row["evidence_light_count"])
    if not 0 <= lights <= 5:
        raise ValueError("evidence_light_count must be within 0..5")
    return RotationPressureHeader(
        pressure_snapshot_id=int(row["pressure_snapshot_id"]),
        as_of_ts_utc=_utc_naive(row["as_of_ts_utc"]),
        venue=str(row["venue"]),
        model_version=str(row["model_version"]),
        eligible_asset_count=int(row["eligible_asset_count"]),
        excluded_missing_pair_count=int(row["excluded_missing_pair_count"]),
        positive_count=int(row["positive_count"]),
        neutral_count=int(row["neutral_count"]),
        negative_count=int(row["negative_count"]),
        market_score=_require_finite_float(row["market_score"], "market_score"),
        positive_breadth_ratio=_require_finite_float(row["positive_breadth_ratio"], "positive_breadth_ratio"),
        negative_breadth_ratio=_require_finite_float(row["negative_breadth_ratio"], "negative_breadth_ratio"),
        acceleration_state=str(row["acceleration_state"]),
        concentration_state=str(row["concentration_state"]),
        confirmation_state=str(row["confirmation_state"]),
        market_direction=direction,
        evidence_light_count=lights,
    )


def row_from_mapping(row: dict[str, Any]) -> RotationPressureRow:
    return RotationPressureRow(
        asset_id=int(row["asset_id"]),
        market=str(row["market"]),
        score_total=_require_finite_float(row["score_total"], "score_total"),
        pressure_state=str(row["pressure_state"]),
        phase_state=str(row["phase_state"]),
        raw_return_24h_pct=_require_finite_float(row["raw_return_24h_pct"], "raw_return_24h_pct"),
        raw_return_7d_pct=_require_finite_float(row["raw_return_7d_pct"], "raw_return_7d_pct"),
        raw_relative_volume_24h=_require_finite_float(row["raw_relative_volume_24h"], "raw_relative_volume_24h"),
        raw_relative_volume_7d=_require_finite_float(row["raw_relative_volume_7d"], "raw_relative_volume_7d"),
        score_acceleration=_require_finite_float(row["score_acceleration"], "score_acceleration"),
        score_persistence=_require_finite_float(row["score_persistence"], "score_persistence"),
    )


def build_dashboard(
    header_row: dict[str, Any] | None,
    observation_rows: Iterable[dict[str, Any]],
    *,
    now_utc: datetime,
) -> RotationPressureDashboard:
    generated = _utc_naive(now_utc)
    if header_row is None:
        return RotationPressureDashboard(
            status="DATA_UNAVAILABLE",
            freshness_state="DATA_UNAVAILABLE",
            generated_at_utc=generated,
            header=None,
            rows=(),
            reason="NO_PRESSURE_SNAPSHOT",
        )

    header = header_from_mapping(header_row)
    rows = tuple(row_from_mapping(row) for row in observation_rows)
    if len(rows) != header.eligible_asset_count:
        return RotationPressureDashboard(
            status="DATA_UNAVAILABLE",
            freshness_state=classify_freshness(header.as_of_ts_utc, generated),
            generated_at_utc=generated,
            header=header,
            rows=rows,
            reason=(
                "OBSERVATION_COUNT_MISMATCH:"
                f"expected={header.eligible_asset_count}:actual={len(rows)}"
            ),
        )

    freshness = classify_freshness(header.as_of_ts_utc, generated)
    status = "AVAILABLE" if freshness == "FRESH" else "DEGRADED"
    return RotationPressureDashboard(
        status=status,
        freshness_state=freshness,
        generated_at_utc=generated,
        header=header,
        rows=rows,
    )


def _iso_z(value: datetime) -> str:
    return _utc_naive(value).isoformat(timespec="seconds") + "Z"


def dashboard_to_json_dict(dashboard: RotationPressureDashboard) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "report_name": "market_rotation_pressure_dashboard_v1",
        "report_version": "1.0",
        "status": dashboard.status,
        "freshness_state": dashboard.freshness_state,
        "reason": dashboard.reason,
        "generated_at_utc": _iso_z(dashboard.generated_at_utc),
        "header": None,
        "rows": [],
        "safety": {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "selection_engine": "none",
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
        },
    }
    if dashboard.header is not None:
        header_payload = asdict(dashboard.header)
        header_payload["as_of_ts_utc"] = _iso_z(dashboard.header.as_of_ts_utc)
        payload["header"] = header_payload
    payload["rows"] = [asdict(row) for row in dashboard.rows]
    return payload


def _fmt_score(value: float) -> str:
    return f"{value:+.1f}"


def _fmt_pct(value: float) -> str:
    return f"{value:+.2f}%"


def _direction_label(direction: str) -> str:
    return {
        "ROTATION_IN": "ROTATION IN",
        "ROTATION_OUT": "ROTATION OUT",
        "MIXED": "MIXED ROTATION",
    }.get(direction, "DATA UNAVAILABLE")


def _lights_html(header: RotationPressureHeader) -> str:
    direction_class = {
        "ROTATION_IN": "light-in",
        "ROTATION_OUT": "light-out",
        "MIXED": "light-mixed",
    }[header.market_direction]
    lights = []
    for index in range(5):
        active = index < header.evidence_light_count
        classes = f"light {'active ' + direction_class if active else ''}".strip()
        lights.append(f"<span class='{classes}' aria-label='evidence light {index + 1}'></span>")
    return "".join(lights)


def _top_rows(rows: tuple[RotationPressureRow, ...], *, positive: bool, limit: int = 5) -> list[RotationPressureRow]:
    selected = [row for row in rows if row.score_total >= 30] if positive else [row for row in rows if row.score_total <= -30]
    return sorted(selected, key=lambda row: row.score_total, reverse=positive)[:limit]


def _top_cards_html(rows: list[RotationPressureRow], *, empty_label: str) -> str:
    if not rows:
        return f"<div class='empty'>{html.escape(empty_label)}</div>"
    return "".join(
        "<div class='top-coin'>"
        f"<strong>{html.escape(row.market)}</strong>"
        f"<span class='score'>{_fmt_score(row.score_total)}</span>"
        f"<span>{html.escape(row.phase_state.replace('_', ' '))}</span>"
        "</div>"
        for row in rows
    )


def render_dashboard_html(dashboard: RotationPressureDashboard) -> str:
    if dashboard.header is None:
        main = (
            "<section class='unavailable'>"
            "<h1>Rotation Pressure</h1>"
            f"<p>DATA UNAVAILABLE — {html.escape(dashboard.reason or 'UNKNOWN')}</p>"
            "</section>"
        )
        title = "Rotation Pressure — unavailable"
    else:
        header = dashboard.header
        top_in = _top_rows(dashboard.rows, positive=True)
        top_out = _top_rows(dashboard.rows, positive=False)
        table_rows = "".join(
            "<tr>"
            f"<td>{html.escape(row.market)}</td>"
            f"<td class='num'>{_fmt_score(row.score_total)}</td>"
            f"<td>{html.escape(row.pressure_state.replace('_', ' '))}</td>"
            f"<td>{html.escape(row.phase_state.replace('_', ' '))}</td>"
            f"<td class='num'>{_fmt_pct(row.raw_return_24h_pct)}</td>"
            f"<td class='num'>{_fmt_pct(row.raw_return_7d_pct)}</td>"
            f"<td class='num'>{row.raw_relative_volume_24h:.2f}x</td>"
            f"<td class='num'>{row.raw_relative_volume_7d:.2f}x</td>"
            f"<td class='num'>{_fmt_score(row.score_acceleration)}</td>"
            f"<td class='num'>{_fmt_score(row.score_persistence)}</td>"
            "</tr>"
            for row in sorted(dashboard.rows, key=lambda row: row.score_total, reverse=True)
        )
        main = f"""
<section class='pressure-strip direction-{header.market_direction.lower()}'>
  <div>
    <div class='eyebrow'>MARKET ROTATION PRESSURE</div>
    <div class='headline'>{_direction_label(header.market_direction)} <span>{_fmt_score(header.market_score)}</span></div>
  </div>
  <div class='lights' aria-label='{header.evidence_light_count} of 5 evidence lights'>{_lights_html(header)}</div>
  <div class='metrics'>
    <span>IN {header.positive_breadth_ratio:.0%}</span>
    <span>OUT {header.negative_breadth_ratio:.0%}</span>
    <span>{html.escape(header.acceleration_state.replace('_', ' '))}</span>
    <span>{html.escape(header.confirmation_state)}</span>
    <span>{html.escape(header.concentration_state)}</span>
  </div>
  <div class='freshness {dashboard.freshness_state.lower()}'>{html.escape(dashboard.freshness_state)}</div>
</section>
<section class='top-grid'>
  <article><h2>Top rotation in</h2>{_top_cards_html(top_in, empty_label='No confirmed rotation-in assets')}</article>
  <article><h2>Top rotation out</h2>{_top_cards_html(top_out, empty_label='No confirmed rotation-out assets')}</article>
</section>
<section class='meta'>
  <span>Snapshot {_iso_z(header.as_of_ts_utc)}</span>
  <span>Eligible {header.eligible_asset_count}</span>
  <span>Missing pair {header.excluded_missing_pair_count}</span>
  <span>Model {html.escape(header.model_version)}</span>
</section>
<section class='table-wrap'>
<table>
<thead><tr><th>Market</th><th>Score</th><th>Pressure</th><th>Phase</th><th>24h</th><th>7d</th><th>RV 24h</th><th>RV 7d</th><th>Acceleration</th><th>Persistence</th></tr></thead>
<tbody>{table_rows}</tbody>
</table>
</section>
"""
        title = "Rotation Pressure"

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
.pressure-strip {{ display:grid; grid-template-columns:minmax(210px,1fr) auto minmax(260px,1.4fr) auto; gap:18px; align-items:center; padding:18px 20px; border:1px solid #24364d; border-radius:16px; background:#0d1b2b; box-shadow:0 10px 30px #0007; }}
.eyebrow {{ font-size:.75rem; letter-spacing:.14em; color:#8fa5bf; }}
.headline {{ margin-top:4px; font-size:1.35rem; font-weight:800; }}
.headline span {{ margin-left:8px; font-variant-numeric:tabular-nums; }}
.lights {{ display:flex; gap:8px; }}
.light {{ width:17px; height:17px; border-radius:50%; border:1px solid #53657a; background:#172536; box-shadow:inset 0 0 7px #000; }}
.light.active.light-in {{ background:#3ee08f; box-shadow:0 0 13px #3ee08f99; }}
.light.active.light-out {{ background:#ff6471; box-shadow:0 0 13px #ff647199; }}
.light.active.light-mixed {{ background:#f3c95f; box-shadow:0 0 13px #f3c95f99; }}
.metrics {{ display:flex; flex-wrap:wrap; gap:8px; }}
.metrics span,.freshness,.meta span {{ padding:6px 9px; border-radius:999px; background:#15263a; color:#c8d6e8; font-size:.78rem; }}
.freshness.fresh {{ color:#74efa8; }} .freshness.stale,.freshness.future_timestamp {{ color:#ff8790; }}
.top-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:16px; }}
article,.table-wrap,.meta,.unavailable {{ border:1px solid #24364d; border-radius:14px; background:#0b1827; padding:16px; }}
h2 {{ margin:0 0 12px; font-size:1rem; color:#b9c8da; }}
.top-coin {{ display:grid; grid-template-columns:1fr auto 1.5fr; gap:10px; padding:8px 0; border-top:1px solid #1b2d42; font-size:.86rem; }}
.top-coin:first-of-type {{ border-top:0; }} .score,.num {{ font-variant-numeric:tabular-nums; text-align:right; }}
.empty {{ color:#71869f; padding:10px 0; }}
.meta {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; padding:10px 14px; }}
.table-wrap {{ margin-top:16px; overflow:auto; padding:0; }}
table {{ width:100%; border-collapse:collapse; min-width:1050px; }} th,td {{ padding:10px 12px; border-bottom:1px solid #182a3e; text-align:left; font-size:.8rem; }} th {{ position:sticky; top:0; background:#102238; color:#a9bdd3; }}
.unavailable {{ max-width:760px; margin:10vh auto; color:#ff9da4; }}
@media(max-width:900px) {{ .pressure-strip {{ grid-template-columns:1fr; }} .top-grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
{main}
<footer><small>Generated {_iso_z(dashboard.generated_at_utc)} · market-only · inferred rotation pressure, not verified fund flow</small></footer>
</body>
</html>"""
