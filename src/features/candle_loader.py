import pandas as pd

def load_candles(db,asset_id,tf,start,end):

 sql="""
 SELECT
 start_ts,
 open,
 high,
 low,
 close,
 volume
 FROM candle
 WHERE asset_id=%s
 AND tf=%s
 AND start_ts >= %s
 AND start_ts < %s
 ORDER BY start_ts
 """

 rows=db.fetch_all(sql,(asset_id,tf,start,end))

 df=pd.DataFrame(rows)

 if df.empty:
  return df

 df["start_ts"]=pd.to_datetime(df["start_ts"],utc=True)

 df=df.set_index("start_ts")

 return df


