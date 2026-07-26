"""Subsystem-owned UTC clock for manual execution authority decisions.

Production APIs do not accept a clock or timestamp override. Tests may patch
this private module function in their own process; no production composition
path imports test infrastructure or exposes a clock selector.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
