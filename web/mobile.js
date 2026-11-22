(()=>{
  const $=s=>document.querySelector(s);
  const messages=[];
  let busy=false,pendingClose=null;
  function bubble(role,text){
    const el=document.createElement("div");
    el.className="bubble "+role;
    el.textContent=text;
    $("#messages").append(el);
    $("#messages").scrollTop=$("#messages").scrollHeight;
  }
  async function api(url,body){
    const r=await fetch(url,{
      method:body?"POST":"GET",
      headers:{"Content-Type":"application/json"},
      ...(body?{body:JSON.stringify(body)}:{})
    });
    const d=await r.json();
    if(!r.ok)throw Error(d.error||"Request failed");
    return d;
  }
  async function health(){
    try{
      const d=await api("/api/health");
      $("#dot").style.background=d.lm_studio?"#63e3b1":"#e4b86d";
      $("#status").textContent=d.lm_studio?"AI CONNECTED":"MODEL OFFLINE";
      $("#model").textContent="MODEL · "+(d.model||"UNKNOWN");
    }catch{
      $("#status").textContent="SERVER OFFLINE";
      $("#model").textContent="LOCAL AI · UNAVAILABLE";
    }
  }
  function normalizeCommand(value){
    return String(value||"").trim().toLowerCase()
      .replace(/[?!.,;:]+$/g,"").replace(/\s+/g," ");
  }
  async function runLocalCommand(text){
    const q=normalizeCommand(text);
    if(/^(what apps are running|what applications are running|show running apps|list running apps|running apps)$/.test(q)){
      const d=await api("/api/running");
      const names=[...new Set((d.apps||[]).map(x=>x.name).filter(Boolean))].sort();
      return names.length?"These applications have visible windows open: "+names.join(", ")+".":"I couldn't find any applications with visible windows open.";
    }
    if(/^(what is the weather|what's the weather|weather|weather in zaragoza|what's the weather in zaragoza|what is the weather in zaragoza)$/.test(q)){
      const d=await api("/api/weather");
      return "Current weather in "+d.location+": "+d.temperature+"°C, "+d.condition+". Feels like "+d.feels_like+"°C. Humidity "+d.humidity+"%, wind "+d.wind_kmh+" km/h. Updated "+d.time+".";
    }
    if(/^(what time is it|what time is it in zaragoza|time|current time)$/.test(q)){
      const d=await api("/api/time");
      return "The current time in Zaragoza is "+new Intl.DateTimeFormat("en-US",{timeZone:"Europe/Madrid",hour:"numeric",minute:"2-digit",hour12:true}).format(new Date(d.time))+".";
    }
    if(/^(show my reminders|show reminders|list reminders|my reminders|reminders)$/.test(q)){
      const d=await api("/api/reminders");
      const items=d.reminders||[];
      if(!items.length)return "You don't have any reminders saved yet.";
      return "Your reminders: "+items.map(x=>(x.done?"Completed: ":"Pending: ")+x.task+(x.due?" ( "+x.due+" )":"")).join("; ")+".";
    }
    return null;
  }
  async function send(raw){
    const text=String(raw||"").trim();
    if(!text||busy)return;
    busy=true;
    $("#prompt").value="";
    bubble("user",text);
    messages.push({role:"user",content:text});
    $("#state").textContent="THINKING";
    try{
      let answer=null,m;
      if(pendingClose){
        if(/^(yes|confirm|do it|close it)$/i.test(normalizeCommand(text))){
          const app=pendingClose;
          pendingClose=null;
          const d=await api("/api/desktop/close",{app,confirm:true});
          answer=d.message;
        }else if(/^(no|cancel|stop)$/i.test(normalizeCommand(text))){
          pendingClose=null;
          answer="Okay, I'll leave it open.";
        }else{
          answer="Please reply YES to confirm closing "+pendingClose+", or NO to cancel.";
        }
      }
      if(!answer&&(m=text.match(/^(?:open|launch|start|run)\s+(.+?)[.!?]*$/i))){
        const d=await api("/api/desktop/open",{app:m[1].trim()});
        answer="Opening "+d.app+".";
      }
      if(!answer&&(m=text.match(/^(?:close|quit|exit)\s+(.+?)[.!?]*$/i))){
        pendingClose=m[1].replace(/\s+app$/i,"").trim();
        answer="Do you want me to close "+pendingClose+"? Reply YES to confirm or NO to cancel. Save your work first.";
      }
      if(!answer)answer=await runLocalCommand(text);
      if(!answer){
        const d=await api("/api/chat",{messages});
        answer=d.reply;
      }
      messages.push({role:"assistant",content:answer});
      bubble("assistant",answer);
      if("speechSynthesis"in window){
        speechSynthesis.cancel();
        const u=new SpeechSynthesisUtterance(answer);
        u.lang="en-US";u.rate=1;speechSynthesis.speak(u);
      }
    }catch(e){
      bubble("assistant","I couldn't complete that: "+e.message);
    }finally{
      busy=false;
      $("#state").textContent="SYSTEM STANDBY";
    }
  }
  $("#chat").addEventListener("submit",e=>{e.preventDefault();send($("#prompt").value);});
  $("#clear").onclick=()=>{
    messages.length=0;
    $("#messages").replaceChildren();
    bubble("assistant","Conversation cleared.");
  };
  document.querySelectorAll("[data-command]").forEach(b=>b.onclick=()=>send(b.dataset.command));
  $("#open").onclick=()=>{const v=$("#appName").value.trim();if(v)send("open "+v);};
  $("#close").onclick=()=>{const v=$("#closeName").value.trim();if(v)send("close "+v);};
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  $("#voice").onclick=()=>{
    if(!SR){
      bubble("assistant","Voice input isn't supported in this browser. Please use the message box; spoken replies are still available.");
      return;
    }
    const rec=new SR();
    rec.lang="en-US";rec.interimResults=false;
    rec.onstart=()=>{$("#state").textContent="LISTENING";$("#voice").classList.add("listening");};
    rec.onresult=e=>send(e.results[0][0].transcript);
    rec.onerror=e=>bubble("assistant","Microphone issue: "+e.error);
    rec.onend=()=>{$("#voice").classList.remove("listening");if(!busy)$("#state").textContent="SYSTEM STANDBY";};
    try{rec.start();}catch(e){bubble("assistant",e.message);}
  };
  health();
  setInterval(health,15000);
})();