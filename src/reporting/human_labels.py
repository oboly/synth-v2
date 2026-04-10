from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from src.reporting.run_live_advice_report_extended import AssetReport


def derive_human_bucket(report: "AssetReport") -> str:
    if report.action == "BUY" and report.bucket == "TOP":
        return "BUY NOW"

    if report.action == "BUY" and report.bucket == "WATCH":
        return "WATCH BUY"

    if report.action == "SELL":
        return "REDUCE / SELL"

    return "NO TRADE"


def derive_human_action(report: "AssetReport") -> str:
    human_bucket = derive_human_bucket(report)

    if human_bucket == "BUY NOW":
        if report.tactical_state == "PULLBACK":
            return "Enter on pullback"
        if report.tactical_state == "REJECTION":
            return "Enter on rejection"
        if report.tactical_state == "BREAKOUT_ATTEMPT":
            return "Use aggressive limit"
        return "Accumulate carefully"

    if human_bucket == "WATCH BUY":
        if report.tactical_state == "PULLBACK":
            return "Wait for better pullback"
        if report.tactical_state == "BREAKOUT_ATTEMPT":
            return "Wait for reclaim"
        if report.tactical_state == "RANGE":
            return "Watch range low"
        return "Wait for confirmation"

    if human_bucket == "REDUCE / SELL":
        return "Sell into strength"

    return "Do nothing"


def derive_human_execution_label(report: "AssetReport") -> str:
    mapping = {
        "PASSIVE": "Passive bids",
        "PASSIVE_REPRICE": "Passive + reprice",
        "AGGRESSIVE_LIMIT": "Aggressive limit",
        "WAIT": "Wait",
    }
    return mapping.get(report.execution_mode, report.execution_mode.title().replace("_", " "))


def derive_ui_tone(report: "AssetReport") -> str:
    human_bucket = derive_human_bucket(report)

    if human_bucket == "BUY NOW":
        return "bullish"
    if human_bucket == "WATCH BUY":
        return "cautious"
    if human_bucket == "REDUCE / SELL":
        return "bearish"
    return "neutral"


def derive_ui_priority(report: "AssetReport") -> int:
    human_bucket = derive_human_bucket(report)

    if human_bucket == "BUY NOW":
        return 3
    if human_bucket == "WATCH BUY":
        return 2
    if human_bucket == "REDUCE / SELL":
        return 1
    return 0


def derive_one_liner(report: "AssetReport") -> str:
    human_bucket = derive_human_bucket(report)

    if human_bucket == "BUY NOW":
        return (
            f"{report.structure_state} setup with {report.tactical_state.lower()} timing; "
            f"best fit is {derive_human_execution_label(report).lower()}."
        )

    if human_bucket == "WATCH BUY":
        return (
            f"{report.structure_state} is improving, but entry quality is {report.entry_quality.lower()}; "
            f"wait for cleaner timing."
        )

    if human_bucket == "REDUCE / SELL":
        return "Structure remains weak; reduce into strength instead of adding fresh longs."

    return "Clarity or reward/risk is insufficient; keep capital free."


def derive_human_labels(report: "AssetReport") -> dict[str, str | int]:
    return {
        "human_bucket": derive_human_bucket(report),
        "human_action": derive_human_action(report),
        "human_execution_label": derive_human_execution_label(report),
        "ui_tone": derive_ui_tone(report),
        "ui_priority": derive_ui_priority(report),
        "one_liner": derive_one_liner(report),
    }


def should_show_buy_fields(report: "AssetReport") -> bool:
    return derive_human_bucket(report) in {"BUY NOW", "WATCH BUY"}


def should_show_sell_fields(report: "AssetReport") -> bool:
    return derive_human_bucket(report) == "REDUCE / SELL"


def should_show_no_trade_fields(report: "AssetReport") -> bool:
    return derive_human_bucket(report) == "NO TRADE"


def safe_decimal_str(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return str(value)
