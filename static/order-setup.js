/* P.O. quantities with separate assembly numbers, GPNs and spool requirements. */
(() => {
  'use strict';
  const ROOT='/api/order-setup',node=id=>document.getElementById(id),arr=v=>Array.isArray(v)?v:[],text=v=>String(v??''),enc=encodeURIComponent;
  const state={active:false,sequence:0,loading:false,saving:false,po:'',list:null,detail:null,error:'',notice:'',query:'',wizard:null,gpnEditor:null,documentSetup:null,formError:'',stale:false,key:0,pausedDraft:null,openAssemblies:[],openCopies:[]};
  const limits={assemblies:100,spools:200,quantity:10000,welds:500};
  const permissions=()=>state.detail?.permissions||state.list?.permissions||{};
  const canManage=()=>window.FabPermissions?.can('manage_production')===true&&permissions().can_manage===true;
  const canRemove=()=>me?.role==='admin'&&permissions().can_remove===true;
  const canUpload=()=>['manage_production','allocate_parts','inspect'].some(capability=>window.FabPermissions?.can(capability)===true);
  const integer=v=>/^\d+$/.test(text(v).trim())&&Number.isSafeInteger(Number(v))?Number(v):null;
  const quantity=v=>{const n=integer(v);return n!==null&&n>=1&&n<=limits.quantity?n:null;};
  const weldCount=v=>{const n=integer(v);return n!==null&&n>=0&&n<=limits.welds?n:null;};
  const display=v=>Number.isSafeInteger(v)&&v>=0?v.toLocaleString():'Not entered';
  const button=(action,label,id='',cls='',disabled=false)=>`<button type="button" class="${esc(cls)}" data-os-action="${esc(action)}" data-os-id="${esc(id)}"${disabled?' disabled':''}>${esc(label)}</button>`;
  const spoolText=(value,label,tag='span')=>window.FabFlowStatus?.spoolText?.(value,label,tag)||`<${tag}>${esc(label??value.qr_alias??value.spool_number??value.item_id)}</${tag}>`;
  const spoolNumber=value=>window.FabFlowStatus?.spoolNumber?.(value)||value.qr_alias||value.display_code||value.spool_number||value.item_id;
  const copyOrder=new Intl.Collator('en',{numeric:true,sensitivity:'base'}).compare;
  const key=()=>String(++state.key);
  const spool=values=>({key:key(),saved_id:values?.id||'',saved_number:values?.spool_number||'',spool_number:values?.spool_number||'',quantity_per_assembly:values?.quantity_per_assembly===null?'':text(values?.quantity_per_assembly??1),welds_per_spool:values?.welds_per_spool==null?'':text(values.welds_per_spool),welds_declared:values?.welds_per_spool!=null});
  const assembly=values=>({key:key(),assembly_number:values?.assembly_number||'',gpn:values?.gpn||'',gpn_label:values?.gpn_label||values?.gpn||'',assembly_quantity:values?.assembly_quantity===null?'':text(values?.assembly_quantity??1),spools:arr(values?.spools).length?values.spools.map(spool):[spool()]});
  const businessGpn=a=>text(a?.gpn_label||a?.gpn).trim();
  const correctedGpn=a=>Boolean(a.gpn_label&&a.gpn_label!==a.gpn);
  const normalized=value=>text(value).trim().replace(/\s+/g,' ').toLowerCase();
  const identityKey=a=>a.assembly_number.trim()?'assembly:'+normalized(a.assembly_number):'gpn:'+normalized(a.gpn);
  const assemblyIdentity=(a,tag='strong')=>`<span class="os-eyebrow">Assembly Number</span><${tag}>${esc(a.assembly_number||'Not entered')}</${tag}><div class="os-note">GPN ${esc(businessGpn(a))}</div>`;
  function errorText(error){
    try{const d=JSON.parse(error.message);if(typeof d.message==='string')return d.message;if(typeof d.detail==='string')return d.detail;if(Array.isArray(d))return d.map(x=>x.msg||'Check the entered values.').join('; ');if(Array.isArray(d.blockers))return d.blockers.join('; ');}catch(_){}
    return text(error.message||'The purchase order could not be saved. Please try again.');
  }
  function url(){const q=new URLSearchParams({'order-setup':'1'});if(state.po)q.set('po',state.po);history.replaceState(null,'','/?'+q.toString());}
  function validList(d){return d&&Array.isArray(d.orders)&&d.permissions&&d.orders.every(o=>typeof o.project_id==='string'&&typeof o.purchase_order==='string');}
  function validDetail(d,po){return d&&d.order&&typeof d.order.project_id==='string'&&(!po||d.order.project_id===po)&&typeof d.order.purchase_order==='string'&&Number.isInteger(d.order.version)&&Array.isArray(d.assemblies)&&d.permissions&&d.totals&&d.assemblies.every(a=>typeof a.gpn_id==='string'&&typeof a.gpn==='string'&&Array.isArray(a.spools)&&a.spools.every(s=>typeof s.spool_number==='string'&&quantity(s.quantity_per_assembly)!==null));}
  function field(id,label,value,options={}){
    return `<div class="field ${options.cls||''}"><label for="${id}">${esc(label)}</label><input id="${id}" value="${esc(value)}" ${options.data||''} type="${options.number?'number':'text'}"${options.number?` inputmode="numeric" min="${options.min??1}" max="${options.limit??10000}" step="1"`:' autocomplete="off"'} maxlength="${options.max||160}"${options.placeholder?` placeholder="${esc(options.placeholder)}"`:''}${state.saving||options.disabled?' disabled':''}></div>`;
  }
  function headline(title,subtitle,actions=''){return `<div class="os-head"><div><span class="os-eyebrow">CLM · Purchase orders</span><h1>${esc(title)}</h1>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div><div class="actions">${actions}</div></div>`;}
  function counts(t){return `<div class="os-counts">${[['Assembly entries',t.assembly_types],['Assemblies needed',t.assembly_quantity],['Total spools needed',t.total_spools]].map(([label,value])=>`<div><span>${label}</span><strong>${display(value)}</strong></div>`).join('')}</div>`;}
  function unknown(t){return t.undeclared_groups?`<p class="os-note os-attention">${display(t.undeclared_groups)} assembly number${t.undeclared_groups===1?' still needs':'s still need'} quantities. Entered quantities are shown on each assembly below.</p>`:'';}
  function weldProgress(row){
    const p=row.weld_progress,warning=Array.isArray(p?.scope_warning)?p.scope_warning.join(' '):p?.scope_warning||'';
    if(p?.defined&&p.percent===null&&warning)return `<div class="os-weld-progress os-weld-unknown"><span>Weld scope needs review</span><small class="os-weld-warning">${esc(warning)}</small></div>`;
    if(p?.defined&&p.total===0)return '<div class="os-weld-progress"><span>No welds required</span></div>';
    if(!p?.defined||typeof p.percent!=='number'||!Number.isFinite(p.percent))return '<div class="os-weld-progress os-weld-unknown"><span>Weld progress not declared</span></div>';
    const percent=Math.max(0,Math.min(100,p.percent));
    return `<div class="os-weld-progress"><span>Recorded weld completion</span><progress max="100" value="${percent}" aria-label="Recorded weld completion for ${esc(row.spool_number)}">${percent}%</progress><strong>${display(p.completed)} of ${display(p.total)} complete</strong>${p.registered_spools<p.required_spools?`<small>${display(p.registered_spools)} of ${display(p.required_spools)} spools registered</small>`:''}${warning?`<small class="os-weld-warning">${esc(warning)}</small>`:''}</div>`;
  }
  function spoolIdentity(row){
    const copies=[...arr(row.physical_spools)].sort((a,b)=>copyOrder(spoolNumber(a),spoolNumber(b))||copyOrder(a.item_id,b.item_id));
    let html=`<strong class="os-planned-number" data-os-planned-number="${esc(row.spool_number)}">${esc(row.spool_number)}</strong>`;
    if(!copies.length)return html+`<p class="os-note">${row.flow_stage_state==='not_registered'||Array.isArray(row.physical_spools)?'No physical copies registered yet.':'Individual spool status is not available.'}</p>`;
    html+=`<details id="osCopies-${esc(row.id)}" class="os-copy-flow" data-os-copies="${esc(row.id)}"${state.openCopies.includes(row.id)?' open':''}><summary>${display(copies.length)} individual ${copies.length===1?'spool':'spools'} · View records</summary><ul>${copies.map(copy=>{
      const stage=window.FabFlowStatus?.normalize(copy),color=stage?stage.color[0].toUpperCase()+stage.color.slice(1):'';
      return `<li data-os-physical-spool="${esc(copy.item_id)}"><div class="os-copy-heading-row"><button type="button" class="os-copy-number" data-os-action="physical-spool" data-os-id="${esc(copy.item_id)}">${spoolText(copy,spoolNumber(copy),'strong')}</button>${canRemove()?button('remove-copy','Remove copy',copy.item_id,'fr-danger os-remove-copy',state.saving):''}</div><div class="os-copy-status">${window.FabFlowStatus?.badge(copy.flow_stage)||'<span>Process unavailable</span>'}${color?`<span class="os-copy-color">Text color: ${esc(color)}</span>`:''}</div>${copy.flow_stage?.blocked===true?`<span class="os-copy-blocked">${stage?.key==='ready_to_ship'?'Release blocked':'Work blocked'}</span>`:''}</li>`;
    }).join('')}</ul>${canRemove()?'<p class="os-copy-removal-note">Removing a copy keeps the planned quantity available for a replacement.</p>':''}</details>`;
    return html;
  }
  function editorRemoval(action,label,id){
    return canRemove()&&id?`<section class="os-editor-removal"><div><strong>Remove this saved record</strong><p>Review the saved record and its linked records before removing. Removal closes this editor without saving its changes. Removed records can be restored.</p></div>${button(action,label,id,'fr-danger',state.saving)}</section>`:'';
  }
  function board(){
    const query=state.query.trim().toLowerCase(),orders=arr(state.list?.orders).filter(o=>!query||[o.purchase_order,o.customer].some(v=>text(v).toLowerCase().includes(query)));
    let html=headline('Purchase orders','Choose an order or set up its GPNs, assemblies and spools.',canManage()?button('new','New P.O.','','primary',state.saving):'');
    html+=`<div class="os-board-tools">${field('osSearch','Find a P.O.',state.query,{placeholder:'P.O. number',max:200})}<div class="actions">${button('refresh','Refresh','', '',state.saving)}${canRemove()?button('removed','Removed records'):''}</div></div>`;
    if(!orders.length)html+=`<section class="os-empty"><h2>${arr(state.list?.orders).length?'No matching P.O.s':'Start with your P.O. number'}</h2><p>${arr(state.list?.orders).length?'Clear the search to see all purchase orders.':'Enter the assemblies and the spools needed for each one, then review and save.'}</p>${canManage()&&!arr(state.list?.orders).length?button('new','Set up a P.O.','','primary',state.saving):''}</section>`;
    else html+=`<div class="os-order-list">${orders.map(o=>`<section class="os-order-card"><div><span class="os-eyebrow">Purchase order</span><h2>${button('order',o.purchase_order,o.project_id,'os-number-link')}</h2>${o.customer?`<p class="os-note">${esc(o.customer)}</p>`:''}</div>${counts(o)}<div class="os-card-footer">${!o.assembly_types?'<span class="os-note">Assembly and spool quantities have not been entered.</span>':o.undeclared_groups?'<span class="os-attention">Some assembly quantities have not been entered.</span>':'<span class="os-note">Assembly and spool quantities saved.</span>'}${button('order','Open P.O.',o.project_id,'primary',state.saving)}</div></section>`).join('')}</div>`;
    html+=`<details id="osBoardProduction" class="os-secondary"><summary>Existing production records</summary><p>Open the detailed order records for physical assemblies, spools and their production documents.</p><div class="actions">${button('production','Production records')}${button('progress','Production progress')}</div></details>`;
    return html;
  }
  function savedAssembly(a){
    const files=a.spools.filter(s=>s.documents?.bom||s.documents?.isometric).length;
    const controls=(canManage()&&a.assembly_number_editable===true?button('identity','Edit assembly',a.gpn_id):'')+
      (canManage()&&a.editable?button('edit',a.assembly_quantity===null?'Enter quantities':'Edit quantities & welds',a.gpn_id):canManage()&&a.welds_editable?button('edit','Set weld counts',a.gpn_id):'');
    return `<details id="osAssemblyDetail-${esc(a.gpn_id)}" class="os-saved-assembly" data-os-assembly-detail="${esc(a.gpn_id)}"${state.openAssemblies.includes(a.gpn_id)?' open':''}><summary><span class="os-chevron" aria-hidden="true"></span><div><span class="os-eyebrow">Assembly</span><strong>${esc(a.assembly_number||'Number not entered')}</strong><span class="os-assembly-summary-note">${display(a.spools.length)} spool ${a.spools.length===1?'number':'numbers'}${files?' · Files on '+display(files):''}</span></div><div class="os-assembly-count"><span>Quantity</span><strong>${display(a.assembly_quantity)}</strong></div><div class="os-assembly-count"><span>Total spools</span><strong>${display(a.total_spools)}</strong></div></summary><div class="os-saved-body"><div class="os-assembly-toolbar"><div>${a.assembly_quantity===null?'<p class="os-attention">Enter the assembly quantity and its required spools.</p>':`<p class="os-quantity-explanation"><strong>${display(a.assembly_quantity)} assemblies</strong> × <strong>${display(a.spools_per_assembly)} spools each</strong> = <strong>${display(a.total_spools)} total spools</strong></p>`}</div><div class="actions">${controls}</div></div>${assemblyUpload(a)}${a.spools.length?`<div class="os-table-wrap"><table class="os-saved-spools"><thead><tr><th>Spool / files / copies</th><th>Qty per assembly</th><th>Welds per spool</th><th>Total on P.O.</th></tr></thead><tbody>${a.spools.map(s=>`<tr><td>${spoolIdentity(s)}<div class="actions os-spool-actions">${window.FabSpoolDocuments?.link('requirements',s.id,s.spool_number,'BOM & drawings','bom')||''}${canRemove()?button('remove-spool-line','Remove spool entry',s.id,'fr-danger',state.saving):''}</div><p class="os-document-status" id="osDocumentStatus-${esc(s.id)}">${documentStatus(s)}</p></td><td data-label="Qty per assembly">${display(s.quantity_per_assembly)}</td><td data-label="Welds per spool">${display(s.welds_per_spool)}${weldProgress(s)}</td><td data-label="Total on P.O.">${display(s.total_quantity)}</td></tr>`).join('')}</tbody></table></div>`:''}${a.locked_reason?`<p class="os-note os-lock-note">${esc(a.locked_reason)}</p>`:''}<div class="actions os-assembly-actions">${button('qr-gpn','Spool QR labels',a.gpn_id)}${button('production-gpn','Production records',a.gpn_id)}${canRemove()?button('remove-gpn','Remove assembly',a.gpn_id,'fr-danger',state.saving):''}</div></div></details>`;
  }
  function gpnRecords(){
    const records=arr(state.detail?.gpn_records),groups=new Map(records.map(r=>[r.id,[]])),unassigned=[];
    for(const a of state.detail.assemblies){
      const identity=a.assembly_definition_id||a.gpn_id;
      const candidates=a.gpn_record_id?records.filter(r=>r.id===a.gpn_record_id):records.filter(r=>arr(r.assembly_definition_ids).includes(identity));
      if(candidates.length===1)groups.get(candidates[0].id).push(a);else unassigned.push(a);
    }
    let html=records.map(r=>`<section class="os-gpn-group" data-os-gpn-record="${esc(r.id)}"><header class="os-gpn-heading"><div><span class="os-eyebrow">Google part number</span><h2>${esc(r.gpn)}</h2><p class="os-note">${display(groups.get(r.id).length)} assembly ${groups.get(r.id).length===1?'record':'records'}${r.description?' · '+esc(r.description):''}</p></div><div class="actions">${canManage()?button('add-gpn-assembly','Add assembly',r.id)+button('edit-gpn','Edit GPN',r.id):''}${canRemove()?`<details id="osGpnOptions-${esc(r.id)}" class="os-more-actions"><summary>More</summary><div>${button('remove-gpn-record','Remove GPN',r.id,'fr-danger',state.saving)}</div></details>`:''}</div></header><div class="os-assembly-list">${groups.get(r.id).length?groups.get(r.id).map(savedAssembly).join(''):'<p class="os-empty-group">Add an assembly to enter its quantity and required spools.</p>'}</div></section>`).join('');
    if(unassigned.length)html+=`<section class="os-gpn-group os-unassigned"><header class="os-gpn-heading"><div><h2>Assembly records</h2><p class="os-note">These saved assemblies have no verified GPN record link. Their current numbers, files and production records remain available.</p></div></header>${unassigned.map(a=>`<div class="os-unassigned-assembly"><p class="os-note">Recorded GPN: <strong>${esc(businessGpn(a))}</strong></p>${savedAssembly(a)}</div>`).join('')}</section>`;
    if(!records.length&&!unassigned.length)html=`<section class="os-empty"><h2>Add a GPN to get started</h2><p>Then add its assemblies and the spools needed for each one.</p>${canManage()?button('add-gpn','Add GPN','','primary',state.saving):''}</section>`;
    return html;
  }
  function resources(){
    const entries=[['qr-labels','Spool QR labels','Open or create labels'],['documents','Add drawings & BOMs','Upload now or later'],['progress','Production progress','Stations, time and current work'],['production','Production records','Physical assemblies and spools'],['spool-records','Spool records & Excel','Review and export saved spool records'],['job-packets','Job Packets','Supporting files and controlled packages']];
    return `<section class="os-resources"><div class="os-section-heading"><h2>Resources</h2><span class="os-note">For this P.O.</span></div><div class="os-resource-grid">${entries.map(([name,label,help])=>`<div>${button(name,label,'','',state.saving)}<p>${esc(help)}</p></div>`).join('')}</div></section>`;
  }
  function workflowHelp(){
    return `<details id="osWorkflowHelp" class="os-secondary os-workflow"><summary>What happens after setup?</summary><p>Add the drawing and BOM, then open Spool QR labels to review existing copies or create eligible physical records. Receiving/material QA and fabrication/QA are recorded on those physical items.</p><p>In Process flow, Step 17 requires the assembly's testing decision. <strong>YES:</strong> NDT → QA/QC → Floor → pressure testing → QA/QC → Floor → Paint/finishing. <strong>NO:</strong> Paint/finishing, subject to the required quality and release checks.</p><p><strong>FAIL:</strong> the recorded return station and employee, completed correction, and a fresh test and QA review. Testing decisions and approvals are recorded in Process flow.</p></details>${window.FabFlowStatus?.legend?`<details id="osSpoolColors" class="os-secondary os-colors"><summary>Spool colors</summary>${window.FabFlowStatus.legend()}</details>`:''}`;
  }
  function detail(){
    const d=state.detail,o=d.order;
    let html=headline(`P.O. ${o.purchase_order}`,'GPNs, assemblies and their required spools.',button('home','← All orders')+(canManage()?button('add-gpn','Add GPN','','primary',state.saving)+button('add','Add assembly','', '',state.saving):''));
    html+=counts(d.totals)+unknown(d.totals)+gpnRecords()+resources()+workflowHelp();
    html+=`<details id="osPoOptions" class="os-secondary"><summary>P.O. options</summary><div class="actions">${button('refresh','Refresh','', '',state.saving)}${canRemove()?button('removed','Removed records / restore','', '',state.saving)+button('remove-order','Remove P.O.',o.project_id,'fr-danger',state.saving):''}</div>${canRemove()?'<p class="os-note">Removing a saved record opens a review of its affected records. Retained history and original records remain available through restore.</p>':''}</details>`;
    return html;
  }
  function parentGpnChoice(a){
    const label=businessGpn(a),rows=arr(state.detail?.gpn_records);
    if(!rows.length)return field('osGpn-'+a.key,'Parent GPN record',a.gpn_label,{data:`data-os-field="gpn_label" data-os-assembly="${a.key}"`,placeholder:'Enter the Google part number'});
    const values=rows.map(r=>r.gpn);if(!values.includes(label))values.unshift(label);
    return `<div class="field"><label for="osGpn-${a.key}">Parent GPN record</label><select id="osGpn-${a.key}" data-os-field="gpn_label" data-os-assembly="${a.key}"${state.saving?' disabled':''}>${values.map(value=>`<option value="${esc(value)}"${value===label?' selected':''}>${esc(value)}</option>`).join('')}</select></div>`;
  }
  function gpnEditor(){
    const f=state.gpnEditor;
    return headline(f.id?'Edit GPN record':'Add GPN record',`P.O. ${state.detail.order.purchase_order}`,button('close-gpn','Close','', '',state.saving))+
      (state.formError?`<div class="os-form-error" role="alert"><p>${esc(state.formError)}</p>${state.stale?button('reload','Reload saved order'):''}</div>`:'')+
      `<form id="osGpnRecordForm" novalidate><fieldset${state.saving?' disabled':''}><section class="os-entry-card">${field('osGpnRecordNumber','Google part number',f.gpn,{data:'data-os-gpn-field="gpn"',placeholder:'Enter the GPN'})}${field('osGpnRecordDescription','Description (optional)',f.description,{max:500,data:'data-os-gpn-field="description"'})}${f.id?`<p class="os-note">This correction applies to the GPN label on all ${display(f.assembly_count)} linked assembly records. Each assembly keeps its own number, quantities and production history.</p>${field('osGpnRecordReason','Reason for this correction',f.reason,{max:3000,data:'data-os-gpn-field="reason"'})}`:''}</section></fieldset><div class="os-wizard-footer"><span>${f.id?'Edit this GPN independently from assembly numbers.':'Add assemblies to this GPN after saving.'}</span><button type="submit" class="primary"${state.saving||state.stale?' disabled':''}>${state.saving?'Saving…':'Save GPN record'}</button></div></form>`+editorRemoval('remove-gpn-record','Remove GPN',f.id);
  }
  function beginGpn(id=''){
    if(!canManage()||state.saving)return;
    const row=id?arr(state.detail?.gpn_records).find(r=>r.id===id):null;if(id&&!row)return;
    state.wizard=null;state.documentSetup=null;state.formError='';state.stale=false;state.notice='';
    state.gpnEditor={id,expected_version:state.detail.order.version,gpn:row?.gpn||'',description:row?.description||'',assembly_count:row?.assembly_count||0,reason:''};render();node('osGpnRecordNumber')?.focus();
  }
  async function saveGpn(){
    const f=state.gpnEditor;if(!f||state.saving||state.stale||!canManage())return;
    state.formError=!f.gpn.trim()||f.gpn.trim().length>160?'Enter a GPN from 1 to 160 characters.':f.description.length>500?'Keep the description within 500 characters.':f.id&&(f.reason.trim().length<4||f.reason.trim().length>3000)?'Enter a reason from 4 to 3,000 characters.':'';
    if(state.formError){render();return;}
    const sequence=++state.sequence,payload={expected_version:f.expected_version,gpn:f.gpn.trim(),description:f.description.trim(),...(f.id?{reason:f.reason.trim()}:{})};state.saving=true;render();
    try{const d=await api(ROOT+'/'+enc(state.po)+'/gpn-records'+(f.id?'/'+enc(f.id):''),{method:f.id?'PATCH':'POST',body:JSON.stringify(payload)});if(!state.active||sequence!==state.sequence)return;if(!validDetail(d,state.po)||!arr(d.gpn_records).some(r=>r.id===d.saved_gpn_record_id))throw Error('The saved GPN response could not be verified. Reload the P.O.');state.detail=d;state.gpnEditor=null;state.notice='GPN record saved.';state.formError='';}
    catch(error){if(state.active&&sequence===state.sequence){state.formError=errorText(error);state.stale=error.status===409||error.message.startsWith('The saved GPN');}}
    finally{if(sequence===state.sequence){state.saving=false;if(state.active)render();}}
  }
  function documentStatus(spoolRow){
    const saved={...spoolRow.documents,...state.documentSetup?.saved?.[spoolRow.id]};
    return saved.bom&&saved.isometric?'BOM and drawing ready':saved.bom?'BOM ready':saved.isometric?'Drawing ready':'No files added yet';
  }
  function assemblyUpload(a){
    if(!a.spools.length)return '';
    return `<div class="os-upload-prompt"><div><strong>Assembly files</strong><p>Add a drawing once for this assembly. Use a spool's BOM &amp; drawings link for a prepared Excel or CSV BOM.</p></div>${canUpload()?button('upload-assembly','Upload drawing or BOM',a.gpn_id,'',state.saving):''}</div>`;
  }
  function pausedDraftNotice(){
    const draft=state.pausedDraft;if(!draft||draft.po!==state.po||state.wizard||state.documentSetup)return '';
    return `<div class="os-resume"><div><strong>You have an unfinished setup</strong><p>Your entries are still here while this page stays open.</p></div>${button('resume','Resume setup','','primary')}</div>`;
  }
  function steps(){const f=state.wizard;if(!f||f.mode!=='new')return '';return `<ol class="os-steps" aria-label="P.O. setup steps">${['P.O. number','Assemblies & spools','Review & save'].map((label,i)=>`<li class="${f.step===i+1?'os-current':f.step>i+1?'os-done':''}"${f.step===i+1?' aria-current="step"':''}><span>${i+1}</span><strong>${label}</strong></li>`).join('')}</ol>`;}
  function assemblyFields(a,index){
    const locked=state.wizard.weldsOnly;
    return `<section class="os-entry-card os-combined-assembly" data-os-assembly="${a.key}"><div class="os-entry-top"><h3>${state.wizard.mode==='new'?'Assembly '+(index+1):locked?'Saved assembly':'Assembly details'}</h3>${state.wizard.mode==='new'&&state.wizard.assemblies.length>1?button('remove-assembly','Remove row',a.key,'os-small',state.saving):''}</div><div class="os-assembly-fields">${field('osGpn-'+a.key,'GPN',businessGpn(a),{disabled:locked||correctedGpn(a),data:`data-os-field="gpn" data-os-assembly="${a.key}" list="osGpnSuggestions"`,placeholder:'Select or enter the Google part number'})}${field('osAssemblyNumber-'+a.key,'Assembly Number (optional)',a.assembly_number,{disabled:locked,data:`data-os-field="assembly_number" data-os-assembly="${a.key}"`,placeholder:'Enter when known'})}${field('osAssemblyQty-'+a.key,'Assembly quantity',a.assembly_quantity,{disabled:locked,number:true,data:`data-os-field="assembly_quantity" data-os-assembly="${a.key}"`})}</div><p class="os-note">GPN and Assembly Number are separate. Use the same GPN for assemblies that belong to that part number.</p>${spoolFields(a)}</section>`;
  }
  function spoolRowRemoval(a,s,locked){
    if(s.saved_id)return canRemove()?`<div class="os-saved-line-removal">${button('remove-spool-line','Remove saved spool',s.saved_id,'fr-danger',state.saving)}<small>Saved: ${esc(s.saved_number)}</small></div>`:'';
    return !locked&&a.spools.length>1?button('remove-spool','Remove row',s.key,'os-small',state.saving):'';
  }
  function spoolFields(a){
    const locked=state.wizard.weldsOnly;
    return `<div class="os-spool-entry"><div class="os-spool-intro"><h4>Spools in one assembly</h4><p>Enter the quantity of each spool for <strong>one assembly</strong>. Welds are counted for <strong>each physical spool</strong>; use 0 only when it has no welds.</p></div>${locked?'<p class="os-attention">Physical production records already exist. Only missing weld counts can be entered; saved scope and declared counts stay locked.</p>':''}<div class="os-spool-labels" aria-hidden="true"><span>Spool number</span><span>Qty per assembly</span><span>Welds per spool</span><span>Total on P.O.</span><span></span></div>${a.spools.map(s=>`<div class="os-spool-row" data-os-spool="${s.key}">${field('osSpoolNumber-'+s.key,'Spool number',s.spool_number,{disabled:locked,data:`data-os-field="spool_number" data-os-assembly="${a.key}" data-os-spool="${s.key}"`,placeholder:'Enter the spool number'})}${field('osSpoolQty-'+s.key,'Qty per assembly',s.quantity_per_assembly,{disabled:locked,number:true,data:`data-os-field="quantity_per_assembly" data-os-assembly="${a.key}" data-os-spool="${s.key}"`})}${field('osSpoolWelds-'+s.key,'Welds per spool',s.welds_per_spool,{number:true,min:0,limit:limits.welds,disabled:locked&&s.welds_declared,placeholder:'Enter count',data:`data-os-field="welds_per_spool" data-os-assembly="${a.key}" data-os-spool="${s.key}"`})}<div class="os-line-total"><span>Total on P.O.</span><strong id="osSpoolTotal-${s.key}">${lineTotal(a,s)}</strong></div><div>${spoolRowRemoval(a,s,locked)}</div></div>`).join('')}<div class="os-spool-footer">${locked?'':button('add-spool','+ Add spool',a.key,'',state.saving||a.spools.length>=limits.spools)}<span><strong id="osAssemblySpools-${a.key}">${assemblySpoolTotal(a)}</strong> total spools on this P.O.</span></div>${locked&&canRemove()?'<p class="os-note">Saved quantities stay locked even if earlier copies were removed. Remove an individual copy from the P.O. or review removal of its containing assembly; a removed copy leaves its planned quantity available for replacement.</p>':''}${canRemove()&&a.spools.some(s=>s.saved_id)?'<p class="os-note">Remove saved spool opens a review of the saved entry. Confirming removal closes this editor without saving its other changes.</p>':''}</div>`;
  }
  function lineTotal(a,s){const aq=quantity(a.assembly_quantity),sq=quantity(s.quantity_per_assembly);return aq===null||sq===null?'—':display(aq*sq);}
  function assemblySpoolTotal(a){const aq=quantity(a.assembly_quantity),q=a.spools.map(s=>quantity(s.quantity_per_assembly));return aq===null||q.some(n=>n===null)?'—':display(aq*q.reduce((x,y)=>x+y,0));}
  function draftTotals(){const rows=state.wizard.assemblies,qs=rows.map(a=>quantity(a.assembly_quantity)),valid=qs.every(q=>q!==null);let total=0;for(const a of rows){const aq=quantity(a.assembly_quantity);for(const s of a.spools){const q=quantity(s.quantity_per_assembly);if(aq===null||q===null)return {assemblies:valid?qs.reduce((x,y)=>x+y,0):null,spools:null};total+=aq*q;}}return {assemblies:valid?qs.reduce((x,y)=>x+y,0):null,spools:total};}
  function reviewSetup(){
    const f=state.wizard,totals=draftTotals();
    return `<section class="os-review-heading"><span class="os-step-kicker">Step 3 of 3</span><h2>Review P.O. ${esc(f.purchase_order)}</h2><p>Check the quantities below. Go back to change an entry, or save the order.</p></section>${f.assemblies.map(a=>`<section class="os-entry-card os-review-assembly"><div class="os-review-identity"><div><span class="os-eyebrow">GPN</span><strong>${esc(businessGpn(a))}</strong></div><div><span class="os-eyebrow">Assembly</span><strong>${esc(a.assembly_number||'Number not entered')}</strong></div><div><span class="os-eyebrow">Quantity</span><strong>${display(quantity(a.assembly_quantity))}</strong></div></div><div class="os-table-wrap"><table><thead><tr><th>Spool number</th><th>Qty per assembly</th><th>Welds per spool</th><th>Total on P.O.</th></tr></thead><tbody>${a.spools.map(s=>`<tr><td>${esc(s.spool_number)}</td><td>${display(quantity(s.quantity_per_assembly))}</td><td>${display(weldCount(s.welds_per_spool))}</td><td>${lineTotal(a,s)}</td></tr>`).join('')}</tbody></table></div></section>`).join('')}<div class="os-save-summary"><div><span>Assemblies needed</span><strong>${display(totals.assemblies)}</strong></div><div><span>Total spools needed</span><strong>${display(totals.spools)}</strong></div></div><p class="os-note">Saving records the planned quantities. Drawings, BOMs and physical spool QR labels are available afterward.</p>`;
  }
  function wizard(){
    const f=state.wizard;if(f.identityOnly)return identityEditor();
    const isNew=f.mode==='new',review=isNew&&f.step===3,title=isNew?'Set up a P.O.':f.mode==='add'?'Add assembly':f.weldsOnly?'Set weld counts':'Edit assembly setup';
    let html=headline(title,isNew?'Enter the order, add its assemblies and spools, then review once before saving.':`P.O. ${state.detail.order.purchase_order}`,button('pause','Close setup','', '',state.saving))+steps();
    if(state.formError)html+=`<div class="os-form-error" role="alert"><strong>Please check the setup</strong><p>${esc(state.formError)}</p>${state.stale?button('reload','Reload saved setup','', '',state.saving):''}</div>`;
    html+=`<form id="orderSetupForm" novalidate><fieldset${state.saving?' disabled':''}>`;
    if(f.step===1)html+=`<section class="os-first-step"><span class="os-step-kicker">Step 1 of 3</span><h2>What is the P.O. number?</h2>${field('osPoNumber','P.O. number',f.purchase_order,{max:200,placeholder:'Enter the purchase order number',data:'data-os-field="purchase_order"'})}</section>`;
    else if(review)html+=reviewSetup();
    else{
      const suggestions=[...new Set([...arr(state.detail?.gpn_records).map(r=>r.gpn),...f.assemblies.map(businessGpn)].filter(Boolean))],totals=draftTotals();
      html+=`<div class="os-step-heading">${isNew?'<span class="os-step-kicker">Step 2 of 3</span>':''}<h2>${f.weldsOnly?'Enter missing weld counts':'Assemblies & spools'}</h2><p>${f.weldsOnly?'Each existing physical record and declared count keeps its current identity.':'Add each assembly and the spools needed to make one of it.'}</p></div><datalist id="osGpnSuggestions">${suggestions.map(value=>`<option value="${esc(value)}"></option>`).join('')}</datalist>${f.assemblies.map(assemblyFields).join('')}${isNew?`<div class="os-add-row">${button('add-assembly','+ Add another assembly','', '',state.saving||f.assemblies.length>=limits.assemblies)}</div>`:''}<div class="os-save-summary"><div><span>Assemblies needed</span><strong id="osDraftAssemblies">${display(totals.assemblies)}</strong></div><div><span>Total spools needed</span><strong id="osDraftSpools">${display(totals.spools)}</strong></div></div>${f.mode==='edit'?`<section class="os-edit-reason">${field('osReason','Reason for this update',f.reason,{max:3000,data:'data-os-field="reason"',placeholder:'Briefly explain the setup or weld-count change'})}</section>`:''}`;
    }
    const saveLabel=isNew?'Save P.O.':f.weldsOnly?'Save weld counts':f.mode==='add'?'Save assembly':'Save changes';
    html+=`</fieldset><div class="os-wizard-footer"><span>${state.saving?'Saving your setup…':isNew?'Nothing is saved until you choose Save P.O.':'This saves only the assembly shown above.'}</span><div class="actions">${isNew&&f.step>1?button('back','Back','', '',state.saving):''}${isNew&&!review?button('next',f.step===1?'Next: assemblies & spools':'Review P.O.','','primary',state.saving):`<button id="osSave" type="submit" class="primary"${state.saving||state.stale?' disabled':''}>${state.saving?'Saving…':saveLabel}</button>`}</div></div></form>`;
    return html+(f.mode==='edit'?editorRemoval('remove-gpn','Remove assembly',f.gpn_id):'');
  }
  function identityEditor(){
    const f=state.wizard,a=f.assemblies[0];
    return headline('Edit assembly record',`P.O. ${state.detail.order.purchase_order}`,button('pause','Close setup','', '',state.saving))+
      (state.formError?`<div class="os-form-error" role="alert"><strong>Please check the assembly number and GPN selection</strong><p>${esc(state.formError)}</p>${state.stale?button('reload','Reload saved setup','', '',state.saving):''}</div>`:'')+
      `<form id="orderSetupForm" novalidate><fieldset${state.saving?' disabled':''}><section class="os-entry-card"><div class="os-assembly-fields os-identity-fields">${field('osAssemblyNumber-'+a.key,'Assembly Number (optional)',a.assembly_number,{data:`data-os-field="assembly_number" data-os-assembly="${a.key}"`,placeholder:'Enter when known'})}${parentGpnChoice(a)}</div><p class="os-note">Choose the parent GPN for this assembly. To correct a GPN across all its assemblies, use Edit GPN under Google part numbers. Leave the Assembly Number blank when unknown.</p>${field('osReason','Reason for this update',f.reason,{max:3000,data:'data-os-field="reason"',placeholder:'Explain the GPN or assembly number correction'})}</section></fieldset><div class="os-wizard-footer"><span>${state.saving?'Saving the GPN and assembly number…':'Spool quantities and physical records are retained.'}</span><div class="actions"><button id="osSave" type="submit" class="primary"${state.saving||state.stale?' disabled':''}>${state.saving?'Saving…':'Save assembly record'}</button></div></div></form>`+editorRemoval('remove-gpn','Remove assembly',f.gpn_id);
  }
  function documentStep(){
    const setup=state.documentSetup,d=state.detail,groups=d.assemblies.filter(a=>setup.gpn_ids.includes(a.gpn_id));
    return headline('Add drawings & BOMs',`P.O. ${d.order.purchase_order} is saved. Files can be added now or later.`,button('documents-back','← Back to P.O.'))+
      `<div class="os-step-heading"><span class="os-step-kicker">Optional files</span><h2>Choose an assembly or spool</h2><p>Upload a full drawing for an assembly to review its detected spool material lists, or open BOM &amp; drawings beside an exact spool to upload a prepared Excel or CSV BOM.</p></div>`+
      groups.map(a=>`<section class="os-entry-card os-document-assembly">${assemblyIdentity(a,'h3')}${assemblyUpload(a)}<div class="os-document-list">${a.spools.map(s=>`<div class="os-document-row"><div>${spoolIdentity(s)}<p class="os-note">${display(s.quantity_per_assembly)} per assembly · ${display(s.total_quantity)} on this P.O.</p><p class="os-document-status" id="osDocumentStatus-${esc(s.id)}">${documentStatus(s)}</p></div><div class="actions">${window.FabSpoolDocuments?.link('requirements',s.id,s.spool_number,'BOM & drawings','bom')||''}</div></div>`).join('')}</div></section>`).join('')+
      (!groups.length?'<div class="os-empty"><p>Add an assembly and its required spools before attaching these files.</p></div>':'')+
      `<p class="os-note">Each saved file stays with its exact assembly or spool. File uploads do not approve production or testing.</p><div class="os-wizard-footer"><span>Your order is already saved. Each file is saved separately.</span><div class="actions">${button('documents-back','Back to P.O.','','primary')}</div></div>`;
  }
  function render(){
    if(!state.active)return;let html='';
    if(state.loading)html=headline('Purchase orders','')+'<div class="os-state" role="status">Loading purchase orders…</div>';
    else if(state.error)html=headline('Purchase orders','')+`<div class="os-state os-form-error" role="alert"><strong>The P.O. could not be opened.</strong><p>${esc(state.error)}</p><div class="actions">${button('refresh','Try again')}${button('home','All P.O.s')}</div></div>`;
    else{html+=pausedDraftNotice();if(state.notice)html+=`<div class="os-notice" role="status">${esc(state.notice)}</div>`;html+=state.gpnEditor?gpnEditor():state.documentSetup?documentStep():state.wizard?wizard():state.detail?detail():board();}
    node('orderSetupContent').innerHTML=html;node('orderSetupContent').setAttribute('aria-busy',String(state.loading));
    const search=node('osSearch');if(search)search.oninput=()=>{state.query=search.value;const caret=search.selectionStart;render();node('osSearch')?.focus();node('osSearch')?.setSelectionRange(caret,caret);};
    const form=node('orderSetupForm');if(form)form.onsubmit=e=>{e.preventDefault();return state.wizard.mode==='new'&&state.wizard.step<3?next():save();};
    const gpnForm=node('osGpnRecordForm');if(gpnForm)gpnForm.onsubmit=e=>{e.preventDefault();return saveGpn();};
    window.FabNavigation?.changed();
  }
  function validation(lastStep){
    const f=state.wizard;if(f.purchase_order.trim().length<2||f.purchase_order.trim().length>200)return 'Enter a P.O. number between 2 and 200 characters.';
    if(lastStep===1)return '';
    if(!f.assemblies.length||f.assemblies.length>limits.assemblies)return 'Enter between 1 and 100 assembly numbers.';
    const used=new Set(f.mode==='new'?[]:arr(state.detail?.assemblies).filter(a=>a.gpn_id!==f.gpn_id).map(a=>identityKey({assembly_number:a.assembly_number||'',gpn:a.gpn})));
    for(let ai=0;ai<f.assemblies.length;ai++){
      const a=f.assemblies[ai],gpn=(f.identityOnly?a.gpn_label:a.gpn).trim(),name=a.assembly_number.trim()||businessGpn(a),key=identityKey(a);
      if(!gpn||gpn.length>160)return `Assembly ${ai+1}: enter a GPN (up to 160 characters).`;
      if(a.assembly_number.trim().length>160)return `Assembly ${ai+1}: the Assembly Number must be 160 characters or fewer.`;
      if(used.has(key))return a.assembly_number.trim()?`Assembly Number ${a.assembly_number.trim()} is listed more than once. Use one row with the full assembly quantity.`:`GPN ${gpn} without an Assembly Number is listed more than once. Enter distinct Assembly Numbers for separate entries.`;used.add(key);
      if(f.identityOnly)continue;
      if(quantity(a.assembly_quantity)===null)return `Assembly ${name}: enter a whole assembly quantity from 1 to 10,000.`;
      if(lastStep<3)continue;
      if(!a.spools.length||a.spools.length>limits.spools)return `Assembly ${name}: enter between 1 and 200 spool numbers.`;
      const numbers=new Set();let total=0;
      for(let si=0;si<a.spools.length;si++){const s=a.spools[si],number=s.spool_number.trim(),normal=number.toLowerCase();if(!number||number.length>160)return `Assembly ${name}, spool ${si+1}: enter a spool number (up to 160 characters).`;if(numbers.has(normal))return `Assembly ${name}: spool ${number} is listed more than once. Combine its quantity into one row.`;numbers.add(normal);const q=quantity(s.quantity_per_assembly);if(q===null)return `Spool ${number}: enter a whole quantity per assembly from 1 to 10,000.`;total+=q;if(weldCount(s.welds_per_spool)===null)return `Spool ${number}: enter the number of welds per spool as a whole number from 0 to 500 (0 only for no welds).`;}
      if(total>limits.quantity)return `Assembly ${name}: the combined spool quantity per assembly must be 10,000 or less.`;
    }
    if(lastStep===3&&['edit','identity'].includes(f.mode)&&(f.reason.trim().length<4||f.reason.trim().length>3000))return 'Enter a reason for this update (4–3,000 characters).';
    return '';
  }
  function focusStep(){const f=state.wizard;if(!f)return;const a=f.assemblies[0],missing=a.spools.find(s=>!s.welds_declared)||a.spools[0],id=f.mode==='new'&&f.step===1?'osPoNumber':f.mode==='new'&&f.step===3?'osSave':f.weldsOnly?'osSpoolWelds-'+missing.key:f.identityOnly?'osAssemblyNumber-'+a.key:'osGpn-'+a.key;node(id)?.focus();}
  function next(){const f=state.wizard;if(!f||f.mode!=='new'||f.step>=3||state.saving||state.stale)return;state.formError=validation(f.step===1?1:3);if(!state.formError)f.step++;render();if(!state.formError)focusStep();}
  function begin(mode,gpnId=''){
    if(!canManage()||state.saving)return;const a=state.detail?.assemblies.find(a=>a.gpn_id===gpnId);if(mode==='edit'&&(!a||(!a.editable&&!a.welds_editable))||mode==='identity'&&(!a||a.assembly_number_editable!==true))return;
    if(state.pausedDraft?.po===state.po&&state.pausedDraft.wizard.mode===mode&&state.pausedDraft.wizard.gpn_id===gpnId){resumeDraft();return;}
    state.notice='';state.formError='';state.stale=false;state.documentSetup=null;state.wizard={mode,identityOnly:mode==='identity',weldsOnly:mode==='edit'&&!a.editable,step:mode==='new'?1:2,expected_version:mode==='new'?0:state.detail.order.version,gpn_id:gpnId,purchase_order:mode==='new'?'':state.detail.order.purchase_order,reason:'',assemblies:[assembly(a)]};render();focusStep();
  }
  function input(target){
    if(state.gpnEditor&&target?.dataset?.osGpnField&&!state.saving){const key=target.dataset.osGpnField;if(['gpn','description','reason'].includes(key))state.gpnEditor[key]=target.value;return;}
    const f=state.wizard;if(!f||state.saving||target?.disabled||!target?.dataset?.osField)return;const name=target.dataset.osField;
    if(name==='purchase_order'||name==='reason'){f[name]=target.value;return;}
    if(f.weldsOnly&&name!=='welds_per_spool'||f.identityOnly&&!['assembly_number','gpn_label'].includes(name))return;
    const a=f.assemblies.find(a=>a.key===target.dataset.osAssembly);if(!a)return;
    if(name==='gpn'&&correctedGpn(a))return;
    if(['assembly_number','gpn','gpn_label','assembly_quantity'].includes(name)){a[name]=target.value;if(name==='gpn')a.gpn_label=target.value;}
    else{const s=a.spools.find(s=>s.key===target.dataset.osSpool);if(s&&!(f.weldsOnly&&s.welds_declared)&&['spool_number','quantity_per_assembly','welds_per_spool'].includes(name))s[name]=target.value;}
    if(f.step===2&&!f.identityOnly){for(const row of f.assemblies){for(const s of row.spools){const el=node('osSpoolTotal-'+s.key);if(el)el.textContent=lineTotal(row,s);}const el=node('osAssemblySpools-'+row.key);if(el)el.textContent=assemblySpoolTotal(row);}const t=draftTotals();if(node('osDraftAssemblies'))node('osDraftAssemblies').textContent=display(t.assemblies);if(node('osDraftSpools'))node('osDraftSpools').textContent=display(t.spools);}
  }
  async function save(){
    const f=state.wizard;if(!f||state.saving||state.stale||!canManage())return;state.formError=validation(3);if(state.formError){render();return;}
    const rows=f.assemblies.map(a=>({assembly_number:a.assembly_number.trim(),gpn:a.gpn.trim(),assembly_quantity:quantity(a.assembly_quantity),spools:a.spools.map(s=>({spool_number:s.spool_number.trim(),quantity_per_assembly:quantity(s.quantity_per_assembly),welds_per_spool:weldCount(s.welds_per_spool)}))}));
    const version=f.expected_version,payload=f.identityOnly?{expected_version:version,assembly_number:rows[0].assembly_number,gpn_label:f.assemblies[0].gpn_label.trim(),reason:f.reason.trim()}:f.mode==='new'?{expected_version:0,purchase_order:f.purchase_order.trim(),assemblies:rows}:{expected_version:version,...rows[0],...(f.mode==='edit'?{reason:f.reason.trim()}:{})};
    const endpoint=f.mode==='new'?ROOT:ROOT+'/'+enc(state.po)+'/assemblies'+(['edit','identity'].includes(f.mode)?'/'+enc(f.gpn_id)+(f.identityOnly?'/identity':''):''),method=['edit','identity'].includes(f.mode)?'PATCH':'POST',sequence=++state.sequence;
    state.saving=true;render();
    try{const d=await api(endpoint,{method,body:JSON.stringify(payload)});if(!state.active||sequence!==state.sequence)return;if(!validDetail(d,f.mode==='new'?'':state.po))throw Error('The saved response could not be verified. Reload the P.O. before making another change.');const saved=arr(d.saved_gpn_ids);if(saved.length!==rows.length||new Set(saved).size!==saved.length||saved.some(id=>!d.assemblies.some(a=>a.gpn_id===id))||f.gpn_id&&saved[0]!==f.gpn_id)throw Error('The saved response did not identify the updated assembly entries. Reload the P.O. before another change.');state.po=d.order.project_id;state.detail=d;state.wizard=null;state.documentSetup=null;state.openAssemblies=f.mode==='new'?[]:[...new Set([...state.openAssemblies,...saved])];state.notice=f.mode==='new'?`P.O. ${d.order.purchase_order} saved. Drawings, BOMs and spool QR labels are available below.`:f.identityOnly?'GPN and assembly number saved.':f.weldsOnly?'Weld counts saved. Open Spool QR labels to review or create eligible physical records.':'Assembly quantities and weld counts saved.';state.formError='';url();}
    catch(error){if(state.active&&sequence===state.sequence){state.formError=errorText(error);state.stale=error.status===409||error.message.startsWith('The saved response');if(state.stale)state.formError+=' Reload the saved setup before making another change.';}}
    finally{if(sequence===state.sequence){state.saving=false;if(state.active)render();}}
  }
  async function load(){
    if(!state.active||!me||state.saving)return;const sequence=++state.sequence,po=state.po;state.loading=true;state.error='';state.wizard=null;state.gpnEditor=null;state.documentSetup=null;state.formError='';state.stale=false;render();
    try{const d=await api(ROOT+(po?'/'+enc(po):''));if(!state.active||sequence!==state.sequence||po!==state.po)return;if(po?!validDetail(d,po):!validList(d))throw Error('The P.O. response could not be verified. Refresh to try again.');if(po){state.detail=d;state.openAssemblies=state.openAssemblies.filter(id=>d.assemblies.some(a=>a.gpn_id===id));state.openCopies=state.openCopies.filter(id=>d.assemblies.some(a=>a.spools.some(s=>s.id===id)));}else{state.list=d;state.detail=null;state.openAssemblies=[];state.openCopies=[];}url();}
    catch(error){if(state.active&&sequence===state.sequence){state.error=errorText(error);state.detail=null;}}
    finally{if(state.active&&sequence===state.sequence){state.loading=false;render();}}
  }
  async function open(options={}){if(!me)return;show('orderSetupPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;state.active=true;state.saving=false;state.po=text(options.po||'');state.detail=null;state.list=null;state.query='';state.notice='';state.wizard=null;state.documentSetup=null;state.openAssemblies=[];state.openCopies=[];await load();if(state.active&&state.detail&&options.gpnRecord&&canManage())beginGpn(options.gpnRecord);if(state.active&&state.detail&&options.addGpn===true&&canManage())beginGpn();}
  const copy=value=>JSON.parse(JSON.stringify(value));
  function pauseDraft(){
    if(state.saving||!state.wizard)return;
    state.pausedDraft={po:state.po,wizard:copy(state.wizard),formError:state.formError,stale:state.stale};
    state.wizard=null;state.formError='';state.stale=false;render();
  }
  function resumeDraft(){
    const draft=state.pausedDraft;if(!draft||draft.po!==state.po||state.saving||!canManage())return;
    state.wizard=copy(draft.wizard);state.formError=draft.formError;state.stale=draft.stale;state.pausedDraft=null;render();focusStep();
  }
  function navigationState(){
    return copy({po:state.po,list:state.list,detail:state.detail,error:state.error,notice:state.notice,query:state.query,
      wizard:state.wizard,gpnEditor:state.gpnEditor,documentSetup:state.documentSetup,formError:state.formError,stale:state.stale,key:state.key,pausedDraft:state.pausedDraft,openAssemblies:state.openAssemblies,openCopies:state.openCopies});
  }
  async function restoreNavigation(snapshot){
    if(!me||!snapshot||typeof snapshot.po!=='string')return open();
    show('orderSetupPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;
    const nextKey=Math.max(state.key,snapshot.key||0),sequence=state.sequence+1;
    Object.assign(state,copy(snapshot),{active:true,saving:false,loading:false,key:nextKey,sequence,openAssemblies:arr(snapshot.openAssemblies),openCopies:arr(snapshot.openCopies)});
    url();
    if(state.gpnEditor){render();node('osGpnRecordNumber')?.focus();return;}
    if(state.wizard){render();focusStep();return;}
    const documentSetup=state.documentSetup,notice=state.notice;
    await load();
    if(state.active&&state.detail&&documentSetup){state.documentSetup=documentSetup;state.notice=notice;render();}
  }
  async function back(){
    if(!state.active)return false;if(state.saving||state.loading)return true;
    if(state.gpnEditor){state.gpnEditor=null;state.formError='';render();return true;}
    if(state.wizard){
      const f=state.wizard;if(f.mode==='new'&&f.step>1){f.step--;state.formError='';render();focusStep();}else pauseDraft();
      return true;
    }
    if(state.documentSetup){state.documentSetup=null;state.notice='Your order is saved. Files can be added beside any assembly or spool.';render();return true;}
    if(state.po){state.po='';state.notice='';state.query='';await load();return true;}
    return false;
  }
  async function removeSaved(action,id){
    if(!state.active||state.loading||state.saving||!canRemove()||!state.detail)return;
    const d=state.detail,lines=d.assemblies.flatMap(a=>a.spools),kinds={'remove-order':'order','remove-gpn-record':'gpn_record','remove-gpn':'gpn','remove-spool-line':'spool_line','remove-copy':'item'},kind=kinds[action];
    const exists=kind==='order'?id===d.order.project_id:kind==='gpn_record'?arr(d.gpn_records).some(r=>r.id===id):kind==='gpn'?d.assemblies.some(a=>a.gpn_id===id):kind==='spool_line'?lines.some(s=>s.id===id):kind==='item'?lines.some(s=>arr(s.physical_spools).some(copy=>copy.item_id===id)):false;
    if(!exists)return;
    const project=state.po,sequence=state.sequence;
    return window.FabRemovals.open({kind,id,onDone:async()=>{
      if(!state.active||state.po!==project||state.sequence!==sequence)return;
      if(state.pausedDraft?.po===project){state.pausedDraft.stale=true;state.pausedDraft.formError='This P.O. changed after removal. Reload the saved setup before making another change.';}
      if(kind==='order'){state.po='';if(state.pausedDraft?.po===project)state.pausedDraft=null;}
      state.notice='Record removed. Open Removed records to restore it.';await load();
    }});
  }
  async function act(action,id){
    if(state.saving)return;
    if(action==='physical-spool')return openItem(id);
    if(action==='add-gpn')return beginGpn();if(action==='edit-gpn')return beginGpn(id);
    if(action==='close-gpn'){state.gpnEditor=null;state.formError='';render();return;}
    if(action==='add-gpn-assembly'){const row=arr(state.detail?.gpn_records).find(r=>r.id===id);if(!row||!canManage())return;begin('add');state.wizard.assemblies[0].gpn=row.gpn;state.wizard.assemblies[0].gpn_label=row.gpn;render();focusStep();return;}
    if(action==='pause')return pauseDraft();if(action==='resume')return resumeDraft();if(action==='documents-back')return back();
    if(action==='documents'&&state.detail){state.documentSetup={gpn_ids:state.detail.assemblies.filter(a=>a.spools.length).map(a=>a.gpn_id),saved:{}};state.notice='';render();return;}
    if(action==='finish-documents'||action==='skip-documents'){state.documentSetup=null;state.notice='P.O. setup saved. You can upload or view documents beside each spool number at any time.';render();return;}
    if(action==='upload-assembly'){const a=state.detail?.assemblies.find(a=>a.gpn_id===id);if(a?.spools.length)return window.FabSpoolDocuments.open({kind:'requirements',id:a.spools[0].id,tab:'upload'});return;}
    if(action==='new')return begin('new');if(action==='add'&&state.detail)return begin('add');if(action==='edit')return begin('edit',id);if(action==='identity')return begin('identity',id);
    if(action==='order'){state.po=id;state.notice='';state.openAssemblies=[];state.openCopies=[];return load();}if(action==='home'){state.po='';state.notice='';state.query='';return load();}if(action==='refresh'||action==='reload'){state.notice='';return load();}
    if(action==='cancel'){if(state.stale)return load();state.wizard=null;state.formError='';render();return;}
    if(action==='next')return next();if(action==='back'&&state.wizard?.mode==='new'&&state.wizard.step>1){state.wizard.step--;state.formError='';render();focusStep();return;}
    if(action==='add-assembly'&&state.wizard?.mode==='new'&&state.wizard.assemblies.length<limits.assemblies){const a=assembly();state.wizard.assemblies.push(a);state.formError='';render();node('osGpn-'+a.key)?.focus();return;}
    if(action==='remove-assembly'&&state.wizard?.mode==='new'&&state.wizard.assemblies.length>1){state.wizard.assemblies=state.wizard.assemblies.filter(a=>a.key!==id);state.formError='';render();return;}
    if(action==='add-spool'&&state.wizard&&!state.wizard.weldsOnly){const a=state.wizard.assemblies.find(a=>a.key===id);if(a&&a.spools.length<limits.spools){const s=spool();a.spools.push(s);state.formError='';render();node('osSpoolNumber-'+s.key)?.focus();}return;}
    if(action==='remove-spool'&&state.wizard&&!state.wizard.weldsOnly){for(const a of state.wizard.assemblies)if(a.spools.length>1)a.spools=a.spools.filter(s=>s.key!==id||s.saved_id);state.formError='';render();return;}
    if(action==='qr-labels'||action==='qr-gpn')return window.FabOrderLabels.open({po:state.po,gpn:action==='qr-gpn'?id:'',kind:'Spool'});
    if(action==='production')return window.FabOrders.open({po:state.po});if(action==='production-gpn')return window.FabOrders.open({po:state.po,gpn:id});if(action==='progress')return window.FabProductionProgress.open({project:state.po});
    if(action==='spool-records'&&state.detail)return window.FabSpoolRecords.open({project:state.po});
    if(action==='job-packets'&&state.detail)return window.FabDossier.open({project:state.po});
    if(action==='removed'&&canRemove())return window.FabRemovals.openList();
    if(['remove-order','remove-gpn-record','remove-gpn','remove-spool-line','remove-copy'].includes(action))return removeSaved(action,id);
  }
  node('orderSetupContent').addEventListener('click',async event=>{const target=event.target.closest('[data-os-action]');if(!target||target.disabled)return;try{await act(target.dataset.osAction,target.dataset.osId||'');}catch(error){notify(errorText(error));}});
  node('orderSetupContent').addEventListener('input',event=>input(event.target));
  node('orderSetupContent').addEventListener('change',event=>input(event.target));
  node('orderSetupContent').addEventListener('toggle',event=>{const target=event.target,assemblyId=target?.dataset?.osAssemblyDetail,copyId=target?.dataset?.osCopies,name=assemblyId?'openAssemblies':copyId?'openCopies':null,id=assemblyId||copyId;if(!name)return;state[name]=target.open?[...new Set([...state[name],id])]:state[name].filter(value=>value!==id);},true);
  document.addEventListener('fabtrace:spool-documents-saved',event=>{
    const change=event.detail;if(!state.active||change?.kind!=='requirements'||!['bom','isometric'].includes(change.document_kind))return;
    if(state.documentSetup){const saved=state.documentSetup.saved[change.id]||(state.documentSetup.saved[change.id]={});saved[change.document_kind]=true;}
    for(const a of arr(state.detail?.assemblies)){const row=a.spools.find(s=>s.id===change.id);if(row){row.documents={...row.documents,[change.document_kind]:true};const el=node('osDocumentStatus-'+change.id);if(el)el.textContent=documentStatus(row);break;}}
  });
  if(node('navOrders'))node('navOrders').onclick=()=>open();
  window.FabOrderSetup={open,refresh:load,navigationState,restoreNavigation,back,canNavigateAway:()=>!state.saving,cancelPending(){state.active=false;state.sequence++;state.loading=false;state.saving=false;}};
})();


