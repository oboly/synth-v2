from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from src.market_data.native_short_fib_context_v1 import (
    PRIMARY_LIFECYCLE_COMPLETED,
    PRIMARY_LIFECYCLE_INVALIDATED,
    SwingCandidateContext,
    _candidate_rank,
)
from src.reporting.manual_short_trader_profit_plan_v1 import (
    CARD_ACTIONABILITY_ACTIVE,
    CARD_MODE_POSITION_HELD,
    FibExtContext,
    ReentryContext,
    TargetHistoryCandle,
    _effective_workflow_action,
    _filter_display_label,
    _filter_value_from_label,
    _order_ladder_display_status,
    build_json_snapshot,
    build_order_rows,
    build_profit_plan_card,
    render_plan_card,
)


RUNNER_NAME = "profit_plan_card_forensic_replay_v1"
DEFAULT_FIXTURES_PATH = Path(
    "tests/fixtures/profit_plan_card_forensic_replay_v1/profit_plan_card_forensic_fixtures_v1.json"
)
DEFAULT_OUTPUT_ROOT = Path("data/research/profit_plan_card_forensic_replay_v1")
NATIVE_CONTEXT_AVAILABLE = "NATIVE_SHORT_CONTEXT_AVAILABLE"

ACTIVE_OR_DEVELOPING_STATES = frozenset(
    {
        "BREAKOUT_CONFIRMED",
        "TARGET_ACTIVE",
        "TARGET_REACHED_OR_PASSED",
        "POST_BREAKOUT_PULLBACK",
        "BELOW_BREAKOUT_GATE",
    }
)
ACTION_LIKE_LABELS = frozenset(
    {
        "BUY_DIP",
        "REBUY_ZONE_NEAR",
        "TAKE_PROFIT_NEAR",
        "BREAKOUT_WATCH",
        "PLACE_LADDER",
        "REPAIR_LADDER",
        "FAR_MOONBAG_ONLY",
    }
)
ACTIVE_LADDER_STATES = frozenset({"LADDER_MISSING", "LADDER_INCOMPLETE", "LADDER_ARMED"})
ORDER_MATCH_TOLERANCE_PCT = Decimal("3")

INVARIANT_FIELDS = [
    "fixture_id",
    "symbol",
    "selected_map_cycle_id",
    "selected_native_map_id",
    "invariant_id",
    "severity",
    "expected_semantics",
    "actual_semantics",
    "relevant_card_fields",
]


@dataclass(frozen=True)
class ForensicOrder:
    side: str
    limit_price: Decimal
    map_cycle_id: str
    created_at_ms: int | None = None
    order_status: str = "OPEN"


@dataclass(frozen=True)
class SelectedMap:
    raw: dict[str, Any]
    candidate: SwingCandidateContext
    rank: tuple[int, datetime]


