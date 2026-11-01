/* CLM's numbered fabrication traveler. The server owns all transition rules. */
(() => {
  'use strict';
  const ROOT='/api/flow', node=id=>document.getElementById(id), encode=encodeURIComponent;
  const arr=value=>Array.isArray(value)?value:[], num=value=>Number.isFinite(Number(value))?Number(value):0;
  const stamp=value=>value?new Date(value).toLocaleString():'—';
  const roles={admin:'Administrator',supervisor:'Supervisor',handler:'Material coordinator',welder:'Welder',fitup_welder:'Fit-up welder',process_welder:'Process welder',inspector:'QA/QC',painter:'Painter',finisher:'Finisher',misc:'Miscellaneous / support'};
  const flowStatus=()=>window.FabFlowStatus;
  const stageBadge=value=>flowStatus()?.badge(value)||'';
  const isSpool=value=>value?.route?value.route==='spool':value?.kind==='Spool';
  const spoolNumber=value=>flowStatus()?.spoolNumber?.(value)||value.qr_alias||value.spool_number||value.google_part_number||value.item_id||value.id;
  const itemLabel=value=>isSpool(value)?spoolNumber(value):value.item_id||value.id;
  const spoolText=(value,label=spoolNumber(value))=>flowStatus()?.spoolText?.(value,label)||esc(label);
  const routeNames={component:'Component',spool:'Spool',assembly:'Assembly'};
  const statusNames={admin_released:'Administrative release',not_started:'Not started',active:'In progress',completed:'Route complete',shipped:'Shipped',delivered:'Delivered',rework:'Needs rework'};
  const stepStatusNames={pending:'Upcoming',current:'Current step',completed:'Completed',not_recorded:'Not recorded',rework:'Needs reinspection',other_route:'Linked record'};
  const phases=[
    {id:'materials',label:'Material receipt & inventory',first:1,last:4},
    {id:'components',label:'Component preparation',first:5,last:8},
    {id:'spool',label:'Spool fabrication',first:9,last:16},
    {id:'assembly',label:'Final assembly',first:17,last:19},
    {id:'paint',label:'Sandblast & paint',first:20,last:22},
    {id:'shipping',label:'Shipment',first:23,last:24},
  ];
  const state={catalog:null,handoffOptions:null,handoffControl:null,board:[],detail:null,item:'',project:'',subproject:'',query:'',status:'',step:'',sequence:0,saving:false,dialogAction:null,dialogStale:false,notice:''};
  const clocks=new WeakMap();
  const now=()=>typeof performance!=='undefined'&&typeof performance.now==='function'?performance.now():Date.now();
  let clockTimer=null;
  const removed=()=>state.detail?.removal?.removed===true||state.detail?.item?.removal?.removed===true;
  const can=action=>!removed()&&arr(state.detail?.allowed_actions).includes(action);
  const action=(name,label,id='',className='',spool=null)=>`<button type="button" class="${esc(className)}" data-flow-action="${esc(name)}"${id?` data-flow-id="${esc(id)}"`:''}>${spool?spoolText(spool,label):esc(label)}</button>`;
  const option=(value,label,selected='')=>`<option value="${esc(value)}"${String(value)===String(selected)?' selected':''}>${esc(label)}</option>`;
  const secondary=text=>`<span class="ff-secondary">${esc(text)}</span>`;
  const tag=(status,label='')=>`<span class="ff-tag ${esc(status)}">${esc(label||statusNames[status]||status)}</span>`;
  const table=html=>`<div class="tablewrap">${html}</div>`;
  const route=id=>arr(state.catalog?.routes).find(row=>row.id===id);
  const definition=step=>arr(state.catalog?.steps).find(row=>Number(row.number)===Number(step));
  const openExceptions=()=>arr(state.detail?.exceptions).filter(row=>!row.closed_at);
  const displayStatus=row=>num(row.open_exceptions)>0?'rework':row.status||'not_started';

  function errorText(error){
    try{const detail=JSON.parse(error.message);if(Array.isArray(detail))return detail.map(row=>`${arr(row.loc).filter(x=>x!=='body').join(' / ')}: ${row.msg||'Check this value'}`).join('\n');if(detail.message)return detail.message;if(detail.flow_blockers)return arr(detail.flow_blockers).join('\n')}catch(_){}
    return error.message||'The request could not be completed.';
  }
  function duration(value){
    const seconds=Math.max(0,Math.floor(num(value))),days=Math.floor(seconds/86400),hours=Math.floor(seconds%86400/3600),minutes=Math.floor(seconds%3600/60),rest=seconds%60;
    return `${days?days+'d ':''}${days||hours?String(hours).padStart(days?2:1,'0')+'h ':''}${String(minutes).padStart(2,'0')}m ${String(rest).padStart(2,'0')}s`;
  }
  function anchor(snapshot){
    if(snapshot&&typeof snapshot==='object'&&!clocks.has(snapshot))clocks.set(snapshot,now());
    return clocks.get(snapshot)??now();
  }
  function clock(snapshot,value,live=false){
    const started=anchor(snapshot),seconds=num(value)+(live?Math.max(0,(now()-started)/1000):0);
    return `<span class="ff-clock"${live?` data-flow-clock="${num(value)}" data-flow-anchor="${started}"`:''}>${duration(seconds)}</span>`;
  }
  function stopClocks(){if(clockTimer!==null){clearInterval(clockTimer);clockTimer=null;}}
  function startClocks(){
    stopClocks();const host=node('flowContent');
    if(typeof setInterval!=='function'||typeof host.querySelectorAll!=='function')return;
    const elements=[...host.querySelectorAll('[data-flow-clock]')];if(!elements.length)return;
    const tick=()=>{const time=now();for(const element of elements)element.textContent=duration(num(element.dataset.flowClock)+Math.max(0,(time-num(element.dataset.flowAnchor))/1000))};
    tick();clockTimer=setInterval(tick,1000);
  }
  function markTimes(detail){
    if(detail?.production_process)anchor(detail.production_process);
    return detail;
  }
  function normalizeId(value){
    if(typeof qrId==='function')return qrId(value,'item');
    const text=String(value||'').trim();
    if(text.startsWith('FABTRACE:ITEM:'))return text.slice(14);
    try{const url=new URL(text);if(url.searchParams.has('item'))return url.searchParams.get('item')}catch(_){}
    return /^[A-Za-z0-9_-]{3,60}$/.test(text)?text:'';
  }
  async function readId(value,label='Item ID'){
    const id=typeof window.resolveItemQr==='function'?await window.resolveItemQr(value):normalizeId(value);
    if(!id)throw Error(label+': scan or enter a valid FabTrace spool label or item ID.');return id;
  }
  function field(name,label,value='',settings={}){
    const id='ff-field-'+name,common=`id="${esc(id)}" name="${esc(name)}"${settings.required?' required':''}${settings.disabled?' disabled':''}`;
    let control;
    if(settings.options)control=`<select ${common}>${settings.options.map(row=>option(row[0],row[1],value)).join('')}</select>`;
    else if(settings.type==='textarea')control=`<textarea ${common}${settings.maxlength?` maxlength="${settings.maxlength}"`:''} rows="${settings.rows||3}">${esc(value)}</textarea>`;
    else control=`<input ${common} type="${settings.type||'text'}" value="${esc(value)}"${settings.min!==undefined?` min="${settings.min}"`:''}${settings.max!==undefined?` max="${settings.max}"`:''}${settings.maxlength?` maxlength="${settings.maxlength}"`:''}${settings.minlength?` minlength="${settings.minlength}"`:''}${settings.placeholder?` placeholder="${esc(settings.placeholder)}"`:''}${settings.readonly?' readonly':''} autocomplete="off">`;
    return `<div class="field${settings.full?' ff-span':''}"><label for="${id}">${esc(label)}${settings.required?' *':''}</label>${control}${settings.help?`<span class="ff-form-help">${esc(settings.help)}</span>`:''}</div>`;
  }
  function fields(content){return `<div class="ff-fields">${content}</div>`}
  function empty(title,copy,controls=''){return `<div class="ff-empty"><strong>${esc(title)}</strong><p>${esc(copy)}</p>${controls}</div>`}
  function metadata(pairs){return `<div class="ff-meta">${pairs.map(([label,value])=>`<dl><dt>${esc(label)}</dt><dd>${esc(value||'—')}</dd></dl>`).join('')}</div>`}
  function updateUrl(){
    const query=new URLSearchParams({flow:'1'});if(state.item)query.set('item',state.item);if(state.project)query.set('project',state.project);
    history.replaceState(null,'','/?'+query.toString());
  }
  async function open(options={}){
    if(!me)return;
    show('flowPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;
    state.item=options.item||'';state.detail=null;state.notice='';
    if(Object.prototype.hasOwnProperty.call(options,'project'))state.project=options.project||'';
    if(options.resetFilters===true){state.subproject='';state.query='';state.status='';state.step='';}
    await load();
  }
  async function load(){
    const sequence=++state.sequence;stopClocks();state.handoffControl?.destroy();state.handoffControl=null;
    node('flowContent').innerHTML='<div class="ff-state" role="status">Loading fabrication process records…</div>';
    node('flowContent').setAttribute('aria-busy','true');
    try{
      const [catalog,board,detail,handoffOptions]=await Promise.all([
        state.catalog?Promise.resolve(state.catalog):api(ROOT+'/catalog'),
        api(ROOT+'/items'),state.item?api(ROOT+'/items/'+encode(state.item)):Promise.resolve(null),
        api('/api/transfers/options'),
      ]);
      if(sequence!==state.sequence)return;
      state.catalog=catalog;state.handoffOptions=handoffOptions;state.board=arr(board.items);state.detail=markTimes(detail);
      for(const row of state.board)markTimes(row);
      render();updateUrl();
    }catch(error){
      if(sequence!==state.sequence)return;
      node('flowContent').innerHTML=`<div class="ff-state ff-error" role="alert"><strong>Process records could not be loaded.</strong><p>${esc(errorText(error))}</p><div class="actions">${action('refresh','Try again')}${action('board','Back to process board')}</div></div>`;
    }finally{if(sequence===state.sequence)node('flowContent').setAttribute('aria-busy','false')}
  }
  async function refresh(){await load()}
  function heading(title,description,controls='',spool=null){
    return `<div class="ff-head"><div><div class="ff-eyebrow">CLM fabrication · Track. Verify. Build. Deliver.</div><h1>${spool?spoolText(spool,title):esc(title)}</h1><p>${esc(description)}</p></div><div class="actions">${controls}${action('refresh','Refresh')}</div></div>`;
  }
  function lookup(){
    return '<form id="flowLookupForm" class="ff-lookup"><div class="field"><label for="flowLookup">Scan or enter item ID</label><input id="flowLookup" name="item" required autocomplete="off" placeholder="Component, spool, or assembly ID"></div><button type="submit" class="primary">Open record</button><p class="ff-help">Use a barcode scanner, type the ID, or paste a FabTrace QR link. A phone QR opens the item record, where Process flow is available.</p></form>';
  }
  function visibleItems(ignoreStep=false){
    const query=state.query.trim().toLowerCase();
    return state.board.filter(row=>(!state.project||row.project_id===state.project)&&(!state.subproject||row.subproject_id===state.subproject)&&(!state.status||displayStatus(row)===state.status)&&(ignoreStep||!state.step||Number(row.current_step)===Number(state.step))&&(!query||[row.item_id,row.spool_number,row.google_part_number,row.qr_alias,row.display_code,row.current_title,row.project_id,row.subproject_id].some(value=>String(value||'').toLowerCase().includes(query))));
  }
  function filters(){
    const projects=[...new Set(state.board.map(row=>row.project_id).filter(Boolean))].sort();
    const subs=[...new Set(state.board.filter(row=>!state.project||row.project_id===state.project).map(row=>row.subproject_id).filter(Boolean))].sort();
    return `<div class="ff-filters"><div class="field"><label for="flowProject">Project</label><select id="flowProject">${option('','All projects',state.project)}${projects.map(value=>option(value,value,state.project)).join('')}</select></div><div class="field"><label for="flowSubproject">Subproject</label><select id="flowSubproject">${option('','All subprojects',state.subproject)}${subs.map(value=>option(value,value,state.subproject)).join('')}</select></div><div class="field"><label for="flowStatus">Status</label><select id="flowStatus">${option('','All statuses',state.status)}${['active','rework','admin_released','completed','shipped','delivered'].map(value=>option(value,statusNames[value],state.status)).join('')}</select></div><div class="field ff-search"><label for="flowSearch">Find item or process</label><input id="flowSearch" type="search" value="${esc(state.query)}" placeholder="Spool number, ID or current step"></div></div>${state.step?`<div class="notice">Showing step ${esc(state.step)} · ${esc(definition(state.step)?.title||'')} ${action('clear-step','Clear step filter','','ff-link')}</div>`:''}`;
  }
  function counts(rows){
    const values=[['In progress',rows.filter(row=>row.status==='active').length,'Active component, spool, and assembly routes'],['Needs rework',rows.filter(row=>num(row.open_exceptions)>0).length,'Open process exceptions'],['Shipped',rows.filter(row=>row.status==='shipped').length,'Awaiting delivery receipt'],['Delivered',rows.filter(row=>row.status==='delivered').length,'Delivery recorded']];
    return `<div class="ff-metrics">${values.map(([label,value,description])=>`<div class="ff-metric"><span>${label}</span><strong>${value}</strong><small>${description}</small></div>`).join('')}</div>`;
  }
  function timingCell(row){
    const process=row.production_process,current=process?.current;
    if(!current)return '<span class="muted">—</span>';
    return clock(process,current.elapsed_seconds,['running','paused'].includes(process.status))+secondary(process.status==='paused'?'Paused':'Running');
  }
  function renderBoard(){
    const rows=visibleItems();
    let html=heading('Fabrication process flow','Follow each part from Inventory through Ready To Ship. Open a record to complete its production steps and QA/QC checks.')+(flowStatus()?.strip(state.catalog.stage_catalog)||'')+(flowStatus()?.legend()||'')+lookup()+filters()+counts(rows);
    html+=`<section class="card"><div class="ff-section-head"><h2>Production board</h2><span class="muted">${rows.length} matching records</span></div>`;
    html+=rows.length?table(`<table class="ff-table"><thead><tr><th>Item / route</th><th>Project</th><th>Flow status / current step</th><th>Time in process</th><th>Status</th><th>Attention</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${action('item',itemLabel(row),row.item_id,'ff-link',isSpool(row)?row:null)}${secondary(routeNames[row.route]||row.route)}</td><td>${esc(row.project_id||'Unassigned')}${secondary(row.subproject_id||'')}</td><td><div class="ff-stage-label">${stageBadge(row.flow_stage)}</div>${row.current_step?`<strong>${esc(row.current_step)} · ${esc(row.current_title)}</strong>`:'<span class="muted">Route finished</span>'}</td><td>${timingCell(row)}</td><td>${tag(displayStatus(row))}</td><td>${num(row.open_exceptions)?`${num(row.open_exceptions)} open exception${num(row.open_exceptions)===1?'':'s'}`:arr(row.blockers).length?esc(row.blockers[0]):'<span class="muted">—</span>'}</td></tr>`).join('')}</tbody></table>`):empty('No matching process records',state.board.length?'Clear the filters or choose another project.':'Open an existing item above. An administrator or supervisor can start its component, spool, or assembly route.');
    html+='</section><section class="card"><div class="ff-section-head"><h2>The 24-step fabrication flow</h2><span class="muted">Select a step to filter the board</span></div><p class="ff-footer-note">Components follow steps 1–8, spools follow 9–16, and assemblies follow 17–24. Linked records connect the material history to the finished assembly.</p>'+renderMap(false)+'</section>';
    return html;
  }
  function stepState(step){
    const flow=state.detail?.flow;if(!flow)return 'pending';
    if(step.route!==flow.route)return 'other_route';
    const status=arr(flow.steps).find(row=>Number(row.number)===Number(step.number))?.status||'pending';
    return openExceptions().some(row=>Number(row.step)===Number(step.number))?'rework':status;
  }
  function renderMap(selected){
    const mapItems=visibleItems(true);
    return `<div class="ff-map">${phases.map(phase=>`<section class="ff-map-section" data-phase="${phase.id}"><h3>${phase.first}–${phase.last} · ${phase.label}</h3><ol>${arr(state.catalog.steps).filter(step=>step.number>=phase.first&&step.number<=phase.last).map(step=>{const visual=selected?stepState(step):state.step&&Number(state.step)===Number(step.number)?'current':'pending',count=mapItems.filter(row=>Number(row.current_step)===Number(step.number)).length;return `<li class="ff-map-step ${visual}"><span class="ff-num">${step.number}</span><div class="ff-map-copy">${selected?`<strong>${esc(step.title)}</strong>`:action('filter-step',step.title,String(step.number),'ff-link')}<small>${selected?(visual==='other_route'?esc(routeNames[step.route]+' record'):stepStatusNames[visual]):count?`${count} record${count===1?'':'s'} at this step`:esc(routeNames[step.route]+' route')}</small></div></li>`}).join('')}</ol></section>`).join('')}</div>`;
  }
  function routeProgress(){
    const flow=state.detail.flow;
    return `<div class="ff-route" aria-label="${esc(routeNames[flow.route]||flow.route)} route progress">${arr(flow.steps).map(step=>{const visual=stepState(step);return `<div class="ff-route-step ${visual}"${step.status==='current'?' aria-current="step"':''}><span class="ff-num">${step.number}</span><strong>${esc(step.title)}</strong><small>${esc(stepStatusNames[visual])}</small></div>`}).join('')}</div><div class="ff-legend"><span class="done">Completed</span><span class="current">Current step</span><span>Upcoming</span><span class="rework">Needs reinspection</span><span class="unknown">Earlier work not recorded</span></div>`;
  }
  function timing(){
    const detail=state.detail,flow=detail.flow,process=detail.production_process,current=process?.current;
    if(!process||!flow)return '';
    const asOf=new Date(process.as_of).getTime(),entered=new Date(flow.step_entered_at).getTime();
    const age=Number.isFinite(asOf)&&Number.isFinite(entered)?Math.max(0,(asOf-entered)/1000):num(current?.elapsed_seconds);
    const running=process.status==='running'&&Boolean(current),paused=process.status==='paused'&&Boolean(current);
    let html='<div class="ff-time-row">';
    if(flow.current)html+=`<div><span>Time at current step</span><strong>${clock(process,age,flow.status==='active')}</strong></div>`;
    if(current)html+=`<div><span>Running time</span><strong>${clock(process,current.active_seconds,running)}</strong></div><div><span>Paused time</span><strong>${clock(process,current.paused_seconds,paused)}</strong></div>`;
    html+='</div>';
    if(current)html+=`<div class="actions">${can('pause')?action('pause','Pause / record delay'):''}${can('resume')?action('resume','Resume process'):''}${process.status==='paused'?tag('rework','Process paused'):''}</div>`;
    return html+'<p class="ff-footer-note">Elapsed clock time includes pauses. This measures the item’s time in the process, not employee labor hours. Stage timers move when the numbered step advances.</p>';
  }
  function stepInputs(step){
    let content='';
    if(step.requires_scan)content+=field('scanned_item_id','Scan or enter this item ID again','',{required:true,maxlength:500,help:'Verify the physical item being processed: '+state.detail.item.id});
    if(step.number===17)content+=field('scanned_child_ids','Scan or enter each linked spool ID','',{required:true,type:'textarea',full:true,rows:4,help:'One spool ID or FabTrace QR link per line. Every linked spool must be verified.'});
    if(step.requires_handoff){
      const transfer=state.detail.transfer||state.detail.item.transfer;
      content+=`<div class="ff-span"><h3>Identify both employees for this handoff</h3><p class="fh-help">Current recorded custodian: <strong>${esc(transfer?.handler_name||transfer?.handler||state.detail.item.handler)}</strong>${transfer?.handler_name?' ('+esc(transfer.handler)+')':''}. Scan the sending badge and receiving badge in their separate fields. The signed-in employee records the step.</p>${window.FabHandoff.controlHtml('flowHandoff',{transfer,options:state.handoffOptions,heading:false})}<div id="flowHandoffReview" class="fh-review" aria-live="polite"></div><p class="fh-record-note">Badges identify the parties; no independent acceptance signature is recorded. Completing this numbered step applies its existing process and QA checks.</p></div>`;
    }else if(step.requires_location||step.number===3){
      const transfer=state.detail.transfer||state.detail.item.transfer;
      content+=`<div class="field"><label for="ff-field-location_id">${step.number===3?'Storage location':'Receiving location / work center'} *</label><select id="ff-field-location_id" name="location_id" required>${window.FabHandoff.locationOptions(state.handoffOptions,transfer,transfer?.location?'current':'')}</select><span class="ff-form-help">Choose an active work center or retain the actual recorded location.</span></div>`;
    }
    if(step.number===5)content+=field('target_spool_id','Assigned spool ID',state.detail.parent?.item_id||'',{required:true,maxlength:500,help:'This must match the spool linked to this component.'});
    if(step.requires_reference)content+=field('reference',step.qa?'Inspection report / approval reference':'PO, BOM, drawing, or record reference','',{required:true,maxlength:500,full:true});
    if(step.number===24)content+=field('carrier','Carrier','',{required:true,maxlength:160})+field('shipment_reference','Shipping document / tracking reference','',{required:true,maxlength:500})+field('destination','Destination / customer','',{required:true,maxlength:500,full:true});
    if(step.qa&&openExceptions().some(row=>Number(row.step)===Number(step.number)))content+=field('resolution','Rework resolution and reinspection findings','',{required:true,type:'textarea',full:true,maxlength:3000});
    content+=field('notes','Work notes / measurements','',{type:'textarea',full:true,maxlength:3000});
    return fields(content);
  }
  function blockers(){
    const list=arr(state.detail.flow?.blockers);
    return list.length?`<div class="ff-blockers"><strong>Resolve before completing this step</strong><ul>${list.map(value=>`<li>${esc(value)}</li>`).join('')}</ul></div>`:'';
  }
  function currentStep(){
    const detail=state.detail,flow=detail.flow,step=flow.current;
    if(!step){
      let title=flow.status==='admin_released'?'Administrative release':flow.status==='shipped'?'Shipment recorded · awaiting delivery':flow.status==='delivered'?'Delivered to customer':'Route complete';
      let description=flow.route==='component'?'This component is ready for the linked spool’s fabrication route.':flow.route==='spool'?'This completed spool can be collected for its assembly.':'The assembly’s recorded route is complete.';
      if(flow.status==='admin_released')description='An administrator released this component. Its recorded work, inspections and unresolved requirements retain their actual status. Admin controls can return it to its previous process position.';
      if(flow.status==='shipped')description='Record the delivery receipt when the customer receives the assembly.';
      if(flow.status==='delivered')description='The delivery acknowledgment remains in the process history.';
      const shipment=['shipped','delivered'].includes(flow.status)?metadata([['Shipped',stamp(flow.shipped_at)],['Carrier',flow.carrier],['Shipping reference',flow.shipment_reference],['Destination',flow.destination],...(flow.status==='delivered'?[['Delivered',stamp(flow.delivered_at)],['Receipt reference',flow.receipt_reference],['Received by',flow.recipient]]:[])]):'';
      return `<section class="card ff-current"><div class="ff-current-label">${esc(routeNames[flow.route])} route</div><h2>${title}</h2><p class="muted">${description}</p>${shipment}${can('deliver')?action('deliver','Record delivery receipt','','primary'):''}${timing()}</section>`;
    }
    const allowed=can('advance'),qa=step.qa,blocked=arr(flow.blockers).length>0;
    let html=`<section class="card ff-current"><div class="ff-section-head"><div><div class="ff-current-label">Current step ${step.number} of 24 · ${esc(routeNames[flow.route])} route</div><h2>${esc(step.title)}</h2></div>${tag(openExceptions().length?'rework':'active')}</div>${timing()}${blockers()}`;
    html+=`<p class="ff-footer-note">Recorded by: ${arr(step.roles).map(value=>esc(roles[value]||value)).join(' · ')}</p>`;
    if(allowed)html+='<form id="flowStepForm"><div id="flowStepError" class="ff-error hidden" role="alert"></div>';
    html+=`<ul class="ff-checklist">${arr(step.checks).map(check=>`<li>${allowed?`<label><input type="checkbox" name="check_${esc(check.id)}" required> <span>${esc(check.label)}</span></label>`:`<span class="ff-check-read">${esc(check.label)}</span>`}</li>`).join('')}</ul>`;
    if(allowed){
      html+=stepInputs(step)+`<div class="actions"><button id="flowAdvance" type="submit" class="primary"${blocked?' disabled':''}>${step.number===24?'Record shipment':qa?'Pass inspection & continue':'Complete step '+step.number}</button>${can('fail')?action('fail',step.number===2?'Record failure / exception':'Record failed inspection'):''}</div></form>`;
    }else{
      html+='<p class="ff-footer-note">An authorized employee can complete this step after checking the physical item and its records.</p>';
      if(can('fail'))html+=action('fail','Record failed inspection');
    }
    return html+'</section>';
  }
  function childCard(child){
    return `<div class="ff-family">${action('item',itemLabel(child),child.item_id,'ff-link',isSpool(child)?child:null)}${stageBadge(child.flow_stage)}${tag(displayStatus(child))}${child.current_step?`<p>${esc(child.current_step)} · ${esc(child.current_title)}</p>`:''}</div>`;
  }
  function family(){
    const detail=state.detail,flow=detail.flow,components=arr(detail.components),spools=arr(detail.spools),orderedAssembly=flow.route==='assembly'&&detail.order_scope?.assembly_id===detail.item.id;
    let html='<section class="card"><div class="ff-section-head"><h2>Linked material & assemblies</h2></div><p class="ff-footer-note">Each link connects separate physical records: components → spool → assembly.</p>';
    if(detail.parent)html+=`<h3>${detail.parent.route==='assembly'?'Parent assembly':'Assigned spool'}</h3><div class="ff-family">${action('item',itemLabel(detail.parent),detail.parent.item_id,'ff-link',isSpool(detail.parent)?detail.parent:null)}</div>`;
    if(flow.route==='component'&&!detail.parent)html+='<p class="muted">No spool assigned yet.</p>';
    if(flow.route==='spool')html+=`<h3>Components · ${components.length} / ${num(flow.expected_children)} expected</h3>${components.length?components.map(childCard).join(''):'<p class="muted">No components linked. Open a component’s process record to assign it to this spool.</p>'}`;
    if(flow.route==='assembly')html+=`<h3>Spools · ${spools.length} / ${num(flow.expected_children)} expected</h3>${spools.length?spools.map(childCard).join(''):'<p class="muted">No spools linked yet.</p>'}`;
    html+=`<div class="actions">${can('assign-component')?action('assign-component',detail.parent?'Update spool assignment':'Assign component to spool'):''}${can('link-spool')?action('link-spool','Link spool to assembly'):''}${can('scope')&&!orderedAssembly?action('scope','Edit required count'):''}</div>`;
    if(orderedAssembly)html+=`<p class="ff-footer-note">Required spool count is managed by PO <strong>${esc(detail.order_scope.purchase_order)}</strong> · GPN / Assembly ${esc(detail.order_scope.gpn)}${detail.order_scope.assembly_part_number!==detail.order_scope.gpn?` · Retained part number ${esc(detail.order_scope.assembly_part_number)}`:''}. The count is locked once the assembly traveler starts.</p>`;
    if(flow.material_reference)html+=`<p class="ff-footer-note">Existing material basis: ${esc(flow.material_reference)}</p>`;
    return html+'</section>';
  }
  function exceptions(){
    const rows=arr(state.detail.exceptions);
    return `<section class="card"><div class="ff-section-head"><h2>Exceptions & rework</h2><span class="muted">${rows.filter(row=>!row.closed_at).length} open</span></div>${rows.length?rows.map(row=>`<article class="ff-exception ${row.closed_at?'closed':''}"><strong>Step ${esc(row.step)} · ${esc(definition(row.step)?.title||'Inspection')}</strong>${secondary(row.closed_at?'Resolved':'Open · returned to step '+row.return_step)}<p>${esc(row.reason)}</p>${row.reference?`<p>Reference: ${esc(row.reference)}</p>`:''}<p class="ff-footer-note">${esc(row.opened_by)} · ${esc(stamp(row.opened_at))}</p>${row.closed_at?`<p><strong>Resolution:</strong> ${esc(row.resolution)}</p><p class="ff-footer-note">${esc(row.closed_by)} · ${esc(stamp(row.closed_at))}</p>`:''}</article>`).join(''):'<p class="muted">No process exceptions recorded.</p>'}</section>`;
  }
  function eventHistory(){
    const labels={start:'Route started',adopt:'Existing work adopted',advance:'Step completed',fail:'Inspection failed',deliver:'Delivery recorded',assign_component:'Component assigned',link_spool:'Spool linked',shipment:'Shipment recorded'};
    const rows=arr(state.detail.events);
    return `<section class="card"><h2>Process history</h2>${rows.length?[...rows].reverse().map(row=>`<div class="ff-history"><strong>${esc(labels[row.action]||String(row.action).replace(/_/g,' '))}${row.step?' · step '+esc(row.step):''}</strong>${row.reference?`<p>Reference: ${esc(row.reference)}</p>`:''}${row.notes?`<p>${esc(row.notes)}</p>`:''}<small>${esc(row.actor)} · ${esc(stamp(row.at))}</small>${row.data&&Object.keys(row.data).length?`<details><summary class="ff-footer-note">Recorded details</summary><pre>${esc(JSON.stringify(row.data,null,2))}</pre></details>`:''}</div>`).join(''):'<p class="muted">No route events recorded.</p>'}</section>`;
  }
  function timingHistory(){
    const process=state.detail.production_process;if(!process)return '';
    const totals=process.totals||{},rows=arr(process.by_process),delays=arr(process.events).filter(row=>['pause','resume'].includes(row.event));
    if(!rows.length)return '';
    return `<section class="card"><h2>Recorded process time</h2><p class="ff-footer-note">${duration(totals.elapsed_seconds)} recorded across ${num(totals.visits)} visits as of ${esc(stamp(process.as_of))}. Return visits stay in the totals.</p>${table(`<table><thead><tr><th>Process</th><th>Visits</th><th>Elapsed</th><th>Running</th><th>Paused</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.process_name)}</td><td>${num(row.visits)}</td><td>${duration(row.elapsed_seconds)}</td><td>${duration(row.active_seconds)}</td><td>${duration(row.paused_seconds)}</td></tr>`).join('')}</tbody></table>`)}${delays.length?`<details class="ff-fold"><summary>Pause history (${delays.length})</summary>${[...delays].reverse().map(row=>`<div class="ff-history"><strong>${row.event==='pause'?'Paused':'Resumed'} · ${esc(row.process_name)}</strong><p>${esc(row.notes||'')}</p><small>${esc(row.actor)} · ${esc(stamp(row.at))}</small></div>`).join('')}</details>`:''}</section>`;
  }
  function renderDetail(){
    const detail=state.detail,item=detail.item,flow=detail.flow;
    let controls=action('board','Process board')+action('item-record','Item & QR record',item.id);
    if(me?.role==='admin'&&!removed())controls+=action('admin-controls','Admin controls',item.id);
    if(['spool','assembly'].includes(flow?.route||detail.suggested_route)||['Spool','Assembly'].includes(item.kind))controls+=action('weld-record','Individual welds',item.id);
    if((flow?.route||detail.suggested_route)==='spool'||item.kind==='Spool')controls+=action('spool-parts','Spool parts',item.id);
    const identity={...item,route:flow?.route||item.route||detail.suggested_route,flow_stage:item.flow_stage||detail.flow_stage};
    let html=heading(itemLabel(identity),item.kind||'Fabrication item',controls,isSpool(identity)?identity:null)+(flowStatus()?.strip(state.catalog.stage_catalog,detail.flow_stage)||'')+(flowStatus()?.legend()||'')+lookup();
    if(removed())html+='<div class="fr-removed-notice"><strong>Removed record · History only</strong><p>Its process route, checks and timing are retained. Open Item &amp; QR record to review or restore its removed group.</p></div>';
    if(state.notice)html+=`<div class="ff-error" role="alert">${esc(state.notice)}</div>`;
    if(!flow){
      html+=`<section class="card"><h2>Start a numbered process route</h2>${metadata([['Item type',item.kind],['Project',item.project],['Location',item.location],['Current handler',item.handler]])}<p>Components follow steps 1–8, spools follow 9–16, and assemblies follow 17–24. Begin at the first step, or record a documented starting point for existing work.</p>${can('start')?action('start','Set up process route','','primary'):'<p class="muted">A supervisor or administrator can start this item’s route.</p>'}</section>`;
      return html+'<section class="card"><h2>The fabrication flow</h2>'+renderMap(false)+'</section>';
    }
    html+=`<section class="card"><div class="ff-section-head"><h2>${esc(routeNames[flow.route])} route · steps ${route(flow.route)?.first_step}–${route(flow.route)?.last_step}</h2>${tag(openExceptions().length?'rework':flow.status)}</div>${routeProgress()}${flow.baseline_reference?`<p class="ff-footer-note"><strong>Existing work starting point:</strong> ${esc(flow.baseline_reference)} · ${esc(flow.baseline_reason||'')} Earlier steps marked “Not recorded” have no completion recorded in this route.</p>`:''}</section>`;
    if(detail.parts?.configured){const t=detail.parts.totals||{},required=num(t.required_qty),prepared=num(t.prepared_qty);html+=`<section class="card"><div class="ff-section-head"><h2>Required component pieces</h2>${action('spool-parts','Spool parts',item.id)}</div><p>${prepared} of ${required} required pieces prepared for fit-up · ${num(t.assigned_qty)} assigned · ${num(t.received_qty)} receipt recorded · ${num(t.short_qty)} still to assign</p>${required>0?`<progress max="${required}" value="${Math.min(required,prepared)}" aria-label="Required pieces prepared for fit-up" style="width:100%"></progress>`:''}</section>`;}
    const boardRow=state.board.find(row=>row.item_id===item.id);
    html+=`<div class="ff-grid"><div>${currentStep()}${exceptions()}</div><div>${family()}<section class="card"><h2>Item record</h2>${metadata([['Project',boardRow?.project_id||flow.project_id||item.project],['Subproject',boardRow?.subproject_id||flow.subproject_id],['Location',item.location],['Current handler',item.handler],['Work status',(detail.transfer||item.transfer)?.status_label||'Not recorded'],['Drawing',item.drawing],['Release decision',(detail.release_control||item.release_control)?.label||(item.released?'Released':'Not released')]])}<p class="ff-footer-note">Each step stores its actor, time, checks, and reference. Quality acceptance and shipment remain separate records.</p></section></div></div>`;
    html+=`<section class="card"><details class="ff-fold"><summary>View the complete 24-step flow</summary><p class="ff-footer-note">Highlighted steps belong to this ${esc(routeNames[flow.route].toLowerCase())}. Other stages belong to its linked component, spool, or assembly records.</p>${renderMap(true)}</details></section>`;
    return html+timingHistory()+eventHistory();
  }
  function render(){
    if(!state.catalog)return;
    state.handoffControl?.destroy();state.handoffControl=null;
    node('flowContent').innerHTML=state.detail?renderDetail():renderBoard();
    node('flowContent').setAttribute('aria-busy','false');wire();startClocks();
  }
  function wire(){
    const lookupForm=node('flowLookupForm');
    if(lookupForm)lookupForm.onsubmit=async event=>{event.preventDefault();const sequence=state.sequence,lookup=state.lookup=(state.lookup||0)+1;try{const item=await readId(node('flowLookup').value);if(sequence!==state.sequence||lookup!==state.lookup)return;await open({item})}catch(error){if(sequence===state.sequence&&lookup===state.lookup)notify(errorText(error))}};
    for(const [id,key] of [['flowProject','project'],['flowSubproject','subproject'],['flowStatus','status']]){
      const element=node(id);if(element)element.onchange=()=>{state[key]=element.value;if(key==='project')state.subproject='';render();updateUrl()};
    }
    const search=node('flowSearch');if(search)search.oninput=()=>{state.query=search.value;const start=search.selectionStart,end=search.selectionEnd;render();node('flowSearch').focus();node('flowSearch').setSelectionRange(start,end)};
    const form=node('flowStepForm');if(form)form.onsubmit=submitStep;
    if(node('flowHandoffSender')){
      const transfer=state.detail.transfer||state.detail.item.transfer;
      const update=control=>{if(node('flowHandoffReview'))node('flowHandoffReview').innerHTML=window.FabHandoff.reviewHtml(control,transfer,state.handoffOptions,state.detail.item)};
      state.handoffControl=window.FabHandoff.bindControls('flowHandoff',{transfer,options:state.handoffOptions,onChange:update});update(state.handoffControl);
    }
  }
  async function save(path,payload){
    if(state.saving)return false;
    state.saving=true;const itemId=state.item,sequence=state.sequence;
    try{
      await api(path,{method:'POST',body:JSON.stringify(payload)});
      if(state.item!==itemId||state.sequence!==sequence)return false;
      state.notice='';notify('Process record saved.');
      await load();
      return true;
    }catch(error){
      if(state.item!==itemId||state.sequence!==sequence)return false;
      if(error.status===409){
        state.notice=errorText(error)+' The record has been refreshed. Review the current step before trying again.';
        state.dialogStale=true;
        if(state.item===itemId)await load();
      }
      throw error;
    }finally{state.saving=false}
  }
  async function submitStep(event){
    event.preventDefault();if(state.saving)return;
    const detail=state.detail,step=detail.flow.current,sequence=state.sequence;if(!can('advance')||!step)return;
    const values=Object.fromEntries(new FormData(event.target)),button=node('flowAdvance'),errorNode=node('flowStepError');
    button.disabled=true;errorNode.classList.add('hidden');
    try{
      const confirmations=arr(step.checks).filter(check=>values['check_'+check.id]==='on').map(check=>check.id);
      if(confirmations.length!==arr(step.checks).length)throw Error('Confirm every checklist item before completing this step.');
      const payload={expected_version:detail.flow.version,confirmations,notes:String(values.notes||'').trim()};
      if(step.requires_scan)payload.scanned_item_id=await readId(values.scanned_item_id);
      if(step.number===17){
        payload.scanned_child_ids=await Promise.all(String(values.scanned_child_ids||'').split(/\r?\n/).map(value=>value.trim()).filter(Boolean).map(value=>readId(value,'Linked spool ID')));
        if(!payload.scanned_child_ids.length)throw Error('Scan or enter each linked spool ID on its own line.');
      }
      if(step.requires_handoff){
        if(!state.handoffControl)throw Error('Refresh this handoff before identifying both employees.');
        Object.assign(payload,await state.handoffControl.read(values));
      }
      else if(step.requires_location||step.number===3){
        const transfer=detail.transfer||detail.item.transfer,location_id=String(values.location_id||'').trim();
        if(!transfer||!Number.isInteger(transfer.version))throw Error('Refresh the current location before completing this step.');
        if(!(location_id==='current'&&transfer.location)&&!arr(state.handoffOptions?.locations).some(row=>row.id===location_id&&row.active))throw Error('Choose an active storage or receiving location.');
        payload.location_id=location_id;payload.expected_transfer_version=transfer.version;
      }
      if(step.number===5)payload.target_spool_id=await readId(values.target_spool_id,'Assigned spool ID');
      if(step.requires_reference){payload.reference=String(values.reference||'').trim();if(!payload.reference)throw Error('Enter the required record or inspection reference.');}
      if(step.number===24)for(const key of ['carrier','shipment_reference','destination']){payload[key]=String(values[key]||'').trim();if(!payload[key])throw Error('Enter the carrier, shipping reference, and destination.');}
      if(step.qa&&openExceptions().some(row=>Number(row.step)===Number(step.number))){payload.resolution=String(values.resolution||'').trim();if(!payload.resolution)throw Error('Record the rework resolution and reinspection findings.');}
      if(state.sequence!==sequence||state.item!==detail.item.id)return;
      await save(ROOT+'/items/'+encode(detail.item.id)+'/advance',payload);
    }catch(error){
      if(state.sequence!==sequence)return;
      const target=node('flowStepError');if(target){target.textContent=errorText(error);target.classList.remove('hidden');target.scrollIntoView({block:'nearest'})}else notify(errorText(error));
    }finally{button.disabled=arr(state.detail?.flow?.blockers).length>0}
  }
  function dialog(title,content,callback,label='Save'){
    node('flowDialogTitle').textContent=title;node('flowDialogFields').innerHTML=content;
    node('flowDialogError').textContent='';node('flowDialogError').classList.add('hidden');
    node('flowDialogSubmit').textContent=label;node('flowDialogSubmit').disabled=false;
    state.dialogAction=callback;state.dialogStale=false;node('flowDialog').showModal();
  }
  function startFlow(){
    if(!can('start'))return;
    const item=state.detail.item,initial=state.detail.suggested_route||(item.kind==='Spool'?'spool':item.kind==='Assembly'?'assembly':'component');
    const configuredParts=state.detail.parts?.configured===true,requiredParts=num(state.detail.parts?.totals?.required_qty),orderScope=item.kind==='Assembly'&&state.detail.order_scope?.assembly_id===item.id?state.detail.order_scope:null,requiredSpools=num(orderScope?.required_spools),expectedFor=id=>id==='spool'&&configuredParts?requiredParts:id==='assembly'&&orderScope?requiredSpools:id==='component'?0:1;
    if(initial==='spool'&&configuredParts&&(!Number.isInteger(requiredParts)||requiredParts<1))return notify('Refresh the required parts list before starting this spool route.');
    if(initial==='assembly'&&orderScope&&(!Number.isInteger(requiredSpools)||requiredSpools<1))return notify('Refresh the PO assembly scope before starting this route.');
    const stepOptions=id=>arr(state.catalog.steps).filter(step=>step.route===id).map(step=>[step.number,`${step.number} · ${step.title}`]);
    const content='<p>A component, spool, and assembly are separate physical records. Start the route that matches this item.</p>'+(orderScope?`<p class="notice">PO <strong>${esc(orderScope.purchase_order)}</strong> · GPN / Assembly <strong>${esc(orderScope.gpn)}</strong>${orderScope.assembly_part_number!==orderScope.gpn?` · Retained part number <strong>${esc(orderScope.assembly_part_number)}</strong>`:''}<br>Required spools: <strong>${requiredSpools}</strong>, from Purchase orders. Confirm this count before starting; it becomes locked with this traveler.</p>`:'')+(configuredParts?`<p class="notice">Required component count: <strong>${requiredParts}</strong>, from Spool parts (${esc(state.detail.parts.reference||'current list')}). To correct the quantity, close this dialog and open Spool parts.</p>`:'')+fields(field('route','Route',initial,{required:true,options:arr(state.catalog.routes).map(row=>[row.id,`${row.label} · steps ${row.first_step}–${row.last_step}`])})+field('start_step','Start at step',route(initial)?.first_step,{required:true,options:stepOptions(initial)}))+`<div id="flowChildrenFields">${fields(field('expected_children','Expected child records',expectedFor(initial),{required:true,type:'number',min:0,max:10000,readonly:initial==='spool'&&configuredParts||initial==='assembly'&&Boolean(orderScope),help:orderScope?'Required assembly spools are managed in Purchase orders.':configuredParts?'Spool component quantities are managed in Spool parts.':'Component records for a spool; spool records for an assembly.'})+field('material_reference','Existing material basis (if no components will be linked)','',{maxlength:500,help:'For an existing spool with zero linked components, identify its approved material records.'}))}</div><div id="flowBaselineFields" class="hidden">${fields(field('baseline_reference','Existing-work record / traveler reference','',{maxlength:500,full:true})+field('baseline_reason','Why this item starts after the first route step','',{type:'textarea',maxlength:3000,full:true}))}<p class="ff-form-help">Earlier steps will be marked “Not recorded.” This does not create historical completion or inspection approvals.</p></div>`+fields(field('notes','Setup notes','',{type:'textarea',maxlength:3000,full:true}));
    dialog('Set up process route · '+item.id,content,async values=>{
      const selected=route(values.route),start=Number(values.start_step),expected=values.route==='component'?0:Number(values.expected_children);
      if(!selected||!Number.isInteger(start)||start<selected.first_step||start>selected.last_step)throw Error('Choose a step within this route.');
      if(!Number.isInteger(expected)||expected<0)throw Error('Expected linked items must be a whole number of zero or more.');
      if(values.route==='spool'&&configuredParts&&expected!==requiredParts)throw Error('The component count must match the current required parts list. Edit quantities in Spool parts.');
      if(values.route==='assembly'&&orderScope&&expected!==requiredSpools)throw Error('The spool count must match the PO assembly scope. Review it in Purchase orders before starting the traveler.');
      const payload={route:values.route,expected_children:expected,start_step:start,notes:String(values.notes||'').trim()};
      if(values.route==='assembly'&&expected<1)throw Error('An assembly needs at least one expected spool.');
      if(values.route==='spool'){payload.material_reference=String(values.material_reference||'').trim();if(!expected&&!payload.material_reference)throw Error('Identify the existing material records when no components will be linked.');}
      if(start>selected.first_step){payload.baseline_reference=String(values.baseline_reference||'').trim();payload.baseline_reason=String(values.baseline_reason||'').trim();if(!payload.baseline_reference||!payload.baseline_reason)throw Error('Enter the existing-work reference and the reason for its starting point.');}
      return save(ROOT+'/items/'+encode(item.id)+'/start',payload);
    },'Start route');
    const updateFields=()=>{
      const selected=node('ff-field-route').value,first=route(selected)?.first_step;
      node('flowChildrenFields').classList.toggle('hidden',selected==='component');
      node('ff-field-expected_children').disabled=selected==='component';
      node('ff-field-expected_children').readOnly=selected==='spool'&&configuredParts||selected==='assembly'&&Boolean(orderScope);
      node('ff-field-material_reference').disabled=selected!=='spool';
      const late=Number(node('ff-field-start_step').value)>first;
      node('flowBaselineFields').classList.toggle('hidden',!late);
      for(const key of ['baseline_reference','baseline_reason']){node('ff-field-'+key).required=late;node('ff-field-'+key).disabled=!late;}
    };
    node('ff-field-route').onchange=()=>{const id=node('ff-field-route').value;node('ff-field-start_step').innerHTML=stepOptions(id).map(row=>option(row[0],row[1],route(id)?.first_step)).join('');node('ff-field-start_step').value=String(route(id)?.first_step);node('ff-field-expected_children').value=String(expectedFor(id));updateFields()};
    node('ff-field-start_step').onchange=updateFields;updateFields();
  }
  function failStep(){
    if(!can('fail'))return;
    const detail=state.detail,step=detail.flow.current,choices=arr(step.return_steps);
    dialog('Record failure · step '+step.number,'<p>The exception stays in the history. The item returns to the selected process and requires a new inspection before continuing.</p>'+fields(field('reason','Failure / nonconformance and required repair','',{required:true,type:'textarea',full:true,maxlength:3000})+field('reference','Inspection / NCR reference','',{required:true,maxlength:500,full:true})+field('return_step','Return to step',choices[0],{required:true,options:choices.map(number=>[number,`${number} · ${definition(number)?.title||''}`])})),async values=>{
      const payload={expected_version:detail.flow.version,reason:String(values.reason||'').trim(),reference:String(values.reference||'').trim(),return_step:Number(values.return_step)};
      if(!payload.reason||!payload.reference)throw Error('Record the failure reason and inspection reference.');
      if(!choices.includes(payload.return_step))throw Error('Choose an allowed return step.');
      return save(ROOT+'/items/'+encode(detail.item.id)+'/fail',payload);
    },'Record exception & return');
  }
  function editScope(){
    if(!can('scope'))return;
    const detail=state.detail,flow=detail.flow,assembly=flow.route==='assembly',linked=arr(assembly?detail.spools:detail.components).length;
    if(assembly&&detail.order_scope)return notify('This assembly spool count is managed in Purchase orders and is locked by its existing traveler.');
    if(!assembly&&detail.parts?.configured)return window.FabParts.open({spool:detail.item.id,project:flow.project_id||state.project});
    dialog('Edit required '+(assembly?'spool':'component')+' count',`<p>${flow.route==='spool'?spoolText({...detail.item,flow_stage:detail.item.flow_stage||detail.flow_stage}):esc(detail.item.id)} has ${linked} linked ${assembly?'spools':'components'}. Record the corrected scope and its authorization reference.</p>`+fields(field('expected_children','Required '+(assembly?'spools':'components'),flow.expected_children,{required:true,type:'number',min:Math.max(linked,assembly?1:0),max:10000})+(!assembly?field('material_reference','Existing material basis (required for zero components)',flow.material_reference||'',{maxlength:500}):'')+field('reference','Scope / drawing / authorization reference','',{required:true,minlength:2,maxlength:500,full:true})+field('reason','Reason for the count correction','',{required:true,type:'textarea',maxlength:3000,full:true})),values=>{
      const expected=Number(values.expected_children),reason=String(values.reason||'').trim(),reference=String(values.reference||'').trim(),material=String(values.material_reference||'').trim();
      if(!Number.isInteger(expected)||expected<Math.max(linked,assembly?1:0))throw Error('The required count cannot be lower than the linked scope. Assemblies need at least one spool.');
      if(!assembly&&!expected&&material.length<2)throw Error('Identify the existing material records when no components will be linked.');
      if(reason.length<4||reference.length<2)throw Error('Enter the correction reason and authorization reference.');
      return save(ROOT+'/items/'+encode(detail.item.id)+'/scope',{expected_version:flow.version,expected_children:expected,material_reference:material,reason,reference});
    },'Save scope correction');
  }
  function linkItem(kind){
    if(!can(kind))return;
    const detail=state.detail,assigning=kind==='assign-component',sequence=state.sequence;
    dialog(assigning?'Assign component to spool':'Link spool to assembly',`<p>${esc(detail.item.display_code||detail.item.id)} · ${assigning?'Assign this component to its existing spool record.':'Add an existing spool to this assembly. Verify its physical QR label or tracking ID.'}</p>`+fields(field('spool_id','Scan or enter spool label',assigning?detail.parent?.item_id||'':'',{required:true,maxlength:2000})+field('reference','BOM / drawing / link reference','',{maxlength:500})+field('notes','Link notes','',{type:'textarea',full:true,maxlength:3000})),async values=>{
      const spoolId=await readId(values.spool_id,'Spool label');
      if(state.sequence!==sequence||state.item!==detail.item.id||!node('flowDialog').open)return false;
      return save(ROOT+'/items/'+encode(detail.item.id)+'/'+kind,{expected_version:detail.flow.version,spool_id:spoolId,reference:String(values.reference||'').trim(),notes:String(values.notes||'').trim()});
    },assigning?'Assign component':'Link spool');
  }
  function deliver(){
    if(!can('deliver'))return;
    const detail=state.detail;
    dialog('Record customer delivery','<p>Record the customer’s acknowledgment after the shipped assembly arrives.</p>'+fields(field('receipt_reference','Delivery receipt / proof of delivery','',{required:true,maxlength:500,full:true})+field('recipient','Received by / customer representative','',{required:true,maxlength:200,full:true})+field('notes','Delivery notes','',{type:'textarea',full:true,maxlength:3000})),values=>{
      const payload={expected_version:detail.flow.version,receipt_reference:String(values.receipt_reference||'').trim(),recipient:String(values.recipient||'').trim(),notes:String(values.notes||'').trim()};
      if(!payload.receipt_reference||!payload.recipient)throw Error('Enter the delivery receipt reference and recipient.');
      return save(ROOT+'/items/'+encode(detail.item.id)+'/deliver',payload);
    },'Record delivery');
  }
  function pauseProcess(actionName){
    if(!can(actionName))return;
    const detail=state.detail,process=detail.production_process;
    dialog(actionName==='pause'?'Pause process / record delay':'Resume process',`<p>${esc(detail.flow.current?.title||'Current process')}</p>`+fields(field('notes',actionName==='pause'?'Delay reason':'Resume notes','',{required:actionName==='pause',type:'textarea',full:true,maxlength:2000})),values=>{
      const notes=String(values.notes||'').trim();if(actionName==='pause'&&notes.length<3)throw Error('Record a delay reason of at least 3 characters.');
      return save('/api/tracking/spools/'+encode(detail.item.id)+'/process',{action:actionName,expected_version:process.version,notes});
    },actionName==='pause'?'Pause process':'Resume process');
  }
  async function act(name,id){
    if(name==='board')return open({project:state.project});
    if(name==='refresh')return refresh();
    if(name==='item')return open({item:id});
    if(name==='item-record')return openItem(id);
    if(name==='admin-controls'&&me?.role==='admin')return window.FabAdmin.open({item:id});
    if(name==='weld-record')return window.FabTracking.open({spool:id});
    if(name==='spool-parts')return window.FabParts.open({spool:id,project:state.project});
    if(name==='filter-step'){state.step=id;state.item='';state.detail=null;render();updateUrl();return;}
    if(name==='clear-step'){state.step='';render();return;}
    if(name==='start')return startFlow();
    if(name==='fail')return failStep();
    if(name==='scope')return editScope();
    if(name==='assign-component'||name==='link-spool')return linkItem(name);
    if(name==='deliver')return deliver();
    if(name==='pause'||name==='resume')return pauseProcess(name);
  }
  node('flowContent').addEventListener('click',async event=>{
    const button=event.target.closest('[data-flow-action]');if(!button||button.disabled||state.saving)return;
    try{await act(button.dataset.flowAction,button.dataset.flowId)}catch(error){notify(errorText(error))}
  });
  node('flowDialogForm').addEventListener('submit',async event=>{
    event.preventDefault();if(!state.dialogAction||state.saving||state.dialogStale||node('flowDialogSubmit').disabled)return;
    const values=Object.fromEntries(new FormData(event.target));node('flowDialogSubmit').disabled=true;node('flowDialogError').classList.add('hidden');
    try{if(await state.dialogAction(values)!==false)node('flowDialog').close()}
    catch(error){node('flowDialogError').textContent=errorText(error)+(state.dialogStale?' Close this dialog and choose the action again using the refreshed record.':'');node('flowDialogError').classList.remove('hidden');node('flowDialogError').scrollIntoView({block:'nearest'})}
    finally{node('flowDialogSubmit').disabled=state.dialogStale}
  });
  node('flowDialogClose').onclick=()=>node('flowDialog').close();
  node('flowDialogCancel').onclick=()=>node('flowDialog').close();
  node('navFlow').onclick=()=>open();
  node('itemFlowBtn').onclick=()=>{if(current)open({item:current.id})};
  window.FabFlow={open,refresh,cancelPending(){state.sequence++;stopClocks();state.handoffControl?.destroy();state.handoffControl=null}};
})();
