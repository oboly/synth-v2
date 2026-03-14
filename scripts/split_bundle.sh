python3 - << 'PY'
from pathlib import Path

bundle="synth_compute_bundle.txt"
outdir="compute"

Path(outdir).mkdir(exist_ok=True)

current=None
buf=[]

for line in open(bundle):
    if line.startswith("===== FILE:"):
        if current:
            Path(outdir,current).write_text("".join(buf))
        current=line.split(":")[1].strip().replace("=====","").strip()
        buf=[]
    else:
        buf.append(line)

if current:
    Path(outdir,current).write_text("".join(buf))

print("Compute bundle extracted.")
PY
