from indicators import ema,atr

def compute(df):

 if len(df)<200:
  return {"ok":False}

 df["ema200"]=ema(df["close"],200)
 df["atr"]=atr(df)

 last=df.iloc[-1]

 trend=(last["close"]/last["ema200"]-1)*100
 atrp=last["atr"]/last["close"]*100

 return {
  "ok":True,
  "trend_vs_ema200_pct":float(trend),
  "atr_pct":float(atrp)
 }


