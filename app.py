from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json, urllib.request, urllib.error, subprocess, os, threading, sqlite3, uuid, time, re, difflib

ROOT=Path(__file__).resolve().parent
HOST="127.0.0.1"; PORT=int(os.environ.get("JARVIS_PORT","8765"))
LM_URL=os.environ.get("LM_STUDIO_URL","http://127.0.0.1:1234").rstrip("/")
MODEL=os.environ.get("JARVIS_MODEL","google/gemma-4-e2b")
DB=ROOT/"jarvis_memory.sqlite3"
MODEL_LOCK=threading.Lock()
SYSTEM="You are JARVIS, a concise and practical local desktop assistant. Never claim an action happened unless confirmed. You can use only the supported local tools exposed by this application. Never invent live weather, appointments, or completed actions."
ACTIONS={"notepad":["notepad.exe"],"calculator":["calc.exe"],"file_explorer":["explorer.exe"],"browser":["cmd.exe","/c","start","","https://www.google.com"]}
SAFE_ROOTS={"desktop":Path.home()/"Desktop","documents":Path.home()/"Documents","downloads":Path.home()/"Downloads"}

def db():
    conn=sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, note TEXT NOT NULL, created_at INTEGER NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS reminders (id TEXT PRIMARY KEY, task TEXT NOT NULL, due TEXT, done INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)")
    return conn

def get_memories():
    with db() as c: return [{"id":r[0],"note":r[1],"created_at":r[2]} for r in c.execute("SELECT id,note,created_at FROM memories ORDER BY created_at DESC")]

def get_reminders():
    with db() as c: rows=c.execute("SELECT id,task,due,done,created_at FROM reminders ORDER BY done,due,created_at").fetchall()
    return [{"id":r[0],"task":r[1],"due":r[2],"done":bool(r[3]),"created_at":r[4]} for r in rows]

def get_installed_apps():
    ps="$ErrorActionPreference='Stop'; Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
    result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],capture_output=True,text=True,timeout=12,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if result.returncode!=0: raise RuntimeError("Could not read the Windows app catalogue.")
    data=json.loads(result.stdout or "[]")
    if isinstance(data,dict): data=[data]
    return [x for x in data if isinstance(x,dict) and isinstance(x.get("Name"),str) and isinstance(x.get("AppID"),str)]

def open_installed_app(query):
    if not isinstance(query,str) or not query.strip() or len(query)>100: raise ValueError("Tell me the application name.")
    apps=get_installed_apps(); norm=lambda s:re.sub(r"[^a-z0-9 ]","",s.lower()).strip(); q=norm(query)
    matches=[x for x in apps if norm(x["Name"])==q] or [x for x in apps if q in norm(x["Name"]) or norm(x["Name"]) in q]
    if not matches:
        ranked=sorted(((difflib.SequenceMatcher(None,q,norm(x["Name"])).ratio(),x) for x in apps),key=lambda z:z[0],reverse=True)
        if ranked and ranked[0][0]>=.82 and (len(ranked)==1 or ranked[0][0]-ranked[1][0]>=.08): matches=[ranked[0][1]]
    matches=list({x["AppID"]:x for x in matches}.values())
    if len(matches)!=1:
        if matches: raise ValueError("I found more than one match: "+", ".join(x["Name"] for x in matches[:8])+". Which one?")
        raise ValueError("I couldn't find that application in your Windows Start menu.")
    app=matches[0]
    subprocess.Popen(["explorer.exe","shell:AppsFolder\\"+app["AppID"]],shell=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    return app["Name"]

def running_apps():
    ps="Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object ProcessName,Id,MainWindowTitle | ConvertTo-Json -Compress"
    r=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],capture_output=True,text=True,timeout=12,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if r.returncode: raise RuntimeError("Could not inspect running applications.")
    data=json.loads(r.stdout or "[]")
    if isinstance(data,dict): data=[data]
    return [{"name":x.get("ProcessName",""),"pid":x.get("Id"),"title":x.get("MainWindowTitle","")} for x in data if isinstance(x,dict)]

