/* Purchase order → GPN → physical assembly → uniquely identified spools. */
(() => {
  'use strict';
  const ROOT='/api/orders',node=id=>document.getElementById(id),text=v=>String(v??''),arr=v=>Array.isArray(v)?v:[],enc=encodeURIComponent;
  const state={active:false,sequence:0,loading:false,pending:null,saving:false,downloading:false,po:'',gpn:'',assembly:'',query:'',list:null,detail:null,form:null,error:'',formError:'',stale:false,staff:[],formRequest:0};
  const count=v=>Number.isInteger(v)&&v>=0?v:null,display=v=>count(v)===null?'—':String(v),canManage=()=>window.FabPermissions?.can('manage_production')===true&&(state.detail||state.list)?.permissions?.can_manage===true;
  const button=(action,label,id='',cls='',disabled=false)=>`<button type="button" class="${esc(cls)}" data-order-action="${esc(action)}" data-order-id="${esc(id)}"${disabled?' disabled':''}>${esc(label)}</button>`;
  const option=(value,label,current)=>`<option value="${esc(value)}"${text(value)===text(current)?' selected':''}>${esc(label)}</option>`;
  const stamp=value=>value?new Date(value).toLocaleString():'—';
  function errorText(error){try{const d=JSON.parse(error.message);if(d.message)return d.message;if(Array.isArray(d))return d.map(x=>`${arr(x.loc).filter(k=>k!=='body').join(' / ')}: ${x.msg||'Check this value'}`).join('; ');if(d.blockers)return arr(d.blockers).join('; ');}catch(_){}return text(error.message||'Purchase order records could not be loaded.');}
  function updateUrl(){const q=new URLSearchParams({orders:'1'});if(state.po)q.set('po',state.po);if(state.gpn)q.set('gpn',state.gpn);if(state.assembly)q.set('assembly',state.assembly);history.replaceState(null,'','/?'+q.toString());}
  function resetForm(){state.formRequest++;state.form=null;state.formError='';state.stale=false;}
  function header(title,subtitle,actions=''){return `<div class="fo-head"><div><span class="fo-eyebrow">CLM · Purchase order planning</span><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="actions">${actions}${button('refresh','Refresh','','',state.saving)}</div></div>`;}
  function counters(t={}){return `<div class="fo-counts">${[['Assemblies',t.assembly_count],['Spools needed',t.required_spools],['Spools linked',t.linked_spools],['Still to link',t.missing_spools]].map(([label,n])=>`<div><span>${label}</span><strong>${display(n)}</strong></div>`).join('')}</div>`;}
  function meter(ready,required){const p=count(ready)!==null&&count(required)!==null&&required>0?Math.max(0,Math.min(100,100*ready/required)):null;return `<div class="fo-meter"><div><span>Ready for assembly</span><strong>${p===null?'Not configured':p.toFixed(p%1?1:0)+'%'}</strong></div>${p===null?'':`<progress max="100" value="${p}" aria-label="Spools ready for assembly">${p}%</progress>`}<small>${display(ready)} of ${display(required)} required spools</small></div>`;}
  function exportsView(){return `<div class="actions">${button('bom','Download BOM Excel','','',state.downloading)}${button('template','Excel BOM template','','',state.downloading)}</div>`;}
  function exportNote(){return '<p class="fo-export-note">Excel uses the current P.O, G.P.N and assembly selection. Excel edits stay in the workbook; enter approved quantities in Spool parts to update FabTrace.</p>';}
  function hierarchy(){
    const d=state.detail,g=d?.gpns.find(g=>g.id===state.gpn),a=d?.assemblies.find(a=>a.item_id===state.assembly),current=a?3:g?2:d?1:0;
    const steps=[['P.O','home','',d?.order.purchase_order||'Choose a P.O',true],['G.P.N','order',state.po,g?.gpn||'Choose a G.P.N',Boolean(d)],['Assembly','gpn',state.gpn,a?.assembly_part_number||'Choose an assembly',Boolean(g)],['Spools','assembly',state.assembly,a?.item_id||'View linked spools',Boolean(a)]];
    return `<nav class="fo-steps" aria-label="Order hierarchy">${steps.map(([label,action,id,value,enabled],i)=>`<button type="button" class="fo-step ${i===current?'fo-step-current':i<current?'fo-step-done':''}" data-order-action="${action}" data-order-id="${esc(id)}"${enabled?'':' disabled'}${i===current?' aria-current="step"':''}><span class="fo-step-number">${i+1}</span><span class="fo-step-copy"><strong>${label}</strong><small>${esc(value)}</small></span>${i<3?'<span class="fo-step-arrow" aria-hidden="true">→</span>':''}</button>`).join('')}</nav>`;
  }
  function board(){
    const query=state.query.trim().toLowerCase(),rows=arr(state.list?.orders).filter(row=>!query||[row.purchase_order,row.customer].some(v=>text(v).toLowerCase().includes(query)));
    let html=hierarchy()+header('P.O','Choose a purchase order to view its G.P.N.',canManage()?button('new-order','New P.O','','primary'):'');
    if(state.form)html+=formView();
    html+=`<div class="fo-filters"><div class="field fo-search"><label for="ordersSearch">Find a P.O</label><input id="ordersSearch" type="search" value="${esc(state.query)}" placeholder="P.O number or customer"></div></div>`;
    if(!rows.length)html+=`<section class="fo-empty"><h2>${state.list?.orders.length?'No matching purchase orders':'Start a P.O'}</h2><p>${state.list?.orders.length?'Clear the search to see other orders.':'Enter the P.O number, then add its G.P.N, assemblies and spools.'}</p>${canManage()?button('new-order','New P.O','','primary'):''}</section>`;
    else html+=`<section class="fo-card"><div class="tablewrap"><table class="fo-orders"><thead><tr><th>P.O number</th><th>Customer</th><th>G.P.N</th><th>Assemblies</th><th>Spools needed</th><th>Linked</th><th>Still to link</th></tr></thead><tbody>${rows.map(o=>`<tr><td>${button('order',o.purchase_order,o.project_id,'fo-po-link')}</td><td>${esc(o.customer||'Not entered')}</td><td class="fo-number">${display(o.gpn_count)}</td><td class="fo-number">${display(o.assembly_count)}</td><td class="fo-number">${display(o.required_spools)}</td><td class="fo-number">${display(o.linked_spools)}</td><td class="fo-number">${display(o.missing_spools)}</td></tr>`).join('')}</tbody></table></div></section>`;
    if(arr(state.list?.unassigned_projects).length)html+=`<section class="fo-card"><h2>Existing projects without a P.O link</h2><p class="fo-note">${state.list.unassigned_projects.length} existing project${state.list.unassigned_projects.length===1?' is':'s are'} available to connect when its P.O number is confirmed.</p>${canManage()?button('attach-project','Connect an existing project'):button('tracking','Open Projects & welds')}</section>`;
    return html;
  }
  function assemblyTable(rows){return `<div class="tablewrap"><table class="fo-assemblies"><thead><tr><th>Assembly / QR ID</th><th>Assembly part number</th><th>Spools needed</th><th>Linked</th><th>Still to link</th><th>Ready for assembly</th><th>Actions</th></tr></thead><tbody>${rows.map(a=>`<tr><td><strong>${esc(a.item_id)}</strong>${a.planning_needed?'<small class="fo-tag fo-pending">Weld plan needed</small>':''}</td><td>${esc(a.assembly_part_number)}</td><td class="fo-number"><strong class="fo-required">${display(a.required_spools)}</strong></td><td class="fo-number">${display(a.linked_spools)}</td><td class="fo-number">${display(a.missing_spools)}</td><td>${meter(a.ready_spools,a.required_spools)}</td><td><div class="actions">${button('assembly','Open spools',a.item_id,'primary')}${canManage()?button('edit-assembly','Edit assembly',a.item_id):''}</div></td></tr>`).join('')}</tbody></table></div>`;}
  function orderView(){
    const d=state.detail,o=d.order,g=d.gpns.find(g=>g.id===state.gpn),a=d.assemblies.find(a=>a.item_id===state.assembly);
    const title=a?'Spools':g?'Assembly':'G.P.N',subtitle=a?`Assembly ${a.assembly_part_number} · ${a.item_id}`:g?`G.P.N ${g.gpn}`:`P.O ${o.purchase_order}`;
    const back=a?button('gpn','← Back to assemblies',g.id):g?button('order','← Back to G.P.N',state.po):button('home','← Back to P.O');
    let html=hierarchy()+header(title,subtitle,back);
    html+=`<section class="fo-card fo-overview"><div class="fo-section-head"><div class="fo-scope"><strong>P.O ${esc(o.purchase_order)}</strong><span>${esc(o.customer||'Customer not entered')}</span>${g?`<span>G.P.N ${esc(g.gpn)}</span>`:''}</div>${exportsView()}</div>${counters(a?{assembly_count:1,...a}:g||d.totals)}${exportNote()}<details class="fo-order-tools"><summary>P.O details &amp; project records</summary>${o.notes?`<p class="fo-note">${esc(o.notes)}</p>`:''}<div class="actions">${button('progress','Project progress')}${button('job-packet','Job Packets')}${canManage()?button('edit-order','Edit P.O details'):''}</div></details></section>`;
    if(state.form)html+=formView();
    if(a)return html+assemblyView(a);
    const query=state.query.trim().toLowerCase();
    if(g){
      const rows=g.assemblies.filter(a=>!query||[a.item_id,a.assembly_part_number].some(v=>text(v).toLowerCase().includes(query)));
      html+=`<div class="fo-filters"><div class="field fo-search"><label for="ordersSearch">Find an assembly</label><input id="ordersSearch" type="search" value="${esc(state.query)}" placeholder="Assembly part number or QR ID"></div><div class="actions">${canManage()?button('edit-gpn','Edit G.P.N',g.id)+button('new-assembly','Add assembly',g.id,'primary'):''}</div></div>`;
      html+=rows.length?`<section class="fo-card">${assemblyTable(rows)}</section>`:`<section class="fo-empty"><h2>${query?'No matching assemblies':'Add the first assembly'}</h2><p>${query?'Clear the search to see all assemblies in this G.P.N.':'Enter the assembly part number and required spool count.'}</p>${!query&&canManage()?button('new-assembly','Add assembly',g.id,'primary'):''}</section>`;
    }else{
      const groups=d.gpns.filter(g=>!query||text(g.gpn).toLowerCase().includes(query));
      html+=`<div class="fo-filters"><div class="field fo-search"><label for="ordersSearch">Find a G.P.N</label><input id="ordersSearch" type="search" value="${esc(state.query)}" placeholder="G.P.N number"></div><div class="actions">${canManage()?button('new-gpn','Add G.P.N','','primary'):''}</div></div>`;
      if(!groups.length)html+=`<section class="fo-empty"><h2>${query?'No matching G.P.N':'Add the first G.P.N'}</h2><p>${query?'Clear the search to see all G.P.N in this P.O.':'Enter a G.P.N, then add the assemblies that belong to it.'}</p>${!query&&canManage()?button('new-gpn','Add G.P.N','','primary'):''}</section>`;
      else html+=`<div class="fo-gpn-grid">${groups.map(g=>`<section class="fo-card fo-gpn"><span class="fo-eyebrow">G.P.N</span><h2>${esc(g.gpn)}</h2><div class="fo-gpn-counts"><div><strong>${display(g.assembly_count)}</strong><span>Assemblies</span></div><div><strong>${display(g.required_spools)}</strong><span>Spools needed</span></div><div><strong>${display(g.linked_spools)}</strong><span>Linked spools</span></div></div>${button('gpn','Open assemblies',g.id,'primary')}</section>`).join('')}</div>`;
    }
    return html+historyView();
  }
  function assemblyView(a){
    let html=`<section class="fo-card"><div class="fo-section-head"><div><span class="fo-eyebrow">Assembly part number</span><h2>${esc(a.assembly_part_number)}</h2><p class="fo-note">QR ID: ${esc(a.item_id)}</p></div><div class="actions">${button('item','Item & QR',a.item_id)}${button('flow','Process flow',a.item_id)}${canManage()?button('edit-assembly','Edit assembly',a.item_id):''}</div></div>${a.drawing?`<p class="fo-note">Drawing / revision: ${esc(a.drawing)}</p>`:''}${meter(a.ready_spools,a.required_spools)}<p class="fo-note">${display(a.missing_spools)} still to link · ${display(a.not_ready_spools)} linked but not ready</p>`;
    if(a.planning_needed)html+=`<div class="fo-notice"><strong>Set the assembly’s weld plan.</strong> Confirm the drawing and actual planned weld count before starting fabrication.${canManage()?`<div class="actions">${button('plan-assembly','Set assembly weld plan',a.item_id,'primary')}</div>`:''}</div>`;
    if(a.flow_started)html+='<p class="fo-note">The required spool count is locked because this assembly has a process traveler.</p>';
    if(arr(a.blockers).length)html+=`<details class="fo-blockers"><summary>Current assembly readiness details</summary><ul>${a.blockers.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`;
    html+='</section>';
    html+=`<section class="fo-card"><div class="fo-section-head"><div><h2>Spools</h2><p class="fo-note">${display(a.linked_spools)} linked / ${display(a.required_spools)} needed</p></div><div class="actions">${canManage()?button('register-spool','Register a new spool',a.item_id,'primary')+button('link-spool','Plan / link a registered spool',a.item_id):''}</div></div>`;
    if(!a.spools.length)html+='<p class="fo-notice">Register each spool, then link its weld plan to this assembly.</p>';
    else html+=`<div class="tablewrap"><table class="fo-spools"><thead><tr><th>Spool / QR ID</th><th>Part number</th><th>Fabrication / process</th><th>Assembly readiness</th><th>BOM and records</th></tr></thead><tbody>${a.spools.map(s=>`<tr><td><strong>${esc(s.item_id)}</strong></td><td>${esc(s.google_part_number||'Not entered')}</td><td><span class="fo-tag ${s.fabrication_finished?'fo-ready':'fo-pending'}">${s.fabrication_finished?'Fabrication finished':'WIP'}</span><small>${s.current_step?'Step '+display(s.current_step)+' · ':''}${esc(({not_started:'Route not started',active:'In progress',completed:'Route completed',released:'Released',shipped:'Shipped',delivered:'Delivered'})[s.flow_status]||s.flow_status||'Route not started')}</small></td><td><span class="fo-tag ${s.ready_for_assembly?'fo-ready':s.blocked?'fo-blocked':'fo-pending'}">${s.ready_for_assembly?'Ready for assembly':'Not ready'}</span>${arr(s.blockers).length?`<small>${esc(s.blockers[0])}</small>`:''}</td><td><div class="actions">${button('parts',canManage()?'Create / edit BOM':'View BOM',s.item_id,'primary')}${button('welds','Welds',s.item_id)}${button('flow','Process flow',s.item_id)}${button('item','Item & QR',s.item_id)}</div></td></tr>`).join('')}</tbody></table></div>`;
    return html+'</section>'+historyView();
  }
  function historyView(){const rows=arr(state.detail?.events);return rows.length?`<section class="fo-card"><details><summary>Purchase order change history (${rows.length})</summary>${rows.map(e=>`<div class="fo-history"><strong>${esc(text(e.event).replace(/_/g,' '))}</strong><small>${esc(e.actor)} · ${esc(stamp(e.at))}</small>${e.details?.reason||e.details?.notes?`<p>${esc(e.details.reason||e.details.notes)}</p>`:''}</div>`).join('')}</details></section>`:'';}
  function field(name,label,value='',options={}){const common=`id="order-field-${esc(name)}" name="${esc(name)}"${options.required?' required':''}${options.disabled?' disabled':''}${options.readonly?' readonly':''}${options.maxlength?` maxlength="${options.maxlength}"`:''}`;let control;if(options.options)control=`<select ${common}>${options.options.map(([v,l])=>option(v,l,value)).join('')}</select>`;else if(options.type==='textarea')control=`<textarea ${common}>${esc(value)}</textarea>`;else control=`<input ${common} type="${esc(options.type||'text')}" value="${esc(value)}"${options.min!==undefined?` min="${options.min}"`:''}${options.max!==undefined?` max="${options.max}"`:''}${options.type==='number'?' step="1"':''}>`;return `<div class="field${options.full?' fo-full':''}"><label for="order-field-${esc(name)}">${esc(label)}${options.required?' *':''}</label>${control}${options.help?`<small class="fo-note">${esc(options.help)}</small>`:''}</div>`;}
  function formView(){
    const f=state.form,v=f.values;let title='',body='',label='Save';
    if(f.kind==='new-order'){
      title='New P.O';label='Create P.O';
      body=field('purchase_order','P.O number',v.purchase_order,{required:true,maxlength:200})+field('customer','Customer',v.customer,{maxlength:200,required:!v.existing_project_id})+field('existing_project_id','Existing project to connect (optional)',v.existing_project_id,{options:[['','Create a project for this PO'],...arr(state.list?.unassigned_projects).map(p=>[p.id,`${p.name} · ${p.id}`])],help:'Choose only after confirming which PO belongs to the existing project.'})+field('notes',v.existing_project_id?'Reason for connecting this project / PO setup notes':'PO setup notes',v.notes,{type:'textarea',full:true,required:Boolean(v.existing_project_id),maxlength:3000});
    }else if(f.kind==='edit-order'){
      title='Edit purchase order details';body=field('purchase_order','P.O number',v.purchase_order,{required:true,maxlength:200})+field('notes','PO notes',v.notes,{type:'textarea',full:true,maxlength:3000})+field('reason','Reason for this correction',v.reason,{required:true,type:'textarea',full:true,maxlength:3000});
    }else if(f.kind==='new-gpn'||f.kind==='edit-gpn'){
      title=f.kind==='new-gpn'?'Add G.P.N':'Edit G.P.N';body=field('gpn','G.P.N',v.gpn,{required:true,maxlength:160});if(f.kind==='edit-gpn')body+=field('reason','Reason for this correction',v.reason,{required:true,type:'textarea',full:true,maxlength:3000});
    }else if(f.kind==='new-assembly'){
      title='Add assembly';label=v.mode==='create'?'Register assembly and save order details':'Connect assembly to this GPN';
      body=field('gpn_id','G.P.N',v.gpn_id,{required:true,options:state.detail.gpns.map(g=>[g.id,g.gpn])})+field('mode','Assembly record',v.mode,{options:[['create','Register a new physical assembly'],['existing','Connect an existing assembly']]});
      if(v.mode==='existing')body+=field('item_id','Existing assembly',v.item_id,{required:true,full:true,options:[['','Select an existing assembly'],...arr(state.detail.available_assemblies).map(a=>[a.item_id,a.item_id])],help:'Only unassigned assembly records belonging to this project are offered.'});
      else body+=field('new_item_id','Unique assembly / QR ID',v.new_item_id,{required:true,maxlength:60})+field('drawing','Drawing / revision',v.drawing,{maxlength:160})+field('location','Current location',v.location,{required:true,maxlength:160})+field('handler','Current custodian',v.handler,{required:true,options:[['','Choose the employee who holds it'],...state.staff.map(e=>[e.badge,`${e.name} · ${e.badge}`])]});
      body+=field('assembly_part_number','Assembly part number',v.assembly_part_number,{required:true,maxlength:160})+field('required_spools','Spools needed',v.required_spools,{required:true,type:'number',min:1,max:10000,help:'Whole unique spool records needed for this physical assembly.'})+field('notes','Assembly order notes',v.notes,{type:'textarea',full:true,maxlength:3000});
    }else if(f.kind==='link-spool'){
      title='Plan / link a registered spool';label='Open spool plan';body=field('spool_id','Registered spool / QR ID',v.spool_id,{required:true,maxlength:2000,full:true,help:'Enter the existing Spool ID or scan its QR. Its current weld plan will open for review with this assembly selected.'});
    }else if(f.kind==='edit-assembly'){
      title='Edit assembly order details · '+f.itemId;body=field('assembly_part_number','Assembly part number',v.assembly_part_number,{required:true,maxlength:160})+field('required_spools','Spools needed',v.required_spools,{required:true,type:'number',min:Math.max(1,f.linked),max:10000,readonly:!f.countEditable,help:f.countEditable?'The count cannot be lower than the linked spool count.':'The assembly already has a traveler. Its declared spool count is locked.'})+field('notes','Assembly order notes',v.notes,{type:'textarea',full:true,maxlength:3000})+field('reason','Reason for this correction',v.reason,{required:true,type:'textarea',full:true,maxlength:3000});
    }
    return `<section class="fo-card fo-edit" id="ordersEditor"><h2>${esc(title)}</h2>${state.formError?`<div class="fo-error" role="alert">${esc(state.formError)}${state.stale?'<p>Close this form and refresh before making another change.</p>':''}</div>`:''}<form id="ordersForm"><div class="fo-form-grid">${body}</div>${f.kind==='new-assembly'&&v.mode==='create'?'<p class="fo-note">Registration creates the physical identity and order scope. Next, set its actual weld plan in Projects & welds.</p>':''}<div class="actions"><button id="ordersSave" class="primary" type="submit"${state.saving||state.stale?' disabled':''}>${state.saving?'Saving…':esc(label)}</button>${button('cancel-form','Cancel','','',state.saving)}</div></form></section>`;
  }
  function preserveForm(){if(!state.form)return;for(const key of Object.keys(state.form.values)){const el=node('order-field-'+key);if(el)state.form.values[key]=el.value;}}
  function render(){if(!state.active)return;node('ordersContent').innerHTML=state.error?header('Purchase orders','PO, GPN and assembly planning')+`<div class="fo-error" role="alert"><strong>Order records could not be verified.</strong><p>${esc(state.error)}</p>${button('refresh','Try again')}${button('home','All purchase orders')}</div>`:state.detail?orderView():board();node('ordersContent').setAttribute('aria-busy','false');wire();}
  function wire(){
    const search=node('ordersSearch');if(search)search.oninput=()=>{state.query=search.value;const caret=search.selectionStart;render();node('ordersSearch').focus();node('ordersSearch').setSelectionRange(caret,caret);};
    const gpn=node('ordersGpn');if(gpn)gpn.onchange=()=>{resetForm();state.gpn=gpn.value;state.assembly='';render();updateUrl();};
    const form=node('ordersForm');if(form)form.onsubmit=saveForm;
    const existing=node('order-field-existing_project_id');if(existing)existing.onchange=()=>{preserveForm();const p=arr(state.list?.unassigned_projects).find(p=>p.id===existing.value);if(p){state.form.values.customer=p.client||'';state.form.values.name='';}render();};
    const mode=node('order-field-mode');if(mode)mode.onchange=()=>{preserveForm();render();};
  }
  function validDetail(d,project){return d?.order?.project_id===project&&Number.isInteger(d.order.version)&&Array.isArray(d.gpns)&&Array.isArray(d.assemblies)&&d.assemblies.every(a=>Array.isArray(a.spools));}
  async function load(){
    if(!state.active||!me)return;if(state.loading)return state.pending;
    const sequence=++state.sequence,project=state.po;resetForm();state.loading=true;state.error='';state.detail=null;state.list=null;node('ordersContent').innerHTML='<div class="fo-state" role="status">Loading purchase orders and assembly scope…</div>';node('ordersContent').setAttribute('aria-busy','true');
    const pending=(async()=>{try{const result=await api(ROOT+(project?'/'+enc(project):''));if(sequence!==state.sequence||!state.active)return;
      if(project){if(!validDetail(result,project))throw Error('The order response could not be verified. Refresh before making a change.');state.detail=result;if(state.gpn&&!result.gpns.some(g=>g.id===state.gpn))throw Error('The selected GPN does not belong to this purchase order.');if(state.assembly){const a=result.assemblies.find(a=>a.item_id===state.assembly);if(!a||state.gpn&&a.gpn_id!==state.gpn)throw Error('The selected assembly does not belong to this PO and GPN.');state.gpn=a.gpn_id;}}
      else {if(!Array.isArray(result?.orders)||!Array.isArray(result?.unassigned_projects))throw Error('The purchase order register response could not be verified.');state.list=result;}
      render();updateUrl();
    }catch(error){if(sequence===state.sequence&&state.active){state.error=errorText(error);state.detail=null;state.list=null;render();}}
    finally{if(sequence===state.sequence){state.loading=false;state.pending=null;}}})();state.pending=pending;return pending;
  }
  async function open(options={}){if(!me)return;show('ordersPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;state.active=true;state.po=text(options.po||'');state.gpn=text(options.gpn||'');state.assembly=text(options.assembly||'');state.query='';state.loading=false;state.pending=null;state.saving=false;resetForm();await load();if(options.create===true&&canManage())return startForm('new-order');}
  async function startForm(kind,id=''){
    if(!canManage()||state.saving||state.loading)return;
    if(kind!=='new-order'&&!state.detail)return;
    if(kind==='new-order'&&state.po)return open({create:true});
    const request=++state.formRequest,d=state.detail,o=d?.order;let f={kind,po:state.po,version:o?.version||0,values:{}};
    if(kind==='new-order')f.values={purchase_order:'',customer:'',name:'',existing_project_id:'',notes:''};
    if(kind==='edit-order')f.values={purchase_order:o.purchase_order,notes:o.notes||'',reason:''};
    if(kind==='new-gpn')f.values={gpn:'',description:''};
    if(kind==='edit-gpn'){const g=d.gpns.find(g=>g.id===id);if(!g)return;f.gpnId=id;f.values={gpn:g.gpn,description:g.description||'',reason:''};}
    if(kind==='new-assembly'){
      if(!d.gpns.length)return;const seq=state.sequence,project=state.po;state.formError='';try{const staff=await api('/api/employees/directory');if(request!==state.formRequest||seq!==state.sequence||project!==state.po||!state.active)return;if(!Array.isArray(staff))throw Error('Employee choices could not be verified.');state.staff=staff;}catch(error){if(request===state.formRequest&&seq===state.sequence&&project===state.po&&state.active)notify(errorText(error));return;}
      f.values={gpn_id:id||state.gpn||d.gpns[0].id,mode:'create',item_id:'',new_item_id:'',drawing:'',location:'',handler:'',assembly_part_number:'',required_spools:1,notes:''};
    }
    if(kind==='edit-assembly'){const a=d.assemblies.find(a=>a.item_id===id);if(!a)return;f.itemId=id;f.linked=a.linked_spools;f.countEditable=a.count_editable===true;f.originalCount=a.required_spools;f.values={assembly_part_number:a.assembly_part_number,required_spools:a.required_spools,notes:a.notes||'',reason:''};}
    if(kind==='link-spool'){if(!d.assemblies.some(a=>a.item_id===id))return;f.itemId=id;f.values={spool_id:''};}
    resetForm();state.form=f;render();node('ordersEditor')?.scrollIntoView({block:'start'});
  }
  async function saveForm(event){
    event.preventDefault();if(!canManage()||!state.form||state.saving||state.stale)return;preserveForm();const f=state.form,v=f.values,sequence=state.sequence,project=f.po;let path=ROOT+(project?'/'+enc(project):''),method='POST',body={expected_version:f.version};
    try{
      if(f.kind==='link-spool'){const id=typeof qrId==='function'?qrId(v.spool_id,'item'):v.spool_id.trim();if(!id)throw Error('Enter or scan a valid registered spool ID.');await window.FabTracking.openPlan({project,item_id:id,assembly_id:f.itemId});return;}
      if(f.kind==='new-order'){if(v.purchase_order.trim().length<2)throw Error('Enter a PO number of at least two characters.');if(!v.existing_project_id&&!v.customer.trim())throw Error('Enter the customer.');if(v.existing_project_id&&v.notes.trim().length<4)throw Error('Record why this existing project belongs to the PO.');body={...body,purchase_order:v.purchase_order.trim(),customer:v.customer.trim(),name:v.existing_project_id?'':v.name.trim(),notes:v.notes.trim(),existing_project_id:v.existing_project_id||null};}
      else if(f.kind==='edit-order'){if(v.purchase_order.trim().length<2)throw Error('Enter a PO number of at least two characters.');method='PATCH';body={...body,purchase_order:v.purchase_order.trim(),notes:v.notes.trim(),reason:v.reason.trim()};}
      else if(['new-gpn','edit-gpn'].includes(f.kind)){if(!v.gpn.trim())throw Error('Enter the GPN.');path+='/gpns'+(f.gpnId?'/'+enc(f.gpnId):'');method=f.gpnId?'PATCH':'POST';body={...body,gpn:v.gpn.trim(),...(f.gpnId?{description:v.description,reason:v.reason.trim()}:{})};}
      else if(['new-assembly','edit-assembly'].includes(f.kind)){
        const n=Number(v.required_spools);if(!Number.isInteger(n)||n<1||n>10000)throw Error('Spools needed must be a whole number from 1 to 10,000.');if(!v.assembly_part_number.trim())throw Error('Enter the assembly part number.');
        body={...body,assembly_part_number:v.assembly_part_number.trim(),required_spools:n,notes:v.notes.trim()};path+='/assemblies';
        if(f.itemId){path+='/'+enc(f.itemId);method='PATCH';body.reason=v.reason.trim();if(n<f.linked)throw Error('Spools needed cannot be less than the number already linked.');if(!f.countEditable&&n!==f.originalCount)throw Error('The required spool count is locked by the assembly traveler.');}
        else {if(!state.detail.gpns.some(g=>g.id===v.gpn_id))throw Error('Choose a GPN from this PO.');body.gpn_id=v.gpn_id;
          if(v.mode==='existing'){if(!state.detail.available_assemblies.some(a=>a.item_id===v.item_id))throw Error('Choose an available assembly from this project.');body.item_id=v.item_id;body.create_item=null;}
          else {if(!v.new_item_id.trim()||!v.location.trim()||!v.handler)throw Error('Enter the assembly ID, current location and current custodian.');body.item_id=v.new_item_id.trim();body.create_item={id:body.item_id,drawing:v.drawing.trim(),location:v.location.trim(),handler:v.handler,welds_required:0};}
        }
      }
      if(method==='PATCH'&&body.reason.length<4)throw Error('Enter a correction reason of at least four characters.');
    }catch(error){state.formError=errorText(error);render();return;}
    state.saving=true;state.formError='';render();
    try{const result=await api(path,{method,body:JSON.stringify(body)});if(!state.active||sequence!==state.sequence||state.form!==f||state.po!==project)return;const target=project||result?.order?.project_id;if(!target||!validDetail(result,target))throw Error('The saved order response could not be verified. Refresh before another change.');state.po=target;state.detail=result;state.list=null;if(f.kind==='new-gpn'){const g=result.gpns.find(g=>g.gpn===body.gpn);state.gpn=g?.id||'';state.assembly='';}if(f.kind==='new-assembly'){state.gpn=body.gpn_id;state.assembly=body.item_id;}resetForm();notify('Purchase order saved.');render();updateUrl();}
    catch(error){if(state.active&&sequence===state.sequence&&state.form===f){state.formError=errorText(error);state.stale=error.status===409||!error.status||error.status>=500;render();}}
    finally{if(state.active&&sequence===state.sequence){state.saving=false;render();}}
  }
  async function download(template=false){
    if(!state.detail||!me||state.downloading)return;const project=state.po,q=new URLSearchParams();if(state.gpn)q.set('gpn_id',state.gpn);if(state.assembly)q.set('assembly_id',state.assembly);const url=ROOT+'/'+enc(project)+(template?'/bom-template.xlsx':'/bom.xlsx')+(q.size?'?'+q.toString():'');
    state.downloading=true;render();let objectUrl=null,anchor=null;
    try{const response=await fetch(url,{credentials:'same-origin',headers:{Accept:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}});if(!response.ok){let message='';try{const value=await response.json();message=typeof value.detail==='string'?value.detail:'';}catch(_){}throw Error(message||(response.status===401?'Sign in again to download the BOM.':'The Excel BOM could not be prepared.'));}if(!(response.headers.get('content-type')||'').includes('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))throw Error('The server did not return an Excel workbook. Refresh and try again.');const blob=await response.blob();objectUrl=URL.createObjectURL(blob);anchor=document.createElement('a');anchor.href=objectUrl;anchor.download=excelDownloadName(response.headers.get('content-disposition'));document.body.appendChild(anchor);anchor.click();anchor.remove();anchor=null;const finished=objectUrl;setTimeout(()=>URL.revokeObjectURL(finished),10000);objectUrl=null;notify('BOM Excel download started. Check your browser downloads.');}
    catch(error){notify(errorText(error));}finally{if(anchor)anchor.remove();if(objectUrl)URL.revokeObjectURL(objectUrl);state.downloading=false;if(state.active)render();}
  }
  async function act(action,id){
    if(action==='refresh')return load();if(action==='home')return open();if(action==='order')return open({po:id});
    if(action==='gpn'){if(!state.detail?.gpns.some(g=>g.id===id))return;resetForm();state.gpn=id;state.assembly='';state.query='';render();updateUrl();return;}
    if(action==='assembly'){const a=state.detail?.assemblies.find(a=>a.item_id===id);if(!a)return;resetForm();state.gpn=a.gpn_id;state.assembly=id;state.query='';render();updateUrl();return;}
    if(['new-order','edit-order','new-gpn','edit-gpn','new-assembly','edit-assembly'].includes(action))return startForm(action,id);
    if(action==='attach-project'){await startForm('new-order');node('order-field-existing_project_id')?.focus();return;}
    if(action==='cancel-form'){if(!state.saving){resetForm();render();}return;}
    if(action==='bom'||action==='template')return download(action==='template');
    if(action==='progress')return window.FabProgress.open({project:state.po});if(action==='job-packet')return window.FabDossier.open({project:state.po});
    if(action==='tracking')return window.FabTracking.open({project:state.po,view:'spools',resetFilters:true});
    if(action==='welds')return window.FabTracking.open({spool:id,project:state.po});if(action==='parts')return window.FabParts.open({spool:id,project:state.po});if(action==='flow')return window.FabFlow.open({item:id,project:state.po});if(action==='item')return openItem(id);
    if(action==='plan-assembly'&&canManage())return window.FabTracking.openPlan({project:state.po,item_id:id});
    if(action==='link-spool'&&canManage())return startForm('link-spool',id);
    if(action==='register-spool'&&canManage())return openNewItem({kind:'Spool',project:state.po});
  }
  node('ordersContent').addEventListener('click',async event=>{const control=event.target.closest('[data-order-action]');if(!control||control.disabled)return;try{await act(control.dataset.orderAction,control.dataset.orderId||'');}catch(error){notify(errorText(error));}});
  node('navOrders').onclick=()=>open({po:state.po,gpn:state.gpn,assembly:state.assembly});
  window.FabOrders={open,refresh:load,cancelPending(){state.active=false;state.sequence++;state.loading=false;state.pending=null;state.saving=false;resetForm();}};
})();
