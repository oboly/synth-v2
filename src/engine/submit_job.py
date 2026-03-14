import json
import yaml
import argparse

from db import DB
from job_queue import submit_job

def load_config():

 with open("config.yaml") as f:
  return yaml.safe_load(f)

def main():

 parser=argparse.ArgumentParser()

 parser.add_argument("--type",required=True)
 parser.add_argument("--params",required=True)

 args=parser.parse_args()

 cfg=load_config()

 db=DB(cfg["db"])

 job_id=submit_job(
  db,
  args.type,
  json.loads(args.params)
 )

 print(job_id)

if __name__=="__main__":
 main()