def close_app(query):
    q=str(query or "").strip().lower()
    if not q or len(q)>100: raise ValueError("Tell me which application to close.")
    matches=[x for x in running_apps() if q in x["name"].lower() or q in x["title"].lower()]
    if not matches: raise ValueError("I couldn't find a running window matching that name.")
    names=sorted(set(x["name"] for x in matches))
    if len(names)>1: raise ValueError("That matches multiple apps: "+", ".join(names[:8])+". Be more specific.")
    ps="$p=Get-Process -Name "+json.dumps(names[0])+" -ErrorAction SilentlyContinue; $closed=0; foreach($x in $p){if($x.MainWindowHandle -ne 0 -and $x.CloseMainWindow()){$closed++}}; Write-Output $closed"
    r=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if r.returncode: raise RuntimeError("Windows could not close that application.")
    count=int((r.stdout or "0").strip() or 0)
    return names[0],count

def search_files(query,folder):
    q=str(query or "").strip().lower()
    if not q or len(q)>120: raise ValueError("Tell me a filename or part of a filename.")
    root=SAFE_ROOTS.get(str(folder or "downloads").lower())
    if root is None: raise ValueError("Search is limited to Desktop, Documents, and Downloads.")
    found=[]
    if root.exists():
        for base,dirs,files in os.walk(root):
            dirs[:]=[x for x in dirs if x not in {"AppData","node_modules",".git","venv","__pycache__"}]
            for name in files:
                if q in name.lower():
                    found.append(str(Path(base)/name))
                    if len(found)>=100: return found
    return found

def make_folder(name,folder):
    name=str(name or "").strip()
    if not name or len(name)>80 or name in {".",".."} or any(x in name for x in '\\/:*?"<>|'): raise ValueError("Enter a valid folder name.")
    root=SAFE_ROOTS.get(str(folder or "documents").lower())
    if root is None: raise ValueError("Folders can only be created in Desktop, Documents, or Downloads.")
    root.mkdir(parents=True,exist_ok=True); target=root/name
    target.mkdir(exist_ok=False)
    return str(target)

def get_models():
    with urllib.request.urlopen(LM_URL+"/v1/models",timeout=4) as r: data=json.load(r)
    return [m.get("id","") for m in data.get("data",[]) if m.get("id","").startswith("google/gemma-4")]

