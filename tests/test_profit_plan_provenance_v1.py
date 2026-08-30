"""Regression tests for Profit Plan Planning PPP provenance (Issue #457).

Covers:
- Planning PPP source attribution (NATIVE_SHORT_CANONICAL / CANONICAL_4H_NAVIGATION /
  HYBRID_REFERENCE_ONLY / DATA_UNAVAILABLE) via load_zone_contexts() and the
  PlanningProvenance contract itself.
- Actionable PPP fail-closed hardening: canonical native map truth,
  selected_map_tier == CURRENT_ACTIVE_MAP, and available (non-blocking)
  lifecycle authority are all now explicit, required conditions.
- Planning PPP never affects ranking; HTML and JSON expose identical
  provenance semantics.

Read-only reporting semantics only: no broker, decision_gate, execution_planner
or executor is touched.
"""
from __future__ import annotations

import re
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.market_data.native_short_fib_context_v1 import NativeShortContextRow, write_context_rows
import src.reporting.manual_short_trader_profit_plan_v1 as pp
import src.reporting.run_manual_short_trader_profit_plan_v1 as profit_plan_runner
from src.reporting.manual_short_trader_profit_plan_v1 import (
    CARD_MODE_POSITION_HELD,
    CardEvidence,
    FibExtContext,
    ReentryContext,
    build_json_snapshot,
    build_profit_plan_card,
    make_planning_provenance,
    render_plan_card,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _native_short_row(
    *,
    symbol: str = "WLD",
    status: str = "NATIVE_SHORT_CONTEXT_AVAILABLE",
) -> NativeShortContextRow:
    return NativeShortContextRow(
        symbol=symbol,
        venue="bitvavo",
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        context_status=status,
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
        current_map_status="CURRENT_ACTIVE_MAP",
        previous_map_cycle_id="",
        previous_map_lifecycle_state="",
        rollover_state="SINGLE_MAP",
        selection_reason="Single active map selected",
    )


def _canonical_fib_row(
    *,
    symbol: str = "ONDO",
    current_leg: str = "UP",
    map_status: str = "FRESH",
    asof_ts_utc: datetime | None = None,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "venue": "bitvavo",
        "quote_currency": "EUR",
        "interval_code": "4h",
        "asof_ts_utc": asof_ts_utc or datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
        "map_status": map_status,
        "current_leg": current_leg,
        "reference_price": Decimal("1.00"),
        "anchor_low_price": Decimal("0.80"),
        "anchor_high_price": Decimal("1.20"),
        "entry_zone_low": Decimal("1.00"),
        "entry_zone_high": Decimal("1.10"),
        "entry_zone_mid": Decimal("1.05"),
        "support_reaction_zone_low": Decimal("0.90"),
        "support_reaction_zone_high": Decimal("1.00"),
        "target_t1": Decimal("1.30"),
        "target_t2": Decimal("1.40"),
        "target_extension": Decimal("1.60"),
    }


def _empty_fib_map_rows(tmpdir: str) -> Path:
    fib_rows = Path(tmpdir) / "fibo_target_map_rows_v1.csv"
    fib_rows.write_text(
        "symbol,current_price,swing_low_price,swing_high_price,local_reaction_price,next_fibo_support_price\n",
        encoding="utf-8",
    )
    return fib_rows


def _active_map_evidence(**overrides: str) -> CardEvidence:
    base = dict(
        map_cycle_id="WLD|SHORT|4h|demo",
        native_map_id="WLD-map-01",
        native_map_status="AVAILABLE",
        selected_map_reason="Single active map selected",
        selected_map_tier="CURRENT_ACTIVE_MAP",
        lifecycle_state="TARGET_ACTIVE",
        rollover_state="SINGLE_MAP",
        account_order_snapshot_status="FRESH",
        price_freshness_state="FRESH",
        anchor_start_ts_utc="2026-06-01T00:00:00Z",
        order_snapshot_ts_utc="2026-06-05T12:00:00Z",
        generation_ts_utc="2026-06-05T12:00:00Z",
    )
    base.update(overrides)
    return CardEvidence(**base)


def _activated_fib_ext() -> FibExtContext:
    """BELOW_BREAKOUT_GATE band -- produces both a re-entry (buy) zone and a
    target (sell) zone, so Planning PPP has coherent entry+target inputs.
    First target (1.272 ext) is reached via history_high_since_activation,
    proving entry activation without requiring native lifecycle authority."""
    return FibExtContext(
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


def _activated_reentry() -> ReentryContext:
    return ReentryContext(
        r382_price=Decimal("0.2100"),
        r500_price=Decimal("0.2000"),
        r618_price=Decimal("0.1800"),
        r786_price=Decimal("0.1400"),
        deepest_touched_label=None,
        missed_main_rebuy_by_pct=None,
    )


def _activated_card(*, evidence: CardEvidence, reentry: ReentryContext | None = None) -> pp.ProfitPlanCard:
    """A card with a genuinely activated setup (first target passed via
    history) and current-map/current-cycle evidence -- otherwise eligible for
    Actionable PPP so tests isolate exactly the evidence field under test.

    Planning PPP provenance must be explicit (Issue #457 -- build_profit_plan_
    card() no longer infers it from fib_ext+reentry presence), so this fixture
    supplies a coherent single native source itself, mirroring how a real
    caller (load_zone_contexts()) would attribute it for this fixture data."""
    return build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.1600"),
        fib_ext=_activated_fib_ext(),
        reentry=reentry if reentry is not None else _activated_reentry(),
        history_high_since_activation=Decimal("0.4600"),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=evidence,
        planning_provenance=make_planning_provenance(
            entry_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
            target_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Canonical native-only coherent Planning PPP
# ---------------------------------------------------------------------------

def test_native_only_coherent_planning_ppp() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = _empty_fib_map_rows(tmpdir)
        native_dir = Path(tmpdir) / "native"
        native_paths = write_context_rows(rows=[_native_short_row(symbol="WLD")], output_dir=native_dir)
        result = profit_plan_runner.load_zone_contexts(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("0.40")},
            swing_anchors={},
            recent_lows={},
            native_short_rows_path=native_paths["rows_csv"],
            fib_map_rows_path=fib_rows,
            native_short_snapshot_status="loaded",
            native_short_snapshot_id="nsctx-v1-test-snapshot",
        )
        provenance = result.planning_provenance_by_symbol["WLD"]
        assert provenance.reference_source == pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL
        assert provenance.entry_source == pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL
        assert provenance.target_source == pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL
        assert provenance.is_coherent is True
        assert provenance.is_hybrid_reference_only is False
        assert provenance.source_map_cycle_id == "WLD|SHORT|4h|demo"


# ---------------------------------------------------------------------------
# 2. Canonical 4h-only coherent Planning PPP
# ---------------------------------------------------------------------------

def test_canonical_4h_only_coherent_planning_ppp() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = _empty_fib_map_rows(tmpdir)
        native_dir = Path(tmpdir) / "native"
        # Native scope covers a different symbol; ONDO has no native row.
        native_paths = write_context_rows(rows=[_native_short_row(symbol="BTC")], output_dir=native_dir)
        result = profit_plan_runner.load_zone_contexts(
            markets=["ONDO-EUR"],
            prices={"ONDO-EUR": Decimal("1.02")},
            swing_anchors={},
            recent_lows={},
            native_short_rows_path=native_paths["rows_csv"],
            fib_map_rows_path=fib_rows,
            canonical_fib_rows_by_symbol={"ONDO": _canonical_fib_row()},
            now_utc=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
        )
        provenance = result.planning_provenance_by_symbol["ONDO"]
        assert provenance.reference_source == pp.PLANNING_SOURCE_CANONICAL_4H_NAVIGATION
        assert provenance.is_coherent is True
        assert provenance.is_hybrid_reference_only is False
        # Canonical rows carry no native map/cycle identity -- never fabricated.
        assert provenance.source_map_id == "DATA_UNAVAILABLE"
        assert provenance.source_map_cycle_id == "DATA_UNAVAILABLE"

        card = build_profit_plan_card(
            symbol="ONDO",
            market="ONDO-EUR",
            current_price=Decimal("1.02"),
            short_context_input_status=result.input_status_by_symbol["ONDO"],
            short_context_coverage_status=result.coverage_status_by_symbol["ONDO"],
            short_context_display_state=result.display_state_by_symbol["ONDO"],
            fib_ext=result.fib_ext_by_symbol["ONDO"],
            reentry=result.reentry_by_symbol["ONDO"],
            evidence=result.evidence_by_symbol.get("ONDO", CardEvidence()),
            planning_provenance=provenance,
        )
        assert pp._planning_ppp(card) is not None


# ---------------------------------------------------------------------------
# 3. Mixed native entry + canonical target (direct provenance-contract unit
#    test -- the current loader only reaches the reverse pairing, but the
#    coherence gate itself must be direction-symmetric).
# ---------------------------------------------------------------------------

def test_mixed_native_entry_canonical_target_is_hybrid_and_blocks_planning_ppp() -> None:
    provenance = make_planning_provenance(
        entry_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
        target_source=pp.PLANNING_SOURCE_CANONICAL_4H_NAVIGATION,
    )
    assert provenance.is_hybrid_reference_only is True
    assert provenance.is_coherent is False
    assert provenance.reference_source == pp.PLANNING_SOURCE_HYBRID_REFERENCE_ONLY
    # A hybrid pairing must never invent a shared map identity.
    assert provenance.source_map_id == "DATA_UNAVAILABLE"
    assert provenance.source_map_cycle_id == "DATA_UNAVAILABLE"

    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.3600"),
        fib_ext=_activated_fib_ext(),
        reentry=_activated_reentry(),
        evidence=_active_map_evidence(),
        planning_provenance=provenance,
    )
    assert pp._planning_ppp(card) is None
    reason = pp._planning_ppp_unavailable_reason(card)
    assert reason is not None and "different sources" in reason


# ---------------------------------------------------------------------------
# 4. Mixed canonical entry + native target -- Issue #238 partial-native +
#    canonical-4h fallback composition, reproduced through load_zone_contexts().
# ---------------------------------------------------------------------------

def test_partial_native_target_plus_canonical_fallback_entry_is_hybrid() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = _empty_fib_map_rows(tmpdir)
        native_dir = Path(tmpdir) / "native"
        # Partial native row: full ext_* fields present (target-shaped) but
        # context_status is not AVAILABLE, so it is never proven canonical
        # and reentry is never populated from this row.
        native_paths = write_context_rows(
            rows=[_native_short_row(symbol="WLD", status="INSUFFICIENT_1H_HISTORY")],
            output_dir=native_dir,
        )
        result = profit_plan_runner.load_zone_contexts(
            markets=["WLD-EUR"],
            prices={"WLD-EUR": Decimal("0.40")},
            swing_anchors={},
            recent_lows={},
            native_short_rows_path=native_paths["rows_csv"],
            fib_map_rows_path=fib_rows,
            canonical_fib_rows_by_symbol={"WLD": _canonical_fib_row(symbol="WLD")},
            now_utc=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
        )
        # Target came from the native partial row; entry was backfilled from
        # the canonical 4h fallback -- two different authorities.
        provenance = result.planning_provenance_by_symbol["WLD"]
        assert provenance.target_source == pp.PLANNING_SOURCE_NATIVE_SHORT_TRANSIENT_REFERENCE
        assert provenance.entry_source == pp.PLANNING_SOURCE_CANONICAL_4H_NAVIGATION
        assert provenance.is_hybrid_reference_only is True
        assert provenance.reference_source == pp.PLANNING_SOURCE_HYBRID_REFERENCE_ONLY

        card = build_profit_plan_card(
            symbol="WLD",
            market="WLD-EUR",
            current_price=Decimal("0.40"),
            fib_ext=result.fib_ext_by_symbol["WLD"],
            reentry=result.reentry_by_symbol["WLD"],
            evidence=result.evidence_by_symbol.get("WLD", CardEvidence()),
            planning_provenance=provenance,
        )
        # Mixed native/canonical inputs must never silently render an
        # ordinary numeric Planning PPP (Issue #457 invariant D).
        assert pp._planning_ppp(card) is None


# ---------------------------------------------------------------------------
# 5. Missing provenance
# ---------------------------------------------------------------------------

def test_missing_zone_context_has_data_unavailable_provenance() -> None:
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.40"),
        fib_ext=None,
        reentry=None,
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
    )
    assert card.planning_provenance.reference_source == "DATA_UNAVAILABLE"
    assert card.planning_provenance.is_coherent is False
    assert pp._planning_ppp(card) is None
    assert pp._planning_ppp_unavailable_reason(card) is not None


