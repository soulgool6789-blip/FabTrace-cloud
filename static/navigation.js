/* App-only contextual navigation. Draft snapshots stay in this signed-in page's memory. */
(() => {
  'use strict';
  const node=id=>document.getElementById(id);
  const pages={
    orderSetupPage:['FabOrderSetup','Orders','order-setup'],ordersPage:['FabOrders','Production records','orders'],
    orderLabelsPage:['FabOrderLabels','Spool QR labels','order-labels'],productionProgressPage:['FabProductionProgress','Production progress','production-progress'],
    handoffPage:['FabHandoff','Scan & transfer','handoff'],flowPage:['FabFlow','Process flow','flow'],
    guidePage:['FabGuide','Guide & setup','guide'],trackingPage:['FabTracking','Projects & welds','tracking'],
    partsPage:['FabParts','Spool parts','parts'],qualityPage:['FabQuality','Audit readiness','quality'],
    dossierPage:['FabDossier','Job Packets','dossier'],progressPage:['FabProgress','Project detail','progress'],
    adminPage:['FabAdmin','Admin controls','admin'],removalsPage:['FabRemovals','Removed records','removed-records'],
    itemsPage:[null,'Items','items'],itemPage:[null,'Item record','item'],bulkPage:[null,'Bulk import & QR labels','bulk'],
    staffPage:[null,'Employees','employees'],auditPage:[null,'Activity log','activity']
  };
  const primary=new Set(['orderSetupPage','ordersPage','orderLabelsPage','productionProgressPage','progressPage','handoffPage','flowPage','guidePage']);
  const originalReplace=history.replaceState.bind(history),stack=[],lastByPage=new Map();
  let active=null,prepared=null,restoring=0,busy=false,observing=false;
  const home=()=>({page:'orderSetupPage',url:'/?order-setup=1',label:'Orders'});

  function safeUrl(value){
    try{const u=new URL(value,location.origin);if(u.origin!==location.origin||!['/','/index.html'].includes(u.pathname))return null;u.hash='';u.searchParams.sort();return '/'+u.search;}catch(_){return null;}
  }
  function pageFor(url){
    const q=new URL(safeUrl(url)||'/',location.origin).searchParams;
    // Route selectors precede item/spool IDs, which are also used inside several workspaces.
    for(const [page,entry] of Object.entries(pages)){if(page!=='itemPage'&&q.has(entry[2]))return page;}
    if(q.has('badge'))return 'handoffPage';
    return q.get('item')||q.get('spool')?'itemPage':'itemsPage';
  }
  function defaultUrl(page){return page==='itemPage'&&typeof current!=='undefined'&&current?.id?'/?'+(current.qr_alias?'spool='+encodeURIComponent(current.qr_alias):'item='+encodeURIComponent(current.id)):'/?'+pages[page][2]+'=1';}
  function copyFrame(frame){return frame?{...frame,fields:frame.fields?.map(value=>({...value})),details:frame.details?.map(value=>({...value}))}:null;}
  function labelFor(page){const title=node(page)?.querySelector('h1');return title?.textContent?.trim().replace(/\s+/g,' ').slice(0,90)||pages[page]?.[1]||'Orders';}
  function canLeave(targetPage){
    if(!active)return true;
    const module=window[pages[active.page]?.[0]];
    if(module?.canNavigateAway?.()===false||window.FabSpoolDocuments?.canNavigateAway?.()===false||window.FabSpoolBom?.canNavigateAway?.()===false){
      if(targetPage!==active.page)notify('Please wait for the current save to finish.');
      return false;
    }
    return true;
  }
  function fieldsFor(page){
    return [...(node(page)?.querySelectorAll('input,select,textarea')||[])].filter(el=>el.type!=='password'&&el.type!=='file'&&el.type!=='hidden'&&(el.id||el.name)).slice(0,250).map(el=>({id:el.id,name:el.name,tag:el.tagName,type:el.type,value:el.value,checked:el.checked}));
  }
  function capture(){
    if(!active)return null;
    const module=window[pages[active.page]?.[0]];
    active.label=labelFor(active.page);active.moduleState=module?.navigationState?.()||null;
    active.documents=window.FabSpoolDocuments?.navigationState?.()||null;
    active.materials=window.FabSpoolBom?.navigationState?.()||null;
    active.fields=fieldsFor(active.page);active.scroll=window.scrollY;
    active.details=[...(node(active.page)?.querySelectorAll('details')||[])].map((el,index)=>({id:el.id,index,open:el.open}));
    if(active.page==='itemsPage')active.itemOffset=typeof offset==='number'?offset:0;
    lastByPage.set(active.page,copyFrame(active));
    return copyFrame(active);
  }
  function prepare(){if(!restoring)prepared=capture();}
  function push(frame){
    if(!frame)return;
    const previous=stack[stack.length-1];
    if(!previous||previous.page!==frame.page||previous.url!==frame.url)stack.push(copyFrame(frame));
    else stack[stack.length-1]=copyFrame(frame);
    if(stack.length>40)stack.shift();
  }
  function beforeShow(page){
    if(!pages[page])return true;
    if(!canLeave(page))return false;
    if(active?.page===page){prepare();return true;}
    if(active&&!restoring){prepare();push(prepared);}
    const existing=safeUrl(location.href),url=pageFor(existing)===page&&!(page==='itemsPage'&&existing==='/')?existing:defaultUrl(page);
    // The first item render canonicalizes legacy ?item= links to its saved
    // ?spool= label. This completes the same navigation, not a second visit.
    // Same-page item changes return above and still push their prior frame.
    active={page,url,label:pages[page][1],transition:!!pages[page][0]||page==='itemPage'};prepared=null;
    // Legacy item, employee, activity and bulk screens did not previously write a route.
    originalReplace(null,'',url);return true;
  }
  function afterShow(page){
    if(active?.page!==page)return;
    node('moreTools')?.removeAttribute('open');
    changed();
  }
  history.replaceState=function(data,title,url){
    if(url==null)return originalReplace(data,title,url);
    const next=safeUrl(url);
    // This wrapper observes known app routes. It never navigates to an external target.
    if(!next)return originalReplace(data,title,url);
    if(active&&pageFor(next)===active.page){
      if(!restoring&&!active.transition&&next!==active.url){
        const previous=prepared?.page===active.page&&prepared.url===active.url?prepared:copyFrame(active);
        push(previous);active={page:active.page,url:next,label:pages[active.page][1]};
      }else active.url=next;
      active.transition=false;prepared=null;
    }
    const result=originalReplace(data,title,url);
    changed();return result;
  };

  function fallback(frame=active){
    if(!frame)return home();
    const q=new URL(frame.url,location.origin).searchParams,set=(page,values={})=>({page,url:'/?'+new URLSearchParams({[pages[page][2]]:'1',...Object.fromEntries(Object.entries(values).filter(([,value])=>value))}),label:pages[page][1]});
    if(frame.page==='orderLabelsPage')return set('orderSetupPage',{po:q.get('po')});
    if(frame.page==='ordersPage'){
      if(q.get('assembly'))return set('ordersPage',{po:q.get('po'),gpn:q.get('gpn')});
      if(q.get('gpn'))return set('ordersPage',{po:q.get('po')});
      return set('orderSetupPage',{po:q.get('po')});
    }
    if(frame.page==='trackingPage'){
      if(q.get('weld'))return set('trackingPage',{project:q.get('project'),spool:q.get('spool')});
      if(q.get('spool'))return set('trackingPage',{project:q.get('project'),view:'spools'});
      if(q.get('view')||q.get('subproject'))return set('trackingPage',{project:q.get('project')});
    }
    if(frame.page==='partsPage'&&q.get('spool'))return set('partsPage',{project:q.get('project')});
    if(frame.page==='flowPage'&&q.get('item'))return set('flowPage',{project:q.get('project')});
    if(frame.page==='handoffPage'&&q.get('item'))return {page:'itemPage',url:'/?item='+encodeURIComponent(q.get('item')),label:'Item record'};
    if(frame.page==='dossierPage'){
      if(q.get('item')||q.get('tab'))return set('dossierPage',{project:q.get('project')});
      if(q.get('project'))return set('dossierPage');
    }
    if(frame.page==='qualityPage'){
      if(q.get('requirement')||q.get('tab'))return set('qualityPage',{workspace:q.get('workspace'),project:q.get('project')});
      if(q.get('workspace'))return set('qualityPage',{project:q.get('project')});
    }
    if(frame.page==='adminPage'&&(q.get('item')||q.get('employee')))return set('adminPage',{tab:q.get('tab')});
    if(frame.page==='guidePage'&&(q.get('section')||q.get('project')))return set('guidePage');
    if(['progressPage','productionProgressPage'].includes(frame.page)&&q.get('project'))return set(frame.page);
    // Legacy project records are not necessarily purchase orders. Their parent stays in that workspace.
    if(q.get('project')&&['trackingPage','partsPage','flowPage','qualityPage'].includes(frame.page))return set(frame.page);
    return home();
  }
  function target(){for(let i=stack.length-1;i>=0;i--){if(stack[i].page!==active?.page||stack[i].url!==active?.url)return stack[i];}return fallback();}
  function backLabel(){
    const snap=active?.page==='orderSetupPage'?window.FabOrderSetup?.navigationState?.():null;
    if(snap?.wizard){const start=snap.wizard.mode==='new'?1:2;return snap.wizard.step>start?'Back to step '+(snap.wizard.step-1):snap.po?'Back to saved order':'Back to orders';}
    if(snap?.documentSetup)return 'Back to saved order';
    if(snap?.po)return 'Back to orders';
    const previous=target();return 'Back to '+(previous?.label||pages[previous?.page]?.[1]||'orders');
  }
  function changed(){
    if(!active)return;
    const label=labelFor(active.page),button=node('navBack'),currentLabel=node('navCurrent');
    active.label=label;
    if(button){button.disabled=busy;const text='← '+backLabel();if(button.textContent!==text)button.textContent=text;}
    if(currentLabel&&currentLabel.textContent!==label)currentLabel.textContent=label;
    node('moreTools')?.classList.toggle('fn-selected',!primary.has(active.page));
    for(const id of ['back','bulkBack','handoffBack'])node(id)?.classList.add('fn-legacy-back');
  }
  async function dispatch(frame){
    const q=new URL(frame.url,location.origin).searchParams,v=name=>q.get(name)||'';
    if(frame.page==='orderSetupPage'&&frame.moduleState&&window.FabOrderSetup?.restoreNavigation)return window.FabOrderSetup.restoreNavigation(frame.moduleState);
    switch(frame.page){
      case 'orderSetupPage':return window.FabOrderSetup.open({po:v('po')});
      case 'ordersPage':return window.FabOrders.open({po:v('po'),gpn:v('gpn'),assembly:v('assembly')});
      case 'orderLabelsPage':return window.FabOrderLabels.open({po:v('po'),gpn:v('gpn'),kind:'Spool'});
      case 'productionProgressPage':return window.FabProductionProgress.open({project:v('project')});
      case 'progressPage':return window.FabProgress.open({project:v('project')});
      case 'handoffPage':return window.FabHandoff.open({item:v('item')});
      case 'flowPage':return window.FabFlow.open({project:v('project'),item:v('item')});
      case 'guidePage':return window.FabGuide.open({project:v('project'),section:v('section')});
      case 'trackingPage':return window.FabTracking.open({project:v('project'),subproject:v('subproject'),spool:v('spool'),weld:v('weld'),view:v('view')});
      case 'partsPage':return window.FabParts.open({project:v('project'),spool:v('spool')});
      case 'qualityPage':return window.FabQuality.open({workspace:v('workspace'),requirement:v('requirement'),project:v('project'),tab:v('tab')});
      case 'dossierPage':return window.FabDossier.open({project:v('project'),item:v('item'),tab:v('tab')||'items'});
      case 'adminPage':if(me?.role!=='admin')return window.FabOrderSetup.open();return window.FabAdmin.open({item:v('item'),tab:v('tab')||'items',badge:v('employee'),includeRemoved:v('removed')==='1'});
      case 'removalsPage':if(me?.role!=='admin')return window.FabOrderSetup.open();return window.FabRemovals.openList();
      case 'itemPage':return v('item')?openItem(v('item')):v('spool')?openItem(await window.resolveItemQr(new URL(frame.url,location.origin).href)):window.FabOrderSetup.open();
      case 'itemsPage':offset=frame.itemOffset||0;if(node('search'))node('search').value=frame.fields?.find(field=>field.id==='search')?.value||'';return listItems();
      case 'bulkPage':if(!jobCan('manage_production'))return window.FabOrderSetup.open();return node('navBulk').onclick();
      case 'staffPage':if(me?.role!=='admin')return window.FabOrderSetup.open();return node('navStaff').onclick();
      case 'auditPage':if(!jobCan('view_audit'))return window.FabOrderSetup.open();return node('navAudit').onclick();
      default:return window.FabOrderSetup.open();
    }
  }
  function restoreFields(frame){
    const root=node(frame.page);if(!root)return;
    // The setup module restores its own authoritative draft. Passwords and file inputs are never copied.
    if(frame.page!=='orderSetupPage')for(const saved of frame.fields||[]){
      const el=saved.id?node(saved.id):[...root.querySelectorAll('input,select,textarea')].find(candidate=>candidate.name===saved.name&&candidate.tagName===saved.tag);
      if(!el||!root.contains(el)||el.type==='password'||el.type==='file'||el.type==='hidden')continue;
      if(['checkbox','radio'].includes(el.type)){if(el.checked!==saved.checked){el.checked=saved.checked;el.dispatchEvent(new Event('change',{bubbles:true}));}}
      else if(el.value!==saved.value){el.value=saved.value;el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));}
    }
    for(const saved of frame.details||[]){const el=saved.id?node(saved.id):root.querySelectorAll('details')[saved.index];if(el&&root.contains(el))el.open=saved.open;}
    window.scrollTo({top:Math.max(0,frame.scroll||0),behavior:'instant'});
  }
  async function restore(frame,{remember=false}={}){
    if(!safeUrl(frame?.url)||!pages[frame?.page]||!canLeave(frame.page))return false;
    if(remember){prepare();push(prepared);}
    restoring++;
    try{
      originalReplace(null,'',frame.url);await dispatch(frame);
      if(active?.page===frame.page){
        active={...copyFrame(frame),url:safeUrl(location.href)||frame.url,transition:false};
        restoreFields(frame);
        if(frame.documents&&window.FabSpoolDocuments?.restoreNavigation)await window.FabSpoolDocuments.restoreNavigation(frame.documents);
        if(frame.materials&&window.FabSpoolBom?.restoreNavigation)await window.FabSpoolBom.restoreNavigation(frame.materials);
        capture();
      }
      prepared=null;return true;
    }finally{restoring--;changed();}
  }
  async function back(){
    if(busy||!active)return;
    busy=true;changed();
    try{
      // A document review or setup step has a closer parent than the previous workspace.
      restoring++;
      const before=active.url,page=active.page;
      let handled;
      try{handled=await window.FabSpoolBom?.back?.();if(!handled)handled=await window.FabSpoolDocuments?.back?.();if(!handled&&page==='orderSetupPage')handled=await window.FabOrderSetup?.back?.();}finally{restoring--;}
      if(handled){
        if(active?.page===page&&active.url!==before)while(stack.at(-1)?.page===page)stack.pop();
        capture();return;
      }
      if(!canLeave(target().page))return;
      let previous;
      while(stack.length){const candidate=stack.pop();if(candidate.page!==active.page||candidate.url!==active.url){previous=candidate;break;}}
      await restore(previous||fallback());
    }catch(error){notify(error?.message||'The previous view could not be opened. Use Orders to continue.');}
    finally{busy=false;changed();}
  }
  // Event capture runs before feature handlers mutate local selections or replace their route.
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('button,a,summary');if(!button)return;
    if(!canLeave(active?.page)&&!node(active?.page)?.contains(button)&&!button.closest('dialog')){event.preventDefault();event.stopImmediatePropagation();return;}
    prepare();
    if(!button.closest('#moreTools'))node('moreTools')?.removeAttribute('open');
    else if(button.tagName==='BUTTON')node('moreTools')?.removeAttribute('open');
  },true);
  document.addEventListener('change',prepare,true);document.addEventListener('submit',prepare,true);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&node('moreTools')?.open){node('moreTools').open=false;node('moreTools').querySelector('summary')?.focus();}});
  node('navBack').onclick=back;
  for(const id of ['back','bulkBack','handoffBack'])if(node(id))node(id).onclick=back;
  // Main Orders reopens an unfinished setup instead of replacing it with a fresh list.
  const ordersClick=node('navOrders').onclick;
  node('navOrders').onclick=()=>{
    if(!canLeave('orderSetupPage'))return;
    if(active?.page==='orderSetupPage')capture();
    const last=lastByPage.get('orderSetupPage'),snapshot=last?.moduleState;
    if(snapshot&&(snapshot.wizard||snapshot.pausedDraft||snapshot.documentSetup))return restore(last,{remember:active?.page!=='orderSetupPage'});
    return ordersClick();
  };
  for(const [page,[name]] of Object.entries(pages)){
    const module=window[name];if(!module)continue;
    for(const method of ['open','openPlan','openBadge','openList'])if(typeof module[method]==='function'){
      const original=module[method];module[method]=function(...args){if(!canLeave(page))return Promise.resolve(false);return original.apply(this,args);};
    }
  }
  window.FabNavigation={beforeShow,afterShow,back,changed,canNavigateAway:()=>canLeave(active?.page),
    // Read-only route metadata is useful for diagnostics; opaque draft contents are not exposed here.
    state:()=>({page:active?.page||null,url:active?.url||null,depth:stack.length,backTarget:target()?.url||home().url})};
  const observer=new MutationObserver(()=>{if(observing)return;observing=true;queueMicrotask(()=>{observing=false;changed();});});
  observer.observe(node('workspace'),{subtree:true,childList:true});
})();
