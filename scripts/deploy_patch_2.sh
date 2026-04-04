#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

PATCH_TXT="scripts/lot_patch_2.txt"
WRITER_PY="scripts/lot_patch_2_writer.py"

if [ ! -f "$PATCH_TXT" ]; then
  echo "[ERROR] Missing $PATCH_TXT"
  exit 1
fi

echo "[INFO] Creating writer script from txt bundle..."
cat > "$WRITER_PY" <<'PY'
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
PY

echo "[INFO] Running writer..."
python "$WRITER_PY"

echo "[INFO] Verifying Python syntax..."
python -m py_compile \
  src/synth_sleeves/version_repo.py \
  src/synth_sleeves/transition_logger.py \
  src/synth_sleeves/equity.py \
  src/synth_sleeves/paper_execution.py \
  src/synth_sleeves/db_repository.py \
  src/synth_sleeves/config_loader.py \
  src/synth_sleeves/pipeline.py \
  scripts/run_sleeve_loop_once.py

echo "[DONE] Patch 2 deployed from txt bundle."
