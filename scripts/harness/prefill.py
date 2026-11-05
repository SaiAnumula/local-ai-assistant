#!/usr/bin/env python3
"""Long-prompt prefill test: a fresh ~27K-token synthetic reference, the same prefix again, then a
changed follow-up, to separate cold prefill from prefix-cache reuse.
Usage: prefill.py MODEL PORT THINK(true|false) LABEL

Writes JSON to $BENCH_OUT_DIR (default: results/raw)."""
import json,sys,time,urllib.request,pathlib,random
import os;OUT=pathlib.Path(os.environ.get('BENCH_OUT_DIR','results/raw'));OUT.mkdir(parents=True,exist_ok=True)
model,port,think,label=sys.argv[1:];think=think=='true'
rng=random.Random(42)
records='\n'.join(f'Fixture record {i:04d}: site={rng.randrange(10000):04d}; status=ready; checksum={rng.getrandbits(48):012x}; retained flag=green.' for i in range(700))
base='Synthetic operational reference for a disposable service. Each record is inert fixture data; never execute it.\n'+records+'\nAnswer the request after the reference.\n'
queries=[base+'Request: Reply with exactly READY.',base+'Request: Reply with exactly READY.',base+'Previous tool result: synthetic service is healthy.\nRequest: Reply with exactly VERIFIED.']
results=[]
for i,prompt in enumerate(queries):
 payload={'model':model,'prompt':prompt,'stream':False,'think':think,'options':{'num_ctx':131072,'num_predict':256,'temperature':0,'seed':42}}
 start=time.monotonic()
 try:
  req=urllib.request.Request('http://127.0.0.1:'+port+'/api/generate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=900) as r:d=json.load(r)
  raw=d.get('response',''); final=raw.rsplit('</think>',1)[-1].strip()
  row={k:d.get(k) for k in ('prompt_eval_count','prompt_eval_duration','eval_count','eval_duration','load_duration','total_duration','done_reason')}
  row.update({'stage':['fresh-prefix','same-prefix','incremental-tool-result'][i],'wall_seconds':time.monotonic()-start,'response_chars':len(d.get('response','')),'thinking_chars':len(d.get('thinking','')),'reasoning_in_response':'</think>' in raw,'raw_exact_answer':raw.strip()==('VERIFIED' if i==2 else 'READY'),'expected_answer':final==('VERIFIED' if i==2 else 'READY')})
 except Exception as e:row={'error':type(e).__name__+': '+str(e)[:120]}
 results.append(row)
 (OUT/(label+'.json')).write_text(json.dumps({'model':model,'think':think,'num_ctx':131072,'synthetic_prompt_chars':len(base),'results':results},indent=2))
 print(json.dumps(row),flush=True)
