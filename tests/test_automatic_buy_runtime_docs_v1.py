from pathlib import Path


def test_automatic_buy_runtime_docs_keep_audit_separate_from_executor_input() -> None:
    text = Path("docs/architecture/automatic_buy_runtime_v1.md").read_text()
    assert "MUST NOT become executor input" in text
    assert "typed in-memory `AutomaticBuyPlanV1`" in text
    assert "does not install or enable a service/timer" in text
