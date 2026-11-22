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
 const ctx=canvas.getContext("2d"),W=640,H=640,CX=320,CY=320,orb=document.getElementById("mic");
 let mode="idle",rotation=0,lastFrame=0,energy=0;
 new MutationObserver(()=>{mode=orb.classList.contains("listening")?"listen":orb.classList.contains("speaking")?"speak":orb.classList.contains("thinking")?"think":"idle"}).observe(orb,{attributes:true,attributeFilter:["class"]});
 let seed=82173;const random=()=>{seed=(seed*16807)%2147483647;return(seed-1)/2147483646};
 const particles=Array.from({length:1900},()=>{const u=random()*2-1,a=random()*Math.PI*2;return{a,u,r:Math.sqrt(1-u*u),size:.35+random()*1.55,phase:random()*6.28,speed:.3+random()*1.6,layer:random(),hue:random(),orbit:random()*6.28}});
 const filaments=Array.from({length:34},()=>({a:random()*6.28,b:random()*6.28,phase:random()*6.28,turns:1.2+random()*2.8,thick:.45+random()*1.2,hue:random()}));
 const sparks=Array.from({length:170},()=>({a:random()*6.28,u:random()*2-1,speed:.15+random()*.5,phase:random()*6.28,size:.5+random()*1.4}));
 const color=(h,a)=>{const n=((h%1)+1)%1*6,i=Math.floor(n),f=n-i,q=Math.round(255*(1-f)),t=Math.round(255*f),v=255,rgb=[[v,t,0],[q,v,0],[0,v,t],[0,q,v],[t,0,v],[v,0,q]][i%6];return 'rgba('+rgb[0]+','+rgb[1]+','+rgb[2]+','+a+')'};
 function project(x,y,z){const ca=Math.cos(rotation),sa=Math.sin(rotation),xx=x*ca-z*sa,zz=x*sa+z*ca,tilt=.19,yy=y*Math.cos(tilt)-zz*Math.sin(tilt),depth=y*Math.sin(tilt)+zz*Math.cos(tilt),pers=1/(1+depth*.2);return{x:CX+xx*218*pers,y:CY+yy*218*pers,z:depth,pers}}
 function frame(now){const dt=Math.min(40,now-lastFrame||16);lastFrame=now;const active=mode==="speak"?1.25:mode==="listen"?1.12:mode==="think"?.92:1;energy+=(active-energy)*.045;rotation+=dt*(mode==="speak"?.00095:mode==="listen"?.00072:.00034);ctx.clearRect(0,0,W,H);
 const halo=ctx.createRadialGradient(CX,CY,8,CX,CY,285);halo.addColorStop(0,color((now*.000025)%1,.17));halo.addColorStop(.35,color((now*.000025+.12)%1,.07));halo.addColorStop(1,"rgba(0,0,0,0)");ctx.fillStyle=halo;ctx.fillRect(0,0,W,H);ctx.globalCompositeOperation="lighter";
 // Layered plasma filaments form a dense, breathing three-dimensional energy cloud.
 filaments.forEach((f,j)=>{ctx.beginPath();for(let i=0;i<=240;i++){const q=i/240*Math.PI*2*f.turns+f.phase+now*.00018*(j%2?1:-1),lat=Math.sin(q*1.45+f.b)*.88,rad=174+26*Math.sin(q*2.8+f.a)+14*Math.cos(q*5.1+f.phase),x=Math.cos(q+f.a)*Math.cos(lat)*rad,y=Math.sin(lat)*rad,z=Math.sin(q+f.a)*Math.cos(lat)*rad,p=project(x/218,y/218,z/218);if(i===0)ctx.moveTo(p.x,p.y);else ctx.lineTo(p.x,p.y)}ctx.strokeStyle=color((f.hue+now*.000035)%1,.11+(j%5)*.035);ctx.lineWidth=f.thick;ctx.stroke()});
 // Fine particles drift across the shell, with depth, shimmer and spectral color shifts.
 particles.forEach((p,i)=>{const wave=Math.sin(now*.00065*p.speed+p.phase)*.045,lat=Math.asin(p.u)+wave,a=p.a+rotation*(.75+p.layer*.9),breath=1+(.025+energy*.07)*Math.sin(now*.0014+p.phase),radius=(.78+.22*Math.sin(p.a*5+p.phase+now*.0004))*breath,x=Math.cos(a)*Math.cos(lat)*p.r*radius,y=Math.sin(lat)*radius,z=Math.sin(a)*Math.cos(lat)*p.r*radius,pt=project(x,y,z),front=Math.max(.12,Math.min(1,.42+pt.z*.48)),alpha=(.16+pt.pers*.65)*front,h=(p.hue+now*.000045+(mode==="speak"?.12:0))%1,size=p.size*(.65+pt.pers*.75);ctx.fillStyle=color(h,alpha);ctx.beginPath();ctx.arc(pt.x,pt.y,size,0,Math.PI*2);ctx.fill();if(i%23===0){ctx.fillStyle=color((h+.08)%1,alpha*.17);ctx.beginPath();ctx.arc(pt.x,pt.y,size*4.5,0,Math.PI*2);ctx.fill()}});
 // Outward-moving sparks create the starburst / particle-explosion effect in the reference.
 sparks.forEach((s,i)=>{const pulse=(now*.00022*s.speed+s.phase)%(Math.PI*2),dist=226+Math.sin(pulse)*23+(mode==="speak"?Math.sin(pulse*2)*18:0),lat=Math.asin(s.u),a=s.a+rotation*1.4,x=Math.cos(a)*Math.cos(lat)*dist,y=Math.sin(lat)*dist,z=Math.sin(a)*Math.cos(lat)*dist,p=project(x/218,y/218,z/218);ctx.fillStyle=color((.53+i/170*.28+now*.000025)%1,.24);ctx.beginPath();ctx.arc(p.x,p.y,s.size*p.pers,0,Math.PI*2);ctx.fill()});
 // Bright inner nucleus and thin rotating magnetic rings.
 const core=ctx.createRadialGradient(CX-22,CY-28,3,CX,CY,132);core.addColorStop(0,"rgba(255,255,255,.28)");core.addColorStop(.18,color((now*.00004)%1,.2));core.addColorStop(.56,color((now*.00004+.16)%1,.075));core.addColorStop(1,"rgba(0,0,0,0)");ctx.fillStyle=core;ctx.beginPath();ctx.arc(CX,CY,132,0,Math.PI*2);ctx.fill();
 for(let n=0;n<6;n++){ctx.beginPath();ctx.ellipse(CX,CY,194+n*9,48+n*12,rotation*(n%2?-.7:.55)+n*.8,0,Math.PI*2);ctx.strokeStyle=color((n/6+now*.00002)%1,.08+n*.012);ctx.lineWidth=.7;ctx.stroke()}
 ctx.globalCompositeOperation="source-over";requestAnimationFrame(frame)}
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


