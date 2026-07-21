from __future__ import annotations

import os
from pathlib import Path
from typing import MutableMapping

from dotenv import dotenv_values


DATABASE_ENV_KEYS = frozenset(
    {
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
        "DB_CHARSET",
        "DB_COLLATION",
        "DB_CONNECT_TIMEOUT",
        "DB_READ_TIMEOUT",
        "DB_WRITE_TIMEOUT",
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DATABASE",
        "MYSQL_CHARSET",
        "MYSQL_COLLATION",
    }
)


def load_database_environment(
    env_path: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Load only database settings; private broker values are never imported."""
    target = os.environ if environ is None else environ
    source = Path.cwd() / ".env" if env_path is None else env_path
    if not source.is_file():
        return
    for key, value in dotenv_values(source, interpolate=False).items():
        if key in DATABASE_ENV_KEYS and value is not None:
            target.setdefault(key, value)
