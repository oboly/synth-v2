from __future__ import annotations

import dataclasses

from src.reporting.fib_coverage_classification_v1 import (
    CANONICAL_SCOPE_ENROLLED,
    CANONICAL_SCOPE_NOT_ENROLLED,
    NATIVE_ROW_ABSENT,
    NATIVE_ROW_PARTIAL,
    NATIVE_SCOPE_NOT_APPLICABLE,
    NATIVE_SCOPE_SUPPORTED,
    NATIVE_SCOPE_UNKNOWN,
    ORIGIN_ACCOUNT_ASSET_CONFIG,
    ORIGIN_ACCOUNT_OPEN_ORDER,
    ORIGIN_ACCOUNT_POSITION_HELD,
    ORIGIN_GLOBAL_PUBLICATION_COHORT,
    ORIGIN_UNKNOWN,
    CANONICAL_ROW_SOURCE_UNAVAILABLE,
    REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE,
    REASON_FIB_MAP_AVAILABLE,
    REASON_FIB_MAP_EXPECTED_BUT_MISSING,
    REASON_FIB_MAP_NOT_ENROLLED,
    REASON_FIB_MAP_SOURCE_UNAVAILABLE,
    REASON_NATIVE_SHORT_CONTEXT_PARTIAL,
    REASON_NATIVE_SHORT_EXPECTED_BUT_MISSING,
    REASON_NOT_APPLICABLE,
    classify_fib_coverage,
    fib_coverage_reason_text,
    summarize_fib_coverage_reasons,
)
from src.reporting.manual_short_trader_profit_plan_v1 import (
    CardEvidence,
    apply_fib_coverage_classification,
    build_json_snapshot,
    build_profit_plan_card,
)


def _classify(**overrides):
    kwargs = dict(
        short_context_coverage_status="FIB_MAP_SYMBOL_MISSING",
        short_context_input_status="ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING",
        is_market_selected=False,
        is_core_sensor=False,
        is_wallet_held=False,
        is_portfolio_asset=False,
        has_open_order=False,
        native_short_scope_state=NATIVE_SCOPE_UNKNOWN,
    )
    kwargs.update(overrides)
    return classify_fib_coverage(**kwargs)


def test_a_canonical_enrolled_row_present_is_available():
    """A. canonical 4h enrolled + row present => available, no false warning."""
    result = _classify(
        short_context_coverage_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        short_context_input_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        is_market_selected=True,
    )
    assert result.canonical_fib_scope_state == CANONICAL_SCOPE_ENROLLED
    assert result.fib_coverage_reason == REASON_FIB_MAP_AVAILABLE
    assert fib_coverage_reason_text(result) is None


def test_b_canonical_enrolled_row_absent_is_expected_but_missing():
    """B. canonical 4h enrolled + row absent => EXPECTED_BUT_MISSING."""
    result = _classify(is_market_selected=True)
    assert result.canonical_fib_scope_state == CANONICAL_SCOPE_ENROLLED
    assert result.fib_coverage_reason == REASON_FIB_MAP_EXPECTED_BUT_MISSING
    assert result.fib_coverage_reason != "FIB_MAP_SYMBOL_MISSING"


def test_c_not_enrolled_held_overlay_is_overlay_outside_scope():
    """C. canonical 4h not enrolled + account-held overlay => overlay-outside-scope."""
    result = _classify(is_wallet_held=True)
    assert result.canonical_fib_scope_state == CANONICAL_SCOPE_NOT_ENROLLED
    assert result.rendered_scope_origin == ORIGIN_ACCOUNT_POSITION_HELD
    assert result.fib_coverage_reason == REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE


def test_d_not_enrolled_open_order_overlay_is_truthful_non_enrolled():
    """D. canonical 4h not enrolled + open-order overlay => truthful non-enrolled classification."""
    result = _classify(has_open_order=True)
    assert result.canonical_fib_scope_state == CANONICAL_SCOPE_NOT_ENROLLED
    assert result.rendered_scope_origin == ORIGIN_ACCOUNT_OPEN_ORDER
    assert result.fib_coverage_reason == REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE


def test_e_native_unsupported_with_canonical_present_stays_available():
    """E. native SHORT unsupported + canonical 4h present => canonical navigation
    still valid; native unsupported remains separate metadata."""
    result = _classify(
        short_context_coverage_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        short_context_input_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        is_market_selected=True,
        native_short_scope_state=NATIVE_SCOPE_NOT_APPLICABLE,
    )
    assert result.fib_coverage_reason == REASON_FIB_MAP_AVAILABLE
    assert result.native_short_scope_state == NATIVE_SCOPE_NOT_APPLICABLE
    assert result.native_short_row_state == NATIVE_ROW_ABSENT


