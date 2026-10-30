/* Generate unique assembly and spool QR labels from saved purchase-order quantities. */
(() => {
  'use strict';
  const ROOT='/api/order-labels', PAGE_SIZE=100, node=id=>document.getElementById(id), enc=encodeURIComponent;
  const state={active:false,sequence:0,po:'',gpn:'',kind:'Assembly',offset:0,overview:null,labels:null,groups:[],employees:[],loading:false,saving:false,printing:false,error:'',notice:'',formError:'',stale:false,location:'',handler:''};
  const list=v=>Array.isArray(v)?v:[], display=v=>Number.isSafeInteger(v)&&v>=0?v.toLocaleString():'Not entered';
  const isSpool=()=>state.kind==='Spool', itemName=()=>isSpool()?'spool':'assembly';
  const canManage=()=>window.FabPermissions?.can('manage_production')===true&&state.overview?.permissions?.can_manage===true;
  const button=(action,label,disabled=false,cls='')=>`<button type="button" data-ol-action="${action}" class="${cls}"${disabled?' disabled':''}>${esc(label)}</button>`;
  const query=(offset=null)=>{const q=new URLSearchParams({kind:state.kind});if(state.gpn)q.set('gpn_id',state.gpn);if(offset!==null){q.set('offset',String(offset));q.set('limit',String(PAGE_SIZE));}return '?'+q.toString();};
  const endpoint=(suffix='',offset=null)=>ROOT+'/'+enc(state.po)+suffix+query(offset);
  function updateUrl(){const q=new URLSearchParams({'order-labels':'1',po:state.po});if(state.gpn)q.set('gpn',state.gpn);if(isSpool())q.set('kind','Spool');history.replaceState(null,'','/?'+q.toString());}
  function errorText(error){
    try{const d=JSON.parse(error.message);if(Array.isArray(d))return d.map(v=>v.msg||'Check the entered value.').join('; ');if(typeof d.message==='string')return d.message;}catch(_){}
    return String(error.message||'The QR labels could not be loaded.');
  }
  function validOverview(d){return d&&d.order?.project_id===state.po&&(!d.kind||d.kind===state.kind)&&Number.isInteger(d.order.version)&&Array.isArray(d.groups)&&d.totals&&d.permissions&&typeof d.qr_ready==='boolean'&&d.groups.every(g=>typeof g.gpn_id==='string'&&typeof g.gpn==='string'&&Number.isInteger(g.registered_quantity));}
  function validLabels(d){return d&&d.order?.project_id===state.po&&(!d.kind||d.kind===state.kind)&&Array.isArray(d.items)&&Number.isInteger(d.total)&&d.items.every(i=>typeof i.id==='string'&&typeof i.google_part_number==='string'&&typeof i.purchase_order==='string'&&(!isSpool()||typeof i.assembly_id==='string'&&typeof i.gpn==='string'));}
  function header(){return `<div class="ol-head"><div><span class="ol-eyebrow">CLM · Purchase orders</span><h1>${isSpool()?'Spool':'GPN'} QR labels</h1><p>${state.overview?'P.O. '+esc(state.overview.order.purchase_order):'Create and print labels from your saved P.O.'}</p></div><div class="actions">${button('back','Back to P.O.',state.saving)}${button('refresh','Refresh',state.loading||state.saving||state.printing)}</div></div>`;}
  function generation(){
    const d=state.overview,remaining=d.totals.remaining_quantity,maximum=d.limit||500;
    if(!canManage())return '<p class="ol-note">An administrator or supervisor can generate additional '+itemName()+' labels.</p>';
    if(!d.groups.length)return '<div class="ol-state"><strong>Add the GPNs and assembly quantities first.</strong><p>Open the P.O. setup to enter the assemblies this order needs.</p></div>';
    if(d.totals.undeclared_groups)return '<div class="ol-warning"><strong>Some GPN quantities have not been entered.</strong><p>Select a GPN with saved quantities, or return to the P.O. to complete its setup. Existing labels remain available below.</p></div>';
    if(remaining===0)return '<div class="ol-ready"><strong>All '+itemName()+' QR codes are ready.</strong><p>Print or reprint the labels below. Each code continues to open the same '+itemName()+' record.</p></div>';
    const disabled=state.saving||state.stale||!d.qr_ready,quantity=Math.min(remaining,maximum);
    return `<section class="ol-create"><h2>Generate the remaining QR codes</h2><p>${isSpool()?'The spool numbers and quantities come from this P.O. Any missing assembly records are created automatically, and each spool stays linked to its own assembly.':'The GPN numbers and quantities come from this P.O.'} Choose the current location and responsible employee for the new records.</p>${state.formError?`<div class="ol-error" role="alert">${esc(state.formError)}${state.stale?'<div class="actions">'+button('refresh','Reload saved labels',state.saving)+'</div>':''}</div>`:''}<form id="orderLabelsForm"><fieldset${disabled?' disabled':''}><div class="ol-fields"><div class="field"><label for="olLocation">Current location</label><input id="olLocation" name="location" value="${esc(state.location)}" maxlength="160" autocomplete="off" placeholder="For example: Receiving" required></div><div class="field"><label for="olHandler">Responsible employee</label><select id="olHandler" name="handler" required><option value="">Choose the employee</option>${state.employees.map(e=>`<option value="${esc(e.badge)}"${e.badge===state.handler?' selected':''}>${esc(e.name)} · ${esc(e.badge)}</option>`).join('')}</select></div></div><p class="ol-note">Generating codes registers the individual items and locks their initial quantity setup. Review the P.O. quantities before continuing.</p><button id="olGenerate" type="submit" class="primary">${state.saving?'Generating…':isSpool()?'Generate spool QR codes':'Generate '+display(quantity)+' QR code'+(quantity===1?'':'s')}</button>${isSpool()?`<span class="ol-batch-note">Up to ${display(maximum)} new items per batch, including assembly records.</span>`:remaining>maximum?`<span class="ol-batch-note">${display(maximum)} at a time · ${display(remaining)} remaining</span>`:''}</fieldset></form></section>`;
  }
  function labelList(){
    const d=state.labels,disabled=state.loading||state.saving||state.printing,first=d.total?state.offset+1:0,last=state.offset+d.items.length;
    let html=`<section class="ol-labels"><div class="ol-section-head"><div><h2>Saved ${itemName()} labels</h2><p>${d.total?display(first)+'–'+display(last)+' of '+display(d.total)+' labels':'Generated labels will appear here.'}</p></div>${button('print',state.printing?'Preparing print sheet…':'Print labels'+(d.total?' '+display(first)+'–'+display(last):''),disabled||!d.items.length||!state.overview.qr_ready,'primary')}</div>`;
    if(d.items.length)html+=`<div class="ol-label-grid">${d.items.map(i=>`<article class="ol-label"><div class="ol-qr">${state.overview.qr_ready?`<img src="/api/items/${enc(i.id)}/qr.png" width="90" height="90" loading="lazy" alt="QR for ${esc(i.id)}">`:'<span>QR unavailable</span>'}</div><div class="ol-label-copy"><span class="ol-eyebrow">${isSpool()?'Spool':'GPN / Assembly'}</span><strong>${esc(i.google_part_number)}</strong><span>P.O. ${esc(i.purchase_order)}</span>${isSpool()?`<span>GPN ${esc(i.gpn)}</span><span class="ol-parent">Assembly ${esc(i.assembly_id)}</span>`:''}<code>${esc(i.id)}</code><div class="actions"><button type="button" data-ol-item="${esc(i.id)}">Open ${itemName()}</button>${isSpool()&&canManage()&&!i.weld_plan_exists?`<button type="button" data-ol-plan="${esc(i.id)}" data-ol-parent="${esc(i.assembly_id)}">Set weld plan</button>`:''}${state.overview.qr_ready?`<a href="/api/items/${enc(i.id)}/qr.png" download="${esc(i.id)}-QR.png">Download QR</a>`:''}</div></div></article>`).join('')}</div>`;
    if(d.total>PAGE_SIZE)html+=`<div class="ol-pagination">${button('previous','Previous '+PAGE_SIZE,disabled||state.offset===0)}<span>${display(first)}–${display(last)} of ${display(d.total)}</span>${button('next','Next '+PAGE_SIZE,disabled||last>=d.total)}</div>`;
    return html+'<p class="ol-note">Print at 100% scale, or choose Save as PDF in the print dialog. Reprinting uses the existing QR codes.</p></section>';
  }
  function render(){
    if(!state.active)return;let html=header();
    if(state.loading)html+='<div class="ol-state" role="status">Loading the P.O. and saved QR labels…</div>';
    else if(state.error)html+=`<div class="ol-error" role="alert"><strong>The QR labels could not be opened.</strong><p>${esc(state.error)}</p>${button('refresh','Try again')}</div>`;
    else if(state.overview&&state.labels){
      const d=state.overview,disabled=state.saving||state.printing;
      if(state.notice)html+=`<div class="ol-ready" role="status">${esc(state.notice)}</div>`;
      html+=`<div class="ol-filters"><div class="ol-scope field"><label for="olKind">Label type</label><select id="olKind"${disabled?' disabled':''}><option value="Assembly"${!isSpool()?' selected':''}>GPN / Assembly labels</option><option value="Spool"${isSpool()?' selected':''}>Spool labels</option></select></div><div class="ol-scope field"><label for="olGpn">GPN / Assembly number</label><select id="olGpn"${disabled?' disabled':''}><option value="">All GPNs on this P.O.</option>${state.groups.map(g=>`<option value="${esc(g.gpn_id)}"${g.gpn_id===state.gpn?' selected':''}>${esc(g.gpn)}</option>`).join('')}</select></div></div><div class="ol-counts"><div><span>QR codes ready</span><strong>${display(d.totals.registered_quantity)}</strong></div><div><span>QR codes still to generate</span><strong>${display(d.totals.remaining_quantity)}</strong></div></div>`;
      if(!d.qr_ready)html+='<div class="ol-warning">QR printing is unavailable until the application has a public HTTPS address configured.</div>';
      html+=generation()+labelList();
    }
    node('orderLabelsContent').innerHTML=html;node('orderLabelsContent').setAttribute('aria-busy',String(state.loading));
    const form=node('orderLabelsForm');if(form)form.onsubmit=event=>{event.preventDefault();return generate();};
    const select=node('olGpn');if(select)select.onchange=()=>{state.gpn=select.value;state.offset=0;state.notice='';return load();};
    const kind=node('olKind');if(kind)kind.onchange=()=>{state.kind=kind.value==='Spool'?'Spool':'Assembly';state.offset=0;state.notice='';return load();};
    const location=node('olLocation'),handler=node('olHandler');if(location)location.oninput=()=>{state.location=location.value;};if(handler)handler.onchange=()=>{state.handler=handler.value;};
  }
  async function load(initial=false){
    if(!state.active||state.saving||!me)return;const sequence=++state.sequence;state.loading=true;state.error='';state.formError='';state.stale=false;render();
    try{
      const requests=[api(endpoint()),api(endpoint('/labels',state.offset))];
      if(initial)requests.push(api(ROOT+'/'+enc(state.po)+'?kind='+enc(state.kind)));
      const [overview,labels,all]=await Promise.all(requests);
      if(!state.active||sequence!==state.sequence)return;
      if(!validOverview(overview)||!validLabels(labels)||(initial&&!validOverview(all)))throw Error('The P.O. response could not be verified. Refresh to try again.');
      state.overview=overview;state.labels=labels;if(initial)state.groups=all.groups;
      if(state.offset&&labels.total<=state.offset){state.offset=Math.max(0,Math.floor(Math.max(0,labels.total-1)/PAGE_SIZE)*PAGE_SIZE);return await load();}
      if(canManage()&&!state.employees.length){state.employees=await api('/api/employees/directory');if(!state.active||sequence!==state.sequence)return;if(!Array.isArray(state.employees))throw Error('The employee directory could not be loaded.');}
      updateUrl();
    }catch(error){if(state.active&&sequence===state.sequence){state.error=errorText(error);state.overview=null;state.labels=null;}}
    finally{if(state.active&&sequence===state.sequence){state.loading=false;render();}}
  }
  async function generate(){
    if(state.saving||state.stale||!canManage()||!state.overview?.qr_ready)return;
    state.location=node('olLocation')?.value.trim()||'';state.handler=node('olHandler')?.value||'';
    if(!state.location||!state.employees.some(e=>e.badge===state.handler)){state.formError='Choose the actual current location and responsible employee for this batch.';render();return;}
    const sequence=++state.sequence,payload={expected_version:state.overview.order.version,kind:state.kind,location:state.location,handler:state.handler,...(state.gpn?{gpn_id:state.gpn}:{})};
    state.saving=true;state.formError='';state.notice='';render();
    try{
      const d=await api(ROOT+'/'+enc(state.po)+'/generate',{method:'POST',body:JSON.stringify(payload)});
      if(!state.active||sequence!==state.sequence)return;
      if(!validOverview(d)||!Number.isInteger(d.created_count))throw Error('The generation result could not be verified. Reload the saved labels before trying again.');
      state.overview=d;
      if(isSpool())state.notice=d.created_count?display(d.created_spool_count||0)+' unique spool QR codes created.'+(d.created_assembly_count?' '+display(d.created_assembly_count)+' assembly records created automatically.':'')+(d.totals.remaining_quantity?' Generate the next batch to finish this P.O.':' All spool labels are ready to print.'):'All required spool QR codes already exist. Their original codes are ready to reprint.';
      else state.notice=d.created_count?display(d.created_count)+' unique assembly QR codes created. The labels are ready to print.':'All required assembly QR codes already exist. Their original codes are ready to reprint.';
      state.offset=0;state.saving=false;await load();
    }catch(error){if(state.active&&sequence===state.sequence){state.formError=errorText(error);state.stale=error.status===409||!error.status;if(state.stale)state.formError+=' Reload the saved labels before trying again.';}}
    finally{if(state.active&&sequence===state.sequence){state.saving=false;render();}}
  }
  function printHtml(d){
    const spool=isSpool();
    const labels=d.items.map(i=>`<article class="label"><img src="/api/items/${enc(i.id)}/qr.png" alt="QR for ${esc(i.id)}"><div class="label-info"><span class="label-kind">${spool?'SPOOL':'GPN / ASSEMBLY'}</span><strong>${esc(i.google_part_number)}</strong><span class="label-po">P.O. ${esc(i.purchase_order)}</span>${spool?`<span class="label-parent">GPN ${esc(i.gpn)}</span><span class="label-parent">Assembly ${esc(i.assembly_id)}</span>`:''}<code>${esc(i.id)}</code></div></article>`).join('');
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>FabTrace QR labels · ${esc(d.order.purchase_order)}</title><style>@page{size:letter;margin:.4in}*{box-sizing:border-box}body{font:12px/1.35 Arial,sans-serif;color:#142e40;margin:20px}.toolbar{max-width:8in;margin:0 auto 20px;padding:14px;background:#edf5fb;border:1px solid #ccdce7;border-radius:8px}.toolbar button{padding:9px 16px;margin-right:10px;cursor:pointer}.sheet{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.1in;max-width:8in;margin:auto}.label{min-height:2.45in;break-inside:avoid;page-break-inside:avoid;border:1px dashed #8a9eab;text-align:center;padding:.1in;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:5px;overflow-wrap:anywhere;min-width:0}.label img{width:1.1in;height:1.1in;object-fit:contain;image-rendering:pixelated;flex-shrink:0}.label-info{width:100%;display:grid;gap:5px}.label-kind{font-size:8px;font-weight:bold;letter-spacing:.07em}.label strong{font-size:12px}.label-po{font-size:10px}.label-parent{font-size:9px}.label code{font:10px/1.3 monospace;overflow-wrap:anywhere}@media print{body{margin:0}.toolbar{display:none}.sheet{max-width:none}}</style></head><body><div class="toolbar"><h1 style="font-size:19px;margin:0 0 8px">P.O. ${esc(d.order.purchase_order)} · ${d.items.length} ${spool?'spool':'assembly'} labels</h1><p id="printStatus">Loading all QR images before printing…</p><button id="printButton" disabled>Print / Save as PDF</button><button id="closeButton">Close</button><small>Print at 100% scale. Each label opens its own ${spool?'spool':'assembly'} record.</small></div><main class="sheet">${labels}</main><script>
const printButton=document.getElementById('printButton'),status=document.getElementById('printStatus');
document.getElementById('closeButton').onclick=()=>window.close();printButton.onclick=()=>window.print();
Promise.all([...document.images].map(im=>new Promise((resolve,reject)=>{if(im.complete){return im.naturalWidth?resolve():reject(Error('QR image unavailable'));}const timer=setTimeout(()=>reject(Error('QR image timed out')),20000);im.onload=()=>{clearTimeout(timer);im.naturalWidth?resolve():reject(Error('QR image unavailable'));};im.onerror=()=>{clearTimeout(timer);reject(Error('QR image unavailable'));};}))).then(()=>{status.textContent='All QR images are ready. Print at 100% scale.';printButton.disabled=false;setTimeout(()=>window.print(),250);}).catch(()=>{status.textContent='A QR image could not load. Close this sheet, refresh FabTrace and sign in again if needed, then retry printing.';});
<\/script></body></html>`;
  }
  async function print(){
    if(state.printing||state.saving||!state.labels?.items.length||!state.overview?.qr_ready)return;
    const sheet=window.open('','_blank');if(!sheet){state.notice='Allow pop-ups for FabTrace, then choose Print labels again.';render();return;}
    sheet.document.write('<!doctype html><title>Preparing FabTrace labels</title><p>Preparing your QR label sheet…</p>');sheet.document.close();
    const sequence=state.sequence;state.printing=true;render();
    try{
      const d=await api(endpoint('/labels',state.offset));
      if(!state.active||sequence!==state.sequence){sheet.close();return;}
      if(!validLabels(d)||!d.items.length||!d.qr_ready)throw Error('These labels are no longer available. Refresh the saved labels.');
      if(sheet.closed)throw Error('The print window was closed. Choose Print labels to try again.');
      sheet.document.open();sheet.document.write(printHtml(d));sheet.document.close();
      state.notice='Print sheet opened. Reprinting this batch keeps the same QR codes.';
    }catch(error){if(!sheet.closed)sheet.close();if(state.active&&sequence===state.sequence)state.notice=errorText(error);}
    finally{if(state.active&&sequence===state.sequence){state.printing=false;render();}}
  }
  async function open(options={}){
    if(!me)return;show('orderLabelsPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;
    Object.assign(state,{active:true,po:String(options.po||''),gpn:String(options.gpn||''),kind:options.kind==='Spool'?'Spool':'Assembly',offset:0,overview:null,labels:null,groups:[],employees:[],loading:false,saving:false,printing:false,error:'',notice:'',formError:'',stale:false,location:'',handler:''});
    if(!state.po){state.error='Open a saved purchase order to generate its assembly and spool labels.';render();return;}await load(true);
  }
  node('orderLabelsContent').addEventListener('click',async event=>{
    const plan=event.target.closest('[data-ol-plan]');if(plan&&!state.saving&&canManage())return window.FabTracking.openPlan({project:state.po,item_id:plan.dataset.olPlan,assembly_id:plan.dataset.olParent});
    const item=event.target.closest('[data-ol-item]');if(item&&!state.saving)return openItem(item.dataset.olItem);
    const target=event.target.closest('[data-ol-action]');if(!target||target.disabled||state.saving)return;
    try{const action=target.dataset.olAction;if(action==='back')return window.FabOrderSetup.open({po:state.po});if(action==='refresh')return load(true);if(action==='print')return print();if(action==='previous'||action==='next'){state.offset=Math.max(0,state.offset+(action==='next'?PAGE_SIZE:-PAGE_SIZE));state.notice='';return load();}}
    catch(error){notify(errorText(error));}
  });
  window.FabOrderLabels={open,refresh:()=>load(true),cancelPending(){state.active=false;state.sequence++;state.loading=false;state.saving=false;state.printing=false;}};
})();