def test_populated_zones_without_explicit_provenance_fail_closed() -> None:
    """Issue #457 review fix: build_profit_plan_card() must never infer a
    coherent provenance class from the mere presence of fib_ext + reentry.
    A direct caller that supplies populated entry/target levels but omits
    planning_provenance must get DATA_UNAVAILABLE and an unavailable Planning
    PPP -- only load_zone_contexts() (or another caller that actually knows
    the per-authority composition) may assert coherence."""
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.1600"),
        fib_ext=_activated_fib_ext(),
        reentry=_activated_reentry(),
        short_context_display_state="HAS_NATIVE_SHORT_FIB_CONTEXT",
        short_context_coverage_status="NATIVE_SHORT_CONTEXT_AVAILABLE",
        presentation_mode=CARD_MODE_POSITION_HELD,
        evidence=_active_map_evidence(),
        # planning_provenance intentionally omitted.
    )
    assert card.buy_zone or card.reload_reentry_zone
    assert card.target_exit_zone
    assert card.planning_provenance.reference_source == "DATA_UNAVAILABLE"
    assert card.planning_provenance.is_coherent is False
    assert pp._planning_ppp(card) is None
    assert pp._planning_ppp_unavailable_reason(card) is not None


# ---------------------------------------------------------------------------
# 6-9, 13. Actionable PPP fail-closed hardening
# ---------------------------------------------------------------------------

