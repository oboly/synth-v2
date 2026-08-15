"""Subsystem-owned UTC clock for the side-neutral algorithmic executor
boundary (Issue #206).

Deliberately duplicated (not imported) from
src.manual_execution._trusted_clock_v1: the shared BUY/SELL executor
boundary must not depend on the manual_execution package, which is
substrate for the manual lane only. Production APIs do not accept a clock
or timestamp override. Tests may patch this private module function in
their own process; no production composition path imports test
infrastructure or exposes a clock selector.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
