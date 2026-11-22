from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json, urllib.request, urllib.error, subprocess, os
ROOT=Path(__file__).resolve().parent
HOST='127.0.0.1'; PORT=int(os.environ.get('JARVIS_PORT','8765'))
LM_URL=os.environ.get('LM_STUDIO_URL','http://127.0.0.1:1234').rstrip('/')
MODEL=os.environ.get('JARVIS_MODEL','google/gemma-4-e2b')
SYSTEM='You are JARVIS, a concise and practical local desktop assistant. Never claim an action happened unless confirmed. PC actions are limited to the visible allowlisted quick actions.'
ACTIONS={'notepad':['notepad.exe'],'calculator':['calc.exe'],'file_explorer':['explorer.exe']}
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw): super().__init__(*a,directory=str(ROOT/'web'),**kw)
 def send_json(self,code,obj):
  b=json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
 def do_GET(self):
  if self.path=='/api/health':
   d={'app':'online','lm_studio':False,'model':MODEL}
   try:
    with urllib.request.urlopen(LM_URL+'/v1/models',timeout=2) as r: x=json.load(r)
    d['lm_studio']=True; d['models']=[m.get('id') for m in x.get('data',[])]
   except Exception as e: d['error']=str(e)
   return self.send_json(200,d)
  if self.path=='/': self.path='/index.html'
  return super().do_GET()
 def do_POST(self):
  n=int(self.headers.get('Content-Length','0'))
  if n>20000: return self.send_json(413,{'error':'Request too large'})
  try: d=json.loads(self.rfile.read(n) or b'{}')
  except Exception: return self.send_json(400,{'error':'Invalid JSON'})
  if self.path=='/api/chat':
   msgs=d.get('messages',[])
   if not isinstance(msgs,list) or not msgs: return self.send_json(400,{'error':'Message required'})
   payload={'model':MODEL,'messages':[{'role':'system','content':SYSTEM}]+msgs[-20:],'temperature':0.7,'max_tokens':700}
   req=urllib.request.Request(LM_URL+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
   try:
    with urllib.request.urlopen(req,timeout=120) as r: out=json.load(r)
    return self.send_json(200,{'reply':out['choices'][0]['message']['content'],'model':MODEL})
   except urllib.error.HTTPError as e: return self.send_json(502,{'error':f'LM Studio HTTP {e.code}: {e.read().decode(errors="replace")[:400]}'})
   except Exception as e: return self.send_json(503,{'error':f'Cannot reach LM Studio at {LM_URL}: {e}'})
  if self.path=='/api/action':
   action=d.get('action')
   if action not in ACTIONS: return self.send_json(400,{'error':'Action not allowed'})
   try: subprocess.Popen(ACTIONS[action],shell=False); return self.send_json(200,{'ok':True,'message':'Launched '+action.replace('_',' ')})
   except Exception as e: return self.send_json(500,{'error':str(e)})
  return self.send_json(404,{'error':'Not found'})
 def log_message(self,fmt,*args): print('[JARVIS] '+fmt%args)
if __name__=='__main__':
 print(f'JARVIS at http://{HOST}:{PORT} | {LM_URL} | {MODEL}')
 ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
