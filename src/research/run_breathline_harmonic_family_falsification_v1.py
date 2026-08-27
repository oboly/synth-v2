from __future__ import annotations

"""Safe CLI entrypoint for Issue #533 harmonic-family falsification v1.

The preregistered statistical implementation lives in
``breathline_harmonic_family_falsification_core_v1``. This module re-exports
that research API and owns only CLI lifecycle/immutable-output handling.
"""

import shutil
import time
from typing import Any

from src.research.breathline_harmonic_family_falsification_core_v1 import *  # noqa: F401,F403
from src.research import breathline_harmonic_family_falsification_core_v1 as _core


# Re-export the core's explicit exception type and helpers for focused tests and
# repository callers. Underscore-prefixed core helpers intentionally stay internal.
InputProvenanceError = _core.InputProvenanceError


def main(argv: list[str] | None = None) -> int:
    args = _core.build_parser().parse_args(argv)
    run_id = _core.validate_run_id(
        args.run_id or _core.utc_now().strftime("%Y%m%dT%H%M%SZ")
    )
    out_dir = args.out_root / run_id
    out_dir_preexisted = out_dir.exists()
    started = time.monotonic()

    _core.emit(
        "STARTED",
        _core.RUNNER_NAME,
        run_id=run_id,
        registry_version=_core.REGISTRY_VERSION,
        permutations=_core.NULL_PERMUTATIONS,
        research_only=True,
    )

    try:
        manifest = _core.analyze(
            source_run_dir=args.source_run_dir,
            out_dir=out_dir,
            permutations=_core.NULL_PERMUTATIONS,
        )
    except Exception as exc:
        # Never remove an already-existing immutable evidence directory. Cleanup
        # is allowed only for a directory that this invocation could have created.
        if not out_dir_preexisted:
            shutil.rmtree(out_dir, ignore_errors=True)
        _core.emit(
            "FAILED",
            _core.RUNNER_NAME,
            run_id=run_id,
            elapsed_seconds=f"{time.monotonic() - started:.2f}",
            error_type=type(exc).__name__,
            error=str(exc),
            broker_private_calls=0,
            broker_writes=0,
            order_submission=0,
            live_orders=0,
            decision_gate="none",
            execution_planner="none",
            executor="none",
        )
        return 1

    _core.emit(
        "FINISHED",
        _core.RUNNER_NAME,
        run_id=run_id,
        elapsed_seconds=f"{time.monotonic() - started:.2f}",
        output_dir=str(out_dir),
        source_run_id=manifest.get("source_run_id"),
        broker_private_calls=0,
        broker_writes=0,
        order_submission=0,
        live_orders=0,
        decision_gate="none",
        execution_planner="none",
        executor="none",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
