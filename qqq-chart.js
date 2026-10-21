/* QQQ day charts for the journal (1D / 15m / 1m) with entry/exit arrows.
   Market data comes from public snapshots in data/qqq/ (written by the GitHub Action). Trade data stays in memory only. */
(function(){
const OWNER='MadHamster6000', REPO='DIYupload', BRANCH='Madhamster-Stock';
const RAW=`https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}/data/qqq/`, PAGES='data/qqq/', TZ='America/New_York';
const cache={}, state={}; let idx=null, daily=null;
async function getJSON(name){ if(name in cache) return cache[name];
  // saved snapshot on Pages first (cached CDN); raw.githubusercontent for fresh days not deployed yet
  const p=(async()=>{ for(const u of [PAGES+name, RAW+name+'?t='+Math.floor(Date.now()/300000)]){ try{ const r=await fetch(u); if(r.ok) return await r.json(); }catch(e){} } return null; })();
  cache[name]=p; return p; }
async function index(){ if(!idx){ idx=await getJSON('index.json'); const fresh=await (async()=>{ try{ const r=await fetch(RAW+'index.json?t='+Math.floor(Date.now()/300000)); return r.ok?r.json():null; }catch(e){ return null; } })(); if(fresh&&(!idx||fresh.updated>idx.updated)) idx=fresh; } return idx||{days:{}}; }
const fake=(d,min)=>Date.UTC(+d.slice(0,4),+d.slice(5,7)-1,+d.slice(8,10))/1000+min*60; // ET wall clock shown as "UTC" (chart has no tz support)
const etParts=ts=>{ const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(ts).map(x=>[x.type,x.value])); return {d:`${p.year}-${p.month}-${p.day}`,min:+p.hour*60+ +p.minute}; };
const COLORS=['#4f8cff','#f59e0b','#a855f7','#14b8a6','#ec4899','#84cc16','#f97316','#06b6d4'];
const sess=m=>m<570?'pre':m>=960?'post':'rth';
async function load(day){ const I=await index(); const prevDays=Object.keys(I.days||{}).filter(d=>d<day).sort(); const prev=prevDays.at(-1);
  const [snap,ps,dl]=await Promise.all([(I.days||{})[day]?getJSON(day+'.json'):null, prev?getJSON(prev+'.json'):null, daily||(daily=getJSON('1d.json'))]);
  return {I,snap,prev,ps,daily:await dl}; }
function bars(snap,ps,prev,day,tf){ const out=[];
  if(ps&&ps[tf]) ps[tf].filter(b=>b[0]>=960).forEach(b=>out.push({time:fake(prev,b[0]),open:b[1],high:b[2],low:b[3],close:b[4],s:'post'})); // prior day's after-hours extension
  if(snap&&snap[tf]) snap[tf].forEach(b=>out.push({time:fake(day,b[0]),open:b[1],high:b[2],low:b[3],close:b[4],s:sess(b[0])}));
  return out; }
function mount(el,day){ if(!window.LightweightCharts){ el.innerHTML='<div class="cov">Chart library failed to load.</div>'; return; }
  const st=state[day]=state[day]||{tf:null,off:new Set()};
  el.innerHTML='<div class="tabs"><b style="margin-right:6px">📉 QQQ</b><span class="tf"></span><span class="cov" style="margin:0 0 0 auto"></span></div><div class="chartbox"></div><div class="legend"></div><div class="cov note2"></div>';
  load(day).then(D=>draw(el,day,D,st)).catch(e=>{ el.querySelector('.note2').textContent='Could not load QQQ data: '+e.message; }); }
function draw(el,day,D,st){ if(!el.isConnected) return;
  const has={m15:!!D.snap?.m15?.length,m1:!!D.snap?.m1?.length,h1:!!D.snap?.h1?.length}, dIdx=(D.daily||[]).findIndex(b=>b[0]>=day);
  const tabs=[['d','1D']]; if(has.m15) tabs.push(['m15','15m']); else if(has.h1) tabs.push(['h1','1h']); if(has.m1) tabs.push(['m1','1m']);
  if(!st.tf||!tabs.some(t=>t[0]===st.tf)) st.tf=has.m1?'m1':has.m15?'m15':has.h1?'h1':'d';
  el.querySelector('.tf').innerHTML=tabs.map(([k,l])=>`<button data-tf="${k}" class="${st.tf===k?'on':''}">${l}</button>`).join(' ');
  const cov=[has.m1&&'1m',has.m15&&'15m',has.h1&&'1h'].filter(Boolean);
  el.querySelector('.tabs .cov').textContent=cov.length?`Saved for this day: daily + ${cov.join(' + ')} (04:00–20:00 ET incl. pre/post)`:'';
  el.querySelector('.note2').innerHTML=!cov.length?(D.daily&&dIdx>=0?`Daily chart only for ${day} — free intraday history is limited (1m ≈ last 30 days, 15m ≈ 60 days, 1h ≈ 2 years) and this day wasn't captured. From now on every trading day is saved permanently after the close.`:`No QQQ data saved for ${day} yet (weekend/holiday, or today's snapshot runs after the close ~8:30 PM ET).`)
    :`Shaded = pre-market (04:00–09:30) / after-hours (16:00–20:00, incl. the prior day's evening). ${st.tf==='d'?'Selected day marked.':'Arrows: ▲ buy (entry/add) · ▼ sell (exit). Times are ET.'} Source: Yahoo Finance public data, delayed.`;
  el.querySelectorAll('[data-tf]').forEach(b=>b.onclick=()=>{ st.tf=b.dataset.tf; draw(el,day,D,st); });
  const box=el.querySelector('.chartbox'); if(st.chart){ st.chart.remove(); st.chart=null; } box.innerHTML='';
  const LC=LightweightCharts, chart=LC.createChart(box,{autoSize:true,layout:{background:{color:'#0b0f17'},textColor:'#9aa4b2'},grid:{vertLines:{color:'#1a2130'},horzLines:{color:'#1a2130'}},
    timeScale:{timeVisible:st.tf!=='d',secondsVisible:false,borderColor:'#263042'},rightPriceScale:{borderColor:'#263042'},crosshair:{mode:0}});
  st.chart=chart;
  const shade=chart.addHistogramSeries({priceScaleId:'shade',priceLineVisible:false,lastValueVisible:false,base:0});
  shade.priceScale().applyOptions({scaleMargins:{top:0,bottom:0}});
  chart.priceScale('shade').applyOptions({scaleMargins:{top:0,bottom:0},visible:false});
  const cs=chart.addCandlestickSeries({upColor:'#22c55e',downColor:'#ef4444',borderVisible:false,wickUpColor:'#22c55e',wickDownColor:'#ef4444'});
  const leg=el.querySelector('.legend'); leg.innerHTML='';
  if(st.tf==='d'){ if(!D.daily||dIdx<0){ return; } const a=Math.max(0,dIdx-63), seg=D.daily.slice(a,dIdx+6);
    const dt=s=>({year:+s.slice(0,4),month:+s.slice(5,7),day:+s.slice(8,10)});
    cs.setData(seg.map(b=>({time:dt(b[0]),open:b[1],high:b[2],low:b[3],close:b[4]})));
    shade.setData(seg.map(b=>({time:dt(b[0]),value:b[0]===day?1:0,color:'rgba(79,140,255,.18)'})));
    if(D.daily[dIdx][0]===day) cs.setMarkers([{time:dt(day),position:'belowBar',shape:'arrowUp',color:'#4f8cff',text:'this day'}]);
    chart.timeScale().fitContent(); return; }
  const bs=bars(D.snap,D.ps,D.prev,day,st.tf); cs.setData(bs.map(({s,...b})=>b));
  shade.setData(bs.map(b=>({time:b.time,value:b.s==='rth'?0:1,color:b.s==='pre'?'rgba(245,158,11,.16)':'rgba(168,85,247,.16)'})));
  // arrows from this day's decrypted executions (memory only)
  const ex=(window.journalExecs?window.journalExecs(day):[]).slice().sort((a,b)=>a.ts-b.ts), step={m1:1,m15:15,h1:60}[st.tf];
  const gs=ex.length?TradeParser.summarize(ex):[], col={}; gs.forEach((g,i)=>col[g.group]=COLORS[i%COLORS.length]);
  leg.innerHTML=gs.length?gs.map((g,i)=>`<label><input type="checkbox" data-g="${g.group}" ${st.off.has(g.group)?'':'checked'}><i style="background:${col[g.group]}"></i>P${i+1} ${g.label} <span class="${g.netPl>0?'pos':g.netPl<0?'neg':'muted'}">${g.netPl>=0?'+':'−'}$${Math.abs(Math.round(g.netPl))}</span></label>`).join('')+'<span class="muted">▲ green = buy · ▼ red = sell · P# = position</span>':'';
  leg.querySelectorAll('[data-g]').forEach(c=>c.onchange=()=>{ c.checked?st.off.delete(c.dataset.g):st.off.add(c.dataset.g); draw(el,day,D,st); });
  const pn={}; gs.forEach((g,i)=>pn[g.group]='P'+(i+1)); const lastOf={}; ex.forEach(x=>lastOf[x.group]=x);
  const times=new Set(bs.map(b=>b.time)); const mk=[];
  ex.filter(x=>!st.off.has(x.group)).forEach(x=>{ const p=etParts(x.ts); if(p.d!==day) return; let t=fake(day,Math.floor(p.min/step)*step); if(!times.has(t)) return;
    const g=gs.find(g=>g.group===x.group), buy=x.side==='buy', fin=lastOf[x.group]===x&&!buy;
    mk.push({time:t,position:buy?'belowBar':'aboveBar',shape:buy?'arrowUp':'arrowDown',color:buy?'#22c55e':'#ef4444',
      text:`${pn[x.group]||''} ${buy?'B':'S'} ${x.qty}@${(+x.price).toFixed(2)}${fin&&g?` P/L ${g.netPl>=0?'+':'−'}$${Math.abs(Math.round(g.netPl))}`:''}`}); });
  mk.sort((a,b)=>a.time-b.time); cs.setMarkers(mk);
  // per-position colored strip along the bottom spanning the hold (first → last fill)
  gs.filter(g=>!st.off.has(g.group)).forEach((g,i)=>{ const ts=ex.filter(x=>x.group===g.group).map(x=>{ const p=etParts(x.ts); return p.d===day?fake(day,Math.floor(p.min/step)*step):null; }).filter(t=>t!=null);
    if(!ts.length) return; const lo=Math.min(...ts), hi=Math.max(...ts), lvl=1+(i%4);
    const ls=chart.addLineSeries({color:col[g.group],lineWidth:4,priceScaleId:'pos',lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false,autoscaleInfoProvider:()=>({priceRange:{minValue:0,maxValue:5}})});
    ls.setData(bs.filter(b=>b.time>=lo&&b.time<=hi).map(b=>({time:b.time,value:lvl}))); chart.priceScale('pos').applyOptions({visible:false,scaleMargins:{top:0.93,bottom:0.01}}); });
  const rs=bs.findIndex(b=>b.time>=fake(day,540)), re=bs.findIndex(b=>b.time>=fake(day,990));
  if(rs>=0) chart.timeScale().setVisibleLogicalRange({from:Math.max(0,rs-(st.tf==='m1'?60:6)),to:re>0?re:bs.length}); else chart.timeScale().fitContent(); }
window.QC={mount,index,_cache:cache};
})();
