from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymysql


REPO_ROOT = Path(__file__).resolve().parents[2]

SOURCE_SPECS = [
    {
        "manifest_path": REPO_ROOT / "data/external/pro_elliott_fibo/manifest/pro_fibo_reference_values_20260507.jsonl",
        "source_name": "Crypto Masterminds",
        "source_type": "PRO_EXTERNAL_REFERENCE",
        "relative_path": "manifest/pro_fibo_reference_values_20260507.jsonl",
        "method_tags": ["pro", "elliott", "fibo", "reference_values"],
        "analysis_ts": "2026-05-07 00:00:00.000000",
    },
    {
        "manifest_path": REPO_ROOT / "data/external/pro_elliott_fibo/manifest/pro_observed_flows_positioning_20260512.jsonl",
        "source_name": "PRO Observed Flows & Positioning",
        "source_type": "PRO_EXTERNAL_RESEARCH",
        "relative_path": "manifest/pro_observed_flows_positioning_20260512.jsonl",
        "method_tags": ["pro", "observed_flows", "elliott", "fibo", "narrative"],
        "analysis_ts": "2026-05-12 00:00:00.000000",
    },
]


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


def load_dotenv_best_effort() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        return


def db_config() -> DbConfig:
    load_dotenv_best_effort()
    return DbConfig(
        host=os.getenv("SYNTH_DB_HOST") or os.getenv("DB_HOST") or "127.0.0.1",
        port=int(os.getenv("SYNTH_DB_PORT") or os.getenv("DB_PORT") or "3306"),
        database=os.getenv("SYNTH_DB_NAME") or os.getenv("DB_NAME") or "synth",
        user=os.getenv("SYNTH_DB_USER") or os.getenv("DB_USER") or "root",
        password=os.getenv("SYNTH_DB_PASSWORD") or os.getenv("DB_PASSWORD") or "",
    )


def connect(config: DbConfig):
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def decimal_value(value: Any) -> Any:
    if value is None:
        return None
    return str(value)