@dataclass(frozen=True)
class Violation:
    fixture_id: str
    symbol: str
    selected_map_cycle_id: str | None
    selected_native_map_id: str | None
    invariant_id: str
    severity: str
    expected_semantics: str
    actual_semantics: str
    relevant_card_fields: dict[str, Any]

    def to_csv_row(self) -> dict[str, str]:
        return {
            "fixture_id": self.fixture_id,
            "symbol": self.symbol,
            "selected_map_cycle_id": self.selected_map_cycle_id or "",
            "selected_native_map_id": self.selected_native_map_id or "",
            "invariant_id": self.invariant_id,
            "severity": self.severity,
            "expected_semantics": self.expected_semantics,
            "actual_semantics": self.actual_semantics,
            "relevant_card_fields": json.dumps(
                self.relevant_card_fields,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "symbol": self.symbol,
            "selected_map_cycle_id": self.selected_map_cycle_id,
            "selected_native_map_id": self.selected_native_map_id,
            "invariant_id": self.invariant_id,
            "severity": self.severity,
            "expected_semantics": self.expected_semantics,
            "actual_semantics": self.actual_semantics,
            "relevant_card_fields": self.relevant_card_fields,
        }


class _PlanCardSectionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.plan_card_attrs: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.plan_card_attrs is not None:
            return
        if tag != "section":
            return
        attr_map = {key: value or "" for key, value in attrs}
        classes = set((attr_map.get("class") or "").split())
        if "plan-card" in classes:
            self.plan_card_attrs = attr_map


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Decimal(text)


def _required_dec(row: dict[str, Any], key: str) -> Decimal:
    value = _dec(row.get(key))
    if value is None:
        raise ValueError(f"missing decimal field {key}")
    return value


def _dt(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("missing datetime")
    if text.endswith("Z"):
        text = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _load_fixture_payload(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != RUNNER_NAME:
        raise ValueError(f"unexpected fixture schema_version={payload.get('schema_version')!r}")
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("fixture payload must contain a fixtures list")
    return payload


def _levels(row: dict[str, Any], key: str) -> tuple[Decimal, ...]:
    return tuple(_required_list_dec(row.get(key)))


def _required_list_dec(value: Any) -> list[Decimal]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected list of decimal strings")
    out: list[Decimal] = []
    for item in value:
        parsed = _dec(item)
        if parsed is not None:
            out.append(parsed)
    return out


def _candidate_from_map(row: dict[str, Any]) -> SwingCandidateContext:
    latest_price = _dec(row.get("latest_primary_close_price")) or _required_dec(row, "max_high_since_anchor")
    return SwingCandidateContext(
        anchor_start_ts_utc=_dt(row["anchor_start_ts_utc"]),
        anchor_end_ts_utc=_dt(row["anchor_end_ts_utc"]),
        anchor_low_price=_required_dec(row, "anchor_low"),
        anchor_high_price=_required_dec(row, "anchor_high"),
        breakout_gate_price=_required_dec(row, "breakout_gate"),
        latest_primary_close_ts_utc=_dt(row.get("latest_primary_close_ts_utc") or row["anchor_end_ts_utc"]),
        latest_primary_close_price=latest_price,
        ext_1_272_price=_required_dec(row, "ext_1_272"),
        ext_1_618_price=_required_dec(row, "ext_1_618"),
        ext_2_000_price=_required_dec(row, "ext_2_000"),
        active_target_levels=_levels(row, "active_target_levels"),
        previous_target_levels=_levels(row, "previous_target_levels"),
        reload_r382_price=_required_dec(row, "reload_r382"),
        reload_r500_price=_required_dec(row, "reload_r500"),
        reload_r618_price=_required_dec(row, "reload_r618"),
        reload_r786_price=_required_dec(row, "reload_r786"),
        invalidation_price=_required_dec(row, "invalidation"),
        primary_4h_lifecycle_state=str(row["lifecycle_state"]),
        max_primary_high_since_anchor=_required_dec(row, "max_high_since_anchor"),
        min_primary_low_since_anchor=_required_dec(row, "min_low_since_anchor"),
    )


def _select_fixture_map(fixture: dict[str, Any]) -> tuple[SelectedMap | None, list[dict[str, Any]]]:
    ranked: list[SelectedMap] = []
    for raw_map in fixture.get("maps") or []:
        candidate = _candidate_from_map(raw_map)
        ranked.append(SelectedMap(raw=raw_map, candidate=candidate, rank=_candidate_rank(candidate)))
    ranked.sort(key=lambda item: item.rank, reverse=True)
    rank_rows = [
        {
            "native_map_id": item.raw.get("native_map_id"),
            "map_cycle_id": item.raw.get("map_cycle_id"),
            "lifecycle_state": item.raw.get("lifecycle_state"),
            "context_status": item.raw.get("context_status"),
            "current_map_status": item.raw.get("current_map_status"),
            "rank": [item.rank[0], item.rank[1].isoformat()],
        }
        for item in ranked
    ]
    return (ranked[0] if ranked else None), rank_rows


def _price_band(
    *,
    current_price: Decimal,
    breakout_gate: Decimal,
    ext_1_272: Decimal,
    ext_1_618: Decimal,
    ext_2_000: Decimal,
) -> str:
    if current_price < breakout_gate:
        return "BELOW_BREAKOUT_GATE"
    if current_price < ext_1_272:
        return "ABOVE_GATE_APPROACHING_1272"
    if current_price < ext_1_618:
        return "BETWEEN_1272_1618"
    if current_price < ext_2_000:
        return "BETWEEN_1618_2000"
    return "ABOVE_2000"


def _build_fib_ext(row: dict[str, Any], current_price: Decimal | None) -> FibExtContext:
    effective_price = current_price or _dec(row.get("latest_primary_close_price")) or _required_dec(row, "max_high_since_anchor")
    ext_1_272 = _required_dec(row, "ext_1_272")
    ext_1_618 = _required_dec(row, "ext_1_618")
    ext_2_000 = _required_dec(row, "ext_2_000")
    breakout_gate = _required_dec(row, "breakout_gate")
    return FibExtContext(
        local_reaction_price=_required_dec(row, "anchor_high"),
        anchor_end_ts_utc=_dt(row["anchor_end_ts_utc"]),
        ext_1_272=ext_1_272,
        ext_1_618=ext_1_618,
        ext_2_000=ext_2_000,
        breakout_gate=breakout_gate,
        price_band=str(
            row.get("price_band")
            or _price_band(
                current_price=effective_price,
                breakout_gate=breakout_gate,
                ext_1_272=ext_1_272,
                ext_1_618=ext_1_618,
                ext_2_000=ext_2_000,
            )
        ),
        ext_1_272_touched_and_rejected=bool(row.get("ext_1_272_touched_and_rejected", False)),
        retesting_breakout_gate=bool(row.get("retesting_breakout_gate", False)),
    )


def _build_reentry(row: dict[str, Any]) -> ReentryContext:
    return ReentryContext(
        r382_price=_required_dec(row, "reload_r382"),
        r500_price=_required_dec(row, "reload_r500"),
        r618_price=_required_dec(row, "reload_r618"),
        r786_price=_required_dec(row, "reload_r786"),
        deepest_touched_label=row.get("deepest_touched_label"),
        missed_main_rebuy_by_pct=_dec(row.get("missed_main_rebuy_by_pct")),
    )


def _history_candle_from_map(row: dict[str, Any]) -> TargetHistoryCandle:
    return TargetHistoryCandle(
        close_ts_utc=_dt(row.get("latest_primary_close_ts_utc") or row["anchor_end_ts_utc"]),
        high_price=_required_dec(row, "max_high_since_anchor"),
        low_price=_required_dec(row, "min_low_since_anchor"),
    )


def _orders_from_fixture(fixture: dict[str, Any]) -> tuple[tuple[ForensicOrder, ...], tuple[ForensicOrder, ...]]:
    buy_orders: list[ForensicOrder] = []
    sell_orders: list[ForensicOrder] = []
    for raw in fixture.get("orders") or []:
        order = ForensicOrder(
            side=str(raw.get("side") or "").lower(),
            limit_price=_required_dec(raw, "limit_price"),
            map_cycle_id=str(raw.get("map_cycle_id") or ""),
            created_at_ms=int(raw["created_at_ms"]) if raw.get("created_at_ms") is not None else None,
            order_status=str(raw.get("order_status") or "OPEN"),
        )
        if order.side == "buy":
            buy_orders.append(order)
        elif order.side == "sell":
            sell_orders.append(order)
        else:
            raise ValueError(f"unsupported order side={order.side!r}")
    return tuple(buy_orders), tuple(sell_orders)


def _build_card_for_fixture(
    fixture: dict[str, Any],
    selected: SelectedMap | None,
    buy_orders: tuple[ForensicOrder, ...],
    sell_orders: tuple[ForensicOrder, ...],
):
    symbol = str(fixture["symbol"]).upper()
    market = str(fixture.get("market") or f"{symbol}-EUR")
    current_price = _dec(fixture.get("current_price"))
    current_price_status = fixture.get("current_price_status")
    current_price_age_min = _dec(fixture.get("current_price_age_min"))

    fib_ext = None
    reentry = None
    history_high = None
    history_low = None
    history_candles: tuple[TargetHistoryCandle, ...] = ()
    short_context_input_status = str(fixture.get("short_context_input_status") or "MISSING_ZONE_CONTEXT")
    short_context_coverage_status = str(fixture.get("short_context_coverage_status") or "FIB_MAP_SYMBOL_MISSING")
    short_context_display_state = str(fixture.get("short_context_display_state") or "NO_NATIVE_SHORT_FIB_CONTEXT")

    if selected is not None:
        row = selected.raw
        context_status = str(row.get("context_status") or "CONTEXT_INVALID_OR_STALE")
        short_context_input_status = context_status
        short_context_coverage_status = context_status
        short_context_display_state = (
            "HAS_NATIVE_SHORT_FIB_CONTEXT"
            if context_status == NATIVE_CONTEXT_AVAILABLE
            else "NO_NATIVE_SHORT_FIB_CONTEXT"
        )
        if context_status == NATIVE_CONTEXT_AVAILABLE:
            fib_ext = _build_fib_ext(row, current_price)
            reentry = _build_reentry(row)
            history_high = _required_dec(row, "max_high_since_anchor")
            history_low = _required_dec(row, "min_low_since_anchor")
            history_candles = (_history_candle_from_map(row),)

    return build_profit_plan_card(
        symbol=symbol,
        market=market,
        current_price=current_price,
        fib_trading_horizon="SHORT",
        short_context_input_status=short_context_input_status,
        short_context_coverage_status=short_context_coverage_status,
        short_context_display_state=short_context_display_state,
        fib_ext=fib_ext,
        reentry=reentry,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
        history_high_since_activation=history_high,
        history_low_since_activation=history_low,
        history_candles_since_activation=history_candles,
        current_price_status=str(current_price_status) if current_price_status else None,
        current_price_age_min=current_price_age_min,
        presentation_mode=CARD_MODE_POSITION_HELD,
    )


def _selected_cycle(selected: SelectedMap | None) -> str | None:
    return None if selected is None else str(selected.raw.get("map_cycle_id") or "")


def _selected_native_id(selected: SelectedMap | None) -> str | None:
    return None if selected is None else str(selected.raw.get("native_map_id") or "")


def _card_fields(card: Any, selected: SelectedMap | None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    fields = {
        "selected_map_cycle_id": _selected_cycle(selected),
        "selected_native_map_id": _selected_native_id(selected),
        "selected_lifecycle_state": None if selected is None else selected.raw.get("lifecycle_state"),
        "selected_context_status": None if selected is None else selected.raw.get("context_status"),
        "selected_current_map_status": None if selected is None else selected.raw.get("current_map_status"),
        "scenario_type": card.scenario_type,
        "setup_state": card.setup_state,
        "event_state": card.event_state,
        "primary_state": card.primary_state,
        "action_label": card.action_label,
        "actionability_state": card.actionability_state,
        "active_target": str(card.active_target) if card.active_target is not None else None,
        "target_exit_zone": [str(v) for v in card.target_exit_zone],
        "reload_reentry_zone": [str(v) for v in card.reload_reentry_zone],
        "invalidation_level": str(card.invalidation_level) if card.invalidation_level is not None else None,
        "distance_to_target_pct": str(card.distance_to_target_pct) if card.distance_to_target_pct is not None else None,
        "distance_to_reload_pct": str(card.distance_to_reload_pct) if card.distance_to_reload_pct is not None else None,
        "distance_to_invalidation_pct": str(card.distance_to_invalidation_pct)
        if card.distance_to_invalidation_pct is not None
        else None,
        "ladder_states": list(card.ladder_states),
        "short_context_display_state": card.short_context_display_state,
        "current_price_status": card.current_price_status,
        "all_sell_targets_completed": card.all_sell_targets_completed,
    }
    if extra:
        fields.update(extra)
    return fields


def _violation(
    *,
    fixture: dict[str, Any],
    selected: SelectedMap | None,
    invariant_id: str,
    severity: str,
    expected: str,
    actual: str,
    fields: dict[str, Any],
) -> Violation:
    return Violation(
        fixture_id=str(fixture["fixture_id"]),
        symbol=str(fixture["symbol"]).upper(),
        selected_map_cycle_id=_selected_cycle(selected),
        selected_native_map_id=_selected_native_id(selected),
        invariant_id=invariant_id,
        severity=severity,
        expected_semantics=expected,
        actual_semantics=actual,
        relevant_card_fields=fields,
    )


def _near(a: Decimal, b: Decimal) -> bool:
    if b <= 0:
        return False
    return abs(a - b) / b * Decimal("100") <= ORDER_MATCH_TOLERANCE_PCT


def _selected_target_levels(selected: SelectedMap | None) -> tuple[Decimal, ...]:
    if selected is None:
        return ()
    row = selected.raw
    levels = []
    levels.extend(_levels(row, "active_target_levels"))
    levels.extend(_levels(row, "previous_target_levels"))
    for key in ("ext_1_272", "ext_1_618", "ext_2_000"):
        levels.append(_required_dec(row, key))
    return tuple(dict.fromkeys(levels))


def _selected_map_levels(selected: SelectedMap | None) -> tuple[Decimal, ...]:
    if selected is None:
        return ()
    row = selected.raw
    levels = list(_selected_target_levels(selected))
    for key in (
        "breakout_gate",
        "reload_r382",
        "reload_r500",
        "reload_r618",
        "reload_r786",
        "invalidation",
        "anchor_low",
        "anchor_high",
    ):
        levels.append(_required_dec(row, key))
    return tuple(dict.fromkeys(levels))


def _parse_card_attrs(html: str) -> dict[str, str]:
    parser = _PlanCardSectionParser()
    parser.feed(html)
    return parser.plan_card_attrs or {}


def _audit_html_json_parity(
    *,
    fixture: dict[str, Any],
    selected: SelectedMap | None,
    card: Any,
    card_json: dict[str, Any],
    html: str,
) -> list[Violation]:
    violations: list[Violation] = []
    attrs = _parse_card_attrs(html)
    if not attrs:
        return [
            _violation(
                fixture=fixture,
                selected=selected,
                invariant_id="I007_HTML_JSON_PARITY",
                severity="HIGH",
                expected="HTML snapshot contains one rendered plan-card section with data attributes.",
                actual="No plan-card section data attributes were parsed.",
                fields=_card_fields(card, selected),
            )
        ]

    checks = [
        ("data-filter-setup", card_json["setup_state"], "setup_state"),
        ("data-filter-primary", card_json["primary_state"], "primary_state"),
        ("data-presentation-mode", card_json.get("presentation_mode"), "presentation_mode"),
    ]
    expected_order_label = _filter_display_label(_order_ladder_display_status(tuple(card_json["ladder_states"])))
    expected_order_value = _filter_value_from_label(expected_order_label)
    checks.append(("data-filter-orders", expected_order_value, "order_ladder_state"))
    expected_action_label = _filter_display_label(_effective_workflow_action(card))
    expected_action_value = _filter_value_from_label(expected_action_label)
    checks.append(("data-filter-action", expected_action_value, "workflow_action"))

    for attr, expected, field_name in checks:
        if expected is None:
            continue
        actual = attrs.get(attr)
        if actual != expected:
            violations.append(
                _violation(
                    fixture=fixture,
                    selected=selected,
                    invariant_id="I007_HTML_JSON_PARITY",
                    severity="HIGH",
                    expected=f"HTML {attr} mirrors JSON/helper {field_name}={expected!r}.",
                    actual=f"HTML {attr}={actual!r}.",
                    fields=_card_fields(card, selected, {"html_attrs": attrs, "json_field": field_name}),
                )
            )

    for literal, field_name in (
        (card_json["setup_state"], "setup_state"),
        (card_json["actionability_state"], "actionability_state"),
    ):
        if literal and literal not in html:
            violations.append(
                _violation(
                    fixture=fixture,
                    selected=selected,
                    invariant_id="I007_HTML_JSON_PARITY",
                    severity="MEDIUM",
                    expected=f"HTML visibly contains canonical JSON {field_name}={literal!r}.",
                    actual=f"{literal!r} not found in rendered card HTML.",
                    fields=_card_fields(card, selected, {"json_field": field_name}),
                )
            )
    return violations


def audit_invariants(
    *,
    fixture: dict[str, Any],
    selected: SelectedMap | None,
    rank_rows: list[dict[str, Any]],
    card: Any,
    card_json: dict[str, Any],
    html: str,
    buy_orders: tuple[ForensicOrder, ...],
    sell_orders: tuple[ForensicOrder, ...],
) -> list[Violation]:
    violations: list[Violation] = []
    expected_selected = fixture.get("expected_selected_map_cycle_id")
    selected_cycle = _selected_cycle(selected)
    selected_state = None if selected is None else str(selected.raw.get("lifecycle_state") or "")

    if selected_cycle != expected_selected:
        violations.append(
            _violation(
                fixture=fixture,
                selected=selected,
                invariant_id="I000_EXPECTED_SELECTION",
                severity="HIGH",
                expected=f"Fixture expected selected map_cycle_id={expected_selected!r}.",
                actual=f"Selected map_cycle_id={selected_cycle!r}.",
                fields=_card_fields(card, selected, {"candidate_rankings": rank_rows}),
            )
        )

    active_maps = [
        row
        for row in fixture.get("maps") or []
        if str(row.get("lifecycle_state") or "") in ACTIVE_OR_DEVELOPING_STATES
    ]
    if active_maps and selected_state not in ACTIVE_OR_DEVELOPING_STATES:
        violations.append(
            _violation(
                fixture=fixture,
                selected=selected,
                invariant_id="I001_ACTIVE_MAP_SELECTION_PRIORITY",
                severity="BLOCKER",
                expected="Any ACTIVE/DEVELOPING map ranks above COMPLETED and INVALIDATED maps.",
                actual=f"Selected lifecycle_state={selected_state!r} while active maps exist.",
                fields=_card_fields(card, selected, {"active_map_cycle_ids": [m.get("map_cycle_id") for m in active_maps]}),
            )
        )

    completed_selected = selected_state == PRIMARY_LIFECYCLE_COMPLETED or card.setup_state == "MAP_COMPLETED"
    if completed_selected:
        bad_completed_fields: dict[str, Any] = {}
        if card.active_target is not None:
            bad_completed_fields["active_target"] = str(card.active_target)
        if card.target_exit_zone:
            bad_completed_fields["target_exit_zone"] = [str(v) for v in card.target_exit_zone]
        active_ladder = sorted(set(card.ladder_states).intersection(ACTIVE_LADDER_STATES))
        if active_ladder:
            bad_completed_fields["active_ladder_states"] = active_ladder
        if card.action_label not in {"WAIT_FOR_NEW_MAP", "NAVIGATION_ONLY"}:
            bad_completed_fields["action_label"] = card.action_label
        if card.actionability_state == CARD_ACTIONABILITY_ACTIVE:
            bad_completed_fields["actionability_state"] = card.actionability_state
        if bad_completed_fields:
            violations.append(
                _violation(
                    fixture=fixture,
                    selected=selected,
                    invariant_id="I002_COMPLETED_MAP_HAS_NO_ACTIVE_CONTEXT",
                    severity="BLOCKER",
                    expected="Completed maps expose only historical/recompute context, no active target or ladder requirement.",
                    actual="Completed-map card retained active-looking fields.",
                    fields=_card_fields(card, selected, bad_completed_fields),
                )
            )

    if selected_state == PRIMARY_LIFECYCLE_INVALIDATED:
        invalidated_active = (
            card.actionability_state == CARD_ACTIONABILITY_ACTIVE
            or card.short_context_display_state == "HAS_NATIVE_SHORT_FIB_CONTEXT"
            or card.setup_state not in {"MINIMAL_CONTEXT", "MAP_COMPLETED"}
        )
        if invalidated_active:
            violations.append(
                _violation(
                    fixture=fixture,
                    selected=selected,
                    invariant_id="I003_INVALIDATED_MAP_NOT_ACTIVE_CONTEXT",
                    severity="BLOCKER",
                    expected="Invalidated maps are never active card context.",
                    actual="Invalidated selected map produced active/native setup context.",
                    fields=_card_fields(card, selected),
                )
            )

    stale_or_missing_price = card.current_price_status == "STALE_CURRENT_PRICE" or fixture.get("current_price") is None
    if stale_or_missing_price:
        bad_price_fields: dict[str, Any] = {}
        if any(
            value is not None
            for value in (card.distance_to_target_pct, card.distance_to_reload_pct, card.distance_to_invalidation_pct)
        ):
            bad_price_fields["distance_metrics"] = {
                "target": str(card.distance_to_target_pct) if card.distance_to_target_pct is not None else None,
                "reload": str(card.distance_to_reload_pct) if card.distance_to_reload_pct is not None else None,
                "invalidation": str(card.distance_to_invalidation_pct)
                if card.distance_to_invalidation_pct is not None
                else None,
            }
        if card.action_label in ACTION_LIKE_LABELS:
            bad_price_fields["action_label"] = card.action_label
        active_ladder = sorted(set(card.ladder_states).intersection(ACTIVE_LADDER_STATES))
        if active_ladder:
            bad_price_fields["ladder_states"] = active_ladder
        if bad_price_fields:
            violations.append(
                _violation(
                    fixture=fixture,
                    selected=selected,
                    invariant_id="I005_STALE_OR_MISSING_PRICE_BLOCKS_ACTION_OUTPUT",
                    severity="HIGH",
                    expected="Stale/missing current price blocks distance metrics and action-like entry/ladder guidance.",
                    actual="Card emitted price-dependent or action-like fields despite stale/missing price.",
                    fields=_card_fields(card, selected, bad_price_fields),
                )
            )

    selected_targets = _selected_target_levels(selected)
    selected_all_levels = _selected_map_levels(selected)
    if selected is not None and card.setup_state != "MINIMAL_CONTEXT":
        lineage_errors: dict[str, Any] = {}
        if card.active_target is not None and not any(_near(card.active_target, level) for level in selected_all_levels):
            lineage_errors["active_target"] = str(card.active_target)
            lineage_errors["selected_map_levels"] = [str(level) for level in selected_all_levels]
        if card.target_exit_zone:
            off_lineage = [
                str(level)
                for level in card.target_exit_zone
                if not any(_near(level, selected_level) for selected_level in selected_all_levels)
            ]
            if off_lineage:
                lineage_errors["target_exit_zone_off_lineage"] = off_lineage
        if card.reload_reentry_zone:
            bad_reload = [
                str(level)
                for level in card.reload_reentry_zone
                if not any(_near(level, selected_level) for selected_level in selected_all_levels)
            ]
            if bad_reload:
                lineage_errors["reload_reentry_zone_off_lineage"] = bad_reload
        if card.invalidation_level is not None and not any(
            _near(card.invalidation_level, selected_level) for selected_level in selected_all_levels
        ):
            lineage_errors["invalidation_level"] = str(card.invalidation_level)
            lineage_errors["selected_map_levels"] = [str(level) for level in selected_all_levels]
        if lineage_errors:
            violations.append(
                _violation(
                    fixture=fixture,
                    selected=selected,
                    invariant_id="I004_CARD_FIELDS_SHARE_SELECTED_MAP_LINEAGE",
                    severity="BLOCKER",
                    expected="Target, reload, invalidation and map identity come from one selected map lineage.",
                    actual="Card fields contain levels outside the selected map lineage.",
                    fields=_card_fields(card, selected, lineage_errors),
                )
            )

    order_rows = build_order_rows(
        card_render_id=card.render_id,
        actionability_state=card.actionability_state,
        current_price=card.current_price,
        buy_zone=() if card.all_sell_targets_completed else card.buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
    )
    active_order_lineage_errors: list[dict[str, Any]] = []
    all_orders = buy_orders + sell_orders
    for row in order_rows:
        if row.state != "ARMED" or row.price is None:
            continue
        matching_orders = [
            order
            for order in all_orders
            if order.side == row.side and _near(order.limit_price, row.price)
        ]
        if matching_orders and not any(order.map_cycle_id == selected_cycle for order in matching_orders):
            active_order_lineage_errors.append(
                {
                    "side": row.side,
                    "row_price": str(row.price),
                    "row_state": row.state,
                    "order_map_cycle_ids": [order.map_cycle_id for order in matching_orders],
                    "selected_map_cycle_id": selected_cycle,
                }
            )
    if active_order_lineage_errors:
        violations.append(
            _violation(
                fixture=fixture,
                selected=selected,
                invariant_id="I006_ORDER_ROWS_MATCH_ACTIVE_MAP_LINEAGE",
                severity="HIGH",
                expected="Only orders from the selected active map lineage count as active ladder coverage.",
                actual="Order rows counted old/stale lineage orders as ARMED coverage.",
                fields=_card_fields(card, selected, {"order_lineage_errors": active_order_lineage_errors}),
            )
        )

    if selected is not None:
        source_errors: dict[str, Any] = {}
        context_status = str(selected.raw.get("context_status") or "")
        current_map_status = str(selected.raw.get("current_map_status") or "")
        if selected_state == PRIMARY_LIFECYCLE_INVALIDATED and context_status == NATIVE_CONTEXT_AVAILABLE:
            source_errors["invalidated_context_status"] = context_status
        if selected_state == PRIMARY_LIFECYCLE_INVALIDATED and current_map_status == "CURRENT_ACTIVE_MAP":
            source_errors["invalidated_current_map_status"] = current_map_status
        if selected_state == PRIMARY_LIFECYCLE_COMPLETED and current_map_status == "CURRENT_ACTIVE_MAP":
            source_errors["completed_current_map_status"] = current_map_status
        if source_errors:
            violations.append(
                _violation(
                    fixture=fixture,
                    selected=selected,
                    invariant_id="I008_LIFECYCLE_SOURCE_STATUS_COMPATIBILITY",
                    severity="HIGH",
                    expected="Lifecycle, source status, current_map_status and action labels are semantically compatible.",
                    actual="Source lifecycle/status fields contradict active-card semantics.",
                    fields=_card_fields(card, selected, source_errors),
                )
            )

    violations.extend(
        _audit_html_json_parity(
            fixture=fixture,
            selected=selected,
            card=card,
            card_json=card_json,
            html=html,
        )
    )
    return violations


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_violation_csv(path: Path, violations: list[Violation]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVARIANT_FIELDS)
        writer.writeheader()
        for violation in violations:
            writer.writerow(violation.to_csv_row())


def replay_fixtures(
    *,
    fixtures_path: Path = DEFAULT_FIXTURES_PATH,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload = _load_fixture_payload(fixtures_path)
    resolved_run_id = run_id or _run_id()
    output_dir = output_root / resolved_run_id
    json_dir = output_dir / "card_json_snapshots"
    html_dir = output_dir / "card_html_snapshots"
    json_dir.mkdir(parents=True, exist_ok=False)
    html_dir.mkdir(parents=True, exist_ok=False)

    all_results: list[dict[str, Any]] = []
    all_violations: list[Violation] = []
    started_at = _iso_now()
    print(
        f"STARTED runner={RUNNER_NAME} mode=research_read_only scope=fixtures worker_count=1 "
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "decision_gate=none execution_planner=none executor=none",
        flush=True,
    )

    for fixture in payload["fixtures"]:
        fixture_id = str(fixture["fixture_id"])
        selected, rank_rows = _select_fixture_map(fixture)
        buy_orders, sell_orders = _orders_from_fixture(fixture)
        card = _build_card_for_fixture(fixture, selected, buy_orders, sell_orders)
        snapshot = build_json_snapshot(
            [card],
            broker_mode="offline_research",
            snapshot_ts=started_at,
            generated_ts_utc=started_at,
            render_id=f"{RUNNER_NAME}:{fixture_id}",
            writer_instance_id=RUNNER_NAME,
        )
        card_json = snapshot["symbols"][0]
        html = render_plan_card(card, buy_orders=buy_orders, sell_orders=sell_orders)
        violations = audit_invariants(
            fixture=fixture,
            selected=selected,
            rank_rows=rank_rows,
            card=card,
            card_json=card_json,
            html=html,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
        )
        all_violations.extend(violations)

        selected_payload = None
        if selected is not None:
            selected_payload = {
                "native_map_id": selected.raw.get("native_map_id"),
                "map_cycle_id": selected.raw.get("map_cycle_id"),
                "lifecycle_state": selected.raw.get("lifecycle_state"),
                "context_status": selected.raw.get("context_status"),
                "current_map_status": selected.raw.get("current_map_status"),
                "rank": [selected.rank[0], selected.rank[1].isoformat()],
            }

        order_rows = build_order_rows(
            card_render_id=card.render_id,
            actionability_state=card.actionability_state,
            current_price=card.current_price,
            buy_zone=() if card.all_sell_targets_completed else card.buy_zone,
            target_level_statuses=card.target_level_statuses,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
        )
        result = {
            "fixture_id": fixture_id,
            "symbol": fixture["symbol"],
            "selected_map": selected_payload,
            "candidate_rankings": rank_rows,
            "selection_reason": (
                "No map fixture available; card built as missing native-short context."
                if selected is None
                else "Selected by native_short_fib_context_v1._candidate_rank; active/developing outranks completed outranks invalidated, then newer anchor_end wins."
            ),
            "card_json_path": str((json_dir / f"{fixture_id}.json").relative_to(output_dir)),
            "card_html_path": str((html_dir / f"{fixture_id}.html").relative_to(output_dir)),
            "card_semantics": {
                "setup_state": card.setup_state,
                "event_state": card.event_state,
                "primary_state": card.primary_state,
                "scenario_type": card.scenario_type,
                "action_label": card.action_label,
                "actionability_state": card.actionability_state,
                "ladder_states": list(card.ladder_states),
                "active_target": str(card.active_target) if card.active_target is not None else None,
                "target_exit_zone": [str(v) for v in card.target_exit_zone],
                "reload_reentry_zone": [str(v) for v in card.reload_reentry_zone],
                "invalidation_level": str(card.invalidation_level) if card.invalidation_level is not None else None,
            },
            "order_rows": [
                {
                    "state": row.state,
                    "reason_code": row.reason_code,
                    "side": row.side,
                    "price": str(row.price) if row.price is not None else None,
                    "distance_pct": str(row.distance_pct) if row.distance_pct is not None else None,
                    "zone_role": row.zone_role,
                }
                for row in order_rows
            ],
            "violation_count": len(violations),
            "violations": [violation.to_json() for violation in violations],
        }
        all_results.append(result)

        _write_json(
            json_dir / f"{fixture_id}.json",
            {
                "fixture_id": fixture_id,
                "selected_map": selected_payload,
                "candidate_rankings": rank_rows,
                "canonical_card_json": card_json,
            },
        )
        (html_dir / f"{fixture_id}.html").write_text(html, encoding="utf-8")
        print(
            f"fixture={fixture_id} selected_map_cycle_id={selected_cycle if (selected_cycle := _selected_cycle(selected)) else 'none'} "
            f"violations={len(violations)}",
            flush=True,
        )

    fixture_results_path = output_dir / "fixture_results.jsonl"
    with fixture_results_path.open("w", encoding="utf-8") as handle:
        for result in all_results:
            handle.write(json.dumps(result, sort_keys=True) + "\n")

    _write_violation_csv(output_dir / "invariant_violations.csv", all_violations)

    severity_counts: dict[str, int] = {}
    invariant_counts: dict[str, int] = {}
    for violation in all_violations:
        severity_counts[violation.severity] = severity_counts.get(violation.severity, 0) + 1
        invariant_counts[violation.invariant_id] = invariant_counts.get(violation.invariant_id, 0) + 1

    summary = {
        "runner": RUNNER_NAME,
        "run_id": resolved_run_id,
        "fixtures_path": str(fixtures_path),
        "output_dir": str(output_dir),
        "started_at_utc": started_at,
        "finished_at_utc": _iso_now(),
        "fixture_count": len(all_results),
        "violation_count": len(all_violations),
        "severity_counts": severity_counts,
        "invariant_counts": invariant_counts,
        "safety": {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "decision_gate": "none",
            "execution_planner": "none",
            "executor": "none",
        },
    }
    _write_json(output_dir / "summary.json", summary)
    _write_json(
        output_dir / "manifest.json",
        {
            "runner": RUNNER_NAME,
            "run_id": resolved_run_id,
            "schema_version": RUNNER_NAME,
            "input_fixtures": str(fixtures_path),
            "outputs": {
                "fixture_results_jsonl": "fixture_results.jsonl",
                "invariant_violations_csv": "invariant_violations.csv",
                "card_json_snapshots": "card_json_snapshots/",
                "card_html_snapshots": "card_html_snapshots/",
                "summary_json": "summary.json",
                "manifest_json": "manifest.json",
            },
            "safety_markers": summary["safety"],
        },
    )
    print(
        f"FINISHED runner={RUNNER_NAME} fixtures={len(all_results)} violations={len(all_violations)} "
        f"output_dir={output_dir} broker_private_calls=0 broker_writes=0 order_submission=0 "
        "live_orders=0 decision_gate=none execution_planner=none executor=none",
        flush=True,
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay deterministic Profit Plan card fixtures against existing card/render helpers "
            "and record forensic invariant violations. Research-only; no DB or broker access."
        )
    )
    parser.add_argument("--fixtures-path", type=Path, default=DEFAULT_FIXTURES_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    replay_fixtures(
        fixtures_path=args.fixtures_path,
        output_root=args.output_root,
        run_id=args.run_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
