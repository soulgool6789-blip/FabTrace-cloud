/* Physical-spool material records, MTR files and mandatory arrival QA/QC. */
(() => {
  'use strict';
  const node=id=>document.getElementById(id),dialog=node('spoolBomDialog'),arr=value=>Array.isArray(value)?value:[],text=value=>String(value??'');
  if(!dialog)return;
  const materialFields=[['supplier','Supplier',160],['supplier_piece_id','Supplier piece / lot ID',160],['heat_number','Heat number',160],['mtr_reference','MTR reference',300],['mtr_url','MTR document link (optional HTTPS)',2000],['notes','Notes',3000]];
  const inspection=()=>({result:'',reference:'',notes:'',checks:{},expected_version:null,basis_sha256:''});
  const mtrDraft=()=>({files:[],reference:'',revision:'',reason:'Initial MTR received for this spool',automaticReason:true,preview:null,error:'',stale:false,attachPiece:''});
  const state={sequence:0,descriptor:null,data:null,draft:null,draftRows:[],traceVersion:0,traceBasis:'',dirty:false,reason:'',panel:'materials',inspection:inspection(),adoptReason:'',mtr:mtrDraft(),historyDetail:{},historyPending:null,historyError:'',scanTimer:null,resume:null,loading:false,working:false,downloading:false,saving:false,error:'',formError:'',notice:'',stale:false,trigger:null,controller:null,downloadController:null};
  const count=value=>Number.isSafeInteger(value)&&value>=0,idOK=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(value);
  const apiPath=value=>typeof value==='string'?value.match(/^\/api\/spool-boms\/(requirements|spools)\/([A-Za-z0-9_-]{1,80})$/):null;
  const clone=value=>value==null?value:JSON.parse(JSON.stringify(value));
  const busy=()=>state.loading||state.working||state.saving;
  const button=(action,label,extra='',primary=false,disabled=false)=>`<button type="button" data-fbom-action="${action}"${primary?' class="primary"':''}${disabled?' disabled':''} ${extra}>${esc(label)}</button>`;
  const bytes=value=>value>=1048576?(value/1048576).toFixed(1)+' MB':Math.max(1,Math.ceil(value/1024))+' KB';
  const stamp=value=>value?new Date(value).toLocaleString():'';
  function documentUrl(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:'';}catch(_){return '';}}
  function localDocumentUrl(value){
    if(typeof value!=='string'||!/^\/api\/(?:spool-boms\/(?:workbooks|mtr-files)\/|spool-documents\/files\/)[A-Za-z0-9_.\/-]+(?:\?download=1)?$/.test(value)||value.includes('..'))return '';
    return value;
  }
  function descriptor(value){
    const path=apiPath(value?.api_url);if(!path)return null;
    if(path[1]==='spools')return {...value,item_id:path[2],spool_number:text(value.spool_number||path[2])};
    return typeof value.spool_number==='string'&&value.spool_number&&typeof value.revision==='string'&&count(value.line_count)?value:null;
  }
  function link(value){
    const d=descriptor(value);if(!d)return '';const physical=apiPath(d.api_url)[1]==='spools';
    return `<button type="button" class="fbom-link" data-spool-bom-url="${esc(d.api_url)}" data-spool-bom-number="${esc(d.spool_number)}" data-spool-bom-revision="${esc(d.revision||'')}" data-spool-bom-lines="${count(d.line_count)?d.line_count:0}" aria-haspopup="dialog" aria-controls="spoolBomDialog" aria-label="${physical?'Materials and arrival QA/QC for physical spool '+esc(d.item_id):'Bill of materials for spool '+esc(d.spool_number)}">${physical?'Materials &amp; QA/QC':'Bill of materials'}</button>`;
  }
  function spoolLink(id,spoolNumber=''){return idOK(id)?link({api_url:'/api/spool-boms/spools/'+encodeURIComponent(id),item_id:id,spool_number:spoolNumber||id}):'';}
  function valid(data,d){
    const path=apiPath(d?.api_url),c=data?.context;if(!path||!c||c.kind!==(path[1]==='spools'?'spool':'requirement')||(path[1]==='spools'?c.item_id:c.requirement_id)!==path[2])return false;
    if(!Array.isArray(data.lines)||!count(data.line_count)||data.lines.length!==data.line_count||typeof data.spool_number!=='string')return false;
    if(path[1]==='requirements')return data.spool_number===d.spool_number&&data.revision===d.revision&&data.line_count===d.line_count&&!!data.source_workbook;
    const t=data.traceability,a=data.arrival;
    return typeof data.bom_available==='boolean'&&t&&count(t.version)&&typeof t.editable==='boolean'&&typeof t.complete==='boolean'&&Array.isArray(t.materials)&&Array.isArray(t.history)&&t.materials.every(p=>typeof p.piece_key==='string'&&p.piece_key.length>0&&materialFields.every(([key])=>typeof p[key]==='string'))&&data.source_status&&a&&count(a.version)&&['pending','passed','failed','needs_reinspection'].includes(a.status)&&typeof a.basis_sha256==='string'&&Array.isArray(a.history)&&Array.isArray(a.checks_catalog)&&a.checks_catalog.every(check=>typeof check.key==='string'&&typeof check.label==='string');
  }
  function errorText(error){
    if(error?.status===401)return 'Your session has expired. Sign in again, then reopen this spool.';
    if(error?.status===403)return 'Your account does not have permission for this action.';
    let message=text(error?.message||'The spool record could not be loaded. Please try again.');
    try{const parsed=JSON.parse(message);message=typeof parsed.detail==='string'?parsed.detail:parsed.message||arr(parsed.blockers||parsed.receiving_blockers||parsed.detail?.blockers||parsed.detail?.receiving_blockers).join('; ')||message;}catch(_){}
    return message;
  }
  async function request(url,options={}){
    const response=await fetch(url,{credentials:'same-origin',redirect:'error',...options});let data;
    try{data=await response.json();}catch(_){const error=Error('The server returned an unreadable response. Reload this spool before retrying.');error.status=response.status;throw error;}
    if(!response.ok){const detail=data.detail,message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map(row=>row.msg||text(row)).join('; '):detail?.message||arr(detail?.blockers||detail?.receiving_blockers).join('; ')||data.message||'This request could not be completed.';const error=Error(message);error.status=response.status;throw error;}
    return data;
  }
  function materialDraft(data){return arr(data.traceability?.materials).map(row=>({piece_key:row.piece_key,...Object.fromEntries(materialFields.map(([key])=>[key,text(row[key])]))}));}
  function applyData(data,keepDraft=false){
    const changed=state.traceVersion!==data.traceability?.version||state.traceBasis!==data.source_status?.expected_bom_sha256;
    state.data=data;
    if(!keepDraft||!state.draft||!state.dirty){state.draft=materialDraft(data);state.draftRows=clone(arr(data.traceability?.materials));state.traceVersion=data.traceability?.version||0;state.traceBasis=data.source_status?.expected_bom_sha256||'';state.dirty=false;state.reason=data.traceability?.configured?'':'Initial material records for this spool';state.stale=false;}
    else if(changed){state.stale=true;state.formError='Saved materials or the BOM changed while your edits were open. Your draft is retained. Reload saved values before applying a new revision.';}
  }
  function bindInspectionContext(){
    const f=state.inspection,a=state.data?.arrival;if(!a)return false;
    const changed=f.expected_version!==null&&(f.expected_version!==a.version||f.basis_sha256!==a.basis_sha256);
    if(changed){f.result='';f.checks={};state.formError='The material evidence or arrival decision changed. Review the current records and confirm the inspection checks again. Your written reference and findings are retained.';}
    f.expected_version=a.version;f.basis_sha256=a.basis_sha256;return changed;
  }
  function contextField(label,value){return value?`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`:'';}
  function contextView(){const c=state.data.context;return `<dl class="fbom-context">${contextField('P.O.',c.purchase_order||c.project_id)}${contextField('Assembly',c.assembly_number||c.assembly_id)}${contextField('Spool number',state.data.spool_number)}${contextField('Unique physical spool ID',c.item_id)}</dl>`;}
  function pieceName(row){return 'Item '+text(row.item)+' · Piece '+text(row.piece_number)+' of '+text(row.pieces_on_line);}
  function sourceView(){
    const d=state.data,s=d.source_status||{},source=s.pinned||s.current,available=d.bom_available!==false,download=localDocumentUrl(source?.download_url||d.source_workbook?.download_url);
    return `<section class="fbom-source-card"><div class="fbom-section-heading"><div><h3>${available?'Bill of material for this spool':'Add this spool’s bill of material'}</h3><p>${available?'Material quantities are for one spool. Heat numbers and MTR records below belong only to this physical spool.':'Upload or create the spool BOM before recording its material rows. Arrival failures and MTR documents can still be recorded.'}</p></div>${button('documents','BOM & drawings','',false,busy())}</div>${source?`<p class="fbom-note">${s.pinned?'Recorded material basis':'Current BOM reference'}: <strong>${esc(source.filename||d.source_document||'BOM')}</strong>${source.revision?' · Revision '+esc(source.revision):''}</p>`:''}${s.changed?`<div class="fbom-warning"><strong>A different BOM is now available.</strong><p>The saved material entries still belong to the previous BOM. Adopting the new BOM archives those entries and starts blank rows. Re-enter and confirm the heat numbers and MTR references for the new BOM.</p>${s.can_adopt?button('adopt-panel','Review new BOM','',false,busy()):`<p>${esc(s.blocked_reason||'A permitted employee must review the replacement BOM.')}</p>`}</div>`:''}${download?`<div class="actions"><a href="${esc(download)}" download>Download ${s.pinned?'recorded':'current'} BOM</a></div>`:''}${arr(d.lines).length?`<details class="fbom-bom-table"><summary>View material list · ${d.line_count} lines</summary>${bomTable(d)}</details>`:''}</section>`;
  }
  function bomTable(d){return `<div class="fbom-table-wrap" role="region" tabindex="0" aria-label="Bill of material for ${esc(d.spool_number)}"><table><caption>Bill of materials · ${esc(d.spool_number)}</caption><thead><tr><th>Item</th><th>Qty</th><th>Part / TAS number</th><th>Description</th><th>Length</th><th>Material</th></tr></thead><tbody>${arr(d.lines).map(row=>`<tr><td>${esc(row.item)}</td><td>${esc(row.quantity)}</td><td>${esc(row.part_number||row.tas_ln_number||'')}</td><td>${esc(row.description)}</td><td>${esc(row.length_display||row.length||'—')}</td><td>${esc(row.material||'')}</td></tr>`).join('')}</tbody></table></div>`;}
  function arrivalView(){
    const a=state.data.arrival;if(!a)return '';
    const labels={pending:'Awaiting QA/QC',passed:'Pass',failed:'Fail',needs_reinspection:'Needs reinspection'},latest=a.latest;
    return `<section class="fbom-arrival fbom-arrival-${a.status}"><div class="fbom-section-heading"><div><span class="fbom-eyebrow">Mandatory arrival inspection</span><h3>${labels[a.status]}</h3><p>${a.can_proceed?'Arrival QA/QC is current for this spool’s recorded materials.':'Work is blocked until QA/QC records a current passing arrival inspection.'}</p></div>${state.panel==='inspection'?'':a.permissions?.can_inspect?button('inspection-panel',latest?'Record reinspection':'Record arrival inspection','',true,busy()):'<span class="fbom-role-note">QA/QC or administrator records the decision</span>'}</div>${latest?`<p class="fbom-note">Last decision: <strong>${esc(latest.result)}</strong> · ${esc(latest.actor)} · ${esc(stamp(latest.at))}${latest.reference?' · '+esc(latest.reference):''}</p>`:''}${!a.can_proceed&&arr(a.blockers).length?`<ul class="fbom-blockers">${a.blockers.map(message=>`<li>${esc(typeof message==='string'?message:message.message||message.detail||'Arrival approval is outstanding.')}</li>`).join('')}</ul>`:''}</section>`;
  }
  function traceField(piece,key,label,max){
    const id='fbom-'+piece.piece_key+'-'+key,value=text(piece[key]),common=`id="${esc(id)}" data-fbom-piece="${esc(piece.piece_key)}" data-fbom-field="${key}" maxlength="${max}"`;
    return `<div class="fbom-field${key==='notes'||key==='mtr_url'?' fbom-wide':''}"><label for="${esc(id)}">${esc(label)}</label>${key==='notes'?`<textarea ${common} rows="2">${esc(value)}</textarea>`:`<input ${common} type="${key==='mtr_url'?'url':'text'}" value="${esc(value)}"${key==='mtr_reference'?' list="fbomMtrReferences"':''} autocomplete="off">`}</div>`;
  }
  function coverage(){const values=state.draft||[],heat=values.filter(p=>p.heat_number.trim()).length,mtr=values.filter(p=>p.mtr_reference.trim()).length;return heat+' of '+values.length+' heat numbers entered · '+mtr+' of '+values.length+' MTR references entered'+(heat<values.length||mtr<values.length?' · Missing details remain incomplete.':'.');}
  function traceabilityView(){
    const d=state.data,t=d.traceability;if(!t)return '';
    const values=state.draft||[],rows=state.draftRows,editable=t.editable,disabled=busy(),docs=arr(d.mtr_documents?.current);
    if(!rows.length)return `<section class="fbom-trace"><h3>Heat numbers & MTRs</h3><p class="fbom-note">${d.bom_available?'This BOM does not yet have usable physical material rows.':'Add a structured BOM to create the material rows for this spool.'}</p>${t.locked_reason?`<p class="fbom-locked">${esc(t.locked_reason)}</p>`:''}</section>`;
    return `<section id="spoolBomTraceability" class="fbom-trace"><div class="fbom-trace-head"><div><h3>Heat numbers & MTRs</h3><p>Material records for <strong>${esc(d.context.item_id)}</strong></p></div><span class="fbom-badge">${t.configured?'Saved revision '+t.version:'Not saved yet'}</span></div><p class="fbom-note">Each piece can have its own heat and MTR. Saving these entries does not approve arrival QA/QC.</p><p id="spoolBomCoverage" class="fbom-coverage">${coverage()}</p>${!editable?`<p class="fbom-locked">${esc(t.locked_reason||'Your role can view these records. A permitted employee can update them.')}</p>`:''}${state.formError?formErrorView():''}<datalist id="fbomMtrReferences">${docs.map(doc=>`<option value="${esc(doc.reference)}">${esc(doc.filename)}</option>`).join('')}</datalist><form id="spoolBomTraceForm" novalidate><fieldset${disabled?' disabled':''}>${rows.map(piece=>{const p=values.find(row=>row.piece_key===piece.piece_key)||{piece_key:piece.piece_key,...Object.fromEntries(materialFields.map(([key])=>[key,'']))},mtr=docs.find(doc=>doc.reference===p.mtr_reference);return `<section class="fbom-piece"><h4>${esc(pieceName(piece))}</h4><p class="fbom-piece-description">${esc(piece.description)}</p><p class="fbom-note">${esc(piece.part_number||piece.tas_ln_number||'Part number not entered')} · ${esc(piece.material||'')}${piece.length_display?' · '+esc(piece.length_display):''}</p>${editable?`<div class="fbom-piece-fields">${materialFields.filter(([key])=>['heat_number','mtr_reference'].includes(key)).map(([key,label,max])=>traceField(p,key,label,max)).join('')}</div><details class="fbom-piece-options"><summary>Supplier, document link and notes</summary><div class="fbom-piece-fields">${materialFields.filter(([key])=>!['heat_number','mtr_reference'].includes(key)).map(([key,label,max])=>traceField(p,key,label,max)).join('')}</div></details>`:`<dl class="fbom-read-fields">${materialFields.map(([key,label])=>`<div><dt>${esc(label)}</dt><dd>${key==='mtr_url'&&documentUrl(p[key])?`<a href="${esc(documentUrl(p[key]))}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Open MTR document</a>`:esc(p[key]||'Not entered')}</dd></div>`).join('')}</dl>`}<div class="actions">${mtr&&localDocumentUrl(mtr.view_url)?`<a href="${esc(localDocumentUrl(mtr.view_url))}" target="_blank" rel="noopener noreferrer">View MTR ${esc(mtr.reference)}</a>`:documentUrl(p.mtr_url)?`<a href="${esc(documentUrl(p.mtr_url))}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">View linked MTR</a>`:''}${editable&&d.mtr_documents?.can_upload?button('mtr-panel','Upload MTR for this piece',`data-fbom-piece="${esc(piece.piece_key)}"`,false,disabled):''}</div>${piece.updated_by?`<p class="fbom-note">Last saved by ${esc(piece.updated_by)}${piece.updated_at?' · '+esc(stamp(piece.updated_at)):''}</p>`:''}</section>`;}).join('')}${editable?`${t.configured?'':'<details class="fbom-piece-options"><summary>Save note</summary>'}<div class="fbom-field fbom-reason"><label for="spoolBomReason">${t.configured?'Reason for this update':'Save note'}</label><textarea id="spoolBomReason" maxlength="3000" rows="2">${esc(state.reason)}</textarea></div>${t.configured?'':'</details>'}<div class="fbom-save-actions"><p class="fbom-note">Partial entries can be saved. Every piece needs a heat number and MTR reference before an arrival Pass.</p><button type="submit" id="spoolBomSave" class="primary"${state.stale?' disabled':''}>${state.saving?'Saving…':'Save material details'}</button></div>`:''}</fieldset></form></section>`;
  }
  function formErrorView(){return `<div class="fbom-error" role="alert"><p>${esc(state.formError)}</p>${state.stale?`<p>Your draft is retained. Reloading replaces it with the latest saved values.</p>${button('reload','Reload saved values','',false,busy())}`:''}</div>`;}
  function archivedMaterialsView(entry){
    const key=String(entry.version),detail=state.historyDetail[key],change=arr(detail?.changes).find(row=>row.type==='bom_adopted');
    if(change)return `<details class="fbom-archive" open><summary>Previous material register · ${arr(change.before_materials).length} pieces</summary><p class="fbom-note">Retained from the previous BOM. These entries are historical and do not approve the current material register.</p>${arr(change.before_materials).map(row=>`<section><strong>${esc(pieceName(row))} · ${esc(row.description||'')}</strong><dl>${materialFields.map(([field,label])=>`<div><dt>${esc(label)}</dt><dd>${field==='mtr_url'&&documentUrl(row[field])?`<a href="${esc(documentUrl(row[field]))}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">View recorded MTR link</a>`:esc(row[field]||'Not entered')}</dd></div>`).join('')}</dl></section>`).join('')}</details>`;
    return button('history-detail',state.historyPending===key?'Loading previous register…':'View previous material register',`data-fbom-version="${esc(key)}"`,false,busy()||state.historyPending===key)+(state.historyError&&state.historyPending===null?`<p class="fbom-error" role="alert">${esc(state.historyError)}</p>`:'');
  }
  function historyView(){
    const t=state.data.traceability,a=state.data.arrival,events=arr(t?.history),inspections=arr(a?.history),mtrs=arr(state.data.mtr_documents?.history);
    if(!events.length&&!inspections.length&&!mtrs.length)return '<p class="fbom-note">Saved material changes and inspection decisions will appear in History.</p>';
    return `<details class="fbom-history"${state.historyPending!==null||Object.keys(state.historyDetail).length||state.historyError?' open':''}><summary>History · material records, MTRs and arrival QA/QC</summary>${inspections.length?`<h4>Arrival inspections</h4>${inspections.map(entry=>`<article><strong>${esc(entry.result)} · ${esc(entry.actor)}</strong><p>${esc(stamp(entry.at))} · ${esc(entry.reference||'')}</p><p>${esc(entry.notes||'')}</p><ul>${Object.entries(entry.checks||{}).map(([key,value])=>`<li>${esc(a.checks_catalog.find(check=>check.key===key)?.label||key)}: ${value?'Confirmed':'Not confirmed'}</li>`).join('')}</ul></article>`).join('')}`:''}${events.length?`<h4>Material revisions</h4>${events.map(entry=>`<article><strong>Revision ${esc(entry.version)} · ${esc(entry.actor)}</strong><p>${esc(stamp(entry.at))} · ${esc(entry.reason||'')}</p>${arr(entry.changes).map(change=>{if(change.type==='bom_adopted')return `<p>A new BOM was adopted. ${Number(change.previous_material_count)||0} prior material pieces were retained in this historical register.</p>${archivedMaterialsView(entry)}`;const piece=state.draftRows.find(row=>row.piece_key===change.piece_key);return `<section><strong>${esc(piece?pieceName(piece):change.piece_key||'BOM basis')}</strong><dl>${materialFields.filter(([key])=>(change.before||{})[key]!== (change.after||{})[key]).map(([key,label])=>`<div><dt>${esc(label)}</dt><dd><span>Before: ${esc(change.before?.[key]||'Not entered')}</span><span>Saved: ${esc(change.after?.[key]||'Not entered')}</span></dd></div>`).join('')}</dl></section>`;}).join('')}</article>`).join('')}`:''}${mtrs.length?`<h4>MTR document versions</h4>${mtrs.map(doc=>mtrCard(doc)).join('')}`:''}</details>`;
  }
  async function loadHistory(version){
    const entry=arr(state.data?.traceability?.history).find(row=>String(row.version)===version),expected=state.descriptor?.api_url+'/history/'+version;
    if(busy()||state.historyPending!==null||!entry||entry.detail_url!==expected||!/^\d+$/.test(version))return;
    const sequence=state.sequence;state.historyPending=version;state.historyError='';render();
    try{const detail=await api(expected);if(sequence!==state.sequence||!dialog.open)return;if(String(detail.version)!==version||!Array.isArray(detail.changes))throw Error('The previous material register could not be verified.');state.historyDetail[version]=detail;}
    catch(error){if(sequence===state.sequence)state.historyError=errorText(error);}
    finally{if(sequence===state.sequence){state.historyPending=null;render();}}
  }
  function mtrCard(doc){const view=localDocumentUrl(doc.view_url),download=localDocumentUrl(doc.download_url);return `<article class="fbom-mtr-card"><strong>${esc(doc.reference)}</strong><p>${esc(doc.filename)} · ${Number(doc.page_count)||0} pages${doc.revision?' · Revision '+esc(doc.revision):' · Version '+esc(doc.version)}</p><p class="fbom-note">${esc(doc.uploaded_by||'')} · ${esc(stamp(doc.uploaded_at))}</p><div class="actions">${view?`<a href="${esc(view)}" target="_blank" rel="noopener noreferrer">View MTR</a>`:''}${download?`<a href="${esc(download)}" download>Download MTR</a>`:''}</div></article>`;}
  function mtrDocumentsView(){const m=state.data.mtr_documents;if(!m)return '';return `<section class="fbom-mtr-documents"><div class="fbom-section-heading"><div><h3>MTR documents</h3><p>Files are retained for this unique spool. Enter the matching reference on each material piece.</p></div>${m.can_upload?button('mtr-panel','Upload MTR','',false,busy()):''}</div>${arr(m.current).length?arr(m.current).map(mtrCard).join(''):'<p class="fbom-note">No MTR files uploaded. Material rows can also carry an existing MTR reference and HTTPS document link.</p>'}</section>`;}
  function input(id,label,value,options={}){return `<div class="fbom-field${options.wide?' fbom-wide':''}"><label for="${id}">${esc(label)}</label>${options.textarea?`<textarea id="${id}" maxlength="${options.max||3000}" rows="3"${busy()?' disabled':''}>${esc(value)}</textarea>`:`<input id="${id}" value="${esc(value)}" maxlength="${options.max||300}"${busy()?' disabled':''}>`}</div>`;}
  function inspectionView(){
    const a=state.data.arrival,f=state.inspection,allowed=a.permissions?.can_inspect===true,passBlocked=state.dirty||state.stale||!state.data.bom_available||!state.data.traceability.complete||state.data.source_status.changed;
    return `<section class="fbom-inspection"><h3>Record arrival QA/QC</h3><p>Check the actual spool and its material records. Every decision is retained with your identity and time.</p>${arrivalView()}${state.dirty?'<p class="fbom-warning">Save the edited material details before recording a Pass. A Fail can still be recorded.</p>':''}${state.formError?formErrorView():''}${allowed?`<form id="spoolArrivalForm" novalidate><fieldset${busy()?' disabled':''}><div class="fbom-field"><label for="spoolArrivalResult">Arrival inspection result</label><select id="spoolArrivalResult"><option value="">Choose Pass or Fail</option><option value="Pass"${f.result==='Pass'?' selected':''}${passBlocked?' disabled':''}>Pass</option><option value="Fail"${f.result==='Fail'?' selected':''}>Fail</option></select></div><div class="fbom-arrival-checks">${a.checks_catalog.map(check=>`<label><input type="checkbox" data-fbom-check="${esc(check.key)}"${f.checks[check.key]?' checked':''}><span>${esc(check.label)}</span></label>`).join('')}</div><p class="fbom-note">A Pass requires every check and complete current heat/MTR records. A Fail can identify missing documents or an unacceptable condition.</p>${input('spoolArrivalReference','Inspection / receiving reference',f.reference,{max:300})}${input('spoolArrivalNotes','Inspection findings / failure reason',f.notes,{textarea:true})}<div class="actions"><button type="submit" id="spoolArrivalSave" class="primary">${state.saving?'Saving…':'Record arrival decision'}</button>${button('back','Back to materials','',false,state.saving)}</div></fieldset></form>`:'<p class="fbom-locked">Only QA/QC and administrators can record an arrival inspection.</p>'}</section>`;
  }
  function adoptView(){const s=state.data.source_status;return `<section class="fbom-adopt"><h3>Review replacement BOM</h3><p>Current material basis: <strong>${esc(s.pinned?.filename||'Previous BOM')}</strong></p><p>Replacement: <strong>${esc(s.current?.filename||'New BOM')}</strong>${s.current?.revision?' · Revision '+esc(s.current.revision):''}</p><div class="fbom-warning"><strong>Material entries will start blank for the new BOM.</strong><p>The previous BOM, heat numbers, MTR references and their history are retained. Re-enter and confirm the material details for this spool, then obtain a new arrival Pass.</p>${state.dirty?'<p>Unsaved material edits will also be replaced when you adopt the new BOM.</p>':''}</div>${state.formError?formErrorView():''}${input('spoolBomAdoptReason','Reason for adopting this BOM',state.adoptReason,{textarea:true})}<div class="actions">${button('adopt','Adopt BOM and reset material entries','',true,busy()||!s.can_adopt||state.stale)}${button('back','Back to materials','',false,state.saving)}</div></section>`;}
  function mtrSeries(){const key=state.mtr.reference.trim().toLocaleLowerCase();return arr(state.data.mtr_documents?.current).find(doc=>text(doc.reference).trim().toLocaleLowerCase()===key);}
  function mtrView(){
    const f=state.mtr,series=mtrSeries();
    if(series&&f.automaticReason){f.reason='';f.automaticReason=false;}
    return `<section class="fbom-mtr-upload"><h3>Upload MTR documents</h3><p>PDFs and scanned JPG/PNG pages stay with <strong>${esc(state.data.context.item_id)}</strong>. Add every page in document order.</p>${f.attachPiece?`<p class="fbom-note">This reference will be added to ${esc(pieceName(state.draftRows.find(row=>row.piece_key===f.attachPiece)||{}))}. Save the material details afterwards to record the association.</p>`:''}${state.formError?formErrorView():''}${f.error?`<div class="fbom-error" role="alert"><p>${esc(f.error)}</p>${f.stale?button('mtr-reload','Reload saved MTR versions','',false,busy()):''}</div>`:''}${input('spoolMtrReference','MTR reference',f.reference,{max:300})}<div class="actions"><label class="fbom-file-button">Choose PDF or scans<input id="spoolMtrFiles" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" multiple${busy()?' disabled':''}></label><label class="fbom-file-button">Scan a page<input id="spoolMtrCamera" type="file" accept="image/png,image/jpeg" capture="environment"${busy()?' disabled':''}></label></div>${f.files.length?`<ol class="fbom-files">${f.files.map((file,index)=>`<li><span><strong>${esc(file.name)}</strong><small>${bytes(file.size)}</small></span><div>${button('mtr-up','↑',`data-fbom-index="${index}" aria-label="Move ${esc(file.name)} earlier"`,false,busy()||!index)}${button('mtr-down','↓',`data-fbom-index="${index}" aria-label="Move ${esc(file.name)} later"`,false,busy()||index===f.files.length-1)}${button('mtr-remove','Remove',`data-fbom-index="${index}"`,false,busy())}</div></li>`).join('')}</ol>`:''}${state.working?'<p class="fbom-state" role="status">Checking the MTR pages… You can go Back to keep your selected files.</p>':f.preview?`<p class="fbom-coverage">${f.preview.page_count} pages will be saved in the viewable MTR file.</p>`:''}${series?`<p class="fbom-warning">This reference already has a saved MTR. Saving creates version ${series.version+1}; earlier files stay in History.</p>`:''}${input('spoolMtrRevision','Revision (optional)',f.revision,{max:80})}${input('spoolMtrReason',series?'Reason for this MTR revision':'Save note',f.reason,{max:3000})}<div class="actions">${button('mtr-save',state.saving?'Saving…':'Save MTR','',true,busy()||!f.preview||f.stale)}${f.files.length&&!f.preview?button('mtr-preview','Check selected pages','',false,busy()):''}${button('back','Back to materials','',false,state.saving)}</div></section>`;
  }
  function legacyView(){const d=state.data,c=d.context;return `<div class="fbom-source"><span class="fbom-badge">Approved drawing BOM</span><p>Drawing <strong>${esc(d.drawing_number)}</strong> · Revision <strong>${esc(d.revision)}</strong> · ${esc(d.revision_date||'')}</p><p>${esc(d.source_document)} · Sheet ${esc(d.source_sheet)} of ${esc(d.source_page_count)}</p></div><dl class="fbom-context">${contextField('P.O.',c.purchase_order)}${contextField('Assembly',c.assembly_number)}</dl>${bomTable(d)}<p class="fbom-note">Heat numbers, MTRs and arrival inspections are recorded separately on each individual physical spool.</p>`;}
  function book(){const d=state.data;return d?.source_status?.pinned||d?.source_status?.current||d?.source_workbook||null;}
  function render(){
    const physical=apiPath(state.descriptor?.api_url)?.[1]==='spools';
    node('spoolBomTitle').textContent=physical?'Materials & QA/QC':'Bill of materials';
    node('spoolBomSubtitle').textContent=state.data?(physical?'Physical spool '+state.data.context.item_id+' · '+state.data.spool_number:'Spool '+state.data.spool_number):state.descriptor?.spool_number||'';
    const body=node('spoolBomContent');body.setAttribute('aria-busy',String(busy()));
    if(state.loading&&!state.data)body.innerHTML='<p class="fbom-state" role="status">Loading this spool’s material and inspection records…</p>';
    else if(state.error&&!state.data)body.innerHTML=`<div class="fbom-error" role="alert"><p>${esc(state.error)}</p>${button('reload','Try again')}</div>`;
    else if(state.data){body.innerHTML=`${state.error?`<p class="fbom-error" role="alert">${esc(state.error)}</p>`:''}${state.notice?`<p class="fbom-save-notice" role="status">${esc(state.notice)}</p>`:''}${physical?contextView()+(state.panel==='inspection'?inspectionView():state.panel==='adopt'?adoptView():state.panel==='mtr'?mtrView():arrivalView()+sourceView()+traceabilityView()+mtrDocumentsView()+historyView()):legacyView()}`;}
    else body.innerHTML='';
    const download=node('spoolBomDownload'),b=book();download.disabled=busy()||state.downloading||!localDocumentUrl(b?.download_url);download.textContent=state.downloading?'Downloading…':physical?'Download BOM':'Download approved Excel';
    node('spoolBomDownloadNote').textContent=state.data&&!physical?'The approved workbook includes both spool bills of materials.':'';
    node('spoolBomClose').disabled=state.saving;node('spoolBomDone').disabled=state.saving;if(node('spoolBomBack'))node('spoolBomBack').disabled=state.saving;
    node('spoolBomDone').textContent=physical?'Return to spool':'Return to setup';wire();
  }
  function wire(){
    const form=node('spoolBomTraceForm');if(form)form.onsubmit=event=>{event.preventDefault();return saveTraceability();};
    const arrival=node('spoolArrivalForm');if(arrival)arrival.onsubmit=event=>{event.preventDefault();return saveInspection();};
    const map=[['spoolBomReason',()=>state,'reason'],['spoolBomAdoptReason',()=>state,'adoptReason'],['spoolArrivalReference',()=>state.inspection,'reference'],['spoolArrivalNotes',()=>state.inspection,'notes'],['spoolMtrReference',()=>state.mtr,'reference'],['spoolMtrRevision',()=>state.mtr,'revision'],['spoolMtrReason',()=>state.mtr,'reason']];
    for(const [id,target,key] of map){const input=node(id);if(input)input.oninput=()=>{target()[key]=input.value;if(id==='spoolMtrReason')state.mtr.automaticReason=false;};}
    const reference=node('spoolMtrReference');if(reference)reference.onchange=()=>render();
    const result=node('spoolArrivalResult');if(result)result.onchange=()=>{state.inspection.result=result.value;};
    for(const id of ['spoolMtrFiles','spoolMtrCamera']){const input=node(id);if(input)input.onchange=()=>addMtrFiles([...input.files]);}
  }
  function mutationError(error){state.formError=errorText(error);state.stale=error.status===409||!error.status;if(state.stale)state.formError+=' Reload the saved values before another revision; the request may already have been saved.';}
  async function mutate(path,payload,onSuccess){
    if(busy())return;const sequence=state.sequence;state.saving=true;state.formError='';state.notice='';render();
    try{const data=await api(state.descriptor.api_url+path,{method:path==='/traceability'?'PUT':'POST',body:JSON.stringify(payload)});if(sequence!==state.sequence||!dialog.open)return;if(!valid(data,state.descriptor))throw Error('The saved response did not match this physical spool.');onSuccess(data);document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:data.context.item_id,action:path,data}}));}
    catch(error){if(sequence===state.sequence)mutationError(error);}
    finally{if(sequence===state.sequence){state.saving=false;render();}}
  }
  async function saveTraceability(){
    if(busy()||state.stale||!state.data?.traceability?.editable)return;
    const reason=state.reason.trim();if(reason.length<4){state.formError='Enter a reason for this material revision (at least 4 characters).';render();return;}
    const materials=state.draft.map(row=>({piece_key:row.piece_key,...Object.fromEntries(materialFields.map(([key])=>[key,row[key].trim()]))}));
    for(const row of materials)for(const [key,label,max] of materialFields){if(row[key].length>max){state.formError=label+' must be '+max+' characters or fewer.';render();return;}if(key==='mtr_url'&&row[key]&&!documentUrl(row[key])){state.formError='Use a full HTTPS link for the MTR document, or leave that optional link blank.';render();return;}}
    const version=state.traceVersion;
    return mutate('/traceability',{expected_version:version,expected_bom_sha256:state.traceBasis,reason,materials},data=>{if(data.traceability.version!==version+1)throw Error('The material revision could not be verified.');applyData(data);state.panel='materials';state.notice='Material details saved for '+data.context.item_id+'. Arrival QA/QC remains a separate decision.';});
  }
  async function saveInspection(){
    if(busy()||state.stale||!state.data?.arrival?.permissions?.can_inspect)return;if(bindInspectionContext()){render();return;}const f=state.inspection,a=state.data.arrival;
    if(!['Pass','Fail'].includes(f.result)){state.formError='Choose Pass or Fail for this arrival inspection.';render();return;}
    if(f.reference.trim().length<2){state.formError='Enter the inspection or receiving reference.';render();return;}
    if(f.notes.trim().length<4){state.formError=f.result==='Fail'?'Describe the arrival failure or missing documentation.':'Enter the inspection findings for this arrival Pass.';render();return;}
    if(f.result==='Pass'&&(state.dirty||!a.checks_catalog.every(check=>f.checks[check.key]===true))){state.formError=state.dirty?'Save the material edits before recording a Pass.':'Confirm every arrival check before recording a Pass.';render();return;}
    return mutate('/arrival-inspections',{expected_version:f.expected_version,basis_sha256:f.basis_sha256,result:f.result,reference:f.reference.trim(),notes:f.notes.trim(),checks:{...f.checks}},data=>{applyData(data,true);state.inspection=inspection();state.panel='materials';state.notice='Arrival '+f.result+' recorded for '+data.context.item_id+'.';});
  }
  async function adopt(){
    if(busy()||state.stale||!state.data.source_status.can_adopt)return;
    if(state.adoptReason.trim().length<4){state.formError='Enter a reason for adopting the new BOM.';render();return;}
    return mutate('/adopt-bom',{expected_version:state.data.traceability.version,expected_bom_sha256:state.data.source_status.expected_bom_sha256,reason:state.adoptReason.trim()},data=>{applyData(data);state.panel='materials';state.adoptReason='';state.inspection=inspection();state.notice='New BOM adopted. Enter and confirm the heat numbers and MTR references for this spool, then record a new arrival inspection.';});
  }
  function cancelPreview(){if(state.scanTimer)clearTimeout(state.scanTimer);state.scanTimer=null;state.controller?.abort();state.controller=null;}
  function queueMtrPreview(){if(state.scanTimer)clearTimeout(state.scanTimer);state.scanTimer=setTimeout(()=>{state.scanTimer=null;if(dialog.open&&state.panel==='mtr')previewMtr();},300);}
  function addMtrFiles(files){
    if(busy()||!state.data?.mtr_documents?.can_upload||!files.length)return;const limits=state.data.mtr_documents.limits||{},f=state.mtr,chosen=[...f.files];
    for(const file of files){if(!/\.(pdf|png|jpe?g)$/i.test(file.name)||!file.size){f.error='Choose nonempty PDF, JPG or PNG files.';render();return;}if(limits.max_file_bytes&&file.size>limits.max_file_bytes){f.error=file.name+' exceeds the file size limit.';render();return;}if(!chosen.some(old=>old.name===file.name&&old.size===file.size&&old.lastModified===file.lastModified))chosen.push(file);}
    if((limits.max_files&&chosen.length>limits.max_files)||(limits.max_total_bytes&&chosen.reduce((n,file)=>n+file.size,0)>limits.max_total_bytes)){f.error='Choose fewer or smaller MTR files.';render();return;}
    f.files=chosen;f.preview=null;f.error='';f.stale=false;if(!f.reference.trim())f.reference=files[0].name.replace(/\.[^.]+$/,'').slice(0,300);render();queueMtrPreview();
  }
  function mtrForm(){const form=new FormData();for(const file of state.mtr.files)form.append('files',file,file.name);return form;}
  async function previewMtr(){
    if(busy()||!state.mtr.files.length||!state.data?.mtr_documents?.can_upload)return;
    cancelPreview();const sequence=state.sequence,f=state.mtr;state.working=true;f.error='';f.preview=null;state.controller=new AbortController();render();
    try{const data=await request(state.descriptor.api_url+'/mtr-preview',{method:'POST',body:mtrForm(),signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(!/^[a-f0-9]{64}$/i.test(data.selection_sha256||'')||!Number.isInteger(data.page_count)||data.page_count<1)throw Error('The MTR page preview could not be verified.');f.preview=data;f.stale=false;}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError')f.error=errorText(error);}
    finally{if(sequence===state.sequence){state.working=false;state.controller=null;render();}}
  }
  async function saveMtr(){
    const f=state.mtr;if(busy()||!f.preview||f.stale||!state.data?.mtr_documents?.can_upload)return;
    if(f.reference.trim().length<2||f.reason.trim().length<4){f.error='Enter an MTR reference and a save reason of at least 4 characters.';render();return;}
    const sequence=state.sequence,form=mtrForm(),series=mtrSeries();form.append('reference',f.reference.trim());form.append('expected_version',String(series?.version||0));form.append('expected_sha256',f.preview.selection_sha256);form.append('revision',f.revision.trim());form.append('reason',f.reason.trim());state.saving=true;f.error='';state.notice='';render();
    try{const data=await request(state.descriptor.api_url+'/mtr-documents',{method:'POST',body:form});if(sequence!==state.sequence||!dialog.open)return;if(!valid(data,state.descriptor))throw Error('The saved MTR did not match this spool.');applyData(data,true);if(f.attachPiece){const row=state.draft?.find(row=>row.piece_key===f.attachPiece);if(row){row.mtr_reference=f.reference.trim();state.dirty=true;}}state.panel='materials';state.notice='MTR '+f.reference.trim()+' saved for '+data.context.item_id+'.'+(f.attachPiece?' Save material details to record this piece’s reference.':'');state.mtr=mtrDraft();document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:data.context.item_id,action:'mtr',data}}));}
    catch(error){if(sequence===state.sequence){f.error=errorText(error);f.stale=error.status===409||!error.status;if(f.stale)f.error+=' Reload the saved MTR versions before retrying; the request may already have been saved.';}}
    finally{if(sequence===state.sequence){state.saving=false;render();}}
  }
  async function reloadMtr(){
    if(busy()||!state.descriptor)return;const sequence=state.sequence,f=state.mtr;state.loading=true;f.error='';state.controller=new AbortController();render();
    try{const data=await api(state.descriptor.api_url,{signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(!valid(data,state.descriptor))throw Error('The MTR records did not match this physical spool.');applyData(data,true);f.stale=false;state.notice='Saved MTR versions refreshed. Review the current version before saving the selected pages.';}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError'){f.error=errorText(error);f.stale=true;}}
    finally{if(sequence===state.sequence){state.loading=false;state.controller=null;render();}}
  }
  function invalidate(){state.sequence++;cancelPreview();state.downloadController?.abort();state.downloadController=null;state.loading=false;state.working=false;state.downloading=false;}
  async function load(){
    if(!dialog.open||!state.descriptor||state.saving)return;cancelPreview();const sequence=++state.sequence,d=state.descriptor;state.loading=true;state.error='';state.controller=new AbortController();render();
    try{const data=await api(d.api_url,{signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(!valid(data,d))throw Error('The returned material records do not match this spool. Reopen it and try again.');applyData(data);state.formError='';state.stale=false;if(state.panel==='inspection')bindInspectionContext();}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError')state.error=errorText(error);}
    finally{if(sequence===state.sequence){state.loading=false;state.controller=null;render();}}
  }
  async function open(value,trigger=document.activeElement){
    const d=descriptor(value);if(!me||!d||state.saving||window.FabSpoolDocuments?.canNavigateAway?.()===false)return;
    if(!value.fresh&&state.resume?.badge===me.badge&&state.resume.descriptor.api_url===d.api_url)return restoreNavigation({...state.resume,open:true});
    window.FabSpoolDocuments?.cancelPending?.();invalidate();state.descriptor={...d};state.data=null;state.draft=null;state.draftRows=[];state.traceVersion=0;state.traceBasis='';state.dirty=false;state.reason='';state.panel='materials';state.inspection=inspection();state.adoptReason='';state.mtr=mtrDraft();state.historyDetail={};state.historyPending=null;state.historyError='';state.resume=null;state.trigger=trigger;state.error='';state.formError='';state.notice='';state.stale=false;node('spoolBomDownloadError').textContent='';
    if(!dialog.open)dialog.showModal();node('spoolBomClose').focus();await load();
  }
  function navigationState(){
    if(!me?.badge)return null;if(!dialog.open||!state.descriptor)return state.resume?.badge===me.badge?state.resume:null;
    return {format:1,badge:me.badge,open:true,descriptor:{...state.descriptor},data:clone(state.data),draft:clone(state.draft),draftRows:clone(state.draftRows),traceVersion:state.traceVersion,traceBasis:state.traceBasis,dirty:state.dirty,reason:state.reason,panel:state.panel,inspection:clone(state.inspection),adoptReason:state.adoptReason,mtr:{...state.mtr,files:[...state.mtr.files],preview:clone(state.mtr.preview)},stale:state.stale,formError:state.formError,notice:state.notice,pendingSave:state.saving};
  }
  async function restoreNavigation(snapshot){
    if(!snapshot||snapshot.format!==1||snapshot.badge!==me?.badge||state.saving||!descriptor(snapshot.descriptor))return false;
    if(!snapshot.open){state.resume=snapshot;return true;}
    await open({...snapshot.descriptor,fresh:true});if(!state.data||state.descriptor?.api_url!==snapshot.descriptor.api_url)return false;
    if(!snapshot.data||!snapshot.draft)return true;
    const changed=snapshot.pendingSave||snapshot.traceVersion!==state.data.traceability?.version||snapshot.traceBasis!==state.data.source_status?.expected_bom_sha256;
    if(!changed)state.reason=snapshot.reason;
    if(snapshot.dirty){state.draft=clone(snapshot.draft);state.draftRows=clone(snapshot.draftRows)||[];state.traceVersion=snapshot.traceVersion;state.traceBasis=snapshot.traceBasis;state.dirty=true;state.reason=snapshot.reason;}
    state.panel=snapshot.panel;state.inspection=clone(snapshot.inspection);state.adoptReason=snapshot.adoptReason;state.mtr={...snapshot.mtr,files:[...snapshot.mtr.files],preview:clone(snapshot.mtr.preview)};state.stale=!!snapshot.pendingSave||!!snapshot.dirty&&(snapshot.stale||changed);state.formError=state.stale?'Saved materials or the BOM changed while you were away. Your draft is retained; reload saved values before applying a new revision.':snapshot.formError;state.notice=snapshot.notice||'';state.resume=null;
    if(state.mtr.attachPiece&&!state.draftRows.some(row=>row.piece_key===state.mtr.attachPiece))state.mtr.attachPiece='';
    if(state.panel==='inspection')bindInspectionContext();
    if(snapshot.pendingSave){state.mtr.stale=true;state.mtr.error='A previous save could not be confirmed. Reload the saved MTR versions before saving another file.';}
    render();return true;
  }
  function close(restore=true,preserve=true){
    if(state.saving&&restore)return;const trigger=state.trigger,snapshot=preserve?navigationState():null;invalidate();state.descriptor=null;state.data=null;state.draft=null;state.draftRows=[];state.reason='';state.dirty=false;state.saving=false;state.stale=false;state.formError='';state.notice='';state.error='';state.trigger=null;state.panel='materials';state.mtr=mtrDraft();state.historyDetail={};state.historyPending=null;state.historyError='';state.resume=snapshot?{...snapshot,open:false}:null;
    if(dialog.open)dialog.close();render();if(restore&&trigger?.isConnected)trigger.focus();
  }
  function back(){
    if(!dialog.open)return false;if(state.saving)return true;
    if(state.working||state.scanTimer){invalidate();state.panel='mtr';render();return true;}
    if(state.panel!=='materials'){state.panel='materials';state.formError='';render();return true;}
    close(true,true);return true;
  }
  async function download(){
    const b=book(),url=localDocumentUrl(b?.download_url);if(busy()||state.downloading||!url)return;
    const sequence=state.sequence;state.downloading=true;state.downloadController=new AbortController();node('spoolBomDownloadError').textContent='';render();let objectUrl,anchor;
    try{const response=await fetch(url,{credentials:'same-origin',redirect:'error',signal:state.downloadController.signal});if(!response.ok){const error=Error('The BOM could not be downloaded.');error.status=response.status;throw error;}const type=(response.headers.get('content-type')||'').split(';')[0].trim().toLowerCase();if(!['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','text/csv','application/csv','application/pdf','application/octet-stream'].includes(type))throw Error('The server did not return a downloadable BOM file.');const blob=await response.blob();if(sequence!==state.sequence||!dialog.open)return;if(!blob.size)throw Error('The downloaded BOM was empty.');objectUrl=URL.createObjectURL(blob);anchor=document.createElement('a');anchor.href=objectUrl;anchor.download=text(b.filename||'spool-BOM.xlsx');document.body.appendChild(anchor);anchor.click();node('spoolBomDownloadError').textContent='BOM download started.';}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError')node('spoolBomDownloadError').textContent=errorText(error);}
    finally{anchor?.remove();if(objectUrl)setTimeout(()=>URL.revokeObjectURL(objectUrl),30000);if(sequence===state.sequence){state.downloading=false;state.downloadController=null;render();}}
  }
  dialog.addEventListener('input',event=>{
    const input=event.target.closest?.('[data-fbom-field]');if(!input||busy()||!state.data?.traceability?.editable)return;const row=state.draft?.find(row=>row.piece_key===input.dataset.fbomPiece),field=input.dataset.fbomField;if(row&&materialFields.some(([key])=>key===field)){row[field]=input.value;state.dirty=true;const coverageNode=node('spoolBomCoverage');if(coverageNode)coverageNode.textContent=coverage();}
  });
  dialog.addEventListener('change',event=>{const input=event.target.closest?.('[data-fbom-check]');if(input&&!busy())state.inspection.checks[input.dataset.fbomCheck]=!!input.checked;});
  dialog.addEventListener('click',async event=>{
    const target=event.target.closest?.('[data-fbom-action]');if(!target||target.disabled)return;const action=target.dataset.fbomAction;
    if(action==='back')return back();if(busy())return;
    if(action==='reload')return load();
    if(action==='documents'){const c=state.data.context;close(false,true);return window.FabSpoolDocuments?.open({kind:c.kind==='spool'?'spools':'requirements',id:c.item_id||c.requirement_id,tab:'bom'});}
    if(action==='inspection-panel'){state.panel='inspection';state.formError='';bindInspectionContext();render();dialog.scrollTop=0;return;}
    if(action==='adopt-panel'){state.panel='adopt';state.formError='';render();dialog.scrollTop=0;return;}
    if(action==='adopt')return adopt();
    if(action==='mtr-panel'){const key=target.dataset.fbomPiece||'';state.panel='mtr';state.formError='';if(key){state.mtr.attachPiece=key;state.mtr.reference=state.draft?.find(row=>row.piece_key===key)?.mtr_reference||state.mtr.reference;}render();dialog.scrollTop=0;return;}
    if(action==='mtr-preview')return previewMtr();if(action==='mtr-save')return saveMtr();if(action==='mtr-reload')return reloadMtr();if(action==='history-detail')return loadHistory(target.dataset.fbomVersion);
    const index=Number(target.dataset.fbomIndex),files=state.mtr.files;
    if(['mtr-up','mtr-down','mtr-remove'].includes(action)&&Number.isInteger(index)&&index>=0&&index<files.length){if(action==='mtr-remove')files.splice(index,1);if(action==='mtr-up'&&index>0)[files[index-1],files[index]]=[files[index],files[index-1]];if(action==='mtr-down'&&index<files.length-1)[files[index+1],files[index]]=[files[index],files[index+1]];state.mtr.preview=null;state.mtr.error='';state.mtr.stale=false;render();if(files.length)queueMtrPreview();}
  });
  node('spoolBomClose').onclick=()=>close();node('spoolBomDone').onclick=()=>close();node('spoolBomDownload').onclick=()=>download();if(node('spoolBomBack'))node('spoolBomBack').onclick=()=>back();
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.addEventListener('close',()=>{if(!dialog.open&&state.descriptor)close(false,true);});
  document.addEventListener('click',event=>{const target=event.target.closest?.('[data-spool-bom-url]');if(!target||target.disabled)return;event.preventDefault();open({api_url:target.dataset.spoolBomUrl,spool_number:target.dataset.spoolBomNumber,revision:target.dataset.spoolBomRevision,line_count:Number(target.dataset.spoolBomLines)},target);});
  window.FabSpoolBom={link,spoolLink,open,navigationState,restoreNavigation,back,canNavigateAway:()=>!state.saving,cancelPending:()=>close(false,true)};
})();
