from __future__ import annotations

"""Closed database binding for the canonical 4h market-chain process tree."""

from dataclasses import dataclass, field
import grp
import os
from pathlib import Path
import pwd
import stat
from typing import Mapping


BINDING_PROFILE_ENV = "SYNTH_DB_BINDING_PROFILE"
BINDING_PROFILE = "synth_chain_4h"
ENV_HOST = "SYNTH_CHAIN_4H_DB_HOST"
ENV_PORT = "SYNTH_CHAIN_4H_DB_PORT"
ENV_USER = "SYNTH_CHAIN_4H_DB_USER"
ENV_DATABASE = "SYNTH_CHAIN_4H_DB_NAME"
ENV_PASSWORD_FILE = "SYNTH_CHAIN_4H_DB_PASSWORD_FILE"
DEDICATED_ENV_KEYS = (
    ENV_HOST,
    ENV_PORT,
    ENV_USER,
    ENV_DATABASE,
    ENV_PASSWORD_FILE,
)
GENERIC_DB_ENV_KEYS = (
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
)

EXPECTED_USER = "synth_chain_4h_writer"
EXPECTED_DATABASE = "synth"
EXPECTED_HOST = "gurkdb"
EXPECTED_PORT = 3306
EXPECTED_PASSWORD_FILE = Path("/etc/synth/synth-chain-4h-db-password-v1")
EXPECTED_SECRET_OWNER = "root"
EXPECTED_SECRET_GROUP = "gurk"
EXPECTED_SECRET_MODE = 0o640
MAX_SECRET_BYTES = 4096


class ChainDatabaseBindingError(ValueError):
    """A fail-closed binding or secret-transport contract violation."""


@dataclass(frozen=True)
class SecretFileMetadata:
    path: Path
    file_type: str
    owner: str
    group: str
    mode: int
    is_symlink: bool


@dataclass(frozen=True)
class ChainDatabaseBinding:
    profile: str
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str
    password_file: Path
    secret_metadata: SecretFileMetadata


def dedicated_binding_requested(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return bool(source.get(BINDING_PROFILE_ENV)) or any(
        key in source for key in DEDICATED_ENV_KEYS
    )


def generic_fallback_variables(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    source = os.environ if environ is None else environ
    return tuple(key for key in GENERIC_DB_ENV_KEYS if source.get(key))


def _identity_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _group_name(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def _expected_ids(
    *,
    expected_uid: int | None,
    expected_gid: int | None,
) -> tuple[int, int]:
    try:
        uid = (
            pwd.getpwnam(EXPECTED_SECRET_OWNER).pw_uid
            if expected_uid is None
            else expected_uid
        )
        gid = (
            grp.getgrnam(EXPECTED_SECRET_GROUP).gr_gid
            if expected_gid is None
            else expected_gid
        )
    except KeyError as exc:
        raise ChainDatabaseBindingError(
            "CHAIN_DB_SECRET_EXPECTED_IDENTITY_UNAVAILABLE"
        ) from exc
    return uid, gid


def read_password_file(
    path: Path,
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> tuple[str, SecretFileMetadata]:
    expected_uid, expected_gid = _expected_ids(
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    try:
        path_stat = path.lstat()
    except FileNotFoundError as exc:
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_MISSING") from exc
    except OSError as exc:
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_UNREADABLE") from exc

    is_symlink = stat.S_ISLNK(path_stat.st_mode)
    if is_symlink:
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_SYMLINK_FORBIDDEN")
    if not stat.S_ISREG(path_stat.st_mode):
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_NOT_REGULAR")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_OPEN_FAILED") from exc

    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_NOT_REGULAR")
        if (
            opened_stat.st_dev != path_stat.st_dev
            or opened_stat.st_ino != path_stat.st_ino
        ):
            raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_CHANGED")
        mode = stat.S_IMODE(opened_stat.st_mode)
        if mode != EXPECTED_SECRET_MODE:
            raise ChainDatabaseBindingError(
                "CHAIN_DB_SECRET_FILE_MODE_INVALID "
                f"expected={EXPECTED_SECRET_MODE:04o} actual={mode:04o}"
            )
        if opened_stat.st_uid != expected_uid or opened_stat.st_gid != expected_gid:
            raise ChainDatabaseBindingError(
                "CHAIN_DB_SECRET_FILE_OWNERSHIP_INVALID "
                f"expected={EXPECTED_SECRET_OWNER}:{EXPECTED_SECRET_GROUP} "
                f"actual={_identity_name(opened_stat.st_uid)}:"
                f"{_group_name(opened_stat.st_gid)}"
            )
        chunks: list[bytes] = []
        remaining = MAX_SECRET_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)

    if len(payload) > MAX_SECRET_BYTES:
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_TOO_LARGE")
    try:
        password = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_ENCODING_INVALID") from exc
    if password.endswith("\r\n"):
        password = password[:-2]
    elif password.endswith("\n"):
        password = password[:-1]
    if not password:
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_EMPTY")
    if "\n" in password or "\r" in password or "\x00" in password:
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_FORMAT_INVALID")

    metadata = SecretFileMetadata(
        path=path,
        file_type="regular",
        owner=_identity_name(opened_stat.st_uid),
        group=_group_name(opened_stat.st_gid),
        mode=mode,
        is_symlink=False,
    )
    return password, metadata


def load_chain_database_binding(
    environ: Mapping[str, str] | None = None,
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> ChainDatabaseBinding:
    source = os.environ if environ is None else environ
    profile = str(source.get(BINDING_PROFILE_ENV) or "")
    if profile != BINDING_PROFILE:
        if not profile:
            raise ChainDatabaseBindingError(
                f"CHAIN_DB_BINDING_PROFILE_MISSING name={BINDING_PROFILE_ENV}"
            )
        raise ChainDatabaseBindingError("CHAIN_DB_BINDING_PROFILE_INVALID")

    missing = tuple(key for key in DEDICATED_ENV_KEYS if not source.get(key))
    if missing:
        raise ChainDatabaseBindingError(
            "CHAIN_DB_BINDING_CONFIG_MISSING names=" + ",".join(missing)
        )

    host = str(source[ENV_HOST]).strip()
    user = str(source[ENV_USER]).strip()
    database = str(source[ENV_DATABASE]).strip()
    if user != EXPECTED_USER:
        raise ChainDatabaseBindingError(
            f"CHAIN_DB_BINDING_USER_INVALID expected={EXPECTED_USER}"
        )
    if database != EXPECTED_DATABASE:
        raise ChainDatabaseBindingError(
            f"CHAIN_DB_BINDING_DATABASE_INVALID expected={EXPECTED_DATABASE}"
        )
    try:
        port = int(str(source[ENV_PORT]))
    except ValueError as exc:
        raise ChainDatabaseBindingError("CHAIN_DB_BINDING_PORT_INVALID") from exc
    if not 1 <= port <= 65535:
        raise ChainDatabaseBindingError("CHAIN_DB_BINDING_PORT_INVALID")

    password_file = Path(str(source[ENV_PASSWORD_FILE]))
    if not password_file.is_absolute():
        raise ChainDatabaseBindingError("CHAIN_DB_SECRET_FILE_PATH_NOT_ABSOLUTE")
    password, metadata = read_password_file(
        password_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    return ChainDatabaseBinding(
        profile=profile,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        password_file=password_file,
        secret_metadata=metadata,
    )
