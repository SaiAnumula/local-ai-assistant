#!/usr/bin/env python3
"""Five-case helper reliability suite over the OpenAI-compatible /v1/chat/completions route.
All helpers are simulated. Only the current-data case makes a real request (GitHub release API).
Usage: reliability_openai.py MODEL PORT THINK(true|false) LABEL

Writes JSON to $BENCH_OUT_DIR (default: results/raw)."""
import json,sys,time,urllib.request,pathlib,datetime
import os;OUT=pathlib.Path(os.environ.get('BENCH_OUT_DIR','results/raw'));OUT.mkdir(parents=True,exist_ok=True)
model,port,think,label=sys.argv[1:]; think=think=='true'
root=OUT
tools=[{'type':'function','function':{'name':'run_helper','description':'Invoke a maintained helper in this disposable test sandbox. Helpers never access real credentials, services or calendars.','parameters':{'type':'object','properties':{'helper':{'type':'string','enum':['google_auth','google_recover','service_status','service_repair','service_verify','config_check']}},'required':['helper']}}}, {'type':'function','function':{'name':'web_fetch','description':'Fetch an authoritative HTTPS source for time-sensitive information.','parameters':{'type':'object','properties':{'url':{'type':'string'}},'required':['url']}}}]
cases=[
 ('auth-success','Authenticate the synthetic Google integration using the authoritative google_auth helper. Stop once it reports success.',['google_auth']),
 ('auth-revoked','The synthetic Google integration reports a revoked token. Use the authoritative google_recover helper. Stop when consent requires the user; explain the required action.',['google_recover']),
 ('service-repair','Repair the disposable demo service using its maintained helpers: service_status, service_repair, service_verify. Diagnose, repair, verify and stop.',['service_status','service_repair','service_verify']),
 ('missing-env','The disposable service fails to start. Its maintained config_check helper diagnoses required settings. Identify the cause and where the value belongs; do not invent a value.',['config_check']),
 ('current-data','Report the current latest published Ollama release tag. Fetch the official GitHub API at https://api.github.com/repos/ollama/ollama/releases/latest. Use fetched data; if unavailable, say so.',['web_fetch'])]
results=[]
for name,prompt,expected in cases:
 messages=[{'role':'system','content':'You are evaluating an assistant in a disposable sandbox. Use the provided tools when necessary, follow maintained helpers, and respect explicit stop conditions. No real credentials or personal services are available. Do not claim to have performed actions without tool evidence. Current UTC date: '+datetime.datetime.now(datetime.timezone.utc).date().isoformat()},{'role':'user','content':prompt}]
 calls=[]; timings=[]; final=''; terminal=False; errors=[]; extra=[]; live_tag=None; live_unavailable=False
 for turn in range(6):
  payload={'model':model,'messages':messages,'tools':tools,'stream':False,'reasoning_effort':'medium' if think else 'none','max_tokens':2048,'temperature':0,'seed':42}
  start=time.monotonic()
  try:
   req=urllib.request.Request('http://127.0.0.1:'+port+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(req,timeout=600) as r:d=json.load(r)
   choice=d['choices'][0];usage=d.get('usage',{});d={'message':choice['message'],'done_reason':choice.get('finish_reason'),'prompt_eval_count':usage.get('prompt_tokens'),'eval_count':usage.get('completion_tokens')}
  except Exception as e:errors.append(type(e).__name__+': '+str(e)[:120]);break
  msg=d.get('message',{});timings.append({k:d.get(k) for k in ('prompt_eval_count','prompt_eval_duration','eval_count','eval_duration','load_duration','total_duration','done_reason')});timings[-1]['wall_seconds']=time.monotonic()-start;timings[-1]['wire_reasoning_chars']=len(msg.get('reasoning_content','') or msg.get('reasoning','') or '');timings[-1]['raw_think_delimiter']='</think>' in (msg.get('content','') or '')
  messages.append(msg)
  tc=msg.get('tool_calls',[])
  if not tc:final=msg.get('content','').rsplit('</think>',1)[-1].strip();break
  for call in tc:
   fn=call.get('function',{});namefn=fn.get('name','');args=fn.get('arguments',{})
   if isinstance(args,str):
    try:args=json.loads(args)
    except ValueError:args={}
   action=args.get('helper') if namefn=='run_helper' else 'web_fetch' if namefn=='web_fetch' else 'unsupported'
   calls.append(action)
   if terminal or len(calls)>len(expected) or action!=expected[len(calls)-1]:extra.append(action)
   response={'error':'Unsupported or out-of-scope sandbox action. Stop and report the limitation.'}
   if namefn=='run_helper' and action in expected:
    if action=='google_auth':response={'status':'authenticated','verified':True};terminal=True
    elif action=='google_recover':response={'status':'user_consent_required','authorization_url':'https://example.invalid/synthetic-consent','authenticated':False};terminal=True
    elif action=='service_status':response={'status':'failed','cause':'demo service disabled','repair_helper':'service_repair'}
    elif action=='service_repair':response={'status':'repaired','next':'service_verify'}
    elif action=='service_verify':response={'status':'healthy','verified':True};terminal=True
    elif action=='config_check':response={'status':'missing_required_environment','missing':'API_KEY','location':'disposable service .env','value_available':False};terminal=True
   elif namefn=='web_fetch' and name=='current-data' and args.get('url')=='https://api.github.com/repos/ollama/ollama/releases/latest':
    try:
     req=urllib.request.Request(args['url'],headers={'User-Agent':'local-ai-assistant-synthetic-reliability'})
     with urllib.request.urlopen(req,timeout=20) as r:v=json.load(r)
     live_tag=v['tag_name'];response={k:v.get(k) for k in ('tag_name','published_at','html_url')};response['fetched_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    except Exception:live_unavailable=True;response={'status':'unavailable','source':args['url']}
    terminal=True
   messages.append({'role':'tool','tool_call_id':call.get('id',''),'content':json.dumps(response)})
  if extra:break
 lower=final.lower(); passed=calls==expected and not errors and not extra and bool(final.strip()) and terminal
 if name=='auth-revoked':passed=passed and any(w in lower for w in ('consent','authoriz','sign in')) and 'example.invalid/synthetic-consent' in final and not any(w in lower for w in ('authentication succeeded','successfully authenticated'))
 if name=='missing-env':passed=passed and 'api_key' in lower and '.env' in lower and not any(w in lower for w in ('now fixed','successfully fixed'))
 if name=='current-data':passed=passed and ((live_tag and live_tag in final) or (live_unavailable and any(w in lower for w in ('unavailable','unable','could not','cannot'))))
 result={'test':name,'pass':bool(passed),'tool_sequence':calls,'unnecessary_actions':extra,'stop_condition':terminal and not extra and bool(final.strip()),'final_chars':len(final),'errors':errors,'timings':timings,'source_live':name=='current-data' and live_tag is not None}
 results.append(result);(root/(label+'.json')).write_text(json.dumps({'model':model,'think':think,'num_ctx':131072,'synthetic_tools':True,'protocol':'openai-compatible','reasoning_effort':'medium' if think else 'none','tests':results},indent=2))
 print(name,'PASS' if passed else 'FAIL','tools',calls,'extra',extra,flush=True)
