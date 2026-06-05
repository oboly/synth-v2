from __future__ import annotations

from dataclasses import dataclass


PROFILE_HAS_NO_ACCOUNT_ACCESS = "PROFILE_HAS_NO_ACCOUNT_ACCESS"


@dataclass(frozen=True)
class DashboardProfileAccess:
    account_profile: str
    venue: str
    trading_account_stable_ref: str


# Explicit dashboard-profile access map.
# The stable ref currently matches trading_account.account_code in the DB, but it is
# treated here only as a legacy stable trading-account reference, not as credential
# selection logic.
CONFIGURED_DASHBOARD_PROFILE_ACCESS: tuple[DashboardProfileAccess, ...] = (
    DashboardProfileAccess(
        account_profile="joost",
        venue="bitvavo",
        trading_account_stable_ref="bitvavo_joost_read",
    ),
)


def resolve_dashboard_profile_access(*, account_profile: str, venue: str) -> DashboardProfileAccess:
    normalized_profile = str(account_profile or "").strip().lower()
    normalized_venue = str(venue or "").strip().lower()
    for row in CONFIGURED_DASHBOARD_PROFILE_ACCESS:
        if row.account_profile == normalized_profile and row.venue == normalized_venue:
            return row
    raise RuntimeError(
        f"{PROFILE_HAS_NO_ACCOUNT_ACCESS}: profile={account_profile} venue={venue}"
    )
