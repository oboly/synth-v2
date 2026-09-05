"""Presentation-only HTML renderer for ``RegimeEvidenceMatrixV1``.

The renderer consumes the canonical read model from
``regime_evidence_matrix_v1``. It never calculates indicator values, upgrades
status/freshness, derives regime labels, or introduces account/execution state.
"""

from __future__ import annotations

import html
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.reporting.dashboard_style_v1 import cockpit_base_css, cockpit_nav, synth_favicon_head_html
from src.reporting.regime_evidence_matrix_v1 import RegimeEvidenceCellV1, RegimeEvidenceMatrixV1


TITLE = "Synth Regime Evidence Matrix"


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _value_text(value: Any) -> str:
    value = _plain(value)
    if isinstance(value, dict):
        return ", ".join(f"{key}={_value_text(item)}" for key, item in sorted(value.items()))
    if isinstance(value, list):
        return ", ".join(_value_text(item) for item in value)
    if value is None:
        return "—"
    return str(value)


def _technical_tone(value: Any) -> str:
    """Map exact technical availability states to presentation tone only.

    This mapping does not create market semantics. It is limited to whether
    prepared evidence is available/fresh/valid versus stale/insufficient.
    The source value itself is always rendered as text.
    """
    label = str(value or "").upper()
    if label in {"VALID", "AVAILABLE", "FRESH"}:
        return "ok"
    if label in {"STALE", "FUTURE_TIMESTAMP"}:
        return "bad"
    if label in {"INSUFFICIENT_DATA", "UNKNOWN", "DATA_UNAVAILABLE"}:
        return "muted"
    return "context"


def _pill(value: Any) -> str:
    visible = "—" if value is None else str(value)
    return f"<span class='pill {_technical_tone(value)}'>{_esc(visible)}</span>"


def _reasons(cell: RegimeEvidenceCellV1) -> str:
    if not cell.reason_codes:
        return "<span class='muted'>—</span>"
    return " ".join(f"<span class='pill muted'>{_esc(code)}</span>" for code in cell.reason_codes)


def _raw(cell: RegimeEvidenceCellV1) -> str:
    if not cell.raw:
        return "<span class='muted'>—</span>"
    items = []
    for key, value in sorted(cell.raw.items()):
        items.append(
            "<div class='evidence-kv'>"
            f"<span class='muted'>{_esc(key)}</span> "
            f"<span class='num'>{_esc(_value_text(value))}</span>"
            "</div>"
        )
    return "".join(items)


def _lifecycle(cell: RegimeEvidenceCellV1) -> str:
    if cell.observed_lifecycle is None:
        return "<span class='muted'>—</span>"
    return _esc(_value_text(cell.observed_lifecycle))


def _row(cell: RegimeEvidenceCellV1) -> str:
    return (
        "<tr>"
        f"<td><strong>{_esc(cell.family)}</strong><div class='muted small'>{_esc(cell.component)}</div></td>"
        f"<td>{_esc(cell.market)}<div class='muted small'>{_esc(cell.scope_key)}</div></td>"
        f"<td>{_pill(cell.status)}</td>"
        f"<td>{_pill(cell.freshness)}</td>"
        f"<td>{_esc(cell.input_interval or '—')}</td>"
        f"<td>{_esc(cell.lookback_horizon or '—')}</td>"
        f"<td>{_esc(cell.effective_horizon or '—')}</td>"
        f"<td>{_lifecycle(cell)}</td>"
        f"<td>{_esc(cell.asof_ts.isoformat() if cell.asof_ts else '—')}</td>"
        f"<td>{_esc(cell.model_id or '—')}<div class='muted small'>{_esc(cell.model_version or '—')}</div></td>"
        f"<td>{_raw(cell)}</td>"
        f"<td>{_reasons(cell)}</td>"
        "</tr>"
    )


def render_regime_evidence_matrix_html(matrix: RegimeEvidenceMatrixV1) -> str:
    """Render one deterministic, read-only evidence matrix page."""
    rows = "\n".join(_row(cell) for cell in matrix.cells)
    css = cockpit_base_css(min_table_width=1900)
    css += """
    .matrix-note { max-width: 1100px; line-height: 1.5; }
    .evidence-kv { margin: 2px 0; white-space: nowrap; }
    td { vertical-align: top; }
    .scope-warning { border-left: 3px solid var(--context); padding-left: 12px; }
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(TITLE)}</title>
{synth_favicon_head_html()}  <style>{css}</style>
</head>
<body>
  <header>
    <div class="page">
      <h1>{_esc(TITLE)}</h1>
      <div class="muted">Evaluated at {_esc(matrix.evaluated_at.isoformat())}</div>
      {cockpit_nav()}
      <div class="matrix-note scope-warning">
        Read-only canonical evidence. Status, freshness, horizons, lifecycle, raw values and reason codes are
        forwarded from upstream contracts. This page does not calculate a composite regime or trading action.
      </div>
    </div>
  </header>
  <main class="page">
    <section class="panel">
      <h2>Evidence components</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Family / component</th>
              <th>Market / scope</th>
              <th>Status</th>
              <th>Freshness</th>
              <th>Input interval</th>
              <th>Lookback</th>
              <th>Effective horizon</th>
              <th>Observed lifecycle</th>
              <th>As-of</th>
              <th>Model</th>
              <th>Raw evidence</th>
              <th>Reason codes</th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""
