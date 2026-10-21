/* Tolerant parser for pasted broker order history (Wealthsimple & generic).
   Exposes window.TradeParser = { parse, etToEpoch, fmtET, tagRows, summarize }. */
(function(root){
const TZ='America/New_York';
const MON=['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
const MRE='(?:'+MON.map(m=>m[0].toUpperCase()+m.slice(1)+'|'+m.toUpperCase()+'|'+m).join('|')+')[a-zA-Z]*\\.?';
const DATE='(?:\\d{4}-\\d{2}-\\d{2}|\\d{1,2}\\/\\d{1,2}(?:\\/\\d{2,4})?|'+MRE+'\\s+\\d{1,2}(?:st|nd|rd|th)?(?:,?\\s+\\d{4})?)';
const STOP=new Set(('BUY SELL BOUGHT SOLD CALL CALLS PUT PUTS C P ET EST EDT AM PM USD CAD US OPEN CLOSE TO BTO STC STO BTC LIMIT MARKET LMT MKT FILLED FILL QTY AVG PRICE DAY GTC ORDER ORDERS STATUS TOTAL EXP EXPIRY STRIKE OPTION OPTIONS CONTRACT CONTRACTS FEE FEES TRADE LONG SHORT DONE EXECUTED X ID NA N A AT OF ON IN THE AND FOR TYPE SIDE TIME DATE NET CASH SUB AMOUNT VALUE COMMISSION ACTIVITY QUANTITY UNIT SYMBOL DESCRIPTION DIRECTION CURRENCY SETTLED PARTIAL PARTIALLY COMPLETE COMPLETED SUBMITTED FILLS '+MON.join(' ').toUpperCase()+' SEPT MON TUE WED THU FRI SAT SUN').split(' '));
const pad=n=>String(n).padStart(2,'0');

function etParts(ts){ const p={}; new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(ts)).forEach(x=>p[x.type]=x.value); return p; }
function etToEpoch(y,mo,d,h=0,mi=0,s=0){ let g=Date.UTC(y,mo-1,d,h,mi,s); for(let i=0;i<2;i++){ const p=etParts(g); const asU=Date.UTC(+p.year,+p.month-1,+p.day,+p.hour%24,+p.minute,+p.second); g+=Date.UTC(y,mo-1,d,h,mi,s)-asU; } return g; }
function fmtET(ts){ const p=etParts(ts); return `${p.year}-${p.month}-${p.day} ${pad(+p.hour%24)}:${p.minute}:${p.second}`; }
function parseETString(s){ const m=String(s||'').trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/); return m?etToEpoch(+m[1],+m[2],+m[3],+(m[4]||9),+(m[5]||30),+(m[6]||0)):NaN; }

function yr(y,ref){ if(!y) return ref; y=+y; return y<100?2000+y:y; }
function parseDateToken(t,refY){ let m;
  if(m=t.match(/^(\d{4})-(\d{2})-(\d{2})$/)) return {y:+m[1],m:+m[2],d:+m[3]};
  if(m=t.match(/^(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?$/)) return {y:yr(m[3],refY),m:+m[1],d:+m[2]};
  if(m=t.match(new RegExp('^('+MRE+')\\s+(\\d{1,2})(?:st|nd|rd|th)?(?:,?\\s+(\\d{4}))?$'))){ const mo=MON.indexOf(m[1].slice(0,3).toLowerCase())+1; if(mo>0) return {y:yr(m[3],refY),m:mo,d:+m[2]}; }
  return null; }
const iso=o=>o?`${o.y}-${pad(o.m)}-${pad(o.d)}`:'';
const num=s=>parseFloat(String(s).replace(/[,$\s]/g,''));

// ---- contract descriptor ----
const RIGHT='(C|P|[Cc]all|[Pp]ut|CALL|PUT)s?';
const RE_OCC=/\b([A-Z]{1,6})\s*(\d{2})(\d{2})(\d{2})([CP])(\d{8})\b/;
const RE_A=new RegExp('\\b([A-Z]{1,5})\\s+(?:('+DATE+')\\s+)?(?:Exp\\w*\\s+)?\\$?(\\d+(?:\\.\\d+)?)\\s*'+RIGHT+'\\b(?:\\s+(?:exp\\w*\\s+)?('+DATE+'))?','g');
const RE_B=new RegExp('\\b([A-Z]{1,5})\\s+(?:('+DATE+')\\s+)?'+RIGHT+'\\s+\\$?(\\d+(?:\\.\\d+)?)\\b(?:\\s+('+DATE+'))?','g');
const RE_C=new RegExp('(?:^|[\\s(])\\$?(\\d+(?:\\.\\d+)?)\\s*'+RIGHT+'\\b(?:\\s+('+DATE+'))?','g');
function findContract(t,refY,defTicker){
  let m=t.match(RE_OCC);
  if(m&&!STOP.has(m[1])) return {ticker:m[1],expiry:`20${m[2]}-${m[3]}-${m[4]}`,right:m[5],strike:+m[6]/1000,span:m[0]};
  for(const re of [RE_A,RE_B]){ re.lastIndex=0; let x; while((x=re.exec(t))){ if(STOP.has(x[1])) { re.lastIndex=x.index+1; continue; }
    const isB=re===RE_B; const strike=+(isB?x[4]:x[3]), right=(isB?x[3]:x[4])[0].toUpperCase(); const dt=x[2]||x[5];
    return {ticker:x[1],strike,right,expiry:dt?iso(parseDateToken(dt.trim(),refY)):'',span:x[0]}; } }
  RE_C.lastIndex=0; let c; while((c=RE_C.exec(t))){ const before=t.slice(0,c.index); const toks=(before.match(/\b[A-Z]{1,5}\b/g)||[]).filter(w=>!STOP.has(w));
    return {ticker:toks.length?toks[toks.length-1]:(defTicker||''),strike:+c[1],right:c[2][0].toUpperCase(),expiry:c[3]?iso(parseDateToken(c[3].trim(),refY)):'',span:c[0].trim()}; }
  return null; }
const hasContract=(t)=>RE_OCC.test(t)||(RE_A.lastIndex=0,RE_A.test(t))||(RE_B.lastIndex=0,RE_B.test(t))||(RE_C.lastIndex=0,RE_C.test(t));

// ---- timestamp ----
const RE_TIME=/\b(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*([AaPp]\.?[Mm]\.?)?/g;
const RE_ISOZ=/\b(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*(Z|[+-]\d{2}:?\d{2})\b/;
function findTimestamp(t,ctxDate){
  let z=t.match(RE_ISOZ); if(z){ const ts=Date.parse(`${z[1]}T${z[2]}${z[3].length===5?z[3].slice(0,3)+':'+z[3].slice(3):z[3]}`); if(isFinite(ts)) return {ts,span:z[0],hasTime:true}; }
  const refY=ctxDate?ctxDate.y:new Date().getFullYear();
  const dates=[]; const dre=new RegExp(DATE,'g'); let d; while((d=dre.exec(t))){ const o=parseDateToken(d[0].trim(),refY); if(o&&o.m>=1&&o.m<=12&&o.d>=1&&o.d<=31) dates.push({o,i:d.index,s:d[0]}); }
  const times=[]; RE_TIME.lastIndex=0; let m; while((m=RE_TIME.exec(t))){ let h=+m[1]; const ap=(m[4]||'').toLowerCase(); if(ap.startsWith('p')&&h<12) h+=12; if(ap.startsWith('a')&&h===12) h=0; if(h<24&&+m[2]<60) times.push({h,mi:+m[2],s:+(m[3]||0),i:m.index,str:m[0]}); }
  if(times.length){ const tm=times[0]; let best=null;
    dates.forEach(x=>{ const dist=Math.abs(x.i-tm.i); if(!best||dist<best.dist) best={...x,dist}; });
    const o=best&&best.dist<40?best.o:ctxDate; if(!o) return null;
    return {ts:etToEpoch(o.y,o.m,o.d,tm.h,tm.mi,tm.s),span:tm.str,dateSpan:best&&best.dist<40?best.s:'',hasTime:true}; }
  if(dates.length){ const o=dates[dates.length-1].o; return {ts:etToEpoch(o.y,o.m,o.d,9,30,0),span:'',dateSpan:dates[dates.length-1].s,hasTime:false}; }
  return null; }

// ---- side / qty / price ----
function findSide(t){ const s=t.toLowerCase();
  if(/\b(buy(?:\s+to\s+(?:open|close))?|bought|bto|btc|long)\b/.test(s)&&!/\b(sell|sold|stc|sto)\b/.test(s)) return 'buy';
  if(/\b(sell(?:\s+to\s+(?:open|close))?|sold|stc|sto)\b/.test(s)) return 'sell';
  if(/\bbuy\b|\bbought\b/.test(s)) return 'buy'; return ''; }
function findQty(t){ let m;
  if(m=t.match(/\bfill(?:ed)?\s*(?:qty|quantity)?\s*:?\s*(\d+)\s*(?:\/|of)\s*\d+/i)) return {q:+m[1],span:m[0]};
  if(m=t.match(/\b(\d+)\s*(?:\/|of)\s*\d+\s*(?:filled|contracts?\s+filled)/i)) return {q:+m[1],span:m[0]};
  if(m=t.match(/\b(?:filled\s*(?:qty|quantity)?|qty|quantity|contracts|shares)\s*:?\s*(-?\d+(?:\.\d+)?)/i)) return {q:Math.abs(+m[1]),span:m[0],neg:+m[1]<0};
  if(m=t.match(/\b(\d+(?:\.\d+)?)\s*(?:contracts?|cts?|x)\b/i)) return {q:+m[1],span:m[0]};
  if(m=t.match(/\bx\s*(\d+)\b/i)) return {q:+m[1],span:m[0]};
  if(m=t.match(/\b(?:bought|sold|buy|sell|bto|stc|sto|btc)(?:\s+to\s+(?:open|close))?\s+(\d+)\b(?![.:\/]\d)(?!\s*[CcPp]\b)/i)) return {q:+m[1],span:m[0]};
  return null; }
function findPrice(t,strike){ let m;
  const re=/(?:avg(?:\.|erage)?\.?\s*(?:fill(?:ed)?\s*)?(?:price)?|fill(?:ed)?\s*(?:price|at|@)|price|premium|@|\bat)\s*[:=]?\s*\$?\s*(\d*\.?\d+)/ig;
  while((m=re.exec(t))){ const v=+m[1]; if(isFinite(v)&&v!==strike) return v; }
  const c=[...t.matchAll(/\$\s*(\d[\d,]*\.?\d*)/g)].map(x=>num(x[1])).filter(v=>isFinite(v)&&v>0&&v!==strike);
  return c.length?Math.min(...c):NaN; }

function extract(text,ctx){
  const raw=text; let t=' '+text.replace(/\s+/g,' ')+' ';
  if(/\b(cancel+ed|rejected|expired\s+order|failed)\b/i.test(t)) return {skip:'cancelled/rejected order'};
  const tsr=findTimestamp(t,ctx.date);
  const k=findContract(t.replace(tsr&&tsr.span&&tsr.hasTime?tsr.span:'\u0000',' '),ctx.date?ctx.date.y:new Date().getFullYear(),ctx.ticker);
  let rest=t; if(k) rest=rest.replace(k.span,' '); if(tsr){ if(tsr.span) rest=rest.replace(tsr.span,' '); if(tsr.dateSpan) rest=rest.replace(tsr.dateSpan,' '); }
  const q=findQty(rest); if(q) rest=rest.replace(q.span,' ');
  const side=findSide(t)||(q&&q.neg?'sell':'');
  const price=findPrice(rest,k?k.strike:NaN);
  const ts=tsr?tsr.ts:NaN;
  const exp=k&&k.expiry?k.expiry:(isFinite(ts)?fmtET(ts).slice(0,10):'');
  return {raw,ts,hasTime:!!(tsr&&tsr.hasTime),ticker:k?k.ticker:'',strike:k?k.strike:NaN,right:k?k.right:'',expiry:exp,expiryAssumed:!!(k&&!k.expiry),side,qty:q?q.q:NaN,price};
}

// ---- CSV / TSV ----
function splitDelim(line,d){ const out=[]; let cur='',q=false; for(let i=0;i<line.length;i++){ const ch=line[i];
  if(q){ if(ch==='"'){ if(line[i+1]==='"'){cur+='"';i++;} else q=false; } else cur+=ch; }
  else if(ch==='"') q=true; else if(ch===d){ out.push(cur); cur=''; } else cur+=ch; } out.push(cur); return out.map(s=>s.trim()); }
const HEAD={time:/^(transaction_?date|date|time|date\/time|filled_?at|fill(ed)? (time|date)|executed|execution time|created_?at|submitted|trade date|time placed)$/i,
  symbol:/^(symbol|instrument|security|contract|option|ticker|underlying)$/i, desc:/^(description|name|details|order)$/i,
  side:/^(activity_?sub_?type|side|action|buy\/sell|transaction|order type)$/i, atype:/^(activity_?type)$/i,
  qty:/^(quantity|qty|filled|filled qty|filled quantity|contracts|shares)$/i, price:/^(unit_?price|price|avg price|average price|fill price|filled price|avg_?price|avg fill price|average fill price)$/i,
  net:/^(net_?cash_?amount|amount|net amount|total|value|net)$/i, strike:/^(strike|strike price)$/i, expiry:/^(expiry|expiration|expiration date|exp|exp date)$/i, right:/^(call\/put|put\/call|right|option type|type)$/i, status:/^(status|order status)$/i};
function parseTable(lines,d,ctx){
  const head=splitDelim(lines[0],d); const map={}; head.forEach((h,i)=>{ for(const k in HEAD) if(map[k]===undefined&&HEAD[k].test(h.replace(/\s+/g,' '))) { map[k]=i; break; } });
  const rows=[],ignored=[];
  lines.slice(1).forEach(line=>{ if(!line.trim()) return; const c=splitDelim(line,d);
    if(c.length<2||/^"?as of /i.test(line)){ ignored.push({raw:'(footer)',why:'footer / not a trade'}); return; }
    const g=k=>map[k]!==undefined?c[map[k]]||'':'';
    if(map.atype!==undefined&&g('atype')&&!/trade|option|buy|sell/i.test(g('atype'))){ ignored.push({raw:g('atype'),why:'not a trade'}); return; }
    if(/cancel|reject/i.test(g('status'))){ ignored.push({raw:g('symbol')+' '+g('time'),why:'cancelled order'}); return; }
    const r=extract([g('time'),g('symbol'),g('desc'),g('side')].join(' '),ctx);
    if(r.skip){ ignored.push({raw:g('symbol')+' '+g('time'),why:r.skip}); return; }
    r.raw=['time','symbol','side','qty','price'].map(g).filter(Boolean).join(' | ');
    if(map.strike!==undefined&&isFinite(num(g('strike')))) r.strike=num(g('strike'));
    if(map.right!==undefined&&/^(c|p|call|put)/i.test(g('right'))) r.right=g('right')[0].toUpperCase();
    if(map.expiry!==undefined&&g('expiry')){ const o=parseDateToken(g('expiry'),new Date().getFullYear()); if(o){ r.expiry=iso(o); r.expiryAssumed=false; } }
    if(map.side!==undefined){ const s=findSide(g('side')); if(s) r.side=s; }
    if(map.qty!==undefined&&isFinite(num(g('qty')))){ const q=num(g('qty')); r.qty=Math.abs(q); if(q<0&&!r.side) r.side='sell'; }
    if(map.price!==undefined&&isFinite(num(g('price')))) r.price=Math.abs(num(g('price')));
    if(map.net!==undefined&&isFinite(num(g('net')))&&r.qty>0&&r.price>0){ const net=Math.abs(num(g('net'))), per=r.qty*r.price;
      if(Math.abs(net-per)/per<0.15 && Math.abs(net-per*100)/(per*100)>0.15) r.price=r.price/100; // Wealthsimple: unit_price per contract
      if(!r.side) r.side=num(g('net'))<0?'buy':'sell'; }
    if(!r.ticker&&ctx.ticker) r.ticker=ctx.ticker;
    if(!isFinite(r.ts)&&ctx.date) r.ts=etToEpoch(ctx.date.y,ctx.date.m,ctx.date.d,9,30,0);
    rows.push(r); });
  return {rows,ignored,format:'table ('+(d===','?'CSV':d==='\t'?'tab-separated':'delimited')+')'};
}

// ---- Wealthsimple Activity export (primary format) ----
// Whitelist: only these fields ever leave this function. account_id, account_type, settlement_date, description, name are dropped here.
function isWS(head){ const h=head.map(x=>x.toLowerCase()); return h.includes('activity_type')&&h.includes('symbol')&&(h.includes('effective_date')||h.includes('transaction_date')); }
function parseWS(lines,d,opts){
  const head=splitDelim(lines[0],d).map(x=>x.toLowerCase()); const ix=k=>head.indexOf(k);
  const I={date:ix('effective_date')>=0?ix('effective_date'):ix('transaction_date'),time:ix('effective_time'),type:ix('activity_type'),sub:ix('activity_sub_type'),sym:ix('symbol'),und:ix('underlying symbol'),qty:ix('quantity'),price:ix('unit_price'),fee:ix('commission'),net:ix('net_cash_amount'),cur:ix('currency')};
  const rows=[], skipped={};
  for(const line of lines.slice(1)){ if(!line.trim()) continue; const c=splitDelim(line,d); const g=k=>I[k]>=0?(c[I[k]]||'').trim():'';
    const type=g('type'); const skip=w=>{ skipped[w]=(skipped[w]||0)+1; };
    if(c.length<5){ skip('footer / not a row'); continue; }
    const occ=g('sym').match(/^([A-Z.]{1,6})\s+(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/);
    const dm=g('date').match(/^(\d{4})-(\d{2})-(\d{2})$/); if(!dm){ skip('no date'); continue; }
    const tm=(g('time').match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?/)||[]);
    const ts=etToEpoch(+dm[1],+dm[2],+dm[3],+(tm[1]||9),+(tm[2]||30),+(tm[3]||0));
    const q=num(g('qty')), fee=Math.abs(num(g('fee'))||0), net=num(g('net'));
    let r=null;
    if(type==='Trade'&&occ){ const sub=g('sub').toUpperCase(); const side=sub==='BUY'?'buy':sub==='SELL'?'sell':(q<0?'sell':'buy');
      r={ts,hasTime:!!tm[1],ticker:occ[1],expiry:`20${occ[2]}-${occ[3]}-${occ[4]}`,right:occ[5],strike:+occ[6]/1000,side,qty:Math.abs(q),price:num(g('price'))/100,fee}; }
    else if(type==='OptionExpiry'&&occ){ r={ts,hasTime:!!tm[1],ticker:occ[1],expiry:`20${occ[2]}-${occ[3]}-${occ[4]}`,right:occ[5],strike:+occ[6]/1000,side:q<0?'sell':'buy',qty:Math.abs(q),price:0,fee:0,expired:true}; }
    else if(type==='Trade'&&opts.includeStocks&&g('sym')){ const sub=g('sub').toUpperCase();
      r={ts,hasTime:!!tm[1],ticker:g('sym').toUpperCase(),expiry:'',right:'S',strike:0,side:sub==='BUY'?'buy':'sell',qty:Math.abs(q),price:num(g('price')),fee}; }
    else { skip(type==='Trade'?'stock trade (enable "Include stocks")':(type||'unknown')); continue; }
    if(isFinite(net)) Object.defineProperty(r,'net',{value:net,enumerable:false}); // in-memory only, for the cash cross-check
    r.raw=`${g('date')} ${g('time')} ${type} ${g('sub')} ${g('sym').replace(/\s+/g,' ')} qty ${g('qty')} @ ${g('price')}`; // sanitized: whitelisted fields only
    rows.push(r); }
  rows.sort((a,b)=>a.ts-b.ts);
  return {rows,ignored:Object.entries(skipped).map(([why,n])=>({raw:`${n} row${n>1?'s':''}`,why})),format:'Wealthsimple Activity export'};
}

function parse(text,opts={}){
  const defDate=opts.date?parseDateToken(opts.date,new Date().getFullYear()):null;
  const ctx={date:defDate,ticker:(opts.ticker||'').toUpperCase()};
  const lines=String(text||'').replace(/\r/g,'').split('\n');
  const first=lines.find(l=>l.trim())||'';
  for(const d of [',','\t',';']){ const cells=splitDelim(first,d); if(cells.length>=5&&isWS(cells)) return parseWS(lines.filter(l=>l.trim()),d,opts); }
  for(const d of ['\t',',',';','|']){ const cells=splitDelim(first,d); if(cells.length>=3&&cells.filter(h=>Object.values(HEAD).some(re=>re.test(h.replace(/\s+/g,' ')))).length>=2) return parseTable(lines.filter(l=>l.trim()),d,ctx); }
  // free text: group lines into blocks
  const blocks=[]; let cur=null, pending=[];
  const isDateOnly=l=>{ const s=l.replace(/\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*,?/ig,'').replace(/today|yesterday/ig,'').trim(); return s&&parseDateToken(s.replace(/,$/,''),new Date().getFullYear()); };
  const anyBlank=lines.some(l=>!l.trim());
  // if blank-line separated chunks each have <=1 contract, use chunks
  if(anyBlank){ const chunks=[]; let c=[]; lines.forEach(l=>{ if(!l.trim()){ if(c.length) chunks.push(c); c=[]; } else c.push(l); }); if(c.length) chunks.push(c);
    const counts=chunks.map(ch=>ch.filter(hasContract).length);
    if(chunks.length>1&&counts.every(n=>n<=1)&&counts.some(n=>n===1)){ chunks.forEach(ch=>{ const dOnly=ch.length===1&&isDateOnly(ch[0]); if(dOnly){ blocks.push({ctxDate:dOnly}); } else blocks.push({lines:ch}); }); }
  }
  if(!blocks.length){ lines.forEach(l=>{ const s=l.trim(); if(!s){ if(cur&&cur.has){ blocks.push(cur); cur=null; } return; }
      const dOnly=isDateOnly(s); if(dOnly&&!hasContract(s)){ if(cur){ blocks.push(cur); cur=null; } blocks.push({ctxDate:dOnly}); return; }
      if(hasContract(s)){ if(cur&&cur.has){ blocks.push(cur); cur=null; } if(!cur) cur={lines:pending.splice(0)}; cur.lines.push(s); cur.has=true; }
      else if(cur) cur.lines.push(s); else pending.push(s); });
    if(cur) blocks.push(cur); }
  const rows=[], ignored=pending.map(raw=>({raw,why:'no option contract found'}));
  blocks.forEach(b=>{ if(b.ctxDate){ ctx.date=b.ctxDate; return; }
    const text=b.lines.join('\n');
    if(!b.lines.some(hasContract)){ ignored.push({raw:text,why:'no option contract found'}); return; }
    const r=extract(text,ctx); if(r.skip){ ignored.push({raw:text,why:r.skip}); return; }
    if(!isFinite(r.ts)&&ctx.date) r.ts=etToEpoch(ctx.date.y,ctx.date.m,ctx.date.d,9,30,0);
    if(!r.expiry&&isFinite(r.ts)) { r.expiry=fmtET(r.ts).slice(0,10); r.expiryAssumed=true; }
    rows.push(r); });
  return {rows,ignored,format:'free text'};
}

// ---- tagging & summary ----
const keyOf=r=>`${r.ticker}|${r.expiry}|${r.strike}|${r.right}`;
const label=r=>r.right==='S'?`${r.ticker} (stock)`:`${r.ticker} ${r.strike}${r.right} ${r.expiry?r.expiry.slice(5).replace('-','/'):''}`;
const mult=r=>r.right==='S'?1:100;
function valid(r){ if(r.right==='S') return !!r.ticker&&(r.side==='buy'||r.side==='sell')&&r.qty>0&&r.price>=0&&isFinite(r.ts); return r.ticker&&r.strike>0&&(r.right==='C'||r.right==='P')&&(r.side==='buy'||r.side==='sell')&&r.qty>0&&r.price>=0&&isFinite(r.ts)&&/^\d{4}-\d{2}-\d{2}$/.test(r.expiry||''); }
function tagRows(rows){ const pos={}, round={};
  rows.map((r,i)=>({r,i})).sort((a,b)=>(a.r.ts-b.r.ts)||(a.i-b.i)).forEach(({r})=>{ r.tag=''; r.group=''; if(!valid(r)) return;
    const k=keyOf(r); const p=pos[k]||0; const d=r.side==='buy'?r.qty:-r.qty; const day=fmtET(r.ts).slice(0,10);
    if(p===0){ round[k]=(round[k]||0)+1; r.tag=d>0?'entry':'entry (short)'; }
    else if(Math.sign(p)===Math.sign(d)) r.tag=p>0?'add':'add (short)';
    else { const np=p+d; r.tag=(r.expired?'expired ':'exit ')+(np===0?'(final)':Math.sign(np)!==Math.sign(p)?'(flip)':'(partial)'); }
    pos[k]=p+d; r.group=`${day}_${r.ticker}_${r.expiry||'stk'}_${r.strike}${r.right}_r${round[k]}`; });
  return rows; }
function summarize(rows){ const g={};
  rows.filter(valid).forEach(r=>{ const s=g[r.group]=g[r.group]||{group:r.group,label:label(r),round:+(r.group.split('_r').pop()),bq:0,bc:0,sq:0,sc:0,n:0,first:r.ts,last:r.ts};
    s.fee=(s.fee||0)+(+r.fee||0); s.m=mult(r); if(isFinite(r.net)) { s.cash=(s.cash||0)+r.net; s.hasCash=true; } s.n++; s.first=Math.min(s.first,r.ts); s.last=Math.max(s.last,r.ts); if(r.side==='buy'){ s.bq+=r.qty; s.bc+=r.qty*r.price; } else { s.sq+=r.qty; s.sc+=r.qty*r.price; } });
  return Object.values(g).map(s=>{ s.avgIn=s.bq?s.bc/s.bq:NaN; s.avgOut=s.sq?s.sc/s.sq:NaN; s.matched=Math.min(s.bq,s.sq); s.open=s.bq-s.sq;
    s.fee=s.fee||0; s.pl=s.matched?(s.avgOut-s.avgIn)*s.matched*s.m:0; s.netPl=s.pl-s.fee; return s; }).sort((a,b)=>a.first-b.first); }

function fixOrder(res){ const rows=res.rows; if(!rows.length||rows.some(r=>r.hasTime)) return res;
  const bad=list=>{ tagRows(list.map((r,i)=>Object.assign(r,{ts:Math.floor(r.ts/60000)*60000+i*1000}))); return list.filter(r=>/no open/.test(r.tag)).length; };
  const fwd=bad(rows.slice()), rev=bad(rows.slice().reverse());
  const order=rev<fwd?rows.slice().reverse():rows.slice(); bad(order); res.rows=order; if(rev<fwd) res.note='No times in data — list looked newest-first, so it was reversed to chronological order.'; else if(rows.length>1) res.note='No times in data — kept the pasted order as chronological.'; return res; }
root.TradeParser={mult,parse:(t,o)=>fixOrder(parse(t,o)),etToEpoch,fmtET,parseETString,tagRows,summarize,valid,label};
})(typeof window!=='undefined'?window:globalThis);
