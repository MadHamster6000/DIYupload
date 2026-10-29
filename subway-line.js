/* Trading Subway Line — $1k→$1M metro map, position sizes, daily-loss framing, time-cost timer.
   Private inputs in this browser only (localStorage). */
(function(){
  var root=document.getElementById('sw-body'); if(!root) return;

  var STATIONS=[1000,2000,4000,8000,16000,32000,64000,128000,256000,512000,1000000];
  var CONTRACTS={1000:4,2000:8,4000:16,8000:32,16000:64,32000:128,64000:256,128000:512,256000:1024,512000:2048,1000000:4096};
  var AVG_PREM=0.30; // $/share average premium for TP panel (×100 = $30 per contract)
  var GOAL=1000000, DEFAULT=2000, BASE_CT=4;
  var SK='mh_subway_station', EK='mh_subway_expectancy';
  var TRADING_DAYS_PER_MONTH=21, TRADING_DAYS_PER_YEAR=252;

  function fmt(n){return n.toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0});}
  function fmtN(n,d){return n.toLocaleString('en-US',{maximumFractionDigits:d==null?0:d});}
  function pct(part,whole){
    if(!whole) return '0';
    var p=(part/whole)*100;
    if(p>=10) return p.toFixed(1);
    if(p>=1) return p.toFixed(2);
    if(p>=0.01) return p.toFixed(3);
    return p.toFixed(4);
  }
  function shortLab(cap){
    if(cap>=1000000) return '$1M';
    if(cap>=1000) return '$'+(cap/1000)+'k';
    return fmt(cap);
  }
  function ct(cap){return CONTRACTS[cap]||Math.max(1,Math.round(4*cap/1000));} // doubling scale: 4 × (capital ÷ 1000), no cap

  function loadStation(){
    try{var v=Number(localStorage.getItem(SK)); if(STATIONS.indexOf(v)>=0) return v;}catch(e){}
    return DEFAULT;
  }
  function saveStation(cap){try{localStorage.setItem(SK,String(cap));}catch(e){}}

  function defaultExp(){
    return {wr:33, avgWin:400, avgLoss:150, tradesPerDay:1, premium:0.30, loss:300};
  }
  function loadExp(){
    var d=defaultExp();
    try{
      var o=JSON.parse(localStorage.getItem(EK)||'null');
      if(o&&typeof o==='object'){
        if(isFinite(o.wr)) d.wr=o.wr;
        if(isFinite(o.avgWin)) d.avgWin=o.avgWin;
        if(isFinite(o.avgLoss)) d.avgLoss=o.avgLoss;
        if(isFinite(o.tradesPerDay)) d.tradesPerDay=o.tradesPerDay;
        if(isFinite(o.premium)) d.premium=o.premium;
        if(isFinite(o.loss)) d.loss=o.loss;
      }
    }catch(e){}
    return d;
  }
  function saveExp(exp){try{localStorage.setItem(EK,JSON.stringify(exp));}catch(e){}}

  var state={station:loadStation(), exp:loadExp()};

  function buildShell(){
    root.innerHTML=
      '<div class="sw-wrap"><div class="sw-metro" id="sw-metro" role="list" aria-label="Trading subway line"></div></div>'+
      '<div class="grid" style="margin-top:14px">'+
        '<div><label for="sw-station">Current station</label><select id="sw-station"></select></div>'+
        '<div><label for="sw-loss">Today\'s loss ($)</label><input type="number" id="sw-loss" min="0" step="1" inputmode="decimal"></div>'+
      '</div>'+
      '<div class="stats" id="sw-stats" style="margin-top:12px"></div>'+
      '<h3 style="margin-top:18px;color:var(--text)">🎯 Size &amp; take-profit at this station <span class="sw-zh">· avg premium $0.30</span></h3>'+
      '<div class="stats" id="sw-tp" style="margin-top:8px"></div>'+
      '<div class="sw-loss" id="sw-loss-out" hidden></div>'+

      '<h3 style="margin-top:22px;color:var(--text)">⏱️ Time invested to $1M <span class="sw-zh">· 唔係利潤</span></h3>'+
      '<p class="sub" style="margin:0 0 10px">Trading days of work from this station to the terminus. Uses your win rate &amp; average $ win/loss (scaled with position size). Not a profit forecast.</p>'+
      '<div class="grid">'+
        '<div><label for="sw-wr">Win rate %</label><input type="number" id="sw-wr" min="0" max="100" step="0.1"></div>'+
        '<div><label for="sw-avg-win">Avg win $ <span class="muted">(at 4 cts)</span></label><input type="number" id="sw-avg-win" min="0" step="1"></div>'+
        '<div><label for="sw-avg-loss">Avg loss $ <span class="muted">(at 4 cts)</span></label><input type="number" id="sw-avg-loss" min="0" step="1"></div>'+
        '<div><label for="sw-tpd">Trades / day</label><input type="number" id="sw-tpd" min="0.1" step="0.1"></div>'+
        '<div><label for="sw-prem">Premium $/share <span class="muted">(debit = ×100)</span></label><input type="number" id="sw-prem" min="0.01" step="0.01"></div>'+
      '</div>'+
      '<div class="stats" id="sw-eta-stats" style="margin-top:12px"></div>'+
      '<div id="sw-eta-msg"></div>'+
      '<div class="sw-hop" id="sw-hop" hidden><table><thead><tr><th>Hop</th><th>Contracts</th><th>Daily return</th><th>Trading days</th></tr></thead><tbody id="sw-hop-body"></tbody></table></div>'+

      '<div class="note" style="margin-top:14px">📝 <b>Exit structure:</b> 50% at +100%, 25% at +300%, 25% kite — matches the playbook. Position sizes on the map follow the doubling scale (4 contracts per $1,000, no ceiling). Avg win/loss scale with contracts from the 4-contract baseline.</div>';
  }

  function buildMap(){
    var metro=document.getElementById('sw-metro');
    metro.innerHTML='';
    var track=document.createElement('div');
    track.className='sw-track'; track.setAttribute('aria-hidden','true');
    metro.appendChild(track);
    var row=document.createElement('div');
    row.className='sw-stations';
    metro.appendChild(row);

    var sel=document.getElementById('sw-station');
    sel.innerHTML='';

    STATIONS.forEach(function(cap,i){
      var btn=document.createElement('button');
      btn.type='button'; btn.className='sw-st'; btn.setAttribute('role','listitem');
      btn.dataset.capital=String(cap);
      if(i===0) btn.classList.add('start');
      if(i===STATIONS.length-1) btn.classList.add('end');

      var lab=document.createElement('div'); lab.className='sw-lab'; lab.textContent=shortLab(cap);
      var dot=document.createElement('div'); dot.className='sw-dot'; dot.setAttribute('aria-hidden','true');
      var size=document.createElement('div'); size.className='sw-size';
      var c=ct(cap);
      size.innerHTML=c+' ct'+(c===1?'':'s');

      btn.appendChild(lab); btn.appendChild(dot); btn.appendChild(size);
      if(i===0){var b=document.createElement('div'); b.className='sw-badge start'; b.textContent='START'; btn.appendChild(b);}
      if(i===STATIONS.length-1){var b2=document.createElement('div'); b2.className='sw-badge end'; b2.textContent='TERMINUS'; btn.appendChild(b2);}
      btn.addEventListener('click',function(){setStation(cap);});
      row.appendChild(btn);

      var opt=document.createElement('option');
      opt.value=String(cap);
      opt.textContent=fmt(cap)+(i===0?' · Start':i===STATIONS.length-1?' · Terminus':'')+' · '+c+' contracts';
      sel.appendChild(opt);
    });
  }

  function setStation(cap){
    state.station=cap;
    saveStation(cap);
    document.getElementById('sw-station').value=String(cap);
    render();
  }

  function readExpFromInputs(){
    var e=state.exp;
    e.wr=Number(document.getElementById('sw-wr').value);
    e.avgWin=Number(document.getElementById('sw-avg-win').value);
    e.avgLoss=Number(document.getElementById('sw-avg-loss').value);
    e.tradesPerDay=Number(document.getElementById('sw-tpd').value);
    e.premium=Number(document.getElementById('sw-prem').value);
    e.loss=Number(document.getElementById('sw-loss').value);
    if(!isFinite(e.wr)) e.wr=0;
    if(!isFinite(e.avgWin)) e.avgWin=0;
    if(!isFinite(e.avgLoss)) e.avgLoss=0;
    if(!isFinite(e.tradesPerDay)||e.tradesPerDay<=0) e.tradesPerDay=1;
    if(!isFinite(e.premium)||e.premium<=0) e.premium=0.30;
    if(!isFinite(e.loss)||e.loss<0) e.loss=0;
    saveExp(e);
  }

  function fillInputs(){
    var e=state.exp;
    document.getElementById('sw-station').value=String(state.station);
    document.getElementById('sw-loss').value=e.loss;
    document.getElementById('sw-wr').value=e.wr;
    document.getElementById('sw-avg-win').value=e.avgWin;
    document.getElementById('sw-avg-loss').value=e.avgLoss;
    document.getElementById('sw-tpd').value=e.tradesPerDay;
    document.getElementById('sw-prem').value=e.premium;
  }

  function baseExpectancy(){
    var e=state.exp;
    var wr=Math.max(0,Math.min(100,e.wr))/100;
    var avgL=Math.abs(e.avgLoss);
    return wr*e.avgWin - (1-wr)*avgL;
  }

  function expectancyAt(contracts){
    return baseExpectancy()*(contracts/BASE_CT);
  }

  function computeHops(fromIdx){
    var e=state.exp;
    var hops=[], totalDays=0;
    var baseExp=baseExpectancy();
    if(baseExp<=0) return {ok:false, baseExp:baseExp, hops:[], totalDays:0};

    for(var i=fromIdx;i<STATIONS.length-1;i++){
      var cap=STATIONS[i];
      var next=STATIONS[i+1];
      var contracts=ct(cap);
      var exp$=expectancyAt(contracts);
      var daily$=e.tradesPerDay*exp$;
      var dailyRet=daily$/cap;
      var days;
      if(dailyRet<=0){
        return {ok:false, baseExp:baseExp, hops:hops, totalDays:totalDays, stuckAt:cap};
      }
      // Exact compound days to double (or reach next if not exact 2x — last hop 512k→1M is ~1.953x)
      var multiple=next/cap;
      days=Math.log(multiple)/Math.log(1+dailyRet);
      hops.push({from:cap,to:next,contracts:contracts,dailyRet:dailyRet,daily$:daily$,days:days,risked:contracts*e.premium*100});
      totalDays+=days;
    }
    return {ok:true, baseExp:baseExp, hops:hops, totalDays:totalDays};
  }

  function renderLoss(){
    var out=document.getElementById('sw-loss-out');
    var loss=state.exp.loss;
    if(!isFinite(loss)||loss<=0){out.hidden=true; out.innerHTML=''; return;}
    var cap=state.station;
    var ofStation=pct(loss,cap);
    var ofGoal=pct(loss,GOAL);
    var contrasts=[2000,10000,100000,1000000];
    var rows=contrasts.map(function(c){
      return '<div class="sw-crow"><em>'+fmt(loss)+'</em> at '+fmt(c)+' = <em>'+pct(loss,c)+'%</em> of station, <em>'+pct(loss,GOAL)+'%</em> of goal</div>';
    }).join('');
    out.hidden=false;
    out.innerHTML=
      '<div class="sw-loss-main"><strong>'+fmt(loss)+'</strong> at '+fmt(cap)+' = <strong>'+ofStation+'%</strong> of this station · <strong>'+ofGoal+'%</strong> of $1,000,000'+
      '<div class="sub" style="margin:6px 0 0">Any loss is part of the journey — keep it in perspective vs the terminus.</div></div>'+
      '<div class="sw-contrast">'+rows+'</div>';
  }

  function renderEta(){
    var idx=STATIONS.indexOf(state.station);
    var msg=document.getElementById('sw-eta-msg');
    var hopEl=document.getElementById('sw-hop');
    var hopBody=document.getElementById('sw-hop-body');
    var stats=document.getElementById('sw-eta-stats');
    var e=state.exp;
    var baseExp=baseExpectancy();
    var contracts=ct(state.station);
    var risked=contracts*e.premium*100;

    stats.innerHTML=
      '<div class="stat"><div class="k">Expectancy / trade (4 cts)</div><div class="v '+(baseExp>0?'pos':baseExp<0?'neg':'')+'">'+fmtN(baseExp,2)+'</div></div>'+
      '<div class="stat"><div class="k">At this station ('+contracts+' cts)</div><div class="v">'+(baseExp>0?'+':'')+fmtN(expectancyAt(contracts),2)+'</div></div>'+
      '<div class="stat"><div class="k">Risked notional</div><div class="v">'+fmt(risked)+'</div><div class="k" style="margin-top:4px;text-transform:none">'+contracts+' × $'+(e.premium*100).toFixed(0)+' debit</div></div>';

    if(idx>=STATIONS.length-1){
      msg.innerHTML='<div class="note" style="margin-top:10px">🏁 You are at the terminus. Time invested: 0 trading days.</div>';
      hopEl.hidden=true; hopBody.innerHTML=''; return;
    }

    var res=computeHops(idx);
    if(!res.ok){
      msg.innerHTML='<div class="sw-eta-warn">⛔ The line does not advance — expectancy is '+(res.baseExp<=0?'≤ 0':('stuck near '+fmt(res.stuckAt)))+
        '. Raise win rate, improve avg win/loss, or cut size until expectancy is positive. No ETA invented.</div>';
      hopEl.hidden=true; hopBody.innerHTML='';
      stats.innerHTML+=
        '<div class="stat"><div class="k">Trading days to $1M</div><div class="v neg">—</div></div>'+
        '<div class="stat"><div class="k">Calendar (≈21 d/mo)</div><div class="v muted">—</div></div>'+
        '<div class="stat"><div class="k">Years (≈252 d/yr)</div><div class="v muted">—</div></div>';
      return;
    }

    var days=res.totalDays;
    var months=days/TRADING_DAYS_PER_MONTH;
    var years=days/TRADING_DAYS_PER_YEAR;
    stats.innerHTML+=
      '<div class="stat"><div class="k">Trading days of work</div><div class="v" style="color:var(--amber)">'+fmtN(days,1)+'</div></div>'+
      '<div class="stat"><div class="k">≈ Months (21 trading d)</div><div class="v">'+fmtN(months,1)+'</div></div>'+
      '<div class="stat"><div class="k">≈ Years (252 trading d)</div><div class="v">'+fmtN(years,2)+'</div></div>';

    msg.innerHTML='<p class="sub" style="margin:10px 0 0">Positive expectancy + scaling size: later hops can take similar or fewer <em>days</em> in % terms while dollar progress speeds up. Figures are time invested, not guaranteed profit.</p>';

    hopBody.innerHTML=res.hops.map(function(h){
      return '<tr><td>'+shortLab(h.from)+' → '+shortLab(h.to)+'</td><td>'+h.contracts+'</td><td class="pos">'+(h.dailyRet*100).toFixed(3)+'%/day</td><td>'+fmtN(h.days,1)+'</td></tr>';
    }).join('');
    hopEl.hidden=false;
  }

  function render(){
    var cap=state.station;
    var idx=STATIONS.indexOf(cap);
    if(idx<0){cap=DEFAULT; state.station=cap; idx=STATIONS.indexOf(cap);}
    var next=idx<STATIONS.length-1?STATIONS[idx+1]:null;
    var remaining=STATIONS.length-1-idx;
    var maxCt=ct(cap);

    document.querySelectorAll('.sw-st').forEach(function(el){
      var c=Number(el.dataset.capital);
      el.classList.toggle('active',c===cap);
      el.classList.toggle('passed',c<cap);
    });

    var toNext$='—', toNextPct='—';
    if(next){toNext$=fmt(next-cap); toNextPct=pct(next-cap,cap)+'%';}
    else {toNext$='Arrived'; toNextPct='0%';}

    document.getElementById('sw-stats').innerHTML=
      '<div class="stat"><div class="k">To next station</div><div class="v">'+toNext$+(next?' <span style="font-size:.85rem;font-weight:600;color:var(--muted)">('+toNextPct+')</span>':'')+'</div></div>'+
      '<div class="stat"><div class="k">Stations to $1M</div><div class="v">'+remaining+'</div></div>'+
      '<div class="stat"><div class="k">Max contracts here</div><div class="v">'+maxCt+'</div></div>';

    var unit=AVG_PREM*100;
    document.getElementById('sw-tp').innerHTML=
      '<div class="stat"><div class="k">Suggested size</div><div class="v">'+maxCt+' cts</div><div class="k" style="margin-top:4px;text-transform:none">'+maxCt+' × $'+AVG_PREM.toFixed(2)+' premium</div></div>'+
      '<div class="stat"><div class="k">Max loss</div><div class="v neg">-'+fmt(maxCt*unit)+'</div><div class="k" style="margin-top:4px;text-transform:none">'+maxCt+' × $'+unit.toFixed(0)+'</div></div>'+
      '<div class="stat"><div class="k">TP +100%</div><div class="v pos">+'+fmt(maxCt*unit)+'</div><div class="k" style="margin-top:4px;text-transform:none">'+maxCt+' × $'+unit.toFixed(0)+'</div></div>'+
      '<div class="stat"><div class="k">TP +300%</div><div class="v pos">+'+fmt(maxCt*unit*3)+'</div><div class="k" style="margin-top:4px;text-transform:none">'+maxCt+' × $'+(unit*3).toFixed(0)+'</div></div>'+
      '<div class="stat"><div class="k">TP +1000%</div><div class="v pos">+'+fmt(maxCt*unit*10)+'</div><div class="k" style="margin-top:4px;text-transform:none">'+maxCt+' × $'+(unit*10).toFixed(0)+'</div></div>';

    renderLoss();
    renderEta();
  }

  function onChange(){
    readExpFromInputs();
    var sel=Number(document.getElementById('sw-station').value);
    if(STATIONS.indexOf(sel)>=0 && sel!==state.station){
      state.station=sel; saveStation(sel);
    }
    render();
  }

  buildShell();
  buildMap();
  fillInputs();
  document.getElementById('sw-station').addEventListener('change',onChange);
  ['sw-loss','sw-wr','sw-avg-win','sw-avg-loss','sw-tpd','sw-prem'].forEach(function(id){
    document.getElementById(id).addEventListener('input',onChange);
  });
  render();
})();