def test_actionable_ppp_available_with_valid_current_map_and_lifecycle() -> None:
    """Baseline: a genuinely activated setup with proven current-map/current-
    cycle evidence must still permit Actionable PPP (Issue #457 must not
    remove legitimate actionable cases)."""
    card = _activated_card(evidence=_active_map_evidence())
    assert pp._entry_activation_proof(card) is True
    assert pp._actionable_ppp_eligible(card) is True
    assert pp._actionable_ppp(card) is not None


def test_actionable_ppp_available_when_selected_map_tier_unavailable() -> None:
    """Issue #550 regression: the native SHORT snapshot contract permanently
    retires ``selected_map_tier`` (native_row.current_map_status) to
    DATA_UNAVAILABLE even on a fully AVAILABLE/canonical row (Issue #496), so
    every real production card carries this exact value. Actionable PPP must
    not fail closed on retired, non-canonical bridge metadata when genuine
    canonical map/lifecycle authority (native_map_status, map_cycle_id,
    lifecycle, entry activation) is otherwise proven."""
    card = _activated_card(evidence=_active_map_evidence(selected_map_tier="DATA_UNAVAILABLE"))
    assert pp._actionable_ppp_eligible(card) is True
    assert pp._actionable_ppp(card) is not None


def test_actionable_ppp_available_when_selected_map_tier_not_current() -> None:
    """Same Issue #550 contract: an arbitrary non-canonical reported tier
    value must not gate Actionable PPP either -- selected_map_tier carries no
    authority at all post-#496."""
    card = _activated_card(evidence=_active_map_evidence(selected_map_tier="PRIOR_MAP_REFERENCE"))
    assert pp._actionable_ppp_eligible(card) is True
    assert pp._actionable_ppp(card) is not None


