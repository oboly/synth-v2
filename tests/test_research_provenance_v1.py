"""
Tests for src/decision_gate/research_provenance_v1.py.

Pure Python — no DB, no broker, no network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.decision_gate.research_provenance_v1 import (
    INGESTION_STATUS_UPLOADED_NOT_INGESTED,
    OVERRIDE_SCOPE_SINGLE_INSTANCE_MANUAL_EXECUTION_ONLY,
    SOURCE_CLASSIFICATION_EXTERNAL_UPLOAD_RESEARCH,
    ResearchProvenanceValidationError,
    build_research_provenance_record,
    validate_override_for_use,
)


NOW = datetime(2026, 7, 25, 20, 0, 0, tzinfo=timezone.utc)
VALID_SHA256 = "a" * 64


def _build(**overrides):
    defaults = dict(
        source_classification=SOURCE_CLASSIFICATION_EXTERNAL_UPLOAD_RESEARCH,
        source_path_or_identifier="theone:synth-data/uploads/aplus/inbox/aplus_raw_...md",
        source_sha256=VALID_SHA256,
        source_ts_utc=NOW - timedelta(days=1),
        ingestion_status=INGESTION_STATUS_UPLOADED_NOT_INGESTED,
        override_scope=OVERRIDE_SCOPE_SINGLE_INSTANCE_MANUAL_EXECUTION_ONLY,
        approving_user="joost",
        approval_ts_utc=NOW,
        allowed_assets=("BTC", "RED"),
        allowed_side="SELL",
        preview_permission=True,
        live_permission=False,
        expires_ts_utc=NOW + timedelta(hours=1),
        single_use=True,
    )
    defaults.update(overrides)
    return build_research_provenance_record(**defaults)


class TestConstructionGuardsGovernance:
    def test_valid_record_builds(self) -> None:
        record = _build()
        assert record.selection_weight == Decimal("0")
        assert record.decision_weight == Decimal("0")
        assert record.live_permission is False
        assert record.allowed_assets == ("BTC", "RED")

    def test_nonzero_selection_weight_rejected(self) -> None:
        with pytest.raises(ResearchProvenanceValidationError):
            _build(selection_weight=Decimal("0.1"))

    def test_nonzero_decision_weight_rejected(self) -> None:
        with pytest.raises(ResearchProvenanceValidationError):
            _build(decision_weight=Decimal("0.1"))

    def test_live_permission_true_rejected(self) -> None:
        with pytest.raises(ResearchProvenanceValidationError):
            _build(live_permission=True)

    def test_bad_sha256_rejected(self) -> None:
        with pytest.raises(ResearchProvenanceValidationError):
            _build(source_sha256="not-a-sha256")

    def test_empty_allowed_assets_rejected(self) -> None:
        with pytest.raises(ResearchProvenanceValidationError):
            _build(allowed_assets=())

    def test_unknown_ingestion_status_rejected(self) -> None:
        with pytest.raises(ResearchProvenanceValidationError):
            _build(ingestion_status="MYSTERIOUSLY_PROMOTED")

    def test_invalid_side_rejected(self) -> None:
        with pytest.raises(ResearchProvenanceValidationError):
            _build(allowed_side="HOLD")


class TestOverrideScopeValidation:
    def test_authorized_asset_and_side_passes(self) -> None:
        record = _build()
        ok, reasons = validate_override_for_use(
            record, asset_symbol="BTC", side="SELL", now=NOW,
        )
        assert ok
        assert reasons == ()

    def test_asset_outside_scope_blocked(self) -> None:
        record = _build()
        ok, reasons = validate_override_for_use(
            record, asset_symbol="ETH", side="SELL", now=NOW,
        )
        assert not ok
        assert "ASSET_NOT_IN_ALLOWED_SCOPE" in reasons

    def test_side_outside_scope_blocked(self) -> None:
        record = _build(allowed_side="SELL")
        ok, reasons = validate_override_for_use(
            record, asset_symbol="BTC", side="BUY", now=NOW,
        )
        assert not ok
        assert "SIDE_NOT_IN_ALLOWED_SCOPE" in reasons

    def test_both_side_scope_allows_either(self) -> None:
        record = _build(allowed_side="BOTH")
        ok, _ = validate_override_for_use(record, asset_symbol="BTC", side="BUY", now=NOW)
        assert ok
        ok, _ = validate_override_for_use(record, asset_symbol="BTC", side="SELL", now=NOW)
        assert ok

    def test_live_use_blocked_when_live_permission_false(self) -> None:
        record = _build()
        ok, reasons = validate_override_for_use(
            record, asset_symbol="BTC", side="SELL", now=NOW, for_live=True,
        )
        assert not ok
        assert "LIVE_PERMISSION_NOT_GRANTED" in reasons

    def test_preview_use_blocked_when_preview_permission_false(self) -> None:
        record = _build(preview_permission=False)
        ok, reasons = validate_override_for_use(
            record, asset_symbol="BTC", side="SELL", now=NOW, for_live=False,
        )
        assert not ok
        assert "PREVIEW_PERMISSION_NOT_GRANTED" in reasons

    def test_expired_override_blocked(self) -> None:
        record = _build(expires_ts_utc=NOW - timedelta(minutes=1))
        ok, reasons = validate_override_for_use(
            record, asset_symbol="BTC", side="SELL", now=NOW,
        )
        assert not ok
        assert "OVERRIDE_EXPIRED" in reasons

    def test_single_use_already_consumed_blocked(self) -> None:
        record = _build()
        consumed = record.__class__(**{**record.__dict__, "consumed_ts_utc": NOW})
        ok, reasons = validate_override_for_use(
            consumed, asset_symbol="BTC", side="SELL", now=NOW,
        )
        assert not ok
        assert "OVERRIDE_ALREADY_CONSUMED" in reasons

    def test_no_expiry_record_still_checked_for_other_conditions(self) -> None:
        record = _build(expires_ts_utc=None)
        ok, reasons = validate_override_for_use(
            record, asset_symbol="BTC", side="SELL", now=NOW + timedelta(days=365),
        )
        assert ok
        assert reasons == ()
