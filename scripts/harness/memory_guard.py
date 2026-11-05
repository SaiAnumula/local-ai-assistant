#!/usr/bin/env python3
"""Memory guard for benchmark runs on a shared desktop.

Refuses to start while the production Ollama instance has a model loaded, then runs COMMAND and
samples RAM, swap, memory PSI, and VRAM every 2 seconds. It kills the command and unloads the
benchmark instance's models if available RAM drops below 6.25 GiB, memory PSI avg10 stays above 15
for 20 seconds, or the run passes 40 minutes. Production is never touched.

Usage: memory_guard.py LABEL COMMAND [ARGS...]
Env:   PROD_OLLAMA, BENCH_OLLAMA (base URLs), BENCH_OUT_DIR (default: results/raw)"""
import subprocess,time,json,pathlib,sys,os,signal,urllib.request
root=pathlib.Path(os.environ.get('BENCH_OUT_DIR','results/raw'));root.mkdir(parents=True,exist_ok=True);PROD=os.environ.get('PROD_OLLAMA','http://127.0.0.1:11437');BENCH=os.environ.get('BENCH_OLLAMA','http://127.0.0.1:11441'); label=sys.argv[1]; samples=[];reason=None
with urllib.request.urlopen(PROD+'/api/ps',timeout=3) as r: production=json.load(r)['models']
if production:
 print('BLOCKED: production model still resident',flush=True);sys.exit(3)
p=subprocess.Popen(sys.argv[2:],start_new_session=True)
start=time.monotonic();high=0
while p.poll() is None:
 m={s.split(':')[0]:int(s.split()[1]) for s in pathlib.Path('/proc/meminfo').read_text().splitlines() if len(s.split())>1 and s.split()[1].isdigit()}
 v={s.split()[0]:int(s.split()[1]) for s in pathlib.Path('/proc/vmstat').read_text().splitlines()}
 psi=pathlib.Path('/proc/pressure/memory').read_text();avg=float(psi.split('avg10=')[1].split()[0]); high=high+1 if avg>15 else 0
 row={'time':time.time(),'available_kib':m['MemAvailable'],'swap_free_kib':m['SwapFree'],'pswpin':v['pswpin'],'pswpout':v['pswpout'],'psi':psi,'vram_used':int(pathlib.Path('/sys/class/drm/card1/device/mem_info_vram_used').read_text())}
 try:
  with urllib.request.urlopen(BENCH+'/api/ps',timeout=1) as r:row['models']=json.load(r)['models']
 except Exception:pass
 samples.append(row)
 if m['MemAvailable']<6.25*1024**2:reason='available RAM below 6.25 GiB'
 if high>=10:reason='memory PSI avg10 above 15 for 20 seconds'
 if time.monotonic()-start>2400:reason='40 minute cap'
 if reason:
  os.killpg(p.pid,signal.SIGTERM)
  try:p.wait(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL)
  # Abort the benchmark endpoint only. Production is never addressed.
  try:
   with urllib.request.urlopen(BENCH+'/api/ps',timeout=2) as r:models=json.load(r)['models']
   for model in models:
    req=urllib.request.Request(BENCH+'/api/generate',data=json.dumps({'model':model['name'],'keep_alive':0}).encode(),headers={'Content-Type':'application/json'})
    urllib.request.urlopen(req,timeout=10).close()
  except Exception:pass
  break
 time.sleep(2)
(root/(label+'-guard.json')).write_text(json.dumps({'reason':reason,'exit':p.wait(),'wall':time.monotonic()-start,'samples':samples},indent=2))
print(json.dumps({'guard':label,'stop_reason':reason,'exit':p.returncode}),flush=True)
sys.exit(p.returncode or (2 if reason else 0))
