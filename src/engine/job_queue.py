import json
from datetime import datetime

def now():

 return datetime.utcnow()

def submit_job(db,job_type,params):

 sql="""
 INSERT INTO compute_jobs
 (job_type,params_json,created_ts)
 VALUES (%s,%s,%s)
 """

 return db.execute(sql,(job_type,json.dumps(params),now()))

def next_job(db):

 sql="""
 SELECT *
 FROM compute_jobs
 WHERE status='pending'
 ORDER BY created_ts
 LIMIT 1
 """

 return db.fetch_one(sql)

def mark_running(db,id,worker):

 sql="""
 UPDATE compute_jobs
 SET status='running',
 started_ts=%s,
 locked_by=%s
 WHERE id=%s
 """

 db.execute(sql,(now(),worker,id))

def mark_done(db,id):

 sql="""
 UPDATE compute_jobs
 SET status='succeeded',
 finished_ts=%s
 WHERE id=%s
 """

 db.execute(sql,(now(),id))

def mark_failed(db,id,error):

 sql="""
 UPDATE compute_jobs
 SET status='failed',
 last_error=%s
 WHERE id=%s
 """

 db.execute(sql,(str(error),id))


