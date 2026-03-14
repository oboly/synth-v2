import yaml
import json
import time

from db import DB
from job_queue import *
from dataset_cache import DatasetCache
from candle_loader import load_candles
from backtest_runner import compute

def load_config():

 with open("config.yaml") as f:
  return yaml.safe_load(f)

def main():

 cfg=load_config()

 db=DB(cfg["db"])

 cache=DatasetCache(cfg["cache"]["root_dir"])

 worker=cfg["worker"]["worker_name"]

 while True:

  job=next_job(db)

  if not job:

   time.sleep(2)
   continue

  id=job["id"]

  mark_running(db,id,worker)

  try:

   params=json.loads(job["params_json"])

   asset_id=params["asset_id"]
   tf=params["tf"]
   start=params["start"]
   end=params["end"]

   path=cache.path(asset_id,tf,start,end)

   df=cache.load(path)

   if df is None:

    df=load_candles(db,asset_id,tf,start,end)

    cache.save(df,path)

   result=compute(df)

   sql="""
   INSERT INTO compute_results
   (job_id,result_json,created_ts)
   VALUES (%s,%s,NOW())
   """

   db.execute(sql,(id,json.dumps(result)))

   mark_done(db,id)

  except Exception as e:

   mark_failed(db,id,str(e))

if __name__=="__main__":
 main()


