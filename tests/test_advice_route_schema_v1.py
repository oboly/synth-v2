from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from src.advice_route.schema_v1 import (
    ROUTE_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_PAYLOAD_TYPES,
    validate_envelope,
)


def _make_valid_envelope(**overrides: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "payload_type": "strategy_proposal",
        "route_version": ROUTE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "payload": {"symbol": "BTC", "setup_id": "SELL_SHORT_SPIKE"},
    }
    envelope.update(overrides)
    return envelope


def test_valid_strategy_proposal_envelope_passes() -> None:
    validate_envelope(_make_valid_envelope())


def test_unknown_payload_type_rejected() -> None:
    try:
        validate_envelope(_make_valid_envelope(payload_type="order_submission"))
    except ValueError as exc:
        assert "payload_type" in str(exc)
        return
    raise AssertionError("Expected ValueError for unknown payload_type")


def test_unsupported_route_version_rejected() -> None:
    try:
        validate_envelope(_make_valid_envelope(route_version="v99"))
    except ValueError as exc:
        assert "route_version" in str(exc)
        return
    raise AssertionError("Expected ValueError for unsupported route_version")


def test_unsupported_schema_version_rejected() -> None:
    try:
        validate_envelope(_make_valid_envelope(schema_version="v99"))
    except ValueError as exc:
        assert "schema_version" in str(exc)
        return
    raise AssertionError("Expected ValueError for unsupported schema_version")


def test_forbidden_fields_rejected() -> None:
    envelope = _make_valid_envelope()
    envelope["broker_order_payload"] = {"unsafe": True}
    try:
        validate_envelope(envelope)
    except ValueError as exc:
        assert "Forbidden field" in str(exc)
        return
    raise AssertionError("Expected ValueError for forbidden field in envelope")


def test_missing_required_key_rejected() -> None:
    envelope = _make_valid_envelope()
    del envelope["payload_type"]
    try:
        validate_envelope(envelope)
    except ValueError as exc:
        assert "missing required keys" in str(exc)
        return
    raise AssertionError("Expected ValueError for missing required key")


def test_non_dict_payload_rejected() -> None:
    try:
        validate_envelope(_make_valid_envelope(payload="not-a-dict"))
    except ValueError as exc:
        assert "payload" in str(exc).lower()
        return
    raise AssertionError("Expected ValueError for non-dict payload")


def test_all_supported_payload_types_accepted() -> None:
    for payload_type in SUPPORTED_PAYLOAD_TYPES:
        validate_envelope(_make_valid_envelope(payload_type=payload_type))


def test_module_has_no_forbidden_imports() -> None:
    source = Path("src/advice_route/schema_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_terms = (
        "decision_gate",
        "execution_planner",
        "executor",
        "broker",
        "bitvavo_client",
        "account_position",
        "balance_snapshot",
        "order_snapshot",
        "db",
    )
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    for module_name in imported_modules:
        parts = tuple(part for part in module_name.split(".") if part)
        for term in forbidden_terms:
            assert term not in parts, f"Forbidden module import found: {module_name}"

    forbidden_dotted_refs = (
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
        "src.common.db",
    )
    for dotted_ref in forbidden_dotted_refs:
        assert dotted_ref not in source, f"Forbidden module reference found: {dotted_ref}"


def main() -> None:
    tests = [
        test_valid_strategy_proposal_envelope_passes,
        test_unknown_payload_type_rejected,
        test_unsupported_route_version_rejected,
        test_unsupported_schema_version_rejected,
        test_forbidden_fields_rejected,
        test_missing_required_key_rejected,
        test_non_dict_payload_rejected,
        test_all_supported_payload_types_accepted,
        test_module_has_no_forbidden_imports,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
