/* Expandable, read-only P.O. progress derived from the recorded production flow. */
(() => {
  'use strict';
  const ROOT='/api/progress/orders',node=id=>document.getElementById(id),text=v=>String(v??''),arr=v=>Array.isArray(v)?v:[],enc=encodeURIComponent;
  const state={active:false,sequence:0,loading:false,project:'',choices:[],data:null,error:'',status:'all',kind:'all',query:'',expanded:new Set(),autoOpen:true};
  const flowStatus=()=>window.FabFlowStatus;
  const stageText=(value,label,tag='span')=>flowStatus()?.stationText(value,label,tag)||`<${tag}>${esc(label)}</${tag}>`;
  const stageBadge=value=>flowStatus()?.badge(value)||'';
  const spoolNumber=value=>flowStatus()?.spoolNumber?.(value)||value.qr_alias||value.spool_number||value.part_number||value.id;
  const spoolText=(value,label=spoolNumber(value),tag='span')=>flowStatus()?.spoolText?.(value,label,tag)||`<${tag}>${esc(label)}</${tag}>`;
  const stepNames={completed:'Recorded',current:'Current step',pending:'Pending',not_recorded:'Earlier step not recorded'};
  const stageNames={completed:'Recorded',current:'In progress',pending:'Pending',not_recorded:'History incomplete',scope_unknown:'Scope not declared',not_applicable:'Outside this route'};
  const button=(action,label,id='',project='',cls='')=>`<button type="button" class="${esc(cls)}" data-pp-action="${esc(action)}" data-pp-id="${esc(id)}" data-pp-project="${esc(project)}">${esc(label)}</button>`;
  const option=(value,label,current)=>`<option value="${esc(value)}"${text(value)===text(current)?' selected':''}>${esc(label)}</option>`;
  const finite=v=>typeof v==='number'&&Number.isFinite(v),quantity=v=>Number.isInteger(v)&&v>=0?v:0;
  const percent=v=>finite(v)?Math.max(0,Math.min(100,v)):null;
  const number=v=>percent(v)===null?'—':percent(v).toFixed(percent(v)%1?1:0)+'%';
  const kind=n=>n.route==='component'?'part':n.route==='assembly'?'assembly':'spool';
  const label=n=>kind(n)==='part'?'Part':kind(n)==='assembly'?'Assembly':'Spool';
  const finishedLabel=n=>kind(n)==='part'?'Prepared':kind(n)==='spool'?'Fabrication finished':'Finished';
  const statusLabel=n=>n.on_hold?'On hold':n.status==='delivered'?'Delivered':n.status==='shipped'?'Shipped':n.fabrication_finished?finishedLabel(n):'WIP';
  const isFiltered=()=>state.query.trim()||state.status!=='all'||state.kind!=='all';
  function errorText(error){try{const d=JSON.parse(error.message);if(d.message)return d.message;}catch(_){}return text(error.message||'Production progress could not be loaded.');}
  function key(kind,id){return kind+':'+id;}
  function opened(k,force=false){return force||state.expanded.has(k)?' open':'';}
  function ownProgress(n){return {completed:n.progress?.completed,total:n.progress?.total,not_recorded:n.progress?.not_recorded,percent:n.progress?.percent};}
  function overallProgress(s){return {completed:s?.completed_steps,total:s?.total_steps,not_recorded:s?.not_recorded_steps,percent:s?.percent};}
  function meter(p,title,complete=false,small=false){
    const pct=percent(p?.percent),total=quantity(p?.total),done=quantity(p?.completed),unrecorded=quantity(p?.not_recorded);
    return `<div class="pp-meter${small?' pp-meter-small':''}${complete&&pct===100?' pp-meter-complete':''}"><div class="pp-meter-heading"><span>${esc(title)}</span><strong>${number(pct)}</strong></div>${pct===null?'<div class="pp-empty-meter" aria-label="Progress is not yet known"></div>':`<progress max="100" value="${pct}" aria-label="${esc(title)}">${number(pct)}</progress>`}<small>${total?`${done} of ${total} recorded steps`:'No registered production steps'}${unrecorded?` · ${unrecorded} earlier step${unrecorded===1?'':'s'} not recorded`:''}</small></div>`;
  }
  function summaryBadges(s){
    let html=`<span>${quantity(s?.spools)} spool${quantity(s?.spools)===1?'':'s'}</span><span>${quantity(s?.parts)} part${quantity(s?.parts)===1?'':'s'}</span>`;
    if(quantity(s?.missing_assemblies))html+=`<span class="pp-warning">${quantity(s.missing_assemblies)} assembl${s.missing_assemblies===1?'y':'ies'} still to register</span>`;
    if(quantity(s?.missing_spools))html+=`<span class="pp-warning">${quantity(s.missing_spools)} spool${s.missing_spools===1?'':'s'} still to link</span>`;
    if(quantity(s?.missing_parts))html+=`<span class="pp-warning">${quantity(s.missing_parts)} part${s.missing_parts===1?'':'s'} still to assign</span>`;
    if(s?.scope_complete===false)html+='<span class="pp-warning">Scope incomplete</span>';
    if(quantity(s?.on_hold))html+=`<span class="pp-hold">${quantity(s.on_hold)} on hold</span>`;
    return `<div class="pp-badges">${html}</div>`;
  }
  function notes(warnings,summary){
    const list=[...new Set(arr(warnings).filter(v=>typeof v==='string'))];
    if(summary?.scope_complete===false&&!list.length)list.push('Required scope is incomplete. Registered progress does not include every required physical item yet.');
    return list.length?`<div class="pp-scope-note"><strong>Scope needs attention</strong><ul>${list.map(v=>`<li>${esc(v)}</li>`).join('')}</ul></div>`:'';
  }
  function stageStrip(stages,title='Flow progress',current=null){
    const active=flowStatus()?.normalize(current);
    const card=(s,index)=>`<li class="pp-stage pp-stage-${esc(s.state)}${active?.key===s.key?' pp-stage-effective-current':''}" data-pp-stage="${esc(s.key)}"${active?.key===s.key?' aria-current="step"':''}><div><strong><span class="pp-stage-sequence">${index+1}</span>${stageText(s,s.label)}</strong><span>${active?.key===s.key?'Current part status':esc(stageNames[s.state]||'Pending')}</span></div>${s.state==='not_applicable'?'<small>No steps on this route</small>':`${meter({completed:s.completed,total:s.total,not_recorded:s.not_recorded,percent:s.percent},s.label,false,true)}`}${quantity(s.missing_records)?`<small class="pp-stage-missing">${quantity(s.missing_records)} required item${s.missing_records===1?'':'s'} still to register</small>`:''}${s.separate?'<small class="pp-shipping-note">Shipment recorded separately</small>':''}</li>`;
    return `<section class="pp-stage-section"><h3>${esc(title)}</h3><ol class="pp-stage-grid">${arr(stages).map(card).join('')}</ol></section>`;
  }
  function itemStages(n){
    return arr(state.data?.stage_catalog).map(s=>{const steps=arr(n.steps).filter(x=>arr(s.steps).includes(x.number));const completed=steps.filter(x=>x.state==='completed').length,current=steps.filter(x=>x.state==='current').length,not_recorded=steps.filter(x=>x.state==='not_recorded').length;return {...s,total:steps.length,completed,current,not_recorded,percent:steps.length?completed/steps.length*100:null,state:!steps.length?'not_applicable':completed===steps.length?'completed':current?'current':not_recorded===steps.length?'not_recorded':'pending'};});
  }
  function searchMatch(values){const q=state.query.trim().toLowerCase();return !q||values.some(v=>text(v).toLowerCase().includes(q));}
  function ownMatch(n){return (state.kind==='all'||kind(n)===state.kind)&&(state.status==='all'||state.status==='hold'&&n.on_hold||state.status==='finished'&&n.fabrication_finished||state.status==='wip'&&!n.fabrication_finished);}
  function filterItem(n,inherited=false){
    const matched=inherited||searchMatch([n.id,n.spool_number,n.google_part_number,n.part_number,n.qr_alias,n.display_code,n.flow_stage?.label,n.current_title,n.location,n.handler,n.handler_name]);
    const children=arr(n.children).map(c=>filterItem(c,matched)).filter(Boolean);
    const own=matched&&ownMatch(n);
    return own||children.length?{...n,children,_context:!own}:null;
  }
  function filteredOrders(){return arr(state.data?.orders).map(o=>{
    const matched=searchMatch([o.project_id,o.purchase_order,o.customer]);
    const gpns=arr(o.gpns).map(g=>{const groupMatch=matched||searchMatch([g.id,g.assembly_number,g.gpn]);const assemblies=arr(g.assemblies).map(n=>filterItem(n,groupMatch)).filter(Boolean);const draft=groupMatch&&(g.setup_needed||g.registration_needed||g.quantity_plan&&!arr(g.assemblies).length)&&state.kind==='all'&&['all','wip'].includes(state.status);return assemblies.length||draft?{...g,assemblies,_assembly_count:g.assemblies.length}:null;}).filter(Boolean);
    const unassigned=arr(o.unassigned).map(n=>filterItem(n,matched)).filter(Boolean);
    const empty=matched&&!arr(o.gpns).length&&!arr(o.unassigned).length&&state.kind==='all'&&['all','wip'].includes(state.status);
    return gpns.length||unassigned.length||empty?{...o,gpns,unassigned}:null;
  }).filter(Boolean);}
  function processSpools(orders){
    const copies=new Map();
    const visit=(n,context)=>{
      const scope=n.route==='assembly'?{...context,assembly_id:n.id}:context;
      if(n.route==='spool'&&!n._context&&!copies.has(n.id))copies.set(n.id,{...n,...scope,item_id:n.id});
      arr(n.children).forEach(child=>visit(child,scope));
    };
    for(const order of orders){
      const context={project_id:order.project_id,purchase_order:order.purchase_order};
      for(const group of order.gpns)for(const assembly of group.assemblies)visit(assembly,{...context,gpn:group.gpn,assembly_number:group.assembly_number||''});
      order.unassigned.forEach(item=>visit(item,context));
    }
    return [...copies.values()];
  }
  function expandFiltered(){
    if(!isFiltered())return;
    const parent=n=>{if(arr(n.children).length){state.expanded.add(key('item',n.id));n.children.forEach(parent);}};
    for(const o of filteredOrders()){state.expanded.add(key('order',o.project_id));for(const g of o.gpns){state.expanded.add(key('gpn',g.id));g.assemblies.forEach(parent);}o.unassigned.forEach(parent);}
  }
  function stepList(n){
    const k=key('steps',n.id);
    return `<details class="pp-step-details" data-pp-expand="${esc(k)}"${opened(k)}><summary>Numbered steps for this ${label(n).toLowerCase()} (${quantity(n.progress?.completed)} recorded)</summary><ol class="pp-numbered-steps">${arr(n.steps).map(s=>`<li class="pp-step-${esc(s.state)}"><span class="pp-step-number">${s.number}</span><div><strong>${esc(s.title)}${s.qa?'<span class="pp-qa">QA/QC</span>':''}</strong><small>${esc(stepNames[s.state]||'Pending')}</small></div></li>`).join('')}</ol></details>`;
  }
  function itemDetail(n){
    const hold=arr(n.hold_reasons),warnings=arr(n.blockers),p=n.parts;
    let html=`<div class="pp-current-stage"><span>Flow status</span>${stageBadge(n.flow_stage)||'<strong>Stage not available</strong>'}${n.flow_stage?.inherited?`<small>Following ${esc(n.flow_stage.source_item_id)}</small>`:''}</div><div class="pp-item-facts"><div><span>Current process</span><strong>${n.current_step?`${n.current_step} · `:''}${esc(n.current_title||(n.fabrication_finished?finishedLabel(n):'Route not started'))}</strong></div><div><span>Location</span><strong>${esc(n.location||'Not recorded')}</strong></div><div><span>Responsible employee</span><strong>${esc(n.handler_name||n.handler||'Not recorded')}${n.handler_name&&n.handler?` <small>${esc(n.handler)}</small>`:''}</strong></div></div>`;
    if(n.route_started===false)html+='<p class="pp-info">This item has no started route. The pending steps below show its applicable production path; they do not record any work.</p>';
    if(n.administrative_release)html+='<p class="pp-warning">Administrative release is recorded. It does not complete unrecorded production steps or ordinary QA checks.</p>';
    html+=notes(n.warnings,n.summary);
    if(n.on_hold)html+=`<div class="pp-hold-note"><strong>On hold</strong>${hold.length?`<ul>${hold.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`:'<p>Open the process record to review the active hold.</p>'}</div>`;
    if(p?.configured||p?.legacy_scope)html+=`<div class="pp-parts-counts"><strong>${p.configured?'Required components':'Referenced material scope'}</strong><span>${quantity(p.assigned_qty)} / ${quantity(p.required_qty)} assigned</span><span>${quantity(p.received_qty)} received</span><span>${quantity(p.prepared_qty)} prepared</span>${quantity(p.short_qty)?`<span class="pp-warning">${quantity(p.short_qty)} still to assign</span>`:''}${p.reference?`<span>Reference: ${esc(p.reference)}</span>`:''}</div>`;
    if(n.required_spools!==null&&n.required_spools!==undefined)html+=`<p class="pp-info"><strong>Required spools:</strong> ${quantity(n.linked_spools)} linked / ${quantity(n.required_spools)} required${quantity(n.missing_spools)?` · ${quantity(n.missing_spools)} still to link`:''}.</p>`;
    html+=stageStrip(itemStages(n),`This ${label(n).toLowerCase()}'s flow`,n.flow_stage)+stepList(n);
    if(warnings.length)html+=`<details class="pp-readiness"><summary>Readiness checks (${warnings.length})</summary><p>Open requirements can include later QA steps. An open requirement is shown separately from an active hold.</p><ul>${warnings.map(v=>`<li>${esc(v)}</li>`).join('')}</ul></details>`;
    html+=`<div class="actions pp-record-actions">${button('flow','Open process flow',n.id,n.project_id,'primary')}${button('item','Item & QR',n.id,n.project_id)}${n.route==='spool'||n.route==='assembly'?button('welds','Weld records',n.id,n.project_id):''}${n.route==='spool'?button('parts','Parts list',n.id,n.project_id):''}</div>`;
    return html;
  }
  function itemView(n,depth=0){
    const k=key('item',n.id),children=arr(n.children),expanded=opened(k);
    let html=`<details class="pp-item${n._context?' pp-context':''}" data-pp-expand="${esc(k)}" data-pp-item="${esc(n.id)}"${expanded}><summary><span class="pp-expander" aria-hidden="true"></span><div class="pp-identity"><span class="pp-eyebrow">${esc(label(n))}${n._context?' · Parent context':''}</span>${kind(n)==='spool'?spoolText(n,spoolNumber(n),'strong'):`<strong>${esc(n.id)}</strong>`}${n.part_number?`<small>${kind(n)==='spool'?'Spool number':'Part no.'} ${kind(n)==='spool'?spoolText(n,n.spool_number||n.part_number):esc(n.part_number)}</small>`:''}<div class="pp-identity-stage">${stageBadge(n.flow_stage)}</div><small>${esc(n.current_title||(n.fabrication_finished?finishedLabel(n):'Route not started'))}</small></div><div class="pp-row-progress">${meter(ownProgress(n),`${label(n)} route`,n.fabrication_finished,true)}</div><span class="pp-status ${n.on_hold?'pp-status-hold':n.fabrication_finished?'pp-status-finished':'pp-status-wip'}">${esc(statusLabel(n))}</span></summary>`;
    if(!expanded)return html+'</details>';
    html+=`<div class="pp-item-body">${itemDetail(n)}`;
    if(children.length)html+=`<section class="pp-children"><h3>${kind(n)==='assembly'?'Spools':'Individual parts'} <span>${children.length}${isFiltered()?' matching':''}</span></h3>${children.map(c=>itemView(c,depth+1)).join('')}</section>`;
    else if(kind(n)==='spool'&&!isFiltered())html+='<p class="pp-info">No individual component QR records are linked to this spool yet.</p>';
    return html+'</div></details>';
  }
  function gpnView(g,project){
    const k=key('gpn',g.id),single=g._assembly_count===1&&g.assemblies.length===1?g.assemblies[0]:null,expanded=opened(k);
    let html=`<details class="pp-gpn" data-pp-expand="${esc(k)}" data-pp-gpn="${esc(g.id)}"${expanded}><summary><span class="pp-expander" aria-hidden="true"></span><div class="pp-identity"><span class="pp-eyebrow">Assembly Number</span><strong>${esc(g.assembly_number||'Not entered')}</strong><small>GPN: ${esc(g.gpn)}</small>${single?`<small>Tracking ID: ${esc(single.id)}</small>`:''}${summaryBadges(g.summary)}</div><div class="pp-row-progress">${meter(overallProgress(g.summary),'Registered branch steps',g.summary?.complete,true)}</div>${g.setup_needed?'<span class="pp-status pp-status-wip">Setup needed</span>':''}</summary>`;
    if(!expanded)return html+'</details>';
    html+=`<div class="pp-gpn-body">${notes(g.warnings,g.summary)}${stageStrip(g.stages,'Assembly flow · registered items')}`;
    if(g.quantity_plan)html+=`<p class="pp-info"><strong>Saved P.O. quantities:</strong> ${quantity(g.quantity_plan.assembly_quantity)} assemblies · ${quantity(g.quantity_plan.spools_per_assembly)} spools per assembly · ${quantity(g.quantity_plan.total_spools)} total spools. ${quantity(g.registered_assemblies)} physical assemblies registered.</p>${g.registration_needed?`<div class="actions">${button('order','Register physical assemblies',g.id,project)}</div>`:''}`;
    if(g.setup_needed)html+=`<p class="pp-info">Finish this assembly’s setup and declare its required spools to establish this branch's scope.</p><div class="actions">${button('order','Open order setup',g.id,project)}</div>`;
    if(single){
      html+=`<section class="pp-assembly-own"><h3>Assembly's own route</h3>${itemView({...single,children:[]})}</section>`;
      html+=`<section class="pp-children"><h3>Spools <span>${arr(single.children).length}${isFiltered()?' matching':''}</span></h3>${arr(single.children).length?single.children.map(n=>itemView(n)).join(''):'<p class="pp-info">No physical spools are linked in this view.</p>'}</section>`;
    }else if(g.assemblies.length)html+=`<p class="pp-info">This GPN has ${g._assembly_count} physical assemblies, each with its own QR identity${isFiltered()?'; '+g.assemblies.length+' match this view':''}.</p>${g.assemblies.map(n=>itemView(n)).join('')}`;
    return html+'</div></details>';
  }
  function orderView(o){
    const k=key('order',o.project_id),expanded=opened(k);
    let html=`<details class="pp-order" data-pp-expand="${esc(k)}" data-pp-order="${esc(o.project_id)}"${expanded}><summary><span class="pp-expander" aria-hidden="true"></span><div class="pp-identity"><span class="pp-eyebrow">Purchase order</span><strong>P.O ${esc(o.purchase_order)}</strong><small>${esc(o.customer||'Customer not recorded')}</small>${summaryBadges(o.summary)}</div><div class="pp-row-progress">${meter(overallProgress(o.summary),'Registered production steps',o.summary?.complete,true)}</div><span class="pp-status ${o.summary?.complete?'pp-status-finished':'pp-status-wip'}">${o.summary?.complete?'Finished':'In progress'}</span></summary>`;
    if(!expanded)return html+'</details>';
    html+=`<div class="pp-order-body">${notes(o.warnings,o.summary)}${stageStrip(o.stages,'P.O flow · registered items')}<div class="actions pp-order-actions">${button('order','Open P.O','',o.project_id)}${button('project-detail','Project detail','',o.project_id)}${button('dossier','Job Packets','',o.project_id)}</div>`;
    if(!o.gpns.length&&!o.unassigned.length)html+='<div class="pp-empty"><strong>No physical production scope registered yet</strong><p>Add the GPN / Assembly, required spools, and actual part records from the P.O.</p></div>';
    html+=o.gpns.map(g=>gpnView(g,o.project_id)).join('');
    if(o.unassigned.length)html+=`<section class="pp-unassigned"><h3>Parts awaiting a GPN / Assembly link</h3><p>These records belong to this P.O. Their parent scope still needs review.</p>${o.unassigned.map(n=>itemView(n)).join('')}</section>`;
    return html+'</div></details>';
  }
  function controls(){return `<section class="pp-controls"><div class="field pp-po-select"><label for="ppPo">Purchase order</label><select id="ppPo">${option('','All P.O.s',state.project)}${state.choices.map(o=>option(o.project_id,`P.O ${o.purchase_order}${o.customer?' · '+o.customer:''}`,state.project)).join('')}</select></div><div class="field"><label for="ppStatus">Production status</label><select id="ppStatus">${[['all','All statuses'],['wip','WIP'],['finished','Finished / prepared'],['hold','On hold']].map(([v,l])=>option(v,l,state.status)).join('')}</select></div><div class="field"><label for="ppKind">Show</label><select id="ppKind">${[['all','Assemblies, spools & parts'],['spool','Spools'],['part','Individual parts'],['assembly','Assemblies']].map(([v,l])=>option(v,l,state.kind)).join('')}</select></div><div class="field pp-search"><label for="ppSearch">Find a P.O., Assembly Number, GPN or part</label><input id="ppSearch" type="search" value="${esc(state.query)}" placeholder="P.O., Assembly Number, GPN, spool number or part ID"></div></section>`;}
  function header(){return `<div class="pp-head"><div><span class="pp-eyebrow">CLM · Production visibility</span><h1>Production progress</h1><p>Every individual spool is grouped under its current process, from Inventory to Ready To Ship.</p></div><div class="actions">${button('refresh','Refresh','','','primary')}${button('orders','Purchase orders')}${button('legacy-progress',state.project?'Project detail':'All project records')}</div></div>`;}
  function summaryView(){const s=state.data.summary||{};return `<section class="pp-overview"><div>${meter(overallProgress(s),'Recorded production steps',s.complete)}<p class="pp-progress-note">Recorded steps describe the selected P.O. scope. Part preparation, spool fabrication, assembly finish and shipment are separate milestones.</p>${s.scope_complete===false?'<p class="pp-warning pp-scope-inline">Scope incomplete · the registered step percentage does not prove the whole order is finished.</p>':''}</div><div class="pp-totals">${[['P.O.s',state.data.orders.length],['Spools',s.spools],['Individual parts',s.parts],['On hold',s.on_hold]].map(([l,n])=>`<div><span>${l}</span><strong>${quantity(n)}</strong></div>`).join('')}</div></section>`;}
  function render(){
    if(!state.active)return;
    let html=header()+controls();
    if(state.loading)html+='<div class="pp-state" role="status">Loading the current P.O. production flow…</div>';
    else if(state.error)html+=`<div class="pp-state pp-error" role="alert"><strong>Production progress could not be verified.</strong><p>${esc(state.error)}</p>${button('refresh','Try again')}${button('all','All P.O.s')}</div>`;
    else if(state.data){
      const rows=filteredOrders();
      if(['all','spool'].includes(state.kind))html+=(flowStatus()?.processBoard(processSpools(rows),{attribute:'data-pp-spool'})||'')+(flowStatus()?.legend()||'');
      html+='<h2>P.O., assembly &amp; part details</h2>'+summaryView();
      if(isFiltered())html+='<p class="pp-filter-note">Search and status filters keep matching items with their parent context. P.O. progress totals still describe the full selected scope.</p>';
      html+=`<div class="pp-list-tools"><span>${rows.length} matching P.O.${rows.length===1?'':'s'}${state.data.as_of?' · Updated '+esc(new Date(state.data.as_of).toLocaleString()):''}</span><div class="actions">${isFiltered()?button('clear','Clear filters'):''}${button('expand','Expand all')}${button('collapse','Collapse all')}</div></div>`;
      if(rows.length)html+=rows.map(orderView).join('');
      else html+=`<div class="pp-empty"><strong>${arr(state.data.orders).length?'No items match this view':'No active P.O.s in this view'}</strong><p>${arr(state.data.orders).length?'Clear the search or change the status/type filter.':'Create a P.O. or restore its removed records to see its registered production scope here.'}</p>${isFiltered()?button('clear','Clear filters'):button('orders','Open purchase orders')}</div>`;
      html+='<p class="pp-footnote">Only recorded current-route work advances a bar. Earlier baseline steps stay unrecorded, rework reopens affected steps, and administrative release does not complete route history. Removed records are outside this working view.</p>';
    }
    node('productionProgressContent').innerHTML=html;node('productionProgressContent').setAttribute('aria-busy',String(state.loading));wire();
  }
  function wire(){
    const po=node('ppPo');if(po)po.onchange=()=>{state.project=po.value;state.expanded.clear();state.autoOpen=true;return load();};
    for(const [id,k] of [['ppStatus','status'],['ppKind','kind']]){const el=node(id);if(el)el.onchange=()=>{state[k]=el.value;expandFiltered();render();node(id)?.focus();};}
    const search=node('ppSearch');if(search)search.oninput=()=>{state.query=search.value;const caret=search.selectionStart;expandFiltered();render();const active=node('ppSearch');active?.focus();active?.setSelectionRange(caret,caret);};
    for(const d of node('productionProgressContent').querySelectorAll('details[data-pp-expand]'))d.ontoggle=()=>{if(d.isConnected===false||!state.active)return;const k=d.dataset.ppExpand;if(d.open===state.expanded.has(k))return;const restoreFocus=d.contains?.(document.activeElement);if(d.open)state.expanded.add(k);else state.expanded.delete(k);render();if(restoreFocus)for(const next of node('productionProgressContent').querySelectorAll('details[data-pp-expand]'))if(next.dataset.ppExpand===k)next.querySelector('summary')?.focus({preventScroll:true});};
  }
  function validItem(n,ids){if(!n||typeof n.id!=='string'||ids.has(n.id)||!['Part','Spool','Assembly'].includes(n.item_kind)||!['component','spool','assembly'].includes(n.route)||!Array.isArray(n.children)||!Array.isArray(n.steps)||!n.progress||!finite(n.progress.percent)||!Array.isArray(n.stages))return false;ids.add(n.id);return n.steps.every(s=>Number.isInteger(s.number)&&stepNames[s.state]&&typeof s.title==='string')&&n.children.every(c=>validItem(c,ids));}
  function validResponse(d,project){
    if(!d||d.selected_project_id!==project||!Array.isArray(d.choices)||!Array.isArray(d.orders)||!Array.isArray(d.stage_catalog)||!d.summary)return false;
    if(!d.choices.every(o=>typeof o.project_id==='string'&&typeof o.purchase_order==='string')||!d.stage_catalog.every(s=>typeof s.key==='string'&&typeof s.label==='string'&&Array.isArray(s.steps)))return false;
    const ids=new Set(),orders=new Set();
    return d.orders.every(o=>{if(typeof o.project_id!=='string'||orders.has(o.project_id)||project&&o.project_id!==project||!Array.isArray(o.gpns)||!Array.isArray(o.unassigned)||!o.summary)return false;orders.add(o.project_id);return o.gpns.every(g=>typeof g.id==='string'&&typeof g.gpn==='string'&&Array.isArray(g.assemblies)&&g.assemblies.every(n=>validItem(n,ids)))&&o.unassigned.every(n=>validItem(n,ids));});
  }
  function updateUrl(){const q=new URLSearchParams({'production-progress':'1'});if(state.project)q.set('project',state.project);history.replaceState(null,'','/?'+q.toString());}
  async function load(){
    if(!state.active||!me)return;
    const sequence=++state.sequence,project=state.project;state.loading=true;state.error='';render();
    try{const d=await api(ROOT+(project?'?project_id='+enc(project):''));if(!state.active||sequence!==state.sequence||project!==state.project)return;if(!validResponse(d,project))throw Error('The production scope response could not be verified. Refresh before relying on this view.');state.data=d;state.choices=d.choices;if(state.autoOpen&&project)state.expanded.add(key('order',project));state.autoOpen=false;expandFiltered();updateUrl();}
    catch(error){if(state.active&&sequence===state.sequence){state.error=errorText(error);state.data=null;}}
    finally{if(state.active&&sequence===state.sequence){state.loading=false;render();}}
  }
  async function open(options={}){if(!me)return;show('productionProgressPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;state.active=true;state.project=text(options.project||'');state.status='all';state.kind='all';state.query='';state.expanded.clear();state.data=null;state.choices=[];state.autoOpen=true;await load();}
  async function act(action,id,project){
    if(action==='refresh')return load();if(action==='all'){state.project='';return load();}if(action==='clear'){state.query='';state.status='all';state.kind='all';render();return;}
    if(action==='expand'||action==='collapse'){state.expanded.clear();if(action==='expand'){const visit=n=>{state.expanded.add(key('item',n.id));state.expanded.add(key('steps',n.id));arr(n.children).forEach(visit);};for(const o of filteredOrders()){state.expanded.add(key('order',o.project_id));o.gpns.forEach(g=>{state.expanded.add(key('gpn',g.id));g.assemblies.forEach(visit);});o.unassigned.forEach(visit);}}render();return;}
    if(action==='orders')return window.FabOrders.open();if(action==='legacy-progress')return window.FabProgress.open({project:state.project});if(action==='order')return window.FabOrders.open({po:project,gpn:id||''});
    if(action==='project-detail')return window.FabProgress.open({project});if(action==='dossier')return window.FabDossier.open({project});
    if(action==='item')return openItem(id);if(action==='flow')return window.FabFlow.open({item:id,project});if(action==='welds')return window.FabTracking.open({spool:id,project});if(action==='parts')return window.FabParts.open({spool:id,project});
  }
  node('productionProgressContent').addEventListener('click',async event=>{const target=event.target.closest('[data-pp-action],[data-pp-spool]');if(!target||target.disabled)return;try{if(target.dataset.ppSpool)return await act('flow',target.dataset.ppSpool,target.dataset.spoolProject||'');await act(target.dataset.ppAction,target.dataset.ppId||'',target.dataset.ppProject||'');}catch(error){notify(errorText(error));}});
  if(node('navProgress'))node('navProgress').onclick=()=>open();
  window.FabProductionProgress={open,refresh:load,cancelPending(){state.active=false;state.sequence++;state.loading=false;}};
})();
