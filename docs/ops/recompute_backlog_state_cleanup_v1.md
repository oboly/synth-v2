# Recompute Backlog State Cleanup v1

After catch-up recompute, raw lifecycle labels can still say `MAP_RECOMPUTE_NEEDED`,
`RECLAIM_CONFIRMED`, or `TARGET_REACHED_STALE` because they describe the old map trigger
that caused the refresh. Those labels are not always the current operational state.

Current display state is derived from `post_refresh_state`:

- `REFRESHED_THIS_RUN`: refreshed in the current lifecycle refresh run; dashboard context, not backlog.
- `REFRESHED_RECENTLY`: latest advice carries a same-asof refresh marker; dashboard context.
- `COOLDOWN_MONITOR`: same-asof refresh marker exists and raw trigger still appears; dashboard watch.
- `RECOMPUTED_BUT_STILL_TRIGGERING`: recomputed but the current map still hits a critical trigger; review.
- `REFRESH_NEEDED`: no refresh/cooldown marker explains the trigger; backlog.
- `REFRESH_FAILED_OR_STALE`: attempted refresh failed or did not produce usable context; critical.
- `NO_REFRESH_NEEDED`: active map context.

The portfolio dashboard keeps raw lifecycle context visible, but policy/severity and recompute
display now use clean post-refresh states for refreshed and cooldown rows. This prevents false
persistent `BLOCK_RECOMPUTE_PENDING` labels after catch-up, while still keeping true stale,
failed, throttled, and still-triggering rows visible in the recompute worklist.

Boundary: this is reporting/advice-lifecycle display cleanup only. It makes no broker calls,
does not submit orders, and does not change selection, decision gate, execution planner, executor,
or account state.
