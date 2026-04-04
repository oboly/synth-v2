from __future__ import annotations

from pathlib import Path
import re
import sys

PATCH_FILE = Path("scripts/lot_patch_2.txt")
ROOT = Path.cwd()

def main() -> int:
    text = PATCH_FILE.read_text(encoding="utf-8")

    pattern = re.compile(
        r"=+\nFILE:\s*(.*?)\n=+\n(.*?)(?=\n=+\nFILE:|\Z)",
        re.DOTALL,
    )
    matches = pattern.findall(text)

    if not matches:
        print("[ERROR] No FILE blocks found in patch txt.")
        return 1

    wrote = 0
    for rel_path, content in matches:
        rel_path = rel_path.strip()
        content = content.lstrip("\n").rstrip() + "\n"

        path = ROOT / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"[WROTE] {rel_path}")
        wrote += 1

    print(f"[DONE] Wrote {wrote} files from txt bundle.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