// Holographic HUD telemetry follows the live JARVIS voice state.
(()=>{const orb=document.getElementById("mic"),voice=document.getElementById("hudVoice"),load=document.getElementById("hudLoad");if(!orb||!voice||!load)return;const sync=()=>{const s=document.getElementById("state")?.textContent||"STANDBY";voice.textContent=s.includes("LISTEN")?"LISTENING":s.includes("SPEAK")?"SPEAKING":s.includes("THINK")?"PROCESSING":"IDLE";load.textContent=s.includes("THINK")?"COMPUTING":s.includes("SPEAK")?"OUTPUT ACTIVE":"READY"};new MutationObserver(sync).observe(document.getElementById("state"),{childList:true,subtree:true,characterData:true});sync()})();

// One-click cinematic presentation mode; all assistant controls remain available when exited.
(()=>{const btn=document.getElementById("cinemaBtn");if(!btn)return;btn.addEventListener("click",()=>{document.body.classList.toggle("cinematic");btn.textContent=document.body.classList.contains("cinematic")?"EXIT CINEMATIC":"CINEMATIC VIEW"})})();

/* Wake-word bubble: the idle screen stays clean; the bubble appears only during interaction. */
(()=>{const zone=document.querySelector(".orb-zone");if(!zone)return;let bubble=document.getElementById("wakeBubble");if(!bubble){bubble=document.createElement("div");bubble.id="wakeBubble";bubble.className="wake-bubble";bubble.setAttribute("aria-live","polite");zone.appendChild(bubble)}const state=document.getElementById("state");const sync=()=>{const s=(state?.textContent||"").toUpperCase();let label="";if(s.includes("LISTEN"))label="LISTENING";else if(s.includes("THINK"))label="THINKING";else if(s.includes("SPEAK"))label="SPEAKING";if(label){bubble.textContent=label;bubble.classList.add("visible")}else bubble.classList.remove("visible")};if(state){new MutationObserver(sync).observe(state,{childList:true,subtree:true,characterData:true});sync()}document.title="JARVIS";})();
