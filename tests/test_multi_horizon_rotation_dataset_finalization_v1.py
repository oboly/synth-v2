from pathlib import Path
from unittest.mock import patch

from src.research.run_multi_horizon_rotation_dataset_builder_v1 import finalize_artifact_bundle


def test_finalization_checkpoint_failure_rolls_bundle_back_to_partial(tmp_path: Path) -> None:
    partial_path = tmp_path / ".validation_rows_v1.jsonl.partial"
    artifact_path = tmp_path / "validation_rows_v1.jsonl"
    summary_path = tmp_path / "validation_summary_v1.json"
    payload = b'{"row":1}\n{"row":2}\n'
    partial_path.write_bytes(payload)

    def fail_checkpoint(final_bytes: int) -> None:
        assert final_bytes == len(payload)
        raise OSError("simulated checkpoint durability failure")

    try:
        finalize_artifact_bundle(
            partial_path=partial_path,
            artifact_path=artifact_path,
            summary_path=summary_path,
            summary={"row_count": 2},
            persist_finished_checkpoint=fail_checkpoint,
        )
    except OSError as exc:
        assert "checkpoint durability failure" in str(exc)
    else:
        raise AssertionError("finalization must fail when FINISHED checkpoint persistence fails")

    assert partial_path.read_bytes() == payload
    assert not artifact_path.exists()
    assert not summary_path.exists()


def test_finalization_summary_failure_rolls_data_back_before_finished_checkpoint(tmp_path: Path) -> None:
    partial_path = tmp_path / ".discovery_rows_v1.jsonl.partial"
    artifact_path = tmp_path / "discovery_rows_v1.jsonl"
    summary_path = tmp_path / "discovery_summary_v1.json"
    payload = b'{"row":1}\n'
    partial_path.write_bytes(payload)
    checkpoint_calls: list[int] = []

    def persist_checkpoint(final_bytes: int) -> None:
        checkpoint_calls.append(final_bytes)

    with patch(
        "src.research.run_multi_horizon_rotation_dataset_builder_v1.write_json_atomic",
        side_effect=OSError("simulated summary durability failure"),
    ):
        try:
            finalize_artifact_bundle(
                partial_path=partial_path,
                artifact_path=artifact_path,
                summary_path=summary_path,
                summary={"row_count": 1},
                persist_finished_checkpoint=persist_checkpoint,
            )
        except OSError as exc:
            assert "summary durability failure" in str(exc)
        else:
            raise AssertionError("finalization must fail when summary persistence fails")

    assert checkpoint_calls == []
    assert partial_path.read_bytes() == payload
    assert not artifact_path.exists()
    assert not summary_path.exists()
