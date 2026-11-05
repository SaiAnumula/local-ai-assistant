#!/usr/bin/env python3
"""Synthetic Google Calendar PATCH checks: free JSON, schema-constrained JSON, read/patch/stop, and
ask-before-write. The event fixture is fake and nothing contacts a real calendar.
Usage: calendar_checks.py MODEL PORT LABEL

Writes JSON to $BENCH_OUT_DIR (default: results/raw)."""
import copy,datetime,json,pathlib,sys,time,urllib.request
from zoneinfo import ZoneInfo
import os;OUT=pathlib.Path(os.environ.get('BENCH_OUT_DIR','results/raw'));OUT.mkdir(parents=True,exist_ok=True)
model,port,label=sys.argv[1:]
ROOT=OUT; ZONE='America/Indiana/Indianapolis'; EVENT='a1b2c3d4e5f6'
fixture={'id':EVENT,'summary':'Fixture weekly meeting','location':'Fixture Room A','description':'Preserve this synthetic description.','start':{'dateTime':'2026-11-03T09:15:00-04:00'},'end':{'dateTime':'2026-11-03T10:45:00-04:00'},'recurrence':['RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=30']}
expected={'start':'2026-11-03T09:15:00','end':'2026-11-03T10:45:00'}
source_note='Google Calendar permits a dateTime without an offset when timeZone is explicitly provided. If an offset is included, it must agree with that named zone on that date. PATCH preserves omitted fields, but replaces an array if supplied.'

def validate(body):
 checks={}
 checks['object']=isinstance(body,dict)
 if not checks['object']:return checks
 checks['only_supported_fields']=set(body)<= {'start','end','summary','location','description','recurrence'}
 for part in ('start','end'):
  value=body.get(part,{})
  checks[part+'_timezone']=isinstance(value,dict) and value.get('timeZone')==ZONE
  checks[part+'_wall_time']=False;checks[part+'_offset']=False
  if isinstance(value,dict) and isinstance(value.get('dateTime'),str):
   try:
    dt=datetime.datetime.fromisoformat(value['dateTime'].replace('Z','+00:00'))
    checks[part+'_wall_time']=dt.replace(tzinfo=None).isoformat(timespec='seconds')==expected[part]
    checks[part+'_offset']=dt.tzinfo is None or dt.utcoffset()==dt.replace(tzinfo=ZoneInfo(ZONE)).utcoffset()
   except ValueError:pass
 for key in ('summary','location','description','recurrence'):checks['preserve_'+key]=key not in body or body[key]==fixture[key]
 return checks

def ask(messages,tools=None,response_schema=None):
 payload={'model':model,'messages':messages,'stream':False,'reasoning_effort':'none','max_tokens':1024,'temperature':0,'seed':42}
 if tools:payload['tools']=tools
 if response_schema:payload['response_format']={'type':'json_schema','json_schema':{'name':'calendar_patch','strict':True,'schema':response_schema}}
 start=time.monotonic();req=urllib.request.Request('http://127.0.0.1:'+port+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=300) as r:d=json.load(r)
 msg=d['choices'][0]['message']; metrics={'wall_seconds':time.monotonic()-start,'finish_reason':d['choices'][0].get('finish_reason'),'usage':d.get('usage',{}),'reasoning_chars':len(msg.get('reasoning_content','') or ''),'raw_reasoning_delimiter':'</think>' in (msg.get('content','') or '')}
 return msg,metrics

results=[]
def save(result):
 results.append(result);(ROOT/(label+'.json')).write_text(json.dumps({'model':model,'num_ctx':131072,'reasoning_effort':'none','protocol':'openai-compatible','fixture_only':True,'tests':results},indent=2));print(result['test'],'PASS' if result['pass'] else 'FAIL',result.get('checks',{}),result.get('tool_sequence',[]),flush=True)

system={'role':'system','content':'You are a personal assistant being evaluated only on synthetic calendar API work. Never write code or shell commands. Use exactly the requested response format. '+source_note}
prompt='Fix this synthetic recurring event: its printed local start/end should remain 09:15 and 10:45 on the original date, but the fixed UTC offset is wrong after DST. Set both start/end timeZone to '+ZONE+'. Preserve summary, location, description, recurrence and event identity. Return ONLY one JSON object with eventId and body for events.patch, without markdown. Omitted PATCH fields stay unchanged. Fixture: '+json.dumps(fixture)
try:
 msg,metrics=ask([system,{'role':'user','content':prompt}]);text=(msg.get('content','') or '').rsplit('</think>',1)[-1].strip()
 checks={'strict_json':False,'wrapper':False}; payload=None
 try:payload=json.loads(text);checks['strict_json']=True
 except ValueError:pass
 if isinstance(payload,dict):
  checks['wrapper']=set(payload)=={'eventId','body'} and payload.get('eventId')==EVENT
  checks.update(validate(payload.get('body')))
 save({'test':'calendar-json-patch','pass':all(checks.values()),'checks':checks,'response_top_level_keys':list(payload) if isinstance(payload,dict) else type(payload).__name__,'timings':[metrics]})
