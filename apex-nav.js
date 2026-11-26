/* Sticky pill nav + bottom tabs: highlight the active section. */
(function(){
  const path=(location.pathname.split('/').pop()||'index.html');
  const isIndex=path===''||path==='index.html';
  const isJournal=path.indexOf('journal')!==-1;
  const isRef=path.indexOf('reference')!==-1;
  const current=document.getElementById('nav-current');
  const pills=[...document.querySelectorAll('#nav a')];

  function setTab(name){
    document.querySelectorAll('.tabbar a').forEach(a=>{
      a.classList.toggle('active', a.dataset.tab===name);
    });
  }
  function labelOf(id){
    const map={
      'morning-brief':'Brief','am-checklist':'清單','playbook':'Playbook',
      'plan-ladder':'Ladder','subway':'Subway','late-scalp':'Late Scalp',
      'kite-mgmt':'Kite','moonshot':'Moonshot','reference':'Cash Table',
      'conviction-sizer':'Conviction','sizing-tool':'Sizing','odte-tips':'Tips',
      'pattern-recap':'Patterns','tradeList':'Trades'
    };
    return map[id]||'';
  }
  function activatePill(id){
    pills.forEach(a=>{
      const href=a.getAttribute('href')||'';
      const hash=href.startsWith('#')?href.slice(1):'';
      a.classList.toggle('active', hash===id || (id==='morning-brief'&&href.indexOf('morning-brief')!==-1));
    });
    const lab=labelOf(id);
    if(current){
      if(lab){ current.hidden=false; current.textContent=lab; }
      else { current.hidden=true; current.textContent=''; }
    }
    const on=document.querySelector('#nav a.active');
    if(on){
      const nav=on.closest('#nav')||on.parentElement;
      const nr=nav.getBoundingClientRect(), r=on.getBoundingClientRect();
      if(r.left<nr.left+12 || r.right>nr.right-12){
        try{ on.scrollIntoView({inline:'nearest',block:'nearest',behavior:'auto'}); }catch(e){}
      }
    }
  }

  if(isJournal) setTab('journal');
  else if(isRef) setTab('reference');
  else setTab(location.hash==='#playbook'?'playbook':'brief');

  if(isIndex||isRef){
    const secs=[...document.querySelectorAll('main section.card[id], main details[id]')];
    if(secs.length&&'IntersectionObserver' in window){
      const obs=new IntersectionObserver(es=>{
        const vis=es.filter(e=>e.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];
        if(!vis||!vis.target.id) return;
        activatePill(vis.target.id);
        if(isIndex){
          const id=vis.target.id;
          setTab(id==='playbook'||id==='plan-ladder'?'playbook':'brief');
        }
      },{rootMargin:'-25% 0px -55% 0px',threshold:[0.15,0.4]});
      secs.forEach(s=>obs.observe(s));
    }
    if(location.hash) activatePill(location.hash.slice(1));
    else if(isIndex) activatePill('morning-brief');
    else if(isRef) activatePill('moonshot');
  }else if(isJournal){
    if(current){ current.hidden=false; current.textContent='Journal'; }
  }

  window.addEventListener('hashchange',()=>{
    const id=location.hash.slice(1);
    if(id) activatePill(id);
    if(isIndex) setTab(id==='playbook'?'playbook':'brief');
  });
})();
