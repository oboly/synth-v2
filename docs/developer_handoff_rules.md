# Developer Handoff Rules

These rules define the preferred delivery format for code and file changes in this repo.

## Shell delivery

- Provide bash-ready heredocs for file creation or replacement on the local host
- Prefer full-file replacement over partial patch fragments
- Run commands from repo root unless explicitly stated otherwise
- For work on a remote host, follow the SSH output rule in `AGENTS.md`: name the
  host outside the code block and do not wrap heredocs in `ssh ...`

## File creation

- For new files or directories, use `mkdir -p` before writing
- Do not use `rm` for files that may not exist
- Overwrite directly with `cat << 'EOF' > file`

## SQL delivery

- Provide SQL in one plain code block
- Do not wrap SQL in shell unless explicitly requested

## Python/code delivery

- Prefer complete file contents
- Keep code copy-paste ready
- Keep indentation clean and stable

## Analysis scripts

- Prefer reading from stable SQL views when available
- Avoid ad hoc schema guessing inside scripts
- Use canonical table and column names from `docs/database/README.md`

