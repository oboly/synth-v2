"""Golden regression fixtures for Manual Trader Dashboard V1 freeze (Issue #558).

This module freezes ten deterministic ``ProfitPlanCard`` scenarios that
together exercise the canonical Manual Trader Dashboard V1 contract described
in ``docs/architecture/manual_trader_dashboard_v1.md``:

 1. valid immediate/actionable setup (numeric Actionable PPP, ACTIVE)
 2. valid "wait for entry" reload setup with numeric Actionable PPP
 3. wait-for-reclaim equivalent (entry above current price, no Actionable PPP)
 4. invalidated setup
 5. stale evidence (STALE_CURRENT_PRICE)
 6. unavailable evidence (missing current price / zone context)
 7. active map with complete Fibonacci levels
 8. completed/passed levels (MAP_COMPLETED reference state)
 9. FET-like contradiction case from Issue #550
10. TAO-like contradiction case from Issue #550

These fixtures reuse the existing canonical card-construction helpers from
``tests/test_profit_plan_provenance_v1.py`` and
``tests/test_manual_short_trader_profit_plan_v1.py`` rather than introducing a
parallel model. No production code is changed by this module.

Safety: reporting-only. broker_writes=0 order_submission=0 executor=none.
"""
from __future__ import annotations

import dataclasses
import re
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable

import pytest

import src.reporting.manual_short_trader_profit_plan_v1 as pp
import src.reporting.run_manual_short_trader_profit_plan_v1 as profit_plan_runner
from src.market_data.native_short_fib_context_v1 import NativeShortContextRow, write_context_rows
from src.reporting.manual_short_trader_profit_plan_v1 import (
    CARD_MODE_POSITION_HELD,
    CardEvidence,
    FibExtContext,
    ProfitPlanCard,
    ReentryContext,
    build_json_snapshot,
    build_profit_plan_card,
    make_planning_provenance,
    render_full_html,
    render_plan_card,
)

