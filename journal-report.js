/* Daily report card + playbook scoring. Pure functions; computed on the fly, never stored in the repo. */
(function(root){
const TP=()=>root.TradeParser;
const DEFAULT_CFG={priceLo:0.25,priceHi:0.45,greenThreshold:500,tickers:['SPY','QQQ']};
const etMin=ts=>{ const s=TP().fmtET(ts); return +s.slice(11,13)*60+ +s.slice(14,16); };
const hhmm=ts=>TP().fmtET(ts).slice(11,16);
const median=a=>{ if(!a.length) return NaN; const s=a.slice().sort((x,y)=>x-y), m=s.length>>1; return s.length%2?s[m]:(s[m-1]+s[m])/2; };
const money=n=>(n<0?'-':'')+'$'+Math.abs(n).toLocaleString('en-US',{maximumFractionDigits:0});

function rounds(execs){ // per contract round, with fills
  const T=TP(); const sums=T.summarize(execs);
  return sums.map(g=>{ const fills=execs.filter(x=>x.group===g.group).sort((a,b)=>a.ts-b.ts);
    const entry=fills.find(f=>/^entry/.test(f.tag)); return {...g,fills,entry,started:!!entry,ticker:fills[0].ticker,cost:g.bc*g.m}; });
}
function dayStats(execs){ const rs=rounds(execs); const pl=rs.reduce((a,r)=>a+r.netPl,0); const started=rs.filter(r=>r.started);
  return {rs,pl,started,avgPerTrade:started.length?started.reduce((a,r)=>a+r.cost,0)/started.length:NaN}; }

function report(day,execs,history,cfg){
  cfg={...DEFAULT_CFG,...(cfg||{})}; const {rs,pl,started,avgPerTrade}=dayStats(execs);
  const closed=rs.filter(r=>r.open===0), wins=closed.filter(r=>r.netPl>0), losses=closed.filter(r=>r.netPl<0);
  const holds=closed.map(r=>(r.last-r.first)/60000);
  const before10=started.filter(r=>etMin(r.entry.ts)<600).length, after10=started.length-before10;
  // re-entries within 15 min of a losing round closing
  const byStart=started.slice().sort((a,b)=>a.entry.ts-b.entry.ts); let reentries=0;
  losses.forEach(l=>{ if(byStart.some(r=>r!==l&&r.entry.ts>=l.last&&r.entry.ts-l.last<=15*60000)) reentries++; });
  const withAdds=rs.filter(r=>r.fills.some(f=>/^add/.test(f.tag))).length;
  const rules=[];
  // 1. time window + tickers
  { const bad=[]; started.forEach(r=>{ const m=etMin(r.entry.ts); if(m<570||m>690) bad.push(`${r.label} entered ${hhmm(r.entry.ts)}`); if(!cfg.tickers.includes(r.ticker)) bad.push(`${r.ticker} not SPY/QQQ`); });
    rules.push({n:1,name:'9:30–11:30 ET, SPY/QQQ only',status:bad.length?'broken':'ok',why:bad}); }
  // 2. 1-3 trades, stop after first loss
  { const bad=[]; if(started.length>3) bad.push(`${started.length} trades (max 3)`);
    const firstLoss=losses.slice().sort((a,b)=>a.last-b.last)[0];
    if(firstLoss){ const after=byStart.filter(r=>r.entry.ts>firstLoss.last); if(after.length) bad.push(`${after.length} new entr${after.length>1?'ies':'y'} after first loss (${firstLoss.label} closed ${hhmm(firstLoss.last)})`); }
    rules.push({n:2,name:'1–3 trades, stop after first loss',status:started.length===0?'na':bad.length?'broken':'ok',why:bad}); }
  // 3. cheap strike, no adds below avg cost
  { const bad=[]; started.forEach(r=>{ if(r.right==='S') return; const p=r.entry.price; if(p<cfg.priceLo||p>cfg.priceHi) bad.push(`${r.label} entry $${p.toFixed(2)}`); });
    rs.forEach(r=>{ let q=0,c=0; r.fills.forEach(f=>{ if(f.side==='buy'){ if(/^add/.test(f.tag)&&q>0&&f.price<c/q-1e-9) bad.push(`${r.label} added at $${f.price.toFixed(2)} below avg $${(c/q).toFixed(2)}`); q+=f.qty; c+=f.qty*f.price; } else if(q>0){ const k=Math.min(1,f.qty/q); c-=c*k; q=Math.max(0,q-f.qty); } }); });
    rules.push({n:3,name:`Entry $${cfg.priceLo.toFixed(2)}–${cfg.priceHi.toFixed(2)}, no adds below avg`,status:started.length===0?'na':bad.length?'broken':'ok',why:bad}); }
  // 4. partial at +100%, all closed by 15:30
  { const bad=[]; let reached=0;
    rs.forEach(r=>{ const exits=r.fills.filter(f=>f.side==='sell'); const hit=exits.find(f=>r.avgIn>0&&f.price>=2*r.avgIn);
      if(hit){ reached++; if(!/partial/.test(hit.tag)&&r.bq>1) bad.push(`${r.label}: first +100% exit sold everything (no partial)`); }
      const late=r.fills.filter(f=>etMin(f.ts)>930&&f.side==='sell'); if(late.length) bad.push(`${r.label}: ${late[0].expired?'expired':'closed'} at ${hhmm(late[0].ts)} (after 15:30)`);
      if(r.open>0&&(!r.expiry||r.expiry<=day)) bad.push(`${r.label}: ${r.open} still open`); });
    rules.push({n:4,name:'Half at +100%, closed by 15:30',status:bad.length?'broken':reached?'ok':'na',why:bad.length?bad:reached?[]:['no position reached +100%']}); }
  // 5. size flat after big green day
  { const prior=(history||[]).filter(h=>h.day<day).sort((a,b)=>a.day<b.day?-1:1); const last5=prior.slice(-5); const green=last5.filter(h=>h.pl>=cfg.greenThreshold).pop();
    if(!green||!isFinite(avgPerTrade)) rules.push({n:5,name:`Flat size after a ≥${money(cfg.greenThreshold)} day`,status:'na',why:[green?'no trades today':'no big green day in prior 5 sessions']});
    else { const base=prior.filter(h=>h.day<green.day).slice(-10).filter(h=>isFinite(h.avgPerTrade)); const avg=base.length?base.reduce((a,h)=>a+h.avgPerTrade,0)/base.length:NaN;
      const ok=!isFinite(avg)||avgPerTrade<=avg*1.1; rules.push({n:5,name:`Flat size after a ≥${money(cfg.greenThreshold)} day`,status:isFinite(avg)?(ok?'ok':'broken'):'na',why:isFinite(avg)?(ok?[]:[`avg ${money(avgPerTrade)}/trade vs limit ${money(avg*1.1)} (green day ${green.day} ${money(green.pl)})`]):['no 10-day baseline before the green day']}); } }
  rules.forEach(r=>r.why=[...new Set(r.why)]);
  const followed=rules.filter(r=>r.status!=='broken').length;
  return {day,pl,trades:started.length,rounds:rs.length,closed:closed.length,winRate:closed.length?wins.length/closed.length:NaN,
    avgWin:wins.length?wins.reduce((a,r)=>a+r.netPl,0)/wins.length:NaN,avgLoss:losses.length?losses.reduce((a,r)=>a+r.netPl,0)/losses.length:NaN,
    medianHold:median(holds),before10,after10,reentries,withAdds,avgPerTrade,rules,followed,wins:wins.length,losses:losses.length};
}
function history(allExecs){ const by={}; allExecs.forEach(e=>{ const d=TP().fmtET(e.ts).slice(0,10); (by[d]=by[d]||[]).push(e); });
  return Object.keys(by).sort().map(day=>{ const s=dayStats(by[day]); return {day,pl:s.pl,avgPerTrade:s.avgPerTrade,execs:by[day]}; }); }
function summaryText(r){ const pct=x=>isFinite(x)?Math.round(x*100)+'%':'—';
  const broken=r.rules.filter(x=>x.status==='broken');
  return `${r.day} · P/L ${money(r.pl)} · ${r.trades} trade${r.trades===1?'':'s'} · win rate ${pct(r.winRate)} · avg win ${isFinite(r.avgWin)?money(r.avgWin):'—'} / avg loss ${isFinite(r.avgLoss)?money(r.avgLoss):'—'} · median hold ${isFinite(r.medianHold)?Math.round(r.medianHold)+'m':'—'} · entries <10AM ${r.before10} / ≥10AM ${r.after10} · quick re-entries after loss ${r.reentries} · positions with adds ${r.withAdds}\nPlaybook: ${r.followed}/5 followed`+(broken.length?` — broke ${broken.map(b=>`#${b.n} ${b.name} (${b.why.join('; ')})`).join(' | ')}`:' ✓'); }
root.JournalReport={report,history,summaryText,DEFAULT_CFG};
})(typeof window!=='undefined'?window:globalThis);
