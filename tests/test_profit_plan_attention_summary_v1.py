from pathlib import Path
from types import SimpleNamespace

from src.reporting.manual_short_trader_profit_plan_v1 import (
    VISIBILITY_CONTEXT_UNAVAILABLE,
    VISIBILITY_NATIVE_ATTENTION,
)
from src.reporting.run_manual_short_trader_profit_plan_v1 import print_summary


def _card(*, symbol: str, attention_required: bool, visibility_class: str):
    return SimpleNamespace(
        symbol=symbol,
        short_context_coverage_status="MARKET_DATA_MISSING",
        visibility_class=visibility_class,
        attention_required=attention_required,
        scenario_type="TEST",
        action_label="WAIT",
        primary_state="WAIT_FOR_ENTRY",
        is_relevant=True,
    )


def test_print_summary_attention_uses_canonical_attention_required(capsys, tmp_path: Path) -> None:
    context = SimpleNamespace(
        profile="test",
        account_code="test",
        trading_account_id=1,
        venue="bitvavo",
        markets=("AAA-EUR", "BBB-EUR"),
        orders=(),
    )
    cards = [
        _card(symbol="AAA", attention_required=False, visibility_class=VISIBILITY_NATIVE_ATTENTION),
        _card(symbol="BBB", attention_required=True, visibility_class=VISIBILITY_CONTEXT_UNAVAILABLE),
    ]
    print_summary(
        context=context,
        cards=cards,
        output_html=tmp_path / "profit-plan.html",
        output_json=tmp_path / "profit-plan.json",
    )
    output = capsys.readouterr().out
    assert "attention=1/2" in output
    assert "canonical_navigation=0/2" in output
    assert "context_unavailable=1/2" in output
