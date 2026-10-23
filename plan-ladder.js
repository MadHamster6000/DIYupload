/* Plan Ladder — private, stored only in this browser's localStorage, keyed by ET date. */
(function(){
  var root=document.getElementById('pl-body'); if(!root) return;
  var IDS=['A','B','C'], PH={A:'702–706 zone',B:'707 swipe',C:'e.g. 700 break & hold'};
  function etDay(){return new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York'}).format(new Date());}
  var day, st;
  function key(){return 'apex-plan-ladder-'+day;}
  function blank(){return {plans:IDS.map(function(id){return {id:id,label:'',trigger:'',max:1,status:'open'};})};}
  function load(){day=etDay();try{st=JSON.parse(localStorage.getItem(key()))||blank();}catch(e){st=blank();}render();}
  function save(){localStorage.setItem(key(),JSON.stringify(st));}
  function failed(){return st.plans.filter(function(p){return p.status==='lost';})[0];}
  function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function render(){
    var f=failed(), h='<p class="sub" style="margin:0 0 10px">'+day+' (ET) · <b>Each plan once. A plan that loses = done for the day.</b></p>';
    if(f) h+='<div class="pl-banner">🔒 Plan '+f.id+' failed — no new plans today.</div>';
    st.plans.forEach(function(p,i){
      var used=p.status!=='open', locked=!used&&!!f, dis=(used||locked)?' disabled':'';
      h+='<div class="pl-row'+(used?' pl-used':'')+(locked?' pl-locked':'')+'" data-i="'+i+'">'
       +'<div class="pl-id">'+(locked?'🔒':p.id)+'</div>'
       +'<div class="pl-f"><label>Plan '+p.id+' label</label><input data-k="label" value="'+esc(p.label)+'" placeholder="Plan '+p.id+'"'+dis+'></div>'
       +'<div class="pl-f pl-w"><label>Entry zone / trigger</label><input data-k="trigger" value="'+esc(p.trigger)+'" placeholder="'+PH[p.id]+'"'+dis+'></div>'
       +'<div class="pl-f pl-n"><label>Max contracts</label><input type="number" min="1" step="1" data-k="max" value="'+p.max+'"'+dis+'></div>'
       +'<div class="pl-act">';
      if(locked) h+='<span class="muted">Locked</span>';
      else if(p.status==='open') h+='<button data-a="enter">Entered</button>';
      else if(p.status==='entered') h+='<button data-a="won" class="pos">Won</button><button data-a="lost" class="neg">Lost</button>';
      else h+='<span class="'+(p.status==='won'?'pos':'neg')+'">Used · '+p.status+'</span>';
      h+='</div></div>';
    });
    h+='<div class="btns"><button class="primary" data-a="save">Save</button><button data-a="reset">Reset today</button><span id="pl-msg" class="muted"></span></div>';
    root.innerHTML=h;
  }
  function grab(){root.querySelectorAll('.pl-row').forEach(function(r){var p=st.plans[+r.dataset.i];if(p.status!=='open'||failed())return;
    r.querySelectorAll('input').forEach(function(inp){var k=inp.dataset.k;p[k]=k==='max'?Math.max(1,parseInt(inp.value,10)||1):inp.value.trim();});});}
  root.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;var a=b.dataset.a,r=b.closest('.pl-row'),p=r?st.plans[+r.dataset.i]:null;
    if(a==='save'){grab();save();render();document.getElementById('pl-msg').textContent=' Saved.';return;}
    if(a==='reset'){if(confirm('Reset today\'s Plan Ladder? This clears all plans for '+day+'.')){localStorage.removeItem(key());st=blank();render();}return;}
    grab();
    if(a==='enter'){if(failed())return;if(!confirm('Mark Plan '+p.id+' as entered? It cannot be re-entered today.'))return;p.status='entered';}
    else if(a==='won') p.status='won';
    else if(a==='lost') p.status='lost';
    save();render();});
  setInterval(function(){if(etDay()!==day)load();},60000);
  load();
})();