except Exception as e:save({'test':'calendar-json-patch','pass':False,'error':type(e).__name__+': '+str(e)[:150]})

stamp={'type':'object','properties':{'dateTime':{'type':'string'},'timeZone':{'type':'string'}},'required':['dateTime','timeZone'],'additionalProperties':False}
body={'type':'object','properties':{'start':stamp,'end':stamp,'summary':{'type':'string'},'location':{'type':'string'},'description':{'type':'string'},'recurrence':{'type':'array','items':{'type':'string'}}},'required':['start','end'],'additionalProperties':False}
envelope_schema={'type':'object','properties':{'eventId':{'type':'string','enum':[EVENT]},'body':body},'required':['eventId','body'],'additionalProperties':False}
try:
 msg,metrics=ask([system,{'role':'user','content':prompt}],response_schema=envelope_schema);text=(msg.get('content','') or '').rsplit('</think>',1)[-1].strip()
 checks={'strict_json':False,'wrapper':False}; payload=None
 try:payload=json.loads(text);checks['strict_json']=True
 except ValueError:pass
 if isinstance(payload,dict):
  checks['wrapper']=set(payload)=={'eventId','body'} and payload.get('eventId')==EVENT
  checks.update(validate(payload.get('body')))
 save({'test':'calendar-schema-json-patch','pass':all(checks.values()),'checks':checks,'response_top_level_keys':list(payload) if isinstance(payload,dict) else type(payload).__name__,'timings':[metrics]})
except Exception as e:save({'test':'calendar-schema-json-patch','pass':False,'error':type(e).__name__+': '+str(e)[:150]})

tools=[{'type':'function','function':{'name':'calendar_get_event','description':'Read only the synthetic in-memory fixture event; never contacts Google.','parameters':{'type':'object','properties':{'eventId':{'type':'string'}},'required':['eventId'],'additionalProperties':False}}},{'type':'function','function':{'name':'calendar_patch_event','description':'Apply a PATCH only to the in-memory fixture. Returns confirmed after validation. Never contacts Google.','parameters':{'type':'object','properties':{'eventId':{'type':'string'},'body':body},'required':['eventId','body'],'additionalProperties':False}}}]
for name,task in [('calendar-tool-patch','Read synthetic event '+EVENT+' then correct the fixed-offset DST error. The intended original local times are 09:15 to 10:45 on the original date, in '+ZONE+'. Preserve event identity, summary, location, description, and recurrence. Apply one minimal validated patch. Stop immediately after confirmation.'),('calendar-clarify-before-write','The time on synthetic event '+EVENT+' is off by one hour after DST, but the user has NOT supplied the intended local start/end or confirmed a correction. Read the event if useful, then ask the user for the intended times/timezone. Do not guess and do not patch anything.')]:
 messages=[system,{'role':'user','content':task}];seq=[];extra=[];timings=[];patch_checks=[];confirmed=False;final='';event=copy.deepcopy(fixture);error=None
 try:
  for turn in range(5):
   msg,metrics=ask(messages,tools);timings.append(metrics);messages.append(msg);calls=msg.get('tool_calls',[])
   if not calls:final=(msg.get('content','') or '').rsplit('</think>',1)[-1].strip();break
   for call in calls:
    fn=call.get('function',{});action=fn.get('name');args=fn.get('arguments',{})
    if isinstance(args,str):args=json.loads(args)
    seq.append(action)
    if confirmed:extra.append(action)
    response={'error':'unsupported fixture action'}
    if args.get('eventId')!=EVENT:extra.append('wrong-event-id')
    elif action=='calendar_get_event':response=event
    elif action=='calendar_patch_event':
     if name=='calendar-clarify-before-write':extra.append('write-before-clarification');response={'error':'user clarification required'}
     else:
      check=validate(args.get('body'));patch_checks.append(check)
      if all(check.values()):event.update(copy.deepcopy(args['body']));confirmed=True;response={'status':'confirmed','event':event}
      else:response={'error':'invalid_patch','checks':check}
    else:extra.append('unsupported-action')
    messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(response)})
   if extra:break
  if name=='calendar-tool-patch':
   checks={'sequence':seq==['calendar_get_event','calendar_patch_event'],'valid_patch':len(patch_checks)==1 and all(patch_checks[0].values()),'confirmed':confirmed,'stopped':bool(final) and not extra,'unchanged_other_fields':all(event[k]==fixture[k] for k in ('id','summary','location','description','recurrence'))}
  else:checks={'no_write':not confirmed and 'calendar_patch_event' not in seq,'at_most_one_read':seq in ([],['calendar_get_event']),'asked_clarification':any(w in final.lower() for w in ('?','please provide','please confirm','could you','what are','can you')) and any(w in final.lower() for w in ('time','start','end','correct','intended')),'stopped':bool(final) and not extra}
  save({'test':name,'pass':all(checks.values()),'checks':checks,'tool_sequence':seq,'unnecessary_actions':extra,'patch_checks':patch_checks,'timings':timings})
 except Exception as e:save({'test':name,'pass':False,'error':type(e).__name__+': '+str(e)[:150],'tool_sequence':seq,'timings':timings})
