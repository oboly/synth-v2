"""Executor-owned UTC clock; production code has no clock override."""
from datetime import datetime, timezone
def utc_now() -> datetime:
    return datetime.now(timezone.utc)
