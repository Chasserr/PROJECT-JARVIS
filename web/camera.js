(()=>{
  const $=s=>document.querySelector(s);
  const panel=$("#cameraPanel"),video=$("#jarvisCameraVideo"),canvas=$("#jarvisCameraCanvas"),
        still=$("#cameraStill"),select=$("#cameraSelect"),status=$("#cameraStatus"),answer=$("#cameraAnswer"),
        start=$("#cameraStart"),stop=$("#cameraStop"),analyze=$("#cameraAnalyze"),
        capture=$("#cameraCapture"),refresh=$("#cameraRefresh"),prompt=$("#cameraPrompt");
  if(!panel)return;
  let stream=null,serverDevices=[];

  function setStatus(text){if(status)status.textContent=text}

  function close(){if(stream){stream.getTracks().forEach(t=>t.stop());stream=null}
    video.srcObject=null;start.disabled=false;stop.disabled=true;analyze.disabled=true;
    if(capture)capture.disabled=true;setStatus("Camera disconnected    point the camera at something and connect")}

  /* The JARVIS runtime owns device discovery: it reads what Windows reports
     through DirectShow, which is what the agent's camera tools use too. */
  async function refreshDevices(){
    setStatus("Scanning cameras…");
    try{
      const r=await fetch("/api/camera/status",{cache:"no-store"});
      const d=await r.json();
      if(!r.ok||d.available===false)throw new Error(d.error||("runtime returned "+r.status));
      serverDevices=d.devices||[];
      select.replaceChildren(new Option("Choose camera",""));
      serverDevices.forEach(x=>select.add(new Option(x.name,x.name)));
      if(d.selected)select.value=d.selected;
      else if(d.default)select.value=d.default;
      if(!serverDevices.length){setStatus("No camera detected. Start Camo or Iriun, then press REFRESH.");return}
      /* The runtime captures without the browser stream, so a still is always allowed. */
      if(capture)capture.disabled=false;
      setStatus(serverDevices.length+" camera(s): "+serverDevices.map(x=>x.name).join(", ")+
        (d.last_error?"    last error: "+d.last_error.slice(0,120):""));
    }catch(e){
      setStatus("Camera diagnostics unavailable: "+e.message);
    }
    try{
      const all=await navigator.mediaDevices.enumerateDevices();
      const browserCams=all.filter(d=>d.kind==="videoinput");
      if(!browserCams.length)setStatus(status.textContent+"    browser preview needs camera permission");
    }catch(e){setStatus(status.textContent+"    browser preview unavailable: "+e.message)}
  }

  start.onclick=async()=>{
    try{
      if(!navigator.mediaDevices?.getUserMedia)throw Error("Camera access needs a secure local context: open http://127.0.0.1:8765.");
      const chosen=select.value||"";
      const constraints={audio:false,video:chosen?{deviceId:{ideal:chosen},width:{ideal:1280},height:{ideal:720}}:{width:{ideal:1280},height:{ideal:720}}};
      stream=await navigator.mediaDevices.getUserMedia(constraints);
      video.srcObject=stream;await video.play();
      $("#cameraPlaceholder").hidden=true;if(still)still.hidden=true;
      start.disabled=true;stop.disabled=false;analyze.disabled=false;if(capture)capture.disabled=false;
      setStatus("Camera connected · live preview running · frames stay on this PC");
    }catch(e){
      start.disabled=false;
      const denied=/NotAllowed|Permission/i.test(e.name+e.message);
      setStatus(denied
        ? "Browser blocked camera access. Allow this site to use the camera, or use CAPTURE STILL (the JARVIS runtime grabs the frame directly)."
        : "Camera connect failed: "+e.message);
      if(capture)capture.disabled=false;
    }
  };

  stop.onclick=close;
  refresh&&(refresh.onclick=refreshDevices);

  async function grabFrame(){
    const body=select.value?{device:select.value}:{};
    const r=await fetch("/api/camera/capture",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||("capture returned "+r.status));
    return d;
  }

  capture&&(capture.onclick=async()=>{
    capture.disabled=true;setStatus("Capturing a still frame…");
    try{
      const d=await grabFrame();
      if(still){still.src="/api/camera/frame?t="+Date.now();still.hidden=false;}
      $("#cameraPlaceholder").hidden=true;
      analyze.disabled=false;
      setStatus("Captured "+d.width+"x"+d.height+" from "+d.device+(d.blank_frame?
        "    WARNING: the device returned a pure black frame, so nothing is in front of it":"")+
        "    saved to "+d.path);
    }catch(e){setStatus("Capture failed: "+e.message);}
    finally{capture.disabled=false;}
  });

  function dataUrlFromVideo(){
    canvas.width=video.videoWidth||1280;canvas.height=video.videoHeight||720;
    canvas.getContext("2d").drawImage(video,0,0,canvas.width,canvas.height);
    return canvas.toDataURL("image/jpeg",0.9);
  }

  async function askRuntime(image,promptText){
    const r=await fetch("/api/camera/analyze",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({image,prompt:promptText})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||("vision returned "+r.status));
    return d;
  }

  analyze.onclick=async()=>{
    analyze.disabled=true;answer.textContent="JARVIS is looking at the frame…";
    const question=(prompt.value||"Describe what you see and identify important objects.").trim();
    try{
      let result;
      if(stream&&video.videoWidth){result=await askRuntime(dataUrlFromVideo(),question)}
      else{
        const shot=await grabFrame();
        if(still){still.src="/api/camera/frame?t="+Date.now();still.hidden=false;$("#cameraPlaceholder").hidden=true}
        const img=await fetch("/api/camera/frame?t="+Date.now());
        const blob=await img.blob();
        const b64=await new Promise(res=>{const fr=new FileReader();fr.onload=()=>res(String(fr.result).split(",")[1]);fr.readAsDataURL(blob)});
        result=await askRuntime(b64,question);
        if(shot.blank_frame)result.description="(the camera returned a black frame) "+(result.description||"");
      }
      answer.textContent=(result.description||"No description returned.")+
        (result.model?"    ["+result.model+" · local]":"");
    }catch(e){answer.textContent="Camera vision failed: "+e.message;}
    finally{analyze.disabled=false;}
  };

  $("#cameraBtn").onclick=()=>{panel.classList.remove("hidden");refreshDevices()};
  $("#cameraClose").onclick=()=>{close();panel.classList.add("hidden")};
})();