def test_f_native_supported_row_absent_is_distinct_expected_but_missing():
    """F. native SHORT expected/supported + native row absent => distinct
    expected-but-missing native classification, independent of canonical state."""
    result = _classify(
        short_context_coverage_status="INSUFFICIENT_4H_HISTORY",
        short_context_input_status="INSUFFICIENT_4H_HISTORY",
        native_short_scope_state=NATIVE_SCOPE_SUPPORTED,
    )
    assert result.native_short_scope_state == NATIVE_SCOPE_SUPPORTED
    # A partial/insufficient native row is not the same as no row at all.
    assert result.native_short_row_state != "AVAILABLE"


def test_g_native_row_absent_canonical_available_not_globally_missing():
    """G. native SHORT row absent but canonical 4h row present => never
    classify the card globally as Fib missing."""
    result = _classify(
        short_context_coverage_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        short_context_input_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        is_market_selected=True,
        native_short_scope_state=NATIVE_SCOPE_UNKNOWN,
    )
    assert result.fib_coverage_reason == REASON_FIB_MAP_AVAILABLE


def test_h_no_native_no_canonical_not_enrolled_is_not_generic_missing():
    """H. no native + no canonical + not enrolled => NOT_ENROLLED-family
    reason, never the generic old FIB_MAP_SYMBOL_MISSING label."""
    result = _classify()
    assert result.canonical_fib_scope_state == CANONICAL_SCOPE_NOT_ENROLLED
    assert result.fib_coverage_reason in {
        REASON_FIB_MAP_NOT_ENROLLED,
        REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE,
    }
    assert result.fib_coverage_reason != "FIB_MAP_SYMBOL_MISSING"


def test_h_unknown_origin_falls_back_to_not_enrolled():
    result = _classify()
    assert result.rendered_scope_origin == ORIGIN_UNKNOWN
    assert result.fib_coverage_reason == REASON_FIB_MAP_NOT_ENROLLED


def test_i_no_native_no_canonical_enrollment_expected_is_expected_but_missing():
    """I. no native + no canonical + canonical enrollment expected => EXPECTED_BUT_MISSING."""
    result = _classify(is_core_sensor=True)
    assert result.canonical_fib_scope_state == CANONICAL_SCOPE_ENROLLED
    assert result.rendered_scope_origin == ORIGIN_GLOBAL_PUBLICATION_COHORT
    assert result.fib_coverage_reason == REASON_FIB_MAP_EXPECTED_BUT_MISSING


def test_source_missing_enrolled_symbol_stays_source_unavailable():
    """FIB_MAP_SOURCE_MISSING means the whole canonical source failed to load --
    even for an enrolled symbol, that must never be reported as
    FIB_MAP_EXPECTED_BUT_MISSING (a per-symbol conclusion the source outage
    cannot support)."""
    result = _classify(
        short_context_coverage_status="FIB_MAP_SOURCE_MISSING",
        short_context_input_status="ZONE_SOURCE_MISSING",
        is_market_selected=True,
    )
    assert result.canonical_fib_row_state == CANONICAL_ROW_SOURCE_UNAVAILABLE
    assert result.fib_coverage_reason == REASON_FIB_MAP_SOURCE_UNAVAILABLE
    assert result.fib_coverage_reason != REASON_FIB_MAP_EXPECTED_BUT_MISSING


def test_source_missing_not_enrolled_overlay_symbol_stays_source_unavailable():
    """FIB_MAP_SOURCE_MISSING + an account-overlay, not-enrolled symbol must
    also avoid a per-symbol enrollment/scope conclusion -- the source outage
    is not evidence the symbol is out of Fib scope."""
    result = _classify(
        short_context_coverage_status="FIB_MAP_SOURCE_MISSING",
        short_context_input_status="ZONE_SOURCE_MISSING",
        is_wallet_held=True,
    )
    assert result.canonical_fib_row_state == CANONICAL_ROW_SOURCE_UNAVAILABLE
    assert result.fib_coverage_reason == REASON_FIB_MAP_SOURCE_UNAVAILABLE
    assert result.fib_coverage_reason != REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE
    assert result.fib_coverage_reason != REASON_FIB_MAP_NOT_ENROLLED


def test_manual_asset_config_overlay_origin():
    result = _classify(is_portfolio_asset=True)
    assert result.rendered_scope_origin == ORIGIN_ACCOUNT_ASSET_CONFIG
    assert result.fib_coverage_reason == REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE


