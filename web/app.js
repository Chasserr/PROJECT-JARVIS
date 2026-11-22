const $=s=>document.querySelector(s),messages=[];let wakeRec=null,wakeOn=true,awaitingCommand=false,conversationActive=false,restartTimer=null,lastSpeechAt=0;
function add(role,text){const sub=$("#subheadline");if(sub)sub.textContent=String(text).slice(0,150);console.log("[JARVIS]",role,text)}
function setState(s){$("#state").textContent=s;$("#mic").classList.toggle("listening",s==="LISTENING");$("#mic").classList.toggle("speaking",s==="SPEAKING");$("#mic").classList.toggle("thinking",s==="THINKING");$("#headline").innerHTML=s==="LISTENING"?'I’m listening<span>.</span>':s==="SPEAKING"?'Speaking<span>.</span>':s==="THINKING"?'One moment<span>.</span>':'I’m here<span>.</span>';$("#subheadline").textContent=s==="LISTENING"?"Go ahead. I'm listening to you.":s==="SPEAKING"?"JARVIS is responding.":s==="THINKING"?"Let me think that through.":"Say “Jarvis” or tap the orb to start a conversation."}
async function health(){try{const r=await fetch("/api/health"),d=await r.json();$("#statusDot").style.background=d.lm_studio?"#5ee0b0":"#e2b66b";$("#statusText").textContent=d.lm_studio?"AI CONNECTED":"MODEL OFFLINE";$("#modelLabel").textContent="MODEL: "+d.model;const sel=$("#modelSelect"),old=sel.value;if(d.models?.length){sel.replaceChildren(...d.models.map(m=>{const o=document.createElement("option");o.value=m;o.textContent=m.replace("google/","");return o}));sel.value=d.models.includes(old)?old:d.model}}catch{$("#statusText").textContent="APP OFFLINE"}}
async function send(text){text=text.trim();if(!text)return;if($("#prompt"))$("#prompt").value="";add("user",text);messages.push({role:"user",content:text});setState("THINKING");try{
const say=v=>{messages.push({role:"assistant",content:v});add("assistant",v);speak(v)};
const call=async(url,body)=>{const r=await fetch(url,{method:body?"POST":"GET",headers:{"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json();if(!r.ok)throw Error(d.error||"Request failed");return d};
let m;
if((m=text.match(/^(?:plan (?:this )?(?:computer )?task|do this on my computer|use my pc to):?\s+(.+)$/i))){if(!window.prepareJarvisTask)throw Error("Open PC CONTROL first.");await window.prepareJarvisTask(m[1]);say("I've prepared a computer action plan. Review it in PC CONTROL, then approve execution.");return}
if(/^(?:inspect|read|describe) (?:the )?(?:screen|current window|active window)[?.!]*$/i.test(text)){const d=await call("/api/computer/inspect");say(d.window?("The active window is "+d.window+". Visible controls: "+(d.controls||[]).slice(0,18).map(c=>c.type+" "+c.name).join("; ")+"."):"I couldn't identify an active window.");return}
if((m=text.match(/^click (?:the )?(?:button|control|field) (.+?)[?.!]*$/i))){const d=await call("/api/computer/ui-action",{window:"",control:m[1].trim()});say("Clicked "+d.control+" in "+d.window+".");return}
if((m=text.match(/^(?:please\s+)?(?:open|go to|navigate to)\s+(?:the\s+)?(?:website|site)?\s*(https?:\/\/\S+|[a-z0-9.-]+\.[a-z]{2,}(?:\/\S*)?)[?.!]*$/i))){const d=await call("/api/computer/open-url",{url:m[1]});say("Opening "+d.url+".");return}
if((m=text.match(/^click at\s+(\d{1,4})[ ,]+(\d{1,4})[?.!]*$/i))){const d=await call("/api/computer/action",{action:"click",x:Number(m[1]),y:Number(m[2])});say("Clicked the screen at "+d.x+", "+d.y+".");return}
if((m=text.match(/^double click at\s+(\d{1,4})[ ,]+(\d{1,4})[?.!]*$/i))){const d=await call("/api/computer/action",{action:"double_click",x:Number(m[1]),y:Number(m[2])});say("Double-clicked at "+d.x+", "+d.y+".");return}
if((m=text.match(/^(?:type on my computer|type on the computer|type into the computer):?\s+(.+)$/i))){const d=await call("/api/computer/action",{action:"type",text:m[1]});say("Typed "+d.characters+" characters into the active window.");return}
if((m=text.match(/^press (enter|tab|escape|esc|space|backspace|delete|up|down|left|right|home|end|pageup|pagedown|f[1-6]|f10|f11|f12)[?.!]*$/i))){const d=await call("/api/computer/action",{action:"press",key:m[1].toLowerCase()});say("Pressed "+m[1]+".");return}
if((m=text.match(/^scroll (up|down)[?.!]*$/i))){const d=await call("/api/computer/action",{action:"scroll",x:1280,y:720,amount:m[1]==="up"?5:-5});say("Scrolled "+m[1]+".");return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:please\s+)?(?:can you\s+)?(?:could you\s+)?(?:open|launch|start|run)\s+(.+?)[?.!]*$/i))){const d=await call("/api/desktop/open",{app:m[1].replace(/^(the|my)\s+/i,"").trim()});say("Opening "+d.app+".");return}
if(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:what(?:'s| is) the time|tell me the time|current time)(?:\s+in\s+zaragoza)?[?.!]*$/i.test(text)){const d=await call("/api/time");say("It's "+new Date(d.time).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"})+" in Zaragoza.");return}
if(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:(?:what(?:'s| is)|how(?:'s| is))\s+(?:the\s+)?weather|weather(?:\s+report)?|tell me (?:the )?weather|give me (?:the )?weather)(?:\s+(?:like\s+)?in\s+zaragoza)?[?.!]*$/i.test(text)){const d=await call("/api/weather");say("In "+d.location+", it's "+d.temperature+" degrees Celsius, feels like "+d.feels_like+" degrees, with "+d.condition+". Humidity is "+d.humidity+" percent and wind is "+d.wind_kmh+" kilometres per hour.");return}
if(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:what apps are running|show running apps|list running apps)[?.!]*$/i.test(text)){const d=await call("/api/running");say(d.apps.length?"Currently open: "+d.apps.map(x=>x.name).filter((v,i,a)=>a.indexOf(v)===i).join(", ")+".":"I couldn't find any open application windows.");return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:close|quit|exit)\s+(.+?)[?.!]*$/i))){const app=m[1].replace(/^(the|my)\s+/i,"").trim();if(!window.confirm("Ask "+app+" to close? Save your work first; unsaved changes could be lost.")){say("Okay, I won't close it.");return}const d=await call("/api/desktop/close",{app,confirm:true});say(d.message);return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:search (?:the )?web for|search the internet for|look up online|google)\s+(.+?)[?.!]*$/i))){const d=await call("/api/search/answer",{query:m[1]});const sourceLine=d.sources?.length?" Sources: "+d.sources.map(x=>x.title).join("; ")+".":"";say((d.answer||"I couldn't find a useful answer.")+sourceLine);return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:find|search for)\s+(.+?)(?:\s+in\s+(desktop|documents|downloads))?[?.!]*$/i))){const d=await call("/api/files/search",{query:m[1],folder:(m[2]||"downloads").toLowerCase()});say(d.files.length?"I found "+d.files.length+" matching file(s): "+d.files.slice(0,8).map(x=>x.replace(/^.*[\\/]/,"")).join(", ")+(d.files.length>8?". There are more results.":"."):"I couldn't find matching files in "+(m[2]||"Downloads")+".");return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:create|make)\s+(?:a\s+)?folder\s+(?:called\s+|named\s+)?(.+?)(?:\s+in\s+(desktop|documents|downloads))?[?.!]*$/i))){const d=await call("/api/files/folder",{name:m[1].trim(),folder:(m[2]||"documents").toLowerCase()});say("Created folder "+d.path+".");return}
if(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:show|list|read)\s+(?:my\s+)?reminders[?.!]*$/i.test(text)){const d=await call("/api/reminders");say(d.reminders.length?"Your reminders: "+d.reminders.map(x=>(x.done?"Completed: ":"")+x.task+(x.due?" ("+x.due+")":"")).join("; "):"You don't have any reminders saved.");return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?remind me to\s+(.+?)[?.!]*$/i))){const d=await call("/api/reminders",{task:m[1].trim()});say("Reminder saved: "+d.reminder.task+". You can ask me to show your reminders.");return}
const r=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({messages})}),d=await r.json();if(!r.ok)throw Error(d.error);messages.push({role:"assistant",content:d.reply});add("assistant",d.reply);speak(d.reply)
}catch(e){add("assistant","I couldn't complete that: "+e.message);speak("I couldn't complete that. "+e.message);setState("SYSTEM READY")}}async function speak(t){if(wakeRec){const r=wakeRec;wakeRec=null;r.stop()}if("speechSynthesis"in window)speechSynthesis.cancel();const resume=()=>{if(wakeOn){conversationActive=true;startWake()}else setState("SYSTEM READY")};try{const status=await fetch("/api/voice/status").then(r=>r.json());if(status.configured){setState("SPEAKING");const response=await fetch("/api/voice/speak",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:t})});if(!response.ok){const err=await response.json();throw Error(err.error||"ElevenLabs speech failed")}const audio=new Audio(URL.createObjectURL(await response.blob()));audio.onended=()=>{URL.revokeObjectURL(audio.src);resume()};audio.onerror=()=>{URL.revokeObjectURL(audio.src);resume()};await audio.play();return}}catch(e){add("assistant","ElevenLabs voice unavailable; using the browser voice for now. "+e.message)}if(!("speechSynthesis"in window)){setState("SYSTEM READY");return}const u=new SpeechSynthesisUtterance(t);u.rate=1;u.pitch=1.02;u.onstart=()=>setState("SPEAKING");u.onend=resume;speechSynthesis.speak(u)}
async function loadMemory(){const r=await fetch("/api/memory"),d=await r.json(),list=$("#memoryList");list.replaceChildren();d.memories.forEach(m=>{const row=document.createElement("div");row.className="memory-row";const span=document.createElement("span");span.textContent=m.note;const del=document.createElement("button");del.textContent="×";del.title="Delete memory";del.onclick=()=>deleteMemory(m.id);row.append(span,del);list.append(row)})}
async function deleteMemory(id){await fetch("/api/memory",{method:"DELETE",headers:{"Content-Type":"application/json"},body:JSON.stringify({id})});loadMemory()}
$("#saveMemory").onclick=async()=>{const note=$("#memoryInput").value.trim();if(!note)return;const r=await fetch("/api/memory",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({note})}),d=await r.json();if(!r.ok){add("assistant",d.error);return}$("#memoryInput").value="";loadMemory();add("assistant","Saved to JARVIS memory.")};
$("#modelSelect").onchange=async e=>{try{const r=await fetch("/api/model",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model:e.target.value})}),d=await r.json();if(!r.ok)throw Error(d.error);messages.length=0;box.innerHTML='<div class="empty-state"><div class="empty-mark">✦</div><div><b>Model changed</b><span>Start a new conversation.</span></div></div>';$("#modelLabel").textContent="MODEL: "+d.model;setState("SYSTEM READY")}catch(err){add("assistant",err.message);health()}};
$("#chatForm").onsubmit=e=>{e.preventDefault();send($("#prompt").value)};$("#clear").onclick=()=>{messages.length=0;box.innerHTML='<div class="empty-state"><div class="empty-mark">✦</div><div><b>Conversation cleared</b><span>Ask JARVIS something new.</span></div></div>'};
document.querySelectorAll("[data-action]").forEach(b=>b.onclick=async()=>{const r=await fetch("/api/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:b.dataset.action})}),d=await r.json();add("assistant",d.message||d.error)});
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
function startWake(){if(!wakeOn||!SR||wakeRec)return;const rec=new SR();wakeRec=rec;rec.continuous=true;rec.interimResults=false;rec.lang="en-US";rec.onstart=()=>{setState(conversationActive?"LISTENING":"STANDING BY")};rec.onresult=e=>{for(let i=e.resultIndex;i<e.results.length;i++){if(!e.results[i].isFinal)continue;const phrase=e.results[i][0].transcript.trim();if(!phrase)continue;lastSpeechAt=Date.now();if(conversationActive){send(phrase);continue}if(/hey jarvis|ok jarvis|okay jarvis|open jarvis|wake up jarvis|wake up|\bjarvis\b/i.test(phrase)){const command=phrase.replace(/.*?(hey jarvis|ok jarvis|okay jarvis|open jarvis|wake up jarvis|wake up|\bjarvis\b)/i,"").trim();conversationActive=true;if(command)send(command);else setState("LISTENING")}}};rec.onerror=e=>{if(e.error!=="no-speech"&&e.error!=="aborted"){add("assistant","Microphone listening issue: "+e.error);setState("MICROPHONE CHECK")}};rec.onend=()=>{if(wakeRec===rec)wakeRec=null;if(wakeOn&&!speechSynthesis.speaking){clearTimeout(restartTimer);restartTimer=setTimeout(()=>{if(wakeOn)startWake()},350)}};try{rec.start()}catch{wakeRec=null;setState("WAKE WORD PAUSED")}}
function stopWake(){wakeOn=false;conversationActive=false;awaitingCommand=false;if(wakeRec){const r=wakeRec;wakeRec=null;r.stop()}$("#wakeToggle").classList.remove("on");$("#wakeHint").textContent="Wake phrase paused";setState("SYSTEM READY")}
$("#wakeToggle").onclick=()=>{if(wakeOn)stopWake();else if(!SR)add("assistant","Continuous wake listening requires Microsoft Edge or Chrome.");else{wakeOn=true;$("#wakeToggle").classList.add("on");$("#wakeHint").textContent='Wake phrase ready: “Open Jarvis”';startWake()}};
$("#mic").onclick=()=>{if(!SR){add("assistant","Voice input is not supported in this browser. Open JARVIS in Microsoft Edge or Chrome.");return}if(wakeRec){const old=wakeRec;wakeRec=null;try{old.stop()}catch{}}awaitingCommand=false;const rec=new SR();rec.lang="en-US";rec.continuous=false;rec.interimResults=true;let heard="";rec.onstart=()=>setState("LISTENING");rec.onresult=e=>{for(let i=e.resultIndex;i<e.results.length;i++){heard=e.results[i][0].transcript;if(e.results[i].isFinal)send(heard)}};rec.onerror=e=>{const messages={"not-allowed":"Microphone access is blocked. Allow microphone access for this JARVIS app in Edge site permissions.","audio-capture":"No microphone was detected. Check your Windows input device.","no-speech":"I did not hear anything. Check your microphone and try again.","network":"Browser speech recognition could not connect. Try again."};add("assistant",messages[e.error]||("Voice input error: "+e.error));setState("SYSTEM READY")};rec.onend=()=>{if(wakeOn&&!speechSynthesis.speaking){wakeRec=null;setTimeout(startWake,500)}else setState("SYSTEM READY")};try{rec.start()}catch(e){add("assistant","Could not start microphone: "+e.message);if(wakeOn)setTimeout(startWake,500)}};
$("#settingsBtn").onclick=()=>$("#settings").classList.toggle("hidden");$("#closeSettings").onclick=()=>$("#settings").classList.add("hidden");$("#memoryToggle").onclick=()=>$("#memoryArea").classList.toggle("hidden");$("#attach").onclick=()=>$("#settings").classList.toggle("hidden");
health();loadMemory();if(SR)startWake();else add("assistant","Voice recognition is unavailable in this browser. Use Microsoft Edge.");setInterval(health,15000);
(()=>{
 const canvas=document.getElementById("neuralCore");if(!canvas)return;
 const c=canvas.getContext("2d"),W=640,H=640,CX=320,CY=320;
 let state="idle",rot=0;
 const orb=document.getElementById("mic");
 new MutationObserver(()=>{state=orb.classList.contains("listening")?"listen":orb.classList.contains("speaking")?"speak":orb.classList.contains("thinking")?"think":"idle"}).observe(orb,{attributes:true,attributeFilter:["class"]});
 let seed=9471;function rand(){seed=(seed*16807)%2147483647;return(seed-1)/2147483646}
 const dots=Array.from({length:1050},()=>{const u=rand()*2-1,a=rand()*Math.PI*2,r=Math.sqrt(1-u*u);return{a,u,r,sz:.35+rand()*1.8,ph:rand()*Math.PI*2,dr:rand()*.12,col:rand()}});
 const strands=Array.from({length:22},(_,i)=>({a:rand()*6.28,phase:rand()*6.28,tilt:(rand()-.5)*1.5,len:1.3+rand()*1.7,offset:rand()*60}));
 function project(x,y,z){const ca=Math.cos(rot),sa=Math.sin(rot),xx=x*ca-z*sa,zz=x*sa+z*ca;const tilt=.24,yy=y*Math.cos(tilt)-zz*Math.sin(tilt),z2=y*Math.sin(tilt)+zz*Math.cos(tilt),pers=1/(1+z2*.22);return{x:CX+xx*205*pers,y:CY+yy*205*pers,z:z2,pers}}
 function frame(t){rot+=state==="speak"?.009:state==="listen"?.006:.0027;const pulse=state==="speak"?1.12:state==="listen"?1.07:state==="think"?.97:1; c.clearRect(0,0,W,H);
 const glow=c.createRadialGradient(CX,CY,4,CX,CY,250);glow.addColorStop(0,state==="speak"?"rgba(160,255,210,.22)":"rgba(0,255,160,.18)");glow.addColorStop(.35,"rgba(0,180,160,.075)");glow.addColorStop(1,"rgba(0,0,0,0)");c.fillStyle=glow;c.fillRect(0,0,W,H);
 c.globalCompositeOperation="lighter";
 // Curved, turbulent energy filaments wrap the volume like a living plasma cloud.
 strands.forEach((s,k)=>{c.beginPath();for(let j=0;j<=180;j++){const q=j/180* Math.PI*2*s.len+s.phase+t*.00024*(state==="speak"?2.5:1),lat=Math.sin(q*1.7+s.offset)*.52+s.tilt,rad=155+24*Math.sin(q*3+s.a)+13*Math.cos(q*5+s.phase);const x=Math.cos(q+s.a)*Math.cos(lat)*rad,y=Math.sin(lat)*rad,z=Math.sin(q+s.a)*Math.cos(lat)*rad;const p=project(x/205,y/205,z/205);if(j===0)c.moveTo(p.x,p.y);else c.lineTo(p.x,p.y)}c.strokeStyle=k%4===0?"rgba(191,255,218,.32)":"rgba(70,255,181,.27)";c.lineWidth=k%5===0?1.5:.75;c.stroke()});
 // Dense irregular cloud of glowing particles, with depth and organic movement.
 dots.forEach((d,i)=>{const wobble=Math.sin(t*.0007+d.ph)*(.025+d.dr*.08),lat=Math.asin(d.u)+wobble,rad=(.78+.22*Math.sin(d.a*4+d.ph+t*.0005))*pulse;const x=Math.cos(d.a+rot*1.8)*Math.cos(lat)*d.r*rad,y=Math.sin(lat)*rad,z=Math.sin(d.a+rot*1.8)*Math.cos(lat)*d.r*rad;const p=project(x,y,z);const alpha=Math.min(.95,.18+p.pers*.66);const blue=d.col>.86||p.z<-.55;c.fillStyle=blue?"rgba(177,255,213,"+alpha+")":"rgba("+(d.col>.5?85:38)+",255,"+(d.col>.5?211:168)+","+alpha+")";const size=d.sz*(.65+p.pers*.65);c.beginPath();c.arc(p.x,p.y,size,0,Math.PI*2);c.fill();if(i%17===0){c.fillStyle="rgba(93,255,225,"+(alpha*.18)+")";c.beginPath();c.arc(p.x,p.y,size*4,0,Math.PI*2);c.fill()}});
 // Electric blue inner nucleus and subtle orbital arcs.
 const core=c.createRadialGradient(CX-18,CY-22,2,CX,CY,108);core.addColorStop(0,"rgba(177,255,238,.42)");core.addColorStop(.2,"rgba(0,255,199,.18)");core.addColorStop(.55,"rgba(0,145,255,.09)");core.addColorStop(1,"rgba(0,0,0,0)");c.fillStyle=core;c.beginPath();c.arc(CX,CY,110,0,Math.PI*2);c.fill();
 for(let n=0;n<4;n++){c.beginPath();c.ellipse(CX,CY,190+n*10,48+n*13,rot*(n%2?-.55:.4)+n,0,Math.PI*2);c.strokeStyle="rgba(70,230,210,"+(.09+n*.012)+")";c.lineWidth=.8;c.stroke()}
 c.globalCompositeOperation="source-over";requestAnimationFrame(frame)}
 requestAnimationFrame(frame);
})();

// JARVIS Computer Control: live screen, mouse, keyboard and safe file operations.
(()=>{
 const $=s=>document.querySelector(s);
 const panel=$("#computerPanel"), shot=$("#desktopShot");
 if(!panel||!shot)return;
 let clickMode=true,lastPoint={x:0,y:0};
 async function api(url,body,headers={}){
  const r=await fetch(url,{method:body?"POST":"GET",headers:{"Content-Type":"application/json",...headers},...(body?{body:JSON.stringify(body)}:{})});
  const type=r.headers.get("content-type")||"";
  const d=type.includes("application/json")?await r.json():null;
  if(!r.ok)throw Error(d?.error||"Computer action failed");
  return d;
 }
 function statusMsg(t){$("#computerStatus").textContent=t}
 async function refreshScreen(){
  try{statusMsg("Capturing Windows screen…");const r=await fetch("/api/computer/screenshot",{cache:"no-store"});if(!r.ok){const d=await r.json();throw Error(d.error||"Screen capture failed")}const blob=await r.blob();const old=shot.dataset.url;if(old)URL.revokeObjectURL(old);const url=URL.createObjectURL(blob);shot.dataset.url=url;shot.src=url;statusMsg("Screen connected · "+new Date().toLocaleTimeString())}
  catch(e){statusMsg(e.message)}
 }
 let pendingPlan=null;
 async function understandScreen(){
  try{const d=await api("/api/computer/vision");$("#visionSummary").textContent=d.description;statusMsg("Screen analyzed by "+d.model)}
  catch(e){$("#visionSummary").textContent=e.message;statusMsg(e.message)}
 }
 async function prepareTaskPlan(task){
  if(!task?.trim())return;
  try{
   statusMsg("JARVIS is examining the screen and planning…");
   const d=await api("/api/computer/plan",{task:task.trim()});pendingPlan=d;
   const preview=$("#taskPreview");preview.replaceChildren();
   const summary=document.createElement("p");summary.textContent=d.summary;preview.append(summary);
   (d.steps||[]).forEach((step,i)=>{const row=document.createElement("div");row.className="plan-step";row.textContent=(i+1)+". "+(step.action==="type"?"Type: "+step.text:step.action==="open_url"?"Open website: "+step.url:step.action==="press"?"Press "+step.key:step.action==="hotkey"?"Shortcut "+step.keys.join("+"):step.action==="wait"?"Wait "+step.seconds+" seconds":step.action+" at "+(step.x??"center")+", "+(step.y??"center"));preview.append(row)});
   $("#executePlan").disabled=!(d.steps||[]).length;
   if(!d.steps?.length){const note=document.createElement("small");note.textContent="JARVIS did not produce safe, actionable steps for this request.";preview.append(note)}
   panel.classList.remove("hidden");$("#settings").classList.add("hidden");
   statusMsg("Plan ready · "+d.steps.length+" step(s) · review before execution");
   return d
  }catch(e){statusMsg(e.message);$("#taskPreview").textContent=e.message;throw e}
 }
 window.prepareJarvisTask=prepareTaskPlan;
 $("#planTask").onclick=()=>prepareTaskPlan($("#taskInput").value);
 $("#taskInput").addEventListener("keydown",e=>{if(e.key==="Enter")prepareTaskPlan($("#taskInput").value)});
 $("#understandScreen").onclick=understandScreen;
 $("#executePlan").onclick=async()=>{
  if(!pendingPlan?.steps?.length)return;
  if(!confirm("Execute the "+pendingPlan.steps.length+" computer actions shown above? Review the steps first."))return;
  try{const d=await api("/api/computer/execute-plan",{confirm:true,steps:pendingPlan.steps});pendingPlan=null;$("#executePlan").disabled=true;$("#taskPreview").textContent="Completed "+d.completed+" action(s).";statusMsg("Task completed · "+d.completed+" action(s)");await refreshScreen();await refreshStatus()}
  catch(e){statusMsg(e.message);add("assistant","The computer task stopped: "+e.message);refreshScreen()}
 };
 async function refreshStatus(){
  try{const d=await api("/api/computer/status");$("#activeWindow").textContent="Active window: "+(d.active_window||"Desktop");$("#processCount").textContent="Running processes: "+d.process_count+" · Screen: "+d.screen.width+" × "+d.screen.height}
  catch(e){statusMsg(e.message)}
 }
 async function act(body){try{const d=await api("/api/computer/action",body);statusMsg("Completed: "+d.action);setTimeout(refreshScreen,350);return d}catch(e){statusMsg(e.message);add("assistant","Computer control: "+e.message)}}
 $("#computerBtn").onclick=()=>{panel.classList.remove("hidden");$("#settings").classList.add("hidden");refreshScreen();refreshStatus();};
 $("#closeComputer").onclick=()=>panel.classList.add("hidden");
 $("#refreshScreen").onclick=refreshScreen;$("#refreshStatus").onclick=refreshStatus;
 async function inspectControls(){
  try{const d=await api("/api/computer/inspect");const box=$("#uiControls");box.replaceChildren();const title=document.createElement("b");title.textContent=d.window||"No active window";box.append(title);
   (d.controls||[]).forEach(c=>{const b=document.createElement("button");b.className="ui-control";b.textContent=c.type+": "+c.name;b.title="Click this exact accessible control";b.onclick=async()=>{try{await api("/api/computer/ui-action",{window:d.window,control:c.name});statusMsg("Clicked "+c.name);setTimeout(refreshScreen,300);setTimeout(inspectControls,450)}catch(e){statusMsg(e.message)}};box.append(b)});
   if(!d.controls?.length){const p=document.createElement("small");p.textContent="No named controls found. Use the screen preview instead.";box.append(p)}
   statusMsg("Inspected "+(d.window||"active window")+" · "+(d.controls?.length||0)+" controls")
  }catch(e){statusMsg(e.message)}
 }
 $("#inspectControls").onclick=inspectControls;
 $("#screenClickMode").onclick=()=>{clickMode=!clickMode;$("#screenClickMode").textContent=clickMode?"CLICK MODE ON":"CLICK MODE OFF";$("#screenClickMode").classList.toggle("off",!clickMode)};
 shot.addEventListener("click",e=>{
  if(!clickMode||!shot.naturalWidth)return;const r=shot.getBoundingClientRect();
  const x=Math.round((e.clientX-r.left)*shot.naturalWidth/r.width),y=Math.round((e.clientY-r.top)*shot.naturalHeight/r.height);
  lastPoint={x,y};act({action:"click",x,y});
 });
 document.querySelectorAll("[data-mouse]").forEach(b=>b.onclick=()=>{
  const type=b.dataset.mouse;const action=type==="left"?"click":type==="right"?"right_click":type==="double"?"double_click":"scroll";
  act({action,x:lastPoint.x,y:lastPoint.y,...(type==="scroll-up"?{amount:5}:type==="scroll-down"?{amount:-5}:{})});
 });
 $("#computerTypeSend").onclick=()=>{const text=$("#computerType").value;if(!text)return;act({action:"type",text});$("#computerType").value=""};
 $("#computerType").addEventListener("keydown",e=>{if(e.key==="Enter")$("#computerTypeSend").click()});
 document.querySelectorAll("[data-key]").forEach(b=>b.onclick=()=>act({action:"press",key:b.dataset.key}));
 document.querySelectorAll("[data-hotkey]").forEach(b=>b.onclick=()=>act({action:"hotkey",keys:b.dataset.hotkey.split("+")}));
 async function browse(path){
  try{const d=await api("/api/computer/files",null,{"X-Jarvis-Path":path});$("#filePath").value=d.path;const list=$("#fileList");list.replaceChildren();
   if(d.parent){const up=document.createElement("button");up.className="file-item";up.textContent="↑ Parent folder";up.onclick=()=>browse(d.parent);list.append(up)}
   d.items.forEach(item=>{const row=document.createElement("div");row.className="file-item";const open=document.createElement("button");open.textContent=(item.type==="folder"?"📁 ":"📄 ")+item.name;open.onclick=()=>item.type==="folder"?browse(item.path):fileAction({action:"open",path:item.path});const tools=document.createElement("span");if(item.type==="file"){const rename=document.createElement("button");rename.textContent="RENAME";rename.onclick=()=>{const name=prompt("New name",item.name);if(name)fileAction({action:"rename",path:item.path,name})};tools.append(rename)}const trash=document.createElement("button");trash.textContent="TRASH";trash.onclick=()=>{if(confirm("Send "+item.name+" to the Windows Recycle Bin?"))fileAction({action:"trash",path:item.path,confirm:true})};tools.append(trash);row.append(open,tools);list.append(row)});
   statusMsg("Browsing "+d.items.length+" items")
  }catch(e){statusMsg(e.message)}
 }
 async function fileAction(body){try{const d=await api("/api/computer/files",body);statusMsg(d.message||"File operation completed");browse($("#filePath").value)}catch(e){statusMsg(e.message)}}
 $("#browseFiles").onclick=()=>browse($("#filePath").value.trim());
 $("#filePath").addEventListener("keydown",e=>{if(e.key==="Enter")browse($("#filePath").value.trim())});
})();