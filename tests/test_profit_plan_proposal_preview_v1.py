from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from src.reporting.profit_plan_proposal_preview_v1 import (
    ALLOWED_OP_TYPES,
    OrderOperation,
    OrderProposal,
    ProposalAccessContext,
    ProposalError,
    build_proposal_from_rows,
    render_proposal_preview_html,
    validate_proposal_request,
    _hash_proposal,
)
from src.reporting.manual_short_trader_profit_plan_v1 import OrderRow

SOURCE = Path("src/reporting/profit_plan_proposal_preview_v1.py").read_text(encoding="utf-8")


def _access() -> ProposalAccessContext:
    return ProposalAccessContext(
        profile_id="alpha",
        trading_account_id="bitvavo_alpha_read",
        session_id="session-test-123",
    )


def _make_row(
    *,
    row_id: str = "row-aaa",
    render_id: str = "rnd-001",
    state: str = "MISSING",
    side: str = "sell",
    price: str = "0.454438",
    zone_role: str = "sell target 1.272",
) -> OrderRow:
    return OrderRow(
        row_id=row_id,
        render_id=render_id,
        state=state,
        reason_code="NO_SELL_ORDER_AT_ACTIVE_TARGET",
        reason_label=f"No sell order at {price}",
        side=side,
        price=Decimal(price),
        distance_pct=Decimal("3.2"),
        zone_role=zone_role,
    )


# -- Safety markers --

def test_source_has_safety_markers() -> None:
    assert "broker_writes=0" in SOURCE
    assert "order_submission=0" in SOURCE
    assert "live_orders=0" in SOURCE
    assert "executor=none" in SOURCE


def test_source_has_no_broker_imports() -> None:
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "bitvavo" not in alias.name
                assert "executor" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "executor" not in node.module
            assert "bitvavo" not in node.module


def test_allowed_op_types_are_restricted() -> None:
    assert ALLOWED_OP_TYPES == frozenset({"ADD_LIMIT_BUY", "ADD_LIMIT_SELL", "CANCEL_ORDER"})


# -- validate_proposal_request --

def test_validate_rejects_empty_render_id() -> None:
    try:
        validate_proposal_request(
            render_id="",
            row_ids=["row-aaa"],
            known_render_id="rnd-001",
            available_row_ids={"row-aaa"},
        )
        assert False, "should have raised"
    except ProposalError as e:
        assert "render_id is required" in str(e)


def test_validate_rejects_mismatched_render_id() -> None:
    try:
        validate_proposal_request(
            render_id="rnd-wrong",
            row_ids=["row-aaa"],
            known_render_id="rnd-001",
            available_row_ids={"row-aaa"},
        )
        assert False, "should have raised"
    except ProposalError as e:
        assert "render_id mismatch" in str(e)


def test_validate_rejects_unknown_row_ids() -> None:
    try:
        validate_proposal_request(
            render_id="rnd-001",
            row_ids=["row-unknown"],
            known_render_id="rnd-001",
            available_row_ids={"row-aaa"},
        )
        assert False, "should have raised"
    except ProposalError as e:
        assert "unknown row_ids" in str(e)


def test_validate_rejects_empty_row_ids() -> None:
    try:
        validate_proposal_request(
            render_id="rnd-001",
            row_ids=[],
            known_render_id="rnd-001",
            available_row_ids={"row-aaa"},
        )
        assert False, "should have raised"
    except ProposalError as e:
        assert "at least one row_id" in str(e)


def test_validate_passes_for_valid_request() -> None:
    validate_proposal_request(
        render_id="rnd-001",
        row_ids=["row-aaa"],
        known_render_id="rnd-001",
        available_row_ids={"row-aaa", "row-bbb"},
    )


# -- build_proposal_from_rows --

def test_build_proposal_assigns_proposal_id() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    assert isinstance(proposal.proposal_id, str)
    assert len(proposal.proposal_id) == 36  # UUID4


def test_build_proposal_missing_sell_row_becomes_add_limit_sell() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001", state="MISSING", side="sell")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    assert len(proposal.operations) == 1
    assert proposal.operations[0].op_type == "ADD_LIMIT_SELL"


def test_build_proposal_missing_buy_row_becomes_add_limit_buy() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001", state="MISSING", side="buy")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    assert proposal.operations[0].op_type == "ADD_LIMIT_BUY"


def test_build_proposal_stale_row_becomes_cancel_order() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001", state="STALE", side="sell")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    assert proposal.operations[0].op_type == "CANCEL_ORDER"


def test_build_proposal_carries_profile_and_account() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    assert proposal.profile_id == "alpha"
    assert proposal.trading_account_id == "bitvavo_alpha_read"


def test_build_proposal_expires_after_ttl() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    delta = (proposal.expires_ts_utc - proposal.created_ts_utc).total_seconds()
    assert delta == 300


def test_build_proposal_decision_gate_preview_blocked_by_default() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    assert proposal.decision_gate_preview == "PREVIEW_BLOCKED"


def test_build_proposal_hash_is_deterministic() -> None:
    ops = (
        OrderOperation(
            op_type="ADD_LIMIT_SELL",
            symbol="WLD",
            side="sell",
            price=Decimal("0.454438"),
            zone_role="sell target 1.272",
            reason_code="NO_SELL_ORDER_AT_ACTIVE_TARGET",
            row_id="row-aaa",
        ),
    )
    h1 = _hash_proposal("alpha", "bitvavo_alpha_read", "rnd-001", ops)
    h2 = _hash_proposal("alpha", "bitvavo_alpha_read", "rnd-001", ops)
    assert h1 == h2
    assert len(h1) == 32


def test_build_proposal_hash_differs_for_different_profile() -> None:
    ops = (
        OrderOperation(
            op_type="ADD_LIMIT_SELL",
            symbol="WLD",
            side="sell",
            price=Decimal("0.454438"),
            zone_role="sell target 1.272",
            reason_code="NO_SELL_ORDER_AT_ACTIVE_TARGET",
            row_id="row-aaa",
        ),
    )
    h1 = _hash_proposal("alpha", "bitvavo_alpha_read", "rnd-001", ops)
    h2 = _hash_proposal("beta", "bitvavo_beta_read", "rnd-001", ops)
    assert h1 != h2


# -- render_proposal_preview_html --

def test_render_proposal_preview_html_contains_op_type() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001", state="MISSING", side="sell")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    html = render_proposal_preview_html(proposal)
    assert "ADD_LIMIT_SELL" in html


def test_render_proposal_preview_html_contains_profile() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    html = render_proposal_preview_html(proposal)
    assert "alpha" in html


def test_render_proposal_preview_html_shows_safety_marker() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    html = render_proposal_preview_html(proposal)
    assert "broker_writes=0" in html
    assert "order_submission=0" in html
    assert "executor=none" in html


def test_render_proposal_preview_html_shows_gate_status() -> None:
    row = _make_row(row_id="row-aaa", render_id="rnd-001")
    proposal = build_proposal_from_rows(
        access=_access(),
        render_id="rnd-001",
        selected_row_ids=["row-aaa"],
        order_rows=(row,),
        symbol="WLD",
    )
    html = render_proposal_preview_html(proposal)
    assert "PREVIEW BLOCKED" in html or "PREVIEW_BLOCKED" in html.replace(" ", "_")
