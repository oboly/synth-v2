from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


UI_PREP_REASON = "UI_PREP_ONLY_NO_AUTH_LAYER"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE_CURRENCY = "EUR"


@dataclass(frozen=True)
class PreparedAction:
    action_id: str
    label: str
    enabled: bool
    reason: str
    target_market: str
    target_profile: str


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def _int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _market_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    active_priority = 0 if _bool(row.get("is_account_active")) else 1
    already_added_priority = 0 if _bool(row.get("already_added")) else 1
    return (active_priority, already_added_priority, str(row.get("market") or ""))


def build_ui_prep_actions(*, profile: str, market: str) -> list[dict[str, Any]]:
    return [
        asdict(
            PreparedAction(
                action_id=action_id,
                label=label,
                enabled=False,
                reason=UI_PREP_REASON,
                target_market=market,
                target_profile=profile,
            )
        )
        for action_id, label in [
            ("add_asset", "Add asset"),
            ("disable_candidate", "Disable selected candidates"),
            ("hide_asset", "Hide selected"),
            ("pause_candidate_24h", "Pause selected for 24h"),
            ("reenable_asset", "Re-enable selected"),
        ]
    ]


def build_manual_add_catalog(
    *,
    profile: str,
    venue_market_rows: list[dict[str, Any]],
    account_asset_rows: list[dict[str, Any]],
    open_order_count_by_market: dict[str, int] | None = None,
    show_all: bool = False,
) -> list[dict[str, Any]]:
    open_order_count_by_market = open_order_count_by_market or {}
    account_by_market = {str(row.get("market") or "").upper(): row for row in account_asset_rows}
    rows: list[dict[str, Any]] = []
    for raw in venue_market_rows:
        market = str(raw.get("market") or "").upper()
        quote_currency = str(raw.get("quote_currency") or "").upper()
        is_tradeable = True if "is_tradeable" not in raw else _bool(raw.get("is_tradeable"))
        existing = account_by_market.get(market)
        open_order_count = _int(open_order_count_by_market.get(market, 0))
        is_account_active = _bool(existing.get("has_wallet_balance")) if existing else False
        if open_order_count > 0:
            is_account_active = True

        if not show_all:
            if quote_currency and quote_currency != DEFAULT_QUOTE_CURRENCY:
                continue
            if "is_tradeable" in raw and not is_tradeable:
                continue
            if existing and not is_account_active:
                continue

        row = {
            "market": market,
            "quote_currency": quote_currency,
            "asset_symbol": str(raw.get("asset_symbol") or raw.get("symbol") or ""),
            "already_added": existing is not None,
            "is_account_active": is_account_active,
            "open_order_count": open_order_count,
            "source": None if existing is None else existing.get("source"),
            "is_visible": None if existing is None else existing.get("is_visible"),
            "is_candidate_enabled": None if existing is None else existing.get("is_candidate_enabled"),
            "is_hidden": None if existing is None else existing.get("is_hidden"),
            "is_order_proposal_enabled": None if existing is None else existing.get("is_order_proposal_enabled"),
            "actions": build_ui_prep_actions(profile=profile, market=market),
        }
        rows.append(row)
    return sorted(rows, key=_market_sort_key)


def build_relevant_view(
    *,
    profile: str,
    account_asset_rows: list[dict[str, Any]],
    open_order_count_by_market: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    open_order_count_by_market = open_order_count_by_market or {}
    rows: list[dict[str, Any]] = []
    seen_markets: set[str] = set()
    for raw in account_asset_rows:
        market = str(raw.get("market") or "").upper()
        hidden = _bool(raw.get("is_hidden"))
        open_order_count = _int(open_order_count_by_market.get(market, 0))
        has_open_order = open_order_count > 0
        if hidden:
            continue
        if not _bool(raw.get("is_visible")) and not has_open_order:
            continue
        seen_markets.add(market)
        row = dict(raw)
        row["market"] = market
        row["open_order_count"] = open_order_count
        row["has_open_order"] = has_open_order
        row["actions"] = build_ui_prep_actions(profile=profile, market=market)
        rows.append(row)
    for market, count in sorted(open_order_count_by_market.items()):
        normalized = str(market or "").upper()
        if normalized in seen_markets:
            continue
        rows.append(
            {
                "market": normalized,
                "source": "OPEN_ORDER_ONLY",
                "is_visible": False,
                "is_candidate_enabled": False,
                "is_order_proposal_enabled": False,
                "is_hidden": False,
                "open_order_count": _int(count),
                "has_open_order": _int(count) > 0,
                "actions": build_ui_prep_actions(profile=profile, market=normalized),
            }
        )
    return sorted(rows, key=lambda row: str(row.get("market") or ""))


def build_settings_view(
    *,
    profile: str,
    venue_market_rows: list[dict[str, Any]],
    account_asset_rows: list[dict[str, Any]],
    open_order_count_by_market: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    return build_manual_add_catalog(
        profile=profile,
        venue_market_rows=venue_market_rows,
        account_asset_rows=account_asset_rows,
        open_order_count_by_market=open_order_count_by_market,
        show_all=True,
    )


def build_open_orders_monitor_view(
    *,
    profile: str,
    account_asset_rows: list[dict[str, Any]],
    open_order_count_by_market: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    account_by_market = {str(row.get("market") or "").upper(): row for row in account_asset_rows}
    for market, count in sorted(open_order_count_by_market.items()):
        normalized = str(market or "").upper()
        base = dict(account_by_market.get(normalized) or {})
        base["market"] = normalized
        base["open_order_count"] = _int(count)
        base["actions"] = build_ui_prep_actions(profile=profile, market=normalized)
        rows.append(base)
    return rows


def build_account_asset_management_payload(
    *,
    profile: str,
    venue_market_rows: list[dict[str, Any]],
    account_asset_rows: list[dict[str, Any]],
    open_order_count_by_market: dict[str, int] | None = None,
) -> dict[str, Any]:
    open_order_count_by_market = open_order_count_by_market or {}
    return {
        "profile": profile,
        "manual_add_rows": build_manual_add_catalog(
            profile=profile,
            venue_market_rows=venue_market_rows,
            account_asset_rows=account_asset_rows,
            open_order_count_by_market=open_order_count_by_market,
            show_all=False,
        ),
        "relevant_rows": build_relevant_view(
            profile=profile,
            account_asset_rows=account_asset_rows,
            open_order_count_by_market=open_order_count_by_market,
        ),
        "settings_rows": build_settings_view(
            profile=profile,
            venue_market_rows=venue_market_rows,
            account_asset_rows=account_asset_rows,
            open_order_count_by_market=open_order_count_by_market,
        ),
        "open_order_rows": build_open_orders_monitor_view(
            profile=profile,
            account_asset_rows=account_asset_rows,
            open_order_count_by_market=open_order_count_by_market,
        ),
        "safety_markers": {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "executor": "none",
        },
    }
