from __future__ import annotations

"""Strictly read-only native SHORT snapshot filesystem contract preflight."""

import argparse
import grp
import json
import os
import pwd
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from src.market_data.native_short_fib_context_snapshot_v1 import (
    BUNDLE_NAME,
    IMMUTABLE_ARTIFACT_MODE,
    IMMUTABLE_SNAPSHOT_DIR_MODE,
    MANIFEST_MODE,
    MANIFEST_NAME,
    PUBLICATION_LOCK_MODE,
    PUBLICATION_LOCK_NAME,
    PUBLISHER_USER as CONTRACT_PUBLISHER_USER,
    PUBLISH_ROOT_MODE,
    READER_GROUP as CONTRACT_READER_GROUP,
    ROWS_NAME,
    SNAPSHOTS_DIR_MODE,
    SnapshotContractError,
    validate_published_snapshot,
)


RUNNER_NAME = "native_short_snapshot_filesystem_preflight_v1"
DEFAULT_SNAPSHOT_ROOT = Path("/var/www/html/synth/_runtime/native_short_context_snapshot_v1")
PUBLISHER_USER = CONTRACT_PUBLISHER_USER
READER_GROUP = CONTRACT_READER_GROUP
READER_USERS = ("theone",)
REQUIRED_READER_GROUP_MEMBERS = (PUBLISHER_USER, *READER_USERS)
PASS = "PASS"
FAIL = "FAIL"


@dataclass(frozen=True)
class Identity:
    name: str
    uid: int
    gids: frozenset[int]


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class PathEvidence:
    path: str
    owner: str
    owner_uid: int
    group: str
    group_gid: int
    mode: str
    acl_xattrs: tuple[str, ...]


@dataclass(frozen=True)
class PreflightResult:
    result: str
    checks: tuple[Check, ...]
    paths: tuple[PathEvidence, ...]


def _identity(name: str) -> Identity:
    account = pwd.getpwnam(name)
    gids = {account.pw_gid}
    for group in grp.getgrall():
        if name in group.gr_mem:
            gids.add(group.gr_gid)
    return Identity(name=name, uid=account.pw_uid, gids=frozenset(gids))


def _group_member_names(group: grp.struct_group) -> set[str]:
    members = set(group.gr_mem)
    members.update(
        account.pw_name
        for account in pwd.getpwall()
        if account.pw_gid == group.gr_gid
    )
    return members


def _permission_bits(metadata: os.stat_result, identity: Identity) -> int:
    mode = stat.S_IMODE(metadata.st_mode)
    if metadata.st_uid == identity.uid:
        return (mode >> 6) & 0b111
    if metadata.st_gid in identity.gids:
        return (mode >> 3) & 0b111
    return mode & 0b111


def _can_read(path: Path, identity: Identity) -> bool:
    return bool(_permission_bits(path.lstat(), identity) & 0b100)


def _can_write(path: Path, identity: Identity) -> bool:
    bits = _permission_bits(path.lstat(), identity)
    if stat.S_ISDIR(path.lstat().st_mode):
        return bits & 0b011 == 0b011
    return bool(bits & 0b010)


def _can_traverse(path: Path, identity: Identity) -> bool:
    return bool(_permission_bits(path.lstat(), identity) & 0b001)


def _path_evidence(path: Path) -> PathEvidence:
    metadata = path.lstat()
    try:
        owner = pwd.getpwuid(metadata.st_uid).pw_name
    except KeyError:
        owner = str(metadata.st_uid)
    try:
        group = grp.getgrgid(metadata.st_gid).gr_name
    except KeyError:
        group = str(metadata.st_gid)
    acl_xattrs = tuple(
        sorted(
            name
            for name in os.listxattr(path, follow_symlinks=False)
            if name in {"system.posix_acl_access", "system.posix_acl_default"}
        )
    )
    return PathEvidence(
        path=str(path),
        owner=owner,
        owner_uid=metadata.st_uid,
        group=group,
        group_gid=metadata.st_gid,
        mode=f"{stat.S_IMODE(metadata.st_mode):04o}",
        acl_xattrs=acl_xattrs,
    )


def _check(
    checks: list[Check],
    name: str,
    condition: bool,
    pass_detail: str,
    fail_detail: str,
) -> None:
    checks.append(Check(name, PASS if condition else FAIL, pass_detail if condition else fail_detail))


