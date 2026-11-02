/* FabTrace project / spool / weld workspace. No client-side acceptance authority. */
(() => {
  'use strict';
  const ROOT = '/api/tracking';
  const node = id => document.getElementById(id);
  const encode = encodeURIComponent;
  const state = {view:'overview', project:'', subproject:'', query:'', status:'', processFilter:'', overview:null, spool:null, weld:null, routeSpool:'', routeWeld:'', exceptions:[], sequence:0, read:null, dialogAction:null, dialogStale:false, processCatalog:null, processDialogLoading:false};
  const role = () => me?.role || '';
  const capability = name => window.FabPermissions?.can(name)===true;
  const manage = () => capability('manage_production');
  const review = () => capability('quality_review');
  const holdRole = () => capability('open_rework');
  const roleLabel = id => window.FabPermissions?.label(id)||id;
  const processAllowed = (action,process=state.spool?.production_process) => Array.isArray(process?.permissions?.allowed_actions)&&process.permissions.allowed_actions.includes(action);
  const operationAllowed = (operation,weld=state.weld) => Array.isArray(weld?.allowed_operations)&&weld.allowed_operations.includes(operation);
  const stamp = value => value ? new Date(value).toLocaleString() : '—';
  const number = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  const arr = value => Array.isArray(value) ? value : [];
  const pick = (value, fallback='—') => value === null || value === undefined || value === '' ? fallback : value;
  const request = (path, method, body) => api(ROOT + path, {method, body:JSON.stringify(body)});
  const isSpool = item => item?.route ? item.route==='spool' : item?.kind!=='Assembly';
  const itemLabel = item => isSpool(item) ? window.FabFlowStatus?.spoolNumber?.(item)||item.qr_alias||item.spool_number||item.google_part_number||item.item_id||item.id : item.item_id||item.id;
  const itemText = (item,label=itemLabel(item)) => isSpool(item) ? window.FabFlowStatus?.spoolText?.(item,label)||esc(label) : esc(label);
  const flowBadge = item => isSpool(item) ? window.FabFlowStatus?.badge(item.flow_stage)||'' : '';
  const option = (value,label,selected='') => `<option value="${esc(value)}"${String(value)===String(selected)?' selected':''}>${esc(label)}</option>`;
  const btn = (action,label,data='',className='',item=null) => `<button type="button" class="${esc(className)}" data-ft-action="${esc(action)}"${data?` data-ft-id="${esc(data)}"`:''}>${item?itemText(item,label):esc(label)}</button>`;
  const small = text => `<span class="ft-secondary">${esc(text)}</span>`;
  const wrap = html => `<div class="tablewrap">${html}</div>`;
  const statusNames = {pending:'Pending',submitted:'Awaiting review',accepted:'Accepted',rejected:'Rejected',not_applicable:'Not applicable',blocked:'On hold',hold:'On hold',complete:'Complete',in_progress:'In progress',not_started:'Not started',open:'Open',closed:'Closed'};
  const statusClass = {accepted:'good',complete:'good',submitted:'pending',pending:'pending',rejected:'bad',blocked:'hold',hold:'hold',not_applicable:'na',not_started:'na',open:'hold',closed:'good',in_progress:'pending'};
  const requirementBadge = r => badge(r.status)+(r.satisfied===false&&['accepted','not_applicable'].includes(r.status)?'<span class="ft-secondary">Prerequisite incomplete</span>':'');
  const badge = status => `<span class="ft-tag ${statusClass[status]||'na'}">${esc(statusNames[status]||status||'Pending')}</span>`;
  const stageNames = {before_welding:'Before welding',after_welding:'After welding',release:'Release'};
  const processStatusNames = {not_started:'Timing not started',running:'Running',paused:'Paused',finished:'Finished'};
  const processEventNames = {start:'Started process',move:'Moved to process',pause:'Paused',resume:'Resumed',finish:'Finished process',release:'Closed on final release'};
  const processClocks = new WeakMap();
  const monotonicNow = () => typeof performance!=='undefined'&&typeof performance.now==='function'?performance.now():Date.now();
  let processClockTimer=null;
  const operationNames = {fitup:'Fit-up recorded',root:'Root recorded',fill_cap:'Fill / cap recorded',complete:'Weld completed'};
  const closedHold = h => Boolean(h.closed_at || h.closed);
  const isRemoved = () => state.spool?.removal?.removed===true||state.spool?.item?.removal?.removed===true;
  const isLocked = () => Boolean(state.spool?.item?.released)||isRemoved();
  const removedNotice = () => isRemoved()?'<div class="fr-removed-notice"><strong>Removed record · History only</strong><p>Recorded welds, inspections and process history are retained. Open Item &amp; QR record to review or restore its removed group.</p></div>':'';
  const currentWeld = () => state.weld || null;
  const requirementsFor = () => state.weld ? arr(state.weld.requirements) : arr(state.spool?.requirements);
  const allRequirements = () => [...arr(state.spool?.requirements), ...arr(state.spool?.welds).flatMap(w => arr(w.requirements))];
  const findRequirement = id => allRequirements().find(r => String(r.id)===String(id)) || arr(state.weld?.requirements).find(r=>String(r.id)===String(id));
  function errorText(error) {
    try {const detail=JSON.parse(error.message);if(Array.isArray(detail))return detail.map(x=>`${arr(x.loc).filter(p=>p!=='body').join(' / ')}: ${x.msg||'Check the value'}`).join('\n')}catch(_){}
    return error.message||'The request could not be completed.';
  }

  function duration(seconds) {
    const value=Math.max(0,Math.floor(number(seconds))), days=Math.floor(value/86400), hours=Math.floor(value%86400/3600), minutes=Math.floor(value%3600/60), rest=value%60;
    return `${days?days+'d ':''}${days||hours?String(hours).padStart(days?2:1,'0')+'h ':''}${String(minutes).padStart(2,'0')}m ${String(rest).padStart(2,'0')}s`;
  }
  function markProcessClock(process) {
    if(process&&typeof process==='object'&&!processClocks.has(process))processClocks.set(process,monotonicNow());
    return process;
  }
  function processRate(process,kind) {
    if(!process?.current||!['running','paused'].includes(process.status))return 0;
    return kind==='elapsed_seconds'||kind==='active_seconds'&&process.status==='running'||kind==='paused_seconds'&&process.status==='paused'?1:0;
  }
  function clockValue(process,base,kind,live=true) {
    markProcessClock(process);
    const anchor=processClocks.get(process)??monotonicNow(), rate=live?processRate(process,kind):0;
    const seconds=number(base)+rate*Math.max(0,(monotonicNow()-anchor)/1000);
    return `<span class="ft-duration"${rate?` data-ft-clock="${number(base)}" data-ft-rate="${rate}" data-ft-anchor="${anchor}"`:''}>${duration(seconds)}</span>`;
  }
  function stopProcessClock() {
    if(processClockTimer!==null){clearInterval(processClockTimer);processClockTimer=null;}
  }
  function startProcessClock() {
    stopProcessClock();
    const host=node('trackingContent');
    if(typeof setInterval!=='function'||typeof host.querySelectorAll!=='function')return;
    const clocks=[...host.querySelectorAll('[data-ft-clock]')];
    if(!clocks.length)return;
    const tick=()=>{const now=monotonicNow();for(const clock of clocks)clock.textContent=duration(number(clock.dataset.ftClock)+number(clock.dataset.ftRate)*Math.max(0,(now-number(clock.dataset.ftAnchor))/1000))};
    tick();processClockTimer=setInterval(tick,1000);
  }
  function processBadge(status) {
    return `<span class="ft-tag ${status==='running'?'pending':status==='paused'?'hold':status==='finished'?'good':'na'}">${esc(processStatusNames[status]||processStatusNames.not_started)}</span>`;
  }
  function processKey(process) {
    const current=process?.current;
    return current?(current.group_key||`${current.process_key}:${current.process_key==='custom'?String(current.process_name).toLowerCase():''}`):process?.status==='finished'?'@finished':'@not_started';
  }
  function processFilters() {
    const choices=new Map([['@not_started','Timing not started'],['@finished','Finished timing']]);
    for(const spool of arr(state.overview?.spools))if(spool.production_process?.current)choices.set(processKey(spool.production_process),spool.production_process.current.process_name);
    return `<div class="field"><label for="ftProcessFilter">Current production process</label><select id="ftProcessFilter">${option('','All processes',state.processFilter)}${[...choices].map(([key,label])=>option(key,label,state.processFilter)).join('')}</select></div>`;
  }

  function field(name,label,value='',settings={}) {
    const id = `ft-field-${name}`;
    const common = `id="${esc(id)}" name="${esc(name)}"${settings.required?' required':''}${settings.disabled?' disabled':''}${settings.readonly?' readonly':''}`;
    let control;
    if(settings.options) control = `<select ${common}>${settings.options.map(x=>Array.isArray(x)?option(x[0],x[1],value):option(x,x,value)).join('')}</select>`;
    else if(settings.type==='textarea') control = `<textarea ${common}${settings.maxlength?` maxlength="${settings.maxlength}"`:''}>${esc(value)}</textarea>`;
    else control = `<input ${common} type="${esc(settings.type||'text')}" value="${esc(value)}"${settings.min!==undefined?` min="${settings.min}"`:''}${settings.max!==undefined?` max="${settings.max}"`:''}${settings.step?` step="${settings.step}"`:''}${settings.minlength?` minlength="${settings.minlength}"`:''}${settings.maxlength?` maxlength="${settings.maxlength}"`:''}${settings.pattern?` pattern="${esc(settings.pattern)}"`:''}${settings.placeholder?` placeholder="${esc(settings.placeholder)}"`:''}>`;
    return `<div class="field${settings.full?' ft-span':''}"><label for="${esc(id)}">${esc(label)}${settings.required?' *':''}</label>${control}${settings.help?`<span class="ft-help">${esc(settings.help)}</span>`:''}</div>`;
  }
  function check(name,label,checked=false) {
    return `<div class="ft-check"><input type="checkbox" id="ft-check-${esc(name)}" name="${esc(name)}"${checked?' checked':''}><label for="ft-check-${esc(name)}">${esc(label)}</label></div>`;
  }
  function safeEvidence(reference) {
    const text = String(reference||'');
    try {
      const url = new URL(text);
      if(['https:','http:'].includes(url.protocol) && !url.username && !url.password) return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>`;
    } catch (_) {}
    return esc(text || 'No reference');
  }
  function definitionRows(list) {
    return `<div class="ft-meta-grid">${list.map(([key,value])=>`<dl><dt>${esc(key)}</dt><dd>${esc(pick(value))}</dd></dl>`).join('')}</div>`;
  }
  function empty(title,text,actions='') {
    return `<div class="ft-empty"><strong>${esc(title)}</strong><p>${esc(text)}</p>${actions}</div>`;
  }
  function filtersQuery() {
    const q = new URLSearchParams();
    if(state.project) q.set('project_id',state.project);
    if(state.subproject) q.set('subproject_id',state.subproject);
    return q.size?'?'+q.toString():'';
  }
  function updateUrl() {
    const q = new URLSearchParams({tracking:'1'});
    if(state.project) q.set('project',state.project);
    if(state.subproject) q.set('subproject',state.subproject);
    if(state.spool?.item?.id) q.set('spool',state.spool.item.id);
    if(state.weld?.id) q.set('weld',state.weld.id);
    if(!['overview','spool','weld'].includes(state.view)) q.set('view',state.view);
    history.replaceState(null,'','/?'+q.toString());
  }
  async function getOverview(read,detailOnly=false) {
    if(!detailOnly)return read(ROOT+'/overview'+filtersQuery());
    // Detail forms need the planning catalogs, not summaries of every other spool.
    const [projects,subprojects,templates]=await Promise.all([read(ROOT+'/projects'),read(ROOT+'/subprojects'),read(ROOT+'/templates')]);
    if(![projects,subprojects,templates].every(Array.isArray))throw Error('The planning choices could not be verified. Refresh to try again.');
    return {projects,subprojects,templates,spools:[]};
  }
  async function open(options={}) {
    if(!me) return;
    show('trackingPage');
    if(typeof stopCloudCamera==='function') stopCloudCamera();
    current = null;
    if(Object.prototype.hasOwnProperty.call(options,'project')) state.project = options.project || '';
    if(Object.prototype.hasOwnProperty.call(options,'subproject')) state.subproject = options.subproject || '';
    if(options.resetFilters===true){state.query='';state.status='';state.processFilter='';}
    state.view = options.weld?'weld':options.spool?'spool':(options.view||'overview');
    if(!['overview','spools','exceptions','templates','spool','weld'].includes(state.view)) state.view='overview';
    state.spool=null; state.weld=null;
    state.routeSpool=options.spool||'';state.routeWeld=options.weld||'';
    await load({spool:options.spool,weld:options.weld});
  }
  async function load(target={}) {
    const sequence=++state.sequence,view=state.view,detailOnly=['spool','weld'].includes(view);
    const spoolId=detailOnly?(target.spool||state.spool?.item?.id||''):'',weldId=detailOnly?(target.weld||state.weld?.id||''):'';
    cancelRead();
    const pending={controller:new AbortController(),timer:null,timedOut:false};state.read=pending;
    pending.timer=setTimeout(()=>{pending.timedOut=true;pending.controller.abort();},30000);
    const read=url=>api(url,{signal:pending.controller.signal});
    stopProcessClock();
    node('trackingContent').innerHTML='<div class="ft-state" role="status">Loading project and weld records…</div>';
    node('trackingContent').setAttribute('aria-busy','true');
    try {
      const detail=async()=>{
        let spool=spoolId?await read(ROOT+'/spools/'+encode(spoolId)):null,weld=null;
        if(sequence!==state.sequence)return null;
        if(spoolId&&spool?.item?.id!==spoolId)throw Error('The spool record does not match the selected item. Reopen it and try again.');
        if(weldId){
          weld=arr(spool?.welds).find(w=>String(w.id)===String(weldId))||await read(ROOT+'/welds/'+encode(weldId));
          if(sequence!==state.sequence)return null;
          if(String(weld?.id)!==String(weldId)||!weld?.item_id)throw Error('The weld record does not match the selected joint. Reopen it and try again.');
          if(!spool||spool.item.id!==weld.item_id){
            spool=await read(ROOT+'/spools/'+encode(weld.item_id));
            if(sequence!==state.sequence)return null;
            if(spool?.item?.id!==weld.item_id)throw Error('The weld and spool records could not be matched. Reopen the spool and try again.');
          }
        }
        return {spool,weld};
      };
      const [overview,records,exceptions]=await Promise.all([
        getOverview(read,detailOnly),detail(),view==='exceptions'?read(ROOT+'/exceptions'+filtersQuery()):Promise.resolve(null),
      ]);
      if(sequence!==state.sequence) return;
      state.overview=overview;state.spool=records.spool;state.weld=records.weld;
      for(const spool of arr(overview.spools))markProcessClock(spool.production_process);
      if(state.spool)markProcessClock(state.spool.production_process);
      if(view==='exceptions')state.exceptions=arr(exceptions.exceptions);
      render(); updateUrl();
    } catch(error) {
      if(sequence!==state.sequence) return;
      const message=pending.timedOut?'This request took too long. Try again to load the current tracking record.':errorText(error);
      node('trackingContent').innerHTML=`<div class="ft-state ft-error" role="alert"><strong>Tracking records could not be loaded.</strong><p>${esc(message)}</p><div class="actions">${btn('retry','Try again')}${btn('overview','Back to projects')}</div></div>`;
    } finally {clearTimeout(pending.timer);pending.controller.abort();if(state.read===pending)state.read=null;if(sequence===state.sequence)node('trackingContent').setAttribute('aria-busy','false');}
  }
  function cancelRead(){const pending=state.read;if(!pending)return;state.read=null;clearTimeout(pending.timer);pending.controller.abort();}
  async function refresh() {
    await load({spool:state.spool?.item?.id||state.routeSpool,weld:state.weld?.id||state.routeWeld});
  }
  function pageHeading(title,subtitle,actions='',item=null,suffix='') {
    return `<div class="ft-top"><div><h1>${item?itemText(item,title):esc(title)}${suffix?' · '+esc(suffix):''}</h1><p>${esc(subtitle)}</p></div><div class="actions">${actions}${btn('refresh','Refresh')}</div></div>`;
  }
  function toolbar() {
    const data=state.overview||{};
    const projects=arr(data.projects), subprojects=arr(data.subprojects).filter(s=>!state.project||s.project_id===state.project);
    return `<div class="ft-toolbar"><div class="field"><label for="ftProjectFilter">Project</label><select id="ftProjectFilter">${option('','All projects',state.project)}${projects.map(p=>option(p.id,`${p.id} · ${p.name}`,state.project)).join('')}</select></div><div class="field"><label for="ftSubprojectFilter">Subproject / work package</label><select id="ftSubprojectFilter">${option('','All subprojects',state.subproject)}${subprojects.map(p=>option(p.id,`${p.id} · ${p.name}`,state.subproject)).join('')}</select></div>${state.view==='spools'?processFilters():''}<div class="field ft-search"><label for="ftSearch">Find a spool, drawing, assembly, or process</label><input id="ftSearch" type="search" value="${esc(state.query)}" placeholder="Filter the displayed records"></div></div>`;
  }
  function tabs() {
    return `<div class="ft-tabs" role="tablist" aria-label="Project tracking views">${[['overview','Overview'],['spools','Spool register'],['exceptions','Outstanding requirements'],['templates','Requirement templates']].map(([id,label])=>`<button type="button" role="tab" aria-selected="${state.view===id}" data-ft-action="view" data-ft-id="${id}">${label}</button>`).join('')}</div>`;
  }
  function metric(label,value,detail,part=null,total=null) {
    const percent=total>0?Math.max(0,Math.min(100,part/total*100)):0;
    return `<div class="ft-metric"><span class="ft-metric-label">${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small>${part!==null?`<div class="ft-meter" aria-hidden="true"><span style="width:${percent}%"></span></div>`:''}</div>`;
  }
  function metrics(metricsData) {
    const m=metricsData||{}, planned=number(m.welds_planned??m.planned_welds), production=number(m.production_complete), qa=number(m.qa_accepted), spools=number(m.spools??1), ready=number(m.ready_to_release), released=number(m.released);
    return `<div class="ft-metrics">${metric('Production complete',`${production} / ${planned}`,'Completed joints / planned joints',production,planned)}${metric('Weld QA accepted',`${qa} / ${planned}`,'Accepted joints / planned joints',qa,planned)}${metric('Ready for final release',`${ready} / ${spools}`,'Spools that meet release checks',ready,spools)}${metric('Final release',`${released} / ${spools}`,'Released spools; shipping is recorded separately',released,spools)}</div>`;
  }
  function matchingSpools() {
    const q=state.query.toLowerCase().trim();
    return arr(state.overview?.spools).filter(s=>(state.view!=='spools'||!state.processFilter||processKey(s.production_process)===state.processFilter)&&(!q||[s.item_id,s.spool_number,s.google_part_number,s.qr_alias,s.display_code,s.assembly_id,s.project_name,s.subproject_name,s.drawing_revision,s.drawing,s.production_process?.current?.process_name].some(x=>String(x||'').toLowerCase().includes(q))));
  }
  function summaryFrom(spools) {
    return spools.reduce((m,s)=>{m.spools++;m.welds_planned+=number(s.planned_welds);m.production_complete+=number(s.production_complete);m.qa_accepted+=number(s.qa_accepted);m.ready_to_release+=s.ready_to_release&&!s.released?1:0;m.released+=s.released?1:0;return m;},{spools:0,welds_planned:0,production_complete:0,qa_accepted:0,ready_to_release:0,released:0});
  }
  function render() {
    if(!state.overview) return;
    let html;
    if(state.view==='weld' && state.weld) html=renderWeld();
    else if(state.view==='spool' && state.spool) html=renderSpool();
    else {
      const actions=manage()?(window.FabOrders?btn('purchase-orders','Start purchase order','','primary'):'')+btn('new-project','New project')+btn('new-subproject','New subproject')+btn('plan-spool','Add / assign spool','','primary'):'';
      html=pageHeading('Projects & welds','Track each work package, spool, and individual joint through production, evidence review, and final release.',actions)+toolbar()+tabs();
      if(state.view==='overview') html+=renderOverview();
      if(state.view==='spools') html+=renderSpoolRegister();
      if(state.view==='exceptions') html+=renderExceptions();
      if(state.view==='templates') html+=renderTemplates();
    }
    node('trackingContent').innerHTML=html;
    node('trackingContent').setAttribute('aria-busy','false');
    wireFilters();
    startProcessClock();
  }
  function wireFilters() {
    const project=node('ftProjectFilter'), subproject=node('ftSubprojectFilter'), search=node('ftSearch'), process=node('ftProcessFilter');
    if(project) project.onchange=async()=>{state.project=project.value;state.subproject='';await load()};
    if(subproject) subproject.onchange=async()=>{state.subproject=subproject.value;if(state.subproject&&!state.project){const s=arr(state.overview.subprojects).find(x=>x.id===state.subproject);if(s)state.project=s.project_id}await load()};
    if(search) search.oninput=()=>{state.query=search.value;const start=search.selectionStart,end=search.selectionEnd;render();node('ftSearch').focus();node('ftSearch').setSelectionRange(start,end)};
    if(process)process.onchange=()=>{state.processFilter=process.value;render()};
  }
  function renderOverview() {
    const spools=matchingSpools(), data=state.overview;
    let html=metrics(summaryFrom(spools));
    if(!arr(data.projects).length) return html+empty('Start with a project','Create a project and subproject, then assign an existing FabTrace item as a spool. No sample records are added.',manage()?btn('new-project','Create project','','primary'):'Ask a supervisor or administrator to create the project.');
    const groups=new Map();
    for(const p of arr(data.projects).filter(p=>!state.project||p.id===state.project)) groups.set('p:'+p.id,{project:p,subproject:null,spools:[]});
    for(const s of arr(data.subprojects).filter(s=>(!state.project||s.project_id===state.project)&&(!state.subproject||s.id===state.subproject))) groups.set('s:'+s.id,{project:arr(data.projects).find(p=>p.id===s.project_id),subproject:s,spools:[]});
    for(const spool of spools) {const key=spool.subproject_id?'s:'+spool.subproject_id:'p:'+spool.project_id;if(groups.has(key))groups.get(key).spools.push(spool)}
    const visible=[...groups.values()].filter(g=>!state.subproject||g.subproject?.id===state.subproject).filter(g=>!state.query||g.spools.length);
    html+=`<div class="card"><div class="ft-section-heading"><h2>Work packages</h2><span class="muted">Select a package to see its spools</span></div>`;
    html+=visible.length?wrap(`<table class="ft-table"><thead><tr><th>Project / subproject</th><th>Spools</th><th>Production</th><th>Weld QA</th><th>Release</th><th>Open blockers</th></tr></thead><tbody>${visible.map(g=>{const m=summaryFrom(g.spools),blockers=g.spools.reduce((n,s)=>n+arr(s.blockers).length,0);return `<tr><td>${btn(g.subproject?'select-subproject':'select-project',g.subproject?`${g.subproject.id} · ${g.subproject.name}`:`${g.project?.id||''} · ${g.project?.name||''}`,g.subproject?.id||g.project?.id,'ft-link')}${small(g.subproject?g.project?.name||g.project?.id||'':'Spools without a subproject')}</td><td class="ft-num">${m.spools}</td><td class="ft-num">${m.production_complete} / ${m.welds_planned}</td><td class="ft-num">${m.qa_accepted} / ${m.welds_planned}</td><td class="ft-num">${m.released} / ${m.spools}</td><td>${blockers?`<span class="ft-tag hold">${blockers} blocking checks</span>`:'<span class="muted">—</span>'}</td></tr>`}).join('')}</tbody></table>`):empty('No matching work packages','Clear the search or choose another project.');
    html+='</div>';
    if(!spools.length) html+=empty('No spools assigned in this view','Assign an existing item, set its planned weld count, and add the individual welds.',manage()?btn('plan-spool','Add / assign spool','','primary'):'');
    else html+=`<div class="card"><div class="ft-section-heading"><h2>Spools needing attention</h2>${btn('view','All spools','spools','ft-link')}</div>${spoolTable(spools.filter(s=>arr(s.blockers).length&&!s.released).slice(0,10))}</div>`;
    return html;
  }
  function renderProcessCell(process) {
    if(!process?.current)return processBadge(process?.status||'not_started');
    return `<strong>${esc(process.current.process_name)}</strong>${small(processStatusNames[process.status]||process.status)}${clockValue(process,process.current.elapsed_seconds,'elapsed_seconds')}`;
  }
  function spoolTable(spools) {
    if(!spools.length) return '<p class="muted">No spools with outstanding blockers in this view.</p>';
    return wrap(`<table class="ft-table"><thead><tr><th>Spool / item</th><th>Work package</th><th>Current process / elapsed</th><th>Production</th><th>Weld QA</th><th>Next blocker</th><th>Release / target</th></tr></thead><tbody>${spools.map(s=>`<tr><td>${btn('open-spool',itemLabel(s),s.item_id,'ft-link ft-spool-id',s)}${flowBadge(s)}${s.assembly_id?small('Assembly: '+s.assembly_id):''}</td><td>${esc(s.project_name||s.project_id||'Unassigned')}${small(s.subproject_name||s.subproject_id||'No subproject')}</td><td>${renderProcessCell(s.production_process)}</td><td class="ft-num">${number(s.production_complete)} / ${number(s.planned_welds)}${small(`${number(s.welds_defined)} weld records`)}</td><td class="ft-num">${number(s.qa_accepted)} / ${number(s.planned_welds)}</td><td>${arr(s.blockers).length?esc(s.blockers[0])+' '+(s.blockers.length>1?small(`+ ${s.blockers.length-1} more checks`):''):'<span class="muted">No blocking checks</span>'}</td><td>${s.release_control?.mode==='admin_override'?'<span class="fa-release-tag">Administrative release</span>':s.released?badge('accepted'):s.ready_to_release?'<span class="ft-tag good">Ready for release</span>':'<span class="ft-tag pending">Open</span>'}${small(s.due_date||'No target date')}</td></tr>`).join('')}</tbody></table>`);
  }
  function renderSpoolRegister() {
    const spools=matchingSpools();
    return metrics(summaryFrom(spools))+`<div class="card"><div class="ft-section-heading"><h2>Spool register</h2><span class="muted">${spools.length} matching spools</span></div>${spools.length?spoolTable(spools):empty('No matching spools','Clear the filters or assign an existing item to a project.',manage()?btn('plan-spool','Add / assign spool','','primary'):'')}</div>`;
  }
  function renderExceptions() {
    const q=state.query.toLowerCase().trim();
    const rows=state.exceptions.filter(x=>!q||[x.item_id,x.spool_number,x.google_part_number,x.qr_alias,x.display_code,x.weld_number,x.label,x.type,x.owner_role].some(v=>String(v||'').toLowerCase().includes(q)));
    return `<div class="card"><div class="ft-section-heading"><h2>Outstanding requirements</h2><span class="muted">${rows.length} records</span></div><p class="ft-filter-note">Each row points to the spool or weld where the requirement can be resolved. Submitted evidence still requires an authorized review.</p>${rows.length?wrap(`<table class="ft-table"><thead><tr><th>Spool</th><th>Weld</th><th>Requirement / blocker</th><th>Status</th><th>Responsible role</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td>${btn('open-spool',itemLabel(x),x.item_id,'ft-link',x)}</td><td>${esc(x.weld_number||'Spool level')}</td><td>${esc(x.label||x.type)}${small(x.type||'')}</td><td>${badge(x.status||'pending')}</td><td>${esc(roleLabel(x.owner_role)||'Supervisor')}</td><td>${btn(x.weld_id?'open-weld':'open-spool','Open',x.weld_id||x.item_id)}</td></tr>`).join('')}</tbody></table>`):empty('No outstanding requirements in this view','Choose another project or clear the search to see more records.')}</div>`;
  }
  function renderTemplates() {
    const templates=arr(state.overview.templates);
    return `<div class="card"><div class="ft-section-heading"><h2>Weld requirement templates</h2>${manage()?btn('new-template','New template revision','','primary'):''}</div><p class="muted">Choose a template when creating a weld. Templates define requirements, approval stages, evidence, and whether a justified not-applicable decision is allowed. Saved revisions remain unchanged.</p><div class="notice">The baseline checklist covers material traceability, procedure / qualification review, fit-up, visual examination, NDE applicability, and final QA. Add the exact examinations and acceptance references required for the job; no code percentage is assumed.</div>${templates.length?`<div class="ft-template-grid">${templates.map(t=>`<div class="card"><div class="row"><h3>${esc(t.name)}</h3><span class="ft-tag">Rev ${esc(t.revision)}</span></div><p class="muted">${esc(t.code||t.id)}</p>${t.source?`<p>${esc(t.source)}</p>`:''}<ol>${arr(t.requirements).map(r=>`<li><strong>${esc(r.label)}</strong> · ${esc(stageNames[r.stage]||r.stage)}${r.allow_na?' · N/A review allowed':''}${r.evidence_required?' · evidence required':''}</li>`).join('')}</ol>${manage()?btn('copy-template','Create next revision',t.id):''}</div>`).join('')}</div>`:empty('Baseline checklist available','Create a project-specific template when additional requirements are needed.',manage()?btn('new-template','Create template','','primary'):'')}</div>`;
  }
  function crumbs(weld=false) {
    const spool=state.spool;
    return `<div class="ft-crumbs">${btn('overview','Projects','','ft-link')}<span>/</span>${weld?btn('back-spool',itemLabel(spool.item),'','ft-link',spool.item):`<span>${itemText(spool.item)}</span>`}${weld?`<span>/</span><span>${esc(state.weld.number)}</span>`:''}</div>`;
  }
  function renderSpool() {
    const s=state.spool, item=s.item, plan=s.plan;
    let actions=btn('item-record','Item & QR record',item.id);
    actions+=btn('process-flow','Process flow',item.id);if(capability('admin')&&!isRemoved())actions+=btn('admin-controls','Admin controls',item.id);
    if(item.kind!=='Assembly')actions+=btn('spool-parts','Spool parts',item.id);
    if(manage()&&!isLocked()) actions+=btn('edit-plan',plan?'Edit spool plan':'Set up spool','','primary');
    let html=crumbs()+pageHeading(itemLabel(item),'Individual weld tracking',actions,item)+flowBadge(item)+removedNotice();
    if(!plan) return html+empty('This item has no individual weld plan','Set its project, subproject, and planned weld count. Existing custody, QR, and inspection records stay linked to this item.',manage()&&!isLocked()?btn('edit-plan','Set up individual weld tracking','','primary'):'A supervisor or administrator can set up the spool plan.');
    const summary=s.summary||{};
    html+=metrics({...summary,spools:1,welds_planned:plan.planned_welds,ready_to_release:summary.ready_to_release&&!item.released?1:0,released:item.released?1:0});
    html+=renderProcess();
    if(s.parts?.configured){const t=s.parts.totals||{},required=number(t.required_qty),prepared=number(t.prepared_qty);html+=`<section class="card"><div class="ft-section-heading"><h2>Required parts</h2>${btn('spool-parts','Spool parts',item.id)}</div><p>${prepared} of ${required} required pieces prepared for fit-up · ${number(t.assigned_qty)} assigned · ${number(t.received_qty)} receipt recorded · ${number(t.short_qty)} still to assign</p>${required>0?`<progress max="${required}" value="${Math.min(required,prepared)}" aria-label="Required pieces prepared for fit-up" style="width:100%"></progress>`:''}<p class="ft-footer-note">Counts come from the required parts list and individual component records. Prepared quantities do not approve the spool's welds or final release.</p></section>`;}
    html+=`<div class="card"><div class="ft-section-heading"><h2>Spool plan</h2>${item.release_control?.mode==='admin_override'?'<span class="fa-release-tag">Administrative release · changes locked</span>':item.released?'<span class="ft-tag good">QA released · changes locked</span>':badge('open')}</div>${definitionRows([['Project',summary.project_name||plan.project_id],['Subproject',summary.subproject_name||plan.subproject_id],['Assembly',plan.assembly_id],['Drawing revision',plan.drawing_revision||item.drawing],['Target date',plan.due_date],['Location / handler',`${item.location||'—'} · ${item.handler||'—'}`]])}${plan.notes?`<p>${esc(plan.notes)}</p>`:''}${plan.zero_weld_reason?`<p class="muted">Zero-weld plan: ${esc(plan.zero_weld_reason)}</p>`:''}${arr(summary.blockers).length?`<details class="ft-fold" open><summary>${summary.blockers.length} release checks outstanding</summary><ul>${summary.blockers.map(b=>`<li>${esc(b)}</li>`).join('')}</ul></details>`:'<p class="muted">All current tracking checks are satisfied.</p>'}<div class="actions">${!isLocked()&&review()?btn('dimensional','Record dimensional inspection'):''}${!isLocked()&&review()?btn('release','Approve final release','','primary'):''}${capability('admin')&&!isRemoved()?btn('admin-controls',item.released?'Release / return controls':'Release as administrator',item.id):''}${item.released&&!isRemoved()&&capability('admin')&&item.release_control?.mode!=='admin_override'?btn('reopen','Reopen released spool'):''}</div><p class="ft-footer-note">Ordinary final release records QA approval. Administrative release is identified separately and retains unresolved requirements. Shipment and delivery have their own records.</p></div>`;
    html+=`<div class="card"><div class="ft-section-heading"><h2>Individual weld matrix</h2>${manage()&&!isLocked()?btn('new-weld','Add weld','','primary'):''}</div><p class="ft-filter-note">${arr(s.welds).length} defined / ${number(plan.planned_welds)} planned joints. Root and fill / cap records count toward one joint.</p>${renderMatrix(arr(s.welds))}</div>`;
    html+=`<div class="ft-two-col"><div class="card"><div class="ft-section-heading"><h2>Spool requirements</h2>${manage()&&!isLocked()?btn('new-requirement','Add requirement'):''}</div>${renderRequirements(arr(s.requirements))}</div><div><div class="card"><div class="ft-section-heading"><h2>Holds</h2>${holdRole()&&!isLocked()?btn('new-hold','Place hold'):''}</div>${renderHolds(arr(s.holds))}</div><div class="card"><h2>Recent tracking history</h2>${renderAudit(arr(s.history).slice(0,20))}</div></div></div>`;
    return html;
  }
  function renderProcess() {
    const process=state.spool.production_process;
    if(!process)return '<section class="card"><h2>Production process time</h2><p class="muted">Refresh the spool to load its process timing.</p></section>';
    const current=process.current, visits=arr(process.visits), totals=process.totals||{};
    let actions='';
    if(process.flow_managed){
      actions=btn('process-flow','Open process flow',state.spool.item.id,'primary');
      if(process.flow_status==='active'&&current){if(processAllowed('resume',process))actions+=btn('process-resume','Resume process');if(processAllowed('pause',process))actions+=btn('process-pause','Pause / record delay');}
    }else if(!isLocked()){
      if(!current&&processAllowed('start',process))actions=btn('process-start',visits.length?'Start another process':'Start process','','primary');
      if(current){if(processAllowed('move',process))actions+=btn('process-move','Move to next process','','primary');if(processAllowed('resume',process))actions+=btn('process-resume','Resume process');if(processAllowed('pause',process))actions+=btn('process-pause','Pause / record delay');if(processAllowed('finish',process))actions+=btn('process-finish','Finish process');}
    }
    let html=`<section class="card ft-process-card" aria-labelledby="ftProcessHeading"><div class="ft-section-heading"><h2 id="ftProcessHeading">Production process time</h2>${processBadge(process.status)}</div>`;
    if(current){
      html+=`<div class="ft-process-current"><div><h3>${esc(current.process_name)}</h3><p class="muted">Started ${esc(stamp(current.started_at))} · ${esc(current.started_by)}</p></div><div class="actions">${actions}</div></div><div class="ft-process-metrics">${[['elapsed_seconds','Elapsed in this process'],['active_seconds','Running time'],['paused_seconds','Paused time']].map(([key,label])=>`<div><span>${label}</span><strong>${clockValue(process,current[key],key)}</strong></div>`).join('')}</div>`;
    }else{
      html+=`<div class="ft-process-current"><div><h3>${visits.length?'No process currently running':'Start timing when this spool enters a process'}</h3><p class="muted">${visits.length?'Choose the next process when work begins again.':'The first start records the time from now. Earlier production time is not estimated.'}</p></div><div class="actions">${actions}</div></div>`;
    }
    html+='<p class="ft-filter-note">Elapsed time includes pauses. Running time counts while the process is running; these are spool clock hours, not crew labor hours. '+(process.flow_managed?'Complete each numbered step in Process flow to move the timer.':'Finish or move the process when the spool leaves it.')+'</p>';
    if(isRemoved())html+='<p class="ft-readonly">Removed record · process timing is retained as recorded.</p>';
    else if(isLocked())html+=state.spool?.item?.release_control?.mode==='admin_override'?'<p class="ft-readonly">Administrative release is recorded. The actual work and inspection records remain visible; Admin controls can return this item to work.</p>':process.flow_managed?'<p class="ft-readonly">Quality release is recorded. The numbered process flow tracks the remaining receiving, assembly, or shipment steps.</p>':'<p class="ft-readonly">Released spool · process timing is closed. An administrator must reopen the spool before another process can start.</p>';
    if(visits.length){
      html+=`<div class="ft-process-total"><strong>Total recorded process time</strong><span>${clockValue(process,totals.elapsed_seconds,'elapsed_seconds')} elapsed</span><span>${clockValue(process,totals.active_seconds,'active_seconds')} running</span><span>${clockValue(process,totals.paused_seconds,'paused_seconds')} paused</span><span>${number(totals.visits)} process visits</span></div>`;
      html+='<h3>Time by process</h3>'+wrap(`<table class="ft-table ft-process-table"><thead><tr><th>Process</th><th>Visits</th><th>Elapsed</th><th>Running</th><th>Paused</th></tr></thead><tbody>${arr(process.by_process).map(row=>{const live=current&&(row.group_key&&current.group_key?row.group_key===current.group_key:row.process_key===current.process_key&&(row.process_key!=='custom'||String(row.process_name).toLowerCase()===String(current.process_name).toLowerCase()));return `<tr><td>${esc(row.process_name)}</td><td>${number(row.visits)}</td>${['elapsed_seconds','active_seconds','paused_seconds'].map(key=>`<td>${clockValue(process,row[key],key,live)}</td>`).join('')}</tr>`}).join('')}</tbody></table>`);
      html+='<h3>Process visits</h3>'+wrap(`<table class="ft-table ft-process-table"><thead><tr><th>Process / status</th><th>Entered</th><th>Left</th><th>Elapsed</th><th>Running</th><th>Paused</th></tr></thead><tbody>${[...visits].reverse().map(visit=>{const live=current&&String(visit.id)===String(current.id);return `<tr><td><strong>${esc(visit.process_name)}</strong>${small(processStatusNames[visit.status]||visit.status)}</td><td>${esc(stamp(visit.started_at))}${small(visit.started_by)}</td><td>${visit.ended_at?esc(stamp(visit.ended_at))+small([visit.ended_by,visit.end_reason==='release'?'Final release':processEventNames[visit.end_reason]||''].filter(Boolean).join(' · ')):'<span class="muted">Still in process</span>'}</td>${['elapsed_seconds','active_seconds','paused_seconds'].map(key=>`<td>${clockValue(process,visit[key],key,live)}</td>`).join('')}</tr>`}).join('')}</tbody></table>`);
      html+=`<details class="ft-fold"><summary>Process changes & delay reasons (${arr(process.events).length})</summary>${[...arr(process.events)].reverse().map(event=>`<div class="ft-history"><strong>${esc(processEventNames[event.event]||event.event)} · ${esc(event.process_name)}</strong>${event.notes?`<p>${esc(event.notes)}</p>`:''}<small>${esc(event.actor)} · ${esc(stamp(event.at))}</small></div>`).join('')}</details>`;
    }
    html+=`<p class="ft-footer-note">Timing follows the stages you record and does not grant quality acceptance. ${process.flow_managed?'Numbered process steps control stage changes.':'Final release closes an open process.'} Last synchronized ${esc(stamp(process.as_of))}; refresh to see changes recorded by another employee.</p></section>`;
    return html;
  }
  function renderMatrix(welds) {
    if(!welds.length) return empty('No welds defined yet','Add each joint with its material sides and procedure, then track its requirements independently.',manage()&&!isLocked()?btn('new-weld','Add first weld','','primary'):'');
    const columns=new Map();
    for(const w of welds) for(const r of arr(w.requirements)) if(!columns.has(r.code))columns.set(r.code,r.label);
    const cols=[...columns];
    return wrap(`<table class="ft-matrix"><thead><tr><th>Weld / joint</th><th>Production</th>${cols.map(([code,label])=>`<th>${esc(label)}</th>`).join('')}<th>QA accepted</th></tr></thead><tbody>${welds.map(w=>`<tr><td>${btn('open-weld',w.number,w.id,'ft-link')}${small([w.joint_type,w.size].filter(Boolean).join(' · '))}${arr(w.holds).some(h=>!closedHold(h))?'<span class="ft-tag hold">Hold</span>':''}</td><td>${badge(w.production_complete?'complete':arr(w.work).some(x=>number(x.cycle)===number(w.cycle))?'in_progress':'not_started')}</td>${cols.map(([code])=>{const r=arr(w.requirements).find(r=>r.code===code);return `<td>${r?`<button type="button" class="ft-cell" data-ft-action="open-weld" data-ft-id="${esc(w.id)}" title="${esc(r.label)} — ${esc(statusNames[r.status]||r.status)}">${requirementBadge(r)}</button>`:'<span class="muted" title="This requirement is not configured for this weld">Not configured</span>'}</td>`}).join('')}<td>${w.qa_accepted?badge('accepted'):badge('pending')}</td></tr>`).join('')}</tbody></table>`)+`<div class="ft-legend"><span>Pending = work or evidence missing</span><span>Awaiting review = evidence submitted</span><span>Not applicable = authorized decision</span><span>Not configured = no requirement record</span></div>`;
  }
  function renderWeld() {
    const w=state.weld;
    let actions=btn('back-spool','Back to spool');
    if(manage()&&!isLocked())actions+=btn('edit-weld','Edit joint details');
    let html=crumbs(true)+pageHeading(itemLabel(state.spool.item),w.description||'Individual weld requirements',actions,state.spool.item,w.number)+removedNotice();
    html+=`<div class="card"><div class="ft-section-heading"><h2>Joint identity & traceability</h2><div class="ft-inline-list">${badge(w.production_complete?'complete':'in_progress')}${w.qa_accepted?'<span class="ft-tag good">QA accepted</span>':'<span class="ft-tag pending">QA pending</span>'}<span class="ft-tag">Work cycle ${number(w.cycle)}</span></div></div>${definitionRows([['Joint type',w.joint_type],['Nominal size',w.size],['Wall thickness',w.wall_thickness],['WPS / revision',[w.wps,w.wps_revision].filter(Boolean).join(' / ')],['Drawing revision',w.drawing_revision],['Component A',w.component_a],['Heat A / MTR A',[w.heat_a,w.mtr_a].filter(Boolean).join(' / ')],['Component B',w.component_b],['Heat B / MTR B',[w.heat_b,w.mtr_b].filter(Boolean).join(' / ')]])}${isLocked()&&!isRemoved()?'<div class="ft-readonly">This spool is released. An administrator must reopen it before changes can be recorded.</div>':''}</div>`;
    html+=`<div class="ft-two-col"><div class="card"><div class="ft-section-heading"><h2>Every weld requirement</h2>${manage()&&!isLocked()?btn('new-requirement','Add requirement'):''}</div>${renderRequirements(arr(w.requirements))}</div><div><div class="card"><div class="ft-section-heading"><h2>Production work</h2></div>${renderWorkActions(w)}${renderWork(arr(w.work))}</div><div class="card"><div class="ft-section-heading"><h2>Holds & repair history</h2><div class="actions">${holdRole()&&!isLocked()?btn('new-hold','Place hold')+btn('repair','Open repair'):''}</div></div>${renderHolds(arr(w.holds))}${renderRepairs(arr(w.repairs))}</div></div></div>`;
    return html;
  }
  function renderWorkActions(w) {
    if(isLocked()) return '';
    const cycle=arr(w.work).filter(x=>number(x.cycle)===number(w.cycle));
    const recorded=new Set(cycle.map(x=>x.operation));
    const before=[...arr(w.requirements),...arr(state.spool.requirements)].filter(r=>r.stage==='before_welding');
    const beforeClear=before.every(r=>r.satisfied!==undefined?r.satisfied:['accepted','not_applicable'].includes(r.status));
    const holds=Boolean(state.spool.item.on_hold)||[...arr(w.holds),...arr(state.spool.holds).filter(h=>!h.weld_id||h.weld_id===w.id)].some(h=>!closedHold(h));
    const required=arr(w.required_operations).length?w.required_operations:['root','fill_cap'];
    const defs=[['fitup','Record fit-up',operationAllowed('fitup',w)],...required.map(operation=>[operation,operation==='root'?'Record root':'Record fill / cap',operationAllowed(operation,w)]),['complete','Mark weld complete',operationAllowed('complete',w)]];
    let html='<div class="actions">';
    for(const [operation,label,permitted] of defs) {
      if(!permitted) continue;
      const gated=operation!=='fitup'&&!beforeClear;
      const missingPasses=(operation==='complete'&&required.some(operation=>!recorded.has(operation)))||(operation==='fill_cap'&&required.includes('root')&&!recorded.has('root'));
      const disabled=w.production_complete||recorded.has(operation)||holds||gated||missingPasses;
      const why=w.production_complete?'This cycle is complete; open a repair for more work':recorded.has(operation)?'Already recorded this cycle':holds?'Resolve open holds first':gated?'Before-welding approvals are outstanding':missingPasses?'Record the preceding configured weld operations first':'';
      html+=`<button type="button" data-ft-action="work" data-ft-id="${operation}"${disabled?' disabled':''}${why?` title="${esc(why)}"`:''}>${label}${recorded.has(operation)?' ✓':''}</button>`;
    }
    html+='</div>';
    if(holds)html+='<p class="ft-footer-note">Work is on hold. Resolve the open hold before recording production.</p>';
    else if(!beforeClear)html+='<p class="ft-footer-note">Root, fill / cap, and completion require accepted before-welding checks.</p>';
    html+='<p class="ft-footer-note">The signed-in employee and server time are recorded. Production operations do not add extra completed joints.</p>';
    return html;
  }
  function renderRequirements(requirements) {
    if(!requirements.length) return '<p class="muted">No additional requirements are configured at this level.</p>';
    return requirements.map(r=>{
      const evidence=arr(r.evidence), reviews=arr(r.reviews);
      const currentEvidence=evidence.filter(e=>number(e.cycle)===number(r.cycle));
      const latest=currentEvidence[0];
      const canSubmit=!isLocked()&&r.permissions?.can_submit_evidence===true;
      const reviewButtons=!isLocked()&&r.permissions?.can_review===true;
      return `<article class="ft-requirement" id="ft-requirement-${esc(r.id)}"><div class="row"><h3>${esc(r.label)}</h3>${requirementBadge(r)}</div><p class="muted">${esc(stageNames[r.stage]||r.stage)} · ${esc(roleLabel(r.owner_role)||'Assigned role')} · ${r.evidence_required?'Evidence required':'Evidence optional'}</p>${r.source?`<p><strong>Source:</strong> ${esc(r.source)}</p>`:''}${arr(r.check_errors).length?`<p><strong>Prerequisites:</strong> ${r.check_errors.map(esc).join('; ')}</p>`:''}${latest?`<p><strong>Latest evidence:</strong> ${safeEvidence(latest.reference)}${latest.result?' · '+esc(latest.result):''}</p>${latest.notes?`<p>${esc(latest.notes)}</p>`:''}<p class="muted">${esc(latest.actor)} · ${stamp(latest.at)}</p>`:'<p class="muted">No evidence recorded for the current work cycle.</p>'}<div class="actions">${canSubmit?btn('evidence','Record evidence',r.id):''}${reviewButtons?btn('review-accept','Accept',r.id)+btn('review-reject','Reject',r.id)+(r.allow_na?btn('review-na','Not applicable',r.id):''):''}</div>${evidence.length||reviews.length?`<details class="ft-fold"><summary>Evidence & review history (${evidence.length+reviews.length})</summary>${evidence.map(e=>`<div class="ft-history"><strong>Evidence · ${esc(e.result||'recorded')}</strong><p>${safeEvidence(e.reference)}</p>${e.notes?`<p>${esc(e.notes)}</p>`:''}<small>${esc(e.actor)} · ${stamp(e.at)} · cycle ${esc(e.cycle)}</small></div>`).join('')}${reviews.map(v=>`<div class="ft-history"><strong>Review · ${esc(statusNames[v.decision]||v.decision||v.status)}</strong>${v.notes?`<p>${esc(v.notes)}</p>`:''}<small>${esc(v.actor||v.reviewer)} · ${stamp(v.at)} · cycle ${esc(v.cycle)}</small></div>`).join('')}</details>`:''}</article>`;
    }).join('');
  }
  function renderWork(work) {
    if(!work.length)return '<p class="muted">No production work recorded yet.</p>';
    return work.map(x=>`<div class="ft-history"><strong>${esc(operationNames[x.operation]||x.operation)}</strong><small>${esc(x.actor)} · ${stamp(x.at)} · cycle ${esc(x.cycle)}</small>${x.notes?`<p>${esc(x.notes)}</p>`:''}</div>`).join('');
  }
  function renderRepairs(repairs) {
    if(!repairs.length)return '<p class="muted">No repair cycles recorded.</p>';
    return `<h3 style="font-size:14px;margin-top:18px">Repair cycles</h3>${repairs.map(r=>`<div class="ft-history"><strong>Repair · cycle ${esc(r.cycle??r.to_cycle??'')}</strong><p>${esc(r.reason||'')}</p><small>${esc(r.actor||r.opened_by||'')} · ${stamp(r.at||r.opened_at)}</small></div>`).join('')}`;
  }
  function renderHolds(holds) {
    if(!holds.length)return '<p class="muted">No holds recorded.</p>';
    return holds.map(h=>`<div class="ft-history"><strong>${closedHold(h)?'Closed hold':'Open hold'}</strong> ${badge(closedHold(h)?'closed':'open')}<p>${esc(h.reason)}</p><small>${esc(h.actor||h.opened_by||'')} · ${stamp(h.at||h.opened_at)}</small>${h.closed_at?`<small>Closed ${stamp(h.closed_at)} · ${esc(h.closed_by||'')}</small>`:''}${h.close_notes||h.notes?`<p>${esc(h.close_notes||h.notes)}</p>`:''}${!closedHold(h)&&review()&&!isLocked()?btn('close-hold','Close hold',h.id):''}</div>`).join('');
  }
  function renderAudit(history) {
    if(!history.length)return '<p class="muted">No tracking events recorded yet.</p>';
    return history.map(x=>`<div class="ft-history"><strong>${esc(String(x.event||'Update').replace(/_/g,' '))}</strong><small>${esc(x.actor)} · ${stamp(x.at)}</small>${x.details?`<details class="ft-fold"><summary>Recorded details</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px">${esc(JSON.stringify(x.details,null,2))}</pre></details>`:''}</div>`).join('');
  }

  function dialog(title,html,action,buttonLabel='Save') {
    node('trackingDialogTitle').textContent=title;
    node('trackingDialogFields').innerHTML=html;
    node('trackingDialogError').classList.add('hidden');
    node('trackingDialogError').textContent='';
    node('trackingDialogSubmit').textContent=buttonLabel;
    node('trackingDialogSubmit').disabled=false;
    state.dialogStale=false;
    state.dialogAction=action;
    node('trackingDialog').showModal();
  }
  function grid(html) {return `<div class="ft-form-grid">${html}</div>`}
  async function processAction(action) {
    if(state.processDialogLoading)return;
    const spool=state.spool, process=spool?.production_process, sequence=state.sequence;
    const flowPause=process?.flow_managed&&process.flow_status==='active'&&['pause','resume'].includes(action);
    if(!processAllowed(action,process)||isLocked()&&!flowPause)throw Error('Your job position cannot change this process.');
    if(process?.flow_managed&&!flowPause)throw Error('Use Process flow to complete the numbered step and change its process.');
    if(!process)throw Error('Refresh the spool to load its current process timing.');
    const selecting=action==='start'||action==='move';
    state.processDialogLoading=true;
    try{
      const choices=arr(process.permissions?.allowed_processes);
      if(selecting&&!choices.length)throw Error('Your position has no permitted destination process.');
      if(sequence!==state.sequence||state.spool?.item?.id!==spool.item.id)return;
      const titles={start:'Start production process',move:'Move to next process',pause:'Pause process / record delay',resume:'Resume process',finish:'Finish process'};
      const buttons={start:'Start process',move:'Move & start next process',pause:'Pause process',resume:'Resume process',finish:'Finish process'};
      const notes={start:'The server records the start time when you save.',move:'Moving closes the current visit and starts the next process at the same time.',pause:'Elapsed time keeps counting during a pause. Record what is delaying the spool.',resume:'Running time resumes when you save. The recorded pause stays in the history.',finish:'Finish when the spool leaves this process. Timing stays stopped until another process starts.'};
      let html=`<p><strong>${itemText(spool.item)}</strong>${process.current?' · '+esc(process.current.process_name):''}</p><div class="notice">${notes[action]}</div>`;
      if(selecting)html+=grid(field('process_key','Production process','',{required:true,options:[['','Select process'],...choices.filter(x=>action!=='move'||x.key==='custom'||x.key!==process.current?.process_key).map(x=>[x.key,x.label])]}))+`<div id="ftProcessCustom" class="hidden">${field('process_name','Custom process name','',{maxlength:80,minlength:2,disabled:true,help:'Use the same name for repeat visits so their times add together.'})}</div>`;
      html+=grid(field('notes',action==='pause'?'Delay reason':'Notes / work center (optional)','',{required:action==='pause',type:'textarea',full:true,maxlength:2000,help:action==='pause'?'For example: waiting for material, inspector, equipment, or another crew.':''}));
      dialog(titles[action],html,async data=>{
        const payload={action,expected_version:process.version,notes:String(data.notes||'').trim()};
        if(action==='pause'&&payload.notes.length<3)throw Error('Enter a delay reason of at least 3 characters.');
        if(selecting){
          if(!choices.some(choice=>choice.key===data.process_key))throw Error('Choose a process permitted for your position.');
          payload.process_key=data.process_key;
          if(data.process_key==='custom'){
            payload.process_name=String(data.process_name||'').trim();
            if(payload.process_name.length<2)throw Error('Enter a custom process name of at least 2 characters.');
          }
        }
        try{
          const result=await request('/spools/'+encode(spool.item.id)+'/process','POST',payload);
          if(state.spool?.item?.id===spool.item.id){state.spool.production_process=result;markProcessClock(result);}
        }catch(error){
          if(error.status===409){
            state.dialogStale=true;state.dialogAction=null;
            await refresh();
            throw Error(errorText(error)+' The spool has been refreshed. Close this dialog and choose the process action again.');
          }
          throw error;
        }
      },buttons[action]);
      if(selecting)node('ft-field-process_key').onchange=()=>{
        const custom=node('ft-field-process_key').value==='custom', input=node('ft-field-process_name');
        node('ftProcessCustom').classList.toggle('hidden',!custom);input.required=custom;input.disabled=!custom;
        if(custom)input.focus();
      };
    }finally{state.processDialogLoading=false;}
  }
  function newProject() {
    dialog('Create project',grid(field('id','Project ID','',{required:true,maxlength:80,help:'Use a permanent identifier for this job.'})+field('name','Project name','',{required:true,maxlength:200})+field('client','Client','',{maxlength:200})+field('description','Description','',{type:'textarea',full:true})),async data=>{const p=await request('/projects','POST',data);state.project=p.id||data.id;state.subproject='';state.view='overview';state.spool=null;state.weld=null});
  }
  function newSubproject() {
    if(!arr(state.overview?.projects).length)return newProject();
    dialog('Create subproject / work package',grid(field('project_id','Project',state.project,{required:true,options:arr(state.overview.projects).map(p=>[p.id,`${p.id} · ${p.name}`])})+field('id','Subproject ID','',{required:true,maxlength:80})+field('name','Subproject name','',{required:true,maxlength:200})+field('description','Scope / description','',{type:'textarea',full:true})),data=>request('/subprojects','POST',data));
  }
  function planSpool(prefill={}) {
    if(!arr(state.overview?.projects).length)return newProject();
    const existing=state.spool?.plan, item=state.spool?.item, registeredParent=state.spool?.registered_assembly_id||'';
    const project=existing?.project_id||prefill.project||state.project||arr(state.overview.projects)[0]?.id||'';
    const suboptions = projectId => [['','No subproject'],...arr(state.overview.subprojects).filter(s=>s.project_id===projectId).map(s=>[s.id,`${s.id} · ${s.name}`])];
    let html=registeredParent?'<p class="ft-required-note">This spool is registered to its purchase-order assembly. Confirm its drawing and actual weld scope before starting fabrication.</p>':'<p class="ft-required-note">Assign an existing item to a project and define its weld plan. Create a new item from the Items screen first if it is not registered.</p>';
    if(item?.welds_done&&!existing)html+='<div class="notice">This item has aggregate weld history. Defining individual joints does not certify those historical welds; record and review each joint before individual QA acceptance.</div>';
    html+=grid(field('item_id','Existing item / spool ID',item?.id||'',{required:true,disabled:Boolean(item),maxlength:60})+field('project_id','Project',project,{required:true,options:arr(state.overview.projects).map(p=>[p.id,`${p.id} · ${p.name}`])})+field('subproject_id','Subproject / work package',existing?.subproject_id||state.subproject,{options:suboptions(project)})+field('assembly_id',registeredParent?'Assigned assembly ID':'Existing assembly ID (optional)',registeredParent||(prefill.assembly_id??existing?.assembly_id??''),{maxlength:60,readonly:Boolean(registeredParent),help:registeredParent?'Assigned by the P.O. and preserved for this physical spool.':'Must identify an existing item whose type is Assembly.'})+field('planned_welds','Planned individual welds',existing?.planned_welds??(registeredParent?'':item?.welds_required??0),{required:true,type:'number',min:0,max:10000,step:1})+field('drawing_revision','Drawing / revision',existing?.drawing_revision||item?.drawing||'',{maxlength:80})+field('due_date','Target completion date',existing?.due_date||'',{type:'date'})+field('zero_weld_reason','Reason if planned welds is zero',existing?.zero_weld_reason||'',{maxlength:1000})+field('notes','Planning notes',existing?.notes||'',{type:'textarea',full:true}));
    dialog(existing?'Edit spool plan':'Set up spool tracking',html,async data=>{
      const itemId=item?.id||data.item_id.trim();
      const planned=Number(data.planned_welds);
      if(!Number.isInteger(planned)||planned<0)throw Error('Planned welds must be a whole number of zero or more.');
      if(planned===0&&!data.zero_weld_reason.trim())throw Error('Explain why this spool has no planned welds.');
      const payload={...data,planned_welds:planned,subproject_id:data.subproject_id||null,assembly_id:data.assembly_id||null,due_date:data.due_date||null};
      delete payload.item_id;
      if(existing)payload.expected_version=existing.version;
      const result=await request('/spools/'+encode(itemId)+'/plan','POST',payload);
      state.spool=result;state.weld=null;state.view='spool';
    });
    node('ft-field-project_id').onchange=e=>{node('ft-field-subproject_id').innerHTML=suboptions(e.target.value).map(x=>option(x[0],x[1])).join('')};
  }
  function weldForm(edit=false) {
    const w=edit?state.weld:{};
    const existingNumbers=new Set(arr(state.spool.welds).map(weld=>weld.number));
    let n=1;while(existingNumbers.has(`W${String(n).padStart(2,'0')}`))n++;
    let html=grid((edit?'':field('number','Weld / joint number',`W${String(n).padStart(2,'0')}`,{required:true,maxlength:80}))+field('description','Joint description / location',w.description||'',{maxlength:500})+field('joint_type','Joint type',w.joint_type||'',{options:[['','Select joint type'],['BW','BW · Butt weld'],['SW','SW · Socket weld'],['BRANCH','Branch weld'],['FILLET','Fillet weld'],['OTHER','Other weld']]})+field('size','Nominal size',w.size||'',{maxlength:80,help:'Include units, for example 4 in.'})+field('wall_thickness','Wall thickness / schedule',w.wall_thickness||'',{maxlength:80})+field('drawing_revision','Drawing / revision',w.drawing_revision||state.spool.plan?.drawing_revision||'',{maxlength:80})+'<h3>Procedure</h3>'+field('wps','WPS ID',w.wps||'',{maxlength:160})+field('wps_revision','WPS revision',w.wps_revision||'',{maxlength:80})+'<h3>Material side A</h3>'+field('component_a','Component / BOM piece A',w.component_a||'',{maxlength:160})+field('heat_a','Heat number A (due at QA/QC-003)',w.heat_a||'',{maxlength:160,help:'Optional through step 14 — Complete Welds. Enter the actual heat number before step 15 — QA/QC-003 - Inspect Welds.'})+field('mtr_a','MTR reference A (due at QA/QC-003)',w.mtr_a||'',{maxlength:300,full:true,help:'Optional through step 14 — Complete Welds. Enter the actual MTR reference before step 15 — QA/QC-003 - Inspect Welds.'})+'<h3>Material side B</h3>'+field('component_b','Component / BOM piece B',w.component_b||'',{maxlength:160})+field('heat_b','Heat number B (due at QA/QC-003)',w.heat_b||'',{maxlength:160,help:'Optional through step 14 — Complete Welds. Enter the actual heat number before step 15 — QA/QC-003 - Inspect Welds.'})+field('mtr_b','MTR reference B (due at QA/QC-003)',w.mtr_b||'',{maxlength:300,full:true,help:'Optional through step 14 — Complete Welds. Enter the actual MTR reference before step 15 — QA/QC-003 - Inspect Welds.'})+(!edit?'<h3>Requirements</h3>'+field('template_id','Requirement template','',{full:true,options:[['','Baseline checklist'],...arr(state.overview.templates).map(t=>[t.id,`${t.name} · Rev ${t.revision}`])],help:'Exact NDE methods and additional job requirements can be added individually.'}):''));
    const ops=arr(w.required_operations).length?w.required_operations:['root','fill_cap'];
    html+='<h3>Required production operations</h3><p class="ft-help">Select the actual production sequence for this joint. A single-pass joint can use fill / cap only.</p>'+check('operation_root','Root must be recorded.',ops.includes('root'))+check('operation_fill_cap','Fill / cap must be recorded.',ops.includes('fill_cap'));
    if(edit)html='<div class="notice">Joint number remains unchanged. Traceability or procedure changes reopen requirements for review. Changing required production operations starts a new work cycle.</div>'+html+grid(field('change_reason','Reason for this controlled correction','',{required:true,type:'textarea',full:true,maxlength:3000}));
    dialog(edit?'Edit individual weld':'Add individual weld',html,async data=>{
      const operations=[];if(data.operation_root==='on')operations.push('root');if(data.operation_fill_cap==='on')operations.push('fill_cap');
      if(!operations.length)throw Error('Select at least one required production operation.');
      data.required_operations=operations;delete data.operation_root;delete data.operation_fill_cap;
      if(edit) await request('/welds/'+encode(w.id),'PATCH',{...data,expected_version:w.version});
      else {const result=await request('/spools/'+encode(state.spool.item.id)+'/welds','POST',{...data,template_id:data.template_id||null});state.weld=result;state.view='weld'}
    });
    if(!edit)node('ft-field-template_id').onchange=event=>{
      const template=arr(state.overview.templates).find(t=>String(t.id)===event.target.value);
      const operations=arr(template?.required_operations).length?template.required_operations:['root','fill_cap'];
      node('ft-check-operation_root').checked=operations.includes('root');node('ft-check-operation_fill_cap').checked=operations.includes('fill_cap');
    };
  }
  function requirementDefinitionFields(value={},prefix='') {
    const name=key=>prefix+key;
    return field(name('code'),'Requirement code',value.code||'',{required:true,maxlength:80})+field(name('label'),'Requirement name',value.label||'',{required:true,maxlength:200})+field(name('stage'),'Approval stage',value.stage||'after_welding',{options:Object.entries(stageNames)})+field(name('owner_role'),'Responsible role',value.owner_role||'inspector',{options:(window.FabPermissions?.roles()||[]).map(role=>[role.id,role.label])})+field(name('check'),'Record prerequisite',value.check||'none',{options:[['none','Evidence / review only'],['materials','Both material sides must be identified'],['procedure','WPS and revision must be recorded'],['welding_complete','Weld must be complete']]})+field(name('source'),'Requirement / acceptance source',value.source||'',{maxlength:1000,help:'Code, contract, WPS, inspection plan, or approved procedure reference.',full:true});
  }
  function newRequirement() {
    dialog(state.weld?'Add weld requirement':'Add spool requirement',grid(requirementDefinitionFields())+check('evidence_required','Evidence is required before acceptance.',true)+check('allow_na','Allow an inspector or administrator to approve a justified not-applicable decision.'),data=>{
      const payload={...data,evidence_required:data.evidence_required==='on',allow_na:data.allow_na==='on'};
      const path=state.weld?'/welds/'+encode(state.weld.id):'/spools/'+encode(state.spool.item.id);
      return request(path+'/requirements','POST',payload);
    });
    if(!state.weld)node('ft-field-check').innerHTML=option('none','Evidence / review only')+option('welding_complete','All planned spool welds must be complete');
  }
  function recordEvidence(id) {
    const r=findRequirement(id);if(!r)throw Error('Requirement not found. Refresh the record.');
    if(isLocked()||r.permissions?.can_submit_evidence!==true)throw Error('Your job position cannot submit this requirement’s evidence.');
    dialog('Record evidence · '+r.label,'<div class="notice">Saving evidence records the result for review. It does not accept the requirement or release the weld.</div>'+grid(field('reference','Report / record reference','',{required:true,minlength:2,maxlength:500,full:true,help:'Enter an identifiable report reference or an http(s) link.'})+field('result','Recorded result','recorded',{options:[['recorded','Recorded / no pass-fail result'],['pass','Pass'],['fail','Fail']]})+field('notes','Measurements, findings, or evidence notes','',{type:'textarea',full:true})),data=>request('/requirements/'+encode(r.id)+'/evidence','POST',{...data,expected_version:r.version}),'Submit evidence');
  }
  function reviewRequirement(id,decision) {
    const r=findRequirement(id);if(!r)throw Error('Requirement not found. Refresh the record.');
    if(isLocked()||r.permissions?.can_review!==true)throw Error('QA/QC permission is required to review this requirement.');
    const title=decision==='accepted'?'Accept requirement':decision==='rejected'?'Reject requirement':'Approve not applicable';
    dialog(title+' · '+r.label,`<p>${esc(r.source||'Review the applicable project requirements and supporting evidence.')}</p>`+grid(field('notes',decision==='not_applicable'?'Justification and authorization reference':'Review notes / approval reference','',{required:true,type:'textarea',full:true})),data=>request('/requirements/'+encode(r.id)+'/review','POST',{...data,decision,expected_version:r.version}),title);
  }
  function work(operation) {
    if(isLocked()||!operationAllowed(operation))throw Error('Your job position cannot record this welding operation.');
    dialog(operationNames[operation]||'Record work',`<p><strong>${esc(state.weld.number)}</strong> · ${esc(me.name)} (${esc(me.badge)})</p>`+grid(field('notes','Work notes / traveler reference','',{type:'textarea',full:true})),data=>request('/welds/'+encode(state.weld.id)+'/work','POST',{...data,operation}),'Record work');
  }
  function newHold() {
    dialog(state.weld?'Place hold on weld':'Place hold on spool',grid(field('reason','Hold reason / required resolution','',{required:true,type:'textarea',full:true})),data=>request('/spools/'+encode(state.spool.item.id)+'/holds','POST',{...data,weld_id:state.weld?.id||null}),'Place hold');
  }
  function closeHold(id) {
    dialog('Close hold',grid(field('notes','Resolution and authorization reference','',{required:true,type:'textarea',full:true})),data=>request('/holds/'+encode(id)+'/close','POST',data),'Close hold');
  }
  function repair() {
    dialog('Open a repair cycle','<div class="notice">The joint keeps its identity. Previous work and evidence remain in history, and a new work cycle requires fresh production records and requirement reviews.</div>'+grid(field('reason','Defect / repair reason / NCR reference','',{required:true,type:'textarea',full:true})),data=>request('/welds/'+encode(state.weld.id)+'/repairs','POST',data),'Open repair cycle');
  }
  function dimensional() {
    dialog('Record spool dimensional inspection',grid(field('result','Inspection result','Pass',{options:['Pass','Fail']})+field('report','Report / traveler reference','',{required:true})+field('measurements','Actual dimensions, tolerances, findings, and instrument references','',{required:true,type:'textarea',full:true})),data=>api('/api/items/'+encode(state.spool.item.id)+'/inspect',{method:'POST',body:JSON.stringify({...data,kind:'Dimensional'})}),'Record inspection');
  }
  function releaseSpool() {
    const blockers=arr(state.spool.summary?.blockers);
    dialog('Approve spool final release',`<div class="notice">The server verifies individual weld acceptance, configured requirements, holds, and spool inspections before approving release.</div>${blockers.length?`<div class="notice danger"><strong>Current outstanding checks</strong><ul>${blockers.map(b=>`<li>${esc(b)}</li>`).join('')}</ul></div>`:''}`+grid(field('reference','Final release / approval reference','',{required:true,full:true})),data=>api('/api/items/'+encode(state.spool.item.id)+'/release',{method:'POST',body:JSON.stringify(data)}),'Approve final release');
  }
  function reopenSpool() {
    dialog('Reopen released spool','<div class="notice danger">Reopening removes the final release and invalidates prior item inspections. The change is recorded in audit history.</div>'+check('confirm','I intend to reopen this released spool.'),async data=>{if(data.confirm!=='on')throw Error('Confirm that this spool should be reopened.');await api('/api/items/'+encode(state.spool.item.id)+'/reopen',{method:'POST'})},'Reopen spool');
  }
  function templateForm(template=null) {
    const original=template?arr(template.requirements):[];
    let counter=0;
    const ops=arr(template?.required_operations).length?template.required_operations:['root','fill_cap'];
    let html='<p class="ft-required-note">Each saved revision is immutable. The six baseline material, procedure, fit-up, visual, NDE-plan, and QA controls are always included. Add job-specific requirements below. Reusing a baseline code can customize its label and source; it cannot remove its core checks.</p>'+grid(field('code','Template code',template?.code||'',{required:true,maxlength:80})+field('name','Template name',template?.name||'',{required:true,maxlength:200})+field('revision','Revision',template?number(template.revision)+1:1,{required:true,type:'number',min:1,step:1})+field('source','Overall specification / inspection plan',template?.source||'',{maxlength:1000}))+check('operation_root','Root work is required.',ops.includes('root'))+check('operation_fill_cap','Fill / cap work is required.',ops.includes('fill_cap'))+`<div id="ftTemplateRows"></div><button type="button" id="ftAddTemplateRequirement">Add requirement</button>`;
    dialog(template?'Create next template revision':'Create requirement template',html,async data=>{
      const rows=[...node('ftTemplateRows').querySelectorAll('[data-template-row]')];
      if(!rows.length)throw Error('Add at least one requirement.');
      const requirements=rows.map(row=>{
        const p=row.dataset.templateRow, get=key=>data[p+key]||'';
        return {code:get('code'),label:get('label'),stage:get('stage'),owner_role:get('owner_role'),check:get('check'),source:get('source'),evidence_required:get('evidence_required')==='on',allow_na:get('allow_na')==='on'};
      });
      const revision=Number(data.revision);if(!Number.isInteger(revision)||revision<1)throw Error('Revision must be a positive whole number.');
      const required_operations=[];if(data.operation_root==='on')required_operations.push('root');if(data.operation_fill_cap==='on')required_operations.push('fill_cap');
      if(!required_operations.length)throw Error('Select at least one required production operation.');
      await request('/templates','POST',{code:data.code,name:data.name,revision,source:data.source,requirements,required_operations});
    },'Save template revision');
    function addRow(value={}) {
      const prefix=`req${++counter}_`;
      const holder=document.createElement('div');holder.className='ft-template-row';holder.dataset.templateRow=prefix;
      holder.innerHTML=`<div class="row"><h3>Requirement</h3><button type="button" data-remove-template>Remove</button></div>`+grid(requirementDefinitionFields(value,prefix))+check(prefix+'evidence_required','Evidence required',value.evidence_required!==false)+check(prefix+'allow_na','Allow justified not-applicable review',Boolean(value.allow_na));
      holder.querySelector('[data-remove-template]').onclick=()=>holder.remove();
      node('ftTemplateRows').append(holder);
    }
    node('ftAddTemplateRequirement').onclick=()=>addRow();
    if(original.length)original.forEach(addRow);else addRow();
  }

  async function act(action,id) {
    if(['new-project','new-subproject','plan-spool','edit-plan','new-weld','edit-weld','new-requirement','new-template','copy-template'].includes(action)&&!manage())throw Error('Production planning permission is required.');
    if(['new-hold','repair'].includes(action)&&!holdRole())throw Error('Your position cannot open a hold or repair.');
    if(['close-hold','dimensional','release'].includes(action)&&!review())throw Error('QA/QC permission is required.');
    if(['reopen','admin-controls'].includes(action)&&!capability('admin'))throw Error('Administrator permission is required.');
    if(action==='process-flow')return window.FabFlow.open({item:id||state.spool?.item?.id});
    if(action==='spool-parts')return window.FabParts.open({spool:id||state.spool?.item?.id,project:state.spool?.plan?.project_id||state.project});
    if(['process-start','process-move','process-pause','process-resume','process-finish'].includes(action))return processAction(action.slice(8));
    if(action==='overview')return open({project:state.project,subproject:state.subproject});
    if(action==='refresh'||action==='retry')return refresh();
    if(action==='view'){state.view=id;state.spool=null;state.weld=null;state.routeSpool='';state.routeWeld='';return load()}
    if(action==='select-project'){state.project=id;state.subproject='';state.view='spools';return load()}
    if(action==='select-subproject'){state.subproject=id;const sub=arr(state.overview.subprojects).find(s=>s.id===id);if(sub)state.project=sub.project_id;state.view='spools';return load()}
    if(action==='open-spool')return open({spool:id});
    if(action==='open-weld')return open({weld:id,spool:state.spool?.item?.id});
    if(action==='back-spool')return open({spool:state.spool.item.id});
    if(action==='item-record')return openItem(id);
    if(action==='purchase-orders'&&manage()&&window.FabOrders)return window.FabOrders.open({create:true});
    if(action==='new-project')return newProject();
    if(action==='new-subproject')return newSubproject();
    if(action==='plan-spool'){state.spool=null;state.weld=null;return planSpool()}
    if(action==='edit-plan')return planSpool();
    if(action==='new-weld')return weldForm();
    if(action==='edit-weld')return weldForm(true);
    if(action==='new-requirement')return newRequirement();
    if(action==='evidence')return recordEvidence(id);
    if(action==='review-accept')return reviewRequirement(id,'accepted');
    if(action==='review-reject')return reviewRequirement(id,'rejected');
    if(action==='review-na')return reviewRequirement(id,'not_applicable');
    if(action==='work')return work(id);
    if(action==='new-hold')return newHold();
    if(action==='close-hold')return closeHold(id);
    if(action==='repair')return repair();
    if(action==='dimensional')return dimensional();
    if(action==='admin-controls'&&capability('admin'))return window.FabAdmin.open({item:id||state.spool.item.id});
    if(action==='release')return releaseSpool();
    if(action==='reopen')return reopenSpool();
    if(action==='new-template')return templateForm();
    if(action==='copy-template')return templateForm(arr(state.overview.templates).find(t=>String(t.id)===String(id)));
  }
  node('trackingContent').addEventListener('click',async event=>{
    const control=event.target.closest('[data-ft-action]');if(!control||control.disabled)return;
    try {await act(control.dataset.ftAction,control.dataset.ftId)}catch(error){notify(errorText(error))}
  });
  node('trackingDialogForm').addEventListener('submit',async event=>{
    event.preventDefault();
    if(!state.dialogAction||node('trackingDialogSubmit').disabled)return;
    const data=Object.fromEntries(new FormData(event.target));
    node('trackingDialogSubmit').disabled=true;
    node('trackingDialogError').classList.add('hidden');
    try {
      await state.dialogAction(data);
      node('trackingDialog').close();
      notify('Tracking record saved.');
      await refresh();
    }catch(error){
      node('trackingDialogError').textContent=errorText(error);
      node('trackingDialogError').classList.remove('hidden');
      node('trackingDialogError').scrollIntoView({block:'nearest'});
    }finally{node('trackingDialogSubmit').disabled=state.dialogStale}
  });
  node('trackingDialogClose').onclick=()=>node('trackingDialog').close();
  node('trackingDialogCancel').onclick=()=>node('trackingDialog').close();
  node('navTracking').onclick=()=>open({view:'overview'});
  node('itemTrackingBtn').onclick=()=>{if(current)open({spool:current.id})};
  async function openPlan(options={}){
    if(!manage())throw Error('Production planning permission is required.');
    state.overview=null;await open({project:options.project||'',subproject:'',spool:options.item_id||'',view:'spools',resetFilters:true});
    if(!state.overview)return;
    if(options.item_id&&state.spool?.item?.id!==options.item_id)return;
    if(state.spool?.item?.released)throw Error('Released items must be returned to work through the existing controlled process before editing their plan.');
    if(options.assembly_id&&state.spool?.item?.kind!=='Spool')throw Error('Select a physical Spool record to link to the assembly.');
    if(options.project&&state.spool?.plan?.project_id&&state.spool.plan.project_id!==options.project)throw Error('This spool belongs to a different project.');
    return planSpool({project:options.project,assembly_id:options.assembly_id});
  }
  window.FabTracking={open,openPlan,refresh,cancelPending(){state.sequence++;cancelRead();stopProcessClock()}};
})();
