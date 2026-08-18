from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
CANONICAL_4H_CONTEXT_AVAILABLE = "CANONICAL_4H_CONTEXT_AVAILABLE"


@dataclass(frozen=True)
class HeldCoverageProblem:
    symbol: str
    code: str
    detail: str


@dataclass(frozen=True)
class HeldCoverageReport:
    held_symbols: tuple[str, ...]
    rendered_wallet_held_symbols: tuple[str, ...]
    problems: tuple[HeldCoverageProblem, ...]

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def held_count(self) -> int:
        return len(self.held_symbols)

    @property
    def rendered_wallet_held_count(self) -> int:
        return len(self.rendered_wallet_held_symbols)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == DATA_UNAVAILABLE:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _normalized_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _symbol_rows(snapshot: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    rows_by_symbol: dict[str, list[Mapping[str, Any]]] = {}
    for raw in snapshot.get("symbols") or []:
        if not isinstance(raw, Mapping):
            continue
        symbol = _normalized_symbol(raw.get("symbol"))
        if symbol:
            rows_by_symbol.setdefault(symbol, []).append(raw)
    return rows_by_symbol


def _wallet_held_symbols(rows_by_symbol: Mapping[str, list[Mapping[str, Any]]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            symbol
            for symbol, rows in rows_by_symbol.items()
            if any(row.get("is_wallet_held") is True for row in rows)
        )
    )


def _problem(symbol: str, code: str, detail: str) -> HeldCoverageProblem:
    return HeldCoverageProblem(symbol=symbol, code=code, detail=detail)


def audit_profit_plan_held_coverage(
    *,
    snapshot: Mapping[str, Any],
    held_amount_by_symbol: Mapping[str, Decimal],
    held_eur_value_by_symbol: Mapping[str, Decimal | None],
    expected_account_snapshot_ts_utc: str | None = None,
    expected_wallet_snapshot_status: str | None = None,
) -> HeldCoverageReport:
    """Audit held-token Profit Plan coverage against persisted account truth.

    This is a reporting-only invariant. It never discovers markets, computes Fib
    levels, invents lifecycle state, infers cost basis, or grants trade
    permission. The expected held universe is supplied by the caller from the
    latest persisted balance snapshot.

    A held asset is considered covered only when exactly one card exists and the
    card preserves current wallet amount/value truth, visible wallet freshness,
    visible price provenance when a price is present, and either numeric Planning
    PPP or a precise unavailable reason. Canonical 4h levels are required only
    when the card itself says canonical 4h context is available. Native SHORT
    lifecycle context is deliberately not required.
    """
    held_symbols = tuple(
        sorted(
            _normalized_symbol(symbol)
            for symbol, amount in held_amount_by_symbol.items()
            if _normalized_symbol(symbol) and amount > 0
        )
    )
    rows_by_symbol = _symbol_rows(snapshot)
    rendered_wallet_held_symbols = _wallet_held_symbols(rows_by_symbol)
    problems: list[HeldCoverageProblem] = []

    if expected_account_snapshot_ts_utc is not None:
        observed = str(snapshot.get("account_snapshot_ts_utc") or "")
        if observed != expected_account_snapshot_ts_utc:
            problems.append(
                _problem(
                    "*",
                    "ACCOUNT_SNAPSHOT_TS_MISMATCH",
                    f"expected={expected_account_snapshot_ts_utc} observed={observed or DATA_UNAVAILABLE}",
                )
            )

    expected_held_count = len(held_symbols)
    snapshot_held_count = snapshot.get("wallet_held_count")
    if snapshot_held_count != expected_held_count:
        problems.append(
            _problem(
                "*",
                "WALLET_HELD_COUNT_MISMATCH",
                f"expected={expected_held_count} observed={snapshot_held_count}",
            )
        )

    for symbol in rendered_wallet_held_symbols:
        if symbol not in held_symbols:
            problems.append(
                _problem(
                    symbol,
                    "STALE_OR_UNEXPECTED_WALLET_HELD_CARD",
                    "card is marked is_wallet_held=true but the latest persisted balance is not positive",
                )
            )

    for symbol in held_symbols:
        rows = rows_by_symbol.get(symbol, [])
        if not rows:
            problems.append(
                _problem(symbol, "HELD_CARD_MISSING", "positive persisted balance has no Profit Plan card")
            )
            continue
        if len(rows) != 1:
            problems.append(
                _problem(symbol, "HELD_CARD_DUPLICATE", f"expected exactly one card, observed={len(rows)}")
            )
            continue

        row = rows[0]
        evidence = row.get("evidence") if isinstance(row.get("evidence"), Mapping) else {}

        if row.get("is_wallet_held") is not True:
            problems.append(
                _problem(symbol, "WALLET_HELD_FLAG_FALSE", "positive persisted balance is not marked wallet-held")
            )

        expected_amount = held_amount_by_symbol[symbol]
        observed_amount = _decimal_or_none(evidence.get("held_amount"))
        if observed_amount != expected_amount:
            problems.append(
                _problem(
                    symbol,
                    "HELD_AMOUNT_MISMATCH",
                    f"expected={expected_amount} observed={evidence.get('held_amount', DATA_UNAVAILABLE)}",
                )
            )

        expected_value = held_eur_value_by_symbol.get(symbol)
        observed_value_raw = evidence.get("held_eur_value")
        observed_value = _decimal_or_none(observed_value_raw)
        if expected_value is None:
            if str(observed_value_raw or DATA_UNAVAILABLE) != DATA_UNAVAILABLE:
                problems.append(
                    _problem(
                        symbol,
                        "HELD_EUR_VALUE_SHOULD_BE_UNAVAILABLE",
                        "current persisted price is unavailable, so held EUR value must not be fabricated",
                    )
                )
        elif observed_value != expected_value:
            problems.append(
                _problem(
                    symbol,
                    "HELD_EUR_VALUE_MISMATCH",
                    f"expected={expected_value} observed={observed_value_raw or DATA_UNAVAILABLE}",
                )
            )

        wallet_status = str(evidence.get("wallet_snapshot_status") or DATA_UNAVAILABLE).upper()
        if wallet_status == DATA_UNAVAILABLE:
            problems.append(
                _problem(symbol, "WALLET_FRESHNESS_UNAVAILABLE", "wallet snapshot freshness/status is not visible")
            )
        elif expected_wallet_snapshot_status is not None and wallet_status != expected_wallet_snapshot_status.upper():
            problems.append(
                _problem(
                    symbol,
                    "WALLET_FRESHNESS_MISMATCH",
                    f"expected={expected_wallet_snapshot_status.upper()} observed={wallet_status}",
                )
            )

        current_price = _decimal_or_none(row.get("current_price"))
        price_status = str(row.get("current_price_status") or DATA_UNAVAILABLE).upper()
        price_ts = str(evidence.get("price_ts_utc") or DATA_UNAVAILABLE)
        price_freshness = str(evidence.get("price_freshness_state") or DATA_UNAVAILABLE).upper()
        if current_price is not None:
            if price_status == DATA_UNAVAILABLE or price_ts == DATA_UNAVAILABLE or price_freshness == DATA_UNAVAILABLE:
                problems.append(
                    _problem(
                        symbol,
                        "PRICE_PROVENANCE_INCOMPLETE",
                        "numeric current price requires visible status, source timestamp and freshness state",
                    )
                )

        planning_ppp = _decimal_or_none(row.get("planning_ppp_pct"))
        unavailable_reason = str(row.get("planning_ppp_unavailable_reason") or "").strip()
        if planning_ppp is None and not unavailable_reason:
            problems.append(
                _problem(
                    symbol,
                    "PLANNING_PPP_WITHOUT_REASON",
                    "Planning PPP is unavailable but no precise unavailable reason is rendered",
                )
            )

        coverage_status = str(row.get("short_context_coverage_status") or "").upper()
        if coverage_status == CANONICAL_4H_CONTEXT_AVAILABLE:
            reentry = row.get("reload_reentry_zone") or row.get("buy_zone") or []
            targets = row.get("target_exit_zone") or []
            invalidation = row.get("invalidation_risk_zone") or row.get("invalidation_level")
            if not reentry:
                problems.append(
                    _problem(symbol, "CANONICAL_REENTRY_LEVEL_MISSING", "canonical 4h context is available but no re-entry level is exposed")
                )
            if not targets:
                problems.append(
                    _problem(symbol, "CANONICAL_TARGET_LEVEL_MISSING", "canonical 4h context is available but no target level is exposed")
                )
            if invalidation is None:
                problems.append(
                    _problem(symbol, "CANONICAL_INVALIDATION_LEVEL_MISSING", "canonical 4h context is available but no invalidation level is exposed")
                )

        cost_basis = str(evidence.get("cost_basis_price_eur") or DATA_UNAVAILABLE)
        position_status = str(evidence.get("position_snapshot_status") or DATA_UNAVAILABLE).upper()
        if cost_basis != DATA_UNAVAILABLE and position_status == DATA_UNAVAILABLE:
            problems.append(
                _problem(
                    symbol,
                    "COST_BASIS_PROVENANCE_INCOMPLETE",
                    "persisted cost basis is present but its account-position authority status is unavailable",
                )
            )

    return HeldCoverageReport(
        held_symbols=held_symbols,
        rendered_wallet_held_symbols=rendered_wallet_held_symbols,
        problems=tuple(problems),
    )