def test_native_supported_absent_no_canonical_exposes_gap_not_not_applicable():
    """native SHORT SUPPORTED + ABSENT + no usable canonical authority must
    expose NATIVE_SHORT_EXPECTED_BUT_MISSING, never silently collapse into
    NOT_APPLICABLE (that would suppress a real supported-native coverage
    gap)."""
    result = _classify(
        short_context_coverage_status="LEGACY_1D_CONTEXT_ONLY",
        short_context_input_status="LEGACY_1D_CONTEXT_ONLY",
        native_short_scope_state=NATIVE_SCOPE_SUPPORTED,
    )
    assert result.native_short_scope_state == NATIVE_SCOPE_SUPPORTED
    assert result.native_short_row_state == NATIVE_ROW_ABSENT
    assert result.fib_coverage_reason == REASON_NATIVE_SHORT_EXPECTED_BUT_MISSING
    assert result.fib_coverage_reason != REASON_NOT_APPLICABLE


def test_native_supported_partial_no_canonical_exposes_gap_not_not_applicable():
    """native SHORT SUPPORTED + PARTIAL + no usable canonical authority must
    expose NATIVE_SHORT_CONTEXT_PARTIAL, never NOT_APPLICABLE."""
    result = _classify(
        short_context_coverage_status="MARKET_DATA_MISSING",
        short_context_input_status="MARKET_DATA_MISSING",
        native_short_scope_state=NATIVE_SCOPE_SUPPORTED,
    )
    assert result.native_short_scope_state == NATIVE_SCOPE_SUPPORTED
    assert result.native_short_row_state == NATIVE_ROW_PARTIAL
    assert result.fib_coverage_reason == REASON_NATIVE_SHORT_CONTEXT_PARTIAL
    assert result.fib_coverage_reason != REASON_NOT_APPLICABLE


def test_native_supported_absent_with_canonical_available_stays_available_but_explicit():
    """native SHORT SUPPORTED + ABSENT, but canonical 4h IS available: overall
    usable Fib authority stays FIB_MAP_AVAILABLE, while the native gap
    remains explicit via native_short_scope_state/native_short_row_state
    (never silently dropped)."""
    result = _classify(
        short_context_coverage_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        short_context_input_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        is_market_selected=True,
        native_short_scope_state=NATIVE_SCOPE_SUPPORTED,
    )
    assert result.fib_coverage_reason == REASON_FIB_MAP_AVAILABLE
    assert result.native_short_scope_state == NATIVE_SCOPE_SUPPORTED
    assert result.native_short_row_state == NATIVE_ROW_ABSENT


def test_production_shape_seven_no_row_cards_are_not_all_broken():
    """L. the observed 60/53/7 production shape can be represented without
    calling all seven no-row cards broken -- some are truthfully not-enrolled
    overlay extensions, distinct from an expected-but-missing publication."""
    not_enrolled_but_held = _classify(is_wallet_held=True)
    enrolled_but_missing = _classify(is_market_selected=True)
    assert not_enrolled_but_held.fib_coverage_reason != enrolled_but_missing.fib_coverage_reason
    assert not_enrolled_but_held.fib_coverage_reason == REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE
    assert enrolled_but_missing.fib_coverage_reason == REASON_FIB_MAP_EXPECTED_BUT_MISSING


def test_k_summary_counts_reconcile_exactly_to_per_symbol_classifications():
    """K. summary counts equal exact per-symbol bucket counts; no double-counting
    a card across mutually exclusive final Fib coverage states."""
    classifications = [
        _classify(short_context_coverage_status="CANONICAL_4H_CONTEXT_AVAILABLE",
                  short_context_input_status="CANONICAL_4H_CONTEXT_AVAILABLE", is_market_selected=True),
        _classify(is_market_selected=True),
        _classify(is_wallet_held=True),
        _classify(has_open_order=True),
        _classify(is_portfolio_asset=True),
        _classify(),
        _classify(is_core_sensor=True),
    ]
    summary = summarize_fib_coverage_reasons(classifications)
    assert sum(summary.values()) == len(classifications)
    for classification in classifications:
        assert classification.fib_coverage_reason in summary


def _card_with_overlays(
    *,
    is_market_selected: bool = False,
    is_core_sensor: bool = False,
    is_wallet_held: bool = False,
    is_portfolio_asset: bool = False,
):
    card = build_profit_plan_card(
        symbol="PLUME",
        market="PLUME-EUR",
        current_price=None,
        short_context_input_status="ZONE_SOURCE_PRESENT_BUT_SYMBOL_MISSING",
        short_context_coverage_status="FIB_MAP_SYMBOL_MISSING",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        current_price_status="MISSING_CURRENT_PRICE",
        evidence=CardEvidence(),
    )
    return dataclasses.replace(
        card,
        current_price=None,
        is_market_selected=is_market_selected,
        is_core_sensor=is_core_sensor,
        is_wallet_held=is_wallet_held,
        is_portfolio_asset=is_portfolio_asset,
    )


