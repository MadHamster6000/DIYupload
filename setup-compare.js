/* Setup Compare — splits saved journal executions into Late Scalp / Morning Playbook / Outside.
   Computed on the fly from the encrypted journal's execution list (saved via "Save executions").
   Nothing new is stored: no CSV, no account data. Underlying QQQ price comes from public data/qqq/<day>.json 1m bars. */
(function(root){
const TP=()=>root.TradeParser, JR=()=>root.JournalReport;
const LATE=15*60+15, AM0=9*60+30, AM1=11*60+30, CLOSE=16*60;
const etMin=ts=>{ const s=TP().fmtET(ts); return +s.slice(11,13)*60+ +s.slice(14,16); };
const hhmm=ts=>TP().fmtET(ts).slice(11,16), dayOf=ts=>TP().fmtET(ts).slice(0,10);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const money=v=>'<span class="'+(v>0?'pos':v<0?'neg':'')+'">'+(v<0?'−':'')+'$'+Math.abs(v).toFixed(0)+'</span>';
const bars={}; let last10=true, lastArgs=null;
function loadBars(day){ if(day in bars) return; bars[day]=null;
  fetch('data/qqq/'+day+'.json').then(r=>r.ok?r.json():null).then(j=>{ bars[day]=j&&j.m1?j.m1:[]; if(lastArgs) render.apply(null,lastArgs); }).catch(()=>{ bars[day]=[]; }); }
function under(r){ if(r.ticker!=='QQQ') return NaN; const b=bars[r.day]; if(!b||!b.length) return NaN; const m=etMin(r.first);
  let best=null; b.forEach(x=>{ if(x[0]<=m&&(!best||x[0]>best[0])) best=x; }); return best&&m-best[0]<=5?best[4]:NaN; }
function rounds(execs){ const T=TP(); const ex=execs.filter(e=>e.right==='C'||e.right==='P').filter(e=>e.ticker==='QQQ'||e.ticker==='SPY').map(e=>({...e}));
  T.tagRows(ex); return T.summarize(ex).map(s=>{ const fills=ex.filter(x=>x.group===s.group).sort((a,b)=>a.ts-b.ts); const f0=fills.find(f=>f.side==='buy')||fills[0];
    const m=etMin(f0.ts); return {...s,fills,ticker:f0.ticker,strike:f0.strike,right:f0.right,first:f0.ts,day:dayOf(f0.ts),entryPx:f0.price,
      pnl:s.hasCash?s.cash:s.netPl,setup:m>=LATE?'late':(m>=AM0&&m<AM1)?'am':'out'}; }); }
function lateFlags(r){ const f=[], u=under(r);
  if(!isFinite(u)) f.push(['price ?','na']); else f.push(Math.abs(r.strike-u)<=1?['≤1 pt','ok']:['too far ('+Math.abs(r.strike-u).toFixed(1)+')','bad']);
  if(r.entryPx<0.20||r.entryPx>0.35) f.push(['premium','bad']);
  if(r.bq<2||r.bq>4) f.push(['size','bad']);
  if(etMin(r.last)>CLOSE||r.open>0) f.push(['exit late','bad']);
  return f; }
function amBroken(day,rs){ const ex=[].concat(...rs.map(r=>r.fills)); if(!ex.length) return [];
  let cfg={}; try{ cfg=JSON.parse(localStorage.getItem('mh_report_cfg')||'{}'); }catch(e){}
  try{ return JR().report(day,ex,[],{...JR().DEFAULT_CFG,...cfg}).rules.filter(x=>x.status==='broken'); }catch(e){ return []; } }
function stat(list){ const n=list.length, w=list.filter(r=>r.pnl>0).length, net=list.reduce((a,r)=>a+r.pnl,0); return {n,wr:n?w/n*100:NaN,net,avg:n?net/n:NaN}; }
function render(execs,preview){ const el=document.getElementById('sc-body'); if(!el) return; lastArgs=[execs,preview];
  let all=(execs||[]).slice(), note='';
  if(preview&&preview.length){ const pdays=new Set(preview.filter(r=>TP().valid(r)).map(r=>dayOf(r.ts))); all=all.filter(e=>!pdays.has(dayOf(e.ts))).concat(preview.filter(r=>TP().valid(r)));
    if(pdays.size) note='<div class="note">Includes the unsaved preview for '+[...pdays].join(', ')+'. Click <b>Save executions</b> to keep it.</div>'; }
  let rs=rounds(all); const days=[...new Set(rs.map(r=>r.day))].sort(); days.forEach(loadBars);
  const shown=last10?days.slice(-10):days; rs=rs.filter(r=>shown.includes(r.day));
  const L=rs.filter(r=>r.setup==='late'), A=rs.filter(r=>r.setup==='am'), O=rs.filter(r=>r.setup==='out');
  L.forEach(r=>{ r.flags=lateFlags(r); r.clean=!r.flags.some(f=>f[1]==='bad'); });
  const amDays=shown.map(d=>({d,br:amBroken(d,A.filter(r=>r.day===d))}));
  const sL=stat(L), sA=stat(A), sO=stat(O), lateBreaks=L.filter(r=>!r.clean).length, amBreaks=amDays.reduce((a,x)=>a+x.br.length,0);
  const pct=x=>isFinite(x)?Math.round(x)+'%':'—', avg=x=>isFinite(x)?money(x):'—';
  const card=(t,s,br,brl)=>'<div class="sc-card"><h3 style="margin-top:0">'+t+'</h3><div class="stats">'+[['Trades',s.n],['Win rate',pct(s.wr)],['Net P&L',money(s.net)],['Avg / trade',avg(s.avg)],[brl,br]].map(x=>'<div class="stat"><div class="k">'+x[0]+'</div><div class="v">'+x[1]+'</div></div>').join('')+'</div></div>';
  const better=(a,b,hi)=>!isFinite(a)||!isFinite(b)||a===b?['','']:(a>b)===hi?[' class="sc-win"','']:['',' class="sc-win"'];
  const row=(k,a,b,fa,fb,cmp)=>{ const c=cmp&&sL.n&&sA.n?better(cmp[0],cmp[1],true):['','']; return '<tr><td style="text-align:left">'+k+'</td><td'+c[0]+'>'+fa+'</td><td'+c[1]+'>'+fb+'</td></tr>'; };
  let h=note+'<div class="btns" style="justify-content:flex-start;margin:0 0 10px"><label style="display:flex;gap:6px;align-items:center;margin:0;text-transform:none"><input type="checkbox" id="sc10" style="width:auto"'+(last10?' checked':'')+'> Last 10 trading days only</label><span class="muted">'+shown.length+' day'+(shown.length===1?'':'s')+' shown · '+days.length+' stored</span></div>';
  if(!rs.length){ el.innerHTML=h+'<p class="sub">No QQQ/SPY option trades saved yet. Load a Wealthsimple CSV above and click <b>Save executions</b>.</p>'; return; }
  h+='<div class="sc-cards">'+card('⏱️ Late Scalp (entry ≥ 3:15 PM)',sL,lateBreaks,'Trades w/ rule breaks')+card('🎯 Morning Playbook (9:30–11:30)',sA,amBreaks,'Rules broken (day total)')+'</div>';
  h+='<p class="sub" style="margin:8px 0">Outside both setups (11:30–3:15 or pre-9:30): <b>'+sO.n+'</b> trade'+(sO.n===1?'':'s')+', net '+money(sO.net)+'.</p>';
  h+='<h3>Side by side</h3><div class="tbl"><table><thead><tr><th style="text-align:left">Metric</th><th>Late Scalp</th><th>Morning</th></tr></thead><tbody>'
    +row('Trades',0,0,sL.n,sA.n)+row('Win rate',0,0,pct(sL.wr),pct(sA.wr),[sL.wr,sA.wr])+row('Net P&L',0,0,money(sL.net),money(sA.net),[sL.net,sA.net])
    +row('Avg P&L / trade',0,0,avg(sL.avg),avg(sA.avg),[sL.avg,sA.avg])+row('Net profitable?',0,0,sL.n?(sL.net>0?'✅ yes':'❌ no'):'—',sA.n?(sA.net>0?'✅ yes':'❌ no'):'—')
    +row('Rule breaks',0,0,lateBreaks+' trade'+(lateBreaks===1?'':'s'),amBreaks+' rule'+(amBreaks===1?'':'s'))+'</tbody></table></div>';
  h+='<h3>Daily</h3><div class="tbl"><table><thead><tr><th style="text-align:left">Day</th><th>Late trades</th><th>Late P&L</th><th>AM trades</th><th>AM P&L</th><th style="text-align:left">AM rules broken</th><th>Outside</th><th>Outside P&L</th></tr></thead><tbody>'
    +shown.slice().reverse().map(d=>{ const l=stat(L.filter(r=>r.day===d)), a=stat(A.filter(r=>r.day===d)), o=stat(O.filter(r=>r.day===d)), br=amDays.find(x=>x.d===d).br;
      return '<tr><td style="text-align:left">'+d+'</td><td>'+l.n+'</td><td>'+money(l.net)+'</td><td>'+a.n+'</td><td>'+money(a.net)+'</td><td style="text-align:left;white-space:normal">'+(br.length?br.map(x=>'<span class="sc-b sc-bad">#'+x.n+' '+esc(x.name)+'</span>').join(''):(a.n?'<span class="sc-b sc-ok">none</span>':'—'))+'</td><td>'+o.n+'</td><td>'+money(o.net)+'</td></tr>'; }).join('')+'</tbody></table></div>';
  h+='<h3>Trades</h3><div class="tbl"><table><thead><tr><th style="text-align:left">Day</th><th style="text-align:left">Setup</th><th style="text-align:left">Contract</th><th>Entry</th><th>Exit</th><th>QQQ @ entry</th><th>Qty</th><th>Entry px</th><th>P&L</th><th style="text-align:left">Late Scalp flags</th></tr></thead><tbody>'
    +rs.slice().sort((a,b)=>b.first-a.first).map(r=>{ const u=r.setup==='late'?under(r):NaN; return '<tr><td style="text-align:left">'+r.day+'</td><td style="text-align:left">'+({late:'⏱️ Late',am:'🎯 Morning',out:'Outside'})[r.setup]+'</td><td style="text-align:left">'+esc(r.label)+'</td><td>'+hhmm(r.first)+'</td><td>'+hhmm(r.last)+'</td><td>'+(isFinite(u)?u.toFixed(2):'—')+'</td><td>'+r.bq+'</td><td>$'+(+r.entryPx).toFixed(2)+'</td><td>'+money(r.pnl)+'</td><td style="text-align:left">'+(r.flags?r.flags.map(f=>'<span class="sc-b sc-'+f[1]+'">'+esc(f[0])+'</span>').join(''):'')+'</td></tr>'; }).join('')+'</tbody></table></div>';
  el.innerHTML=h; }
if(typeof document!=='undefined') document.addEventListener('change',e=>{ if(e.target&&e.target.id==='sc10'){ last10=e.target.checked; if(lastArgs) render.apply(null,lastArgs); } });
root.SetupCompare={render,rounds};
})(typeof window!=='undefined'?window:globalThis);