def test_actionable_ppp_unavailable_when_lifecycle_state_data_unavailable() -> None:
    card = _activated_card(evidence=_active_map_evidence(lifecycle_state="DATA_UNAVAILABLE"))
    assert card.all_sell_targets_completed is False
    assert pp._map_lifecycle_blocks_action(card) is True
    assert pp._actionable_ppp_eligible(card) is False
    assert pp._actionable_ppp(card) is None


def test_actionable_ppp_unavailable_when_lifecycle_explicitly_blocking() -> None:
    card = _activated_card(evidence=_active_map_evidence(lifecycle_state="MAP_COMPLETED"))
    assert card.all_sell_targets_completed is False
    assert pp._map_lifecycle_blocks_action(card) is True
    assert pp._actionable_ppp_eligible(card) is False
    assert pp._actionable_ppp(card) is None


def test_former_production_shape_mog_actionable_ppp_unavailable() -> None:
    """Exact production regression shape (Issue #457 comment, 2026-08-23):
    native_map_status AVAILABLE, native_map_id + map_cycle_id present,
    selected_map_tier unavailable, lifecycle_state DATA_UNAVAILABLE, entry
    activation proof present, otherwise eligible. Actionable PPP MUST be
    unavailable; Planning PPP (native-source, coherent) may remain numeric."""
    evidence = _active_map_evidence(
        selected_map_tier="DATA_UNAVAILABLE",
        lifecycle_state="DATA_UNAVAILABLE",
    )
    assert evidence.native_map_status == "AVAILABLE"
    assert evidence.native_map_id != "DATA_UNAVAILABLE"
    assert evidence.map_cycle_id != "DATA_UNAVAILABLE"

    card = _activated_card(evidence=evidence, reentry=_activated_reentry())
    assert pp._entry_activation_proof(card) is True
    assert pp._actionable_ppp_eligible(card) is False
    assert pp._actionable_ppp(card) is None

    # Coherent single native source -- Planning PPP stays numeric (reporting-
    # only reference), distinct from Actionable PPP's fail-closed authority.
    assert card.planning_provenance.is_coherent is True
    assert pp._planning_ppp(card) is not None


