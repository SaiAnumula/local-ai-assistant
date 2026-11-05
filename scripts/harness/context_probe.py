#!/usr/bin/env python3
"""Near-window recall probe: places three anchor codes at the start, middle, and end of a ~115K-token
synthetic reference and checks that the model returns all three.
Usage: context_probe.py MODEL PORT LABEL

Writes JSON to $BENCH_OUT_DIR (default: results/raw)."""
import json,sys,time,urllib.request,pathlib,random,re
import os;OUT=pathlib.Path(os.environ.get('BENCH_OUT_DIR','results/raw'));OUT.mkdir(parents=True,exist_ok=True)
model,port,label=sys.argv[1:];rng=random.Random(617)
rows=[]
for i in range(3000):
 if i in (0,1500,2999):
  name,value={0:('start','ALDER-4821'),1500:('middle','BRONZE-7395'),2999:('end','CEDAR-2608')}[i]
  rows.append(f'ANCHOR {name}: {value}. This exact anchor code is the required lookup value.')
 rows.append(f'Fixture record {i:04d}: site={rng.randrange(10000):04d}; status=ready; checksum={rng.getrandbits(48):012x}; retained flag=green.')
prompt='Read this inert synthetic reference. Keep the three ANCHOR codes for a lookup at the end.\n'+'\n'.join(rows)+'\nReturn only a JSON object with keys start, middle, end and the exact respective ANCHOR codes. Do not use tools.'
payload={'model':model,'prompt':prompt,'stream':False,'think':False,'options':{'num_ctx':131072,'num_predict':256,'temperature':0,'seed':42}}
start=time.monotonic()
req=urllib.request.Request('http://127.0.0.1:'+port+'/api/generate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(req,timeout=1800) as r:d=json.load(r)
 content=d.get('response',''); row={k:d.get(k) for k in ('prompt_eval_count','prompt_eval_duration','eval_count','eval_duration','total_duration','load_duration','done_reason')}
 row.update({'wall_seconds':time.monotonic()-start,'anchors_recalled':{k:v in content for k,v in {'start':'ALDER-4821','middle':'BRONZE-7395','end':'CEDAR-2608'}.items()},'response_chars':len(content),'input_chars':len(prompt)})
except Exception as e:row={'error':type(e).__name__+': '+str(e)[:200],'wall_seconds':time.monotonic()-start}
(OUT/(label+'.json')).write_text(json.dumps({'model':model,'num_ctx':131072,'think':False,'synthetic':True,'result':row},indent=2))
print(json.dumps(row),flush=True)
