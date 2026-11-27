const $=s=>document.querySelector(s),messages=[],box=document.querySelector("#messages");let wakeRec=null,wakeOn=true,awaitingCommand=false,conversationActive=false,processing=false,restartTimer=null,lastSpeechAt=0,pendingCloseApp=null,jarvisAudioSpeaking=false,lastJarvisSpeech="",lastJarvisSpeechAt=0,jarvisSpeechRun=0,activeJarvisAudio=null;
function add(role,text){const sub=$("#subheadline");if(sub)sub.textContent=String(text).slice(0,150);const box=$("#messages");if(box){if(!box.dataset.started){box.replaceChildren();box.dataset.started="1"}const item=document.createElement("div");item.className="msg "+(role==="user"?"user":"assistant");item.textContent=String(text);box.append(item);box.scrollTop=box.scrollHeight;box.closest(".chat-dock")?.classList.add("has-messages")}console.log("[JARVIS]",role,text)}
function setState(s){$("#state").textContent=s;$("#mic").classList.toggle("listening",s==="LISTENING");$("#mic").classList.toggle("speaking",s==="SPEAKING");$("#mic").classList.toggle("thinking",s==="THINKING");$("#headline").innerHTML=s==="LISTENING"?'I   m listening<span>.</span>':s==="SPEAKING"?'Speaking<span>.</span>':s==="THINKING"?'One moment<span>.</span>':'I   m here<span>.</span>';$("#subheadline").textContent=s==="LISTENING"?"Go ahead. I'm listening to you.":s==="SPEAKING"?"JARVIS is responding.":s==="THINKING"?"Let me think that through.":"Say    Jarvis    or tap the orb to start a conversation."}
async function health(){try{const r=await fetch("/api/health"),d=await r.json();const connected=!!(d.ollama||d.agent_core?.status==="ok"||d.lm_studio);$("#statusDot").style.background=connected?"#5ee0b0":"#e2b66b";$("#statusText").textContent=connected?(d.provider==="ollama"?"OLLAMA CONNECTED":"AI CONNECTED"):"MODEL OFFLINE";$("#modelLabel").textContent=d.model;const cm=$("#connectionModel");if(cm)cm.textContent=d.model;const sel=$("#modelSelect"),old=sel.value;if(d.models?.length){sel.replaceChildren(...d.models.map(m=>{const o=document.createElement("option");o.value=m;o.textContent=m.replace("google/","");return o}));sel.value=d.models.includes(old)?old:d.model}}catch{$("#statusText").textContent="APP OFFLINE"}}
async function send(text){text=String(text||"").trim().replace(/^[\s,.:;!?-]*/,"").replace(/^(?:(?:(?:hey|okay|ok|open|wake up)\s+)?jarvis\b[\s,.:;!?-]*)+/i,"").replace(/^[\s,.:;!?-]*/,"").replace(/\bcap\s*cuts?\b/ig,"CapCut").trim().replace(/^(?:(?:uh|um|erm|well)\b[\s,.:;!?-]*)+/i,"").trim();if(!text||/^(?:hey\s+)?open\s+jarvis[?.!]*$/i.test(text)||processing)return;processing=true;if($("#prompt"))$("#prompt").value="";add("user",text);messages.push({role:"user",content:text});setState("THINKING");try{
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
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:please\s+)?(?:(?:can|could) you\s+)?(?:open|launch|start|run)\s+(.+?)(?:\s+(?:on|from)\s+(?:my\s+)?(?:windows pc|pc|computer))?[?.!]*$/i))){const d=await call("/api/desktop/open",{app:m[1].replace(/^(the|my)\s+/i,"").trim()});say("Opening "+d.app+".");return}
if(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:what(?:'s| is) the time|tell me the time|current time)(?:\s+in\s+zaragoza)?[?.!]*$/i.test(text)){const d=await call("/api/time");say("It's "+new Date(d.time).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"})+" in Zaragoza.");return}
if(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:(?:what(?:'s| is)|how(?:'s| is))\s+(?:the\s+)?weather|weather(?:\s+report)?|tell me (?:the )?weather|give me (?:the )?weather)(?:\s+(?:like\s+)?in\s+zaragoza)?[?.!]*$/i.test(text)){const d=await call("/api/weather");say("In "+d.location+", it's "+d.temperature+" degrees Celsius, feels like "+d.feels_like+" degrees, with "+d.condition+". Humidity is "+d.humidity+" percent and wind is "+d.wind_kmh+" kilometres per hour.");return}
if(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:what apps are running|show running apps|list running apps)[?.!]*$/i.test(text)){const d=await call("/api/running");say(d.apps.length?"Currently open: "+d.apps.map(x=>x.name).filter((v,i,a)=>a.indexOf(v)===i).join(", ")+".":"I couldn't find any open application windows.");return}
if((m=text.replace(/\bcap\s*cuts?\b/ig,"CapCut").match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:please\s+)?(?:(?:can|could) you\s+)?(?:close|quit|exit|shut down)\s+(?:the\s+)?(.+?)(?:\s+app)?(?:\s+(?:on|from)\s+(?:my\s+)?(?:windows pc|pc|computer))?[?.!]*$/i))){const app=m[1].replace(/^(the|my)\s+/i,"").trim();const d=await call("/api/desktop/close",{app});say(d.message);return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:search (?:the )?web for|search the internet for|look up online|google)\s+(.+?)[?.!]*$/i))){const d=await call("/api/search/answer",{query:m[1]});const sourceLine=d.sources?.length?" Sources: "+d.sources.map(x=>x.title).join("; ")+".":"";say((d.answer||"I couldn't find a useful answer.")+sourceLine);return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:find|search for)\s+(.+?)(?:\s+in\s+(desktop|documents|downloads))?[?.!]*$/i))){const d=await call("/api/files/search",{query:m[1],folder:(m[2]||"downloads").toLowerCase()});say(d.files.length?"I found "+d.files.length+" matching file(s): "+d.files.slice(0,8).map(x=>x.replace(/^.*[\\/]/,"")).join(", ")+(d.files.length>8?". There are more results.":"."):"I couldn't find matching files in "+(m[2]||"Downloads")+".");return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:create|make)\s+(?:a\s+)?folder\s+(?:called\s+|named\s+)?(.+?)(?:\s+in\s+(desktop|documents|downloads))?[?.!]*$/i))){const d=await call("/api/files/folder",{name:m[1].trim(),folder:(m[2]||"documents").toLowerCase()});say("Created folder "+d.path+".");return}
if(/^(?:(?:hey\s+)?jarvis[,.! ]*)?(?:show|list|read)\s+(?:my\s+)?reminders[?.!]*$/i.test(text)){const d=await call("/api/reminders");say(d.reminders.length?"Your reminders: "+d.reminders.map(x=>(x.done?"Completed: ":"")+x.task+(x.due?" ("+x.due+")":"")).join("; "):"You don't have any reminders saved.");return}
if((m=text.match(/^(?:(?:hey\s+)?jarvis[,.! ]*)?remind me to\s+(.+?)[?.!]*$/i))){const d=await call("/api/reminders",{task:m[1].trim()});say("Reminder saved: "+d.reminder.task+". You can ask me to show your reminders.");return}
const r=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({messages})}),d=await r.json();if(!r.ok)throw Error(d.error);messages.push({role:"assistant",content:d.reply});add("assistant",d.reply);speak(d.reply)
}catch(e){const msg=String(e.message||e);const friendly=/10061|LM Studio|ECONNREFUSED|Failed to fetch/i.test(msg)?"My AI chat model is offline right now. Local PC commands, time and weather are still available.":"That command failed: "+msg;add("assistant",friendly);speak(friendly)}finally{processing=false}}function speechPlainText(value){return String(value||" ").replace(/\*\*/g,"").replace(/^\s*[-*]\s+/gm,"").replace(/^\s*\d+[.)]\s+/gm,"").replace(/\s+/g," ").trim()}async function speak(t){t=speechPlainText(t);if(!t)return;const now=Date.now(),key=t.toLowerCase().replace(/[^a-z0-9]+/g," ").trim();if(key===lastJarvisSpeech&&now-lastJarvisSpeechAt<9000)return;lastJarvisSpeech=key;lastJarvisSpeechAt=now;const run=++jarvisSpeechRun;jarvisAudioSpeaking=true;if(wakeRec){const r=wakeRec;wakeRec=null;try{r.stop()}catch{}}if("speechSynthesis"in window)speechSynthesis.cancel();if(activeJarvisAudio){try{activeJarvisAudio.pause();activeJarvisAudio.src=""}catch{}activeJarvisAudio=null}const resume=()=>{if(run!==jarvisSpeechRun)return;conversationActive=false;jarvisAudioSpeaking=false;if(wakeOn)startWake();else setState("SYSTEM READY")};try{setState("SPEAKING");const r=await fetch("/api/voice/speak",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:t,voice:"af_bella"})});if(!r.ok)throw Error("Kokoro voice unavailable");const audio=new Audio(URL.createObjectURL(await r.blob()));activeJarvisAudio=audio;audio.onended=()=>{URL.revokeObjectURL(audio.src);activeJarvisAudio=null;resume()};audio.onerror=()=>{URL.revokeObjectURL(audio.src);activeJarvisAudio=null;resume()};await audio.play()}catch(e){add("assistant","Bella voice is temporarily unavailable. I will keep the selected Bella voice and will not switch to another voice.");resume()}}
async function loadMemory(){const r=await fetch("/api/memory"),d=await r.json(),list=$("#memoryList");list.replaceChildren();d.memories.forEach(m=>{const row=document.createElement("div");row.className="memory-row";const span=document.createElement("span");span.textContent=m.note;const del=document.createElement("button");del.textContent="  ";del.title="Delete memory";del.onclick=()=>deleteMemory(m.id);row.append(span,del);list.append(row)})}
async function deleteMemory(id){await fetch("/api/memory",{method:"DELETE",headers:{"Content-Type":"application/json"},body:JSON.stringify({id})});loadMemory()}
$("#saveMemory").onclick=async()=>{const note=$("#memoryInput").value.trim();if(!note)return;const r=await fetch("/api/memory",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({note})}),d=await r.json();if(!r.ok){add("assistant",d.error);return}$("#memoryInput").value="";loadMemory();add("assistant","Saved to JARVIS memory.")};
$("#modelSelect").onchange=async e=>{try{const r=await fetch("/api/model",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({model:e.target.value})}),d=await r.json();if(!r.ok)throw Error(d.error);messages.length=0;box.innerHTML='<div class="empty-state"><div class="empty-mark">   </div><div><b>Model changed</b><span>Start a new conversation.</span></div></div>';$("#modelLabel").textContent="MODEL: "+d.model;setState("SYSTEM READY")}catch(err){add("assistant",err.message);health()}};
$("#chatForm").onsubmit=e=>{e.preventDefault();send($("#prompt").value)};$("#clear").onclick=()=>{messages.length=0;box.innerHTML='<div class="empty-state"><div class="empty-mark">   </div><div><b>Conversation cleared</b><span>Ask JARVIS something new.</span></div></div>'};
document.querySelectorAll("[data-action]").forEach(b=>b.onclick=async()=>{const r=await fetch("/api/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:b.dataset.action})}),d=await r.json();add("assistant",d.message||d.error)});
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
function startWake(){if(!wakeOn||!SR||wakeRec||window.jarvisWhisperRecording||jarvisAudioSpeaking)return;const rec=new SR();wakeRec=rec;rec.continuous=true;rec.interimResults=false;rec.lang="en-US";rec.onstart=()=>{setState(conversationActive?"LISTENING":"STANDING BY")};rec.onresult=e=>{for(let i=e.resultIndex;i<e.results.length;i++){if(!e.results[i].isFinal)continue;const phrase=e.results[i][0].transcript.trim();if(!phrase)continue;lastSpeechAt=Date.now();const wakeOnly=/^(?:(?:hey|okay|ok|open|wake up)\s+)?jarvis[,.!\s]*$/i.test(phrase)||/^(?:hey|okay|ok)\s+jarvis[,.!\s]*$/i.test(phrase);if(conversationActive){if(wakeOnly)continue;conversationActive=false;send(phrase);continue}if(/hey jarvis|ok jarvis|okay jarvis|open jarvis|wake up jarvis|wake up|\bjarvis\b/i.test(phrase)){const wakePattern=/(?:hey\s+jarvis|okay\s+jarvis|ok\s+jarvis|open\s+jarvis|wake up jarvis|wake up|\bjarvis\b)/ig;let wakeMatch,lastWake=null;while((wakeMatch=wakePattern.exec(phrase))!==null)lastWake=wakeMatch;const command=lastWake?phrase.slice(lastWake.index+lastWake[0].length).trim():phrase;if(command){conversationActive=false;send(command)}else{conversationActive=true;setState("LISTENING")}}}};rec.onerror=e=>{if(e.error!=="no-speech"&&e.error!=="aborted"){add("assistant","Microphone listening issue: "+e.error);setState("MICROPHONE CHECK")}};rec.onend=()=>{if(wakeRec===rec)wakeRec=null;if(wakeOn&&!jarvisAudioSpeaking&&!speechSynthesis.speaking){clearTimeout(restartTimer);restartTimer=setTimeout(()=>{if(wakeOn)startWake()},350)}};try{rec.start()}catch{wakeRec=null;setState("WAKE WORD PAUSED")}}
function stopWake(){wakeOn=false;conversationActive=false;awaitingCommand=false;if(wakeRec){const r=wakeRec;wakeRec=null;r.stop()}$("#wakeToggle").classList.remove("on");$("#wakeHint").textContent="Wake phrase paused";setState("SYSTEM READY")}
$("#wakeToggle").onclick=()=>{if(wakeOn)stopWake();else if(!SR)add("assistant","Continuous wake listening requires Microsoft Edge or Chrome.");else{wakeOn=true;$("#wakeToggle").classList.add("on");$("#wakeHint").textContent='Wake phrase ready:    Open Jarvis   ';startWake()}};
$("#mic").onclick=()=>{conversationActive=true;if(!wakeRec)startWake();setState("LISTENING")};$("#settingsBtn").onclick=()=>$("#settings").classList.toggle("hidden");$("#closeSettings").onclick=()=>$("#settings").classList.add("hidden");$("#memoryToggle").onclick=()=>$("#memoryArea").classList.toggle("hidden");$("#attach").onclick=()=>$("#settings").classList.toggle("hidden");
async function coreApi(path,body){
 const response=await fetch(path,{method:body===undefined?"GET":"POST",headers:{"Content-Type":"application/json"},...(body===undefined?{}:{body:JSON.stringify(body)})});
 const data=await response.json().catch(()=>({error:"Invalid response from JARVIS Core"}));
 if(!response.ok&&!(response.status===409&&data.status==="awaiting_approval"))throw Error(data.error||data.detail||("Core request failed: "+response.status));
 return data;
}
function coreText(tag,value,cls){
 const el=document.createElement(tag);if(cls)el.className=cls;el.textContent=String(value??"");return el;
}
function renderCoreRun(run){
 const card=coreText("article","", "core-run-card");
 const head=coreText("div",run.status.replaceAll("_"," ").toUpperCase(),"core-run-head");
 const goal=coreText("p",run.goal,"core-run-goal");card.append(head,goal);
 if(run.plan?.summary)card.append(coreText("p",run.plan.summary,"vision-summary"));
 if(run.plan?.steps?.length){
  const list=document.createElement("ol");list.className="core-step-list";
  run.plan.steps.forEach(step=>{const li=coreText("li",step.tool+(step.rationale?"     "+step.rationale:""));list.append(li)});card.append(list);
 }
 if(run.steps?.length){
  const done=coreText("div","Execution results","core-run-label");card.append(done);
  run.steps.forEach(step=>{const line=coreText("div",(step.ok?"    ":"    ")+step.tool+(step.error?": "+step.error:""),"core-step-result");card.append(line)});
 }
 if(run.status==="awaiting_approval"&&run.approval){
  const approval=coreText("div","","core-approval");
  approval.append(coreText("b","Permission required: "+run.approval.permission));
  approval.append(coreText("p","JARVIS wants to run: "+run.approval.tool));
  approval.append(coreText("pre",JSON.stringify(run.approval.args,null,2)));
  const actions=coreText("div","","core-approval-actions");
  const yes=coreText("button","APPROVE THIS STEP","small-btn");yes.type="button";yes.onclick=async()=>{if(!confirm("Approve this exact JARVIS Core tool step?"))return;yes.disabled=true;try{await coreApi("/api/core/runs/"+run.run_id+"/approve",{});await refreshCoreRuns()}catch(e){alert(e.message);yes.disabled=false}};
  const no=coreText("button","REJECT RUN","text-btn");no.type="button";no.onclick=async()=>{if(!confirm("Reject this step and stop the run?"))return;no.disabled=true;try{await coreApi("/api/core/runs/"+run.run_id+"/reject",{});await refreshCoreRuns()}catch(e){alert(e.message);no.disabled=false}};
  actions.append(yes,no);approval.append(actions);card.append(approval);
 }else if(run.status==="running"){
  const cancel=coreText("button","CANCEL RUN","text-btn");cancel.type="button";cancel.onclick=async()=>{if(!confirm("Cancel this JARVIS Core run?"))return;await coreApi("/api/core/runs/"+run.run_id+"/cancel",{});refreshCoreRuns()};card.append(cancel);
 }
 if(run.answer)card.append(coreText("p",run.answer,"core-run-answer"));
 if(run.error)card.append(coreText("p",run.error,"core-run-error"));
 return card;
}
async function refreshCoreRuns(){
 const list=$("#coreRunList"),status=$("#coreAgentStatus");status.textContent="Checking local Core   ";
 try{
  const [data,tools]=await Promise.all([coreApi("/api/core/runs"),coreApi("/api/core/tools")]);
  list.replaceChildren();
  (data.runs||[]).forEach(run=>list.append(renderCoreRun(run)));
  if(!(data.runs||[]).length)list.append(coreText("div","No agent runs yet. Submit a goal above to begin.","vision-summary"));
  status.textContent="CORE ONLINE    "+(tools.length||0)+" registered tools    "+(data.runs||[]).length+" recent runs";
 }catch(e){status.textContent="CORE CONNECTION ISSUE";list.replaceChildren(coreText("div",e.message,"core-run-error"))}
}
$("#coreAgentBtn").onclick=()=>{$("#coreAgentPanel").classList.remove("hidden");$("#computerPanel").classList.add("hidden");$("#settings").classList.add("hidden");refreshCoreRuns()};
$("#closeCoreAgent").onclick=()=>$("#coreAgentPanel").classList.add("hidden");
$("#refreshCoreRuns").onclick=refreshCoreRuns;
$("#computerBtn").addEventListener("click",()=>$("#coreAgentPanel").classList.add("hidden"));
$("#coreRunForm").onsubmit=async e=>{
 e.preventDefault();const input=$("#coreGoal"),goal=input.value.trim();if(!goal)return;
 const button=$("#coreRunSubmit");button.disabled=true;button.textContent="PLANNING   ";
 try{const run=await coreApi("/api/core/runs",{goal});input.value="";await refreshCoreRuns();if(run.status==="awaiting_approval")$("#coreAgentStatus").textContent="Approval required    review the pending step below";else if(run.status==="completed")$("#coreAgentStatus").textContent="Run completed";else $("#coreAgentStatus").textContent="Run status: "+run.status}
 catch(err){$("#coreAgentStatus").textContent=err.message;await refreshCoreRuns()}
 finally{button.disabled=false;button.textContent="START"}
};
async function loadSpotifySetup(){try{const r=await fetch("/api/spotify/status"),d=await r.json();$("#spotifySetupState").textContent=d.configured?"Secret saved locally":"Client ID ready   secret needed";$("#spotifySetupMessage").textContent=d.configured?"Spotify secret is saved on this PC.":"Client ID is configured. Enter the Client Secret from Spotify Developer Dashboard."; }catch(e){$("#spotifySetupMessage").textContent="Could not read Spotify setup status.";}}
$("#saveSpotifySecret").onclick=async()=>{const input=$("#spotifyClientSecret"),secret=input.value.trim(),button=$("#saveSpotifySecret"),msg=$("#spotifySetupMessage");if(!secret){msg.textContent="Paste your Spotify Client Secret first.";return}button.disabled=true;button.textContent="SAVING ";try{const r=await fetch("/api/spotify/credentials",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({client_secret:secret})}),d=await r.json();if(!r.ok)throw Error(d.error||"Could not save Spotify credentials.");input.value="";msg.textContent=d.message;$("#spotifySetupState").textContent="Secret saved locally";}catch(e){msg.textContent=e.message}finally{button.disabled=false;button.textContent="SAVE SECRET LOCALLY"}};
health();loadMemory();loadSpotifySetup();if(SR)startWake();else add("assistant","Voice recognition is unavailable in this browser. Use Microsoft Edge.");setInterval(health,15000);
(()=>{
 return;const canvas=document.getElementById("neuralCore");if(!canvas)return;
 const ctx=canvas.getContext("2d"),W=640,H=640,CX=320,CY=320,orb=document.getElementById("mic");
 let mode="idle",rotation=0,lastFrame=0,energy=0;
 new MutationObserver(()=>{mode=orb.classList.contains("listening")?"listen":orb.classList.contains("speaking")?"speak":orb.classList.contains("thinking")?"think":"idle"}).observe(orb,{attributes:true,attributeFilter:["class"]});
 let seed=82173;const random=()=>{seed=(seed*16807)%2147483647;return(seed-1)/2147483646};
 const particles=Array.from({length:1900},()=>{const u=random()*2-1,a=random()*Math.PI*2;return{a,u,r:Math.sqrt(1-u*u),size:.35+random()*1.55,phase:random()*6.28,speed:.3+random()*1.6,layer:random(),hue:random(),orbit:random()*6.28}});
 const filaments=Array.from({length:34},()=>({a:random()*6.28,b:random()*6.28,phase:random()*6.28,turns:1.2+random()*2.8,thick:.45+random()*1.2,hue:random()}));
 const sparks=Array.from({length:170},()=>({a:random()*6.28,u:random()*2-1,speed:.15+random()*.5,phase:random()*6.28,size:.5+random()*1.4}));
 const color=(h,a)=>{const n=((h%1)+1)%1*6,i=Math.floor(n),f=n-i,q=Math.round(255*(1-f)),t=Math.round(255*f),v=255,rgb=[[v,t,0],[q,v,0],[0,v,t],[0,q,v],[t,0,v],[v,0,q]][i%6];return 'rgba('+rgb[0]+','+rgb[1]+','+rgb[2]+','+a+')'};
 function project(x,y,z){const ca=Math.cos(rotation),sa=Math.sin(rotation),xx=x*ca-z*sa,zz=x*sa+z*ca,tilt=.19,yy=y*Math.cos(tilt)-zz*Math.sin(tilt),depth=y*Math.sin(tilt)+zz*Math.cos(tilt),pers=1/(1+depth*.2);return{x:CX+xx*260*pers,y:CY+yy*260*pers,z:depth,pers}}
 function frame(now){const dt=Math.min(40,now-lastFrame||16);lastFrame=now;const active=mode==="speak"?1.25:mode==="listen"?1.12:mode==="think"?.92:1;energy+=(active-energy)*.045;rotation+=dt*(mode==="speak"?.00095:mode==="listen"?.00072:.00034);ctx.clearRect(0,0,W,H);
 const halo=ctx.createRadialGradient(CX,CY,8,CX,CY,285);halo.addColorStop(0,color((now*.000025)%1,.17));halo.addColorStop(.35,color((now*.000025+.12)%1,.07));halo.addColorStop(1,"rgba(0,0,0,0)");ctx.fillStyle=halo;ctx.fillRect(0,0,W,H);ctx.globalCompositeOperation="lighter";
 // Layered plasma filaments form a dense, breathing three-dimensional energy cloud.
 filaments.forEach((f,j)=>{ctx.beginPath();for(let i=0;i<=240;i++){const q=i/240*Math.PI*2*f.turns+f.phase+now*.00018*(j%2?1:-1),lat=Math.sin(q*1.45+f.b)*.88,rad=174+26*Math.sin(q*2.8+f.a)+14*Math.cos(q*5.1+f.phase),x=Math.cos(q+f.a)*Math.cos(lat)*rad,y=Math.sin(lat)*rad,z=Math.sin(q+f.a)*Math.cos(lat)*rad,p=project(x/260,y/260,z/260);if(i===0)ctx.moveTo(p.x,p.y);else ctx.lineTo(p.x,p.y)}ctx.strokeStyle=color((.56+f.hue*.15+now*.00002)%1,.16+(j%5)*.045);ctx.lineWidth=f.thick;ctx.stroke()});
 // Fine particles drift across the shell, with depth, shimmer and spectral color shifts.
 particles.forEach((p,i)=>{const wave=Math.sin(now*.00065*p.speed+p.phase)*.045,lat=Math.asin(p.u)+wave,a=p.a+rotation*(.75+p.layer*.9),breath=1+(.025+energy*.07)*Math.sin(now*.0014+p.phase),radius=(.78+.22*Math.sin(p.a*5+p.phase+now*.0004))*breath,x=Math.cos(a)*Math.cos(lat)*p.r*radius,y=Math.sin(lat)*radius,z=Math.sin(a)*Math.cos(lat)*p.r*radius,pt=project(x,y,z),front=Math.max(.12,Math.min(1,.42+pt.z*.48)),alpha=(.16+pt.pers*.65)*front,h=(.55+p.hue*.15+now*.000025+(mode==="speak"?.025:0))%1,size=p.size*(.65+pt.pers*.75);ctx.fillStyle=color(h,alpha);ctx.beginPath();ctx.arc(pt.x,pt.y,size,0,Math.PI*2);ctx.fill();if(i%23===0){ctx.fillStyle=color((h+.08)%1,alpha*.17);ctx.beginPath();ctx.arc(pt.x,pt.y,size*4.5,0,Math.PI*2);ctx.fill()}});
 // Outward-moving sparks create the starburst / particle-explosion effect in the reference.
 sparks.forEach((s,i)=>{const pulse=(now*.00022*s.speed+s.phase)%(Math.PI*2),dist=226+Math.sin(pulse)*23+(mode==="speak"?Math.sin(pulse*2)*18:0),lat=Math.asin(s.u),a=s.a+rotation*1.4,x=Math.cos(a)*Math.cos(lat)*dist,y=Math.sin(lat)*dist,z=Math.sin(a)*Math.cos(lat)*dist,p=project(x/260,y/260,z/260);ctx.fillStyle=color((.54+i/170*.15+now*.000025)%1,.24);ctx.beginPath();ctx.arc(p.x,p.y,s.size*p.pers,0,Math.PI*2);ctx.fill()});
 // Electric cyan/violet spherical rim and dark glass nucleus, matching the supplied orb.
 ctx.globalCompositeOperation="source-over";
 const rim=ctx.createRadialGradient(CX,CY,158,CX,CY,244);rim.addColorStop(0,"rgba(20,30,70,0)");rim.addColorStop(.72,"rgba(31,105,255,.035)");rim.addColorStop(.88,"rgba(22,198,255,.18)");rim.addColorStop(.95,"rgba(126,67,255,.2)");rim.addColorStop(1,"rgba(0,0,0,0)");ctx.fillStyle=rim;ctx.beginPath();ctx.arc(CX,CY,246,0,Math.PI*2);ctx.fill();
 const core=ctx.createRadialGradient(CX-24,CY-38,4,CX,CY,126);core.addColorStop(0,"rgba(7,10,30,.92)");core.addColorStop(.72,"rgba(5,8,28,.84)");core.addColorStop(1,"rgba(8,14,44,.08)");ctx.fillStyle=core;ctx.beginPath();ctx.arc(CX,CY,126,0,Math.PI*2);ctx.fill();
 // Central OpenJarvis infinity mark, neon cyan fading into violet.
 ctx.save();ctx.lineCap="round";ctx.lineJoin="round";ctx.shadowBlur=20;ctx.shadowColor="#4c7dff";
 const lg=ctx.createLinearGradient(CX-70,CY-20,CX+70,CY+18);lg.addColorStop(0,"#16dcff");lg.addColorStop(.48,"#417dff");lg.addColorStop(1,"#bd36ff");ctx.strokeStyle=lg;ctx.lineWidth=17;ctx.beginPath();ctx.moveTo(CX-61,CY-4);ctx.bezierCurveTo(CX-39,CY-48,CX-9,CY-48,CX+8,CY-5);ctx.bezierCurveTo(CX+31,CY+42,CX+53,CY+33,CX+64,CY-4);ctx.bezierCurveTo(CX+45,CY-45,CX+16,CY-45,CX-4,CY-4);ctx.bezierCurveTo(CX-26,CY+39,CX-49,CY+37,CX-61,CY-4);ctx.stroke();ctx.shadowBlur=0;
 ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillStyle="#f7f5ff";ctx.font="600 35px 'Space Grotesk',Arial";ctx.fillText("OpenJarvis",CX,CY+55);ctx.fillStyle="rgba(221,226,255,.85)";ctx.font="500 15px 'DM Sans',Arial";ctx.letterSpacing="4px";ctx.fillText("AI BRAIN",CX,CY+83);ctx.restore();ctx.globalCompositeOperation="lighter";
 for(let n=0;n<7;n++){ctx.beginPath();ctx.ellipse(CX,CY,190+n*10,54+n*12,rotation*(n%2?-.7:.55)+n*.8,0,Math.PI*2);ctx.strokeStyle=color((.57+n*.035+now*.000015)%1,.09+n*.014);ctx.lineWidth=.8;ctx.stroke()}
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
  try{statusMsg("Capturing Windows screen   ");const r=await fetch("/api/computer/screenshot",{cache:"no-store"});if(!r.ok){const d=await r.json();throw Error(d.error||"Screen capture failed")}const blob=await r.blob();const old=shot.dataset.url;if(old)URL.revokeObjectURL(old);const url=URL.createObjectURL(blob);shot.dataset.url=url;shot.src=url;statusMsg("Screen connected    "+new Date().toLocaleTimeString())}
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
   statusMsg("JARVIS is examining the screen and planning   ");
   const d=await api("/api/computer/plan",{task:task.trim()});pendingPlan=d;
   const preview=$("#taskPreview");preview.replaceChildren();
   const summary=document.createElement("p");summary.textContent=d.summary;preview.append(summary);
   (d.steps||[]).forEach((step,i)=>{const row=document.createElement("div");row.className="plan-step";row.textContent=(i+1)+". "+(step.action==="type"?"Type: "+step.text:step.action==="open_url"?"Open website: "+step.url:step.action==="press"?"Press "+step.key:step.action==="hotkey"?"Shortcut "+step.keys.join("+"):step.action==="wait"?"Wait "+step.seconds+" seconds":step.action+" at "+(step.x??"center")+", "+(step.y??"center"));preview.append(row)});
   $("#executePlan").disabled=!(d.steps||[]).length;
   if(!d.steps?.length){const note=document.createElement("small");note.textContent="JARVIS did not produce safe, actionable steps for this request.";preview.append(note)}
   panel.classList.remove("hidden");$("#settings").classList.add("hidden");
   statusMsg("Plan ready    "+d.steps.length+" step(s)    review before execution");
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
  try{const d=await api("/api/computer/execute-plan",{confirm:true,steps:pendingPlan.steps});pendingPlan=null;$("#executePlan").disabled=true;$("#taskPreview").textContent="Completed "+d.completed+" action(s).";statusMsg("Task completed    "+d.completed+" action(s)");await refreshScreen();await refreshStatus()}
  catch(e){statusMsg(e.message);add("assistant","The computer task stopped: "+e.message);refreshScreen()}
 };
 async function refreshStatus(){
  try{const d=await api("/api/computer/status");$("#activeWindow").textContent="Active window: "+(d.active_window||"Desktop");$("#processCount").textContent="Running processes: "+d.process_count+"    Screen: "+d.screen.width+"    "+d.screen.height}
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
   statusMsg("Inspected "+(d.window||"active window")+"    "+(d.controls?.length||0)+" controls")
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
   if(d.parent){const up=document.createElement("button");up.className="file-item";up.textContent="    Parent folder";up.onclick=()=>browse(d.parent);list.append(up)}
   d.items.forEach(item=>{const row=document.createElement("div");row.className="file-item";const open=document.createElement("button");open.textContent=(item.type==="folder"?"     ":"     ")+item.name;open.onclick=()=>item.type==="folder"?browse(item.path):fileAction({action:"open",path:item.path});const tools=document.createElement("span");if(item.type==="file"){const rename=document.createElement("button");rename.textContent="RENAME";rename.onclick=()=>{const name=prompt("New name",item.name);if(name)fileAction({action:"rename",path:item.path,name})};tools.append(rename)}const trash=document.createElement("button");trash.textContent="TRASH";trash.onclick=()=>{if(confirm("Send "+item.name+" to the Windows Recycle Bin?"))fileAction({action:"trash",path:item.path,confirm:true})};tools.append(trash);row.append(open,tools);list.append(row)});
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


// Visual Workflow Studio     saved locally; dispatches the configured pipeline to JARVIS Core.
(()=> {
 const $=s=>document.querySelector(s),panel=$('#workflowPanel'),canvas=$('#jarvisWorkflowCanvas'),nodesEl=$('#jarvisWorkflowNodes'),wires=$('#jarvisWorkflowWires');
 if(!panel||!canvas)return;
 const seed=[
  {id:'input',kind:'INPUT',title:'User request',detail:'Capture the goal, context and constraints.',x:40,y:100},
  {id:'reason',kind:'AI REASONING',title:'Understand & plan',detail:'Interpret intent and create a safe ordered plan.',x:300,y:100},
  {id:'memory',kind:'MEMORY',title:'Recall memory',detail:'Retrieve relevant saved context before acting.',x:560,y:25},
  {id:'tools',kind:'TOOLS',title:'Execute tools',detail:'Run registered tools within their permissions.',x:560,y:205},
  {id:'recover',kind:'RECOVERY',title:'Recover errors',detail:'Diagnose failures and re-plan within safe limits.',x:820,y:205},
  {id:'verify',kind:'VERIFY',title:'Verify result',detail:'Check tool outcomes and prepare the final response.',x:1080,y:100}
 ];
 const seedLinks=[['input','reason'],['reason','memory'],['reason','tools'],['tools','recover'],['memory','verify'],['recover','verify']];
 let nodes=load('jarvis.workflow.nodes',seed),links=load('jarvis.workflow.links',seedLinks),selected='reason',connecting=null,drag=null,nodeStatuses={};
 function load(k,f){try{return JSON.parse(localStorage.getItem(k))||f}catch{return f}}
 function save(){localStorage.setItem('jarvis.workflow.nodes',JSON.stringify(nodes));localStorage.setItem('jarvis.workflow.links',JSON.stringify(links))}
 function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
 function render(){
  nodesEl.innerHTML=nodes.map(n=>'<div class="j-workflow-node '+(n.id===selected?'selected ':'')+(n.id===connecting?'connecting':'')+' node-status-'+(nodeStatuses[n.id]||'idle')+'" data-id="'+esc(n.id)+'" style="left:'+n.x+'px;top:'+n.y+'px"><div class="j-node-head"><span>'+esc(n.kind)+'</span><button class="j-node-port" data-connect="'+esc(n.id)+'">   </button></div><b>'+esc(n.title)+'</b><p>'+esc(n.detail)+'</p><small>    '+esc((nodeStatuses[n.id]||'READY').toUpperCase())+'</small></div>').join('');
  wires.innerHTML=links.map(([a,b])=>{const A=nodes.find(n=>n.id===a),B=nodes.find(n=>n.id===b);if(!A||!B)return '';const x1=A.x+190,y1=A.y+52,x2=B.x,y2=B.y+52,m=(x1+x2)/2;return '<path d="M '+x1+' '+y1+' C '+m+' '+y1+', '+m+' '+y2+', '+x2+' '+y2+'" fill="none" stroke="#5bd9bd" stroke-width="2"/><path d="M '+(x2-8)+' '+(y2-5)+' L '+x2+' '+y2+' L '+(x2-8)+' '+(y2+5)+'" fill="none" stroke="#5bd9bd" stroke-width="2"/>'}).join('');
  $('#workflowCount').textContent='PIPELINE    '+nodes.length+' NODES    '+links.length+' WIRES';
  const n=nodes.find(x=>x.id===selected);$('#workflowNodeName').value=n?.title||'';$('#workflowNodeDetail').value=n?.detail||'';$('#workflowConnectHint').textContent=connecting?'Connecting from '+(nodes.find(x=>x.id===connecting)?.title||'node')+'. Select a destination node.':'Select a node to edit. Click its dot then another node to connect.';
 }
 nodesEl.addEventListener('pointerdown',e=>{const el=e.target.closest('.j-workflow-node');if(!el||e.target.closest('.j-node-port'))return;const n=nodes.find(x=>x.id===el.dataset.id);selected=n.id;drag={id:n.id,x:e.clientX,y:e.clientY};el.setPointerCapture(e.pointerId);render()});
 nodesEl.addEventListener('pointermove',e=>{if(!drag)return;const n=nodes.find(x=>x.id===drag.id);n.x=Math.max(0,n.x+e.clientX-drag.x);n.y=Math.max(0,n.y+e.clientY-drag.y);drag={id:drag.id,x:e.clientX,y:e.clientY};const el=nodesEl.querySelector('[data-id="'+drag.id+'"]');if(el){el.style.left=n.x+'px';el.style.top=n.y+'px'}drawWires()});
 nodesEl.addEventListener('pointerup',()=>{if(drag){drag=null;save();render()}});
 nodesEl.addEventListener('click',e=>{const port=e.target.closest('[data-connect]'),el=e.target.closest('.j-workflow-node');if(port){const id=port.dataset.connect;if(!connecting)connecting=id;else{if(connecting!==id&&!links.some(l=>l[0]===connecting&&l[1]===id))links.push([connecting,id]);connecting=null}selected=id;save();render();return}if(el){selected=el.dataset.id;render()}});
 function drawWires(){wires.innerHTML=links.map(([a,b])=>{const A=nodes.find(n=>n.id===a),B=nodes.find(n=>n.id===b);if(!A||!B)return '';const x=A.x+190,y=A.y+52,X=B.x,Y=B.y+52,m=(x+X)/2;return '<path d="M '+x+' '+y+' C '+m+' '+y+', '+m+' '+Y+', '+X+' '+Y+'" fill="none" stroke="#5bd9bd" stroke-width="2"/>'}).join('')}
 $('#workflowNodeName').addEventListener('input',e=>{const n=nodes.find(x=>x.id===selected);if(n){n.title=e.target.value;save();const el=nodesEl.querySelector('[data-id="'+selected+'"] b');if(el)el.textContent=n.title}});
 $('#workflowNodeDetail').addEventListener('input',e=>{const n=nodes.find(x=>x.id===selected);if(n){n.detail=e.target.value;save();const el=nodesEl.querySelector('[data-id="'+selected+'"] p');if(el)el.textContent=n.detail}});
 $('#workflowDeleteNode').onclick=()=>{if(nodes.length<=2){$('#workflowLog').textContent='Keep at least two nodes in the workflow.';return}nodes=nodes.filter(n=>n.id!==selected);links=links.filter(l=>l[0]!==selected&&l[1]!==selected);selected=nodes[0].id;save();render()};
 document.querySelectorAll('[data-add-node]').forEach(b=>b.onclick=()=>{const kind=b.dataset.addNode,id=kind+'-'+Date.now(),names={reason:'AI reasoning',memory:'Memory lookup',tool:'Tool action',approval:'Approval gate',verify:'Verification'};nodes.push({id,kind:kind.toUpperCase(),title:names[kind],detail:'Describe this workflow step.',x:100+(nodes.length%4)*250,y:390+Math.floor(nodes.length/4)*150});selected=id;save();render()});
 $('#workflowReset').onclick=()=>{if(!confirm('Reset the workflow to the default JARVIS pipeline?'))return;nodes=JSON.parse(JSON.stringify(seed));links=JSON.parse(JSON.stringify(seedLinks));selected='reason';connecting=null;save();render();$('#workflowLog').textContent='Default workflow restored.'};
 $('#workflowRun').onclick=async()=>{const degree=Object.fromEntries(nodes.map(n=>[n.id,0]));links.forEach(([a,b])=>{if(degree[a]!==undefined&&degree[b]!==undefined)degree[b]++});const queue=nodes.filter(n=>degree[n.id]===0),sorted=[];while(queue.length){const current=queue.shift();sorted.push(current);links.filter(([a])=>a===current.id).forEach(([,b])=>{if(degree[b]!==undefined&&--degree[b]===0)queue.push(nodes.find(n=>n.id===b))})}if(sorted.length!==nodes.length){$('#workflowLog').textContent='Cannot run: the workflow contains a dependency cycle.';return}const button=$('#workflowRun');button.disabled=true;$('#workflowStatus').textContent='Submitting pipeline to JARVIS Core   ';$('#workflowLog').textContent='JARVIS Core is planning this workflow. Execution and any required approvals will appear in CORE AGENT.';try{nodeStatuses=Object.fromEntries(nodes.map(n=>[n.id,'queued']));render();const result=await coreApi('/api/core/workflow/runs',{mission,nodes,links});nodeStatuses=Object.fromEntries((result.nodes||[]).map(n=>[n.id,n.status]));render();const details=(result.nodes||[]).map(n=>n.title+': '+n.status+(n.error?'     '+n.error:'')+(n.output?'\\n'+String(n.output).slice(0,500):'')).join('\\n\\n');$('#workflowLog').textContent='Workflow '+result.id+'    '+result.status+'\\n\\n'+details;$('#workflowStatus').textContent='Node execution    '+result.status;await refreshCoreRuns()}catch(e){$('#workflowLog').textContent='Workflow failed to dispatch: '+e.message;$('#workflowStatus').textContent='Dispatch error'}finally{button.disabled=false}};
 $('#workflowBtn').onclick=()=>{panel.classList.remove('hidden');$('#coreAgentPanel').classList.add('hidden');$('#computerPanel').classList.add('hidden');$('#settings').classList.add('hidden');render()};
 $('#closeWorkflow').onclick=()=>panel.classList.add('hidden');
 $('#computerBtn').addEventListener('click',()=>panel.classList.add('hidden'));
 $('#coreAgentBtn').addEventListener('click',()=>panel.classList.add('hidden'));
 render();
 if(new URLSearchParams(location.search).get('workflow')==='1'){panel.classList.remove('hidden');$('#coreAgentPanel').classList.add('hidden');$('#computerPanel').classList.add('hidden')}
})();



/* Local microphone capture -> faster-whisper on this PC. */
window.jarvisWhisperRecording=false;
let jarvisWhisperRecorder=null,jarvisWhisperStream=null,jarvisWhisperTimer=null;
async function startWhisperCapture(){
 if(window.jarvisWhisperRecording){if(jarvisWhisperRecorder&&jarvisWhisperRecorder.state!=="inactive")jarvisWhisperRecorder.stop();return}
 if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){add("assistant","This browser does not support local microphone recording. Use the latest Microsoft Edge or Chrome.");return}
 if(wakeRec){const old=wakeRec;wakeRec=null;try{old.stop()}catch{}}
 clearTimeout(restartTimer);
 try{
  jarvisWhisperStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
  const mime=MediaRecorder.isTypeSupported("audio/webm;codecs=opus")?"audio/webm;codecs=opus":(MediaRecorder.isTypeSupported("audio/webm")?"audio/webm":"");
  jarvisWhisperRecorder=new MediaRecorder(jarvisWhisperStream,mime?{mimeType:mime}:{});
  const chunks=[];
  jarvisWhisperRecorder.ondataavailable=e=>{if(e.data&&e.data.size)chunks.push(e.data)};
  jarvisWhisperRecorder.onerror=e=>{add("assistant","Microphone recording failed: "+(e.error?.message||"unknown error"));};
  jarvisWhisperRecorder.onstop=async()=>{
   window.jarvisWhisperRecording=false;
   if(jarvisWhisperStream)jarvisWhisperStream.getTracks().forEach(track=>track.stop());
   jarvisWhisperStream=null;
   clearTimeout(jarvisWhisperTimer);
   try{
    const blob=new Blob(chunks,{type:jarvisWhisperRecorder.mimeType||"audio/webm"});
    if(blob.size<1500){setState("SYSTEM READY");add("assistant","I didn't capture enough audio. Tap the core and try again.");if(wakeOn)setTimeout(startWake,500);return}
    setState("THINKING");add("system","Sending audio to local Whisper for transcription   ");
    const form=new FormData();form.append("audio",blob,"jarvis-recording.webm");
    const response=await fetch("/api/voice/transcribe",{method:"POST",body:form});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||"Local transcription failed");
    const transcript=String(result.text||"").trim();
    if(!transcript){add("assistant","I couldn't detect speech in that recording. Please try again.");setState("SYSTEM READY");if(wakeOn)setTimeout(startWake,500);return}
    add("system","Whisper heard: "+transcript);
    await send(transcript);
   }catch(error){add("assistant","Local Whisper transcription failed: "+error.message);setState("SYSTEM READY");if(wakeOn)setTimeout(startWake,500)}
  };
  window.jarvisWhisperRecording=true;
  jarvisWhisperRecorder.start(250);
  setState("LISTENING");
  add("system","Listening with the local microphone. Tap the core to finish, or wait up to 7 seconds.");
  jarvisWhisperTimer=setTimeout(()=>{if(jarvisWhisperRecorder?.state==="recording")jarvisWhisperRecorder.stop()},7000);
 }catch(error){
  window.jarvisWhisperRecording=false;
  if(jarvisWhisperStream)jarvisWhisperStream.getTracks().forEach(track=>track.stop());
  jarvisWhisperStream=null;
  add("assistant",error.name==="NotAllowedError"?"Microphone permission is blocked. Allow microphone access for JARVIS in Edge or Chrome.":"Could not access the microphone: "+error.message);
  setState("SYSTEM READY");
  if(wakeOn)setTimeout(startWake,500);
 }
}

/* OpenJarvis reference-dashboard navigation bindings */
(()=> {
 const click=id=>{const el=document.getElementById(id);if(el)el.click()};
 const nav=(id)=>{document.querySelectorAll(".rail-item").forEach(x=>x.classList.remove("active"));const el=document.getElementById(id);if(el)el.classList.add("active")};
 const bind=(id,fn)=>{const el=document.getElementById(id);if(el)el.addEventListener("click",fn)};
 bind("railAgents",()=>{nav("railAgents")});
 bind("railWorkflows",()=>{nav("railWorkflows");click("workflowBtn")});
 bind("railPC",()=>{nav("railPC");click("computerBtn")});
 bind("railMemory",()=>{nav("railMemory");click("settingsBtn");setTimeout(()=>{const m=document.getElementById("memoryArea");if(m&&!m.classList.contains("hidden"))return;click("memoryToggle")},80)});
 bind("railTools",()=>{nav("railTools")});
 bind("railSettings",()=>{nav("railSettings");click("settingsBtn")});
 bind("quickAgent",()=>click("coreAgentBtn"));
 bind("quickWorkflow",()=>click("workflowBtn"));
 bind("quickScreen",()=>{click("computerBtn");setTimeout(()=>click("understandScreen"),250)});
 bind("quickVideo",()=>{const p=document.getElementById("prompt");if(p){p.value="Help me create a video. Ask me for the source footage and style.";p.focus()}});
 bind("micQuick",()=>{if(typeof startWhisperCapture==="function")startWhisperCapture();else click("mic")});
 document.querySelectorAll('[data-nav="chat"]').forEach(el=>el.addEventListener("click",()=>{nav(null);document.getElementById("prompt")?.focus()}));
})();