# ---------------------------------------------------------------------------
# 11. Planning PPP never affects ranking
# ---------------------------------------------------------------------------

def test_planning_ppp_never_drives_sort_value() -> None:
    """A card with a large numeric Planning PPP but no Actionable PPP (blocked
    by unavailable lifecycle authority) must sort as if PPP were entirely
    absent -- Actionable PPP is the only ranking input."""
    planning_only_card = _activated_card(
        evidence=_active_map_evidence(lifecycle_state="DATA_UNAVAILABLE"),
    )
    assert pp._planning_ppp(planning_only_card) is not None
    assert pp._actionable_ppp(planning_only_card) is None

    html = render_plan_card(planning_only_card)
    match = re.search(r"data-sort-ppp='([^']*)'", html)
    assert match is not None
    assert match.group(1) == "-999999"


# ---------------------------------------------------------------------------
# 12. HTML and JSON expose identical provenance semantics
# ---------------------------------------------------------------------------

def test_html_and_json_expose_identical_provenance_semantics() -> None:
    hybrid_provenance = make_planning_provenance(
        entry_source=pp.PLANNING_SOURCE_CANONICAL_4H_NAVIGATION,
        target_source=pp.PLANNING_SOURCE_NATIVE_SHORT_CANONICAL,
    )
    card = build_profit_plan_card(
        symbol="WLD",
        market="WLD-EUR",
        current_price=Decimal("0.4600"),
        fib_ext=_activated_fib_ext(),
        reentry=_activated_reentry(),
        evidence=_active_map_evidence(),
        planning_provenance=hybrid_provenance,
    )
    html = render_plan_card(card)
    ref_match = re.search(r"data-planning-reference-source='([^']*)'", html)
    hybrid_match = re.search(r"data-planning-hybrid-reference-only='([^']*)'", html)
    assert ref_match is not None and hybrid_match is not None
    assert ref_match.group(1) == pp.PLANNING_SOURCE_HYBRID_REFERENCE_ONLY
    assert hybrid_match.group(1) == "true"

    snapshot = build_json_snapshot([card], broker_mode="db_snapshot")
    json_provenance = snapshot["symbols"][0]["planning_provenance"]
    assert json_provenance["reference_source"] == ref_match.group(1)
    assert json_provenance["is_hybrid_reference_only"] is True
