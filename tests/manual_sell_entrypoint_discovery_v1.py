"""AST discovery for production-callable SELL planning/execution surfaces."""
from __future__ import annotations

import ast
from pathlib import Path


DISCOVERY_ROOTS = (
    "src/decision_gate",
    "src/execution",
    "src/execution_ladder",
    "src/execution_planner",
    "src/executor",
    "src/manual_execution",
    "src/orchestration",
    "src/policy",
    "scripts",
)

SELL_LITERALS = {
    "SELL",
    "sell",
    "EXIT_PASSIVE_LIMIT",
    "EXIT_LADDER",
    "PASSIVE_EXIT",
    "PASSIVE_EXIT_LADDER",
    "CLOSE_POSITION_MARKET_PAPER",
}

SELL_NAME_TOKENS = ("sell", "exit")
ENTRYPOINT_PREFIXES = (
    "build",
    "create",
    "decide",
    "execute",
    "insert",
    "main",
    "parse",
    "place",
    "preview",
    "process",
    "resolve",
    "round",
    "run",
    "update",
)

DISCOVERY_PATH_MARKERS = (
    "manual_execution",
    "execution_planner",
    "execution_ladder",
    "limit_sell",
    "executor",
    "exit_policy",
    "run_paper_cycle",
    "run_live_paper",
    "run_sell_only",
    "execution/worker.py",
    "run_paper_execution_runner",
)

DISCOVERY_PATH_EXCLUSIONS = {
    "src/execution_planner/planner.py",
    "src/execution_planner/run_execution_planner_skeleton.py",
}

PLANNER_OR_PERSISTENCE_SINKS = {
    "_build_buy_execution_plan_preview",
    "_build_ladder_legs",
    "_build_single_leg",
    "_insert_execution_plan",
    "_validate_paper_plan",
    "build_execution_plan",
    "build_execution_plan_preview",
    "build_exit_plan_from_position",
    "build_limit_sell_ladder_orders",
    "build_manual_sell_execution_plan_preview",
    "create_exit_plan_without_reservation",
    "create_plan_with_reservation",
    "create_plan_without_reservation",
    "execute_plan_paper",
    "insert_event",
    "insert_intent",
    "insert_plan",
    "place_limit_sell_ladder_orders",
    "preview_limit_sell_ladder_orders",
    "resolve_ladder_preview",
    "round_ladder_preview",
    "run_exit_policy_v1",
    "update_plan",
    "update_plan_state",
}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _function_body_without_docstring(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.stmt]:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _is_sell_capable_candidate(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    if node.name in PLANNER_OR_PERSISTENCE_SINKS:
        return True
    if node.name == "evaluate_manual_execution_request":
        return True
    entrypoint_shaped = node.name.lstrip("_").startswith(ENTRYPOINT_PREFIXES)
    if entrypoint_shaped and any(
        token in node.name.lower() for token in SELL_NAME_TOKENS
    ):
        return True

    body = _function_body_without_docstring(node)
    for statement in body:
        for descendant in ast.walk(statement):
            if (
                isinstance(descendant, ast.Constant)
                and isinstance(descendant.value, str)
                and descendant.value in SELL_LITERALS
            ):
                return entrypoint_shaped
            if isinstance(descendant, ast.Call):
                call_name = _call_name(descendant)
                if call_name in PLANNER_OR_PERSISTENCE_SINKS:
                    return entrypoint_shaped
    return False


def _module_name(repo_root: Path, path: Path) -> str:
    return ".".join(path.relative_to(repo_root).with_suffix("").parts)


def discover_sell_entrypoints(
    repo_root: Path,
    *,
    roots: tuple[str, ...] = DISCOVERY_ROOTS,
) -> set[str]:
    discovered: set[str] = set()
    for relative_root in roots:
        root = repo_root / relative_root
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in files:
            if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
                continue
            relative_path = path.relative_to(repo_root).as_posix()
            if not any(marker in relative_path for marker in DISCOVERY_PATH_MARKERS):
                continue
            if relative_path in DISCOVERY_PATH_EXCLUSIONS:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            module_name = _module_name(repo_root, path)
            class_stack: list[str] = []

            top_level = [
                statement
                for statement in tree.body
                if not isinstance(
                    statement,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
            ]
            if any(
                isinstance(descendant, ast.Call)
                and _call_name(descendant) in PLANNER_OR_PERSISTENCE_SINKS
                for statement in top_level
                for descendant in ast.walk(statement)
            ):
                discovered.add(f"{module_name}.<module>")

            class Visitor(ast.NodeVisitor):
                def visit_ClassDef(self, class_node: ast.ClassDef) -> None:
                    class_stack.append(class_node.name)
                    self.generic_visit(class_node)
                    class_stack.pop()

                def visit_FunctionDef(self, function_node: ast.FunctionDef) -> None:
                    if _is_sell_capable_candidate(function_node):
                        owner = ".".join(class_stack)
                        prefix = f"{module_name}.{owner}" if owner else module_name
                        discovered.add(f"{prefix}.{function_node.name}")
                    self.generic_visit(function_node)

                def visit_AsyncFunctionDef(
                    self,
                    function_node: ast.AsyncFunctionDef,
                ) -> None:
                    if _is_sell_capable_candidate(function_node):
                        owner = ".".join(class_stack)
                        prefix = f"{module_name}.{owner}" if owner else module_name
                        discovered.add(f"{prefix}.{function_node.name}")
                    self.generic_visit(function_node)

            Visitor().visit(tree)
    return discovered


def unclassified_sell_entrypoints(
    discovered: set[str],
    classifications: dict[str, str],
) -> set[str]:
    return discovered - set(classifications)
