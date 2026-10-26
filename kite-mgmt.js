/* Kite Management — protective trail log, stored only in this browser's localStorage. */
(function(){
  var roots=[].slice.call(document.querySelectorAll('#kite-body'));
  if(!roots.length) return;
  var KEY='apex-kite-trail-log';
  var ACTIONS=['initial floor','trail up','hard-stop close'];
  function etNow(){return new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date());}
  function etDay(){return new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York'}).format(new Date());}
  function rows(){try{return JSON.parse(localStorage.getItem(KEY))||[];}catch(e){return [];}}
  function put(r){localStorage.setItem(KEY,JSON.stringify(r));}
  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function floorSuggest(mark){var m=parseFloat(mark);if(!isFinite(m)||m<=0)return '';return (Math.round(m*0.5*100)/100).toFixed(2);}
  function flags(r){var f=[];
    if(r.qty>1) f.push(['runner >1','bad']);
    else if(r.qty===1) f.push(['1 runner','ok']);
    if(r.mark>0&&r.floor>0){
      var ratio=r.floor/r.mark;
      if(ratio>=0.4&&ratio<=0.6) f.push(['~50% floor','ok']);
      else f.push(['floor off 50%','bad']);
    }
    if(r.action==='hard-stop close'){
      if(r.time&&r.time<='15:30') f.push(['by 3:30','ok']);
      else f.push(['after 3:30','bad']);
    } else if(r.time&&r.time>'15:30') f.push(['still open after 3:30','bad']);
    return f;}
  function money(v){return (v==null||v==='')?'—':('$'+Number(v).toFixed(2));}
  function bindFloor(root){
    var mark=root.querySelector('[data-f="mark"]'), fl=root.querySelector('[data-f="floor"]');
    if(!mark||!fl||mark._kiteBound) return;
    mark._kiteBound=1;
    mark.addEventListener('input',function(){if(fl.dataset.touched==='1')return;fl.value=floorSuggest(mark.value);});
    fl.addEventListener('input',function(){fl.dataset.touched='1';});
  }
  function renderOne(root){
    var list=rows(), h='';
    h+='<div class="ls-grid">';
    h+='<div><label>Date</label><input data-f="date" type="date" value="'+etDay()+'"></div>';
    h+='<div><label>Time (ET)</label><input data-f="time" type="time" value="'+etNow()+'"></div>';
    h+='<div><label>Position label</label><input data-f="label" type="text" placeholder="e.g. QQQ 715C"></div>';
    h+='<div><label>Action</label><select data-f="action">'+ACTIONS.map(function(a){return '<option>'+a+'</option>';}).join('')+'</select></div>';
    h+='<div><label>Kite mark $</label><input data-f="mark" type="number" step="0.01" min="0" placeholder="current premium"></div>';
    h+='<div><label>New floor $ (~50%)</label><input data-f="floor" type="number" step="0.01" min="0" placeholder="auto from mark"></div>';
    h+='<div><label>Contracts left</label><input data-f="qty" type="number" step="1" min="0" max="1" value="1" title="Keep runner to 1"></div>';
    h+='<div><label>Note</label><input data-f="note" type="text" placeholder="cancel old · place new limit"></div>';
    h+='</div>';
    h+='<div class="btns"><button class="primary" data-a="add">+ Log trail</button><button data-a="csv">Export CSV</button><span class="km-msg warn"></span></div>';
    h+='<div class="tbl" style="margin-top:12px"><table><thead><tr><th>Date</th><th>Time</th><th style="text-align:left">Label</th><th style="text-align:left">Action</th><th>Mark</th><th>Floor</th><th>Qty</th><th style="text-align:left">Flags</th><th style="text-align:left">Note</th><th></th></tr></thead><tbody>';
    if(!list.length) h+='<tr><td colspan="10" class="muted" style="text-align:center">No kite trails logged yet.</td></tr>';
    list.forEach(function(r,i){
      h+='<tr><td>'+esc(r.date)+'</td><td>'+esc(r.time)+'</td><td style="text-align:left">'+esc(r.label)+'</td><td style="text-align:left">'+esc(r.action)+'</td><td>'+money(r.mark)+'</td><td>'+money(r.floor)+'</td><td>'+r.qty+'</td><td style="text-align:left">'
        +flags(r).map(function(f){return '<span class="ls-b ls-'+f[1]+'">'+f[0]+'</span>';}).join('')
        +'</td><td style="text-align:left;white-space:normal">'+esc(r.note)+'</td><td><button class="x" data-a="del" data-i="'+i+'" title="Delete row">✕</button></td></tr>';
    });
    h+='</tbody></table></div>';
    var n=list.length, stops=list.filter(function(r){return r.action==='hard-stop close';}).length, trails=list.filter(function(r){return r.action==='trail up';}).length, init=list.filter(function(r){return r.action==='initial floor';}).length;
    var days={};list.forEach(function(r){days[r.date]=1;});
    h+='<div class="stats">'
      +[['Trails logged',n],['Initial floors',init],['Trail-ups',trails],['Hard-stop closes',stops],['Days',Object.keys(days).length]]
       .map(function(x){return '<div class="stat"><div class="k">'+x[0]+'</div><div class="v">'+x[1]+'</div></div>';}).join('')
      +'</div>';
    root.innerHTML=h;
    bindFloor(root);
  }
  function render(){roots.forEach(renderOne);}
  function onClick(e){
    var b=e.target.closest('button'); if(!b) return;
    var root=b.closest('#kite-body'); if(!root) return;
    var a=b.dataset.a, list=rows();
    if(a==='add'){
      var r={}; root.querySelectorAll('[data-f]').forEach(function(el){r[el.dataset.f]=el.value.trim();});
      r.mark=parseFloat(r.mark); r.floor=parseFloat(r.floor); r.qty=parseInt(r.qty,10);
      if(ACTIONS.indexOf(r.action)<0) r.action='initial floor';
      if(!r.date||!r.time||!r.label||!isFinite(r.mark)||r.mark<=0||!isFinite(r.floor)||r.floor<0||!isFinite(r.qty)||r.qty<0){
        var msg=root.querySelector('.km-msg'); if(msg) msg.textContent=' Fill date, time, label, mark, floor, and contracts.';
        return;
      }
      if(r.qty>1){ var m2=root.querySelector('.km-msg'); if(m2) m2.textContent=' Runner capped at 1 contract — set qty to 1 (or 0 if flat).'; return; }
      list.push(r); list.sort(function(x,y){return (x.date+x.time).localeCompare(y.date+y.time);}); put(list); render();
    } else if(a==='del'){
      if(confirm('Delete this trail row?')){ list.splice(+b.dataset.i,1); put(list); render(); }
    } else if(a==='csv'){
      var hd=['date','time_et','label','action','kite_mark','new_floor','contracts','note'];
      var q=function(v){v=String(v==null?'':v);return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;};
      var csv=[hd.join(',')].concat(list.map(function(r){return [r.date,r.time,r.label,r.action,r.mark,r.floor,r.qty,r.note].map(q).join(',');})).join('\n');
      var u=URL.createObjectURL(new Blob([csv],{type:'text/csv'})),l=document.createElement('a');l.href=u;l.download='kite-trail-log.csv';l.click();setTimeout(function(){URL.revokeObjectURL(u);},1000);
    }
  }
  roots.forEach(function(root){root.addEventListener('click',onClick);});
  render();
})();
