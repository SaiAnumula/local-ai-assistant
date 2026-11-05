#!/usr/bin/env python3
"""Runs scripts/benchmark_ollama.sh and samples /api/ps, /proc/meminfo, memory PSI, and amdgpu VRAM use
once per second while it runs.
Usage: run_benchmark.py MODEL PORT THINK(true|false) LABEL [NUM_CTX]

Writes JSON to $BENCH_OUT_DIR (default: results/raw)."""
import sys,subprocess,time,json,urllib.request,pathlib
import os;OUT=pathlib.Path(os.environ.get('BENCH_OUT_DIR','results/raw'));OUT.mkdir(parents=True,exist_ok=True)
model,port,think,label=sys.argv[1:5]
num_ctx=sys.argv[5] if len(sys.argv)>5 else '131072'
root=OUT
cmd=['bash',str(pathlib.Path(__file__).resolve().parents[1]/'benchmark_ollama.sh'),'--model',model,'--endpoint','http://127.0.0.1:'+port,'--runs','3','--num-ctx',num_ctx,'--think',think,'--output',str(root/(label+'.csv'))]
p=subprocess.Popen(cmd)
samples=[]
while p.poll() is None:
 s={'time':time.time()}
 try:
  with urllib.request.urlopen('http://127.0.0.1:'+port+'/api/ps',timeout=2) as r:
   s['models']=[{k:m.get(k) for k in ('name','size','size_vram','context_length')} for m in json.load(r).get('models',[])]
  mem={line.split(':')[0]:int(line.split()[1]) for line in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(line.split())>1 and line.split()[1].isdigit()}
  s['memory_kib']={k:mem[k] for k in ('MemTotal','MemAvailable','SwapTotal','SwapFree')}
  s['memory_pressure']=pathlib.Path('/proc/pressure/memory').read_text()
  s['vram_used_bytes']=int(pathlib.Path('/sys/class/drm/card1/device/mem_info_vram_used').read_text())
 except Exception as e:s['telemetry_error']=type(e).__name__
 samples.append(s)
 time.sleep(1)
(root/(label+'-telemetry.json')).write_text(json.dumps(samples,indent=2))
print('benchmark_exit',p.returncode,'telemetry_samples',len(samples),flush=True)
sys.exit(p.returncode)
