// Morning Brief renderer: reads data/brief/latest.json (built by .github/workflows/morning-brief.yml)
(function(){
  const el=document.getElementById('mb-body'); if(!el) return;
  const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const f=(n,d=2)=>n==null?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:d});
  const tag=i=>`<span class="mb-tag mb-${i}">${i}</span>`;
  const na=t=>`<p class="sub">⚠️ ${t} unavailable today (source failed). Check back after the next refresh.</p>`;
  function wallsCard(w,ratio){
    const nq=k=>(ratio&&w.sym==='QQQ')?` <small class="mb-nq">≈NQ ${f(k*ratio,0)}</small>`:'';
    const row=(l,k,c)=>`<tr><td>${l}</td><td style="color:${c}">${f(k)}${nq(k)}</td></tr>`;
    return `<div class="mb-card"><h3>${esc(w.sym)} · spot ${f(w.spot)} · exp ${esc(w.expiry)}${w.is0dte?' (0DTE)':''}</h3>
    <table class="mb-t">${row('Call wall (max OI)',w.call_wall_oi,'var(--green)')}${row('Call wall (max gamma)',w.call_wall_gamma,'var(--green)')}
    ${row('Gamma flip (zero-GEX est.)',w.gamma_flip,'var(--amber)')}${row('Max pain',w.max_pain,'var(--purple)')}
    ${row('Put wall (max gamma)',w.put_wall_gamma,'var(--red)')}${row('Put wall (max OI)',w.put_wall_oi,'var(--red)')}
    <tr><td>Net GEX</td><td style="color:${w.net_gex_sign==='positive'?'var(--green)':'var(--red)'}">${w.net_gex_sign} (${f(w.net_gex_musd,0)}M $/1%)</td></tr>
    <tr><td>Put/Call OI</td><td>${f(w.pcr_oi)}</td></tr></table>
    <p class="sub" style="margin:6px 0 0">${w.net_gex_sign==='negative'?'Negative gamma: dealers chase moves, expect bigger swings / trend.':'Positive gamma: dealers dampen moves, expect mean reversion / pinning.'}</p>
    <div class="mb-two"><div><b>Top call OI</b>${w.top_calls.map(x=>`<div>${f(x.k)} · ${f(x.oi,0)}</div>`).join('')}</div>
    <div><b>Top put OI</b>${w.top_puts.map(x=>`<div>${f(x.k)} · ${f(x.oi,0)}</div>`).join('')}</div></div></div>`;
  }
  function stratCard(t){
    if(!t) return '';
    const col=t.bias==='PUT'?'var(--red)':t.bias==='CALL'?'var(--green)':'var(--amber)';
    const ver=(n,v)=>v?`<div class="mb-card"><h3>${n}</h3><table class="mb-t"><tr><td>Entry</td><td><b>${esc(v.entry)}</b></td></tr><tr><td>TP1 +100%</td><td style="color:var(--green)">${esc(v.tp1)}</td></tr><tr><td>TP2 +300%</td><td style="color:var(--green)">${esc(v.tp2)}</td></tr><tr><td>Rest</td><td>kite until 3:30 PM ET</td></tr><tr><td>Stop</td><td style="color:var(--red)">${esc(v.stop)}</td></tr></table><p class="sub" style="margin:6px 0 0">${esc(v.setup)}</p></div>`:'';
    return `<h3>0 · Today's Strategy</h3><div class="mb-card" style="border-left:3px solid ${col}"><h3 style="color:${col}">${esc(t.bias)} bias${t.strength?' · '+esc(t.strength):''}</h3><p class="sub" style="margin:0">${esc(t.summary)}</p></div>
    <div class="mb-grid">${ver('Version A · Sweep entry',t.A)}${ver('Version B · Wall entry',t.B)}</div>
    <div class="mb-card"><b>Rules for both</b>${(t.rules||[]).map(r=>`<div>• ${esc(r)}</div>`).join('')}<p style="margin:8px 0 0"><b>Day invalidation:</b> <span style="color:var(--amber)">${esc(t.invalidation)}</span></p></div>
    <p class="sub" style="font-size:.8rem">${esc(t.disclaimer)}</p>`;
  }
  function render(b){
    const dl=d=>d===b.days[0]?'Today':'Next session';
    let h=(b.strategy&&b.strategy.plan?`<p style="margin:0 0 8px;font-weight:700;color:${b.strategy.bias==='PUT'?'var(--red)':b.strategy.bias==='CALL'?'var(--green)':'var(--amber)'}">${esc(b.strategy.plan)}</p>`:'')+`<p class="sub">Generated ${esc(b.generated.replace('T',' '))} ET. ${esc(b.note)}</p>`+stratCard(b.strategy)+`<h3>1 · 0DTE option walls</h3>`;
    h+=b.walls&&b.walls.length?`<div class="mb-grid">${b.walls.map(w=>wallsCard(w,b.nq_ratio)).join('')}</div>${b.nq_ratio?`<p class="sub">≈NQ = QQQ level × ${b.nq_ratio} (current ratio). Rough estimate only, not futures order-book walls.</p>`:''}`:na('Option walls');
    h+=`<h3>2 · Market calendar (ET)</h3>`;
    if(b.macro){h+=b.macro.length?`<table class="mb-t mb-cal"><tr><th>Day</th><th>Time</th><th>Event</th><th>Impact</th><th>Fcst / Prev</th></tr>${b.macro.map(e=>`<tr><td>${dl(e.date)}</td><td>${esc(e.time)}</td><td>${esc(e.title)}</td><td>${tag(e.impact)}</td><td>${esc(e.forecast)} / ${esc(e.previous)}</td></tr>`).join('')}</table>`:'<p class="sub">No US economic events scheduled.</p>';}else h+=na('Economic calendar');
    if(b.earnings){h+=`<h3 style="font-size:.9rem">Major earnings</h3>`+(b.earnings.length?`<table class="mb-t mb-cal"><tr><th>Day</th><th>Ticker</th><th>When</th><th>Mkt cap</th><th>Impact</th></tr>${b.earnings.slice(0,30).map(e=>`<tr><td>${dl(e.date)}</td><td><b>${esc(e.sym)}</b>${e.qqq_top?' ⭐':''}</td><td>${esc(e.when)}</td><td>$${f(e.mcap_b,0)}B</td><td>${tag(e.impact)}</td></tr>`).join('')}</table><p class="sub">⭐ = QQQ / mega-cap mover.</p>`:'<p class="sub">No major earnings.</p>');}else h+=na('Earnings calendar');
    h+=`<h3>3 · Gamma squeeze scanner</h3>`;
    const s=b.squeeze;
    h+=s?`<p class="sub">Scanned ${s.scanned} names (watchlist + Yahoo most-active / gainers / most-shorted). Edit <code>data/brief/watchlist.txt</code> to add tickers. Score is a heuristic, not a prediction.</p>
    <div style="overflow-x:auto"><table class="mb-t mb-cal"><tr><th>#</th><th>Ticker</th><th>Price</th><th>Score</th><th>Short %</th><th>Float</th><th>Call/Put OI</th><th>Call vol/OI</th><th>IV</th><th>5d</th><th>Why</th></tr>
    ${s.top.map((x,i)=>`<tr><td>${i+1}</td><td><b>${esc(x.sym)}</b>${x.penny?' 🪙':''}</td><td>${f(x.price)}</td><td><b>${f(x.score,0)}</b></td><td>${f(x.short_pct,0)}%</td><td>${f(x.float_m,0)}M</td><td>${f(x.cp_ratio,1)}</td><td>${f(x.cvol_oi)}</td><td>${f(x.iv,0)}%</td><td style="color:${x.mom5>=0?'var(--green)':'var(--red)'}">${f(x.mom5,1)}%</td><td class="mb-why">${x.why.map(esc).join(' · ')}</td></tr>`).join('')}</table></div>`:na('Squeeze scanner');
    if(b.errors&&b.errors.length) h+=`<p class="sub" style="font-size:.8rem">Source notes: ${b.errors.map(esc).join('; ')}</p>`;
    el.innerHTML=h;
  }
  fetch('data/brief/latest.json?t='+Date.now()).then(r=>{if(!r.ok)throw 0;return r.json()}).then(render)
    .catch(()=>{el.innerHTML='<p class="sub">Morning Brief not generated yet. It runs weekdays at 8:30 AM ET.</p>'});
})();