def test_apply_fib_coverage_classification_is_additive_to_existing_status():
    """Existing short_context_coverage_status must stay untouched -- this is a
    purely additive classification, not a replacement of the legacy status
    consumed elsewhere (scenario/action derivation, existing summaries)."""
    cards = [_card_with_overlays(is_wallet_held=True)]
    out = apply_fib_coverage_classification(
        cards,
        open_order_count_by_market={},
        native_short_scope_state_by_symbol={},
    )
    assert out[0].short_context_coverage_status == "FIB_MAP_SYMBOL_MISSING"
    assert out[0].fib_coverage is not None
    assert out[0].fib_coverage.fib_coverage_reason == REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE


def test_j_json_and_html_reason_expose_same_state():
    """J. JSON and HTML expose the same reason/state -- HTML renders card.reasons
    directly, so the JSON classification and the appended card reason text
    must agree, not be independently derived."""
    cards = [_card_with_overlays(is_wallet_held=True)]
    out = apply_fib_coverage_classification(
        cards,
        open_order_count_by_market={},
        native_short_scope_state_by_symbol={},
    )
    card = out[0]
    reason_text = fib_coverage_reason_text(card.fib_coverage)
    assert reason_text is not None
    assert reason_text in card.reasons

    snapshot = build_json_snapshot(out)
    json_entry = snapshot["symbols"][0]["fib_coverage_classification"]
    assert json_entry == card.fib_coverage.to_json()
    assert json_entry["fib_coverage_reason"] == REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE
    assert snapshot["fib_coverage_summary"][REASON_ACCOUNT_OVERLAY_OUTSIDE_FIB_SCOPE] == 1


def test_native_short_gap_json_and_html_reason_expose_same_final_reason():
    """A supported-but-missing native SHORT gap (no usable canonical
    fallback) must show the actual final fib_coverage_reason -- not merely
    a native_short_row_state assertion -- identically in card.reasons
    (HTML's source) and the JSON classification block."""
    card = _card_with_overlays()
    card = dataclasses.replace(
        card,
        short_context_coverage_status="LEGACY_1D_CONTEXT_ONLY",
        short_context_input_status="LEGACY_1D_CONTEXT_ONLY",
    )
    out = apply_fib_coverage_classification(
        [card],
        open_order_count_by_market={},
        native_short_scope_state_by_symbol={"PLUME": "SUPPORTED"},
    )
    result_card = out[0]
    assert result_card.fib_coverage.fib_coverage_reason == REASON_NATIVE_SHORT_EXPECTED_BUT_MISSING

    reason_text = fib_coverage_reason_text(result_card.fib_coverage)
    assert reason_text is not None
    assert reason_text in result_card.reasons

    snapshot = build_json_snapshot(out)
    json_entry = snapshot["symbols"][0]["fib_coverage_classification"]
    assert json_entry["fib_coverage_reason"] == REASON_NATIVE_SHORT_EXPECTED_BUT_MISSING
    assert json_entry == result_card.fib_coverage.to_json()
    assert snapshot["fib_coverage_summary"][REASON_NATIVE_SHORT_EXPECTED_BUT_MISSING] == 1
    assert snapshot["fib_coverage_summary"][REASON_NOT_APPLICABLE] == 0


def test_apply_fib_coverage_classification_does_not_duplicate_reason_on_reapply():
    cards = [_card_with_overlays(is_wallet_held=True)]
    once = apply_fib_coverage_classification(
        cards, open_order_count_by_market={}, native_short_scope_state_by_symbol={}
    )
    twice = apply_fib_coverage_classification(
        once, open_order_count_by_market={}, native_short_scope_state_by_symbol={}
    )
    assert once[0].reasons == twice[0].reasons


def test_available_card_gets_no_supplemental_reason():
    card = _card_with_overlays(is_market_selected=True)
    card = dataclasses.replace(
        card,
        short_context_coverage_status="CANONICAL_4H_CONTEXT_AVAILABLE",
        short_context_input_status="CANONICAL_4H_CONTEXT_AVAILABLE",
    )
    out = apply_fib_coverage_classification(
        [card], open_order_count_by_market={}, native_short_scope_state_by_symbol={}
    )
    assert out[0].fib_coverage.fib_coverage_reason == REASON_FIB_MAP_AVAILABLE
    assert out[0].reasons == card.reasons
