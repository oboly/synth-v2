"""
Tests for src/research/replay_parameter_study_harness_v1.py and its CLI
wrapper src/research/run_replay_parameter_study_harness_v1.py.

Pure Python — no DB, no broker, no network. Covers the Issue #205
acceptance criteria directly:
- determinism (identical inputs -> identical canonical output)
- leakage (future data must not affect the decision function)
- missing-data fail-closed / explicit-classification behavior
- unsupported-parameter fail-closed behavior
- immutable, create-new-only artifact writing
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.research.replay_parameter_study_harness_v1 import (
    MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE,
    MISSING_DATA_POLICY_FAIL_CLOSED,
    QUALITY_AVAILABLE,
    QUALITY_MISSING,
    QUALITY_UNKNOWN,
    ArtifactConflictError,
    Dataset,
    EvaluationResult,
    MissingDataError,
    NonCanonicalValueError,
    ParameterDimension,
    ParameterGrid,
    ParameterSet,
    ParameterStudyDefinition,
    PointInTimeView,
    ReplayCutoff,
    ReplayHarnessError,
    ReplayRecord,
    UniverseSpec,
    UnsupportedParameterError,
    apply_parameter_overlay,
    build_point_in_time_view,
    canonical_json,
    classify_missing_data,
    content_hash,
    run_parameter_study,
    write_result_artifact,
)
from src.research.run_replay_parameter_study_harness_v1 import (
    demo_field_threshold_decision,
    demo_field_threshold_evaluation,
)


UTC = timezone.utc
T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _dataset(records: tuple[ReplayRecord, ...]) -> Dataset:
    return Dataset(
        dataset_id="unit_test_dataset",
        schema_version="v1",
        source_refs=("unit-test",),
        start_ts_utc=T0,
        end_ts_utc=T0 + timedelta(days=30),
        records=records,
    )


def _universe(symbols: tuple[str, ...] = ("BTC", "ETH", "XRP")) -> UniverseSpec:
    return UniverseSpec(universe_id="unit_test_universe", version="v1", symbols=symbols)


def _study(
    *,
    values=(1.0, 5.0, 20.0),
    missing_data_policy: str = MISSING_DATA_POLICY_FAIL_CLOSED,
) -> ParameterStudyDefinition:
    grid = ParameterGrid(
        dimensions=(
            ParameterDimension(name="field_name", values=("value",)),
            ParameterDimension(name="threshold", values=tuple(values)),
        )
    )
    return ParameterStudyDefinition(
        study_id="unit_test_study",
        study_version="v1",
        feature_versions={"toy_field": "v1"},
        parameter_grid=grid,
        missing_data_policy=missing_data_policy,
        decision_fn_id="demo_field_threshold_decision",
        evaluation_fn_id="demo_field_threshold_evaluation",
    )


# --------------------------------------------------------------------------
# Canonical serialization / content hashing
# --------------------------------------------------------------------------


class TestCanonicalSerialization:
    def test_dict_key_order_is_irrelevant(self) -> None:
        a = canonical_json({"b": 1, "a": 2})
        b = canonical_json({"a": 2, "b": 1})
        assert a == b

    def test_no_insignificant_whitespace(self) -> None:
        assert canonical_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(NonCanonicalValueError):
            canonical_json({"ts": datetime(2026, 1, 1, 0, 0, 0)})

    def test_aware_datetime_normalized_to_utc(self) -> None:
        aware = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert "2026-01-01T00:00:00+00:00" in canonical_json({"ts": aware})

    def test_nan_rejected(self) -> None:
        with pytest.raises(NonCanonicalValueError):
            canonical_json({"x": float("nan")})

    def test_infinity_rejected(self) -> None:
        with pytest.raises(NonCanonicalValueError):
            canonical_json({"x": float("inf")})

    def test_opaque_object_rejected(self) -> None:
        class Opaque:
            pass

        with pytest.raises(NonCanonicalValueError):
            canonical_json({"x": Opaque()})

    def test_content_hash_stable_for_identical_input(self) -> None:
        obj = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
        assert content_hash(obj) == content_hash(dict(obj))

    def test_content_hash_changes_with_content(self) -> None:
        assert content_hash({"a": 1}) != content_hash({"a": 2})


# --------------------------------------------------------------------------
# Dataset / universe bounds
# --------------------------------------------------------------------------


class TestDatasetBounds:
    def test_record_outside_half_open_bounds_rejected(self) -> None:
        rec = ReplayRecord(symbol="BTC", as_of_ts_utc=T0 + timedelta(days=31), quality=QUALITY_AVAILABLE)
        with pytest.raises(ReplayHarnessError):
            _dataset((rec,))

    def test_record_at_end_bound_rejected_half_open(self) -> None:
        rec = ReplayRecord(symbol="BTC", as_of_ts_utc=T0 + timedelta(days=30), quality=QUALITY_AVAILABLE)
        with pytest.raises(ReplayHarnessError):
            _dataset((rec,))

    def test_record_at_start_bound_accepted(self) -> None:
        rec = ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE)
        dataset = _dataset((rec,))
        assert dataset.records == (rec,)

    def test_naive_dataset_bound_rejected(self) -> None:
        with pytest.raises(ReplayHarnessError):
            Dataset(
                dataset_id="x",
                schema_version="v1",
                source_refs=(),
                start_ts_utc=datetime(2026, 1, 1),
                end_ts_utc=T0 + timedelta(days=1),
                records=(),
            )

    def test_duplicate_universe_symbols_rejected(self) -> None:
        with pytest.raises(ReplayHarnessError):
            UniverseSpec(universe_id="u", version="v1", symbols=("BTC", "BTC"))


# --------------------------------------------------------------------------
# Parameter grid: deterministic enumeration + fail-closed unsupported params
# --------------------------------------------------------------------------


class TestParameterGrid:
    def test_enumerate_is_deterministic_across_calls(self) -> None:
        grid = ParameterGrid(
            dimensions=(
                ParameterDimension(name="a", values=(1, 2)),
                ParameterDimension(name="b", values=("x", "y")),
            )
        )
        first = grid.enumerate()
        second = grid.enumerate()
        assert first == second
        assert [ps.candidate_id for ps in first] == [ps.candidate_id for ps in second]

    def test_enumerate_cartesian_order(self) -> None:
        grid = ParameterGrid(
            dimensions=(
                ParameterDimension(name="a", values=(1, 2)),
                ParameterDimension(name="b", values=("x", "y")),
            )
        )
        combos = [dict(ps.values) for ps in grid.enumerate()]
        assert combos == [
            {"a": 1, "b": "x"},
            {"a": 1, "b": "y"},
            {"a": 2, "b": "x"},
            {"a": 2, "b": "y"},
        ]

    def test_forbidden_safety_parameter_name_rejected(self) -> None:
        with pytest.raises(UnsupportedParameterError):
            ParameterGrid(dimensions=(ParameterDimension(name="account_id", values=(1,)),))

    def test_custom_forbidden_name_rejected(self) -> None:
        with pytest.raises(UnsupportedParameterError):
            ParameterGrid(
                dimensions=(ParameterDimension(name="lookback", values=(1,)),),
                forbidden_parameter_names=frozenset({"lookback"}),
            )

    def test_duplicate_dimension_names_rejected(self) -> None:
        with pytest.raises(UnsupportedParameterError):
            ParameterGrid(
                dimensions=(
                    ParameterDimension(name="a", values=(1,)),
                    ParameterDimension(name="a", values=(2,)),
                )
            )

    def test_unsupported_value_type_rejected(self) -> None:
        with pytest.raises(UnsupportedParameterError):
            ParameterDimension(name="a", values=({"nested": True},))  # type: ignore[arg-type]

    def test_non_finite_float_value_rejected(self) -> None:
        with pytest.raises(UnsupportedParameterError):
            ParameterDimension(name="a", values=(float("nan"),))

    def test_grid_digest_deterministic(self) -> None:
        grid1 = ParameterGrid(dimensions=(ParameterDimension(name="a", values=(1, 2)),))
        grid2 = ParameterGrid(dimensions=(ParameterDimension(name="a", values=(1, 2)),))
        assert grid1.digest == grid2.digest

    def test_grid_digest_changes_with_values(self) -> None:
        grid1 = ParameterGrid(dimensions=(ParameterDimension(name="a", values=(1, 2)),))
        grid2 = ParameterGrid(dimensions=(ParameterDimension(name="a", values=(1, 3)),))
        assert grid1.digest != grid2.digest


class TestApplyParameterOverlay:
    def test_unsupported_override_key_rejected(self) -> None:
        with pytest.raises(UnsupportedParameterError):
            apply_parameter_overlay(
                {"threshold": 1.0},
                {"unknown_param": 5.0},
                allowed_parameter_names=frozenset({"threshold"}),
            )

    def test_valid_overlay_merges_without_mutating_base(self) -> None:
        base = {"threshold": 1.0, "field_name": "value"}
        merged = apply_parameter_overlay(
            base, {"threshold": 9.0}, allowed_parameter_names=frozenset({"threshold", "field_name"})
        )
        assert merged == {"threshold": 9.0, "field_name": "value"}
        assert base == {"threshold": 1.0, "field_name": "value"}


# --------------------------------------------------------------------------
# Missing-data classification: explicit, never a silent skip
# --------------------------------------------------------------------------


class TestMissingData:
    def test_absent_symbol_classified_missing(self) -> None:
        dataset = _dataset(())
        universe = _universe(("BTC",))
        view = build_point_in_time_view(dataset, ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)))
        report = classify_missing_data(view, universe, policy=MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE)
        assert report.missing_symbols == ("BTC",)
        assert report.available_symbols == ()

    def test_unknown_quality_classified_unknown(self) -> None:
        rec = ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_UNKNOWN, payload={"value": 1.0})
        dataset = _dataset((rec,))
        universe = _universe(("BTC",))
        view = build_point_in_time_view(dataset, ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)))
        report = classify_missing_data(view, universe, policy=MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE)
        assert report.unknown_symbols == ("BTC",)

    def test_explicit_missing_quality_classified_missing(self) -> None:
        rec = ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_MISSING, payload={})
        dataset = _dataset((rec,))
        universe = _universe(("BTC",))
        view = build_point_in_time_view(dataset, ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)))
        report = classify_missing_data(view, universe, policy=MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE)
        assert report.missing_symbols == ("BTC",)

    def test_run_fails_closed_when_required_symbol_missing(self) -> None:
        rec = ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 10.0})
        dataset = _dataset((rec,))  # ETH, XRP absent from default 3-symbol universe
        study = _study(missing_data_policy=MISSING_DATA_POLICY_FAIL_CLOSED)

        with pytest.raises(MissingDataError):
            run_parameter_study(
                study=study,
                dataset=dataset,
                universe=_universe(),
                cutoff=ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)),
                decision_fn=demo_field_threshold_decision,
                evaluation_fn=demo_field_threshold_evaluation,
                code_sha="test-sha",
            )

    def test_run_classifies_and_continues_when_configured(self) -> None:
        rec = ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 10.0})
        dataset = _dataset((rec,))
        study = _study(missing_data_policy=MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE)

        result = run_parameter_study(
            study=study,
            dataset=dataset,
            universe=_universe(),
            cutoff=ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)),
            decision_fn=demo_field_threshold_decision,
            evaluation_fn=demo_field_threshold_evaluation,
            code_sha="test-sha",
        )

        # Explicit classification, not a silent skip: the run succeeds AND
        # the missing symbols are recorded in the result.
        assert set(result.missing_data_report.missing_symbols) == {"ETH", "XRP"}
        assert len(result.results) == 3  # one per threshold in the grid


# --------------------------------------------------------------------------
# Point-in-time leakage guard
# --------------------------------------------------------------------------


class TestLeakageGuard:
    def test_view_excludes_records_after_cutoff(self) -> None:
        early = ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 1.0})
        future = ReplayRecord(
            symbol="BTC", as_of_ts_utc=T0 + timedelta(days=5), quality=QUALITY_AVAILABLE, payload={"value": 999.0}
        )
        dataset = _dataset((early, future))
        cutoff = ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1))
        view = build_point_in_time_view(dataset, cutoff)
        assert view.latest("BTC") == early
        assert future not in view.history("BTC")

    def test_view_includes_record_exactly_at_cutoff(self) -> None:
        rec = ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 1.0})
        dataset = _dataset((rec,))
        view = build_point_in_time_view(dataset, ReplayCutoff(as_of_ts_utc=T0))
        assert view.latest("BTC") == rec

    def test_future_record_does_not_change_decision_output(self) -> None:
        """A future record that WOULD change the decision if leaked (very
        high value, well above every threshold) must not affect the
        decision function's output, because it is outside the
        point-in-time view."""
        early = ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 1.0})
        universe = _universe(("BTC",))
        cutoff = ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1))

        dataset_without_future = _dataset((early,))
        view_without_future = build_point_in_time_view(dataset_without_future, cutoff)

        leaking_future = ReplayRecord(
            symbol="BTC", as_of_ts_utc=T0 + timedelta(days=5), quality=QUALITY_AVAILABLE, payload={"value": 999.0}
        )
        dataset_with_future = _dataset((early, leaking_future))
        view_with_future = build_point_in_time_view(dataset_with_future, cutoff)

        parameter_set = ParameterSet(candidate_id="P00000-test", values={"field_name": "value", "threshold": 500.0})
        missing_report = classify_missing_data(view_with_future, universe, policy=MISSING_DATA_POLICY_FAIL_CLOSED)

        out_without_future = demo_field_threshold_decision(parameter_set, view_without_future, cutoff, missing_report)
        out_with_future = demo_field_threshold_decision(parameter_set, view_with_future, cutoff, missing_report)

        # threshold=500 is above the pre-cutoff value (1.0) but below the
        # leaking future value (999.0). If future data leaked, BTC would be
        # selected. It must not be.
        assert out_without_future == out_with_future == {"selected_symbols": ()}

    def test_evaluation_fn_may_use_future_data(self) -> None:
        """Contrast case: the evaluation function is explicitly allowed to
        see future data (that is its job), unlike the decision function."""
        early = ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 10.0})
        future = ReplayRecord(
            symbol="BTC", as_of_ts_utc=T0 + timedelta(days=5), quality=QUALITY_AVAILABLE, payload={"value": 10.0}
        )
        dataset = _dataset((early, future))
        cutoff = ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1))
        parameter_set = ParameterSet(candidate_id="P00000-test", values={"field_name": "value", "threshold": 1.0})
        decision_output = {"selected_symbols": ("BTC",)}

        eval_result = demo_field_threshold_evaluation(parameter_set, decision_output, dataset, cutoff)
        assert eval_result.metrics["observed_forward_count"] == 1


# --------------------------------------------------------------------------
# End-to-end determinism
# --------------------------------------------------------------------------


class TestDeterminism:
    def _run(self) -> object:
        records = (
            ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 10.0}),
            ReplayRecord(
                symbol="BTC", as_of_ts_utc=T0 + timedelta(days=5), quality=QUALITY_AVAILABLE, payload={"value": 30.0}
            ),
            ReplayRecord(symbol="ETH", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 5.0}),
            ReplayRecord(symbol="XRP", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 1.0}),
        )
        dataset = _dataset(records)
        study = _study()
        return run_parameter_study(
            study=study,
            dataset=dataset,
            universe=_universe(),
            cutoff=ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)),
            decision_fn=demo_field_threshold_decision,
            evaluation_fn=demo_field_threshold_evaluation,
            code_sha="fixed-test-sha",
        )

    def test_identical_inputs_produce_identical_canonical_output(self) -> None:
        first = self._run()
        second = self._run()
        assert first.result_content_hash == second.result_content_hash
        assert canonical_json(first.canonical_content()) == canonical_json(second.canonical_content())

    def test_result_binds_all_required_provenance_fields(self) -> None:
        result = self._run()
        assert result.dataset_identity
        assert result.cutoff_ts_utc == T0 + timedelta(days=1)
        assert result.universe_identity
        assert result.feature_versions == {"toy_field": "v1"}
        assert result.parameter_grid_digest
        assert result.code_sha == "fixed-test-sha"
        assert len(result.results) == 3

    def test_evaluation_fn_wrong_return_type_rejected(self) -> None:
        dataset = _dataset((ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 10.0}),))
        study = _study(missing_data_policy=MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE)

        def bad_evaluation_fn(parameter_set, decision_output, dataset_, cutoff):
            return {"not": "an EvaluationResult"}

        with pytest.raises(ReplayHarnessError):
            run_parameter_study(
                study=study,
                dataset=dataset,
                universe=_universe(),
                cutoff=ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)),
                decision_fn=demo_field_threshold_decision,
                evaluation_fn=bad_evaluation_fn,
                code_sha="test-sha",
            )

    def test_evaluation_fn_mismatched_candidate_id_rejected(self) -> None:
        dataset = _dataset((ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 10.0}),))
        study = _study(missing_data_policy=MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE)

        def bad_evaluation_fn(parameter_set, decision_output, dataset_, cutoff):
            return EvaluationResult(
                candidate_id="WRONG-ID", parameter_values=parameter_set.values, sample_count=0, metrics={}
            )

        with pytest.raises(ReplayHarnessError):
            run_parameter_study(
                study=study,
                dataset=dataset,
                universe=_universe(),
                cutoff=ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)),
                decision_fn=demo_field_threshold_decision,
                evaluation_fn=bad_evaluation_fn,
                code_sha="test-sha",
            )


# --------------------------------------------------------------------------
# Immutable artifact writer
# --------------------------------------------------------------------------


class TestArtifactWriter:
    def test_write_then_conflict_on_identical_run_id(self, tmp_path) -> None:
        records = (ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 10.0}),)
        dataset = _dataset(records)
        study = _study(missing_data_policy=MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE)
        result = run_parameter_study(
            study=study,
            dataset=dataset,
            universe=_universe(),
            cutoff=ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)),
            decision_fn=demo_field_threshold_decision,
            evaluation_fn=demo_field_threshold_evaluation,
            code_sha="test-sha",
        )

        path = write_result_artifact(result, tmp_path)
        assert path.exists()

        with pytest.raises(ArtifactConflictError):
            write_result_artifact(result, tmp_path)

    def test_artifact_content_matches_result_json(self, tmp_path) -> None:
        records = (ReplayRecord(symbol="BTC", as_of_ts_utc=T0, quality=QUALITY_AVAILABLE, payload={"value": 10.0}),)
        dataset = _dataset(records)
        study = _study(missing_data_policy=MISSING_DATA_POLICY_CLASSIFY_AND_CONTINUE)
        result = run_parameter_study(
            study=study,
            dataset=dataset,
            universe=_universe(),
            cutoff=ReplayCutoff(as_of_ts_utc=T0 + timedelta(days=1)),
            decision_fn=demo_field_threshold_decision,
            evaluation_fn=demo_field_threshold_evaluation,
            code_sha="test-sha",
        )
        path = write_result_artifact(result, tmp_path)
        assert path.read_text(encoding="utf-8") == result.to_json()
