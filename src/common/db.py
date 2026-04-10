from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor


load_dotenv(".env")


def _getenv_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_db_connection():
    return get_connection()

def get_connection():
    return pymysql.connect(
        host=_getenv_required("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=_getenv_required("DB_USER"),
        password=os.getenv("DB_PASSWORD", ""),
        database=_getenv_required("DB_NAME"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


@contextmanager
def db_cursor(commit: bool = False) -> Iterator:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield conn, cur
        if commit:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
