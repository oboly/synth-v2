from pathlib import Path
import pandas as pd

class DatasetCache:

 def __init__(self,root):

  self.root=Path(root)
  self.root.mkdir(parents=True,exist_ok=True)

 def path(self,asset_id,tf,start,end):

  p=self.root/str(asset_id)/tf
  p.mkdir(parents=True,exist_ok=True)

  return p/f"{start}_{end}.parquet"

 def load(self,path):

  if path.exists():
   return pd.read_parquet(path)

  return None

 def save(self,df,path):

  df.to_parquet(path)