def _existing_components(path: Path) -> list[Path]:
    absolute = Path(os.path.abspath(path))
    return [
        component
        for component in reversed((absolute, *absolute.parents))
        if os.path.lexists(component)
    ]


def _contract_paths(
    snapshot_root: Path,
) -> tuple[list[tuple[Path, int]], list[Path], list[Path]]:
    snapshots_dir = snapshot_root / "snapshots"
    expected: list[tuple[Path, int]] = [
        (snapshot_root, PUBLISH_ROOT_MODE),
        (snapshot_root / MANIFEST_NAME, MANIFEST_MODE),
        (snapshot_root / PUBLICATION_LOCK_NAME, PUBLICATION_LOCK_MODE),
        (snapshots_dir, SNAPSHOTS_DIR_MODE),
    ]
    symlinks: list[Path] = []
    unexpected: list[Path] = []
    allowed_root_names = {MANIFEST_NAME, PUBLICATION_LOCK_NAME, "snapshots"}
    for entry in snapshot_root.iterdir():
        if entry.is_symlink():
            symlinks.append(entry)
        if entry.name not in allowed_root_names:
            unexpected.append(entry)
    if snapshots_dir.is_dir() and not snapshots_dir.is_symlink():
        for entry in sorted(snapshots_dir.iterdir()):
            if entry.is_symlink():
                symlinks.append(entry)
                continue
            expected.append((entry, IMMUTABLE_SNAPSHOT_DIR_MODE))
            if entry.is_dir():
                allowed_artifact_names = {ROWS_NAME, BUNDLE_NAME}
                expected.extend(
                    (
                        (entry / ROWS_NAME, IMMUTABLE_ARTIFACT_MODE),
                        (entry / BUNDLE_NAME, IMMUTABLE_ARTIFACT_MODE),
                    )
                )
                for child in entry.iterdir():
                    if child.is_symlink():
                        symlinks.append(child)
                    if child.name not in allowed_artifact_names:
                        unexpected.append(child)
            else:
                unexpected.append(entry)
    return expected, symlinks, unexpected


