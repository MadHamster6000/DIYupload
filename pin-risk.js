/* Pin-risk check — after 3:00 PM ET, flag open 0DTE (same-day expiry) option positions
   within 1.0 point of strike vs QQQ spot. Uses public data/qqq/<day>.json; trade data stays in memory. */
(function(root){
const PIN_MIN=15*60, CLOSE=16*60, THRESH=1.0;
const TZ='America/New_York';
const barsCache={};
const etDay=()=>new Intl.DateTimeFormat('en-CA',{timeZone:TZ}).format(new Date());
const etMinNow=()=>{ const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:TZ,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date()).map(x=>[x.type,x.value])); return +p.hour*60+ +p.minute; };
const etMin=ts=>{ const s=root.TradeParser.fmtET(ts); return +s.slice(11,13)*60+ +s.slice(14,16); };
const hhmm=m=>String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0');
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function loadBars(day){ if(day in barsCache) return barsCache[day];
  const p=fetch('data/qqq/'+day+'.json').then(r=>r.ok?r.json():null).then(j=>j&&(j.m1||j.m15)?j:null).catch(()=>null);
  barsCache[day]=p; return p; }
function spotAt(bars, minute){ // closest bar at or before minute (prefer m1)
  const m1=bars.m1||[], m15=bars.m15||[];
  const src=m1.length?m1:m15;
  let best=null; src.forEach(b=>{ if(b[0]<=minute&&(!best||b[0]>best[0])) best=b; });
  return best?{min:best[0],px:best[4]}:null;
}
function lastSpotFrom(bars, fromMin){ const m1=bars.m1||[], m15=bars.m15||[];
  const src=(m1.length?m1:m15).filter(b=>b[0]>=fromMin&&b[0]<CLOSE+60);
  if(!src.length){ // fall back to any bar at/after fromMin
    const all=(m1.length?m1:m15).filter(b=>b[0]>=fromMin); if(!all.length) return null;
    const b=all[all.length-1]; return {min:b[0],px:b[4]}; }
  const b=src[src.length-1]; return {min:b[0],px:b[4]}; }
function qtyAt(fills, minute){ let q=0; fills.forEach(f=>{ if(etMin(f.ts)<=minute) q+=f.side==='buy'?f.qty:-f.qty; }); return q; }
function wasOpenAfter3(fills){ // open at some point at/after 15:00
  let q=0, open=false; const chron=fills.slice().sort((a,b)=>a.ts-b.ts);
  for(const f of chron){ const m=etMin(f.ts); if(m>=PIN_MIN&&q>0) open=true; q+=f.side==='buy'?f.qty:-f.qty; if(m>=PIN_MIN&&q>0) open=true; }
  if(q>0) open=true; // still open at end (0DTE into close/expiry)
  return open; }
