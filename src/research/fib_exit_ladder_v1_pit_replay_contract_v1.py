"""
Synth v2.6 research helper: FIB_EXIT_LADDER_V1_PIT_REPLAY_CONTRACT_V1.

Layer:
    research only. Pure functions, no DB access, no I/O.

Purpose:
    Machine-testable primitives for the frozen point-in-time (PIT) replay
    protocol in
    docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md (Issue #707
    Phase A). This module does NOT implement the PIT replay engine
    (anchor geometry detection, rung building, fill simulation, selection,
    or disposition logic) — that is explicitly out of scope for Phase A
    per the contract's § 1 (non-goals) and § 15 (required tests). It exists
    only to make the contract's § 2 (timestamp semantics), § 5 (PIT anchor
    eligibility), and § 10 (promotion-grade criteria) mechanically provable
    without running the replay or inspecting any new outcome metric.

Boundary:
    - No DB access.
    - No account access.
    - No order creation.
    - No writes to decision, execution, account, order, selection, or live
      tables.
    - No PIT outcome metric (return, alpha, fill) is computed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping, Optional

from src.research.run_fib_exit_ladder_backtest_v1 import Candle

# Frozen per docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md § 4.
# Reusing the #270 broad chronology unchanged; see that section for why.
SELECTION_WINDOW = ("2020-01-01 00:00:00", "2022-01-01 00:00:00")
OOS_WINDOW_1 = ("2022-01-01 00:00:00", "2024-01-01 00:00:00")
OOS_WINDOW_2 = ("2024-01-01 00:00:00", "2026-09-01 00:00:00")

# Frozen per § 3. HBAR/SUI remain descriptive/out of scope, exactly as in
# the #270 contract; they are deliberately absent here.
REQUIRED_ASSET_UNIVERSE = ("LINK", "XLM", "SOL", "XRP", "HOT")

# Frozen per § 6. FIB_STANDARD is deliberately excluded: it was never part
# of #270's originally-bucketed families and is not added here without
# evidence.
CANDIDATE_FAMILIES = ("PRO_3X4X", "SUPERCYCLE", "EXPLOSIVE_SUPERCYCLE")

# Frozen per § 6, reused verbatim from
# run_fib_exit_ladder_scoreboard_v1.DEFAULT_MAX_SELL_FRACTIONS.
SELL_FRACTION_GRID: tuple[Decimal, ...] = (
    Decimal("0.40"),
    Decimal("0.50"),
    Decimal("0.60"),
    Decimal("0.70"),
    Decimal("0.80"),
)

# Frozen per § 10. Exactly these nine criteria must all be True for a
# completed replay run to be promotion-grade evidence for #657.
PROMOTION_GRADE_CRITERIA = (
    "true_pit_eligibility",
    "no_look_ahead",
    "disjoint_selection_oos",
    "deterministic_replay",
    "sufficient_sample_count",
    "positive_oos_alpha",
    "stable_reproducible",
    "immutable_raw_evidence",
    "verifier_reproduces",
)


def visible_candle_indices(decision_idx: int) -> range:
    """The candle indices usable at a decision made at candles[decision_idx]'s
    own open timestamp, per contract § 2.

    A candle at index j is closed (and therefore visible) at decision_idx's
    open timestamp iff j < decision_idx: candle j's close boundary is
    candles[j + 1].open_ts_utc, and decision_idx's own open timestamp is
    >= that boundary only when j + 1 <= decision_idx. The decision candle
    itself (index == decision_idx) is never visible to its own decision —
    this is the same-candle-leakage rule.
    """
    if decision_idx < 0:
        raise ValueError(f"decision_idx must be >= 0; got {decision_idx}.")
    return range(0, decision_idx)


def find_confirmation_index(
    candles: list[Candle], wave1_high: Decimal, wave2_idx: int
) -> Optional[int]:
    """The PIT confirmation event per contract § 5.2: the first candle,
    strictly after wave2_idx, whose close_price closes back above
    wave1_high. Only candles at indices > wave2_idx are examined, and only
    in forward (ascending) order, so the result is deterministic and never
    depends on any candle beyond the one actually returned.

    Returns None if no such candle exists in the given series (the
    candidate is not yet confirmed within this data).
    """
    if wave2_idx < 0 or wave2_idx >= len(candles):
        raise ValueError(f"wave2_idx out of range: {wave2_idx} for {len(candles)} candles.")

    for idx in range(wave2_idx + 1, len(candles)):
        if candles[idx].close_price > wave1_high:
            return idx
    return None


def observable_index_for_confirmation(
    candles: list[Candle], confirmation_idx: int
) -> Optional[int]:
    """The earliest index at which the confirmation candle's close_price is
    knowable, per contract § 2/§ 5.2: candle confirmation_idx closes at
    candles[confirmation_idx + 1].open_ts_utc, so that next candle's index
    is the earliest observable/decision index. Returns None if
    confirmation_idx is the last available candle (the event is not yet
    observable within this data, per § 5.2)."""
    if confirmation_idx < 0 or confirmation_idx >= len(candles):
        raise ValueError(
            f"confirmation_idx out of range: {confirmation_idx} for {len(candles)} candles."
        )

    observable_idx = confirmation_idx + 1
    if observable_idx >= len(candles):
        return None
    return observable_idx


@dataclass(frozen=True)
class PitEntry:
    entry_idx: int
    entry_ts: datetime
    entry_price: Decimal


def entry_from_confirmation(candles: list[Candle], confirmation_idx: int) -> Optional[PitEntry]:
    """The PIT entry/decision (contract § 5.2): entry_ts/entry_price are
    taken from the candle at observable_index_for_confirmation, i.e. the
    first candle at or after which the confirmation event's close is
    actually knowable — never from the confirmation candle's own
    same-candle values. Returns None if the confirmation event is not yet
    observable within the given series."""
    observable_idx = observable_index_for_confirmation(candles, confirmation_idx)
    if observable_idx is None:
        return None

    observable_candle = candles[observable_idx]
    return PitEntry(
        entry_idx=observable_idx,
        entry_ts=observable_candle.open_ts_utc,
        entry_price=observable_candle.open_price,
    )


def evaluate_promotion_grade(criteria: Mapping[str, bool]) -> bool:
    """Whether a completed PIT replay run satisfies contract § 10.

    Fail-closed: requires every one of PROMOTION_GRADE_CRITERIA to be
    present and explicitly `True` (not merely truthy — see the #270
    disposition module's identical rationale for rejecting non-bool
    values). A missing key, a non-bool value, or any key not `True` yields
    `promotion_grade=0` for the whole run; extra/unexpected keys are
    rejected outright rather than silently ignored, since an unexpected key
    could mask a typo'd/misnamed real criterion never actually being
    checked.
    """
    provided = set(criteria)
    expected = set(PROMOTION_GRADE_CRITERIA)

    unexpected = sorted(provided - expected)
    if unexpected:
        raise ValueError(
            f"evaluate_promotion_grade received unexpected criteria keys: {unexpected}; "
            f"expected exactly {sorted(expected)}."
        )

    for name in PROMOTION_GRADE_CRITERIA:
        if name not in criteria:
            return False
        value = criteria[name]
        if not isinstance(value, bool):
            raise TypeError(
                f"promotion-grade criterion {name!r} must be True or False; "
                f"got {value!r} of type {type(value).__name__}."
            )
        if value is not True:
            return False

    return True
