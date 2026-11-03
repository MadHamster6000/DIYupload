/* Stale-position check — flag any open QQQ/SPY option position whose price reference has not
   changed for >= 120 minutes. Price source: the same public data/qqq/<day>.json 1-min bars that
   pin-risk.js uses (QQQ underlying close). The journal has no option last/mark feed, so "price"
   = QQQ spot. Non-QQQ positions are listed as "no bars — check manually". Re-checks every 60 s
   while the page is open (today only). Trade data stays in memory. */
(function(root){
const STALE=120, CLOSE=16*60, TZ='America/New_York', RECHECK_MS=60000;
const etDay=()=>new Intl.DateTimeFormat('en-CA',{timeZone:TZ}).format(new Date());
const etMinNow=()=>{ const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:TZ,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date()).map(x=>[x.type,x.value])); return +p.hour*60+ +p.minute; };
const etMin=ts=>{ const s=root.TradeParser.fmtET(ts); return +s.slice(11,13)*60+ +s.slice(14,16); };
const hhmm=m=>String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0');
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function fetchBars(day,fresh){ return fetch('data/qqq/'+day+'.json'+(fresh?'?t='+Date.now():''),{cache:fresh?'no-store':'default'})
  .then(r=>r.ok?r.json():null).then(j=>j&&(j.m1||j.m15)?j:null).catch(()=>null); }
function qtyAt(fills,minute){ let q=0; fills.forEach(f=>{ if(etMin(f.ts)<=minute) q+=f.side==='buy'?f.qty:-f.qty; }); return q; }
// Find the last bar (<= atMin) and the minute price last changed (close vs previous close).
function lastMove(bars,atMin){
  const src=((bars.m1&&bars.m1.length)?bars.m1:(bars.m15||[])).filter(b=>b[0]<=atMin).sort((a,b)=>a[0]-b[0]);
  if(!src.length) return null;
  const last=src[src.length-1]; let moved=src[0][0];
  for(let i=src.length-1;i>0;i--){ if(src[i][4]!==src[i-1][4]){ moved=src[i][0]; break; } }
  return {px:last[4],lastBar:last[0],moved};
}
function analyze(day,execs,bars){
  const TP=root.TradeParser; if(!TP||!execs||!execs.length) return {flags:[]};
  const today=etDay()===day, nowM=today?Math.min(etMinNow(),CLOSE):CLOSE;
  const ex=execs.filter(e=>(e.right==='C'||e.right==='P')&&(e.ticker==='QQQ'||e.ticker==='SPY')).map(e=>({...e}));
  TP.tagRows(ex);
  const by={}; ex.forEach(e=>{ (by[e.group]=by[e.group]||[]).push(e); });
  const flags=[];
  Object.keys(by).forEach(g=>{
    const fills=by[g].slice().sort((a,b)=>a.ts-b.ts), f0=fills[0];
    if(today){ // live: only positions open right now
      const q=qtyAt(fills,nowM); if(q<=0) return;
      if(f0.ticker!=='QQQ'){ flags.push({label:TP.label(f0),qty:q,na:true,note:'no '+f0.ticker+' bars — check manually'}); return; }
      if(!bars){ flags.push({label:TP.label(f0),qty:q,na:true,note:'QQQ snapshot not loaded'}); return; }
      const lm=lastMove(bars,nowM); if(!lm) return;
      const since=Math.max(etMin(fills[0].ts),lm.moved), mins=nowM-since;
      if(nowM-lm.moved>=STALE) flags.push({label:TP.label(f0),qty:q,px:lm.px,moved:hhmm(lm.moved),mins:nowM-lm.moved,lastBar:hhmm(lm.lastBar)});
      return;
    }
    // historical: walk each open minute, flag first stretch of >=120 min with no price change while open
    if(f0.ticker!=='QQQ'||!bars) return;
    const src=((bars.m1&&bars.m1.length)?bars.m1:(bars.m15||[])).slice().sort((a,b)=>a[0]-b[0]);
    let runStart=null,runPx=null;
    for(const b of src){ if(qtyAt(fills,b[0])<=0){ runStart=null; continue; }
      if(runStart===null||b[4]!==runPx){ runStart=b[0]; runPx=b[4]; continue; }
      if(b[0]-runStart>=STALE){ flags.push({label:TP.label(f0),qty:qtyAt(fills,b[0]),px:runPx,moved:hhmm(runStart),mins:b[0]-runStart,lastBar:hhmm(b[0])}); break; } }
  });
  return {flags,today,nowM};
}
function renderHTML(r){ if(!r||!r.flags.length) return '';
  const rows=r.flags.map(f=>f.na?`<li><b>${esc(f.label)}</b> · ${f.qty} open — ${esc(f.note)}</li>`
    :`<li><b>${esc(f.label)}</b> · ${f.qty} open · last QQQ $${f.px.toFixed(2)} (bar ${f.lastBar} ET) · last moved <b>${f.moved} ET</b> · <b>${f.mins} min unchanged</b></li>`).join('');
  const n=r.flags.filter(f=>!f.na).length;
  return `<div class="pin-banner stale-banner" role="alert"><div class="pin-title">${n?`⏸️ Stale position · ${n} open with no price change ≥ 2 h`:'⏸️ Stale-position check'}${r.today?' <span class="pin-live">LIVE</span>':''}</div>
    <p class="pin-warn">Price reference = QQQ 1-min close from the page snapshot (no option mark feed). No movement for 2 hours usually means a dead position or a stale data feed — verify in your broker.</p>
    <ul class="pin-list">${rows}</ul></div>`; }
const timers=new WeakMap();
function mount(el,day,execs){ if(!el) return; const live=etDay()===day;
  const run=fresh=>fetchBars(day,fresh).then(bars=>{ if(!el.isConnected){ clearInterval(timers.get(el)); return; }
    el.innerHTML=renderHTML(analyze(day,execs||[],bars)); }).catch(()=>{});
  run(false);
  if(live){ clearInterval(timers.get(el)); timers.set(el,setInterval(()=>run(true),RECHECK_MS)); } }
root.StalePosition={mount,analyze,lastMove,STALE};
})(typeof window!=='undefined'?window:globalThis);
