/* Late Scalp Setup — private log, stored only in this browser's localStorage (all days, one key). */
(function(){
  var root=document.getElementById('ls-body'); if(!root) return;
  var KEY='apex-late-scalp-log';
  var TAGS=['Liquidity Grab','John Wick Candle','Hammer','RSI Reversal','Breakout','Other'];
  function etNow(){return new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date());}
  function mins(t){var a=String(t||'').split(':');return a.length<2?NaN:+a[0]*60+ +a[1];}
  function gap(r){var g=mins(r.entry)-mins(r.placed);return isFinite(g)&&g>0?g:0;}
  function etDay(){return new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York'}).format(new Date());}
  function rows(){try{return JSON.parse(localStorage.getItem(KEY))||[];}catch(e){return [];}}
  function put(r){localStorage.setItem(KEY,JSON.stringify(r));}
  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function pnl(r){return Math.round((r.exitPx-r.prem)*r.qty*100*100)/100;}
  function flags(r){var f=[];
    f.push(Math.abs(r.strike-r.under)<=1?['≤1 pt','ok']:['too far','bad']);
    if(r.entry&&r.entry<'15:15') f.push(['early','bad']);
    if(r.prem<0.20||r.prem>0.35) f.push(['premium','bad']);
    if(r.prem<0.30) f.push(['possible passive bid','bad']);
    if(gap(r)>1) f.push(['waited bid ('+gap(r)+'m)','bad']);
    if(r.qty<2||r.qty>4) f.push(['size','bad']);
    if(r.exit&&r.exit>'16:00') f.push(['exit late','bad']);
    return f;}
  function clean(r){return flags(r).every(function(x){return x[1]==='ok';});}
  function stats(list){var n=list.length,w=0,net=0,d={};list.forEach(function(r){var p=pnl(r);net+=p;if(p>0)w++;d[r.date]=1;});
    var W=list.map(pnl).filter(function(p){return p>0;}),Lo=list.map(pnl).filter(function(p){return p<0;});
    var aw=W.length?W.reduce(function(a,b){return a+b;},0)/W.length:0, al=Lo.length?-Lo.reduce(function(a,b){return a+b;},0)/Lo.length:0;
    return {n:n,wr:n?Math.round(w/n*100):0,net:net,avg:n?net/n:0,exp:n?(W.length/n)*aw-(Lo.length/n)*al:0,days:Object.keys(d).length,pb:list.filter(function(r){return r.prem<0.30;}).length};}
  function money(v){return '<span class="'+(v>0?'pos':v<0?'neg':'')+'">'+(v<0?'−':'')+'$'+Math.abs(v).toFixed(2)+'</span>';}
  function statBlock(t,s){return '<h3>'+t+'</h3><div class="stats">'
    +[['Trades',s.n],['Win rate',s.wr+'%'],['Net P&L',money(s.net)],['Avg / trade',money(s.avg)],['Expectancy',money(s.exp)],['Possible passive bids',s.pb],['Days logged',s.days]]
     .map(function(x){return '<div class="stat"><div class="k">'+x[0]+'</div><div class="v">'+x[1]+'</div></div>';}).join('')+'</div>';}
  var F=[['date','Date','date'],['placed','Order placed (ET)','time'],['entry','Entry time (ET)','time'],['under','QQQ at entry','number'],['strike','Strike','number'],
    ['side','Put/Call','select'],['qty','Contracts','number'],['prem','Premium paid','number'],['exit','Exit time (ET)','time'],['exitPx','Exit price','number'],['stag','Setup tag','tag'],['note','Note','text']];
  function render(){
    var list=rows(), h='<div class="ls-grid">';
    F.forEach(function(f){h+='<div><label>'+f[1]+'</label>'+(f[2]==='tag'?'<select data-f="stag"><option value="">— untagged —</option>'+TAGS.map(function(t){return '<option>'+t+'</option>';}).join('')+'</select>':f[2]==='select'
      ?'<select data-f="side"><option>Put</option><option>Call</option></select>'
      :'<input data-f="'+f[0]+'" type="'+f[2]+'"'+(f[2]==='number'?' step="0.01" min="0"':'')+(f[0]==='date'?' value="'+etDay()+'"':'')+(f[0]==='placed'?' value="'+etNow()+'" title="Defaults to now; edit only if the bid sat unfilled"':'')+(f[0]==='qty'?' value="2" step="1"':'')+'>')+'</div>';});
    h+='</div><div class="btns"><button class="primary" data-a="add">+ Log trade</button><button data-a="csv">Export CSV</button><span id="ls-msg" class="warn"></span></div>';
    h+='<div class="tbl" style="margin-top:12px"><table id="ls-table"><thead><tr><th>Date</th><th>Placed</th><th>Entry</th><th>Gap</th><th>QQQ</th><th>Strike</th><th>P/C</th><th>Qty</th><th>Prem</th><th>Exit</th><th>Exit px</th><th>P&L</th><th style="text-align:left">Flags</th><th style="text-align:left">Tag</th><th style="text-align:left">Note</th><th></th></tr></thead><tbody>';
    if(!list.length) h+='<tr><td colspan="16" class="muted" style="text-align:center">No late scalps logged yet.</td></tr>';
    list.forEach(function(r,i){h+='<tr><td>'+esc(r.date)+'</td><td>'+esc(r.placed||'')+'</td><td>'+esc(r.entry)+'</td><td>'+gap(r)+'m</td><td>'+r.under.toFixed(2)+'</td><td>'+r.strike+'</td><td>'+esc(r.side)+'</td><td>'+r.qty+'</td><td>'+r.prem.toFixed(2)+'</td><td>'+esc(r.exit)+'</td><td>'+r.exitPx.toFixed(2)+'</td><td>'+money(pnl(r))+'</td><td style="text-align:left">'
      +flags(r).map(function(f){return '<span class="ls-b ls-'+f[1]+'">'+f[0]+'</span>';}).join('')+'</td><td style="text-align:left"><select data-t="'+i+'"><option value="">—</option>'+TAGS.map(function(t){return '<option'+(r.stag===t?' selected':'')+'>'+t+'</option>';}).join('')+'</select></td><td style="text-align:left;white-space:normal">'+esc(r.note)+'</td><td><button class="x" data-a="del" data-i="'+i+'" title="Delete row">✕</button></td></tr>';});
    h+='</tbody></table></div>'+statBlock('All late scalps',stats(list))+statBlock('Rule-compliant only (no flags)',stats(list.filter(clean)));
    var tg=TAGS.filter(function(t){return list.some(function(r){return r.stag===t;});}).map(function(t){return [t,list.filter(function(r){return r.stag===t;})];});
    var un=list.filter(function(r){return !r.stag;}); if(un.length&&tg.length) tg.push(['Untagged',un]);
    tg.forEach(function(x){h+=statBlock('🏷️ '+esc(x[0]),stats(x[1]));});
    root.innerHTML=h;
  }
  root.addEventListener('change',function(e){var t=e.target;if(t.dataset&&t.dataset.t!==undefined){var list=rows();list[+t.dataset.t].stag=t.value;put(list);render();}});
  root.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;var a=b.dataset.a,list=rows();
    if(a==='add'){var r={};root.querySelectorAll('[data-f]').forEach(function(el){r[el.dataset.f]=el.value.trim();});
      ['under','strike','prem','exitPx'].forEach(function(k){r[k]=parseFloat(r[k]);});r.qty=parseInt(r.qty,10);
      if(TAGS.indexOf(r.stag)<0) r.stag='';
      if(!r.date||!r.entry||!r.exit||[r.under,r.strike,r.prem,r.exitPx,r.qty].some(isNaN)){document.getElementById('ls-msg').textContent=' Fill in every field except note.';return;}
      list.push(r);list.sort(function(x,y){return (x.date+x.entry).localeCompare(y.date+y.entry);});put(list);render();}
    else if(a==='del'){if(confirm('Delete this row?')){list.splice(+b.dataset.i,1);put(list);render();}}
    else if(a==='csv'){var hd=['date','placed','entry','gap_min','qqq','strike','side','contracts','premium','exit','exit_price','pnl','flags','setup_tag','note'];
      var q=function(v){v=String(v==null?'':v);return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;};
      var csv=[hd.join(',')].concat(list.map(function(r){return [r.date,r.placed||'',r.entry,gap(r),r.under,r.strike,r.side,r.qty,r.prem,r.exit,r.exitPx,pnl(r),flags(r).map(function(f){return f[0];}).join(' '),r.stag||'',r.note].map(q).join(',');})).join('\n');
      var u=URL.createObjectURL(new Blob([csv],{type:'text/csv'})),l=document.createElement('a');l.href=u;l.download='late-scalp-log.csv';l.click();setTimeout(function(){URL.revokeObjectURL(u);},1000);}
  });
  render();
})();
