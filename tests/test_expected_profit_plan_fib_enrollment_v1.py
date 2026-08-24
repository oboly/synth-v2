"""Regression contract for the Issue #505 canonical Fib cohort enrollment."""
from __future__ import annotations

import re
from pathlib import Path


MIGRATION = Path("db/migrations/20260824_expected_profit_plan_fib_enrollment_v1.sql")
EXPECTED_SYMBOLS = {"AERO", "ARB", "CHIP", "PENDLE", "TIA"}
NOT_EXPECTED_SYMBOLS = {"BILL", "POL"}


def _source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_exact_expected_profit_plan_fib_cohort_is_enrolled() -> None:
    symbols = set(re.findall(r"'([A-Z0-9]+)'", _source()))

    assert EXPECTED_SYMBOLS <= symbols
    assert not (NOT_EXPECTED_SYMBOLS & symbols)
    assert symbols == EXPECTED_SYMBOLS | {"EUR"}


def test_enrollment_is_limited_to_enabled_tradeable_bitvavo_eur_markets() -> None:
    source = _source()

    assert "JOIN venue_market AS vm" in source
    for predicate in (
        "a.is_enabled = 1",
        "COALESCE(a.is_tradeable, 0) = 1",
        "vm.venue = 'bitvavo'",
        "vm.quote_currency = 'EUR'",
        "vm.is_tradeable = 1",
    ):
        assert predicate in source


def test_migration_updates_only_canonical_cohort_authority_and_legacy_mirror() -> None:
    source = "\n".join(
        line for line in _source().splitlines() if not line.lstrip().startswith("--")
    )

    assert "SET a.is_publication_cohort = 1," in source
    assert "a.is_portfolio = 1" in source
    forbidden = ("reporting", "decision_gate", "execution_planner", "executor", "broker")
    assert not any(token in source.lower() for token in forbidden)
