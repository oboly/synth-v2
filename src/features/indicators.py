import pandas as pd

def ema(series,span):

 return series.ewm(span=span,adjust=False).mean()

def atr(df,period=14):

 high=df["high"]
 low=df["low"]
 close=df["close"]

 prev_close=close.shift(1)

 tr=pd.concat([
  high-low,
  (high-prev_close).abs(),
  (low-prev_close).abs()
 ],axis=1).max(axis=1)

 return tr.rolling(period).mean()


