import pandas as pd
from src.common.db import get_connection

SQL = """
SELECT
    entry_ts_utc,
    signal_family,
    reversion_state_bucket,
    next_return_4h
FROM v_reversion_extreme_low_participation_confirmed_4h
WHERE next_return_4h IS NOT NULL
"""

conn = get_connection()
df = pd.read_sql(SQL, conn)
conn.close()

df["entry_ts_utc"] = pd.to_datetime(df["entry_ts_utc"])

recent = df[df["entry_ts_utc"] >= "2026-01-01"]

print("\n=== SUMMARY ===")
print(recent.groupby("signal_family")["next_return_4h"].agg(["count","mean","median","std"]))

print("\n=== BY BUCKET ===")
print(recent.groupby(["signal_family","reversion_state_bucket"])["next_return_4h"].agg(["count","mean","median","std"]))
