/* Open, evidenced inspection failures. Existing source records own all corrections and decisions. */
(() => {
  'use strict';
  const node=id=>document.getElementById(id),encode=encodeURIComponent;
  const arr=value=>Array.isArray(value)?value:[],text=value=>String(value??'');
  const esc=value=>text(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const types=[['QA-001','Material'],['QA-002','Isometric Dimensions Test'],['QA-003','Weld Inspection'],['QA-004','NDT Results'],['QA-005','Verify Pressure Testing'],['QA-006','Final Inspection']];
  const statuses={return_required:'Return for rework required',needs_rework:'Rework required',awaiting_reinspection:'Awaiting QA/QC reinspection'};
  const filterStatuses=['return_required','needs_rework','awaiting_reinspection','needs_routing_review'];
  const state={inspection:'',project:'',query:'',status:'',spools:[],active:false,sequence:0,pending:null,opening:false,loaded:false,materialDialog:null};
  const natural=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});
  const itemId=row=>text(row?.item_id).trim();
  const spoolName=row=>window.FabFlowStatus?.spoolNumber?.(row)||row.qr_alias||row.spool_number||itemId(row);
  const spoolText=row=>window.FabFlowStatus?.spoolText?window.FabFlowStatus.spoolText(row,spoolName(row)):esc(spoolName(row));
  const typeLabel=code=>code.replace('QA-','QA/QC-')+' - '+(types.find(row=>row[0]===code)?.[1]||'Inspection');
  const tag=(label,kind='')=>`<span class="fif-tag${kind?' '+esc(kind):''}">${esc(label)}</span>`;
  const button=(action,label,extra='',className='')=>`<button type="button"${className?` class="${esc(className)}"`:''} data-failure-action="${esc(action)}"${extra}>${esc(label)}</button>`;
  const option=(value,label,current)=>`<option value="${esc(value)}"${text(value)===text(current)?' selected':''}>${esc(label)}</option>`;
  const stamp=value=>{const date=new Date(value);return value&&Number.isFinite(date.getTime())?date.toLocaleString():'Not recorded';};
  const failureKey=failure=>text(failure.source_item_id)+'|'+text(failure.id);
  function uniqueFindings(spools){const result=new Map();for(const spool of spools)for(const failure of spool.failures)result.set(failureKey(failure),failure);return [...result.values()];}
  function normalizeSpools(values){
    const records=new Map();
    for(const value of values){
      if(!value||!itemId(value)||!Array.isArray(value.failures))throw Error('An affected spool could not be verified. Refresh to load the current failed inspections.');
      let row=records.get(itemId(value));if(!row){row={...value,item_id:itemId(value),failures:[]};records.set(row.item_id,row);}
      const known=new Set(row.failures.map(failureKey));
      for(const failure of value.failures){
        if(!failure||!text(failure.id)||!text(failure.source_item_id)||!text(failure.inspection_key))throw Error('A failure record could not be verified. Refresh to load its recorded finding.');
        if(!known.has(failureKey(failure))){row.failures.push({...failure});known.add(failureKey(failure));}
      }
    }
    return [...records.values()].filter(row=>row.failures.length).sort((a,b)=>natural.compare(spoolName(a),spoolName(b))||natural.compare(a.item_id,b.item_id));
  }
  function matchesInspection(failure){
    if(!state.inspection)return true;
    return failure.inspection_key===(state.inspection==='legacy_testing'?'legacy_testing':state.inspection.replace('QA-',''));
  }
  function matchesStatus(failure){
    return !state.status||state.status==='needs_routing_review'&&failure.routing_known===false||failure.status===state.status;
  }
  function visibleSpools(){
    const query=state.query.trim().toLowerCase();
    return state.spools.filter(row=>!state.project||row.project_id===state.project).map(row=>{
      const identityMatch=!query||[row.item_id,spoolName(row),row.description,row.project_id,row.project_name,row.purchase_order,row.assembly_id,row.assembly_number].some(value=>text(value).toLowerCase().includes(query));
      return {...row,failures:row.failures.filter(failure=>matchesInspection(failure)&&matchesStatus(failure)&&(identityMatch||[
        failure.title,failure.display_qa_code,failure.reason,failure.reference,failure.source_item_id,failure.piece_identifier,failure.piece_key,
        failure.return_title,failure.return_station?.label,...arr(failure.return_positions),...arr(failure.return_roles),failure.return_employee?.name,failure.return_employee?.badge,failure.correction?.description,
      ].some(value=>text(value).toLowerCase().includes(query))))};
    }).filter(row=>row.failures.length);
  }
  function updateUrl(){
    const query=new URLSearchParams({'inspection-failures':'1'});
    if(state.inspection)query.set('inspection',state.inspection);if(state.project)query.set('project',state.project);if(state.query)query.set('q',state.query);if(state.status)query.set('status',state.status);
    history.replaceState(null,'','/?'+query.toString());
  }
  function cancelRead(){const pending=state.pending;if(!pending)return;state.pending=null;clearTimeout(pending.timer);pending.controller.abort();}
  function cancelPending(){state.active=false;state.sequence++;cancelRead();state.opening=false;state.materialDialog=null;}
  function errorText(error){return text(error?.message||'The failed inspection records could not be loaded.');}
  async function load(){
    const sequence=++state.sequence,badge=me?.badge;cancelRead();
    const pending={controller:new AbortController(),timer:null,timedOut:false};state.pending=pending;
    pending.timer=setTimeout(()=>{pending.timedOut=true;pending.controller.abort();},30000);
    const content=node('inspectionFailuresContent');content.setAttribute('aria-busy','true');
    content.innerHTML='<div class="fif-state" role="status">Loading failed inspections…</div>';
    try{
      const result=await api('/api/flow/inspection-failures',{signal:pending.controller.signal});
      if(!state.active||sequence!==state.sequence||badge!==me?.badge)return;
      if(!Array.isArray(result?.spools))throw Error('The failed inspection response could not be verified. Refresh to try again.');
      state.spools=normalizeSpools(result.spools);state.loaded=true;render();updateUrl();
    }catch(error){
      if(!state.active||sequence!==state.sequence||badge!==me?.badge)return;
      const description=pending.timedOut?'This request took too long. Refresh to load the current failed inspections.':errorText(error);
      content.innerHTML=`<div class="fif-state fif-error" role="alert"><strong>Failed inspections could not be loaded.</strong><p>${esc(description)}</p>${button('refresh','Try again')}</div>`;
    }finally{
      clearTimeout(pending.timer);pending.controller.abort();if(state.pending===pending)state.pending=null;
      if(state.active&&sequence===state.sequence)content.setAttribute('aria-busy','false');
    }
  }
  async function open(options={}){
    if(typeof me==='undefined'||!me)return;
    if(show('inspectionFailuresPage')===false)return;
    if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;state.active=true;state.materialDialog=null;
    if(options.resetFilters===true){state.inspection='';state.project='';state.query='';state.status='';}
    if(Object.prototype.hasOwnProperty.call(options,'inspection'))state.inspection=types.some(row=>row[0]===options.inspection)||options.inspection==='legacy_testing'?options.inspection:'';
    for(const key of ['project','query'])if(Object.prototype.hasOwnProperty.call(options,key))state[key]=text(options[key]);
    if(Object.prototype.hasOwnProperty.call(options,'status'))state.status=filterStatuses.includes(options.status)?options.status:'';
    await load();
  }
  function filters(){
    const projects=[...new Set([...state.spools.map(row=>row.project_id),state.project].filter(Boolean))].sort(natural.compare);
    const legacy=state.inspection==='legacy_testing'||state.spools.some(row=>row.failures.some(failure=>failure.inspection_key==='legacy_testing'));
    return `<div class="fif-filters"><div class="field"><label for="failureInspection">Failed inspection</label><select id="failureInspection">${option('','All inspections',state.inspection)}${types.map(([code])=>option(code,typeLabel(code),state.inspection)).join('')}${legacy?option('legacy_testing','Earlier testing review · type not recorded',state.inspection):''}</select></div><div class="field"><label for="failureProject">Project</label><select id="failureProject">${option('','All projects',state.project)}${projects.map(project=>option(project,project,state.project)).join('')}</select></div><div class="field"><label for="failureStatus">Required follow-up</label><select id="failureStatus">${option('','All open failures',state.status)}${filterStatuses.map(status=>option(status,status==='needs_routing_review'?'Return routing needs review':statuses[status],state.status)).join('')}</select></div><div class="field fif-search"><label for="failureSearch">Find spool, defect, or destination</label><input id="failureSearch" type="search" value="${esc(state.query)}" placeholder="Spool, assembly, P.O., defect or station" autocomplete="off"></div></div>`;
  }
  function metrics(spools){
    const failures=uniqueFindings(spools),rework=failures.filter(failure=>['needs_rework','return_required'].includes(failure.status)).length,reinspection=failures.filter(failure=>failure.status==='awaiting_reinspection').length;
    const values=[['Affected physical spools',spools.length],['Open failed inspections',failures.length],['Correction required',rework],['Awaiting QA/QC reinspection',reinspection]];
    return `<div class="fif-metrics">${values.map(([label,value])=>`<div class="fif-metric"><span>${esc(label)}</span><strong>${value}</strong></div>`).join('')}</div>`;
  }
  function returnDetails(failure){
    const positions=arr(failure.return_positions).filter(value=>typeof value==='string'&&value.trim()),roleLabels=positions.length?positions:arr(failure.return_roles).map(role=>window.FabPermissions?.label?.(role)||role);
    const routingKnown=failure.routing_known===true,destination=routingKnown&&failure.return_station?.label?failure.return_station.label:'Return station needs review',person=failure.return_employee;
    const detail=failure.routing_known===false?`<p class="fif-routing-warning">${esc(failure.routing_note||'The recorded failure does not establish a verified return destination. Open its source record to review the required routing.')}</p>`:failure.routing_note?`<p class="fif-secondary">${esc(failure.routing_note)}</p>`:'';
    return `<div class="fif-return"><div><span>Required return station</span><strong>${esc(destination)}</strong>${routingKnown&&failure.return_title?`<small>${esc(failure.return_title)}</small>`:''}</div><div><span>Responsible job position</span><strong>${esc(routingKnown&&roleLabels.length?roleLabels.join(' / '):'Responsible position needs review')}</strong>${person?.badge||person?.name?`<small>Recorded employee: ${esc(person.name||person.badge)}${person.name&&person.badge?' ('+esc(person.badge)+')':''}</small>`:''}</div>${detail}</div>`;
  }
  function correctionDetails(failure){
    const correction=failure.correction;
    if(!correction)return '<p class="fif-pending"><strong>Completed correction has not been recorded.</strong> Open the source record for the return and rework controls.</p>';
    return `<section class="fif-correction"><h4>Recorded completed correction</h4><p class="fif-prose">${esc(correction.description||'Correction details not recorded.')}</p><p class="fif-secondary">${esc(correction.actor||'Employee not recorded')} · ${esc(stamp(correction.at))}${correction.reference?' · '+esc(correction.reference):''}</p><p class="fif-reinspection">${failure.status==='awaiting_reinspection'?'Awaiting QA/QC reinspection. This failed inspection remains open until the corrected work is accepted.':'This failed inspection is still open. Review the current record for the remaining return, rework, and QA/QC requirements.'}</p></section>`;
  }
  function failureCard(spool,failure){
    const label=failure.title||failure.display_qa_code||'Recorded inspection failure',scope=failure.scope==='assembly'?'Assembly inspection':failure.scope==='component'?'Component inspection':'Spool inspection';
    const source=failure.source_item_id,sourceDescription=failure.scope==='assembly'?'This finding applies to the linked spool. Its correction and QA/QC decision are recorded on the assembly.':failure.scope==='component'?'This finding belongs to a component assigned to this physical spool.':'This finding belongs to this physical spool.';
    const controls=failure.open_item_id&&['flow','material'].includes(failure.open_kind)?button('open-record',failure.open_kind==='material'?'Open material inspection':failure.scope==='assembly'?'Open assembly review':failure.scope==='component'?'Open component review':'Open spool review',` data-failure-id="${esc(failure.id)}" data-failure-spool="${esc(spool.item_id)}"`,'primary'):'<span class="fif-routing-warning">Source record needs review before an action can be opened.</span>';
    const saved=(failure.saved_qa_code&&failure.saved_qa_code!==failure.qa_code)||(failure.saved_title&&failure.saved_title!==failure.title);
    return `<article class="fif-failure" data-inspection-failure="${esc(failure.id)}" data-failure-status="${esc(failure.status)}"><div class="fif-failure-head"><div><span class="fif-eyebrow">${esc(scope)}</span><h3>${esc(label)}</h3>${failure.piece_identifier||failure.piece_key?`<p class="fif-secondary">Material piece: ${esc(failure.piece_identifier||failure.piece_key)}</p>`:''}</div>${tag(statuses[failure.status]||'Review required',failure.status==='awaiting_reinspection'?'reinspection':'needs-work')}</div><div class="fif-defect"><h4>Recorded defect / reason for failure</h4><p class="fif-prose">${esc(text(failure.reason).trim()||'Failure description not recorded. Open the source record to review the finding.')}</p><p class="fif-secondary">Reported by ${esc(failure.actor||'Not recorded')} · ${esc(stamp(failure.at))}${failure.reference?' · Reference: '+esc(failure.reference):''}</p></div>${returnDetails(failure)}${correctionDetails(failure)}<div class="fif-source"><div><p><strong>Source record:</strong> ${esc(source)}</p><p>${esc(sourceDescription)}</p>${saved?`<p class="fif-secondary">Originally recorded as ${esc(failure.saved_title||failure.saved_qa_code)}.</p>`:''}${failure.source_released?'<p class="fif-routing-warning">The source record is released. Open it to review the available return controls.</p>':''}</div>${controls}</div></article>`;
  }
  function spoolCard(spool){
    const metadata=[spool.purchase_order?'P.O. '+spool.purchase_order:'',spool.project_id||'',spool.assembly_number?'Assembly '+spool.assembly_number:spool.assembly_id?'Assembly '+spool.assembly_id:''].filter(Boolean);
    return `<section class="card fif-spool" data-failed-spool="${esc(spool.item_id)}"><div class="fif-spool-head"><div><span class="fif-eyebrow">Affected physical spool</span><h2>${spoolText(spool)}</h2>${spool.item_id!==spoolName(spool)?`<p class="fif-secondary">Record ${esc(spool.item_id)}</p>`:''}${metadata.length?`<p class="fif-secondary">${metadata.map(esc).join(' · ')}</p>`:''}</div><div class="fif-spool-tags">${tag(spool.failures.length+' open finding'+(spool.failures.length===1?'':'s'),'needs-work')}${spool.released?tag('Released spool'):''}</div></div>${spool.failures.map(failure=>failureCard(spool,failure)).join('')}</section>`;
  }
  function empty(){
    const filtered=Boolean(state.inspection||state.project||state.query||state.status);
    return `<div class="fif-state fif-empty"><strong>${filtered?'No open failures match these filters.':'No open failed inspections.'}</strong><p>${filtered?'Clear a filter to view other affected physical spools.':'No unresolved inspection failures were found for the active physical spools.'}</p><p>Other inspection records are available in Inspections.</p>${button('inspections','Open Inspections')}</div>`;
  }
  function render(){
    if(!state.active||!state.loaded)return;
    const spools=visibleSpools();
    node('inspectionFailuresContent').innerHTML=`<div class="fif-head"><div><span class="fif-eyebrow">CLM fabrication · QA/QC follow-up</span><h1>Failed Inspections</h1><p>Find the affected spool, the failed inspection, and where the corrective work must go.</p></div><div class="actions">${button('inspections','All inspections')}${button('refresh','Refresh')}</div></div>${filters()}${metrics(spools)}<p class="fif-note">Completed rework stays on this list while QA/QC reinspection is outstanding. An assembly finding appears under each affected physical spool and counts once in the open-inspection total.</p>${spools.length?spools.map(spoolCard).join(''):empty()}`;
    wireFilters();
  }
  function wireFilters(){
    for(const [id,key] of [['failureInspection','inspection'],['failureProject','project'],['failureStatus','status']]){
      const input=node(id);if(input)input.onchange=()=>{state[key]=input.value;render();updateUrl();};
    }
    const search=node('failureSearch');if(search)search.oninput=()=>{
      state.query=search.value;const start=search.selectionStart,end=search.selectionEnd;render();const replacement=node('failureSearch');replacement?.focus();
      if(typeof replacement?.setSelectionRange==='function'&&start!==null)replacement.setSelectionRange(start,end);updateUrl();
    };
  }
  async function openRecord(spoolId,failureId,trigger){
    const spool=visibleSpools().find(row=>row.item_id===spoolId),failure=spool?.failures.find(row=>text(row.id)===failureId);
    if(!state.active||state.opening||!failure||!failure.open_item_id)return;
    state.opening=true;
    try{
      const target=text(failure.open_item_id);
      if(failure.open_kind==='material'){
        if(!window.FabSpoolBom?.open)throw Error('The material inspection screen is unavailable. Refresh FabTrace and try again.');
        const physical=state.spools.find(row=>row.item_id===target)||{item_id:target};
        const owner={badge:me?.badge,item_id:target};state.materialDialog=owner;
        try{
          await window.FabSpoolBom.open({api_url:'/api/spool-boms/spools/'+encode(target),item_id:target,spool_number:spoolName(physical)},trigger);
          const dialog=node('spoolBomDialog');if(dialog&&!dialog.open&&state.materialDialog===owner)state.materialDialog=null;
        }catch(error){if(state.materialDialog===owner)state.materialDialog=null;throw error;}
      }else if(failure.open_kind==='flow'){
        if(!window.FabFlow?.open)throw Error('The source inspection record is unavailable. Refresh FabTrace and try again.');
        await window.FabFlow.open({item:target,project:spool.project_id||state.project});
      }
    }finally{state.opening=false;}
  }
  node('inspectionFailuresContent').addEventListener('click',async event=>{
    const target=event.target.closest('[data-failure-action]');if(!target||target.disabled||!state.active)return;
    try{
      if(target.dataset.failureAction==='refresh')return await load();
      if(target.dataset.failureAction==='inspections')return await window.FabInspections?.open({inspection:types.some(row=>row[0]===state.inspection)?state.inspection:'QA-001',project:state.project,query:state.query,status:''});
      if(target.dataset.failureAction==='open-record')await openRecord(target.dataset.failureSpool,target.dataset.failureId,target);
    }catch(error){notify(errorText(error));}
  });
  node('spoolBomDialog')?.addEventListener('close',()=>{
    const owner=state.materialDialog;state.materialDialog=null;
    if(owner&&state.active&&owner.badge===me?.badge)return load();
  });
  node('navInspectionFailures').onclick=()=>open({resetFilters:true});
  window.FabInspectionFailures={open,refresh:()=>state.active?load():Promise.resolve(),cancelPending,navigationState(){return {inspection:state.inspection,project:state.project,query:state.query,status:state.status};},canNavigateAway:()=>true};
})();