def upsert_source(cur, spec: dict[str, Any]) -> int:
    path = spec["manifest_path"]
    if not path.exists():
        raise FileNotFoundError(path)

    now = utc_now_str()
    relative_path = spec["relative_path"]
    file_name = path.name
    file_ext = path.suffix.lower()
    file_size = path.stat().st_size
    file_sha = sha256_file(path)

    cur.execute(
        """
        INSERT INTO research_external_analysis_source (
            manifest_version,
            source_name,
            source_type,
            source_file_path,
            relative_path,
            file_name,
            file_ext,
            file_type,
            file_size_bytes,
            file_sha256,
            image_width,
            image_height,
            symbol_guess,
            pair_guess,
            exchange_guess,
            interval_guess,
            analysis_ts_guess_utc,
            method_tags_guess,
            status,
            indexed_at_utc,
            created_at_utc,
            updated_at_utc
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            NULL, NULL, NULL, NULL, NULL, NULL, %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            manifest_version = VALUES(manifest_version),
            source_name = VALUES(source_name),
            source_type = VALUES(source_type),
            source_file_path = VALUES(source_file_path),
            file_name = VALUES(file_name),
            file_ext = VALUES(file_ext),
            file_type = VALUES(file_type),
            file_size_bytes = VALUES(file_size_bytes),
            file_sha256 = VALUES(file_sha256),
            analysis_ts_guess_utc = VALUES(analysis_ts_guess_utc),
            method_tags_guess = VALUES(method_tags_guess),
            status = VALUES(status),
            indexed_at_utc = VALUES(indexed_at_utc),
            updated_at_utc = VALUES(updated_at_utc)
        """,
        (
            "external_analysis_manifest_v1",
            spec["source_name"],
            spec["source_type"],
            str(path.relative_to(REPO_ROOT)),
            relative_path,
            file_name,
            file_ext,
            "text",
            file_size,
            file_sha,
            spec["analysis_ts"],
            json.dumps(spec["method_tags"]),
            "MANUAL_NORMALIZED",
            now,
            now,
            now,
        ),
    )
    cur.execute(
        "SELECT id FROM research_external_analysis_source WHERE relative_path = %s",
        (relative_path,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"source row not found after upsert: {relative_path}")
    return int(row["id"])


def delete_existing_normalized_rows(cur, source_ids: list[int]) -> None:
    if not source_ids:
        return
    placeholders = ",".join(["%s"] * len(source_ids))
    for table in [
        "research_external_chart_observation",
        "research_external_target_level",
        "research_external_narrative_claim",
    ]:
        cur.execute(f"DELETE FROM {table} WHERE source_id IN ({placeholders})", source_ids)


def insert_narrative_claim(
    cur,
    source_id: int,
    symbol: str | None,
    claim_type: str,
    claim_text: str,
    stance_code: str | None,
    extraction_method: str = "MANUAL_TEXT",
    quality_score: str = "0.8000",
) -> None:
    now = utc_now_str()
    cur.execute(
        """
        INSERT INTO research_external_narrative_claim (
            source_id,
            symbol,
            claim_type,
            claim_text,
            stance_code,
            extraction_method,
            quality_score,
            created_at_utc,
            updated_at_utc
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            source_id,
            symbol,
            claim_type,
            claim_text,
            stance_code,
            extraction_method,
            quality_score,
            now,
            now,
        ),
    )


def insert_target_level(
    cur,
    source_id: int,
    symbol: str,
    pair: str | None,
    scenario_code: str | None,
    level_label: str,
    level_kind: str,
    fib_level: Any = None,
    wave_label: str | None = None,
    price_usd: Any = None,
    price_eur: Any = None,
    price_native: Any = None,
    native_currency_code: str | None = None,
    extraction_method: str = "MANUAL_TEXT",
    quality_score: str = "0.8000",
    notes: str | None = None,
) -> None:
    now = utc_now_str()
    cur.execute(
        """
        INSERT INTO research_external_target_level (
            source_id,
            symbol,
            pair,
            scenario_code,
            level_label,
            level_kind,
            fib_level,
            wave_label,
            price_usd,
            price_eur,
            price_native,
            native_currency_code,
            extraction_method,
            quality_score,
            notes,
            created_at_utc,
            updated_at_utc
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            source_id,
            symbol,
            pair,
            scenario_code,
            level_label,
            level_kind,
            decimal_value(fib_level),
            wave_label,
            decimal_value(price_usd),
            decimal_value(price_eur),
            decimal_value(price_native),
            native_currency_code,
            extraction_method,
            quality_score,
            notes,
            now,
            now,
        ),
    )


def insert_chart_observation(
    cur,
    source_id: int,
    symbol: str,
    pair: str | None,
    exchange: str | None,
    interval_code: str | None,
    asof_ts_utc: str | None,
    method_code: str,
    bias_code: str | None,
    structure_code: str | None,
    wave_label: str | None,
    fib_anchor_low: Any = None,
    fib_anchor_high: Any = None,
    fib_level: Any = None,
    zone_low: Any = None,
    zone_high: Any = None,
    target_price: Any = None,
    invalidation_price: Any = None,
    currency_code: str | None = None,
    extraction_method: str = "MANUAL_TEXT",
    quality_score: str = "0.7500",
    notes: str | None = None,
) -> None:
    now = utc_now_str()
    cur.execute(
        """
        INSERT INTO research_external_chart_observation (
            source_id,
            symbol,
            pair,
            exchange,
            interval_code,
            asof_ts_utc,
            method_code,
            bias_code,
            structure_code,
            wave_label,
            fib_anchor_low,
            fib_anchor_high,
            fib_level,
            zone_low,
            zone_high,
            target_price,
            invalidation_price,
            currency_code,
            extraction_method,
            quality_score,
            notes,
            created_at_utc,
            updated_at_utc
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            source_id,
            symbol,
            pair,
            exchange,
            interval_code,
            asof_ts_utc,
            method_code,
            bias_code,
            structure_code,
            wave_label,
            decimal_value(fib_anchor_low),
            decimal_value(fib_anchor_high),
            decimal_value(fib_level),
            decimal_value(zone_low),
            decimal_value(zone_high),
            decimal_value(target_price),
            decimal_value(invalidation_price),
            currency_code,
            extraction_method,
            quality_score,
            notes,
            now,
            now,
        ),
    )


def insert_range_as_bounds(
    cur,
    source_id: int,
    symbol: str,
    pair: str | None,
    scenario_code: str,
    base_label: str,
    level_kind: str,
    values: list[Any],
    native_currency_code: str = "UNSPECIFIED",
    notes: str | None = None,
) -> None:
    if len(values) != 2:
        raise ValueError(f"range must have exactly two values for {symbol}:{base_label}")
    insert_target_level(
        cur,
        source_id,
        symbol,
        pair,
        scenario_code,
        f"{base_label}_low",
        level_kind,
        price_native=values[0],
        native_currency_code=native_currency_code,
        notes=notes,
    )
    insert_target_level(
        cur,
        source_id,
        symbol,
        pair,
        scenario_code,
        f"{base_label}_high",
        level_kind,
        price_native=values[1],
        native_currency_code=native_currency_code,
        notes=notes,
    )


def load_20260507_reference_rows(cur, source_id: int, rows: list[dict[str, Any]]) -> int:
    inserted = 0
    for row in rows:
        symbol = row["asset_symbol"].upper()
        pair = row.get("market_hint")
        scenario_code = row["reference_id"]
        levels = row.get("levels", {})

        insert_narrative_claim(
            cur,
            source_id,
            symbol,
            "NARRATIVE",
            f"{symbol} external PRO structure label: {row.get('structure_label')}. Research-only; verified_truth=false; direct_signal=false.",
            "MIXED",
            quality_score="0.8500",
        )

        for key, value in levels.items():
            if key == "targets":
                for target in value:
                    label = target["label"]
                    if "range" in target:
                        insert_range_as_bounds(
                            cur,
                            source_id,
                            symbol,
                            pair,
                            scenario_code,
                            label,
                            "TARGET_ZONE_BOUND",
                            target["range"],
                            notes="External PRO target range from 2026-05-07 reference manifest.",
                        )
                        inserted += 2
                    else:
                        insert_target_level(
                            cur,
                            source_id,
                            symbol,
                            pair,
                            scenario_code,
                            label,
                            "TARGET",
                            price_native=target["value"],
                            native_currency_code="UNSPECIFIED",
                            notes="External PRO target from 2026-05-07 reference manifest.",
                        )
                        inserted += 1
            elif key.endswith("_range") or isinstance(value, list):
                insert_range_as_bounds(
                    cur,
                    source_id,
                    symbol,
                    pair,
                    scenario_code,
                    key,
                    "REFERENCE_ZONE_BOUND",
                    value,
                    notes="External PRO reference range from 2026-05-07 manifest.",
                )
                inserted += 2
            elif isinstance(value, str):
                insert_narrative_claim(
                    cur,
                    source_id,
                    symbol,
                    "NARRATIVE",
                    f"{symbol} external PRO reference metadata {key}: {value}.",
                    "MIXED",
                    quality_score="0.7500",
                )
            else:
                kind = "REFERENCE_LEVEL"
                if "break" in key or "confirmation" in key or "shoulder" in key:
                    kind = "TRIGGER_LEVEL"
                if "buy_zone" in key:
                    kind = "ENTRY_ZONE_BOUND"
                insert_target_level(
                    cur,
                    source_id,
                    symbol,
                    pair,
                    scenario_code,
                    key,
                    kind,
                    price_native=value,
                    native_currency_code="UNSPECIFIED",
                    notes="External PRO reference level from 2026-05-07 manifest.",
                )
                inserted += 1
    return inserted


def load_20260512_observed_flows_rows(cur, source_id: int, rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    claim_count = 0
    level_count = 0
    observation_count = 0

    insert_narrative_claim(
        cur,
        source_id,
        None,
        "MACRO",
        "PRO text describes early-stage rotation from BTC/ETH into select altcoins, with macro headwinds unresolved and current conditions framed as preconditions for an altcoin cycle rather than confirmation.",
        "MIXED",
        quality_score="0.7500",
    )
    claim_count += 1

    for row in rows:
        symbol = row["asset_symbol"].upper()
        pair = row.get("market_hint")
        scenario_code = row["scenario_code"]

        summary_claim = (
            f"{symbol} scenario metadata: asset_status={row.get('asset_status')}; "
            f"external_theme={row.get('external_theme')}; narrative_quality={row.get('narrative_quality')}; "
            f"risk_theme={row.get('risk_theme')}; time_horizon={row.get('time_horizon')}; "
            "research_only=true; direct_signal=false; verified_truth=false."
        )
        insert_narrative_claim(
            cur,
            source_id,
            symbol,
            "NARRATIVE",
            summary_claim,
            "MIXED",
            quality_score="0.8500",
        )
        claim_count += 1

        for claim in row.get("claims", []):
            insert_narrative_claim(
                cur,
                source_id,
                symbol,
                claim["claim_type"],
                claim["claim_text"],
                claim.get("stance_code"),
                quality_score="0.8000",
            )
            claim_count += 1

        for level in row.get("levels", []):
            insert_target_level(
                cur,
                source_id,
                symbol,
                pair,
                scenario_code,
                level["level_label"],
                level["level_kind"],
                fib_level=level.get("fib_level"),
                wave_label=level.get("wave_label"),
                price_usd=level.get("price_usd"),
                price_eur=level.get("price_eur"),
                price_native=level.get("price_native"),
                native_currency_code=level.get("native_currency_code"),
                notes=level.get("notes"),
            )
            level_count += 1

        for obs in row.get("observations", []):
            insert_chart_observation(
                cur,
                source_id,
                symbol,
                obs.get("pair") or pair,
                obs.get("exchange"),
                obs.get("interval_code"),
                obs.get("asof_ts_utc"),
                obs["method_code"],
                obs.get("bias_code"),
                obs.get("structure_code"),
                obs.get("wave_label"),
                fib_anchor_low=obs.get("fib_anchor_low"),
                fib_anchor_high=obs.get("fib_anchor_high"),
                fib_level=obs.get("fib_level"),
                zone_low=obs.get("zone_low"),
                zone_high=obs.get("zone_high"),
                target_price=obs.get("target_price"),
                invalidation_price=obs.get("invalidation_price"),
                currency_code=obs.get("currency_code"),
                notes=obs.get("notes"),
            )
            observation_count += 1

    return claim_count, level_count, observation_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-db", action="store_true", help="Actually write rows to DB. Default is dry-run.")
    args = parser.parse_args()

    config = db_config()
    print(
        f"DB host={config.host} port={config.port} db={config.database} "
        f"user={config.user} password=<{ 'set' if config.password else 'empty' }>"
    )

    source_rows = {spec["relative_path"]: read_jsonl(spec["manifest_path"]) for spec in SOURCE_SPECS}
    for rel_path, rows in source_rows.items():
        print(f"manifest={rel_path} rows={len(rows)}")

    if not args.write_db:
        print("DRY_RUN: no DB writes")
        return 0

    with connect(config) as conn:
        try:
            with conn.cursor() as cur:
                source_ids: dict[str, int] = {}
                for spec in SOURCE_SPECS:
                    source_ids[spec["relative_path"]] = upsert_source(cur, spec)

                delete_existing_normalized_rows(cur, list(source_ids.values()))

                count_20260507 = load_20260507_reference_rows(
                    cur,
                    source_ids["manifest/pro_fibo_reference_values_20260507.jsonl"],
                    source_rows["manifest/pro_fibo_reference_values_20260507.jsonl"],
                )

                claims_20260512, levels_20260512, observations_20260512 = load_20260512_observed_flows_rows(
                    cur,
                    source_ids["manifest/pro_observed_flows_positioning_20260512.jsonl"],
                    source_rows["manifest/pro_observed_flows_positioning_20260512.jsonl"],
                )

                conn.commit()

                print("WRITE_OK")
                print(f"source_ids={source_ids}")
                print(f"target_levels_20260507={count_20260507}")
                print(f"claims_20260512={claims_20260512}")
                print(f"target_levels_20260512={levels_20260512}")
                print(f"chart_observations_20260512={observations_20260512}")
        except Exception:
            conn.rollback()
            raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
