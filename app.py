from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json, urllib.request, urllib.error, subprocess, os, threading, sqlite3, uuid, time
ROOT=Path(__file__).resolve().parent
HOST="127.0.0.1"; PORT=int(os.environ.get("JARVIS_PORT","8765"))
LM_URL=os.environ.get("LM_STUDIO_URL","http://127.0.0.1:1234").rstrip("/")
MODEL=os.environ.get("JARVIS_MODEL","google/gemma-4-e2b")
DB=ROOT/"jarvis_memory.sqlite3"
MODEL_LOCK=threading.Lock()
SYSTEM="You are JARVIS, a concise and practical local desktop assistant. Never claim an action happened unless confirmed. PC actions are limited to the visible allowlisted quick actions. Use saved memories only when relevant and do not invent details."
ACTIONS={"notepad":["notepad.exe"],"calculator":["calc.exe"],"file_explorer":["explorer.exe"],"browser":["cmd.exe","/c","start","","https://www.google.com"]}
def db():
    conn=sqlite3.connect(DB); conn.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, note TEXT NOT NULL, created_at INTEGER NOT NULL)"); return conn
def get_memories():
    with db() as c: return [{"id":r[0],"note":r[1],"created_at":r[2]} for r in c.execute("SELECT id,note,created_at FROM memories ORDER BY created_at DESC")]
def get_models():
    with urllib.request.urlopen(LM_URL+"/v1/models",timeout=4) as r: data=json.load(r)
    return [m.get("id","") for m in data.get("data",[]) if m.get("id","").startswith("google/gemma-4")]
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(ROOT/"web"),**kw)
    def send_json(self,code,obj):
        body=json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(body)
    def read_body(self):
        n=int(self.headers.get("Content-Length","0"))
        if n>20000: raise ValueError("Request too large")
        return json.loads(self.rfile.read(n) or b"{}")
    def do_GET(self):
        if self.path=="/api/health":
            with MODEL_LOCK: selected=MODEL
            d={"app":"online","lm_studio":False,"model":selected,"models":[],"memory_count":0}
            try: d["models"]=get_models(); d["lm_studio"]=True
            except Exception as e: d["error"]=str(e)
            d["memory_count"]=len(get_memories()); return self.send_json(200,d)
        if self.path=="/api/memory": return self.send_json(200,{"memories":get_memories()})
        if self.path=="/": self.path="/index.html"
        return super().do_GET()
    def do_POST(self):
        global MODEL
        try: data=self.read_body()
        except ValueError as e: return self.send_json(413,{"error":str(e)})
        except Exception: return self.send_json(400,{"error":"Invalid JSON"})
        if self.path=="/api/memory":
            note=data.get("note","")
            if not isinstance(note,str) or not note.strip(): return self.send_json(400,{"error":"Enter a memory first."})
            if len(note)>500: return self.send_json(400,{"error":"Memories must be 500 characters or fewer."})
            item={"id":uuid.uuid4().hex[:12],"note":note.strip(),"created_at":int(time.time())}
            with db() as c: c.execute("INSERT INTO memories VALUES (?,?,?)",(item["id"],item["note"],item["created_at"]))
            return self.send_json(200,{"ok":True,"memory":item})
        if self.path=="/api/model":
            requested=data.get("model")
            try: available=get_models()
            except Exception as e: return self.send_json(503,{"error":f"LM Studio unavailable: {e}"})
            if requested not in available: return self.send_json(400,{"error":"Choose an available Gemma 4 model."})
            with MODEL_LOCK: MODEL=requested
            return self.send_json(200,{"ok":True,"model":MODEL})
        if self.path=="/api/chat":
            messages=data.get("messages",[])
            if not isinstance(messages,list) or not messages: return self.send_json(400,{"error":"A message is required"})
            clean=[]
            for item in messages[-20:]:
                if not isinstance(item,dict) or item.get("role") not in ("user","assistant") or not isinstance(item.get("content"),str): return self.send_json(400,{"error":"Invalid chat message format"})
                clean.append({"role":item["role"],"content":item["content"][:8000]})
            memories=get_memories()
            memory_text="\n".join("- "+m["note"] for m in memories[:30]) or "No saved memories."
            with MODEL_LOCK: selected=MODEL
            payload={"model":selected,"messages":[{"role":"system","content":SYSTEM+"\n\nUSER-SAVED MEMORY (use only when relevant):\n"+memory_text}]+clean,"temperature":0.7,"max_tokens":700}
            req=urllib.request.Request(LM_URL+"/v1/chat/completions",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
            try:
                with urllib.request.urlopen(req,timeout=120) as r: result=json.load(r)
                return self.send_json(200,{"reply":result["choices"][0]["message"]["content"],"model":selected})
            except urllib.error.HTTPError as e: return self.send_json(502,{"error":f"LM Studio HTTP {e.code}: {e.read().decode(errors='replace')[:400]}"})
            except Exception as e: return self.send_json(503,{"error":f"Cannot reach LM Studio: {e}"})
        if self.path=="/api/action":
            action=data.get("action")
            if action not in ACTIONS: return self.send_json(400,{"error":"Action not allowed"})
            try: subprocess.Popen(ACTIONS[action],shell=False); return self.send_json(200,{"ok":True,"message":"Launched "+action.replace("_"," ")})
            except Exception as e: return self.send_json(500,{"error":str(e)})
        return self.send_json(404,{"error":"Not found"})
    def do_DELETE(self):
        if self.path!="/api/memory": return self.send_json(404,{"error":"Not found"})
        try: data=self.read_body()
        except Exception: return self.send_json(400,{"error":"Invalid request"})
        mid=data.get("id")
        with db() as c: cur=c.execute("DELETE FROM memories WHERE id=?",(mid,))
        return self.send_json(200,{"ok":True,"deleted":cur.rowcount})
    def log_message(self,fmt,*args): print("[JARVIS] "+fmt%args)
if __name__=="__main__":
    with db(): pass
    print(f"JARVIS at http://{HOST}:{PORT} | model {MODEL}")
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()