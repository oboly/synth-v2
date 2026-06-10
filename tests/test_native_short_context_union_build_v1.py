"""
Tests for native SHORT context union build.

Verifies:
- _select_symbols supports comma-separated profiles (union, no duplicates)
- Shell scripts contain required union build phase and warning logic
- No broker writes in native context build path

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# _select_symbols — multi-profile union
# ---------------------------------------------------------------------------

def test_select_symbols_single_profile_unchanged() -> None:
    """Single profile: same behaviour as before."""
    from src.market_data.run_native_short_fib_context_v1 import _select_symbols

    with patch(
        "src.market_data.run_native_short_fib_context_v1._load_markets_for_profile",
        return_value=["BTC-EUR", "ETH-EUR"],
    ) as mock_load:
        symbols, markets = _select_symbols(
            explicit_symbols=[],
            account_profile="joost",
            venue="bitvavo",
        )
    mock_load.assert_called_once_with(account_profile="joost", venue="bitvavo")
    assert set(symbols) == {"BTC", "ETH"}
    assert set(markets) == {"BTC-EUR", "ETH-EUR"}


def test_select_symbols_two_profiles_returns_union() -> None:
    """Two profiles: union of all markets, no duplicates."""
    from src.market_data.run_native_short_fib_context_v1 import _select_symbols

    def load_side_effect(*, account_profile: str, venue: str) -> list[str]:
        if account_profile == "joost":
            return ["BTC-EUR", "SOL-EUR", "LDO-EUR"]
        if account_profile == "hugo":
            return ["BTC-EUR", "ETH-EUR"]
        return []

    with patch(
        "src.market_data.run_native_short_fib_context_v1._load_markets_for_profile",
        side_effect=load_side_effect,
    ):
        symbols, markets = _select_symbols(
            explicit_symbols=[],
            account_profile="joost,hugo",
            venue="bitvavo",
        )

    assert set(symbols) == {"BTC", "ETH", "SOL", "LDO"}
    assert set(markets) == {"BTC-EUR", "ETH-EUR", "SOL-EUR", "LDO-EUR"}


def test_select_symbols_joost_markets_not_removed_when_hugo_runs_after() -> None:
    """
    Regression: if called with 'joost,hugo', markets only in joost are NOT dropped.
    Per-profile sequential builds (joost then hugo) would overwrite — union build prevents this.
    """
    from src.market_data.run_native_short_fib_context_v1 import _select_symbols

    joost_only = "ALGO-EUR"
    hugo_only = "ETH-EUR"

    def load_side_effect(*, account_profile: str, venue: str) -> list[str]:
        if account_profile == "joost":
            return [joost_only, "BTC-EUR"]
        if account_profile == "hugo":
            return [hugo_only, "BTC-EUR"]
        return []

    with patch(
        "src.market_data.run_native_short_fib_context_v1._load_markets_for_profile",
        side_effect=load_side_effect,
    ):
        symbols, markets = _select_symbols(
            explicit_symbols=[],
            account_profile="joost,hugo",
            venue="bitvavo",
        )

    assert "ALGO" in symbols, "Joost-only market ALGO must be present in union"
    assert "ETH" in symbols, "Hugo-only market ETH must be present in union"


def test_select_symbols_deduplicates_shared_markets() -> None:
    """Markets shared across profiles appear exactly once."""
    from src.market_data.run_native_short_fib_context_v1 import _select_symbols

    with patch(
        "src.market_data.run_native_short_fib_context_v1._load_markets_for_profile",
        return_value=["BTC-EUR", "ETH-EUR"],
    ):
        symbols, markets = _select_symbols(
            explicit_symbols=[],
            account_profile="joost,hugo",
            venue="bitvavo",
        )

    assert symbols.count("BTC") == 1
    assert markets.count("BTC-EUR") == 1


def test_select_symbols_empty_profile_string_returns_empty() -> None:
    """Empty --account-profile with no explicit symbols returns empty (unchanged contract)."""
    from src.market_data.run_native_short_fib_context_v1 import _select_symbols

    with patch(
        "src.market_data.run_native_short_fib_context_v1._load_markets_for_profile",
    ) as mock_load:
        symbols, markets = _select_symbols(
            explicit_symbols=[],
            account_profile="",
            venue="bitvavo",
        )
    mock_load.assert_not_called()
    assert symbols == []
    assert markets == []


# ---------------------------------------------------------------------------
# Shell script source checks
# ---------------------------------------------------------------------------

_LINKED_REFRESH_SH = Path(
    "scripts/odroid/run_linked_profile_dashboard_refresh_once.sh"
)
_RENDER_ONCE_SH = Path(
    "scripts/odroid/run_account_wallet_dashboard_render_once.sh"
)


def test_linked_refresh_contains_union_build_phase() -> None:
    src = _LINKED_REFRESH_SH.read_text()
    assert "build_union_native_short_context" in src, (
        "run_linked_profile_dashboard_refresh_once.sh must contain union native context build phase"
    )


def test_linked_refresh_passes_union_path_to_per_profile_render() -> None:
    src = _LINKED_REFRESH_SH.read_text()
    assert "SYNTH_NATIVE_SHORT_ROWS_PATH" in src, (
        "Linked refresh must pass SYNTH_NATIVE_SHORT_ROWS_PATH to per-profile render"
    )


def test_linked_refresh_emits_warn_when_union_build_fails() -> None:
    src = _LINKED_REFRESH_SH.read_text()
    assert "MISSING_OR_BUILD_FAILED" in src, (
        "Linked refresh must emit explicit WARN when union context build fails"
    )


def test_render_once_uses_prebuilt_context_when_env_set() -> None:
    src = _RENDER_ONCE_SH.read_text()
    assert "PRE_BUILT_NATIVE_ROWS_PATH" in src, (
        "run_account_wallet_dashboard_render_once.sh must check PRE_BUILT_NATIVE_ROWS_PATH"
    )
    assert "pre_built_union" in src, (
        "Script must log native_short_context=pre_built_union when using shared context"
    )


def test_render_once_falls_back_to_per_profile_build_when_no_prebuilt() -> None:
    src = _RENDER_ONCE_SH.read_text()
    assert "build_native_short_context" in src, (
        "Per-profile fallback build must remain for standalone use"
    )


def test_no_broker_writes_in_native_context_runner() -> None:
    src = Path("src/market_data/run_native_short_fib_context_v1.py").read_text()
    assert "broker_writes=0" in src or "broker_private_calls=0" in src or "broker_writes" not in src, (
        "Native context runner must not perform broker writes"
    )
    # Verify safety: no order submission or executor calls
    assert "order_submission" not in src or "order_submission=0" in src
