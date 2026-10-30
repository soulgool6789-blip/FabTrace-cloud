/* Simple P.O. quantities: assembly numbers, quantities and spool requirements. */
(() => {
  'use strict';
  const ROOT='/api/order-setup',node=id=>document.getElementById(id),arr=v=>Array.isArray(v)?v:[],text=v=>String(v??''),enc=encodeURIComponent;
  const state={active:false,sequence:0,loading:false,saving:false,po:'',list:null,detail:null,error:'',notice:'',query:'',wizard:null,formError:'',stale:false,key:0};
  const limits={assemblies:100,spools:200,quantity:10000};
  const permissions=()=>state.detail?.permissions||state.list?.permissions||{};
  const canManage=()=>window.FabPermissions?.can('manage_production')===true&&permissions().can_manage===true;
  const canRemove=()=>me?.role==='admin'&&permissions().can_remove===true;
  const integer=v=>/^\d+$/.test(text(v).trim())&&Number.isSafeInteger(Number(v))?Number(v):null;
  const quantity=v=>{const n=integer(v);return n!==null&&n>=1&&n<=limits.quantity?n:null;};
  const display=v=>Number.isSafeInteger(v)&&v>=0?v.toLocaleString():'Not entered';
  const button=(action,label,id='',cls='',disabled=false)=>`<button type="button" class="${esc(cls)}" data-os-action="${esc(action)}" data-os-id="${esc(id)}"${disabled?' disabled':''}>${esc(label)}</button>`;
  const key=()=>String(++state.key);
  const spool=values=>({key:key(),spool_number:values?.spool_number||'',quantity_per_assembly:values?.quantity_per_assembly===null?'':text(values?.quantity_per_assembly??1)});
  const assembly=values=>({key:key(),gpn:values?.gpn||'',assembly_quantity:values?.assembly_quantity===null?'':text(values?.assembly_quantity??1),spools:arr(values?.spools).length?values.spools.map(spool):[spool()]});
  function errorText(error){
    try{const d=JSON.parse(error.message);if(typeof d.message==='string')return d.message;if(typeof d.detail==='string')return d.detail;if(Array.isArray(d))return d.map(x=>x.msg||'Check the entered values.').join('; ');if(Array.isArray(d.blockers))return d.blockers.join('; ');}catch(_){}
    return text(error.message||'The purchase order could not be saved. Please try again.');
  }
  function url(){const q=new URLSearchParams({'order-setup':'1'});if(state.po)q.set('po',state.po);history.replaceState(null,'','/?'+q.toString());}
  function validList(d){return d&&Array.isArray(d.orders)&&d.permissions&&d.orders.every(o=>typeof o.project_id==='string'&&typeof o.purchase_order==='string');}
  function validDetail(d,po){return d&&d.order&&typeof d.order.project_id==='string'&&(!po||d.order.project_id===po)&&typeof d.order.purchase_order==='string'&&Number.isInteger(d.order.version)&&Array.isArray(d.assemblies)&&d.permissions&&d.totals&&d.assemblies.every(a=>typeof a.gpn_id==='string'&&typeof a.gpn==='string'&&Array.isArray(a.spools)&&a.spools.every(s=>typeof s.spool_number==='string'&&quantity(s.quantity_per_assembly)!==null));}
  function field(id,label,value,options={}){
    return `<div class="field ${options.cls||''}"><label for="${id}">${esc(label)}</label><input id="${id}" value="${esc(value)}" ${options.data||''} type="${options.number?'number':'text'}"${options.number?' inputmode="numeric" min="1" max="10000" step="1"':' autocomplete="off"'} maxlength="${options.max||160}"${options.placeholder?` placeholder="${esc(options.placeholder)}"`:''}${state.saving?' disabled':''}></div>`;
  }
  function headline(title,subtitle,actions=''){return `<div class="os-head"><div><span class="os-eyebrow">CLM · Purchase orders</span><h1>${esc(title)}</h1>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div><div class="actions">${actions}</div></div>`;}
  function counts(t){return `<div class="os-counts">${[['Assembly numbers',t.assembly_types],['Assemblies needed',t.assembly_quantity],['Total spools needed',t.total_spools]].map(([label,value])=>`<div><span>${label}</span><strong>${display(value)}</strong></div>`).join('')}</div>`;}
  function unknown(t){return t.undeclared_groups?`<p class="os-note os-attention">${display(t.undeclared_groups)} assembly number${t.undeclared_groups===1?' still needs':'s still need'} quantities. Entered quantities are shown on each assembly below.</p>`:'';}
  function board(){
    const query=state.query.trim().toLowerCase(),orders=arr(state.list?.orders).filter(o=>!query||[o.purchase_order,o.customer].some(v=>text(v).toLowerCase().includes(query)));
    let html=headline('Purchase orders','Set up a P.O. with assembly numbers, quantities and the spools each assembly needs.',canManage()?button('new','New P.O.','','primary',state.saving):'');
    html+=`<div class="os-board-tools">${field('osSearch','Find a P.O.',state.query,{placeholder:'P.O. number',max:200})}<div class="actions">${button('refresh','Refresh','', '',state.saving)}${canRemove()?button('removed','Removed records'):''}</div></div>`;
    if(!orders.length)html+=`<section class="os-empty"><h2>${arr(state.list?.orders).length?'No matching P.O.s':'Start with your P.O. number'}</h2><p>${arr(state.list?.orders).length?'Clear the search to see all purchase orders.':'Then enter the assembly numbers and quantities, followed by their spool numbers and quantities.'}</p>${canManage()&&!arr(state.list?.orders).length?button('new','Set up a P.O.','','primary',state.saving):''}</section>`;
    else html+=`<div class="os-order-list">${orders.map(o=>`<section class="os-order-card"><div><span class="os-eyebrow">Purchase order</span><h2>${button('order',o.purchase_order,o.project_id,'os-number-link')}</h2>${o.customer?`<p class="os-note">${esc(o.customer)}</p>`:''}</div>${counts(o)}<div class="os-card-footer">${!o.assembly_types?'<span class="os-note">Assembly and spool quantities have not been entered.</span>':o.undeclared_groups?'<span class="os-attention">Some assembly quantities have not been entered.</span>':'<span class="os-note">Assembly and spool quantities saved.</span>'}${button('order','Open P.O.',o.project_id,'primary',state.saving)}</div></section>`).join('')}</div>`;
    html+=`<details class="os-secondary"><summary>Existing production records</summary><p>Open the detailed order records for physical assemblies, spools and their production documents.</p><div class="actions">${button('production','Production records')}${button('progress','Production progress')}</div></details>`;
    return html;
  }
  function detail(){
    const d=state.detail,o=d.order;
    let html=headline(`P.O. ${o.purchase_order}`,'Assembly numbers and the spools needed for each assembly.',button('home','All P.O.s')+(canManage()?button('add','Add assembly number','','primary',state.saving):''));
    html+=counts(d.totals)+unknown(d.totals);
    if(!d.assemblies.length)html+=`<section class="os-empty"><h2>Add the first assembly number</h2><p>Enter its Google part number, the number of assemblies needed and its spool quantities.</p>${canManage()?button('add','Add assembly number','','primary',state.saving):''}</section>`;
    else html+=`<div class="os-assembly-list">${d.assemblies.map((a,i)=>`<details class="os-saved-assembly"${i===0?' open':''}><summary><span class="os-chevron" aria-hidden="true"></span><div><span class="os-eyebrow">Google part number / Assembly</span><strong>${esc(a.gpn)}</strong></div><div class="os-assembly-count"><span>Assemblies needed</span><strong>${display(a.assembly_quantity)}</strong></div><div class="os-assembly-count"><span>Total spools</span><strong>${display(a.total_spools)}</strong></div></summary><div class="os-saved-body">${a.assembly_quantity===null?'<p class="os-attention">Assembly quantity and spool requirements have not been entered for this number.</p>':`<p class="os-quantity-explanation"><strong>${display(a.assembly_quantity)} assemblies</strong> × <strong>${display(a.spools_per_assembly)} spools per assembly</strong> = <strong>${display(a.total_spools)} total spools</strong></p>`}${a.spools.length?`<div class="os-table-wrap"><table><thead><tr><th>Spool number</th><th>Qty per assembly</th><th>Total on this P.O.</th></tr></thead><tbody>${a.spools.map(s=>`<tr><td>${esc(s.spool_number)}</td><td>${display(s.quantity_per_assembly)}</td><td>${display(s.total_quantity)}</td></tr>`).join('')}</tbody></table></div>`:''}${a.locked_reason?`<p class="os-note">${esc(a.locked_reason)}</p>`:''}<div class="actions os-assembly-actions">${canManage()&&a.editable?button('edit',a.assembly_quantity===null?'Enter quantities':'Edit quantities',a.gpn_id):''}${button('production-gpn','Production records',a.gpn_id)}${canRemove()?button('remove-gpn','Remove assembly number',a.gpn_id,'fr-danger'):''}</div></div></details>`).join('')}</div>`;
    html+=`<details class="os-secondary"><summary>P.O. options and production records</summary><div class="actions">${button('refresh','Refresh','', '',state.saving)}${button('production','Production records')}${button('progress','Production progress')}${canRemove()?button('remove-order','Remove P.O.',o.project_id,'fr-danger'):''}</div></details>`;
    return html;
  }
  function steps(){const f=state.wizard;return `<ol class="os-steps" aria-label="P.O. setup steps">${['P.O. number','Assemblies & quantities','Spools & quantities'].map((label,i)=>`<li class="${f.step===i+1?'os-current':f.step>i+1?'os-done':''}"${f.step===i+1?' aria-current="step"':''}><span>${i+1}</span><strong>${label}</strong></li>`).join('')}</ol>`;}
  function assemblyFields(a,index){
    return `<section class="os-entry-card" data-os-assembly="${a.key}"><div class="os-entry-top"><h3>Assembly ${index+1}</h3>${state.wizard.mode==='new'&&state.wizard.assemblies.length>1?button('remove-assembly','Remove row',a.key,'os-small',state.saving):''}</div><div class="os-assembly-fields">${field('osAssemblyNumber-'+a.key,'Google part number / Assembly number',a.gpn,{data:`data-os-field="gpn" data-os-assembly="${a.key}"`,placeholder:'Enter the assembly number'})}${field('osAssemblyQty-'+a.key,'How many assemblies?',a.assembly_quantity,{number:true,data:`data-os-field="assembly_quantity" data-os-assembly="${a.key}"`})}</div></section>`;
  }
  function spoolFields(a){
    return `<section class="os-entry-card os-spool-entry"><div class="os-entry-top"><div><span class="os-eyebrow">Google part number / Assembly</span><h3>${esc(a.gpn)}</h3></div><span class="os-quantity-tag">${display(quantity(a.assembly_quantity))} assemblies</span></div><p class="os-note">Enter the spool quantities needed for <strong>one assembly</strong>.</p><div class="os-spool-labels" aria-hidden="true"><span>Spool number</span><span>Qty per assembly</span><span>Total on P.O.</span><span></span></div>${a.spools.map(s=>`<div class="os-spool-row" data-os-spool="${s.key}">${field('osSpoolNumber-'+s.key,'Spool number',s.spool_number,{data:`data-os-field="spool_number" data-os-assembly="${a.key}" data-os-spool="${s.key}"`,placeholder:'Enter the spool number'})}${field('osSpoolQty-'+s.key,'Qty per assembly',s.quantity_per_assembly,{number:true,data:`data-os-field="quantity_per_assembly" data-os-assembly="${a.key}" data-os-spool="${s.key}"`})}<div class="os-line-total"><span>Total on P.O.</span><strong id="osSpoolTotal-${s.key}">${lineTotal(a,s)}</strong></div><div>${a.spools.length>1?button('remove-spool','Remove',s.key,'os-small',state.saving):''}</div></div>`).join('')}<div class="os-spool-footer">${button('add-spool','+ Add spool number',a.key,'',state.saving||a.spools.length>=limits.spools)}<span><strong id="osAssemblySpools-${a.key}">${assemblySpoolTotal(a)}</strong> spools for this assembly number</span></div></section>`;
  }
  function lineTotal(a,s){const aq=quantity(a.assembly_quantity),sq=quantity(s.quantity_per_assembly);return aq===null||sq===null?'—':display(aq*sq);}
  function assemblySpoolTotal(a){const aq=quantity(a.assembly_quantity),q=a.spools.map(s=>quantity(s.quantity_per_assembly));return aq===null||q.some(n=>n===null)?'—':display(aq*q.reduce((x,y)=>x+y,0));}
  function draftTotals(){const rows=state.wizard.assemblies,qs=rows.map(a=>quantity(a.assembly_quantity)),valid=qs.every(q=>q!==null);let total=0;for(const a of rows){const aq=quantity(a.assembly_quantity);for(const s of a.spools){const q=quantity(s.quantity_per_assembly);if(aq===null||q===null)return {assemblies:valid?qs.reduce((x,y)=>x+y,0):null,spools:null};total+=aq*q;}}return {assemblies:valid?qs.reduce((x,y)=>x+y,0):null,spools:total};}
  function wizard(){
    const f=state.wizard,title=f.mode==='new'?'Set up a P.O.':f.mode==='add'?'Add an assembly number':'Edit assembly quantities';
    let html=headline(title,f.mode==='new'?'Three short steps. Save the P.O. when all quantities are entered.':`P.O. ${state.detail.order.purchase_order}`,button('cancel','Cancel','', '',state.saving))+steps();
    if(state.formError)html+=`<div class="os-form-error" role="alert"><strong>Please check the setup</strong><p>${esc(state.formError)}</p>${state.stale?button('reload','Reload saved setup','', '',state.saving):''}</div>`;
    html+=`<form id="orderSetupForm" novalidate><fieldset${state.saving?' disabled':''}>`;
    if(f.step===1)html+=`<section class="os-first-step"><span class="os-step-kicker">Step 1 of 3</span><h2>What is your P.O. number?</h2>${field('osPoNumber','P.O. number',f.purchase_order,{max:200,placeholder:'Enter the purchase order number',data:'data-os-field="purchase_order"'})}</section>`;
    if(f.step===2)html+=`<div class="os-step-heading"><span class="os-step-kicker">Step 2 of 3 · P.O. ${esc(f.purchase_order)}</span><h2>Which assemblies do you need?</h2><p>Add each Google part number / assembly number and the number of assemblies needed.</p></div>${f.assemblies.map(assemblyFields).join('')}${f.mode==='new'?`<div class="os-add-row">${button('add-assembly','+ Add another assembly number','', '',state.saving||f.assemblies.length>=limits.assemblies)}</div>`:''}`;
    if(f.step===3){const totals=draftTotals();html+=`<div class="os-step-heading"><span class="os-step-kicker">Step 3 of 3 · P.O. ${esc(f.purchase_order)}</span><h2>Which spools make up each assembly?</h2><p>Spool quantities are for one assembly. The total on the P.O. is calculated for you.</p></div>${f.assemblies.map(spoolFields).join('')}<div class="os-save-summary"><div><span>Assemblies in this setup</span><strong id="osDraftAssemblies">${display(totals.assemblies)}</strong></div><div><span>Total spools</span><strong id="osDraftSpools">${display(totals.spools)}</strong></div></div>${f.mode==='edit'?`<section class="os-edit-reason">${field('osReason','Reason for this update',f.reason,{max:3000,data:'data-os-field="reason"',placeholder:'Briefly explain the quantity or number change'})}</section>`:''}`;}
    html+=`</fieldset><div class="os-wizard-footer"><span>${state.saving?'Saving your setup…':'Your entries are saved together when you finish.'}</span><div class="actions">${f.step>(f.mode==='new'?1:2)?button('back','Back','', '',state.saving):''}${f.step<3?button('next','Next →','','primary',state.saving):`<button id="osSave" type="submit" class="primary"${state.saving||state.stale?' disabled':''}>${state.saving?'Saving…':f.mode==='new'?'Save P.O.':f.mode==='add'?'Save assembly number':'Save changes'}</button>`}</div></div></form>`;
    return html;
  }
  function render(){
    if(!state.active)return;let html='';
    if(state.loading)html=headline('Purchase orders','')+'<div class="os-state" role="status">Loading purchase orders…</div>';
    else if(state.error)html=headline('Purchase orders','')+`<div class="os-state os-form-error" role="alert"><strong>The P.O. could not be opened.</strong><p>${esc(state.error)}</p><div class="actions">${button('refresh','Try again')}${button('home','All P.O.s')}</div></div>`;
    else{if(state.notice)html+=`<div class="os-notice" role="status">${esc(state.notice)}</div>`;html+=state.wizard?wizard():state.detail?detail():board();}
    node('orderSetupContent').innerHTML=html;node('orderSetupContent').setAttribute('aria-busy',String(state.loading));
    const search=node('osSearch');if(search)search.oninput=()=>{state.query=search.value;const caret=search.selectionStart;render();node('osSearch')?.focus();node('osSearch')?.setSelectionRange(caret,caret);};
    const form=node('orderSetupForm');if(form)form.onsubmit=e=>{e.preventDefault();return state.wizard.step<3?next():save();};
  }
  function validation(lastStep){
    const f=state.wizard;if(f.purchase_order.trim().length<2||f.purchase_order.trim().length>200)return 'Enter a P.O. number between 2 and 200 characters.';
    if(lastStep===1)return '';
    if(!f.assemblies.length||f.assemblies.length>limits.assemblies)return 'Enter between 1 and 100 assembly numbers.';
    const used=new Set();
    for(let ai=0;ai<f.assemblies.length;ai++){
      const a=f.assemblies[ai],name=a.gpn.trim(),normalized=name.toLowerCase();
      if(!name||name.length>160)return `Assembly ${ai+1}: enter a Google part number / assembly number (up to 160 characters).`;
      if(used.has(normalized))return `Assembly number ${name} is listed more than once. Use one row with the full assembly quantity.`;used.add(normalized);
      if(quantity(a.assembly_quantity)===null)return `Assembly ${name}: enter a whole assembly quantity from 1 to 10,000.`;
      if(lastStep<3)continue;
      if(!a.spools.length||a.spools.length>limits.spools)return `Assembly ${name}: enter between 1 and 200 spool numbers.`;
      const numbers=new Set();let total=0;
      for(let si=0;si<a.spools.length;si++){const s=a.spools[si],number=s.spool_number.trim(),normal=number.toLowerCase();if(!number||number.length>160)return `Assembly ${name}, spool ${si+1}: enter a spool number (up to 160 characters).`;if(numbers.has(normal))return `Assembly ${name}: spool ${number} is listed more than once. Combine its quantity into one row.`;numbers.add(normal);const q=quantity(s.quantity_per_assembly);if(q===null)return `Spool ${number}: enter a whole quantity per assembly from 1 to 10,000.`;total+=q;}
      if(total>limits.quantity)return `Assembly ${name}: the combined spool quantity per assembly must be 10,000 or less.`;
    }
    if(lastStep===3&&f.mode==='edit'&&(f.reason.trim().length<4||f.reason.trim().length>3000))return 'Enter a reason for this update (4–3,000 characters).';
    return '';
  }
  function focusStep(){const f=state.wizard;if(!f)return;const id=f.step===1?'osPoNumber':f.step===2?'osAssemblyNumber-'+f.assemblies[0].key:'osSpoolNumber-'+f.assemblies[0].spools[0].key;node(id)?.focus();}
  function next(){if(!state.wizard||state.saving||state.stale)return;state.formError=validation(state.wizard.step);if(!state.formError)state.wizard.step++;render();if(!state.formError)focusStep();}
  function begin(mode,gpnId=''){
    if(!canManage()||state.saving)return;const a=state.detail?.assemblies.find(a=>a.gpn_id===gpnId);if(mode==='edit'&&(!a||!a.editable))return;
    state.notice='';state.formError='';state.stale=false;state.wizard={mode,step:mode==='new'?1:2,gpn_id:gpnId,purchase_order:mode==='new'?'':state.detail.order.purchase_order,reason:'',assemblies:[assembly(a)]};render();focusStep();
  }
  function input(target){
    const f=state.wizard;if(!f||state.saving||!target?.dataset?.osField)return;const name=target.dataset.osField;
    if(name==='purchase_order'||name==='reason'){f[name]=target.value;return;}
    const a=f.assemblies.find(a=>a.key===target.dataset.osAssembly);if(!a)return;
    if(name==='gpn'||name==='assembly_quantity')a[name]=target.value;
    else{const s=a.spools.find(s=>s.key===target.dataset.osSpool);if(s&&['spool_number','quantity_per_assembly'].includes(name))s[name]=target.value;}
    if(f.step===3){for(const row of f.assemblies){for(const s of row.spools){const el=node('osSpoolTotal-'+s.key);if(el)el.textContent=lineTotal(row,s);}const el=node('osAssemblySpools-'+row.key);if(el)el.textContent=assemblySpoolTotal(row);}const t=draftTotals();if(node('osDraftAssemblies'))node('osDraftAssemblies').textContent=display(t.assemblies);if(node('osDraftSpools'))node('osDraftSpools').textContent=display(t.spools);}
  }
  async function save(){
    const f=state.wizard;if(!f||state.saving||state.stale||!canManage())return;state.formError=validation(3);if(state.formError){render();return;}
    const rows=f.assemblies.map(a=>({gpn:a.gpn.trim(),assembly_quantity:quantity(a.assembly_quantity),spools:a.spools.map(s=>({spool_number:s.spool_number.trim(),quantity_per_assembly:quantity(s.quantity_per_assembly)}))}));
    const version=f.mode==='new'?0:state.detail.order.version,payload=f.mode==='new'?{expected_version:0,purchase_order:f.purchase_order.trim(),assemblies:rows}:{expected_version:version,...rows[0],...(f.mode==='edit'?{reason:f.reason.trim()}:{})};
    const endpoint=f.mode==='new'?ROOT:ROOT+'/'+enc(state.po)+'/assemblies'+(f.mode==='edit'?'/'+enc(f.gpn_id):''),method=f.mode==='edit'?'PATCH':'POST',sequence=++state.sequence;
    state.saving=true;render();
    try{const d=await api(endpoint,{method,body:JSON.stringify(payload)});if(!state.active||sequence!==state.sequence)return;if(!validDetail(d,f.mode==='new'?'':state.po))throw Error('The saved response could not be verified. Reload the P.O. before making another change.');state.po=d.order.project_id;state.detail=d;state.wizard=null;state.notice=f.mode==='new'?`P.O. ${d.order.purchase_order} saved.`:'Assembly quantities saved.';state.formError='';url();}
    catch(error){if(state.active&&sequence===state.sequence){state.formError=errorText(error);state.stale=error.status===409||error.message.startsWith('The saved response');if(state.stale)state.formError+=' Reload the saved setup before making another change.';}}
    finally{if(sequence===state.sequence){state.saving=false;if(state.active)render();}}
  }
  async function load(){
    if(!state.active||!me||state.saving)return;const sequence=++state.sequence,po=state.po;state.loading=true;state.error='';state.wizard=null;state.formError='';state.stale=false;render();
    try{const d=await api(ROOT+(po?'/'+enc(po):''));if(!state.active||sequence!==state.sequence||po!==state.po)return;if(po?!validDetail(d,po):!validList(d))throw Error('The P.O. response could not be verified. Refresh to try again.');if(po)state.detail=d;else{state.list=d;state.detail=null;}url();}
    catch(error){if(state.active&&sequence===state.sequence){state.error=errorText(error);state.detail=null;}}
    finally{if(state.active&&sequence===state.sequence){state.loading=false;render();}}
  }
  async function open(options={}){if(!me)return;show('orderSetupPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;state.active=true;state.saving=false;state.po=text(options.po||'');state.detail=null;state.list=null;state.query='';state.notice='';state.wizard=null;await load();}
  async function act(action,id){
    if(state.saving)return;
    if(action==='new')return begin('new');if(action==='add'&&state.detail)return begin('add');if(action==='edit')return begin('edit',id);
    if(action==='order'){state.po=id;state.notice='';return load();}if(action==='home'){state.po='';state.notice='';state.query='';return load();}if(action==='refresh'||action==='reload'){state.notice='';return load();}
    if(action==='cancel'){if(state.stale)return load();state.wizard=null;state.formError='';render();return;}
    if(action==='next')return next();if(action==='back'&&state.wizard){state.wizard.step--;state.formError='';render();focusStep();return;}
    if(action==='add-assembly'&&state.wizard?.mode==='new'&&state.wizard.assemblies.length<limits.assemblies){const a=assembly();state.wizard.assemblies.push(a);state.formError='';render();node('osAssemblyNumber-'+a.key)?.focus();return;}
    if(action==='remove-assembly'&&state.wizard?.mode==='new'&&state.wizard.assemblies.length>1){state.wizard.assemblies=state.wizard.assemblies.filter(a=>a.key!==id);state.formError='';render();return;}
    if(action==='add-spool'&&state.wizard){const a=state.wizard.assemblies.find(a=>a.key===id);if(a&&a.spools.length<limits.spools){const s=spool();a.spools.push(s);state.formError='';render();node('osSpoolNumber-'+s.key)?.focus();}return;}
    if(action==='remove-spool'&&state.wizard){for(const a of state.wizard.assemblies)if(a.spools.length>1)a.spools=a.spools.filter(s=>s.key!==id);state.formError='';render();return;}
    if(action==='production')return window.FabOrders.open({po:state.po});if(action==='production-gpn')return window.FabOrders.open({po:state.po,gpn:id});if(action==='progress')return window.FabProductionProgress.open({project:state.po});
    if(action==='removed'&&canRemove())return window.FabRemovals.openList();
    if(['remove-order','remove-gpn'].includes(action)&&canRemove())return window.FabRemovals.open({kind:action==='remove-order'?'order':'gpn',id,onDone:async()=>{if(action==='remove-order')state.po='';state.notice='';await load();}});
  }
  node('orderSetupContent').addEventListener('click',async event=>{const target=event.target.closest('[data-os-action]');if(!target||target.disabled)return;try{await act(target.dataset.osAction,target.dataset.osId||'');}catch(error){notify(errorText(error));}});
  node('orderSetupContent').addEventListener('input',event=>input(event.target));
  if(node('navOrders'))node('navOrders').onclick=()=>open();
  window.FabOrderSetup={open,refresh:load,cancelPending(){state.active=false;state.sequence++;state.loading=false;state.saving=false;}};
})();
