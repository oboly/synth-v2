import sys
from pathlib import Path

# Ensure the project root is always the first entry on sys.path so that
# `src.*` imports resolve to this repository, not the sibling synth-v2 repo
# that shares the same package namespace.
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