def weather():
    url="https://api.open-meteo.com/v1/forecast?latitude=41.6488&longitude=-0.8891&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m&timezone=Europe%2FMadrid"
    req=urllib.request.Request(url,headers={"User-Agent":"JARVIS-local/1.0"})
    with urllib.request.urlopen(req,timeout=12) as r: d=json.load(r)
    cur=d["current"]; codes={0:"clear",1:"mostly clear",2:"partly cloudy",3:"overcast",45:"foggy",48:"foggy",51:"light drizzle",53:"drizzle",55:"heavy drizzle",61:"light rain",63:"rain",65:"heavy rain",71:"light snow",73:"snow",75:"heavy snow",80:"rain showers",81:"rain showers",82:"heavy rain showers",95:"thunderstorm",96:"thunderstorm with hail",99:"thunderstorm with hail"}
    return {"location":"Zaragoza, Spain","temperature":cur["temperature_2m"],"feels_like":cur["apparent_temperature"],"humidity":cur["relative_humidity_2m"],"wind_kmh":cur["wind_speed_10m"],"condition":codes.get(cur["weather_code"],"unknown"),"time":cur["time"]}

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
        if self.path=="/api/reminders": return self.send_json(200,{"reminders":get_reminders()})
        if self.path=="/api/time":
            try: now=datetime.now(ZoneInfo("Europe/Madrid"))
            except Exception: now=datetime.now().astimezone()
            return self.send_json(200,{"time":now.isoformat(),"timezone":"Europe/Madrid"})
        if self.path=="/api/weather":
            try: return self.send_json(200,weather())
            except Exception as e: return self.send_json(503,{"error":"Live weather unavailable: "+str(e)})
        if self.path=="/api/running":
            try: return self.send_json(200,{"apps":running_apps()})
            except Exception as e: return self.send_json(503,{"error":str(e)})
        if self.path=="/api/apps":
            try: return self.send_json(200,{"apps":[{"name":x["Name"],"id":x["AppID"]} for x in get_installed_apps()]})
            except Exception as e: return self.send_json(503,{"error":str(e)})
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
        if self.path=="/api/reminders":
            task=data.get("task","").strip() if isinstance(data.get("task",""),str) else ""
            due=data.get("due")
            if not task or len(task)>300: return self.send_json(400,{"error":"Enter a reminder up to 300 characters."})
            if due is not None and (not isinstance(due,str) or len(due)>80): return self.send_json(400,{"error":"Invalid reminder date."})
            item={"id":uuid.uuid4().hex[:12],"task":task,"due":due,"done":False,"created_at":int(time.time())}
            with db() as c: c.execute("INSERT INTO reminders(id,task,due,done,created_at) VALUES(?,?,?,?,?)",(item["id"],task,due,0,item["created_at"]))
            return self.send_json(200,{"ok":True,"reminder":item})
        if self.path=="/api/reminders/complete":
            rid=data.get("id")
            with db() as c: cur=c.execute("UPDATE reminders SET done=1 WHERE id=?",(rid,))
            return self.send_json(200,{"ok":cur.rowcount==1})
        if self.path=="/api/files/search":
            try: return self.send_json(200,{"files":search_files(data.get("query"),data.get("folder","downloads"))})
            except ValueError as e: return self.send_json(400,{"error":str(e)})
            except Exception as e: return self.send_json(500,{"error":str(e)})
        if self.path=="/api/files/folder":
            try: return self.send_json(200,{"ok":True,"path":make_folder(data.get("name"),data.get("folder","documents"))})
            except FileExistsError: return self.send_json(409,{"error":"That folder already exists."})
            except ValueError as e: return self.send_json(400,{"error":str(e)})
            except Exception as e: return self.send_json(500,{"error":str(e)})
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
            memory_text="\n".join("- "+m["note"] for m in get_memories()[:30]) or "No saved memories."
            with MODEL_LOCK: selected=MODEL
            payload={"model":selected,"messages":[{"role":"system","content":SYSTEM+"\n\nUSER-SAVED MEMORY (use only when relevant):\n"+memory_text}]+clean,"temperature":0.7,"max_tokens":700}
            req=urllib.request.Request(LM_URL+"/v1/chat/completions",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
            try:
                with urllib.request.urlopen(req,timeout=120) as r: result=json.load(r)
                return self.send_json(200,{"reply":result["choices"][0]["message"]["content"],"model":selected})
            except urllib.error.HTTPError as e: return self.send_json(502,{"error":f"LM Studio HTTP {e.code}: {e.read().decode(errors='replace')[:400]}"})
            except Exception as e: return self.send_json(503,{"error":f"Cannot reach LM Studio: {e}"})
        if self.path=="/api/desktop/open":
            try: name=open_installed_app(data.get("app","")); return self.send_json(200,{"ok":True,"message":"Opening "+name,"app":name})
            except ValueError as e: return self.send_json(404,{"error":str(e)})
            except Exception as e: return self.send_json(500,{"error":"Could not open application: "+str(e)})
        if self.path=="/api/desktop/close":
            if data.get("confirm") is not True: return self.send_json(409,{"confirmation_required":True,"error":"Please confirm before closing an application. Unsaved work could be lost."})
            try:
                name,count=close_app(data.get("app"))
                return self.send_json(200,{"ok":True,"message":("Asked "+name+" to close." if count else "No close request was accepted by "+name+". Save your work and close it manually if needed.")})
            except ValueError as e: return self.send_json(404,{"error":str(e)})
            except Exception as e: return self.send_json(500,{"error":"Could not close application: "+str(e)})
        if self.path=="/api/action":
            action=data.get("action")
            if action not in ACTIONS: return self.send_json(400,{"error":"Action not allowed"})
            try: subprocess.Popen(ACTIONS[action],shell=False); return self.send_json(200,{"ok":True,"message":"Launched "+action.replace("_"," ")})
            except Exception as e: return self.send_json(500,{"error":str(e)})
        return self.send_json(404,{"error":"Not found"})
    def do_DELETE(self):
        if self.path=="/api/memory":
            try: data=self.read_body()
            except Exception: return self.send_json(400,{"error":"Invalid request"})
            with db() as c: cur=c.execute("DELETE FROM memories WHERE id=?",(data.get("id"),))
            return self.send_json(200,{"ok":True,"deleted":cur.rowcount})
        if self.path=="/api/reminders":
            try: data=self.read_body()
            except Exception: return self.send_json(400,{"error":"Invalid request"})
            with db() as c: cur=c.execute("DELETE FROM reminders WHERE id=?",(data.get("id"),))
            return self.send_json(200,{"ok":True,"deleted":cur.rowcount})
        return self.send_json(404,{"error":"Not found"})
    def log_message(self,fmt,*args): print("[JARVIS] "+fmt%args)

if __name__=="__main__":
    with db(): pass
    print(f"JARVIS at http://{HOST}:{PORT} | model {MODEL}")
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()