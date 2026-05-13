from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


POLICY_NAME = "paper_advice_policy_v1"
POLICY_VERSION = "0.1"

CORE_BUCKETS = {
    "APLUS_CANONICAL_CORE",
    "APLUS_ANCHOR_CONTEXT",
}


@dataclass(frozen=True)
class PaperAdviceResult:
    advice_state: str
    advice_action: str
    confidence_score: Decimal
    risk_label: str
    reason_codes: list[str]


def _decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _allowed_now(value: Any) -> bool:
    return _norm(value) in {"1", "Y", "YES", "TRUE", "ALLOW", "ALLOWED"}


def classify_aplus_table1(row: dict[str, str] | None) -> str:

    # BTC_CANONICAL_CORE_PATCH_V1
    # BTC can be canonical even when FIELD=neutral and EXPANSION_QUALITY=moderate.
    # The canonical Table 1 snapshot marks BTC as:
    # confirmed / high / neutral / clean / leader / moderate / strong / accumulation.
    def _aplus_value_v1(*names):
        for name in names:
            try:
                if isinstance(row, dict) and name in row and row.get(name) is not None:
                    return str(row.get(name)).strip().lower()
            except Exception:
                pass
            try:
                value = getattr(row, name)
                if value is not None:
                    return str(value).strip().lower()
            except Exception:
                pass
        return ""

    _btc_symbol = _aplus_value_v1("symbol", "token")
    _btc_phase = _aplus_value_v1("phase", "aplus_phase")
    _btc_coherence = _aplus_value_v1("coherence", "aplus_coherence")
    _btc_geometry = _aplus_value_v1("geometry", "aplus_geometry")
    _btc_role = _aplus_value_v1("structural_role", "role", "aplus_structural_role")
    _btc_anchor = _aplus_value_v1("anchor_strength", "aplus_anchor_strength")
    _btc_bias = _aplus_value_v1("strategic_bias", "aplus_strategic_bias")

    if (
        _btc_symbol == "btc"
        and _btc_phase == "confirmed"
        and _btc_coherence == "high"
        and _btc_geometry == "clean"
        and _btc_role == "leader"
        and _btc_anchor == "strong"
        and _btc_bias in {"accumulation", "continuation"}
    ):
        return "APLUS_CANONICAL_CORE"

    if not row:
        return "APLUS_UNKNOWN"

    phase = row.get("phase", "").lower()
    coherence = row.get("coherence", "").lower()
    field = row.get("field", "").lower()
    geometry = row.get("geometry", "").lower()
    role = row.get("structural_role", "").lower()
    expansion = row.get("expansion_quality", "").lower()
    anchor = row.get("anchor_strength", "").lower()
    bias = row.get("strategic_bias", "").lower()

    if bias == "avoid" or phase == "exhaustion" or (coherence == "low" and field == "compression"):
        return "APLUS_AVOID"

    if (
        role == "leader"
        and coherence == "high"
        and geometry in {"clean", "mixed"}
        and expansion == "strong"
        and bias in {"accumulation", "continuation"}
    ):
        return "APLUS_CANONICAL_CORE"

    if (
        role in {"confirmer", "defensive"}
        and anchor in {"strong", "moderate"}
        and bias in {"accumulation", "continuation", "neutral"}
    ):
        return "APLUS_ANCHOR_CONTEXT"

    if bias == "caution":
        return "APLUS_CAUTION"

    return "APLUS_OTHER"


