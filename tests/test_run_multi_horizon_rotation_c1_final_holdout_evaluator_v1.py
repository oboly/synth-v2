import json
import signal
from datetime import UTC, datetime, timedelta

import pytest

from src.research.multi_horizon_rotation_validation_streaming_v1 import StreamingValidationAccumulator
from src.research.multi_horizon_rotation_validation_v1 import ValidationRow
import src.research.run_multi_horizon_rotation_c1_final_holdout_evaluator_v1 as runner
from src.research.run_multi_horizon_rotation_c1_final_holdout_evaluator_v1 import INPUT_BASENAME, evaluate_streaming, main


def row(i, candidate_id="C1"):
    return {"venue":"bitvavo", "asset_id":1, "asof_ts":(datetime(2026,8,1,tzinfo=UTC)+timedelta(minutes=15*i)).isoformat().replace("+00:00","Z"), "candidate_id":candidate_id, "candidate_score":float((-1) ** i), "b0_score":float((-1) ** i), "b0_pressure_state":"ROTATION_IN", "b1_return":float((-1) ** (i + 1)), "forward_15m":.01, "forward_1h":.01, "forward_4h":.01, "forward_24h":.01}


def write(path, rows):
    path.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")


def test_c1_only_enforcement_and_frozen_metrics(tmp_path):
    path = tmp_path / INPUT_BASENAME
    rows = [row(i) for i in range(40)]
    write(path, rows)
    summary, count = evaluate_streaming(path)
    assert count == 40 and summary["candidate_id"] == "C1"
    assert set(summary["metrics"]["forward_ic"]) == {"15m", "1h", "4h", "24h"}
    frozen = StreamingValidationAccumulator()
    for i in range(40):
        frozen.add(ValidationRow("bitvavo", 1, datetime(2026,8,1,tzinfo=UTC)+timedelta(minutes=15*i), "C1", float((-1)**i), float((-1)**i), "ROTATION_IN", float((-1)**(i+1)), .01, .01, .01, .01))
    expected = frozen.finish()
    assert summary["metrics"]["sample_count"] == expected["candidate_summaries"]["C1"]["sample_count"]
    assert summary["metrics"]["forward_ic"] == {key: value.__dict__ for key, value in expected["candidate_summaries"]["C1"]["forward_ic"].items()}
    assert summary["lead_lag_vs_b1"] == expected["lead_lag_vs_b1"]["C1"]
    bad = row(0, "C2"); bad["forward_15m"] = "invalid"
    write(path, [bad])
    with pytest.raises(ValueError, match="candidate_id must be C1"):
        evaluate_streaming(path)


def test_bounded_streaming_state(tmp_path):
    path = tmp_path / INPUT_BASENAME
    write(path, [row(i) for i in range(500)])
    summary, count = evaluate_streaming(path)
    assert count == 500 and summary["metrics"]["persistence"]["run_count"] == 500
    accumulator = StreamingValidationAccumulator()
    for i in range(500):
        accumulator.add(ValidationRow("bitvavo", 1, datetime(2026,8,1,tzinfo=UTC)+timedelta(minutes=15*i), "C1", float((-1)**i), 1.0, "ROTATION_IN", 1.0, .01, .01, .01, .01))
    accumulator.finish()
    assert len(accumulator.temporal) == 1


def test_runner_safety_output(tmp_path):
    path = tmp_path / INPUT_BASENAME; output = tmp_path / "out.json"
    write(path, [row(i) for i in range(8)])
    assert main(["--input-jsonl", str(path), "--output-json", str(output)]) == 0
    assert json.loads(output.read_text())["safety"]["database_reads"] == 0
    assert json.loads(output.read_text())["summary"]["candidate_id"] == "C1"


@pytest.mark.parametrize(("signum", "expected_exit"), [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_runner_handles_interrupt_without_completed_output(tmp_path, capsys, monkeypatch, signum, expected_exit):
    path = tmp_path / INPUT_BASENAME
    output = tmp_path / "out.json"
    write(path, [row(0)])
    previous = signal.getsignal(signum)
    monkeypatch.setattr(runner, "evaluate_streaming", lambda _path: signal.raise_signal(signum))
    assert main(["--input-jsonl", str(path), "--output-json", str(output)]) == expected_exit
    stdout = capsys.readouterr().out
    terminal = [line for line in stdout.splitlines() if line.startswith("INTERRUPTED ")]
    assert len(terminal) == 1
    assert signal.Signals(signum).name in terminal[0]
    assert "FINISHED runner=" not in stdout
    assert not output.exists()
    assert not output.with_suffix(output.suffix + ".partial").exists()
    assert signal.getsignal(signum) is previous
