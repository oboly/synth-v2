from __future__ import annotations

"""Privacy-boundary guard for the entry-candidate static dashboard.

The entry-candidate dashboard (rendered into entry-candidates.html by the MVP
cockpit) must remain market-only and account-agnostic. It must never read,
receive, render or derive from account balances, wallets, positions, open
orders, linked-profile account snapshots, private broker endpoints/clients,
decision_gate output, execution plans, or executor state.

This guard inspects the actual import closure, CLI arguments, and SQL table
references rather than relying on filename matching.
"""

import ast
from pathlib import Path


MODULE_PATH = Path("src/reporting/run_entry_candidate_static_dashboard_v1.py")

# Substrings that, if present in an imported src.* module path, indicate an
# account-aware / private-broker / decision / execution dependency.
FORBIDDEN_IMPORT_SUBSTRINGS = (
    "account",
    "wallet",
    "balance",
    "position",
    "broker",
    "decision_gate",
    "execution",
    "executor",
    "private",
    "profile",
)

# Account/private tables that must never appear in a FROM/JOIN clause.
FORBIDDEN_TABLE_SUBSTRINGS = (
    "account_balance",
    "account_asset",
    "account_position",
    "account_wallet",
    "balance_snapshot",
    "position_snapshot",
    "order_snapshot",
    "open_order",
    "wallet_snapshot",
)


def _src_import_closure(entry: Path) -> set[str]:
    """Return the set of first-party (src.*) modules reachable from entry."""
    seen_files: set[Path] = set()
    imported: set[str] = set()
    stack = [entry]
    while stack:
        current = stack.pop()
        if current in seen_files or not current.exists():
            continue
        seen_files.add(current)
        tree = ast.parse(current.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for mod in mods:
                if mod.startswith("src."):
                    imported.add(mod)
                    candidate = Path(mod.replace(".", "/") + ".py")
                    if candidate.exists():
                        stack.append(candidate)
    return imported


def test_entry_candidate_import_closure_is_account_agnostic() -> None:
    closure = _src_import_closure(MODULE_PATH)
    assert closure, "expected to resolve a non-empty src import closure"
    offenders = {
        mod
        for mod in closure
        for token in FORBIDDEN_IMPORT_SUBSTRINGS
        if token in mod
    }
    assert not offenders, f"entry-candidate closure imports account/private modules: {sorted(offenders)}"


def test_entry_candidate_cli_has_no_account_or_profile_args() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    added_args: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            added_args.append(str(node.args[0].value))
    assert added_args, "expected argparse arguments to be discoverable"
    for flag in added_args:
        low = flag.lower()
        assert "account" not in low, f"entry-candidate exposes account arg: {flag}"
        assert "profile" not in low, f"entry-candidate exposes profile arg: {flag}"
        assert "wallet" not in low, f"entry-candidate exposes wallet arg: {flag}"


def test_entry_candidate_queries_no_account_tables() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8").lower()
    # Collect table names following FROM/JOIN.
    import re

    tables = set(re.findall(r"(?:from|join)\s+([a-z_][a-z0-9_]*)", source))
    for table in tables:
        for token in FORBIDDEN_TABLE_SUBSTRINGS:
            assert token not in table, f"entry-candidate queries account/private table: {table}"


def test_entry_candidate_declares_market_only_safety_markers() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "account_awareness=0" in source
    assert "broker_private_calls=0" in source
    assert "market-only" in source


def main() -> None:
    for test in (
        test_entry_candidate_import_closure_is_account_agnostic,
        test_entry_candidate_cli_has_no_account_or_profile_args,
        test_entry_candidate_queries_no_account_tables,
        test_entry_candidate_declares_market_only_safety_markers,
    ):
        test()
    print("ok")


if __name__ == "__main__":
    main()
