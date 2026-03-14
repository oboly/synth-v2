from pathlib import Path
from datetime import datetime, timezone
from synth.db.db import db_cursor

UTC = timezone.utc

def apply_sql_file(path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with db_cursor() as (_conn, cur):
        for stmt in statements:
            cur.execute(stmt)

def migrate() -> None:
    mig_dir = Path(__file__).resolve().parents[1] / "migrations"
    files = sorted(mig_dir.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No migration files found in {mig_dir}")
    for f in files:
        apply_sql_file(f)
    print(f"Migrations applied: {len(files)}")

if __name__ == "__main__":
    migrate()