function analyze(day, execs, bars){
  const TP=root.TradeParser; if(!TP||!execs||!execs.length) return {flags:[],armed:false,note:''};
  const today=etDay()===day, nowM=etMinNow();
  const armed=!today||nowM>=PIN_MIN; // historical always; today only after 3pm
  const ex=execs.filter(e=>(e.right==='C'||e.right==='P')&&(e.ticker==='QQQ'||e.ticker==='SPY')).map(e=>({...e}));
  TP.tagRows(ex);
  const by={}; ex.forEach(e=>{ (by[e.group]=by[e.group]||[]).push(e); });
  const flags=[];
  Object.keys(by).forEach(g=>{
    const fills=by[g].slice().sort((a,b)=>a.ts-b.ts); const f0=fills[0];
    if(f0.expiry!==day) return; // 0DTE / same-day expiry only
    if(f0.ticker!=='QQQ'){ if(wasOpenAfter3(fills)||qtyAt(fills,CLOSE)>0) flags.push({ticker:f0.ticker,strike:+f0.strike,right:f0.right,label:TP.label(f0),dist:NaN,spot:NaN,at:'',qty:qtyAt(fills,CLOSE)||qtyAt(fills,PIN_MIN),note:'no '+f0.ticker+' bars — check manually',na:true}); return; }
    if(!wasOpenAfter3(fills)&&qtyAt(fills,PIN_MIN)<=0&&qtyAt(fills,CLOSE)<=0) return;
    if(!bars){ flags.push({ticker:'QQQ',strike:+f0.strike,right:f0.right,label:TP.label(f0),dist:NaN,spot:NaN,at:'',qty:Math.max(qtyAt(fills,PIN_MIN),qtyAt(fills,CLOSE)),note:'QQQ snapshot not loaded yet',na:true}); return; }
    // Walk RTH bars from 15:00; flag if open qty within 1 pt of strike
    const src=(bars.m1&&bars.m1.length?bars.m1:bars.m15||[]).filter(b=>b[0]>=PIN_MIN&&b[0]<CLOSE);
    let hit=null;
    if(src.length){ for(const b of src){ const q=qtyAt(fills,b[0]); if(q>0){ const dist=Math.abs(b[4]-f0.strike); if(dist<=THRESH){ hit={min:b[0],px:b[4],dist,qty:q}; break; } } } }
    // If still open at end of day / into close, also check last spot ≥15:00
    if(!hit){ const qEnd=qtyAt(fills,CLOSE-1); const last=lastSpotFrom(bars,PIN_MIN); if(last&&(qEnd>0||qtyAt(fills,last.min)>0)){ const q=qtyAt(fills,last.min); if(q>0){ const dist=Math.abs(last.px-f0.strike); if(dist<=THRESH) hit={min:last.min,px:last.px,dist,qty:q}; } } }
    // Live today: no bars yet after 15:00 — use last available bar
    if(!hit&&today&&armed){ const qNow=qtyAt(fills,nowM); if(qNow>0){ const last=lastSpotFrom(bars,0)||spotAt(bars,nowM); if(last){ const dist=Math.abs(last.px-f0.strike); if(dist<=THRESH) hit={min:last.min,px:last.px,dist,qty:qNow}; } } }
    if(hit) flags.push({ticker:'QQQ',strike:+f0.strike,right:f0.right,label:TP.label(f0),dist:hit.dist,spot:hit.px,at:hhmm(hit.min),qty:hit.qty,na:false});
  });
  return {flags,armed,today,nowM};
}
function renderHTML(day, result){
  if(!result) return '';
  const {flags,armed,today}=result;
  if(!armed){ // today before 3pm — quiet tip only if there are open 0DTE kites
    return ''; }
  if(!flags.length) return '';
  const rows=flags.map(f=>{
    if(f.na) return `<li><b>${esc(f.label)}</b> — ${esc(f.note||'check manually')}</li>`;
    return `<li><b>${esc(f.label)}</b> · strike <b>${f.strike}</b> · spot $${f.spot.toFixed(2)} @ ${f.at} ET · <b>${f.dist.toFixed(2)} pt</b> from strike · ${f.qty} open</li>`;
  }).join('');
  const real=flags.filter(f=>!f.na);
  const title=real.length?`⚠️ Pin-risk · ${real.length} open 0DTE within 1 pt of strike`:`⚠️ Pin-risk check`;
  return `<div class="pin-banner" role="alert"><div class="pin-title">${title}${today?' <span class="pin-live">LIVE</span>':''}</div>
    <p class="pin-warn">After 3:00 PM ET, an open kite near its expiring strike can get <b>pinned or dragged</b> toward that strike into the close. Prefer exiting or tightening — do not add.</p>
    <ul class="pin-list">${rows}</ul></div>`;
}
function mount(el, day, execs){ if(!el) return;
  el.innerHTML='<div class="pin-banner pin-loading muted">Checking pin-risk…</div>';
  loadBars(day).then(bars=>{
    if(!el.isConnected) return;
    const r=analyze(day, execs||[], bars);
    el.innerHTML=renderHTML(day, r);
  }).catch(()=>{ if(el.isConnected) el.innerHTML=''; }); }
root.PinRisk={mount,analyze,loadBars,PIN_MIN,THRESH};
})(typeof window!=='undefined'?window:globalThis);