def inspect_snapshot_filesystem(
    snapshot_root: Path,
    *,
    publisher: Identity,
    consumers: Sequence[Identity],
    reader_gid: int,
    reader_group: str,
) -> PreflightResult:
    checks: list[Check] = []
    evidence: list[PathEvidence] = []
    components = _existing_components(snapshot_root)
    symlink_components = [path for path in components if stat.S_ISLNK(path.lstat().st_mode)]
    _check(
        checks,
        "symlink_components",
        not symlink_components,
        "no symlink in snapshot-root ancestry",
        f"symlinks={','.join(map(str, symlink_components))}",
    )
    if not snapshot_root.is_dir() or snapshot_root.is_symlink():
        _check(
            checks,
            "snapshot_root",
            False,
            "",
            f"missing_or_unsafe={snapshot_root}",
        )
        return PreflightResult(FAIL, tuple(checks), tuple(evidence))
    evidence.extend(_path_evidence(path) for path in components[:-1])

    same_uid = [consumer.name for consumer in consumers if consumer.uid == publisher.uid]
    _check(
        checks,
        "same_uid_conflicts",
        not same_uid,
        "publisher UID is distinct from every consumer UID",
        f"publisher={publisher.name}:{publisher.uid} conflicts={','.join(same_uid)}",
    )
    _check(
        checks,
        "publisher_reader_group_membership",
        reader_gid in publisher.gids,
        f"publisher {publisher.name} is a member of {reader_group}",
        f"group={reader_group} missing={publisher.name}",
    )
    group_membership_missing = [
        consumer.name for consumer in consumers if reader_gid not in consumer.gids
    ]
    _check(
        checks,
        "reader_group_membership",
        not group_membership_missing,
        f"all consumers are members of {reader_group}",
        f"group={reader_group} missing={','.join(group_membership_missing)}",
    )

    for identity in (publisher, *consumers):
        blocked = [
            str(path)
            for path in components[:-1]
            if not stat.S_ISDIR(path.lstat().st_mode) or not _can_traverse(path, identity)
        ]
        _check(
            checks,
            f"parent_traversal:{identity.name}",
            not blocked,
            f"{identity.name} can traverse every existing parent",
            f"{identity.name} blocked={','.join(blocked)}",
        )

    expected_paths, tree_symlinks, unexpected_paths = _contract_paths(snapshot_root)
    _check(
        checks,
        "snapshot_tree_symlinks",
        not tree_symlinks,
        "no symlinks in snapshot publication tree",
        f"symlinks={','.join(map(str, tree_symlinks))}",
    )
    _check(
        checks,
        "unexpected_paths",
        not unexpected_paths,
        "snapshot publication tree contains only contract paths",
        f"unexpected={','.join(map(str, unexpected_paths))}",
    )
    missing = [str(path) for path, _ in expected_paths if not os.path.lexists(path)]
    _check(
        checks,
        "required_paths",
        not missing,
        "all canonical contract paths exist",
        f"missing={','.join(missing)}",
    )
    existing_expected = [
        (path, mode) for path, mode in expected_paths if os.path.lexists(path)
    ]
    evidence.extend(_path_evidence(path) for path, _ in existing_expected)
    acl_paths = [
        f"{path.path}:{','.join(path.acl_xattrs)}"
        for path in evidence
        if path.acl_xattrs
    ]
    _check(
        checks,
        "extended_acls",
        not acl_paths,
        "no parent or publication path has an extended POSIX ACL",
        f"violations={','.join(acl_paths)}",
    )

    wrong_modes = [
        f"{path}:{stat.S_IMODE(path.lstat().st_mode):04o}!={mode:04o}"
        for path, mode in existing_expected
        if stat.S_IMODE(path.lstat().st_mode) != mode
    ]
    _check(
        checks,
        "canonical_modes",
        not wrong_modes,
        "all publication paths have canonical deterministic modes",
        f"violations={','.join(wrong_modes)}",
    )
    wrong_owners = [
        f"{path}:{path.lstat().st_uid}"
        for path, _ in existing_expected
        if path.lstat().st_uid != publisher.uid
    ]
    _check(
        checks,
        "publisher_ownership",
        not wrong_owners,
        f"all publication paths are owned by {publisher.name}",
        f"expected_uid={publisher.uid} violations={','.join(wrong_owners)}",
    )
    wrong_groups = [
        f"{path}:{path.lstat().st_gid}"
        for path, _ in existing_expected
        if path.lstat().st_gid != reader_gid
    ]
    _check(
        checks,
        "reader_group",
        not wrong_groups,
        f"all publication paths use reader group {reader_group}",
        f"expected_gid={reader_gid} violations={','.join(wrong_groups)}",
    )
    writable_modes = [
        f"{path}:{stat.S_IMODE(path.lstat().st_mode):04o}"
        for path, _ in existing_expected
        if stat.S_IMODE(path.lstat().st_mode) & 0o022
    ]
    _check(
        checks,
        "group_world_write",
        not writable_modes,
        "no publication path is group-writable or world-writable",
        f"violations={','.join(writable_modes)}",
    )

    manifest_path = snapshot_root / MANIFEST_NAME
    lock_path = snapshot_root / PUBLICATION_LOCK_NAME
    snapshots_dir = snapshot_root / "snapshots"
    publisher_write_targets = (snapshot_root, snapshots_dir, manifest_path, lock_path)
    publisher_write_failures = [
        str(path)
        for path in publisher_write_targets
        if not os.path.lexists(path) or not _can_write(path, publisher)
    ]
    _check(
        checks,
        "publisher_write_access",
        not publisher_write_failures,
        f"mode bits grant {publisher.name} direct writes on the mutable publication surfaces",
        f"not_writable={','.join(publisher_write_failures)}",
    )
    immutable_paths = [
        path
        for path, mode in existing_expected
        if mode in {IMMUTABLE_SNAPSHOT_DIR_MODE, IMMUTABLE_ARTIFACT_MODE}
    ]
    publisher_immutable_writes = [
        str(path) for path in immutable_paths if _can_write(path, publisher)
    ]
    _check(
        checks,
        "finalized_snapshot_direct_write_bits",
        not publisher_immutable_writes,
        (
            "finalized snapshot modes omit direct write bits; publisher-side "
            "immutability remains application-enforced because the owning "
            "publisher can chmod"
        ),
        f"writable={','.join(publisher_immutable_writes)}",
    )

    try:
        validated = validate_published_snapshot(snapshot_root)
    except (OSError, SnapshotContractError) as exc:
        validated = None
        _check(checks, "snapshot_digest", False, "", str(exc))
    else:
        _check(
            checks,
            "snapshot_digest",
            True,
            f"snapshot_id={validated.snapshot_id} row_count={validated.row_count}",
            "",
        )

    raw_paths = [manifest_path]
    if validated is not None:
        raw_paths.extend((validated.rows_path, validated.bundle_path))
    for consumer in consumers:
        read_failures: list[str] = []
        for path in raw_paths:
            if not os.path.lexists(path) or not _can_read(path, consumer):
                read_failures.append(str(path))
                continue
            for parent in (snapshot_root, *reversed(path.parents)):
                if parent == snapshot_root.parent:
                    continue
                if parent == snapshot_root or parent.is_relative_to(snapshot_root):
                    if not _can_traverse(parent, consumer):
                        read_failures.append(f"{path}:blocked_by={parent}")
                        break
        write_paths = [
            path
            for path, _ in existing_expected
            if _can_write(path, consumer)
        ]
        _check(
            checks,
            f"consumer_read:{consumer.name}",
            not read_failures,
            f"{consumer.name} can read manifest and referenced immutable artifacts",
            f"unreadable={','.join(read_failures)}",
        )
        _check(
            checks,
            f"consumer_write_rejection:{consumer.name}",
            not write_paths,
            f"{consumer.name} cannot write any publication path",
            f"writable={','.join(map(str, write_paths))}",
        )

    result = PASS if all(check.status == PASS for check in checks) else FAIL
    return PreflightResult(result, tuple(checks), tuple(evidence))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Native SHORT snapshot filesystem ownership and digest preflight."
    )
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--publisher-user", default=PUBLISHER_USER)
    parser.add_argument("--reader-group", default=READER_GROUP)
    parser.add_argument("--consumer-user", action="append", dest="consumer_users")
    parser.add_argument("--output", choices=("json", "summary"), default="summary")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    consumer_users: tuple[str, ...] = ()
    try:
        publisher = _identity(args.publisher_user)
        reader = grp.getgrnam(args.reader_group)
        actual_reader_members = _group_member_names(reader)
        consumer_users = tuple(sorted(set(args.consumer_users or READER_USERS)))
        consumers = tuple(_identity(name) for name in consumer_users)
        result = inspect_snapshot_filesystem(
            args.snapshot_root,
            publisher=publisher,
            consumers=consumers,
            reader_gid=reader.gr_gid,
            reader_group=reader.gr_name,
        )
        exact_readers = actual_reader_members == set(REQUIRED_READER_GROUP_MEMBERS)
        exact_reader_check = Check(
            "exact_reader_group_membership",
            PASS if exact_readers else FAIL,
            (
                "reader group members are exactly "
                f"{','.join(REQUIRED_READER_GROUP_MEMBERS)}"
            )
            if exact_readers
            else (
                f"actual={','.join(sorted(actual_reader_members)) or 'none'} "
                f"expected={','.join(REQUIRED_READER_GROUP_MEMBERS)}"
            ),
        )
        checks = (*result.checks, exact_reader_check)
        result = PreflightResult(
            PASS if all(check.status == PASS for check in checks) else FAIL,
            checks,
            result.paths,
        )
    except (KeyError, OSError, SnapshotContractError) as exc:
        payload = {
            "runner": RUNNER_NAME,
            "result": FAIL,
            "detail": f"identity_or_group_missing={exc}",
            "read_only": True,
        }
        rendered = (
            json.dumps(payload, sort_keys=True)
            if args.output == "json"
            else " ".join(f"{key}={value}" for key, value in payload.items())
        )
        print(rendered)
        return 1

    payload = {
        "runner": RUNNER_NAME,
        "result": result.result,
        "publisher_user": args.publisher_user,
        "reader_group": args.reader_group,
        "consumer_users": consumer_users,
        "read_only": True,
        "checks": [asdict(check) for check in result.checks],
        "paths": [asdict(path) for path in result.paths],
    }
    if args.output == "json":
        print(json.dumps(payload, sort_keys=True))
    else:
        failed = [check.name for check in result.checks if check.status == FAIL]
        print(
            f"runner={RUNNER_NAME} result={result.result} read_only=true "
            f"publisher={args.publisher_user} readers={','.join(consumer_users)} "
            f"reader_group={args.reader_group} failed={','.join(failed) or 'none'}"
        )
        for path in result.paths:
            print(
                f"path={path.path} owner={path.owner} owner_uid={path.owner_uid} "
                f"group={path.group} group_gid={path.group_gid} mode={path.mode} "
                f"acl_xattrs={','.join(path.acl_xattrs) or 'none'}"
            )
    return 0 if result.result == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
