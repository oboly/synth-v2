from pathlib import Path


def test_acceptance_stops_at_phase4b_orchestrator_without_execution_dependencies() -> None:
    text = (Path(__file__).resolve().parents[1] / "src/exit_policy/automatic_exit_dry_run_acceptance_v1.py").read_text()
    assert "evaluate_automatic_exit_runtime_item_v1" in text
    for forbidden in ("src.executor", "credential_resolver", "broker_client", "selection_engine", "manual_execution", "submit_order", "place_order", "-EUR", "active_target_price <=", "invalidation_price >=", "round_quantity", "ladder"):
        assert forbidden not in text
