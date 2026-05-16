# TODO — Dev / Ops Hygiene

## Status

Mostly done / parked. Keep as operational hygiene notes.

These items came from recent chats and are not active research lanes unless they block Synth work.

## Done / parked — Codex smoke lane

Status: done.

Notes:

- Codex smoke/test branch work was completed successfully.
- User confirmed Codex test passed.
- No active TODO unless future Codex-specific repo automation is opened.

Boundary:

```text
Do not mix Codex smoke work into Market Breath research branches.
```

## Done / parked — DBeaver / MariaDB access recovery

Status: done.

Notes:

- Remote MariaDB connection from dev host to `gurkdb` was verified.
- Password mismatch/root-secret change was identified as the cause of earlier DBeaver connection confusion.
- No active TODO unless DBeaver workspace breaks again.

Known good verification shape:

```text
mysql -h 192.168.1.221 -P 3306 -u synth -p"$PASS" synth \
  -e "SELECT DATABASE() AS db, USER() AS login_user, CURRENT_USER() AS matched_user;"
```

Expected matched user pattern:

```text
synth@192.168.1.%
```

## P3 — MariaDB export / backup hygiene

Status: open if not already completed outside repo.

Reason:

Recent chat included a local MariaDB export / backup help request. No canonical repo TODO was found for backup cadence or export scripts.

Tasks:

- Decide whether Synth needs a documented manual DB export procedure.
- Decide whether backup belongs in `docs/ops/` or `docs/status/` rather than research docs.
- Keep secrets out of git.
- Do not commit database dumps.
- Prefer a documented command that reads DB password from the existing local secret path.

Boundary:

```text
Operational backup hygiene only.
No DB schema changes.
No runtime chain changes.
No broker/order involvement.
```

## P4 — Local untracked file hygiene

Status: ongoing hygiene.

Notes:

- A+ raw files may remain untracked while parked.
- Avoid broad `git add data/`.
- Market Breath branches should stage only intended Market Breath artifacts.

Recommended check before every commit:

```bash
git status --short
git diff --cached --name-only
```
