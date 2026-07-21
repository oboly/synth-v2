from __future__ import annotations


LIVE_PREREQUISITE_CODES = (
    "CANONICAL_DECISION_GATE_PERMISSION_PRODUCER_REQUIRED",
    "ACCOUNT_BOUND_TRADE_CREDENTIAL_BINDING_REQUIRED",
    "LIVE_EXECUTOR_ACTIVATION_REQUIRED",
)


class LiveExecutionPrerequisitesUnavailable(RuntimeError):
    code = "LIVE_EXECUTION_PREREQUISITES_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(f"{self.code}:" + ",".join(LIVE_PREREQUISITE_CODES))
