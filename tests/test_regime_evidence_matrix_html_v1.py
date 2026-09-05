from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.reporting.regime_evidence_matrix_html_v1 import render_regime_evidence_matrix_html
from src.reporting.regime_evidence_matrix_v1 import RegimeEvidenceCellV1, build_matrix, unavailable_cell


EVALUATED = datetime(2026, 9, 5, 3, 15, tzinfo=UTC)
ASOF = datetime(2026, 9, 5, 3, 0, tzinfo=UTC)


def _cell(**overrides: object) -> RegimeEvidenceCellV1:
    values: dict[str, object] = {
        "family": "MOMENTUM",
        "component": "MACD",
        "market": "BTC-EUR",
        "scope_key": "venue=bitvavo;asset_id=1;market=BTC-EUR",
        "status": "INSUFFICIENT_DATA",
        "freshness": "UNKNOWN",
        "asof_ts": ASOF,
        "model_id": "momentum_evidence_snapshot",
        "model_version": "1.0",
        "input_interval": "4h",
        "lookback_horizon": "35 bars @ 4h",
        "effective_horizon": "UNKNOWN",
        "observed_lifecycle": "UNMEASURED",
        "raw": {
            "macd_value": Decimal("1.25"),
            "signal_value": Decimal("1.00"),
            "histogram_value": Decimal("0.25"),
        },
        "reason_codes": ("UNMAPPED_HORIZON", "FRESHNESS_NOT_OWNER_DEFINED"),
        "provenance": {"venue": "bitvavo", "asset_id": 1},
        "source_contract": "MomentumEvidenceSnapshot",
    }
    values.update(overrides)
    return RegimeEvidenceCellV1(**values)  # type: ignore[arg-type]


def test_renderer_exposes_source_owned_evidence_and_metadata() -> None:
    matrix = build_matrix(evaluated_at=EVALUATED, cells=[_cell()])

    rendered = render_regime_evidence_matrix_html(matrix)

    assert "MOMENTUM" in rendered
    assert "MACD" in rendered
    assert "BTC-EUR" in rendered
    assert "INSUFFICIENT_DATA" in rendered
    assert "UNKNOWN" in rendered
    assert "35 bars @ 4h" in rendered
    assert "UNMEASURED" in rendered
    assert "momentum_evidence_snapshot" in rendered
    assert "1.25" in rendered
    assert "UNMAPPED_HORIZON" in rendered
    assert "FRESHNESS_NOT_OWNER_DEFINED" in rendered


def test_renderer_unavailable_family_is_visible_as_text_not_color_only() -> None:
    cell = unavailable_cell(family="VOLATILITY", detail="no canonical owner")
    matrix = build_matrix(evaluated_at=EVALUATED, cells=[cell])

    rendered = render_regime_evidence_matrix_html(matrix)

    assert "VOLATILITY" in rendered
    assert "INSUFFICIENT_DATA" in rendered
    assert "NO_CANONICAL_OWNER" in rendered


def test_renderer_does_not_invent_regime_or_trade_states() -> None:
    matrix = build_matrix(evaluated_at=EVALUATED, cells=[_cell()])

    rendered = render_regime_evidence_matrix_html(matrix)

    for forbidden in (
        "EARLY_UP",
        "MOMENTUM_REVERSAL",
        "ETH_LED",
        "BTC_LED",
        "BUY_READY",
        "SELL",
        "UPTREND_EMERGING",
    ):
        assert forbidden not in rendered


def test_renderer_escapes_market_raw_keys_values_and_reason_codes() -> None:
    cell = _cell(
        market="<script>alert(1)</script>",
        raw={"<key>": "<img src=x onerror=alert(1)>"},
        reason_codes=("<REASON>",),
    )
    matrix = build_matrix(evaluated_at=EVALUATED, cells=[cell])

    rendered = render_regime_evidence_matrix_html(matrix)

    assert "<script>alert(1)</script>" not in rendered
    assert "<img src=x onerror=alert(1)>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "&lt;key&gt;" in rendered
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "&lt;REASON&gt;" in rendered


def test_renderer_preserves_structured_lifecycle_content() -> None:
    cell = _cell(observed_lifecycle={"status": "MEASURED", "median_seconds": 7200})
    matrix = build_matrix(evaluated_at=EVALUATED, cells=[cell])

    rendered = render_regime_evidence_matrix_html(matrix)

    assert "status=MEASURED" in rendered
    assert "median_seconds=7200" in rendered


def test_renderer_is_deterministic_for_identical_matrix() -> None:
    matrix = build_matrix(evaluated_at=EVALUATED, cells=[_cell()])

    assert render_regime_evidence_matrix_html(matrix) == render_regime_evidence_matrix_html(matrix)
