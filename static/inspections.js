/* Inspection entry points. Existing material and traveler screens own every decision. */
(() => {
  'use strict';
  const node=id=>document.getElementById(id),encode=encodeURIComponent;
  const arr=value=>Array.isArray(value)?value:[],text=value=>String(value??'');
  const esc=value=>text(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const inspections=[
    {code:'QA-001',label:'QA/QC-001',name:'Material',scope:'material',step:2,description:'Review each material piece and the spool’s receiving inspection.'},
    {code:'QA-002',label:'QA/QC-002',name:'Isometric Dimensions Test',scope:'spool',step:11,description:'Review the physical spool’s dimensions and fit-up against its isometric.'},
    {code:'QA-003',label:'QA/QC-003',name:'Weld Inspection',scope:'spool',step:15,description:'Review the spool’s weld inspection records and required acceptance checks.'},
    {code:'QA-004',label:'QA/QC-004',name:'NDT Results',scope:'assembly',step:18,phase:'ndt_qa',description:'Review the recorded NDT results for the assembly and its linked spools.'},
    {code:'QA-005',label:'QA/QC-005',name:'Verify Pressure Testing',scope:'assembly',step:18,phase:'pressure_qa',description:'Review the pressure-test results and their separate QA/QC decision.'},
    {code:'QA-006',label:'QA/QC-006',name:'Final Inspection',scope:'assembly',step:22,description:'Review the final condition, required documentation, and release checks.'},
  ];
  const state={inspection:'QA-001',project:'',query:'',status:'',catalog:null,travelers:[],spools:[],active:false,sequence:0,pending:null,opening:false};
  const selected=()=>inspections.find(row=>row.code===state.inspection)||inspections[0];
  const definition=code=>inspections.find(row=>row.code===code);
  const title=row=>row.label+' - '+row.name;
  const button=(action,label,id='',className='')=>`<button type="button"${className?` class="${esc(className)}"`:''} data-inspection-action="${esc(action)}"${id?` data-inspection-id="${esc(id)}"`:''}>${esc(label)}</button>`;
  const option=(value,label,current)=>`<option value="${esc(value)}"${text(value)===text(current)?' selected':''}>${esc(label)}</option>`;
  const tag=(label,className='')=>`<span class="fi-tag${className?' '+esc(className):''}">${esc(label)}</span>`;
  const natural=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});
  const itemId=row=>text(row?.item_id||row?.id).trim();
  const spoolName=row=>window.FabFlowStatus?.spoolNumber?.(row)||row.qr_alias||row.spool_number||row.google_part_number||itemId(row);
  const recordName=row=>row.record_kind==='spool'?spoolName(row):row.record_kind==='assembly'&&row.assembly_number?'Assembly '+row.assembly_number:itemId(row);
  const displayName=row=>row.record_kind==='spool'&&window.FabFlowStatus?.spoolText?window.FabFlowStatus.spoolText(row,recordName(row)):esc(recordName(row));
  const attention=row=>Number(row.open_exceptions)>0||row.blocked===true||row.flow_stage?.blocked===true||arr(row.blockers).length>0;
  function unique(rows){const result=new Map();for(const row of rows){const id=itemId(row);if(id&&!result.has(id))result.set(id,{...row,item_id:id});}return result;}
  function currentReview(row,inspection=selected()){
    const traveler=row.traveler;
    if(!traveler||traveler.status!=='active'||traveler.released===true||Number(traveler.current_step)!==inspection.step)return false;
    const expectedRoute=inspection.scope==='material'?'component':inspection.scope;
    if(traveler.route!==expectedRoute)return false;
    // The retained testing traveler also used QA-004 for pressure. Its actual
    // phase, never a display number or a last-recorded station, identifies it.
    if(inspection.phase)return traveler.current_testing_phase===inspection.phase;
    return true;
  }
  function allRecords(inspection=selected()){
    const travelers=unique(state.travelers),spools=unique(state.spools),records=new Map();
    if(inspection.scope!=='assembly'){
      for(const [id,spool] of spools){
        const traveler=travelers.get(id);
        records.set(id,{...traveler,...spool,traveler,record_kind:'spool',open_kind:inspection.scope==='material'?'material':'flow'});
      }
      if(inspection.scope==='material')for(const [id,traveler] of travelers){
        if(traveler.route==='component'&&!records.has(id))records.set(id,{...traveler,traveler,record_kind:'component',open_kind:'flow'});
      }
    }else{
      for(const [id,traveler] of travelers){
        if(traveler.route==='assembly')records.set(id,{...traveler,traveler,record_kind:'assembly',open_kind:'flow',linked_spools:[]});
      }
      for(const spool of spools.values()){
        const parent=text(spool.assembly_id).trim();if(!parent)continue;
        let row=records.get(parent);
        if(!row){
          row={item_id:parent,record_kind:'assembly',open_kind:'flow',linked_spools:[],project_id:spool.project_id||'',project_name:spool.project_name||'',purchase_order:spool.purchase_order||'',assembly_number:spool.assembly_number||'',gpn:spool.gpn||'',traveler:null,status:'not_started'};
          records.set(parent,row);
        }
        row.linked_spools.push(spool);
        for(const field of ['assembly_number','purchase_order','project_id','project_name','gpn'])if(!row[field]&&spool[field])row[field]=spool[field];
      }
    }
    return [...records.values()].sort((a,b)=>Number(currentReview(b,inspection))-Number(currentReview(a,inspection))||Number(attention(b))-Number(attention(a))||natural.compare(recordName(a),recordName(b))||natural.compare(a.item_id,b.item_id));
  }
  function scopedRecords(inspection=selected()){
    const query=state.query.trim().toLowerCase();
    return allRecords(inspection).filter(row=>(!state.project||row.project_id===state.project)&&(!query||[
      row.item_id,recordName(row),row.description,row.project_id,row.project_name,row.purchase_order,row.assembly_id,row.assembly_number,row.gpn,
      ...arr(row.linked_spools).flatMap(spool=>[spool.item_id,spoolName(spool),spool.description]),
    ].some(value=>text(value).toLowerCase().includes(query))));
  }
  function visibleRecords(){return scopedRecords().filter(row=>state.status==='current'?currentReview(row):state.status==='attention'?attention(row):true);}
  function updateUrl(){
    const query=new URLSearchParams({inspections:'1',inspection:state.inspection});
    if(state.project)query.set('project',state.project);if(state.query)query.set('q',state.query);if(state.status)query.set('status',state.status);
    history.replaceState(null,'','/?'+query.toString());
  }
  function cancelRead(){const pending=state.pending;if(!pending)return;state.pending=null;clearTimeout(pending.timer);pending.controller.abort();}
  function cancelPending(){state.active=false;state.sequence++;cancelRead();state.opening=false;}
  function message(error){
    if(error?.name==='AbortError')return 'The inspection records request was interrupted. Refresh to try again.';
    return text(error?.message||'The inspection records could not be loaded.');
  }
  async function load(){
    const sequence=++state.sequence,badge=me?.badge;cancelRead();
    const pending={controller:new AbortController(),timer:null,timedOut:false};state.pending=pending;
    pending.timer=setTimeout(()=>{pending.timedOut=true;pending.controller.abort();},30000);
    const content=node('inspectionsContent');content.setAttribute('aria-busy','true');
    content.innerHTML='<div class="fi-state" role="status">Loading inspection records…</div>';
    try{
      const read=url=>api(url,{signal:pending.controller.signal});
      const [catalog,travelers,spools]=await Promise.all([read('/api/flow/catalog'),read('/api/flow/items'),read('/api/flow/board')]);
      if(!state.active||sequence!==state.sequence||badge!==me?.badge)return;
      if(!Array.isArray(catalog?.steps)||!Array.isArray(travelers?.items)||!Array.isArray(spools?.items))throw Error('The inspection records could not be verified. Refresh to try again.');
      state.catalog=catalog;state.travelers=travelers.items;state.spools=spools.items;
      render();updateUrl();
    }catch(error){
      if(!state.active||sequence!==state.sequence||badge!==me?.badge)return;
      const description=pending.timedOut?'This request took too long. Refresh to load the current inspection records.':message(error);
      content.innerHTML=`<div class="fi-state fi-error" role="alert"><strong>Inspection records could not be loaded.</strong><p>${esc(description)}</p>${button('refresh','Try again')}</div>`;
    }finally{
      clearTimeout(pending.timer);pending.controller.abort();if(state.pending===pending)state.pending=null;
      if(state.active&&sequence===state.sequence)content.setAttribute('aria-busy','false');
    }
  }
  async function open(options={}){
    if(typeof me==='undefined'||!me)return;
    if(show('inspectionsPage')===false)return;
    if(typeof stopCloudCamera==='function')stopCloudCamera();
    current=null;state.active=true;
    if(options.resetFilters===true){state.inspection='QA-001';state.project='';state.query='';state.status='';}
    if(Object.prototype.hasOwnProperty.call(options,'inspection'))state.inspection=definition(options.inspection)?.code||'QA-001';
    for(const key of ['project','query'])if(Object.prototype.hasOwnProperty.call(options,key))state[key]=text(options[key]);
    if(Object.prototype.hasOwnProperty.call(options,'status'))state.status=['current','attention'].includes(options.status)?options.status:'';
    await load();
  }
  function categoryMenu(){
    return `<div class="fi-menu" role="group" aria-label="Inspection types">${inspections.map(inspection=>{
      const rows=scopedRecords(inspection),current=rows.filter(row=>currentReview(row,inspection)).length;
      return `<button type="button" class="fi-menu-item${state.inspection===inspection.code?' selected':''}" data-inspection-action="select" data-inspection-id="${inspection.code}" data-inspection-code="${inspection.code}" aria-pressed="${state.inspection===inspection.code}"><span class="fi-code">${inspection.label}</span><strong>${inspection.name}</strong><span class="fi-menu-description">${esc(inspection.description)}</span><span class="fi-menu-count">${rows.length} record${rows.length===1?'':'s'}${current?' · '+current+' current review'+(current===1?'':'s'):''}</span></button>`;
    }).join('')}</div>`;
  }
  function filters(){
    const rows=[...state.spools,...state.travelers],projects=[...new Set([...rows.map(row=>row.project_id),state.project].filter(Boolean))].sort(natural.compare);
    return `<div class="fi-filters"><div class="field"><label for="inspectionsProject">Project</label><select id="inspectionsProject">${option('','All projects',state.project)}${projects.map(project=>option(project,project,state.project)).join('')}</select></div><div class="field"><label for="inspectionsStatus">Show records</label><select id="inspectionsStatus">${option('','All records',state.status)}${option('current','Current review',state.status)}${option('attention','Needs attention',state.status)}</select></div><div class="field fi-search"><label for="inspectionsSearch">Find spool, assembly, or purchase order</label><input id="inspectionsSearch" type="search" value="${esc(state.query)}" placeholder="Spool number, assembly, P.O. or ID" autocomplete="off"></div></div>`;
  }
  function context(row){
    const values=[row.purchase_order?'P.O. '+row.purchase_order:'',row.project_name||row.project_id||'',row.record_kind==='spool'&&row.assembly_number?'Assembly '+row.assembly_number:'',row.gpn?'GPN '+row.gpn:''];
    return values.filter(Boolean).map(esc).join(' · ');
  }
  function access(row){
    if(currentReview(row))return tag('Current review','current');
    if(row.status==='admin_released')return tag('Administrative release');
    if(row.open_kind==='material')return tag('Material record');
    if(!row.traveler)return tag('Route not started');
    return tag(row.released?'Released record':'View record');
  }
  function recordTable(rows){
    if(!rows.length)return `<div class="fi-state"><strong>No records match this selection.</strong><p>${state.status==='current'?'No matching traveler is currently at this review. Choose All records to view other inspection records.':'Choose another project or clear the search and record filters.'}</p></div>`;
    return `<div class="tablewrap"><table class="fi-table"><thead><tr><th>Physical record</th><th>Current process</th><th>Inspection access</th><th>Attention</th><th>Review</th></tr></thead><tbody>${rows.map(row=>{
      const current= currentReview(row),station=window.FabFlowStatus?.badge?.(row.flow_stage)||'',workTitle=row.traveler?.current_title||'',count=Number(row.open_exceptions)||0;
      const warnings=count?`${count} open finding${count===1?'':'s'}`:attention(row)?'Record needs attention':'',first=arr(row.blockers).find(value=>typeof value==='string');
      const linked=arr(row.linked_spools),control=row.open_kind==='material'?'Open material inspection':current?'Open review':'Open record';
      return `<tr data-inspection-record="${esc(row.item_id)}" data-inspection-current="${current}"><td><strong>${displayName(row)}</strong><small>${esc(({spool:'Individual spool',component:'Component',assembly:'Assembly'})[row.record_kind])}${row.item_id!==recordName(row)?' · '+esc(row.item_id):''}</small>${context(row)?`<small>${context(row)}</small>`:''}${linked.length?`<small>${linked.length} linked spool${linked.length===1?'':'s'}</small>`:''}</td><td>${station}${workTitle?`<small>${esc(workTitle)}</small>`:!station?'<span class="muted">No traveler step recorded</span>':''}</td><td>${access(row)}</td><td>${warnings?tag(warnings,'attention'):'<span class="muted">—</span>'}${first?`<small>${esc(first)}</small>`:''}</td><td>${button('open-record',control,row.item_id,current?'primary':'')}</td></tr>`;
    }).join('')}</tbody></table></div>`;
  }
  function render(){
    if(!state.active||!state.catalog)return;
    const inspection=selected(),rows=visibleRecords();
    const scope=inspection.scope==='assembly'?'Testing and final inspection are recorded on the assembly that contains the linked spools. Search a spool number to find its assembly review.':inspection.scope==='material'?'Open a physical spool to inspect its individual material pieces and receiving record. Component travelers are listed separately.':'Each physical spool has its own dimensions and weld inspection records. Open its record to review the checklist, evidence, and signed result.';
    node('inspectionsContent').innerHTML=`<div class="fi-head"><div><span class="fi-eyebrow">CLM fabrication · QA/QC</span><h1>Inspections</h1><p>Choose an inspection, find the physical record, and open its review.</p></div>${button('refresh','Refresh')}</div>${filters()}${categoryMenu()}<section class="card fi-records" aria-labelledby="inspectionsSelectedTitle"><div class="fi-section-head"><div><h2 id="inspectionsSelectedTitle">${esc(title(inspection))}</h2><p>${esc(scope)}</p></div><span class="fi-record-count">${rows.length} matching record${rows.length===1?'':'s'}</span></div><p class="fi-note">“Current review” identifies the traveler’s active inspection step. Other entries provide access to their records; their inclusion does not indicate a passing or completed inspection.</p>${recordTable(rows)}</section>`;
    wireFilters();
  }
  function wireFilters(){
    for(const [id,key] of [['inspectionsProject','project'],['inspectionsStatus','status']]){
      const input=node(id);if(input)input.onchange=()=>{state[key]=input.value;render();updateUrl();};
    }
    const search=node('inspectionsSearch');if(search)search.oninput=()=>{
      state.query=search.value;const start=search.selectionStart,end=search.selectionEnd;render();
      const replacement=node('inspectionsSearch');replacement?.focus();if(typeof replacement?.setSelectionRange==='function'&&start!==null)replacement.setSelectionRange(start,end);updateUrl();
    };
  }
  async function openRecord(id,trigger){
    const row=visibleRecords().find(value=>value.item_id===id);if(!row||state.opening||!state.active)return;
    state.opening=true;
    try{
      if(row.open_kind==='material'){
        if(!window.FabSpoolBom?.open)throw Error('The material inspection screen is unavailable. Refresh FabTrace and try again.');
        await window.FabSpoolBom.open({api_url:'/api/spool-boms/spools/'+encode(row.item_id),item_id:row.item_id,spool_number:recordName(row)},trigger);
      }else{
        if(!window.FabFlow?.open)throw Error('The inspection record is unavailable. Refresh FabTrace and try again.');
        await window.FabFlow.open({item:row.item_id,project:row.project_id||state.project});
      }
    }finally{state.opening=false;}
  }
  node('inspectionsContent').addEventListener('click',async event=>{
    const target=event.target.closest('[data-inspection-action]');if(!target||target.disabled||!state.active)return;
    const action=target.dataset.inspectionAction,id=target.dataset.inspectionId;
    try{
      if(action==='refresh')return await load();
      if(action==='select'&&definition(id)){state.inspection=id;render();updateUrl();return;}
      if(action==='open-record')await openRecord(id,target);
    }catch(error){notify(message(error));}
  });
  node('navInspections').onclick=()=>open({resetFilters:true});
  window.FabInspections={open,refresh:()=>state.active?load():Promise.resolve(),cancelPending,navigationState(){return {inspection:state.inspection,project:state.project,query:state.query,status:state.status};},canNavigateAway:()=>true};
})();
