# Dashboard Time Display Policy V1

Canonical rule:

- store, process, and query timestamps in UTC
- DB timestamps remain UTC
- JSON timestamps remain UTC
- human-facing dashboard timestamps display in profile-local time
- current default profile/display timezone is `Europe/Amsterdam`
- DST must follow the IANA timezone database
- UTC may appear only as secondary/debug context, not as the primary UI time

Current profile timezone configuration:

- `joost` → `Europe/Amsterdam`

Implementation notes:

- reporting pages should use the shared formatter in
  `src/reporting/dashboard_time_v1.py`
- account-scoped runners should source the profile timezone from explicit
  dashboard profile access config
- global/legacy public pages currently use the canonical default display
  timezone until a broader user/profile-aware website layer exists

Boundary:

- changing display timezone must not change stored timestamps
- changing display timezone must not change JSON/API payload timestamps
- changing display timezone must not change freshness calculations, which remain
  based on UTC source timestamps