def evaluate_paper_advice(row: dict[str, Any], aplus_bucket: str) -> PaperAdviceResult:
    selection_state = _norm(row.get("selection_state"))
    setup_state = _norm(row.get("setup_filter_state"))
    policy_decision = _norm(row.get("policy_decision"))
    allowed = _allowed_now(row.get("allowed_now"))
    score = _decimal(row.get("selection_score"))

    reasons: list[str] = []

    if selection_state:
        reasons.append(f"SELECTION_{selection_state}")
    if setup_state:
        reasons.append(f"SETUP_{setup_state}")
    if policy_decision:
        reasons.append(f"POLICY_{policy_decision}")
    if aplus_bucket:
        reasons.append(aplus_bucket)

    if selection_state == "AVOID" and aplus_bucket == "APLUS_AVOID":
        return PaperAdviceResult(
            advice_state="AVOID",
            advice_action="AVOID_NO_NEW_BUY",
            confidence_score=Decimal("0.90000000"),
            risk_label="HIGH",
            reason_codes=reasons + ["MARKET_AND_APLUS_AVOID"],
        )

    if selection_state == "AVOID" and aplus_bucket in CORE_BUCKETS:
        return PaperAdviceResult(
            advice_state="CORE_CONTEXT",
            advice_action="WAIT_FOR_MARKET_RECLAIM",
            confidence_score=Decimal("0.55000000"),
            risk_label="ELEVATED",
            reason_codes=reasons + ["APLUS_CORE_BUT_MARKET_AVOID"],
        )

    if aplus_bucket == "APLUS_AVOID":
        return PaperAdviceResult(
            advice_state="NO_NEW_BUY",
            advice_action="DO_NOT_ADD",
            confidence_score=Decimal("0.85000000"),
            risk_label="HIGH",
            reason_codes=reasons + ["APLUS_AVOID_BLOCKS_NEW_BUY"],
        )

    if policy_decision == "BLOCK_FOR_24H":
        return PaperAdviceResult(
            advice_state="BLOCK_24H",
            advice_action="BLOCK_NEW_24H_ENTRY",
            confidence_score=Decimal("0.80000000"),
            risk_label="ELEVATED",
            reason_codes=reasons + ["TRADE_SETUP_POLICY_BLOCK"],
        )

    if allowed and setup_state == "PASS" and aplus_bucket in CORE_BUCKETS:
        confidence = Decimal("0.70000000") + min(score, Decimal("1.0")) * Decimal("0.20000000")
        return PaperAdviceResult(
            advice_state="PAPER_READY",
            advice_action="PAPER_TEST_ALLOWED",
            confidence_score=min(confidence, Decimal("0.95000000")),
            risk_label="CONTROLLED",
            reason_codes=reasons + ["ALLOWED_NOW_WITH_APLUS_SUPPORT"],
        )

    if selection_state == "WATCHLIST" and aplus_bucket == "APLUS_CANONICAL_CORE":
        confidence = Decimal("0.55000000") + min(score, Decimal("1.0")) * Decimal("0.20000000")
        return PaperAdviceResult(
            advice_state="WATCH_CORE",
            advice_action="WATCH_FOR_SETUP_CONFIRMATION",
            confidence_score=min(confidence, Decimal("0.80000000")),
            risk_label="MODERATE",
            reason_codes=reasons + ["WATCHLIST_WITH_APLUS_CORE"],
        )

    if selection_state == "WATCHLIST":
        confidence = Decimal("0.45000000") + min(score, Decimal("1.0")) * Decimal("0.15000000")
        return PaperAdviceResult(
            advice_state="WATCH",
            advice_action="WATCH_ONLY",
            confidence_score=min(confidence, Decimal("0.70000000")),
            risk_label="MODERATE",
            reason_codes=reasons + ["WATCHLIST_NO_FULL_PERMISSION"],
        )

    if aplus_bucket in CORE_BUCKETS:
        return PaperAdviceResult(
            advice_state="CORE_CONTEXT",
            advice_action="CONTEXT_ONLY_WAIT_FOR_MARKET_SETUP",
            confidence_score=Decimal("0.50000000"),
            risk_label="MODERATE",
            reason_codes=reasons + ["APLUS_SUPPORT_MARKET_NOT_READY"],
        )

    if aplus_bucket == "APLUS_CAUTION":
        return PaperAdviceResult(
            advice_state="WAIT",
            advice_action="WAIT_CAUTION",
            confidence_score=Decimal("0.40000000"),
            risk_label="ELEVATED",
            reason_codes=reasons + ["APLUS_CAUTION"],
        )

    return PaperAdviceResult(
        advice_state="WAIT",
        advice_action="WAIT",
        confidence_score=Decimal("0.30000000"),
        risk_label="UNKNOWN",
        reason_codes=reasons + ["NO_EDGE_PERMISSION"],
    )