from tests.test_manual_short_trader_profit_plan_v1 import (
    _active_level_status as _shared_active_level_status,
    _near_like_card,
    _passed_level_status as _shared_passed_level_status,
)
from tests.test_profit_plan_provenance_v1 import (
    _activated_card,
    _active_map_evidence,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# ---------------------------------------------------------------------------
# Scenario 1: valid immediate/actionable setup
# ---------------------------------------------------------------------------

def _golden_01_valid_immediate_actionable() -> ProfitPlanCard:
    return _activated_card(evidence=_active_map_evidence())


# ---------------------------------------------------------------------------
# Scenario 2: valid "wait for entry" reload setup, numeric Actionable PPP
# ---------------------------------------------------------------------------

def _golden_02_wait_for_entry_numeric_ppp() -> ProfitPlanCard:
    fet_reentry = ReentryContext(
        r382_price=Decimal("0.2142"),
        r500_price=Decimal("0.2050"),
        r618_price=Decimal("0.1958"),
        r786_price=Decimal("0.1827"),
        deepest_touched_label="retrace_0_382",
        missed_main_rebuy_by_pct=Decimal("1.95"),
    )
    fib_ext = FibExtContext(
        local_reaction_price=Decimal("0.2500"),
        anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
        ext_1_272=Decimal("0.4500"),
        ext_1_618=Decimal("0.5200"),
        ext_2_000=Decimal("0.8000"),
        breakout_gate=Decimal("0.3000"),
        price_band="BELOW_BREAKOUT_GATE",
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=False,
    )
    return build_profit_plan_card(
        symbol="FET",
        market="FET-EUR",
        current_price=Decimal("0.21"),
        fib_ext=fib_ext,
        reentry=fet_reentry,
        history_high_since_activation=Decimal("0.4600"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=_active_map_evidence(map_cycle_id="FET|SHORT|4h|demo"),
        planning_provenance=make_planning_provenance(
            entry_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
            target_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
        ),
    )


# ---------------------------------------------------------------------------
# Scenario 3: wait-for-reclaim equivalent (entry above current, no Actionable PPP)
# ---------------------------------------------------------------------------

def _golden_03_wait_for_reclaim_no_ppp() -> ProfitPlanCard:
    reentry = ReentryContext(
        r382_price=Decimal("0.90"),
        r500_price=Decimal("0.80"),
        r618_price=Decimal("0.73"),
        r786_price=Decimal("0.60"),
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )
    fib_ext = FibExtContext(
        local_reaction_price=Decimal("0.95"),
        anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
        ext_1_272=Decimal("1.10"),
        ext_1_618=Decimal("1.30"),
        ext_2_000=Decimal("1.60"),
        breakout_gate=Decimal("1.00"),
        price_band="BELOW_BREAKOUT_GATE",
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=False,
    )
    return build_profit_plan_card(
        symbol="ONDO",
        market="ONDO-EUR",
        current_price=Decimal("0.70"),
        fib_ext=fib_ext,
        reentry=reentry,
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        # DATA_UNAVAILABLE lifecycle blocks Actionable PPP (Issue #457 hardening)
        # while the reload ladder is genuinely above current price -- the exact
        # shape _entry_wait_label() reports as "wait for reclaim".
        evidence=_active_map_evidence(
            map_cycle_id="ONDO|SHORT|4h|demo",
            lifecycle_state="DATA_UNAVAILABLE",
        ),
        planning_provenance=make_planning_provenance(
            entry_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
            target_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
        ),
    )


# ---------------------------------------------------------------------------
# Scenario 4: invalidated setup
# ---------------------------------------------------------------------------

def _golden_04_invalidated_setup() -> ProfitPlanCard:
    fet_reentry = ReentryContext(
        r382_price=Decimal("0.2142"),
        r500_price=Decimal("0.2050"),
        r618_price=Decimal("0.1958"),
        r786_price=Decimal("0.1827"),
        deepest_touched_label="retrace_0_382",
        missed_main_rebuy_by_pct=Decimal("1.95"),
    )
    fib_ext = FibExtContext(
        local_reaction_price=Decimal("0.2500"),
        anchor_end_ts_utc=datetime(2026, 6, 1, tzinfo=UTC),
        ext_1_272=Decimal("0.4500"),
        ext_1_618=Decimal("0.5200"),
        ext_2_000=Decimal("0.8000"),
        breakout_gate=Decimal("0.3000"),
        price_band="BELOW_BREAKOUT_GATE",
        ext_1_272_touched_and_rejected=False,
        retesting_breakout_gate=False,
    )
    # current_price (0.16) is below the r786 invalidation level (0.1827).
    return build_profit_plan_card(
        symbol="FET",
        market="FET-EUR",
        current_price=Decimal("0.16"),
        fib_ext=fib_ext,
        reentry=fet_reentry,
        history_high_since_activation=Decimal("0.4600"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=_active_map_evidence(map_cycle_id="FET|SHORT|4h|demo"),
        planning_provenance=make_planning_provenance(
            entry_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
            target_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
        ),
    )


# ---------------------------------------------------------------------------
# Scenario 5: stale evidence
# ---------------------------------------------------------------------------

def _golden_05_stale_evidence() -> ProfitPlanCard:
    return build_profit_plan_card(
        symbol="SOL",
        market="SOL-EUR",
        current_price=Decimal("140.00"),
        current_price_status="STALE_CURRENT_PRICE",
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
    )


# ---------------------------------------------------------------------------
# Scenario 6: unavailable evidence
# ---------------------------------------------------------------------------

def _golden_06_unavailable_evidence() -> ProfitPlanCard:
    return build_profit_plan_card(
        symbol="XLM",
        market="XLM-EUR",
        current_price=None,
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="FIB_MAP_SYMBOL_MISSING",
        presentation_mode=CARD_MODE_POSITION_HELD,
    )


# ---------------------------------------------------------------------------
# Scenario 7: active map with complete Fibonacci levels
# ---------------------------------------------------------------------------

def _native_short_row_for_map(symbol: str, *, current_map_status: str) -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol=symbol,
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        map_cycle_id=f"{symbol}|SHORT|4h|demo",
        anchor_start_ts_utc=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        anchor_end_ts_utc=datetime(2026, 6, 2, 0, 0, tzinfo=UTC),
        anchor_low_price=Decimal("0.3000"),
        anchor_high_price=Decimal("0.3800"),
        breakout_gate_price=Decimal("0.3800"),
        latest_primary_close_ts_utc=datetime(2026, 6, 5, 8, 0, tzinfo=UTC),
        latest_support_close_ts_utc=datetime(2026, 6, 5, 11, 0, tzinfo=UTC),
        latest_primary_close_price=Decimal("0.4700"),
        ext_1_272_price=Decimal("0.454438"),
        ext_1_618_price=Decimal("0.515600"),
        ext_2_000_price=Decimal("0.6200"),
        active_target_levels=(Decimal("0.515600"), Decimal("0.6200")),
        previous_target_levels=(Decimal("0.454438"),),
        reload_r382_price=Decimal("0.3494"),
        reload_r500_price=Decimal("0.3400"),
        reload_r618_price=Decimal("0.3306"),
        reload_r786_price=Decimal("0.3171"),
        invalidation_price=Decimal("0.3000"),
        primary_4h_lifecycle_state="ACTIVE_4H_EXTENSION",
        supporting_1h_state="ALIGNED_WITH_4H",
        context_freshness_status="FRESH",
        max_primary_high_since_anchor=Decimal("0.4700"),
        min_primary_low_since_anchor=Decimal("0.3300"),
        source_name="native_short_fib_context_v1",
        source_version="0.1",
        source_primary_ref="obs_market_candle:4h",
        source_support_ref="obs_market_candle:1h",
        current_map_status=current_map_status,
        previous_map_cycle_id="",
        previous_map_lifecycle_state="",
        rollover_state="SINGLE_MAP",
        selection_reason="Single active map selected",
    )


def _card_from_native_row(symbol: str, *, current_map_status: str) -> ProfitPlanCard:
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = Path(tmpdir) / "fibo_target_map_rows_v1.csv"
        fib_rows.write_text(
            "symbol,current_price,swing_low_price,swing_high_price,local_reaction_price,next_fibo_support_price\n",
            encoding="utf-8",
        )
        native_dir = Path(tmpdir) / "native"
        native_paths = write_context_rows(
            rows=[_native_short_row_for_map(symbol, current_map_status=current_map_status)],
            output_dir=native_dir,
        )
        result = profit_plan_runner.load_zone_contexts(
            markets=[f"{symbol}-EUR"],
            prices={f"{symbol}-EUR": Decimal("0.4560")},
            swing_anchors={},
            recent_lows={},
            native_short_rows_path=native_paths["rows_csv"],
            fib_map_rows_path=fib_rows,
            native_short_snapshot_status="loaded",
            native_short_snapshot_id="nsctx-v1-test-snapshot",
        )
        evidence = result.evidence_by_symbol[symbol]
        return build_profit_plan_card(
            symbol=symbol,
            market=f"{symbol}-EUR",
            current_price=Decimal("0.4560"),
            fib_trading_horizon="SHORT",
            short_context_input_status=result.input_status_by_symbol[symbol],
            short_context_coverage_status=result.coverage_status_by_symbol[symbol],
            short_context_display_state=result.display_state_by_symbol[symbol],
            fib_ext=result.fib_ext_by_symbol.get(symbol),
            reentry=result.reentry_by_symbol.get(symbol),
            presentation_mode=CARD_MODE_POSITION_HELD,
            evidence=evidence,
            planning_provenance=result.planning_provenance_by_symbol.get(symbol),
        )


def _golden_07_active_map_complete_levels() -> ProfitPlanCard:
    return _card_from_native_row("SOL", current_map_status="CURRENT_ACTIVE_MAP")


# ---------------------------------------------------------------------------
# Scenario 8: completed/passed levels (MAP_COMPLETED reference state)
# ---------------------------------------------------------------------------

def _golden_08_map_completed_reference() -> ProfitPlanCard:
    return _near_like_card()


# ---------------------------------------------------------------------------
# Scenarios 9 & 10: FET-like / TAO-like Issue #550 contradiction regressions
#
# Production shape: the native SHORT snapshot contract permanently retires
# ``current_map_status`` (legacy tier metadata) to "UNAVAILABLE" even on a
# fully AVAILABLE/canonical row (Issue #496). Actionable PPP must remain
# eligible on this exact contradiction shape (native_map_status=AVAILABLE,
# selected_map_tier=DATA_UNAVAILABLE) -- see
# tests/test_manual_short_trader_profit_plan_v1.py::
# test_load_zone_contexts_retired_tier_metadata_reaches_importer_as_unavailable
# and tests/test_profit_plan_provenance_v1.py::
# test_actionable_ppp_available_when_selected_map_tier_unavailable.
# ---------------------------------------------------------------------------

def _golden_contradiction_card(symbol: str) -> ProfitPlanCard:
    return _card_from_native_row(symbol, current_map_status="UNAVAILABLE")


def _golden_09_fet_like_contradiction() -> ProfitPlanCard:
    return _golden_contradiction_card("FET")


def _golden_10_tao_like_contradiction() -> ProfitPlanCard:
    return _golden_contradiction_card("TAO")


GOLDEN_SCENARIOS: dict[str, Callable[[], ProfitPlanCard]] = {
    "01_valid_immediate_actionable": _golden_01_valid_immediate_actionable,
    "02_wait_for_entry_numeric_ppp": _golden_02_wait_for_entry_numeric_ppp,
    "03_wait_for_reclaim_no_ppp": _golden_03_wait_for_reclaim_no_ppp,
    "04_invalidated_setup": _golden_04_invalidated_setup,
    "05_stale_evidence": _golden_05_stale_evidence,
    "06_unavailable_evidence": _golden_06_unavailable_evidence,
    "07_active_map_complete_levels": _golden_07_active_map_complete_levels,
    "08_map_completed_reference": _golden_08_map_completed_reference,
    "09_fet_like_contradiction": _golden_09_fet_like_contradiction,
    "10_tao_like_contradiction": _golden_10_tao_like_contradiction,
}


# ---------------------------------------------------------------------------
# C. Golden regression assertions per scenario
# ---------------------------------------------------------------------------

def test_golden_01_valid_immediate_actionable() -> None:
    card = _golden_01_valid_immediate_actionable()
    assert card.actionability_state == pp.CARD_ACTIONABILITY_ACTIVE
    assert pp._actionable_ppp_eligible(card) is True
    assert pp._actionable_ppp(card) is not None
    assert card.action_label not in (None, "", "None")


def test_golden_02_wait_for_entry_numeric_ppp() -> None:
    card = _golden_02_wait_for_entry_numeric_ppp()
    assert card.scenario_type == "REENTRY_WAIT"
    assert card.action_label == "REBUY_ZONE_NEAR"
    assert card.actionability_state == pp.CARD_ACTIONABILITY_ACTIVE
    ppp = pp._actionable_ppp(card)
    assert ppp is not None
    assert ppp > 0


def test_golden_03_wait_for_reclaim_no_ppp() -> None:
    card = _golden_03_wait_for_reclaim_no_ppp()
    assert card.actionability_state == pp.CARD_ACTIONABILITY_ACTIVE
    assert pp._actionable_ppp(card) is None
    assert pp._entry_wait_label(card) == "Entry above current — wait for reclaim"
    assert pp._format_actionable_ppp(card) == "— · Entry above current — wait for reclaim"


def test_golden_04_invalidated_setup() -> None:
    card = _golden_04_invalidated_setup()
    assert card.actionability_state == pp.CARD_ACTIONABILITY_INVALIDATED
    assert pp._actionable_ppp(card) is None


def test_golden_05_stale_evidence() -> None:
    card = _golden_05_stale_evidence()
    assert card.actionability_state == pp.CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE
    assert card.current_price_status == "STALE_CURRENT_PRICE"
    assert len(card.reasons) > 0
    assert any("stale" in reason.lower() for reason in card.reasons)


def test_golden_06_unavailable_evidence() -> None:
    card = _golden_06_unavailable_evidence()
    assert card.actionability_state == pp.CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE
    assert card.current_price is None
    assert len(card.reasons) > 0
    assert any("missing" in reason.lower() for reason in card.reasons)


def test_golden_07_active_map_complete_levels() -> None:
    card = _golden_07_active_map_complete_levels()
    assert card.actionability_state == pp.CARD_ACTIONABILITY_ACTIVE
    assert card.invalidation_level is not None
    assert len(card.target_exit_zone) >= 1
    assert len(card.target_level_statuses) >= 2
    lifecycle_states = {level.lifecycle_state for level in card.target_level_statuses}
    assert "UPCOMING" in lifecycle_states


def test_golden_08_map_completed_reference() -> None:
    card = _golden_08_map_completed_reference()
    assert card.setup_state == "MAP_COMPLETED"
    assert card.all_sell_targets_completed is True
    assert card.action_label == "WAIT_FOR_NEW_MAP"


@pytest.mark.parametrize("symbol_key", ["09_fet_like_contradiction", "10_tao_like_contradiction"])
def test_golden_09_10_contradiction_regression(symbol_key: str) -> None:
    """Issue #550: retired ``selected_map_tier`` legacy metadata must never
    block Actionable PPP when canonical native map/lifecycle truth is
    otherwise proven -- proven per-symbol for both FET and TAO."""
    card = GOLDEN_SCENARIOS[symbol_key]()
    assert card.evidence.native_map_status == "AVAILABLE"
    assert card.evidence.selected_map_tier == "DATA_UNAVAILABLE"
    assert pp._actionable_ppp_eligible(card) is True
    assert pp._actionable_ppp(card) is not None
    assert "MAP_TIER_NOT_CONFIRMED_CURRENT" not in pp._action_gate_blocking_reason_codes(card)


def test_all_ten_golden_scenarios_registered() -> None:
    assert len(GOLDEN_SCENARIOS) == 10


_UUID4_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def test_golden_scenarios_are_deterministic() -> None:
    """Building each golden scenario twice must produce byte-identical HTML
    and semantically identical JSON (modulo per-construction UUID4 identity
    fields such as render_id / writer_instance_id / order row ids, which are
    identity, not content)."""
    for name, builder in GOLDEN_SCENARIOS.items():
        card_a = builder()
        card_b = builder()
        html_a = _UUID4_RE.sub("<uuid>", render_plan_card(card_a))
        html_b = _UUID4_RE.sub("<uuid>", render_plan_card(card_b))
        assert html_a == html_b, f"non-deterministic HTML for {name}"

        json_a = build_json_snapshot([card_a], snapshot_ts="2026-06-05T12:00:00Z")
        json_b = build_json_snapshot([card_b], snapshot_ts="2026-06-05T12:00:00Z")
        # render_id/writer_instance_id are UUID4 per call by design; strip
        # before comparing the rest of the snapshot.
        for payload in (json_a, json_b):
            payload.pop("render_id", None)
            payload.pop("writer_instance_id", None)
            for row in payload["symbols"]:
                row.pop("render_id", None)
        assert json_a == json_b, f"non-deterministic JSON for {name}"


# ---------------------------------------------------------------------------
# D. Advice-presence invariant
# ---------------------------------------------------------------------------

def test_advice_presence_invariant_no_silent_empty_advice() -> None:
    """If a card carries complete/valid canonical evidence, operator advice
    (action_label + at least one reason, or an explicit PPP-unavailable
    reason) must never be silently empty. This is the Issue #558 freeze
    invariant: advice may be a WAIT/REVIEW state, but it must never be an
    unexplained blank."""
    for name, builder in GOLDEN_SCENARIOS.items():
        card = builder()
        assert card.action_label not in (None, ""), f"{name}: action_label missing"

        html = render_plan_card(card)
        json_row = build_json_snapshot([card], snapshot_ts="2026-06-05T12:00:00Z")["symbols"][0]
        assert json_row["action_label"] == card.action_label

        if card.actionability_state == pp.CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE:
            # Context-unavailable cards must carry an explicit reason, not a
            # bare/empty advice state.
            assert len(card.reasons) > 0, f"{name}: no reason for unavailable context"
        elif pp._actionable_ppp(card) is None and card.actionability_state == pp.CARD_ACTIONABILITY_ACTIVE:
            # No numeric Actionable PPP on an otherwise-active card must
            # still carry a deterministic canonical reason via
            # _format_actionable_ppp()/_entry_wait_label(), never a bare "—".
            formatted = pp._format_actionable_ppp(card)
            assert formatted != "—", f"{name}: unexplained missing Actionable PPP"
            assert "data-actionable-ppp=" in html


# ---------------------------------------------------------------------------
# E. HTML/JSON agreement
# ---------------------------------------------------------------------------

def _json_row_for(card: ProfitPlanCard) -> dict:
    snapshot = build_json_snapshot([card], snapshot_ts="2026-06-05T12:00:00Z")
    return snapshot["symbols"][0]


def _require_attr(html: str, attr: str) -> str:
    """Extract a single-quoted HTML data-attribute value, failing loudly if
    the attribute is absent (a missing attribute is never treated as a pass)."""
    match = re.search(rf"{re.escape(attr)}='([^']*)'", html)
    assert match is not None, f"{attr} attribute not found in rendered HTML"
    return match.group(1)


@pytest.mark.parametrize("name", list(GOLDEN_SCENARIOS.keys()))
def test_html_json_agreement_core_fields(name: str) -> None:
    card = GOLDEN_SCENARIOS[name]()
    html = render_plan_card(card)
    row = _json_row_for(card)

    # --- Actionable PPP: JSON actionable_ppp_pct/actionable_ppp_available
    # must map exactly onto data-actionable-ppp/data-sort-ppp, using the same
    # canonical formatting (_pct) and unavailable sentinel ("-999999" sort /
    # "--" display) the renderer itself uses -- not a substring/presence check.
    actionable_ppp = pp._actionable_ppp(card)
    actionable_attr = _require_attr(html, "data-actionable-ppp")
    sort_attr = _require_attr(html, "data-sort-ppp")
    if actionable_ppp is not None:
        assert row["actionable_ppp_pct"] == str(actionable_ppp)
        assert row["actionable_ppp_available"] is True
        assert actionable_attr == pp._pct(actionable_ppp)
        assert sort_attr == str(actionable_ppp)
    else:
        assert row["actionable_ppp_pct"] is None
        assert row["actionable_ppp_available"] is False
        assert actionable_attr == "—"
        assert sort_attr == "-999999"

    # --- Planning PPP + provenance: JSON planning_ppp_pct/planning_provenance
    # must map exactly onto data-planning-ppp and the four
    # data-planning-*-source/hybrid attributes.
    planning_ppp = pp._planning_ppp(card)
    planning_attr = _require_attr(html, "data-planning-ppp")
    if planning_ppp is not None:
        assert row["planning_ppp_pct"] == str(planning_ppp)
        assert planning_attr == pp._pct(planning_ppp)
    else:
        assert row["planning_ppp_pct"] is None
        assert planning_attr == "—"
    provenance = row["planning_provenance"]
    assert _require_attr(html, "data-planning-reference-source") == provenance["reference_source"]
    assert _require_attr(html, "data-planning-entry-source") == provenance["entry_source"]
    assert _require_attr(html, "data-planning-target-source") == provenance["target_source"]
    assert _require_attr(html, "data-planning-hybrid-reference-only") == str(provenance["is_hybrid_reference_only"]).lower()

    # --- action/wait state: data-filter-action/data-filter-action-label are
    # rendered from the single canonical _effective_workflow_action() (see
    # its docstring); assert the HTML attributes equal that exact function's
    # output run through the same display-label/value derivation the
    # renderer uses, not merely that the attributes are present.
    assert row["action_label"] == card.action_label
    assert row["actionability_state"] == card.actionability_state
    if card.presentation_mode in pp._NO_ACCOUNT_STATE_MODES:
        expected_filter_label = ""
        expected_filter_value = ""
    else:
        expected_displayed_action = pp._effective_workflow_action(card)
        expected_filter_label = pp._filter_display_label(expected_displayed_action)
        expected_filter_value = pp._filter_value_from_label(expected_filter_label)
    assert _require_attr(html, "data-filter-action") == expected_filter_value
    assert _require_attr(html, "data-filter-action-label") == expected_filter_label

    # --- freshness/unavailable state
    assert row["current_price_status"] == card.current_price_status
    assert row["evidence"]["price_freshness_state"] == card.evidence.price_freshness_state
    assert _require_attr(html, "data-price-freshness-state") == row["evidence"]["price_freshness_state"]

    # --- lifecycle/map state: JSON evidence.{lifecycle_state,selected_map_tier,
    # native_map_status} against the corresponding data-* attributes.
    # data-native-map-status is rendered via _native_map_status() (a
    # normalizing projection, not a raw field echo), so compare against that
    # same canonical function rather than the raw evidence field.
    assert row["evidence"]["lifecycle_state"] == card.evidence.lifecycle_state
    assert row["evidence"]["selected_map_tier"] == card.evidence.selected_map_tier
    assert row["evidence"]["native_map_status"] == card.evidence.native_map_status
    assert _require_attr(html, "data-map-lifecycle-state") == row["evidence"]["lifecycle_state"]
    assert _require_attr(html, "data-selected-map-tier") == row["evidence"]["selected_map_tier"]
    assert _require_attr(html, "data-native-map-status") == pp._native_map_status(card)

    # --- re-entry/target levels: no discrete HTML data-attribute carries the
    # reload/target level list (they render as plain text in the fib
    # section), so the strongest available proof is that every JSON display
    # companion value (the same *_display string JSON exposes) appears
    # verbatim in the rendered HTML -- not an independently recomputed value.
    for level_display in row["reload_reentry_zone_display"]:
        assert level_display in html
    for level_display in row["target_exit_zone_display"]:
        assert level_display in html

    # --- no-action/reasons: JSON reasons must equal the card's reasons
    # exactly, and each reason's HTML-escaped form (the exact transform
    # render_plan_card applies via esc()) must appear verbatim in the
    # rendered <li> list.
    assert row["reasons"] == list(card.reasons)
    for reason in card.reasons:
        assert f"<li>{pp.esc(reason)}</li>" in html
