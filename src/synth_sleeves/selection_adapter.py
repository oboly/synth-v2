"""
SYNTH v2
Module: synth_sleeves.selection_adapter
Purpose:
    Read real latest selection-state rows from the DB and map them to AgentSignalRow.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from src.synth_sleeves.models import AgentSignalRow
from src.synth_sleeves.selection_semantics import derive_canonical_selection_state


@dataclass(slots=True)
class TableShape:
    name: str
    columns: set[str]


class SelectionStateAdapter:
    def __init__(self, connection_params: dict[str, Any]) -> None:
        self._connection_params = connection_params

    def _connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            cursorclass=DictCursor,
            autocommit=True,
            charset="utf8mb4",
            **self._connection_params,
        )

    def _get_current_database(self) -> str:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DATABASE() AS db_name")
                row = cur.fetchone()
        return str(row["db_name"])

    def _get_table_shape(self, object_name: str) -> TableShape | None:
        db_name = self._get_current_database()

        sql = """
        SELECT COLUMN_NAME
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (db_name, object_name))
                rows = cur.fetchall()

        if not rows:
            return None

        return TableShape(
            name=object_name,
            columns={str(r["COLUMN_NAME"]) for r in rows},
        )

    @staticmethod
    def _pick(shape: TableShape | None, candidates: list[str]) -> str | None:
        if shape is None:
            return None
        for c in candidates:
            if c in shape.columns:
                return c
        return None

    @staticmethod
    def _dec(v: Any, default: Decimal = Decimal("0")) -> Decimal:
        if v is None:
            return default
        return Decimal(str(v))

    def _asset_map(self) -> dict[int, str]:
        shape = self._get_table_shape("asset")
        if shape is None:
            return {}

        id_col = self._pick(shape, ["asset_id", "id"])
        sym_col = self._pick(shape, ["symbol", "token"])

        if not id_col or not sym_col:
            return {}

        sql = f"SELECT {id_col} AS id, {sym_col} AS sym FROM asset"

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        return {int(r["id"]): str(r["sym"]) for r in rows}

    def _prices(self) -> dict[int, Decimal]:
        shape = self._get_table_shape("v_latest_price_eur")
        if shape is None:
            return {}

        token_col = self._pick(shape, ["token"])
        tf_col = self._pick(shape, ["tf"])
        price_col = self._pick(shape, ["current_price_eur"])

        if not token_col or not tf_col or not price_col:
            return {}

        asset_map = self._asset_map()
        asset_by_symbol = {v: k for k, v in asset_map.items()}

        sql = f"""
        SELECT {token_col} AS token, {tf_col} AS tf, {price_col} AS price
        FROM v_latest_price_eur
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        tf_priority = {"1h": 1, "4h": 2, "1d": 3}
        best: dict[int, tuple[int, Decimal]] = {}

        for r in rows:
            token = r["token"]
            tf = r["tf"]
            price = r["price"]

            if token is None or price is None:
                continue

            asset_id = asset_by_symbol.get(str(token))
            if asset_id is None:
                continue

            prio = tf_priority.get(str(tf), 999)
            val = self._dec(price)

            if asset_id not in best or prio < best[asset_id][0]:
                best[asset_id] = (prio, val)

        return {aid: v for aid, (_, v) in best.items()}

    def _relative_strength(self) -> dict[int, dict[str, Decimal]]:
        shape = self._get_table_shape("v_latest_relative_strength")
        if shape is None:
            return {}

        sql = """
        SELECT
            asset_id,
            rs_return_7d_pct,
            rs_rank_7d,
            rs_rank_pct_7d,
            rs_zscore_7d,
            rs_return_14d_pct,
            rs_rank_14d,
            rs_rank_pct_14d,
            rs_zscore_14d
        FROM v_latest_relative_strength
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        out: dict[int, dict[str, Decimal]] = {}
        for r in rows:
            asset_id = int(r["asset_id"])
            out[asset_id] = {
                "rs_return_7d_pct": self._dec(r["rs_return_7d_pct"]),
                "rs_rank_7d": self._dec(r["rs_rank_7d"]),
                "rs_rank_pct_7d": self._dec(r["rs_rank_pct_7d"]),
                "rs_zscore_7d": self._dec(r["rs_zscore_7d"]),
                "rs_return_14d_pct": self._dec(r["rs_return_14d_pct"]),
                "rs_rank_14d": self._dec(r["rs_rank_14d"]),
                "rs_rank_pct_14d": self._dec(r["rs_rank_pct_14d"]),
                "rs_zscore_14d": self._dec(r["rs_zscore_14d"]),
            }
        return out

    def _momentum_persistence(self) -> dict[int, dict[str, Decimal]]:
        shape = self._get_table_shape("v_latest_momentum_persistence")
        if shape is None:
            return {}

        sql = """
        SELECT
            asset_id,
            mp_green_ratio_7d,
            mp_mean_daily_return_7d_pct,
            mp_std_daily_return_7d_pct,
            mp_persistence_score_7d,
            mp_green_ratio_14d,
            mp_mean_daily_return_14d_pct,
            mp_std_daily_return_14d_pct,
            mp_persistence_score_14d
        FROM v_latest_momentum_persistence
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        out: dict[int, dict[str, Decimal]] = {}
        for r in rows:
            asset_id = int(r["asset_id"])
            out[asset_id] = {
                "mp_green_ratio_7d": self._dec(r["mp_green_ratio_7d"]),
                "mp_mean_daily_return_7d_pct": self._dec(r["mp_mean_daily_return_7d_pct"]),
                "mp_std_daily_return_7d_pct": self._dec(r["mp_std_daily_return_7d_pct"]),
                "mp_persistence_score_7d": self._dec(r["mp_persistence_score_7d"]),
                "mp_green_ratio_14d": self._dec(r["mp_green_ratio_14d"]),
                "mp_mean_daily_return_14d_pct": self._dec(r["mp_mean_daily_return_14d_pct"]),
                "mp_std_daily_return_14d_pct": self._dec(r["mp_std_daily_return_14d_pct"]),
                "mp_persistence_score_14d": self._dec(r["mp_persistence_score_14d"]),
            }
        return out

    def _latest_selection(self) -> list[dict[str, Any]]:
        shape = self._get_table_shape("selection_state")
        if shape is None:
            raise RuntimeError("selection_state missing")

        aid = self._pick(shape, ["asset_id"])
        ts = self._pick(shape, ["state_ts_utc", "created_ts_utc"])

        sql = f"""
        SELECT s.*
        FROM selection_state s
        JOIN (
            SELECT {aid} aid, MAX({ts}) ts
            FROM selection_state
            GROUP BY {aid}
        ) x
        ON s.{aid} = x.aid AND s.{ts} = x.ts
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchall()

    def load_agent_signal_rows(self) -> list[AgentSignalRow]:
        rows = self._latest_selection()
        asset_map = self._asset_map()
        prices = self._prices()
        rs_map = self._relative_strength()
        mp_map = self._momentum_persistence()

        shape = self._get_table_shape("selection_state")

        aid = self._pick(shape, ["asset_id"])
        state_col = self._pick(shape, ["selection_state"])
        score_col = self._pick(shape, ["selection_score"])
        bias_col = self._pick(shape, ["selection_bias"])

        out: list[AgentSignalRow] = []

        for r in rows:
            asset_id = int(r[aid])

            raw_state = str(r.get(state_col) or "WATCH")
            score = self._dec(r.get(score_col))
            raw_bias = str(r.get(bias_col) or "WATCH")

            canonical = derive_canonical_selection_state(
                raw_selection_state=raw_state,
                raw_selection_bias=raw_bias,
                selection_score=score,
            )

            rs = rs_map.get(asset_id, {})
            mp = mp_map.get(asset_id, {})

            out.append(
                AgentSignalRow(
                    asset_id=asset_id,
                    symbol=asset_map.get(asset_id, f"id_{asset_id}"),
                    selection_state=canonical,
                    selection_score=score,
                    selection_bias=raw_bias,
                    regime_ok=True,
                    htf_reject=False,
                    liquidity_ok=True,
                    latest_price_eur=prices.get(asset_id, Decimal("0")),
                    extra={
                        "raw_selection_state": raw_state,
                        "raw_selection_bias": raw_bias,
                        "rs_return_7d_pct": rs.get("rs_return_7d_pct", Decimal("0")),
                        "rs_rank_7d": rs.get("rs_rank_7d", Decimal("0")),
                        "rs_rank_pct_7d": rs.get("rs_rank_pct_7d", Decimal("0")),
                        "rs_zscore_7d": rs.get("rs_zscore_7d", Decimal("0")),
                        "rs_return_14d_pct": rs.get("rs_return_14d_pct", Decimal("0")),
                        "rs_rank_14d": rs.get("rs_rank_14d", Decimal("0")),
                        "rs_rank_pct_14d": rs.get("rs_rank_pct_14d", Decimal("0")),
                        "rs_zscore_14d": rs.get("rs_zscore_14d", Decimal("0")),
                        "mp_green_ratio_7d": mp.get("mp_green_ratio_7d", Decimal("0")),
                        "mp_mean_daily_return_7d_pct": mp.get("mp_mean_daily_return_7d_pct", Decimal("0")),
                        "mp_std_daily_return_7d_pct": mp.get("mp_std_daily_return_7d_pct", Decimal("0")),
                        "mp_persistence_score_7d": mp.get("mp_persistence_score_7d", Decimal("0")),
                        "mp_green_ratio_14d": mp.get("mp_green_ratio_14d", Decimal("0")),
                        "mp_mean_daily_return_14d_pct": mp.get("mp_mean_daily_return_14d_pct", Decimal("0")),
                        "mp_std_daily_return_14d_pct": mp.get("mp_std_daily_return_14d_pct", Decimal("0")),
                        "mp_persistence_score_14d": mp.get("mp_persistence_score_14d", Decimal("0")),
                    },
                )
            )

        return out
