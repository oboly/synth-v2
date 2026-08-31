from pathlib import Path

from src.research.run_multi_horizon_rotation_dataset_builder_v1 import finalize_artifact_with_checkpoint


def test_finalization_checkpoint_failure_rolls_final_artifact_back_to_partial(tmp_path: Path) -> None:
    partial_path = tmp_path / ".validation_rows_v1.jsonl.partial"
    artifact_path = tmp_path / "validation_rows_v1.jsonl"
    payload = b'{"row":1}\n{"row":2}\n'
    partial_path.write_bytes(payload)

    def fail_checkpoint(final_bytes: int) -> None:
        assert final_bytes == len(payload)
        raise OSError("simulated checkpoint durability failure")

    try:
        finalize_artifact_with_checkpoint(
            partial_path=partial_path,
            artifact_path=artifact_path,
            persist_finished_checkpoint=fail_checkpoint,
        )
    except OSError as exc:
        assert "checkpoint durability failure" in str(exc)
    else:
        raise AssertionError("finalization must fail when FINISHED checkpoint persistence fails")

    assert partial_path.read_bytes() == payload
    assert not artifact_path.exists()
