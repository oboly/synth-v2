from __future__ import annotations

"""Legacy DB compatibility wrapper.

Importing this module intentionally preserves the repository's historical
``load_dotenv()`` behavior. PAPER runtimes use ``db_env_v1`` plus
``db_core_v1`` directly and must not import this wrapper.
"""

from dotenv import load_dotenv


load_dotenv()


from src.common.db_core_v1 import (  # noqa: E402
    DEFAULT_CHARSET,
    DEFAULT_COLLATION,
    DEFAULT_DATABASE,
    _db_charset,
    _db_collation,
    _env_first,
    _env_int,
    db_cursor,
    get_connection,
    get_db_connection,
    test_connection,
)


__all__ = [
    "DEFAULT_CHARSET",
    "DEFAULT_COLLATION",
    "DEFAULT_DATABASE",
    "db_cursor",
    "get_connection",
    "get_db_connection",
    "test_connection",
]
