from __future__ import annotations

import argparse
import re
from pathlib import Path


FILE_HEADER_RE = re.compile(
    r"^# =============================================================================\s*$\n"
    r"^# FILE:\s*(?P<path>.+?)\s*$\n"
    r"^# =============================================================================\s*$",
    re.MULTILINE,
)


def split_bundle(text: str) -> list[tuple[str, str]]:
    matches = list(FILE_HEADER_RE.finditer(text))
    results: list[tuple[str, str]] = []

    for i, match in enumerate(matches):
        file_path = match.group("path").strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end]
        content = content.lstrip("\n").rstrip() + "\n"
        results.append((file_path, content))

    return results


def should_write(path_str: str) -> bool:
    path = Path(path_str)
    return path.suffix == ".py"


def write_files(bundle_path: Path, root_dir: Path, overwrite: bool) -> int:
    text = bundle_path.read_text(encoding="utf-8")
    file_entries = split_bundle(text)

    if not file_entries:
        raise RuntimeError("No '# FILE: ...' sections found in bundle.")

    written = 0
    for rel_path, content in file_entries:
        if not should_write(rel_path):
            print(f"[SKIP] non-py: {rel_path}")
            continue

        out_path = root_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if out_path.exists() and not overwrite:
            print(f"[SKIP] exists: {out_path}")
            continue

        out_path.write_text(content, encoding="utf-8")
        print(f"[WRITE] {out_path}")
        written += 1

    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write only Python files from a bundle text with '# FILE:' sections."
    )
    parser.add_argument("bundle", help="Path to the bundle text file.")
    parser.add_argument(
        "--root",
        default=".",
        help="Project root directory to write into. Default: current directory.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files.",
    )
    args = parser.parse_args()

    bundle_path = Path(args.bundle).resolve()
    root_dir = Path(args.root).resolve()

    count = write_files(bundle_path=bundle_path, root_dir=root_dir, overwrite=args.overwrite)
    print(f"[DONE] py_files_written={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
