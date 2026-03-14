from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from synth.aplus.parser import parse_aplus_text
from synth.aplus.repository import APlusRepository
from synth.db.connection import get_connection


def main() -> None:
    raw_text = Path("data/aplus/latest_aplus.txt").read_text(encoding="utf-8")

    doc = parse_aplus_text(
        raw_text=raw_text,
        created_ts=datetime.now(timezone.utc),
        source_name="chatgpt_a_plus",
        model_variant="8.5D_breathline",
        prompt_label="manual_paste",
    )

    conn = get_connection()
    try:
        repo = APlusRepository(conn)
        run_id = repo.store_document(doc)
        conn.commit()
        print(f"Stored A+ run_id={run_id} assets={len(doc.assets)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
