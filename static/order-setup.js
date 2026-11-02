/* P.O. quantities with separate assembly numbers, GPNs and spool requirements. */
(() => {
  'use strict';
  const ROOT='/api/order-setup',node=id=>document.getElementById(id),arr=v=>Array.isArray(v)?v:[],text=v=>String(v??''),enc=encodeURIComponent;
  const state={active:false,sequence:0,loading:false,saving:false,po:'',list:null,detail:null,error:'',notice:'',query:'',wizard:null,documentSetup:null,formError:'',stale:false,key:0,pausedDraft:null};
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
  const spool=values=>({key:key(),spool_number:values?.spool_number||'',quantity_per_assembly:values?.quantity_per_assembly===null?'':text(values?.quantity_per_assembly??1),welds_per_spool:values?.welds_per_spool==null?'':text(values.welds_per_spool),welds_declared:values?.welds_per_spool!=null});
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
    html+=`<div class="os-copy-flow"><p class="os-copy-heading">${display(copies.length)} individual ${copies.length===1?'spool':'spools'}</p><ul>${copies.map(copy=>{
      const stage=window.FabFlowStatus?.normalize(copy),color=stage?stage.color[0].toUpperCase()+stage.color.slice(1):'';
      return `<li data-os-physical-spool="${esc(copy.item_id)}"><button type="button" class="os-copy-number" data-os-action="physical-spool" data-os-id="${esc(copy.item_id)}">${spoolText(copy,spoolNumber(copy),'strong')}</button><div class="os-copy-status">${window.FabFlowStatus?.badge(copy.flow_stage)||'<span>Process unavailable</span>'}${color?`<span class="os-copy-color">Text color: ${esc(color)}</span>`:''}</div>${copy.flow_stage?.blocked===true?`<span class="os-copy-blocked">${stage?.key==='ready_to_ship'?'Release blocked':'Work blocked'}</span>`:''}</li>`;
    }).join('')}</ul></div>`;
    return html;
  }
  function board(){
    const query=state.query.trim().toLowerCase(),orders=arr(state.list?.orders).filter(o=>!query||[o.purchase_order,o.customer].some(v=>text(v).toLowerCase().includes(query)));
    let html=headline('Purchase orders','Start an order, add its assemblies and spools, then upload the drawing or BOM.',canManage()?button('new','New P.O.','','primary',state.saving):'');
    html+=`<div class="os-board-tools">${field('osSearch','Find a P.O.',state.query,{placeholder:'P.O. number',max:200})}<div class="actions">${button('refresh','Refresh','', '',state.saving)}${canRemove()?button('removed','Removed records'):''}</div></div>`;
    if(!orders.length)html+=`<section class="os-empty"><h2>${arr(state.list?.orders).length?'No matching P.O.s':'Start with your P.O. number'}</h2><p>${arr(state.list?.orders).length?'Clear the search to see all purchase orders.':'We will guide you through the assemblies, spools and files, one step at a time.'}</p>${canManage()&&!arr(state.list?.orders).length?button('new','Set up a P.O.','','primary',state.saving):''}</section>`;
    else html+=`<div class="os-order-list">${orders.map(o=>`<section class="os-order-card"><div><span class="os-eyebrow">Purchase order</span><h2>${button('order',o.purchase_order,o.project_id,'os-number-link')}</h2>${o.customer?`<p class="os-note">${esc(o.customer)}</p>`:''}</div>${counts(o)}<div class="os-card-footer">${!o.assembly_types?'<span class="os-note">Assembly and spool quantities have not been entered.</span>':o.undeclared_groups?'<span class="os-attention">Some assembly quantities have not been entered.</span>':'<span class="os-note">Assembly and spool quantities saved.</span>'}${button('order','Open P.O.',o.project_id,'primary',state.saving)}</div></section>`).join('')}</div>`;
    html+=`<details class="os-secondary"><summary>Existing production records</summary><p>Open the detailed order records for physical assemblies, spools and their production documents.</p><div class="actions">${button('production','Production records')}${button('progress','Production progress')}</div></details>`;
    return html;
  }
  function detail(){
    const d=state.detail,o=d.order;
    let html=headline(`P.O. ${o.purchase_order}`,'Assembly quantities, spool quantities and the number of welds on each spool.',button('home','← All orders')+button('qr-labels',canManage()?'Generate spool QR labels':'View spool QR labels','','primary',state.saving)+(canManage()?button('add','Add assembly number','', '',state.saving):''));
    html+=counts(d.totals)+unknown(d.totals)+(window.FabFlowStatus?.legend()||'');
    if(!d.assemblies.length)html+=`<section class="os-empty"><h2>Add the first assembly number</h2><p>Enter its Google part number, the number of assemblies needed and its spool quantities.</p>${canManage()?button('add','Add assembly number','','primary',state.saving):''}</section>`;
    else html+=`<div class="os-assembly-list">${d.assemblies.map(a=>`<details class="os-saved-assembly" open><summary><span class="os-chevron" aria-hidden="true"></span><div>${assemblyIdentity(a)}</div><div class="os-assembly-count"><span>Assemblies needed</span><strong>${display(a.assembly_quantity)}</strong></div><div class="os-assembly-count"><span>Total spools</span><strong>${display(a.total_spools)}</strong></div></summary><div class="os-saved-body">${a.assembly_quantity===null?'<p class="os-attention">Assembly quantity and spool requirements have not been entered for this number.</p>':`<p class="os-quantity-explanation"><strong>${display(a.assembly_quantity)} assemblies</strong> × <strong>${display(a.spools_per_assembly)} spools per assembly</strong> = <strong>${display(a.total_spools)} total spools</strong></p>`}${assemblyUpload(a)}${a.spools.length?`<div class="os-table-wrap"><table class="os-saved-spools"><thead><tr><th>Spool number / individual copies</th><th>Qty per assembly</th><th>Welds per spool</th><th>Total on this P.O.</th></tr></thead><tbody>${a.spools.map(s=>`<tr><td>${spoolIdentity(s)}<div>${window.FabSpoolDocuments?.link('requirements',s.id,s.spool_number,'BOM & drawings','bom')||''}</div><p class="os-document-status" id="osDocumentStatus-${esc(s.id)}">${documentStatus(s)}</p></td><td data-label="Qty per assembly">${display(s.quantity_per_assembly)}</td><td data-label="Welds per spool">${display(s.welds_per_spool)}${weldProgress(s)}</td><td data-label="Total on this P.O.">${display(s.total_quantity)}</td></tr>`).join('')}</tbody></table></div>`:''}${a.locked_reason?`<p class="os-note">${esc(a.locked_reason)}</p>`:''}<div class="actions os-assembly-actions">${canManage()&&a.assembly_number_editable===true?button('identity','Edit GPN / Assembly Number',a.gpn_id):''}${canManage()&&a.editable?button('edit',a.assembly_quantity===null?'Enter quantities':'Edit quantities & welds',a.gpn_id):canManage()&&a.welds_editable?button('edit','Set weld counts',a.gpn_id):''}${button('qr-gpn','Spool QR labels',a.gpn_id)}${button('production-gpn','Production records',a.gpn_id)}${canRemove()?button('remove-gpn','Remove assembly',a.gpn_id,'fr-danger'):''}</div></div></details>`).join('')}</div>`;
    html+=`<details class="os-secondary"><summary>P.O. options and production records</summary><div class="actions">${button('refresh','Refresh','', '',state.saving)}${button('production','Production records')}${button('progress','Production progress')}${canRemove()?button('remove-order','Remove P.O.',o.project_id,'fr-danger'):''}</div></details>`;
    return html;
  }
  function documentStatus(spoolRow){
    const saved={...spoolRow.documents,...state.documentSetup?.saved?.[spoolRow.id]};
    return saved.bom&&saved.isometric?'BOM and drawing ready':saved.bom?'BOM ready':saved.isometric?'Drawing ready':'No files added yet';
  }
  function assemblyUpload(a){
    if(!a.spools.length)return '';
    return `<div class="os-upload-prompt"><div><strong>Drawings &amp; bills of material</strong><p>Choose a PDF, photo or scan. FabTrace finds the matching spools and separates their BOMs. Use a spool’s BOM &amp; drawings link for a prepared Excel or CSV file.</p></div>${canUpload()?button('upload-assembly','Upload drawing or BOM',a.gpn_id,'primary',state.saving):''}</div>`;
  }
  function pausedDraftNotice(){
    const draft=state.pausedDraft;if(!draft||draft.po!==state.po||state.wizard||state.documentSetup)return '';
    return `<div class="os-resume"><div><strong>You have an unfinished setup</strong><p>Your entries are still here while this page stays open.</p></div>${button('resume','Resume setup','','primary')}</div>`;
  }
  function steps(){const f=state.documentSetup?{step:4}:state.wizard;return `<ol class="os-steps" aria-label="P.O. setup steps">${['P.O. number','Assemblies','Spools','Drawings & BOMs'].map((label,i)=>`<li class="${f.step===i+1?'os-current':f.step>i+1?'os-done':''}"${f.step===i+1?' aria-current="step"':''}><span>${i+1}</span><strong>${label}</strong></li>`).join('')}</ol>`;}
  function assemblyFields(a,index){
    return `<section class="os-entry-card" data-os-assembly="${a.key}"><div class="os-entry-top"><h3>Assembly ${index+1}</h3>${state.wizard.mode==='new'&&state.wizard.assemblies.length>1?button('remove-assembly','Remove row',a.key,'os-small',state.saving):''}</div><div class="os-assembly-fields">${field('osAssemblyNumber-'+a.key,'Assembly Number (optional)',a.assembly_number,{data:`data-os-field="assembly_number" data-os-assembly="${a.key}"`,placeholder:'Enter when known'})}${field('osGpn-'+a.key,'GPN',businessGpn(a),{disabled:correctedGpn(a),data:`data-os-field="gpn" data-os-assembly="${a.key}"`,placeholder:'Enter the Google part number'})}${field('osAssemblyQty-'+a.key,'How many assemblies?',a.assembly_quantity,{number:true,data:`data-os-field="assembly_quantity" data-os-assembly="${a.key}"`})}</div></section>`;
  }
  function spoolFields(a){
    const locked=state.wizard.weldsOnly;
    return `<section class="os-entry-card os-spool-entry"><div class="os-entry-top"><div>${assemblyIdentity(a,'h3')}</div><span class="os-quantity-tag">${display(quantity(a.assembly_quantity))} assemblies</span></div><p class="os-note">Enter the spool quantities needed for <strong>one assembly</strong> and the number of welds on <strong>each individual spool</strong>. Enter 0 only if that spool has no welds.</p>${locked?'<p class="os-attention">Physical spool records already exist. Enter missing weld counts below; existing numbers, quantities and declared weld counts are retained.</p>':''}<div class="os-spool-labels" aria-hidden="true"><span>Spool number</span><span>Qty per assembly</span><span>Welds per spool</span><span>Total on P.O.</span><span></span></div>${a.spools.map(s=>`<div class="os-spool-row" data-os-spool="${s.key}">${field('osSpoolNumber-'+s.key,'Spool number',s.spool_number,{disabled:locked,data:`data-os-field="spool_number" data-os-assembly="${a.key}" data-os-spool="${s.key}"`,placeholder:'Enter the spool number'})}${field('osSpoolQty-'+s.key,'Qty per assembly',s.quantity_per_assembly,{disabled:locked,number:true,data:`data-os-field="quantity_per_assembly" data-os-assembly="${a.key}" data-os-spool="${s.key}"`})}${field('osSpoolWelds-'+s.key,'Welds per spool',s.welds_per_spool,{number:true,min:0,limit:limits.welds,disabled:locked&&s.welds_declared,placeholder:'How many?',data:`data-os-field="welds_per_spool" data-os-assembly="${a.key}" data-os-spool="${s.key}"`})}<div class="os-line-total"><span>Total on P.O.</span><strong id="osSpoolTotal-${s.key}">${lineTotal(a,s)}</strong></div><div>${!locked&&a.spools.length>1?button('remove-spool','Remove',s.key,'os-small',state.saving):''}</div></div>`).join('')}<div class="os-spool-footer">${locked?'':button('add-spool','+ Add spool number',a.key,'',state.saving||a.spools.length>=limits.spools)}<span><strong id="osAssemblySpools-${a.key}">${assemblySpoolTotal(a)}</strong> spools for this assembly number</span></div><p class="os-note">Each physical spool receives its own QR code and its own numbered weld records for welding and visual inspection.</p></section>`;
  }
  function lineTotal(a,s){const aq=quantity(a.assembly_quantity),sq=quantity(s.quantity_per_assembly);return aq===null||sq===null?'—':display(aq*sq);}
  function assemblySpoolTotal(a){const aq=quantity(a.assembly_quantity),q=a.spools.map(s=>quantity(s.quantity_per_assembly));return aq===null||q.some(n=>n===null)?'—':display(aq*q.reduce((x,y)=>x+y,0));}
  function draftTotals(){const rows=state.wizard.assemblies,qs=rows.map(a=>quantity(a.assembly_quantity)),valid=qs.every(q=>q!==null);let total=0;for(const a of rows){const aq=quantity(a.assembly_quantity);for(const s of a.spools){const q=quantity(s.quantity_per_assembly);if(aq===null||q===null)return {assemblies:valid?qs.reduce((x,y)=>x+y,0):null,spools:null};total+=aq*q;}}return {assemblies:valid?qs.reduce((x,y)=>x+y,0):null,spools:total};}
  function wizard(){
    const f=state.wizard;if(f.identityOnly)return identityEditor();const title=f.mode==='new'?'Set up a P.O.':f.mode==='add'?'Add an assembly':f.weldsOnly?'Set weld counts':'Edit assembly setup';
    let html=headline(title,f.mode==='new'?'Four short steps. You can go back and keep what you entered.':`P.O. ${state.detail.order.purchase_order}`,button('pause','Close setup','', '',state.saving))+(f.weldsOnly?'':steps());
    if(state.formError)html+=`<div class="os-form-error" role="alert"><strong>Please check the setup</strong><p>${esc(state.formError)}</p>${state.stale?button('reload','Reload saved setup','', '',state.saving):''}</div>`;
    html+=`<form id="orderSetupForm" novalidate><fieldset${state.saving?' disabled':''}>`;
    if(f.step===1)html+=`<section class="os-first-step"><span class="os-step-kicker">Step 1 of 4</span><h2>What is your P.O. number?</h2>${field('osPoNumber','P.O. number',f.purchase_order,{max:200,placeholder:'Enter the purchase order number',data:'data-os-field="purchase_order"'})}</section>`;
    if(f.step===2)html+=`<div class="os-step-heading"><span class="os-step-kicker">Step 2 of 4 · P.O. ${esc(f.purchase_order)}</span><h2>Which assemblies do you need?</h2><p>Enter the Assembly Number when known, its GPN, and the number of assemblies needed. These are separate values.</p></div>${f.assemblies.map(assemblyFields).join('')}${f.mode==='new'?`<div class="os-add-row">${button('add-assembly','+ Add another assembly','', '',state.saving||f.assemblies.length>=limits.assemblies)}</div>`:''}`;
    if(f.step===3){const totals=draftTotals();html+=`<div class="os-step-heading"><span class="os-step-kicker">${f.weldsOnly?'Weld setup':'Step 3 of 4'} · P.O. ${esc(f.purchase_order)}</span><h2>${f.weldsOnly?'How many welds are on each spool?':'Which spools make up each assembly?'}</h2><p>Spool quantities are for one assembly. The weld count applies separately to every physical copy of that spool.</p></div>${f.assemblies.map(spoolFields).join('')}<div class="os-save-summary"><div><span>Assemblies in this setup</span><strong id="osDraftAssemblies">${display(totals.assemblies)}</strong></div><div><span>Total spools</span><strong id="osDraftSpools">${display(totals.spools)}</strong></div></div>${f.mode==='edit'?`<section class="os-edit-reason">${field('osReason','Reason for this update',f.reason,{max:3000,data:'data-os-field="reason"',placeholder:'Briefly explain the setup or weld-count change'})}</section>`:''}`;}
    html+=`</fieldset><div class="os-wizard-footer"><span>${state.saving?'Saving your setup…':'Your entries are saved together when you finish.'}</span><div class="actions">${!f.weldsOnly&&f.step>(f.mode==='new'?1:2)?button('back','Back','', '',state.saving):''}${f.step<3?button('next','Next →','','primary',state.saving):`<button id="osSave" type="submit" class="primary"${state.saving||state.stale?' disabled':''}>${state.saving?'Saving…':f.weldsOnly?'Save weld counts':'Save & add files'}</button>`}</div></div></form>`;
    return html;
  }
  function identityEditor(){
    const f=state.wizard,a=f.assemblies[0];
    return headline('Edit GPN / Assembly Number',`P.O. ${state.detail.order.purchase_order}`,button('pause','Close setup','', '',state.saving))+
      (state.formError?`<div class="os-form-error" role="alert"><strong>Please check the GPN and assembly number</strong><p>${esc(state.formError)}</p>${state.stale?button('reload','Reload saved setup','', '',state.saving):''}</div>`:'')+
      `<form id="orderSetupForm" novalidate><fieldset${state.saving?' disabled':''}><section class="os-entry-card"><div class="os-assembly-fields os-identity-fields">${field('osAssemblyNumber-'+a.key,'Assembly Number (optional)',a.assembly_number,{data:`data-os-field="assembly_number" data-os-assembly="${a.key}"`,placeholder:'Enter when known'})}${field('osGpn-'+a.key,'GPN',a.gpn_label,{data:`data-os-field="gpn_label" data-os-assembly="${a.key}"`,placeholder:'Enter the Google part number'})}</div><p class="os-note">These values apply to this assembly entry and its physical copies. GPN is required; leave the Assembly Number blank when unknown.</p>${field('osReason','Reason for this update',f.reason,{max:3000,data:'data-os-field="reason"',placeholder:'Explain the GPN or assembly number correction'})}</section></fieldset><div class="os-wizard-footer"><span>${state.saving?'Saving the GPN and assembly number…':'Spool quantities and physical records are retained.'}</span><div class="actions"><button id="osSave" type="submit" class="primary"${state.saving||state.stale?' disabled':''}>${state.saving?'Saving…':'Save GPN and assembly number'}</button></div></div></form>`;
  }
  function documentStep(){
    const setup=state.documentSetup,d=state.detail,groups=d.assemblies.filter(a=>setup.gpn_ids.includes(a.gpn_id));
    return headline('Add drawings & BOMs',`P.O. ${d.order.purchase_order} is saved. Upload files now, or come back later.`)+steps()+
      `<div class="os-step-heading"><span class="os-step-kicker">Step 4 of 4 · Optional</span><h2>Upload your drawing or BOM</h2><p>Choose the full drawing once for each assembly. FabTrace finds the spool material lists and prepares their separate Excel BOMs. Check the results, then save.</p></div>`+
      groups.map(a=>`<section class="os-entry-card os-document-assembly">${assemblyIdentity(a,'h3')}${assemblyUpload(a)}<div class="os-document-list">${a.spools.map(s=>`<div class="os-document-row"><div>${spoolIdentity(s)}<p class="os-note">${display(s.quantity_per_assembly)} per assembly · ${display(s.total_quantity)} on this P.O.</p><p class="os-document-status" id="osDocumentStatus-${esc(s.id)}">${documentStatus(s)}</p></div><div class="actions">${window.FabSpoolDocuments?.link('requirements',s.id,s.spool_number,'BOM & drawings','bom')||''}</div></div>`).join('')}</div></section>`).join('')+
      `<p class="os-note">Each matching spool keeps its own Excel BOM and a link to the complete drawing. Upload a prepared BOM beside its spool if you already have one.</p><div class="os-wizard-footer"><span>Your order is already saved.</span><div class="actions">${button('documents-back','← Back to order')}${button('skip-documents','Do this later')}${button('finish-documents','Finish setup','','primary')}</div></div>`;
  }
  function render(){
    if(!state.active)return;let html='';
    if(state.loading)html=headline('Purchase orders','')+'<div class="os-state" role="status">Loading purchase orders…</div>';
    else if(state.error)html=headline('Purchase orders','')+`<div class="os-state os-form-error" role="alert"><strong>The P.O. could not be opened.</strong><p>${esc(state.error)}</p><div class="actions">${button('refresh','Try again')}${button('home','All P.O.s')}</div></div>`;
    else{html+=pausedDraftNotice();if(state.notice)html+=`<div class="os-notice" role="status">${esc(state.notice)}</div>`;html+=state.documentSetup?documentStep():state.wizard?wizard():state.detail?detail():board();}
    node('orderSetupContent').innerHTML=html;node('orderSetupContent').setAttribute('aria-busy',String(state.loading));
    const search=node('osSearch');if(search)search.oninput=()=>{state.query=search.value;const caret=search.selectionStart;render();node('osSearch')?.focus();node('osSearch')?.setSelectionRange(caret,caret);};
    const form=node('orderSetupForm');if(form)form.onsubmit=e=>{e.preventDefault();return !state.wizard.identityOnly&&state.wizard.step<3?next():save();};
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
  function focusStep(){const f=state.wizard;if(!f)return;const id=f.step===1?'osPoNumber':f.step===2?'osAssemblyNumber-'+f.assemblies[0].key:(f.weldsOnly?'osSpoolWelds-':'osSpoolNumber-')+(f.weldsOnly?f.assemblies[0].spools.find(s=>!s.welds_declared)||f.assemblies[0].spools[0]:f.assemblies[0].spools[0]).key;node(id)?.focus();}
  function next(){if(!state.wizard||state.wizard.identityOnly||state.saving||state.stale)return;state.formError=validation(state.wizard.step);if(!state.formError)state.wizard.step++;render();if(!state.formError)focusStep();}
  function begin(mode,gpnId=''){
    if(!canManage()||state.saving)return;const a=state.detail?.assemblies.find(a=>a.gpn_id===gpnId);if(mode==='edit'&&(!a||(!a.editable&&!a.welds_editable))||mode==='identity'&&(!a||a.assembly_number_editable!==true))return;
    if(state.pausedDraft?.po===state.po&&state.pausedDraft.wizard.mode===mode&&state.pausedDraft.wizard.gpn_id===gpnId){resumeDraft();return;}
    state.notice='';state.formError='';state.stale=false;state.documentSetup=null;state.wizard={mode,identityOnly:mode==='identity',weldsOnly:mode==='edit'&&!a.editable,step:mode==='new'?1:mode==='edit'&&!a.editable?3:2,gpn_id:gpnId,purchase_order:mode==='new'?'':state.detail.order.purchase_order,reason:'',assemblies:[assembly(a)]};render();focusStep();
  }
  function input(target){
    const f=state.wizard;if(!f||state.saving||target?.disabled||!target?.dataset?.osField)return;const name=target.dataset.osField;
    if(name==='purchase_order'||name==='reason'){f[name]=target.value;return;}
    if(f.weldsOnly&&name!=='welds_per_spool'||f.identityOnly&&!['assembly_number','gpn_label'].includes(name))return;
    const a=f.assemblies.find(a=>a.key===target.dataset.osAssembly);if(!a)return;
    if(name==='gpn'&&correctedGpn(a))return;
    if(['assembly_number','gpn','gpn_label','assembly_quantity'].includes(name)){a[name]=target.value;if(name==='gpn')a.gpn_label=target.value;}
    else{const s=a.spools.find(s=>s.key===target.dataset.osSpool);if(s&&!(f.weldsOnly&&s.welds_declared)&&['spool_number','quantity_per_assembly','welds_per_spool'].includes(name))s[name]=target.value;}
    if(f.step===3){for(const row of f.assemblies){for(const s of row.spools){const el=node('osSpoolTotal-'+s.key);if(el)el.textContent=lineTotal(row,s);}const el=node('osAssemblySpools-'+row.key);if(el)el.textContent=assemblySpoolTotal(row);}const t=draftTotals();if(node('osDraftAssemblies'))node('osDraftAssemblies').textContent=display(t.assemblies);if(node('osDraftSpools'))node('osDraftSpools').textContent=display(t.spools);}
  }
  async function save(){
    const f=state.wizard;if(!f||state.saving||state.stale||!canManage())return;state.formError=validation(3);if(state.formError){render();return;}
    const rows=f.assemblies.map(a=>({assembly_number:a.assembly_number.trim(),gpn:a.gpn.trim(),assembly_quantity:quantity(a.assembly_quantity),spools:a.spools.map(s=>({spool_number:s.spool_number.trim(),quantity_per_assembly:quantity(s.quantity_per_assembly),welds_per_spool:weldCount(s.welds_per_spool)}))}));
    const version=f.mode==='new'?0:state.detail.order.version,payload=f.identityOnly?{expected_version:version,assembly_number:rows[0].assembly_number,gpn_label:f.assemblies[0].gpn_label.trim(),reason:f.reason.trim()}:f.mode==='new'?{expected_version:0,purchase_order:f.purchase_order.trim(),assemblies:rows}:{expected_version:version,...rows[0],...(f.mode==='edit'?{reason:f.reason.trim()}:{})};
    const endpoint=f.mode==='new'?ROOT:ROOT+'/'+enc(state.po)+'/assemblies'+(['edit','identity'].includes(f.mode)?'/'+enc(f.gpn_id)+(f.identityOnly?'/identity':''):''),method=['edit','identity'].includes(f.mode)?'PATCH':'POST',sequence=++state.sequence;
    state.saving=true;render();
    try{const d=await api(endpoint,{method,body:JSON.stringify(payload)});if(!state.active||sequence!==state.sequence)return;if(!validDetail(d,f.mode==='new'?'':state.po))throw Error('The saved response could not be verified. Reload the P.O. before making another change.');const saved=arr(d.saved_gpn_ids);if(saved.length!==rows.length||new Set(saved).size!==saved.length||saved.some(id=>!d.assemblies.some(a=>a.gpn_id===id))||f.gpn_id&&saved[0]!==f.gpn_id)throw Error('The saved response did not identify the updated assembly entries. Reload the P.O. before another change.');state.po=d.order.project_id;state.detail=d;state.wizard=null;state.documentSetup=f.weldsOnly||f.identityOnly?null:{gpn_ids:[...saved],saved:{}};state.notice=f.mode==='new'?`P.O. ${d.order.purchase_order} saved.`:f.identityOnly?'GPN and assembly number saved.':f.weldsOnly?'Weld counts saved. Generate spool QR labels to finish creating any pending weld records.':'Assembly quantities and weld counts saved.';state.formError='';url();}
    catch(error){if(state.active&&sequence===state.sequence){state.formError=errorText(error);state.stale=error.status===409||error.message.startsWith('The saved response');if(state.stale)state.formError+=' Reload the saved setup before making another change.';}}
    finally{if(sequence===state.sequence){state.saving=false;if(state.active)render();}}
  }
  async function load(){
    if(!state.active||!me||state.saving)return;const sequence=++state.sequence,po=state.po;state.loading=true;state.error='';state.wizard=null;state.documentSetup=null;state.formError='';state.stale=false;render();
    try{const d=await api(ROOT+(po?'/'+enc(po):''));if(!state.active||sequence!==state.sequence||po!==state.po)return;if(po?!validDetail(d,po):!validList(d))throw Error('The P.O. response could not be verified. Refresh to try again.');if(po)state.detail=d;else{state.list=d;state.detail=null;}url();}
    catch(error){if(state.active&&sequence===state.sequence){state.error=errorText(error);state.detail=null;}}
    finally{if(state.active&&sequence===state.sequence){state.loading=false;render();}}
  }
  async function open(options={}){if(!me)return;show('orderSetupPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;state.active=true;state.saving=false;state.po=text(options.po||'');state.detail=null;state.list=null;state.query='';state.notice='';state.wizard=null;state.documentSetup=null;await load();}
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
      wizard:state.wizard,documentSetup:state.documentSetup,formError:state.formError,stale:state.stale,key:state.key,pausedDraft:state.pausedDraft});
  }
  async function restoreNavigation(snapshot){
    if(!me||!snapshot||typeof snapshot.po!=='string')return open();
    show('orderSetupPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;
    const nextKey=Math.max(state.key,snapshot.key||0),sequence=state.sequence+1;
    Object.assign(state,copy(snapshot),{active:true,saving:false,loading:false,key:nextKey,sequence});
    url();
    if(state.wizard){render();focusStep();return;}
    const documentSetup=state.documentSetup,notice=state.notice;
    await load();
    if(state.active&&state.detail&&documentSetup){state.documentSetup=documentSetup;state.notice=notice;render();}
  }
  async function back(){
    if(!state.active)return false;if(state.saving||state.loading)return true;
    if(state.wizard){
      const f=state.wizard;if(!f.weldsOnly&&f.step>(f.mode==='new'?1:2)){f.step--;state.formError='';render();focusStep();}else pauseDraft();
      return true;
    }
    if(state.documentSetup){state.documentSetup=null;state.notice='Your order is saved. Files can be added beside any assembly or spool.';render();return true;}
    if(state.po){state.po='';state.notice='';state.query='';await load();return true;}
    return false;
  }
  async function act(action,id){
    if(state.saving)return;
    if(action==='physical-spool')return openItem(id);
    if(action==='pause')return pauseDraft();if(action==='resume')return resumeDraft();if(action==='documents-back')return back();
    if(action==='finish-documents'||action==='skip-documents'){state.documentSetup=null;state.notice='P.O. setup saved. You can upload or view documents beside each spool number at any time.';render();return;}
    if(action==='upload-assembly'){const a=state.detail?.assemblies.find(a=>a.gpn_id===id);if(a?.spools.length)return window.FabSpoolDocuments.open({kind:'requirements',id:a.spools[0].id,tab:'upload'});return;}
    if(action==='new')return begin('new');if(action==='add'&&state.detail)return begin('add');if(action==='edit')return begin('edit',id);if(action==='identity')return begin('identity',id);
    if(action==='order'){state.po=id;state.notice='';return load();}if(action==='home'){state.po='';state.notice='';state.query='';return load();}if(action==='refresh'||action==='reload'){state.notice='';return load();}
    if(action==='cancel'){if(state.stale)return load();state.wizard=null;state.formError='';render();return;}
    if(action==='next')return next();if(action==='back'&&state.wizard&&!state.wizard.weldsOnly){state.wizard.step--;state.formError='';render();focusStep();return;}
    if(action==='add-assembly'&&state.wizard?.mode==='new'&&state.wizard.assemblies.length<limits.assemblies){const a=assembly();state.wizard.assemblies.push(a);state.formError='';render();node('osAssemblyNumber-'+a.key)?.focus();return;}
    if(action==='remove-assembly'&&state.wizard?.mode==='new'&&state.wizard.assemblies.length>1){state.wizard.assemblies=state.wizard.assemblies.filter(a=>a.key!==id);state.formError='';render();return;}
    if(action==='add-spool'&&state.wizard&&!state.wizard.weldsOnly){const a=state.wizard.assemblies.find(a=>a.key===id);if(a&&a.spools.length<limits.spools){const s=spool();a.spools.push(s);state.formError='';render();node('osSpoolNumber-'+s.key)?.focus();}return;}
    if(action==='remove-spool'&&state.wizard&&!state.wizard.weldsOnly){for(const a of state.wizard.assemblies)if(a.spools.length>1)a.spools=a.spools.filter(s=>s.key!==id);state.formError='';render();return;}
    if(action==='qr-labels'||action==='qr-gpn')return window.FabOrderLabels.open({po:state.po,gpn:action==='qr-gpn'?id:'',kind:'Spool'});
    if(action==='production')return window.FabOrders.open({po:state.po});if(action==='production-gpn')return window.FabOrders.open({po:state.po,gpn:id});if(action==='progress')return window.FabProductionProgress.open({project:state.po});
    if(action==='removed'&&canRemove())return window.FabRemovals.openList();
    if(['remove-order','remove-gpn'].includes(action)&&canRemove())return window.FabRemovals.open({kind:action==='remove-order'?'order':'gpn',id,onDone:async()=>{if(action==='remove-order')state.po='';state.notice='';await load();}});
  }
  node('orderSetupContent').addEventListener('click',async event=>{const target=event.target.closest('[data-os-action]');if(!target||target.disabled)return;try{await act(target.dataset.osAction,target.dataset.osId||'');}catch(error){notify(errorText(error));}});
  node('orderSetupContent').addEventListener('input',event=>input(event.target));
  document.addEventListener('fabtrace:spool-documents-saved',event=>{
    const change=event.detail;if(!state.active||change?.kind!=='requirements'||!['bom','isometric'].includes(change.document_kind))return;
    if(state.documentSetup){const saved=state.documentSetup.saved[change.id]||(state.documentSetup.saved[change.id]={});saved[change.document_kind]=true;}
    for(const a of arr(state.detail?.assemblies)){const row=a.spools.find(s=>s.id===change.id);if(row){row.documents={...row.documents,[change.document_kind]:true};const el=node('osDocumentStatus-'+change.id);if(el)el.textContent=documentStatus(row);break;}}
  });
  if(node('navOrders'))node('navOrders').onclick=()=>open();
  window.FabOrderSetup={open,refresh:load,navigationState,restoreNavigation,back,canNavigateAway:()=>!state.saving,cancelPending(){state.active=false;state.sequence++;state.loading=false;state.saving=false;}};
})();

