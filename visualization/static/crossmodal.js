/* AV view is derived from recorded execution events through the replay cursor.
 * Full board snapshots are never used to reveal future request results. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const seq = row => Number(row.dashboard_sequence_num || row.sequence_num || 0);
  let selectedId = '', last = null, activeWindow = null, origin = 0, renderKey = '', waveformKey = '';
  const artifact = (rid,kind,index=0,track='') => '/api/av-artifact?' + new URLSearchParams({request:rid,kind,index,track});
  function seek(sourceTime) {
    const video = $('av-source-video'), audio = $('av-source-audio');
    if (video.readyState) video.currentTime = Math.max(0, sourceTime - origin);
    if (audio.readyState && activeWindow) audio.currentTime = Math.max(0, sourceTime - activeWindow.source_interval.start);
    $('av-source-seek').value = sourceTime;
    $('av-source-time').textContent = `${Number(sourceTime).toFixed(3)} s source PTS`;
  }
  function drawWaveform(value) {
    const canvas=$('av-waveform'), ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.strokeStyle='#0897ad';ctx.beginPath();const points=value.points||[];
    points.forEach((p,i)=>{const x=i/Math.max(1,points.length-1)*canvas.width;ctx.moveTo(x,(1-p.min)*canvas.height/2);ctx.lineTo(x,(1-p.max)*canvas.height/2);});ctx.stroke();
  }
  function render(detail) {
    last=detail;const context=detail.context||{},timing=context.av_timing, panel=$('av-workspace');
    panel.hidden=!timing;if(!timing)return;
    const max=detail.maxSequence||0,events=(detail.events||[]).filter(r=>seq(r)<=max);
    const requests=new Map(), evidence=[],updates=[];let review=null;
    for(const r of events){const surface=r.surface, payload=r.result||{},id=r.metadata?.request_id;
      if(id && surface.startsWith('crossmodal_request_')) requests.set(id,{...(requests.get(id)||{}),...payload});
      if(surface==='crossmodal_tool_result' && r.status!=='error') evidence.push(payload);
      if(surface==='crossmodal_hypothesis_updated')updates.push(payload);
      if(surface==='case_review_completed')review=payload;
    }
    const eventRid=detail.selected?.raw_event?.metadata?.request_id || detail.selected?.metadata?.request_id;
    if(eventRid && requests.has(eventRid))selectedId=eventRid;
    if(!requests.has(selectedId))selectedId=[...requests.keys()].at(-1)||'';
    const request=requests.get(selectedId), results=evidence.filter(e=>e.request_id===selectedId);
    const window=results.find(e=>e.tool_name==='extract_aligned_av_window')?.measurements;
    origin=Number(timing.source_origin||0);
    const times=(timing.video_frames||[]).map(f=>f.source_time),low=times[0]||0,high=Math.max(low+0.001,...times);
    $('av-alignment-quality').textContent=`Timing ${timing.quality} · ${timing.time_mapping_id}`;
    const slider=$('av-source-seek');slider.min=low;slider.max=high;
    const zoom=Number($('av-zoom').value),center=request?(request.source_interval.start+request.source_interval.end)/2:(high+low)/2;
    const span=(high-low)/zoom,left=Math.max(low,Math.min(high-span,center-span/2)),right=left+span;
    const label=r=>`${r.initiating_agent_id} → Judge 6 → ${r.target_agent_id} · ${r.source_interval.start.toFixed(3)}–${r.source_interval.end.toFixed(3)} s · ${r.status}`;
    const markers=[...requests.values()].filter(r=>r.source_interval.end>=left&&r.source_interval.start<=right).map(r=>`<button type="button" data-av-request="${esc(r.request_id)}" title="${esc(label(r))}" style="left:${Math.max(0,(r.source_interval.start-left)/span*100)}%;width:${Math.min(100,Math.max(2,(Math.min(right,r.source_interval.end)-Math.max(left,r.source_interval.start))/span*100))}%">${r.initiating_agent_id==='audio_investigator'?'A→V':'V→A'} ${esc(r.status)}</button>`).join('');
    const pts=times.filter(t=>t>=left&&t<=right).filter((_,i,a)=>i%Math.max(1,Math.ceil(a.length/100))===0).map(t=>`<i style="left:${(t-left)/span*100}%" title="PTS ${t.toFixed(6)}"></i>`).join('');
    const seenIds=new Set(events.flatMap(r=>r.evidence_ids||[]));
    const intervalMark=(a,b,text,css='')=>a<=right&&b>=left?`<span class="av-interval ${css}" title="${esc(text)}" style="left:${Math.max(0,(a-left)/span*100)}%;width:${Math.max(1,Math.min(100,(Math.min(b,right)-Math.max(a,left))/span*100))}%">${esc(text)}</span>`:'';
    const toSource=time=>{const sample=Math.round(time*timing.sample_rate),a=(timing.audio_spans||[]).find(s=>s.sample_start<=sample&&sample<=s.sample_end);return a?a.source_start+(sample-a.sample_start)/timing.sample_rate:null;};
    const audible=(context.audio_evidence||[]).filter(e=>seenIds.has(e.evidence_id));
    const audioMarks=audible.map(e=>{const a=toSource(e.start_time),b=toSource(e.end_time);return a!==null&&b!==null?intervalMark(a,b,`${e.tool_name}: ${e.prediction||'measured'}`,'audio'):'';}).join('');
    const visualMarks=(context.evidence||[]).filter(e=>seenIds.has(e.evidence_id)&&e.frame_references?.length).map(e=>{const ts=e.frame_references.map(r=>timing.video_frames?.[r.source_frame_index]?.source_time).filter(t=>t!==undefined);return ts.length?intervalMark(Math.min(...ts),Math.max(...ts)+.04,e.tool_name,'visual'):'';}).join('');
    const judgeMarks=events.filter(r=>r.surface==='crossmodal_hypothesis_updated').map(r=>{const i=r.metadata?.source_interval;return i?intervalMark(i.start,i.end,'Judge hypothesis update','judge'):'';}).join('');
    $('av-media-tracks').innerHTML=`<div><b>VIDEO PTS</b><div class="av-track">${pts}</div></div><div><b>VISUAL EVIDENCE</b><div class="av-track">${visualMarks}</div></div><div><b>AUDIO EVIDENCE</b><div class="av-track">${audioMarks}</div></div><div><b>AV REQUESTS</b><div class="av-track">${markers}</div></div><div><b>JUDGE UPDATES</b><div class="av-track">${judgeMarks}</div></div><small>${left.toFixed(3)}–${right.toFixed(3)} s source PTS · zoom changes the source track, not execution replay</small>`;
    $('av-request-list').innerHTML=[...requests.values()].map(r=>`<button class="button" type="button" data-av-request="${esc(r.request_id)}" aria-pressed="${r.request_id===selectedId}">${esc(r.request_id)} · ${esc(label(r))}</button>`).join('')||'No cross-modal requests recorded by this execution step.';
    panel.querySelectorAll('[data-av-request]').forEach(n=>n.onclick=()=>{selectedId=n.dataset.avRequest;render({...detail,selected:null});});
    $('av-request-detail').textContent=JSON.stringify(request?{request_id:request.request_id,initiator:request.initiating_agent_id,target:request.target_agent_id,status:request.status,source_interval:request.source_interval,question:request.question,triggering_evidence_ids:request.triggering_evidence_ids,decision:request.decision_reason,parent_request_id:request.parent_request_id}: {note:'Separate modality results remain available.'},null,2);
    const measurements=results.filter(r=>r.tool_name!=='extract_aligned_av_window').map(r=>({tool:r.tool_name,tool_call_id:r.tool_call_id,evidence_id:r.evidence_id,measurements:r.measurements}));
    $('av-result-detail').textContent=JSON.stringify({measurements,response:request?.response||'No recipient response recorded yet.'},null,2);
    const sync=results.find(e=>e.tool_name==='estimate_lip_speech_synchrony')?.measurements;
    const plot=$('av-offset-plot'),points=sync?.track_measurements?.[0]?.offset_search||[];plot.hidden=!points.length;
    if(points.length){
      const c=plot.getContext('2d');c.clearRect(0,0,1000,180);
      const ys=points.map(p=>p.distance),lo=Math.min(...ys),hi=Math.max(...ys);
      c.strokeStyle='#7751d0';c.beginPath();
      points.forEach((p,i)=>{const x=40+i/(points.length-1)*920,y=120-(p.distance-lo)/Math.max(.001,hi-lo)*100;i?c.lineTo(x,y):c.moveTo(x,y);});c.stroke();
      c.fillStyle='#168391';c.font='13px sans-serif';
      [0,Math.floor(points.length/2),points.length-1].forEach(i=>c.fillText(`${points[i].offset_seconds.toFixed(2)} s`,Math.min(925,40+i/(points.length-1)*920),143));
      c.fillText(`Embedding distance ${lo.toFixed(2)}–${hi.toFixed(2)}; positive offset = audio leads video`,40,12);
      c.fillText('SyncNet offset search · model distance, not authenticity probability',40,170);
    }

    $('av-review-detail').textContent=JSON.stringify({updates,review:review||'No case review recorded by this step.'},null,2);
    const key=JSON.stringify([selectedId,results.map(e=>e.evidence_id)]);
    if(key!==renderKey){
      renderKey=key;activeWindow=window||null;
      $('av-frame-strip').innerHTML='';$('av-face-strip').innerHTML='';
      if(context.video_available && $('av-source-video').getAttribute('src')!=='/api/video') $('av-source-video').src='/api/video';
      $('av-source-video').muted=true;
      if(window){
        $('av-source-video').poster=artifact(selectedId,'frame',0);
        $('av-source-video').onloadedmetadata=()=>seek(request.source_interval.start);
        $('av-source-audio').onloadedmetadata=()=>seek(request.source_interval.start);
        if($('av-source-audio').getAttribute('src')!==artifact(selectedId,'audio')) $('av-source-audio').src=artifact(selectedId,'audio');$('av-spectrogram').src=artifact(selectedId,'spectrogram');$('av-spectrogram').hidden=false;
        const frames=window.frames||[], stride=Math.max(1,Math.ceil(frames.length/10));
        $('av-frame-strip').innerHTML=frames.map((f,i)=>({f,i})).filter((_,i)=>i%stride===0).map(({f,i})=>`<button type="button" data-av-time="${f.source_time}"><img src="${artifact(selectedId,'frame',i)}" alt="Actual source frame ${f.source_time.toFixed(3)} s"><small>${f.source_time.toFixed(3)} s</small></button>`).join('');
        const tracks=results.find(e=>e.tool_name==='locate_visible_speakers')?.measurements?.candidate_face_tracks||[];
        $('av-face-strip').innerHTML=tracks.slice(0,8).map(t=>`<figure><img src="${artifact(selectedId,'face',0,t.track_id)}" alt="Candidate face ${esc(t.track_id)}"><img src="${artifact(selectedId,'mouth',0,t.track_id)}" alt="Geometric lower-face crop, not mouth landmarks"><figcaption>${esc(t.track_id)} · candidate only; speaker unassigned</figcaption></figure>`).join('')||'No candidate face track recorded.';
        if(sync?.track_measurements?.length) $('av-face-strip').innerHTML+=sync.track_measurements.map(t=>`<figure><img src="${artifact(selectedId,'sync-crop',0,t.face_track_id)}" alt="Actual model face crop"><figcaption>${esc(t.face_track_id)} · SyncNet input crop</figcaption></figure>`).join('');
        $('av-playback-note').textContent='Media seeks use source PTS. Video is muted; original selected audio plays separately. Browser playback is approximate and is not a lip-sync measurement.';
        const wkey=window.window_id;if(wkey!==waveformKey){waveformKey=wkey;fetch(artifact(selectedId,'waveform')).then(r=>r.json()).then(v=>{if(activeWindow?.window_id===wkey)drawWaveform(v);}).catch(()=>{});}
        seek(request.source_interval.start);
      }else{
        $('av-source-audio').removeAttribute('src');$('av-spectrogram').hidden=true;
        $('av-waveform').getContext('2d').clearRect(0,0,900,140);waveformKey='';
        if(sync?.track_measurements?.length) $('av-face-strip').innerHTML+=sync.track_measurements.map(t=>`<figure><img src="${artifact(selectedId,'sync-crop',0,t.face_track_id)}" alt="Actual model face crop"><figcaption>${esc(t.face_track_id)} · SyncNet input crop</figcaption></figure>`).join('');
        $('av-playback-note').textContent='No aligned extraction executed by this replay step.';
      }
    }
    panel.querySelectorAll('[data-av-time]').forEach(n=>n.onclick=()=>seek(Number(n.dataset.avTime)));
  }
  document.addEventListener('argus:av-selection',event=>render(event.detail));
  $('av-source-seek').oninput=e=>seek(Number(e.target.value));
  $('av-zoom').onchange=()=>last&&render(last);
  $('av-focus').onclick=()=>$('av-workspace').classList.toggle('av-expanded');
  $('av-play').onclick=async()=>{if(!activeWindow)return;seek(activeWindow.source_interval.start);try{await Promise.all([$('av-source-video').play(),$('av-source-audio').play()]);}catch(_){};};
  $('av-source-video').ontimeupdate=()=>{const video=$('av-source-video'),sourceTime=video.currentTime+origin;$('av-source-seek').value=sourceTime;$('av-source-time').textContent=`${sourceTime.toFixed(3)} s source PTS`;if(activeWindow&&sourceTime>=activeWindow.source_interval.end){video.pause();$('av-source-audio').pause();}};
})();
