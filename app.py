from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json, urllib.request, urllib.error, subprocess, os, threading
ROOT=Path(__file__).resolve().parent
HOST="127.0.0.1"
PORT=int(os.environ.get("JARVIS_PORT","8765"))
LM_URL=os.environ.get("LM_STUDIO_URL","http://127.0.0.1:1234").rstrip("/")
MODEL=os.environ.get("JARVIS_MODEL","google/gemma-4-e2b")
MODEL_LOCK=threading.Lock()
SYSTEM="You are JARVIS, a concise and practical local desktop assistant. Never claim an action happened unless confirmed. PC actions are limited to the visible allowlisted quick actions."
ACTIONS={"notepad":["notepad.exe"],"calculator":["calc.exe"],"file_explorer":["explorer.exe"]}
def get_models():
    req=urllib.request.Request(LM_URL+"/v1/models")
    with urllib.request.urlopen(req,timeout=4) as response:
        data=json.load(response)
    return [m.get("id","") for m in data.get("data",[]) if m.get("id","").startswith("google/gemma-4")]
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/"web"),**kwargs)
    def send_json(self,code,payload):
        body=json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(body)
    def read_body(self):
        length=int(self.headers.get("Content-Length","0"))
        if length>20000: raise ValueError("Request too large")
        return json.loads(self.rfile.read(length) or b"{}")
    def do_GET(self):
        if self.path=="/api/health":
            with MODEL_LOCK: selected=MODEL
            data={"app":"online","lm_studio":False,"model":selected,"models":[]}
            try:
                data["models"]=get_models()
                data["lm_studio"]=True
            except Exception as exc:
                data["error"]=str(exc)
            return self.send_json(200,data)
        if self.path=="/":
            self.path="/index.html"
        return super().do_GET()
    def do_POST(self):
        global MODEL
        try:
            data=self.read_body()
        except ValueError as exc:
            return self.send_json(413,{"error":str(exc)})
        except Exception:
            return self.send_json(400,{"error":"Invalid JSON"})
        if self.path=="/api/model":
            requested=data.get("model")
            try:
                available=get_models()
            except Exception as exc:
                return self.send_json(503,{"error":f"LM Studio unavailable: {exc}"})
            if requested not in available:
                return self.send_json(400,{"error":"Choose an available Gemma 4 model shown in the model list."})
            with MODEL_LOCK:
                MODEL=requested
            return self.send_json(200,{"ok":True,"model":MODEL})
        if self.path=="/api/chat":
            messages=data.get("messages",[])
            if not isinstance(messages,list) or not messages:
                return self.send_json(400,{"error":"A message is required"})
            clean=[]
            for item in messages[-20:]:
                if not isinstance(item,dict) or item.get("role") not in ("user","assistant") or not isinstance(item.get("content"),str):
                    return self.send_json(400,{"error":"Messages must contain user/assistant roles and text content."})
                clean.append({"role":item["role"],"content":item["content"][:8000]})
            with MODEL_LOCK:
                selected=MODEL
            payload={"model":selected,"messages":[{"role":"system","content":SYSTEM}]+clean,"temperature":0.7,"max_tokens":700}
            request=urllib.request.Request(LM_URL+"/v1/chat/completions",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
            try:
                with urllib.request.urlopen(request,timeout=120) as response:
                    result=json.load(response)
                reply=result["choices"][0]["message"]["content"]
                return self.send_json(200,{"reply":reply,"model":selected})
            except urllib.error.HTTPError as exc:
                return self.send_json(502,{"error":f"LM Studio HTTP {exc.code}: {exc.read().decode(errors='replace')[:400]}"})
            except Exception as exc:
                return self.send_json(503,{"error":f"Cannot reach LM Studio at {LM_URL}: {exc}"})
        if self.path=="/api/action":
            action=data.get("action")
            if action not in ACTIONS:
                return self.send_json(400,{"error":"Action not allowed"})
            try:
                subprocess.Popen(ACTIONS[action],shell=False)
                return self.send_json(200,{"ok":True,"message":"Launched "+action.replace("_"," ")})
            except Exception as exc:
                return self.send_json(500,{"error":str(exc)})
        return self.send_json(404,{"error":"Not found"})
    def log_message(self,fmt,*args):
        print("[JARVIS] "+fmt%args)
if __name__=="__main__":
    print(f"JARVIS running at http://{HOST}:{PORT} | LM Studio: {LM_URL} | model: {MODEL}")
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()

[executed on device: RIQCO (8d334d39-dd57-43d5-a43f-c4290607a406)]
