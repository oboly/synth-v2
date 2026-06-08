from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.reporting.manual_short_trader_profit_plan_v1 import OrderRow


PREVIEW_NAME = "profit_plan_proposal_preview_v1"
PREVIEW_VERSION = "0.1"

PROPOSAL_TTL_SECONDS = 300  # proposals expire after 5 minutes

ALLOWED_OP_TYPES: frozenset[str] = frozenset({
    "ADD_LIMIT_BUY",
    "ADD_LIMIT_SELL",
    "CANCEL_ORDER",
})

# broker_writes=0 order_submission=0 live_orders=0 decision_gate=preview_only executor=none


@dataclass(frozen=True)
class ProposalAccessContext:
    """Carries session-validated identity. Built by the web handler after session+CSRF checks."""
    profile_id: str
    trading_account_id: str
    session_id: str


@dataclass(frozen=True)
class OrderOperation:
    """One atomic intended order action in a proposal."""
    op_type: str        # ADD_LIMIT_BUY | ADD_LIMIT_SELL | CANCEL_ORDER
    symbol: str
    side: str
    price: Decimal | None
    zone_role: str
    reason_code: str
    row_id: str


@dataclass(frozen=True)
class OrderProposal:
    """Read-only preview proposal — no orders placed, no broker calls."""
    proposal_id: str
    profile_id: str
    trading_account_id: str
    render_id: str
    created_ts_utc: datetime
    expires_ts_utc: datetime
    operations: tuple[OrderOperation, ...]
    proposal_hash: str      # deterministic hash of profile_id+render_id+op contents
    decision_gate_preview: str  # PREVIEW_ALLOWED | PREVIEW_BLOCKED | PREVIEW_UNAVAILABLE


class ProposalError(ValueError):
    pass


def _hash_proposal(
    profile_id: str,
    trading_account_id: str,
    render_id: str,
    operations: tuple[OrderOperation, ...],
) -> str:
    payload = json.dumps({
        "profile_id": profile_id,
        "trading_account_id": trading_account_id,
        "render_id": render_id,
        "ops": [
            {
                "op_type": op.op_type,
                "row_id": op.row_id,
                "symbol": op.symbol,
                "side": op.side,
                "price": str(op.price) if op.price is not None else None,
                "zone_role": op.zone_role,
            }
            for op in operations
        ],
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _op_type_for_row(row: OrderRow) -> str:
    if row.state == "MISSING":
        return "ADD_LIMIT_SELL" if row.side == "sell" else "ADD_LIMIT_BUY"
    if row.state == "STALE":
        return "CANCEL_ORDER"
    return "CANCEL_ORDER"  # HISTORICAL etc. → cancel


def _decision_gate_preview(operations: tuple[OrderOperation, ...]) -> str:
    """
    Conservative preview: always PREVIEW_BLOCKED in this read-only module.
    A live decision_gate integration requires account balance/position context
    that is not available here. The web handler may enrich this.
    """
    if not operations:
        return "PREVIEW_UNAVAILABLE"
    return "PREVIEW_BLOCKED"


def validate_proposal_request(
    *,
    render_id: str,
    row_ids: list[str],
    known_render_id: str,
    available_row_ids: set[str],
) -> None:
    if not render_id:
        raise ProposalError("render_id is required")
    if render_id != known_render_id:
        raise ProposalError(
            f"render_id mismatch: request={render_id!r} known={known_render_id!r}"
        )
    if not row_ids:
        raise ProposalError("at least one row_id is required")
    unknown = [rid for rid in row_ids if rid not in available_row_ids]
    if unknown:
        raise ProposalError(f"unknown row_ids: {unknown!r}")


def build_proposal_from_rows(
    *,
    access: ProposalAccessContext,
    render_id: str,
    selected_row_ids: list[str],
    order_rows: tuple[OrderRow, ...],
    symbol: str,
) -> OrderProposal:
    available_row_ids = {r.row_id for r in order_rows}
    validate_proposal_request(
        render_id=render_id,
        row_ids=selected_row_ids,
        known_render_id=render_id,  # caller is responsible for matching card render_id
        available_row_ids=available_row_ids,
    )

    selected_rows = [r for r in order_rows if r.row_id in selected_row_ids]
    now = datetime.now(UTC)

    operations = tuple(
        OrderOperation(
            op_type=_op_type_for_row(row),
            symbol=symbol,
            side=row.side,
            price=row.price,
            zone_role=row.zone_role,
            reason_code=row.reason_code,
            row_id=row.row_id,
        )
        for row in selected_rows
    )

    proposal_hash = _hash_proposal(
        access.profile_id,
        access.trading_account_id,
        render_id,
        operations,
    )

    return OrderProposal(
        proposal_id=str(uuid.uuid4()),
        profile_id=access.profile_id,
        trading_account_id=access.trading_account_id,
        render_id=render_id,
        created_ts_utc=now,
        expires_ts_utc=now + timedelta(seconds=PROPOSAL_TTL_SECONDS),
        operations=operations,
        proposal_hash=proposal_hash,
        decision_gate_preview=_decision_gate_preview(operations),
    )


def render_proposal_preview_html(proposal: OrderProposal) -> str:
    import html as _html

    def esc(v: Any) -> str:
        return _html.escape(str(v), quote=True)

    ops_html = ""
    for op in proposal.operations:
        price_str = str(op.price) if op.price is not None else "—"
        ops_html += (
            f"<tr>"
            f"<td class='mono'>{esc(op.op_type)}</td>"
            f"<td class='mono'>{esc(op.symbol)}</td>"
            f"<td>{esc(op.side.upper())}</td>"
            f"<td>LIMIT</td>"
            f"<td class='mono'>{esc(price_str)}</td>"
            f"<td class='muted small'>{esc(op.zone_role)}</td>"
            f"</tr>"
        )

    gate_css = "blocked" if proposal.decision_gate_preview == "PREVIEW_BLOCKED" else "ok"
    gate_label = proposal.decision_gate_preview.replace("_", " ")

    return (
        "<div class='proposal-preview'>"
        f"<div class='proposal-header'>"
        f"<span class='proposal-id muted small'>Proposal {esc(proposal.proposal_id[:8])}…</span>"
        f"<span class='gate-badge {gate_css}'>{esc(gate_label)}</span>"
        f"</div>"
        f"<div class='muted small'>Profile: {esc(proposal.profile_id)} · "
        f"Account: {esc(proposal.trading_account_id)} · "
        f"Expires: {esc(proposal.expires_ts_utc.strftime('%H:%M:%S UTC'))}</div>"
        f"<table class='proposal-ops'>"
        f"<thead><tr><th>Op</th><th>Symbol</th><th>Side</th><th>Type</th><th>Price</th><th>Zone</th></tr></thead>"
        f"<tbody>{ops_html}</tbody>"
        f"</table>"
        "<div class='proposal-footer muted small'>"
        "Read-only preview — broker_writes=0 order_submission=0 executor=none"
        "</div>"
        "</div>"
    )
