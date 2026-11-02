/* Relay V0.2. The video merge is performed by the server, never manually. */
'use strict';
const $=id=>document.getElementById(id),root=$('root');
const cfg=JSON.parse(document.getElementById('relay-config')?.textContent || '{"mode":"start"}');
const urlAbsolute=path=>new URL(path,location.origin).href;
let stream=null,recorder=null,selection=null,selectedUrl=null,fileShare=null;
const safe=txt=>String(txt).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const btn=(id,label,variant='')=>`<button type="button" id="${id}" class="btn ${variant}">${label}</button>`;
const note=txt=>`<div class="notice">${txt}</div>`;
function status(txt,err=false){const e=$('status');if(e){e.textContent=txt;e.className='status'+(err?' error':'')}}
function stopCam(){try{stream?.getTracks().forEach(x=>x.stop())}catch(e){}stream=null}
function render(){
 if(cfg.mode==='start'||cfg.mode==='join') return recordingPage();
 if(cfg.mode==='watch')return watchPage();
 if(cfg.mode==='delete')return deletePage();
}
function recordingPage(){
 const adding=cfg.mode==='join';
 root.innerHTML=`<div class="small"><span class="n">${adding?'YOUR TURN':'START A RELAY'}</span> · ${adding?'Watch → record → share':'Record → invite'}</div>
 <h1>${adding?'Add yourself to this moment.':'A video that travels through friends.'}</h1>
 <p>${adding?'Watch what your friends made. Record your three seconds; Relay joins you to the video immediately.':'Record a tiny clip, invite one friend, and they make the next part of the same video.'}</p>
 ${adding?`<video id="watch-video" controls playsinline preload="metadata" src="${safe(cfg.movie_url)}"></video><p class="small">${cfg.clips} ${cfg.clips===1?'clip':'clips'} so far · Your recording will be added to the end.</p>`:''}
 <div class="card"><div class="stage" id="stage"><span class="emoji">${adding?'🙌':'🎥'}</span><video id="cam" class="camera hidden" autoplay muted playsinline></video><video id="selected" class="camera hidden" controls playsinline></video><div class="count hidden" id="counter">3</div></div>
 <div class="hint">${adding?'Start with your palm covering the camera. Uncover it and reach toward your friend.':'Finish with your palm covering the camera to hide the handoff.'}</div>
 <div class="bar"><div id="bar-progress"></div></div>
 <label class="consent"><input type="checkbox" id="consent"/><span>I am an adult, have permission from anyone visible, and agree to share via a private link. Anyone who gets the link can watch. Free test recordings may disappear after the host sleeps.</span></label>
 ${cfg.protected?'<p><input id="pilot-code" type="password" placeholder="Private pilot code" autocomplete="off"/></p>':''}
 <div class="actions">${btn('record','● Record 3 seconds')}${btn('phone','Use my phone camera','alt')}${btn('upload','Save & automatically merge','alt hidden')}</div>
 <input type="file" id="file" accept="video/*" capture="user"/><p class="status" id="status" aria-live="polite"></p>
 ${note('No editing. After recording, Relay creates the combined video automatically. Keep this page open while it uploads.')}</div>`;
 $('record').onclick=record3;
 $('phone').onclick=()=>$('file').click();
 $('file').onchange=()=>{if($('file').files?.[0]){selection=$('file').files[0];showSelection();if($('consent').checked)uploadNow()}};
 $('upload').onclick=uploadNow;
 if(cfg.protected){const code=new URLSearchParams(location.hash.slice(1)).get('pilot');if(code)$('pilot-code').value=code;}
}
function showSelection(){
 stopCam();$('cam').classList.add('hidden');
 if(selectedUrl)URL.revokeObjectURL(selectedUrl);
 selectedUrl=URL.createObjectURL(selection);
 $('selected').src=selectedUrl;$('selected').classList.remove('hidden');
 $('record').textContent='↺ Retake 3 seconds';$('upload').classList.remove('hidden');
 status('Clip ready. Tap “Save & automatically merge”.');
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function record3(){
 if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){status('Use “Use my phone camera” on this device.',true);return}
 try{
  $('record').disabled=true;status('Opening camera…');
  stopCam();stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:{ideal:720},height:{ideal:1280}},audio:true});
  $('cam').srcObject=stream;$('cam').classList.remove('hidden');
  const types=['video/mp4;codecs=avc1.42E01E,mp4a.40.2','video/webm;codecs=vp8,opus','video/webm','video/mp4'];
  const mime=types.find(t=>MediaRecorder.isTypeSupported(t));
  recorder=new MediaRecorder(stream,mime?{mimeType:mime}:{});
  const chunks=[];recorder.ondataavailable=e=>{if(e.data?.size)chunks.push(e.data)};
  for(let count=3;count>0;count--){$('counter').textContent=String(count);$('counter').classList.remove('hidden');await sleep(450)}
  $('counter').classList.add('hidden');status('Recording now…');
  const done=new Promise((resolve,reject)=>{recorder.onstop=resolve;recorder.onerror=reject});
  recorder.start(250);
  const started=Date.now();const tick=setInterval(()=>{$('bar-progress').style.width=`${Math.min(100,(Date.now()-started)/3000*100)}%`},75);
  await sleep(3000);if(recorder.state!=='inactive')recorder.stop();await done;clearInterval(tick);
  selection=new Blob(chunks,{type:recorder.mimeType||mime||'video/webm'});
  if(selection.size<1000)throw new Error('Recording appears empty');
  // User has opted in through checkbox; merge automatically with zero editor steps.
  showSelection();
  if($('consent').checked)await uploadNow();
 }catch(err){status('Camera unavailable. Try “Use my phone camera”. '+(err?.message||''),true);stopCam()}
 finally{$('record').disabled=false}
}
async function uploadNow(){
 if(!selection){status('Record a clip first.',true);return}
 if(!$('consent').checked){status('Please agree to private-link sharing first.',true);return}
 if(selection.size>15*1024*1024){status('Clip is too large. Please make a shorter recording.',true);return}
 const form=new FormData();form.append('clip',selection,selection.name|| (selection.type.includes('mp4')?'clip.mp4':'clip.webm'));
 if(cfg.protected)form.append('pilot_code',$('pilot-code').value);
 $('record').disabled=true;$('phone').disabled=true;$('upload').disabled=true;
 status('Combining your recording…  ◌');
 try{
  const response=await fetch(cfg.mode==='join'?`/api/join/${encodeURIComponent(cfg.token)}`:'/api/new',{method:'POST',body:form});
  const result=await response.json().catch(()=>({detail:'Unexpected server response'}));
  if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Video merge failed. Try again.');
  if(result.delete_url){try{localStorage.setItem('relay:delete',result.delete_url)}catch(e){}}
  location.href=result.watch_url;
 }catch(err){status(err.message||'Could not create Relay',true);$('record').disabled=false;$('phone').disabled=false;$('upload').disabled=false}
}
async function watchPage(){
 root.innerHTML=`<div class="small"><span class="n">THE MOMENT</span> · Combined automatically</div><h1>Your Relay is ready.</h1>
 <p>Watch the combined video. Pass it to another friend so they can add the next moment.</p>
 <video id="watch-video" controls autoplay playsinline preload="auto"></video><p id="watch-step" class="small"></p>
 <div class="actions">${btn('share','Send to next friend on WhatsApp')}${btn('share-mp4','Share combined video file','alt')}${btn('copy','Copy invitation link','ghost')}</div>
 <p class="status" id="status" aria-live="polite"></p><hr class="line"/>${note('Anyone with the link can watch. A friend records their clip on the page, and Relay automatically makes the next combined video.')}
 <p class="small" id="owner"></p>`;
 try{
  const resp=await fetch('/api/watch/'+encodeURIComponent(cfg.token));if(!resp.ok)throw Error('Video expired');
  const info=await resp.json();$('watch-video').src=info.video_url;
  $('watch-step').textContent=`${info.clips} ${info.clips===1?'person':'people'} · Combined video`;
  const invitation=info.invite_url;
  const text=invitation?`I added my 3 seconds to our Relay! Watch it, add your own clip, and pass it on: ${invitation}`:`Watch our finished Relay: ${location.href}`;
  $('share').textContent=info.can_continue?'Send to next friend on WhatsApp':'Share finished Relay';
  $('share').onclick=()=>{window.location.href='https://wa.me/?text='+encodeURIComponent(text)};
  $('copy').onclick=async()=>{try{await navigator.clipboard.writeText(text);status('Copied! Paste it in WhatsApp.')}catch(e){status('Copy this link: '+(invitation||location.href))}};
  $('share-mp4').disabled=true;
  status('Preparing video sharing…');
  // Prefetch before user taps Share: mobile share sheet requires a user gesture.
  fetch(info.video_url).then(r=>r.ok?r.blob():Promise.reject()).then(blob=>{
    fileShare=new File([blob],`relay-${info.clips}-friends.mp4`,{type:'video/mp4'});
    $('share-mp4').disabled=false;status('Video ready. Invite the next friend or share the MP4.');
  }).catch(()=>{status('Video plays above. Share the private link to continue.')});
  $('share-mp4').onclick=async()=>{
    if(!fileShare){status('Video is still preparing.');return}
    try{
      if(navigator.canShare?.({files:[fileShare]}))await navigator.share({files:[fileShare],text:invitation||location.href});
      else{const a=document.createElement('a');a.href=info.video_url;a.download='Relay.mp4';a.click();status('Video downloaded. Share it from your Downloads folder. Invite the next friend with the link above.')}
    }catch(e){if(e.name!=='AbortError')status('Video sharing unavailable. Use the WhatsApp invitation link.');}
  };
  try{const owner=localStorage.getItem('relay:delete');if(owner){$('owner').innerHTML=`<a href="${safe(owner)}">Delete my Relay</a>`}}catch(e){}
 }catch(e){status('Relay has expired or been deleted.',true);$('share').disabled=true;$('share-mp4').disabled=true;$('copy').disabled=true}
}
function deletePage(){root.innerHTML=`<h1>Delete your Relay?</h1><p>All recordings, combined videos and invitation links will stop working immediately.</p><div class="actions">${btn('delete-confirm','Delete everything')}</div><p class="status" id="status"></p>`;$('delete-confirm').onclick=async()=>{const res=await fetch('/api/delete/'+encodeURIComponent(cfg.token),{method:'POST'});if(res.ok){status('Deleted.');$('delete-confirm').disabled=true}else status('Unable to delete.',true)}}
render();
