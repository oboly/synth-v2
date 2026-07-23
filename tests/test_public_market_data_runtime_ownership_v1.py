from __future__ import annotations

import ast
import re
from pathlib import Path


ODROID_SCRIPTS = tuple(sorted(Path("scripts/odroid").glob("*.sh")))
PRICE_WRAPPER = Path("scripts/run_market_price_snapshot_once.sh")
CANDLE_WRAPPER = Path("scripts/run_market_candle_freshness_once.sh")
CHAIN_WRAPPER = Path("scripts/run_chain_4h.sh")
ORCHESTRATOR = Path("scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh")
SYSTEMD_TREES = (Path("deploy/systemd"), Path("docs/ops/systemd"), Path("scripts/odroid/systemd"))


def _executable_text(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def _unit_value(path: Path, key: str) -> list[str]:
    values = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k == key:
            values.append(v)
    return values


def test_no_odroid_script_can_invoke_a_public_market_data_writer() -> None:
    forbidden = (
        "src.market_data.run_market_price_snapshot_v1",
        "src.etl.bitvavo.run_candles_etl",
        "scripts/run_market_price_snapshot_once.sh",
        "scripts/run_market_candle_freshness_once.sh",
        "scripts/run_chain_4h.sh",
        "scripts/run_native_short_scope_status_chain_once.sh",
        "src.market_data.run_native_short_scope_status_chain_v1",
        "src.market_data.run_native_short_fib_context_snapshot_v1",
        "scripts/run_market_rotation_pressure_once.sh",
        "src.research.run_market_rotation_history_v1",
        "src.research.run_market_rotation_pressure_v1",
    )
    for path in ODROID_SCRIPTS:
        executable = _executable_text(path)
        for token in forbidden:
            assert token not in executable, f"{path} invokes forbidden writer token {token}"


def test_linked_profile_orchestrator_is_validation_then_account_then_render() -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8")
    validation = source.index('run_persisted_market_price_validation')
    account = source.index('phase_start "refresh_account_snapshot"')
    render = source.index('phase_start "render_snapshot_dashboard"')
    profit = source.index('phase_start "profit_plan_render"')
    assert validation < account < render < profit
    assert "SYNTH_MARKET_PRICE_REFRESH_SCRIPT" not in source
    assert "run_account_wallet_refresh_once.sh" in source
    assert "run_account_profit_plan_snapshot_render_once.sh" in source


def test_public_price_writer_has_immutable_identity_guard_and_lock() -> None:
    wrapper = PRICE_WRAPPER.read_text(encoding="utf-8")
    service = Path("deploy/systemd/synth-market-price-snapshot-writer.service")
    timer = Path("deploy/systemd/synth-market-price-snapshot-writer.timer")
    service_text = service.read_text(encoding="utf-8")
    assert wrapper.count("flock -n 9") == 1
    assert 'OWNER="public-price-snapshot-writer"' in wrapper
    assert "SYNTH_MARKET_PRICE_WRITER_OWNER" not in wrapper
    assert wrapper.count("src.market_data.run_market_price_snapshot_v1") == 1
    assert wrapper.count("--write-db") == 1
    assert "ConditionHost=gurkdb" in service_text
    assert "verify_writer_capability_authorization_v1" in service_text
    assert "scripts/run_market_price_snapshot_once.sh" in service_text
    assert "Unit=synth-market-price-snapshot-writer.service" in timer.read_text(encoding="utf-8")


def test_candle_writer_has_immutable_identity_guard_and_lock() -> None:
    wrapper = CANDLE_WRAPPER.read_text(encoding="utf-8")
    service = Path("deploy/systemd/synth-market-candle-freshness-writer.service")
    timer = Path("deploy/systemd/synth-market-candle-freshness-writer.timer")
    service_text = service.read_text(encoding="utf-8")
    assert wrapper.count("flock -n 9") == 1
    assert 'OWNER="public-candle-freshness-writer"' in wrapper
    assert "SYNTH_MARKET_CANDLE_WRITER_OWNER" not in wrapper
    assert wrapper.count("src.etl.bitvavo.run_candles_etl") == 1
    for interval in ('run_or_fail "15m"', 'run_or_fail "1h"', 'run_or_fail "4h"', 'run_or_fail "1d"', 'run_or_fail "1w"'):
        assert interval in wrapper
    assert "ConditionHost=gurkdb" in service_text
    assert "verify_writer_capability_authorization_v1" in service_text
    assert "scripts/run_market_candle_freshness_once.sh" in service_text
    assert "Unit=synth-market-candle-freshness-writer.service" in timer.read_text(encoding="utf-8")


def test_4h_chain_consumes_both_persisted_public_feeds_without_writer_repair() -> None:
    chain = _executable_text(CHAIN_WRAPPER)
    price_validation = "src.operations.run_persisted_market_price_freshness_v1"
    candle_validation = "src.operations.run_persisted_market_candle_freshness_v1"
    native_short = "scripts/run_native_short_scope_status_chain_once.sh"
    assert chain.index(price_validation) < chain.index(candle_validation) < chain.index(native_short)
    for forbidden in (
        "src.market_data.run_market_price_snapshot_v1",
        "src.etl.bitvavo.run_candles_etl",
        "refresh_public_prices",
        "scripts/run_market_price_snapshot_once.sh",
        "scripts/run_market_candle_freshness_once.sh",
    ):
        assert forbidden not in chain


def test_4h_owner_graph_has_no_reporting_remote_or_account_paths() -> None:
    service = _executable_text(Path("deploy/systemd/synth-chain-4h.service"))
    chain = _executable_text(CHAIN_WRAPPER)
    combined = f"{service}\n{chain}".lower()
    for forbidden in (
        "src.reporting",
        "publish_paper_advice_dashboard_to_odroid",
        "synth_paper_advice_dashboard",
        "odroid",
        "ssh",
        "scp",
        "src.account",
        "decision_gate",
        "execution_planner",
        "src.executor",
        "src.broker",
    ):
        assert forbidden not in combined
    assert "verify_writer_capability_authorization_v1" in service
    assert "conditionhost=devlap" in service.lower()


def test_public_writer_contracts_have_no_cross_host_or_account_dependency() -> None:
    paths = (
        PRICE_WRAPPER,
        CANDLE_WRAPPER,
        Path("deploy/systemd/synth-market-price-snapshot-writer.service"),
        Path("deploy/systemd/synth-market-price-snapshot-writer.timer"),
        Path("deploy/systemd/synth-market-candle-freshness-writer.service"),
        Path("deploy/systemd/synth-market-candle-freshness-writer.timer"),
    )
    forbidden = ("ssh ", "scp ", "odroid", "src.account", "src.reporting", "decision_gate", "execution_planner", "src.executor")
    for path in paths:
        source = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in source, f"{path} contains forbidden dependency {token}"


def test_public_market_python_writers_have_no_forbidden_layer_imports() -> None:
    forbidden = ("src.account", "src.reporting", "src.decision_gate", "src.execution_planner", "src.executor", "src.broker")
    for path in (
        Path("src/market_data/run_market_price_snapshot_v1.py"),
        Path("src/etl/bitvavo/run_candles_etl.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any(name.startswith(forbidden) for name in imported), path


def test_odroid_candle_templates_are_retired_from_repository() -> None:
    assert not Path("scripts/odroid/systemd/synth-market-candle-freshness.service").exists()
    assert not Path("scripts/odroid/systemd/synth-market-candle-freshness.timer").exists()
    retired = Path("scripts/odroid/run_market_candle_freshness_once.sh").read_text(encoding="utf-8")
    assert "ODROID_PUBLIC_MARKET_WRITER_RETIRED" in retired
    assert "writer_invocations=0" in retired
    assert "scripts/run_market_candle_freshness_once.sh" not in retired


def test_duplicate_detection_scans_all_systemd_trees_by_writer_token() -> None:
    capability_tokens = {
        "public_price_snapshot": ("scripts/run_market_price_snapshot_once.sh",),
        "public_candle_freshness": ("scripts/run_market_candle_freshness_once.sh",),
        "market_rotation_pressure": ("scripts/run_market_rotation_pressure_once.sh", "run_market_rotation_history_v1", "run_market_rotation_pressure_v1"),
        "native_short_4h_chain": ("scripts/run_chain_4h.sh", "run_native_short_scope_status_chain_once.sh", "run_native_short_fib_context_snapshot_v1"),
    }
    hits = {capability: [] for capability in capability_tokens}
    for root in SYSTEMD_TREES:
        for unit in sorted(root.glob("*.service")):
            executable = _executable_text(unit)
            for capability, tokens in capability_tokens.items():
                if any(token in executable for token in tokens):
                    hits[capability].append(str(unit))
    assert hits["public_price_snapshot"] == ["deploy/systemd/synth-market-price-snapshot-writer.service"]
    assert hits["public_candle_freshness"] == ["deploy/systemd/synth-market-candle-freshness-writer.service"]
    assert hits["market_rotation_pressure"] == ["deploy/systemd/synth-market-rotation-pressure-writer.service"]
    assert hits["native_short_4h_chain"] == ["deploy/systemd/synth-chain-4h.service"]


def test_all_deploy_services_are_explicitly_host_bound_and_guarded() -> None:
    for service in Path("deploy/systemd").glob("*.service"):
        text = service.read_text(encoding="utf-8")
        if service.name.startswith("synth-market-") or service.name == "synth-chain-4h.service":
            expected_host = (
                "gurkdb"
                if service.name
                in {
                    "synth-market-price-snapshot-writer.service",
                    "synth-market-candle-freshness-writer.service",
                }
                else "devlap"
            )
            assert f"ConditionHost={expected_host}" in text
            assert "verify_writer_capability_authorization_v1" in text
            assert _unit_value(service, "User") == ["gurk"]
            assert _unit_value(service, "WorkingDirectory") == ["/home/gurk/projects/synth-v2"]


def test_concurrent_public_writer_capabilities_use_distinct_authorization_files() -> None:
    import json

    registry = json.loads(
        Path("deploy/ownership/writer_capability_ownership_v1.json").read_text(
            encoding="utf-8"
        )
    )
    paths = {
        cap["capability_id"]: cap["authorization_guard"]["authorization_file"]
        for cap in registry["capabilities"]
    }
    assert paths["public_price_snapshot"] != paths["public_candle_freshness"]


def test_account_snapshot_persistence_remains_separate_and_present() -> None:
    linked_account = Path("scripts/odroid/run_account_wallet_refresh_once.sh").read_text(encoding="utf-8")
    mvp_account = Path("scripts/odroid/run_mvp_account_refresh_once.sh").read_text(encoding="utf-8")
    assert "src.account.run_account_wallet_refresh_v1" in linked_account
    assert "--write-db" in linked_account
    assert "run_broker_balance_snapshot_writer_v1" in mvp_account
    assert "run_broker_account_position_snapshot_writer_v1" in mvp_account
