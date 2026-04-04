from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import argparse
import sys

from dotenv import load_dotenv

from src.common.db import get_db_connection


OUTPUT_DIR = Path("data/aplus_prompt_out")


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_filename(source_name: str, mode_name: str, scope_name: str) -> str:
    ts = utc_now().strftime("%Y-%m-%dT%H%M%SZ")
    return f"{ts}_{source_name}_{mode_name}_{scope_name}.txt"


def load_enabled_tokens(conn) -> list[str]:
    sql = """
    SELECT symbol
    FROM asset
    WHERE is_enabled = 1
    ORDER BY symbol
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    tokens: list[str] = []

    for row in rows:
        if isinstance(row, dict):
            tokens.append(str(row["symbol"]).upper())
        else:
            tokens.append(str(row[0]).upper())

    return tokens


def load_template(
    conn,
    *,
    template_type: str,
    template_name: str | None = None,
) -> dict[str, str]:
    if template_name:
        sql = """
        SELECT template_name, body_text
        FROM prompt_template
        WHERE template_type = %s
          AND template_name = %s
          AND is_active = 1
        ORDER BY version_num DESC, created_ts_utc DESC
        LIMIT 1
        """
        params = (template_type, template_name)
    else:
        sql = """
        SELECT template_name, body_text
        FROM prompt_template
        WHERE template_type = %s
          AND is_active = 1
        ORDER BY version_num DESC, created_ts_utc DESC
        LIMIT 1
        """
        params = (template_type,)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

    if not row:
        raise RuntimeError(
            f"No active prompt_template found for template_type={template_type}"
            + (f", template_name={template_name}" if template_name else "")
        )

    if isinstance(row, dict):
        return {
            "template_name": str(row["template_name"]),
            "body_text": str(row["body_text"]),
        }

    return {
        "template_name": str(row[0]),
        "body_text": str(row[1]),
    }


def render_token_list(tokens: list[str]) -> str:
    return "\n".join(tokens)


def render_prompt(template_body: str, tokens: list[str]) -> str:
    token_block = render_token_list(tokens)
    return template_body.replace("{{TOKEN_LIST}}", token_block)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write A+ prompt txt file from DB template + DB token selection"
    )
    parser.add_argument("--template-type", default="APLUS_CODEX")
    parser.add_argument("--template-name", default=None)
    parser.add_argument("--source-name", default="aplus")
    parser.add_argument("--mode-name", default="codex")
    parser.add_argument("--scope-name", default="portfolio")
    parser.add_argument("--stdout", action="store_true")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    conn = get_db_connection()

    try:
        tokens = load_enabled_tokens(conn)
        if not tokens:
            raise RuntimeError("No tokens found with is_enabled = 1")

        template = load_template(
            conn,
            template_type=args.template_type,
            template_name=args.template_name,
        )

        rendered = render_prompt(template["body_text"], tokens)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        filename = make_filename(
            source_name=args.source_name,
            mode_name=args.mode_name,
            scope_name=args.scope_name,
        )
        output_path = OUTPUT_DIR / filename
        output_path.write_text(rendered, encoding="utf-8")

        print(f"[DONE] wrote prompt file: {output_path}")
        print(f"[INFO] template_name={template['template_name']}")
        print(f"[INFO] token_count={len(tokens)}")

        if args.stdout:
            print("\n--- PROMPT START ---\n")
            print(rendered)
            print("\n--- PROMPT END ---")

        return 0

    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
