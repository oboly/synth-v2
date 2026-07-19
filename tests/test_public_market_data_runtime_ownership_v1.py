from __future__ import annotations

import ast
from pathlib import Path


ODROID_SCRIPTS = tuple(sorted(Path("scripts/odroid").glob("*.sh")))
PRICE_WRAPPER = Path("scripts/run_market_price_snapshot_once.sh")
CANDLE_WRAPPER = Path("scripts/run_market_candle_freshness_once.sh")
CHAIN_WRAPPER = Path("scripts/run_chain_4h.sh")
ORCHESTRATOR = Path("scripts/odroid/run_linked_profile_runtime_orchestrator_once.sh")


def _executable_text(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_no_odroid_script_can_invoke_a_public_market_data_writer() -> None:
    forbidden = (
        "src.market_data.run_market_price_snapshot_v1",
        "src.etl.bitvavo.run_candles_etl",
        "scripts/run_chain_4h.sh",
        "run_native_short_scope_status_chain_once.sh",
        "src.market_data.run_native_short_scope_status_chain_v1",
        "src.market_data.run_native_short_map_materializer_v1",
        "scripts/run_market_rotation_pressure_once.sh",
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


def test_devlap_public_price_writer_has_one_owner_and_one_lock() -> None:
    wrapper = PRICE_WRAPPER.read_text(encoding="utf-8")
    service = Path("deploy/systemd/synth-market-price-snapshot-writer.service").read_text(encoding="utf-8")
    timer = Path("deploy/systemd/synth-market-price-snapshot-writer.timer").read_text(encoding="utf-8")
    assert wrapper.count("flock -n 9") == 1
    assert 'OWNER="devlap-public-market-data"' in wrapper
    assert wrapper.count("src.market_data.run_market_price_snapshot_v1") == 1
    assert wrapper.count("--write-db") == 1
    assert service.count("scripts/run_market_price_snapshot_once.sh") == 1
    assert timer.count("Unit=synth-market-price-snapshot-writer.service") == 1
    assert "Requires=synth-market-price-snapshot-writer.service" not in timer


def test_devlap_candle_writer_has_one_owner_and_one_lock() -> None:
    wrapper = CANDLE_WRAPPER.read_text(encoding="utf-8")
    service = Path("deploy/systemd/synth-market-candle-freshness-writer.service").read_text(encoding="utf-8")
    timer = Path("deploy/systemd/synth-market-candle-freshness-writer.timer").read_text(encoding="utf-8")
    assert wrapper.count("flock -n 9") == 1
    assert 'OWNER="devlap-public-market-data"' in wrapper
    assert wrapper.count("src.etl.bitvavo.run_candles_etl") == 1
    for interval in ('run_or_fail "15m"', 'run_or_fail "1h"', 'run_or_fail "4h"', 'run_or_fail "1d"', 'run_or_fail "1w"'):
        assert interval in wrapper
    assert service.count("scripts/run_market_candle_freshness_once.sh") == 1
    assert timer.count("Unit=synth-market-candle-freshness-writer.service") == 1
    assert "Requires=synth-market-candle-freshness-writer.service" not in timer
    chain = CHAIN_WRAPPER.read_text(encoding="utf-8")
    assert "src.etl.bitvavo.run_candles_etl" not in chain
    assert "src.operations.run_persisted_market_candle_freshness_v1" in chain


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


def test_4h_owner_graph_has_no_reporting_or_remote_transport() -> None:
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
    ):
        assert forbidden not in combined


def test_devlap_writer_contracts_have_no_cross_host_or_account_dependency() -> None:
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


def test_account_snapshot_persistence_remains_separate_and_present() -> None:
    linked_account = Path("scripts/odroid/run_account_wallet_refresh_once.sh").read_text(encoding="utf-8")
    mvp_account = Path("scripts/odroid/run_mvp_account_refresh_once.sh").read_text(encoding="utf-8")
    assert "src.account.run_account_wallet_refresh_v1" in linked_account
    assert "--write-db" in linked_account
    assert "run_broker_balance_snapshot_writer_v1" in mvp_account
    assert "run_broker_account_position_snapshot_writer_v1" in mvp_account
