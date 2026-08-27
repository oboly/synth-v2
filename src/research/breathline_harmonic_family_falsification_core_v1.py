from __future__ import annotations

"""Corrected core facade for Issue #533 harmonic-family falsification v1.0.1.

The underlying v1.0.0 implementation is retained byte-for-byte in
``_breathline_harmonic_family_falsification_impl_v1`` for auditability. Before
any analysis call, this facade replaces only the preregistered Lane A phase-null
statistic with the v1.0.1 unit-circle-consistent implementation. All duration,
Lane B, split, baseline, provenance and safety logic remains unchanged.
"""

import random
from statistics import mean
from typing import Any

from src.research._breathline_harmonic_family_falsification_impl_v1 import *  # noqa: F401,F403
from src.research import _breathline_harmonic_family_falsification_impl_v1 as _impl
from src.research.breathline_harmonic_family_registry_v1 import (
    PHASE_MARKERS,
    RANDOM_SEED,
)


InputProvenanceError = _impl.InputProvenanceError


def circular_phase_distance(position: float, marker_ratio: float) -> float:
    """Shortest unit-circle distance after mapping both values modulo one phase."""
    observed = float(position) % 1.0
    marker = float(marker_ratio) % 1.0
    delta = abs(observed - marker)
    return min(delta, 1.0 - delta)


def phase_null_tests(
    phase_rows: list[dict[str, Any]],
    *,
    permutations: int,
) -> dict[str, dict[str, Any]]:
    """Evaluate Lane A phase markers against the frozen circular-shift null.

    The observed statistic and every null statistic use exactly the same shortest
    unit-circle distance. This is required for markers outside [0, 1], notably
    extension=1.272, whose circular representation is 0.272.
    """
    output: dict[str, dict[str, Any]] = {}
    for population, rows in _impl.populations(phase_rows).items():
        present = [row for row in rows if row["present"]]
        by_node = {
            node: [row for row in present if row["node"] == node]
            for node, _ in PHASE_MARKERS
        }
        actual: dict[str, float | None] = {
            node: (
                mean(
                    circular_phase_distance(
                        float(row["observed_phase_position"]),
                        ratio,
                    )
                    for row in node_rows
                )
                if node_rows
                else None
            )
            for node, ratio in PHASE_MARKERS
            for node_rows in (by_node[node],)
        }

        null_by_node: dict[str, list[float]] = {
            node: [] for node, _ in PHASE_MARKERS
        }
        cycle_ids = sorted({str(row["cycle_id"]) for row in present})
        for permutation_index in range(permutations):
            rng = random.Random(
                f"{RANDOM_SEED}:{population}:lane_a_phase:{permutation_index}"
            )
            shift_by_cycle = {cycle_id: rng.random() for cycle_id in cycle_ids}
            for node, ratio in PHASE_MARKERS:
                node_rows = by_node[node]
                if not node_rows:
                    continue
                null_error = mean(
                    circular_phase_distance(
                        (
                            float(row["observed_phase_position"])
                            + shift_by_cycle[str(row["cycle_id"])]
                        )
                        % 1.0,
                        ratio,
                    )
                    for row in node_rows
                )
                null_by_node[node].append(null_error)

        raw_p = {
            node: _impl.permutation_p_value(
                actual[node],
                null_by_node[node],
                higher_is_better=False,
            )
            for node, _ in PHASE_MARKERS
        }
        corrected = _impl.holm_bonferroni(raw_p)
        output[population] = {
            node: {
                "present_count": len(by_node[node]),
                "phase_null_metric": "shortest_unit_circle_distance",
                "mean_circular_phase_distance": actual[node],
                **corrected[node],
            }
            for node, _ in PHASE_MARKERS
        }
    return output


# The retained implementation's summarize_lane_a() resolves its private helper
# dynamically from its own module namespace. Install exactly the v1.0.1
# preregistered correction before any public analyze() call can execute.
_impl._phase_null_tests = phase_null_tests
