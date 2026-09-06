"""Issue #756 Codex block BUY RESERVATIONS: bucket-scoped pending-BUY-exposure
read model over canonical open/planned executable BUY facts.

decision_gate does not own ``executor_execution_leg``/``executor_execution_handoff``
(the shared #206 executor substrate) -- this module only reads them
(read-only: no writes, no order authority, no broker calls) to compute how
much EUR notional is already committed to open, not-yet-terminal BUY legs
across *every market* sharing one ``(trading_account_id, strategy_bucket_id)``
scope. Without this, a new BUY request in a market with no open order of its
own could exceed the bucket's remaining capacity purely because the
existing open exposure sits in a *different* market of the same bucket
(e.g. an open BTC BUY reservation must still count against a new ETH BUY
request in the same sleeve).

Reserving (non-terminal) leg states: PREPARED, SUBMISSION_UNCERTAIN,
RECONCILIATION_REQUIRED, ACTIVE, PARTIALLY_FILLED -- every state in which the
leg's full planned notional remains an open commitment. FILLED legs are
excluded: their capital has already moved into
``strategy_owned_inventory_ledger_v1``'s attributed owned exposure (see
``src/executor/strategy_owned_fill_attribution_v1.py``) and must never be
counted twice. CANCELED/EXPIRED/REJECTED/FAILED legs never reserve capacity.

No second reservation subsystem is introduced: this is a read model over the
existing shared executor tables, joined by the strategy lineage now carried
on ``executor_execution_handoff`` (see the #756 migration propagating it).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

RESERVING_LEG_STATES: Final[tuple[str, ...]] = (
    "PREPARED", "SUBMISSION_UNCERTAIN", "RECONCILIATION_REQUIRED", "ACTIVE", "PARTIALLY_FILLED",
)


class StrategyBucketBuyReservationRepositoryError(RuntimeError):
    """Fail-closed reservation read-model error. ``args[0]`` is the reason code."""


def load_bucket_active_buy_reservations_eur_v1(
    conn: Any, *, trading_account_id: int, strategy_bucket_id: str,
) -> Decimal:
    """Return the sum of every non-terminal open BUY leg's planned notional
    (``price * quantity``) across every market in this exact
    ``(trading_account_id, strategy_bucket_id)`` scope.

    Read-only. Fails closed (raises
    :class:`StrategyBucketBuyReservationRepositoryError`) on an invalid
    lookup or an internally inconsistent (negative) total.
    """
    if trading_account_id <= 0 or not isinstance(strategy_bucket_id, str) or not strategy_bucket_id.strip():
        raise StrategyBucketBuyReservationRepositoryError("INVALID_BUCKET_RESERVATION_LOOKUP")
    placeholders = ", ".join(["%s"] * len(RESERVING_LEG_STATES))
    sql = f"""
    SELECT leg.price AS price, leg.quantity AS quantity
    FROM executor_execution_leg leg
    JOIN executor_execution_handoff handoff
      ON handoff.executor_execution_handoff_id = leg.executor_execution_handoff_id
    WHERE handoff.trading_account_id = %s
      AND handoff.strategy_bucket_id = %s
      AND leg.side = 'BUY'
      AND leg.state IN ({placeholders})
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, strategy_bucket_id, *RESERVING_LEG_STATES))
        rows = [dict(row) for row in cur.fetchall()]
    total = Decimal("0")
    for row in rows:
        total += Decimal(str(row["price"])) * Decimal(str(row["quantity"]))
    if total < 0:
        raise StrategyBucketBuyReservationRepositoryError("NEGATIVE_BUCKET_RESERVATION_INCONSISTENT")
    return total
