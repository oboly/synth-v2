"""
manual_execution_operator_identity_v1 — explicit canonical Bitvavo
``operatorId`` resolution for the manual SELL ladder submission orchestrator
(Issue #369).

Layer: executor-only, pure/no DB access, no broker calls.

Bitvavo's Create Order requires an integer ``operatorId`` identifying the
trader/bot placing the order. It must be one explicit, canonical Synth
executor/bot identity — never inferred from a user/profile display name or
slug — and is resolved fail-closed from an explicit environment variable
only. There is no fallback default.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import os
from typing import Final, Mapping

BITVAVO_OPERATOR_ID_ENV: Final[str] = "SYNTH_BITVAVO_OPERATOR_ID"


class OperatorIdentityNotConfiguredError(ValueError):
    """Fail-closed: no explicit canonical operatorId is configured."""


def resolve_operator_id(*, env: Mapping[str, str] | None = None) -> int:
    """Resolve the canonical Bitvavo operatorId from an explicit env var.
    Fails closed (raises) if missing, empty, non-integer, or non-positive.
    Never inferred from a display name or profile slug."""
    source = env if env is not None else os.environ
    raw = (source.get(BITVAVO_OPERATOR_ID_ENV) or "").strip()
    if not raw:
        raise OperatorIdentityNotConfiguredError(
            f"MISSING_BITVAVO_OPERATOR_ID: set {BITVAVO_OPERATOR_ID_ENV}"
        )
    try:
        value = int(raw)
    except ValueError:
        raise OperatorIdentityNotConfiguredError(
            f"INVALID_BITVAVO_OPERATOR_ID: {raw!r} is not an integer"
        ) from None
    if value <= 0:
        raise OperatorIdentityNotConfiguredError(
            f"INVALID_BITVAVO_OPERATOR_ID: must be a positive integer, got {value}"
        )
    return value
