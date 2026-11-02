/* Physical-spool material records, MTR files and mandatory arrival QA/QC. */
(() => {
  'use strict';
  const node=id=>document.getElementById(id),dialog=node('spoolBomDialog'),arr=value=>Array.isArray(value)?value:[],text=value=>String(value??'');
  if(!dialog)return;
  const spoolRecord=value=>({...value?.context,spool_number:value?.spool_number,flow_stage:value?.flow_stage});
  const spoolText=(value,label)=>window.FabFlowStatus?.spoolText(spoolRecord(value),label)||esc(label);
  const materialFields=[['supplier','Supplier',160],['supplier_piece_id','Supplier piece / lot ID',160],['heat_number','Heat number',160],['mtr_reference','MTR reference',300],['mtr_url','MTR document link (optional HTTPS)',2000],['notes','Notes',3000]];
  const natural=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'}),compare=(a,b)=>natural.compare(text(a),text(b));
  const orderedPieces=values=>[...values].sort((a,b)=>compare(a.item,b.item)||(Number(a.line_number)||0)-(Number(b.line_number)||0)||(Number(a.piece_number)||0)-(Number(b.piece_number)||0)||compare(a.piece_key,b.piece_key));
  const freshBulk=()=>({open:false,reference:'',notes:'',signature:'',error:'',stale:false});
  const inspection=()=>({result:'',reference:'',notes:'',checks:{},expected_version:null,basis_sha256:''});
  const mtrDraft=()=>({files:[],reference:'',revision:'',reason:'Initial MTR received for this spool',automaticReason:true,preview:null,error:'',stale:false,attachPiece:''});
  const state={sequence:0,descriptor:null,data:null,draft:null,draftRows:[],traceVersion:0,traceBasis:'',dirty:false,reason:'',panel:'materials',inspection:inspection(),adoptReason:'',mtr:mtrDraft(),historyDetail:{},historyPending:null,historyError:'',qaDrafts:{},qaHistory:{},qaHistoryOpen:{},qaHistoryPending:null,qaHistoryError:{},savingQa:'',bulkQa:freshBulk(),scanTimer:null,resume:null,loading:false,working:false,downloading:false,saving:false,error:'',formError:'',notice:'',stale:false,trigger:null,controller:null,downloadController:null};
  const count=value=>Number.isSafeInteger(value)&&value>=0,idOK=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(value);
  const apiPath=value=>typeof value==='string'?value.match(/^\/api\/spool-boms\/(requirements|spools)\/([A-Za-z0-9_-]{1,80})$/):null;
  const clone=value=>value==null?value:JSON.parse(JSON.stringify(value));
  const busy=()=>state.loading||state.working||state.saving;
  const button=(action,label,extra='',primary=false,disabled=false)=>`<button type="button" data-fbom-action="${action}"${primary?' class="primary"':''}${disabled?' disabled':''} ${extra}>${esc(label)}</button>`;
  const bytes=value=>value>=1048576?(value/1048576).toFixed(1)+' MB':Math.max(1,Math.ceil(value/1024))+' KB';
  const stamp=value=>value?new Date(value).toLocaleString():'';
  const inspectionReferenceLabel=result=>'Inspection reference'+(result==='Fail'?' (required)':' (optional)');
  const inspectionNotesLabel=result=>result==='Fail'?'Failure reason (required)':'Inspection notes (optional)';
  const heatDeferred=()=>state.data?.traceability?.heat_required_for_receiving===false;
  const heatDueLabel=()=>text(state.data?.traceability?.heat_required_at_label||'QA/QC-003 - Inspect Welds');
  const heatPolicyText=()=>heatDeferred()?'Heat numbers are optional through step 14 — Complete Welds. Enter them before step '+(state.data.traceability.heat_required_from_step||15)+' — '+heatDueLabel()+'. MTR references remain required for arrival.':'Heat numbers and MTR references are required for arrival Pass.';
  const heatFieldLabel=()=>heatDeferred()?'Heat number (optional until '+heatDueLabel()+')':'Heat number';
  const inspectionHelp=result=>result==='Fail'?'Enter the inspection report or checklist number and explain the failure. Your name and time are recorded automatically. The inspection reference is separate from the MTR reference.':'You may add an inspection report or checklist number and notes. Your name and time are recorded automatically. '+heatPolicyText();
  const decisionHelp=f=>!f?.editing?'Choose Pass or Fail, then save the decision.':f.result==='Pass'?'Pass is selected. Inspection reference and notes are optional; save to confirm.':f.result==='Fail'?'Fail is selected. Enter the required inspection reference and failure reason, then save.':'Review the evidence and choose Pass or Fail again.';
  function inspectionError(result,reference,notes){
    if(!['Pass','Fail'].includes(result))return 'Choose Pass or Fail for this inspection.';
    if(reference.trim().length>300)return 'Inspection reference must be 300 characters or fewer.';
    if(notes.trim().length>3000)return 'Inspection notes must be 3000 characters or fewer.';
    if(result==='Fail'&&reference.trim().length<2)return 'Enter an inspection reference for this Fail (at least 2 characters).';
    if(result==='Fail'&&notes.trim().length<4)return 'Enter a failure reason for this Fail (at least 4 characters).';
    return '';
  }
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
    try{const parsed=JSON.parse(message),detail=parsed.detail||parsed;message=typeof detail==='string'?detail:[detail.message,...arr(detail.blockers||detail.receiving_blockers),...arr(detail.piece_blockers).map(row=>(row.piece_label||row.piece_key)+': '+arr(row.blockers).join(' '))].filter(Boolean).join('; ')||message;}catch(_){}
    return message;
  }
  async function request(url,options={}){
    const response=await fetch(url,{credentials:'same-origin',redirect:'error',...options});let data;
    try{data=await response.json();}catch(_){const error=Error('The server returned an unreadable response. Reload this spool before retrying.');error.status=response.status;throw error;}
    if(!response.ok){const detail=data.detail,message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map(row=>row.msg||text(row)).join('; '):detail?.message||arr(detail?.blockers||detail?.receiving_blockers).join('; ')||data.message||'This request could not be completed.';const error=Error(message);error.status=response.status;throw error;}
    return data;
  }
  function materialDraft(data){return arr(data.traceability?.materials).map(row=>({piece_key:row.piece_key,...Object.fromEntries(materialFields.map(([key])=>[key,text(row[key])]))}));}
  function initialMaterialValues(data){return !data.traceability?.configured||!arr(data.traceability?.materials).some(row=>materialFields.some(([field])=>text(row[field]).trim()));}
  function applyData(data,keepDraft=false){
    const changed=state.traceVersion!==data.traceability?.version||state.traceBasis!==data.source_status?.expected_bom_sha256,preserveReason=keepDraft&&!changed&&!!state.draft;
    state.data=data;
    if(!keepDraft||!state.draft||!state.dirty){state.draft=materialDraft(data);state.draftRows=clone(arr(data.traceability?.materials));state.traceVersion=data.traceability?.version||0;state.traceBasis=data.source_status?.expected_bom_sha256||'';state.dirty=false;if(!preserveReason)state.reason=initialMaterialValues(data)?'Initial material records for this spool':'';state.stale=false;}
    else if(changed){state.stale=true;state.formError='Saved materials or the BOM changed while your edits were open. Your draft is retained. Reload saved values before applying a new revision.';}
    syncPieceQaDrafts();
    if(state.bulkQa.open&&state.bulkQa.signature&&state.bulkQa.signature!==bulkQaSignature()){state.bulkQa.stale=true;state.bulkQa.error='Material evidence or a QA decision changed. Reload and review the current pieces before PASS ALL. Your findings are retained.';}
  }
  function bindInspectionContext(){
    const f=state.inspection,a=state.data?.arrival;if(!a)return false;
    const changed=f.expected_version!==null&&(f.expected_version!==a.version||f.basis_sha256!==a.basis_sha256);
    if(changed){f.result='';f.checks={};state.formError='The material evidence or arrival decision changed. Review the current records and confirm the inspection checks again. Your written reference and findings are retained.';}
    f.expected_version=a.version;f.basis_sha256=a.basis_sha256;return changed;
  }
  function contextField(label,value,spool){return value?`<div><dt>${esc(label)}</dt><dd>${spool?spoolText(spool,value):esc(value)}</dd></div>`:'';}
  function contextView(){const c=state.data.context;return `<dl class="fbom-context">${contextField('P.O.',c.purchase_order||c.project_id)}${contextField('Assembly',c.assembly_number||c.assembly_id)}${contextField('Spool number',state.data.spool_number,state.data)}${contextField('Physical spool',c.display_code||c.qr_alias||c.item_id,state.data)}${c.display_code&&c.display_code!==c.item_id?contextField('Internal record ID',c.item_id):''}</dl>`;}
  function pieceName(row){return row.piece_label||'Item '+text(row.item)+' · Piece '+text(row.piece_number).padStart(3,'0')+' of '+text(row.pieces_on_line).padStart(3,'0');}
  function physicalName(){const c=state.data?.context||{};return c.display_code||c.qr_alias||c.item_id||'';}
  function sharedMaterialSourceView(s){
    if(!s.uses_shared_structured_bom||!s.current)return '';
    const viewed=s.viewed_bom,view=localDocumentUrl(viewed?.view_url||text(viewed?.download_url).replace('?download=1',''));
    return `<div class="fbom-save-notice"><strong>Material list from spool setup</strong><p>The current item quantities come from <strong>${esc(s.current.filename||'the setup BOM')}</strong>.${viewed?.filename?' <strong>'+esc(viewed.filename)+'</strong> remains available to view.':''}</p>${view?`<a href="${esc(view)}" target="_blank" rel="noopener noreferrer">View attached document</a>`:''}</div>`;
  }
  function sourceView(){
    const d=state.data,s=d.source_status||{},source=s.pinned||s.current,available=d.bom_available!==false,download=localDocumentUrl(source?.download_url||d.source_workbook?.download_url);
    return `<section class="fbom-source-card"><div class="fbom-section-heading"><div><h3>${available?'Bill of material for this spool':'Add this spool’s bill of material'}</h3><p>${available?'Material quantities are for one spool. Heat numbers and MTR records below belong only to this physical spool.':'Upload or create the spool BOM before recording its material rows. Arrival failures and MTR documents can still be recorded.'}</p></div>${button('documents','BOM & drawings','',false,busy())}</div>${source?`<p class="fbom-note">${s.pinned?'Recorded material basis':'Current BOM reference'}: <strong>${esc(source.filename||d.source_document||'BOM')}</strong>${source.revision?' · Revision '+esc(source.revision):''}</p>`:''}${sharedMaterialSourceView(s)}${s.changed?`<div class="fbom-warning"><strong>A different BOM is now available.</strong><p>The saved material entries still belong to the previous BOM. Adopting the new BOM archives those entries and starts blank rows. Re-enter and confirm the MTR references and any heat numbers already available for the new BOM.</p>${s.can_adopt?button('adopt-panel','Review new BOM','',false,busy()):`<p>${esc(s.blocked_reason||'A permitted employee must review the replacement BOM.')}</p>`}</div>`:''}${download?`<div class="actions"><a href="${esc(download)}" download>Download ${s.pinned?'recorded':'current'} BOM</a></div>`:''}${arr(d.lines).length?`<details class="fbom-bom-table"><summary>View material list · ${d.line_count} lines</summary>${bomTable(d)}</details>`:''}</section>`;
  }
  function bomTable(d){return `<div class="fbom-table-wrap" role="region" tabindex="0" aria-label="Bill of material for ${esc(d.spool_number)}"><table><caption>Bill of materials · ${spoolText(d,d.spool_number)}</caption><thead><tr><th>Item</th><th>Qty</th><th>Part / TAS number</th><th>Description</th><th>Length</th><th>Material</th></tr></thead><tbody>${arr(d.lines).map(row=>`<tr><td>${esc(row.item)}</td><td>${esc(row.quantity)}</td><td>${esc(row.part_number||row.tas_ln_number||'')}</td><td>${esc(row.description)}</td><td>${esc(row.length_display||row.length||'—')}</td><td>${esc(row.material||'')}</td></tr>`).join('')}</tbody></table></div>`;}
  function arrivalView(compact=false){
    const a=state.data.arrival;if(!a)return '';
    const labels={pending:'Awaiting QA/QC',passed:'Pass',failed:'Fail',needs_reinspection:'Needs reinspection'},latest=a.latest;
    if(compact)return `<p class="fbom-note">Saved arrival status: <strong>${labels[a.status]}</strong>${latest?' · '+esc(latest.actor)+' · '+esc(stamp(latest.at)):''}</p>`;
    return `<section class="fbom-arrival fbom-arrival-${a.status}"><div class="fbom-section-heading"><div><span class="fbom-eyebrow">Mandatory arrival inspection</span><h3>${labels[a.status]}</h3><p>${a.can_proceed?'Arrival QA/QC is current for this spool’s recorded materials.':'Work is blocked until QA/QC records a current passing arrival inspection.'}</p></div>${state.panel==='inspection'?'':a.permissions?.can_inspect?button('inspection-panel',latest?'Record reinspection':'Record arrival inspection','',true,busy()):'<span class="fbom-role-note">QA/QC or administrator records the decision</span>'}</div>${latest?`<p class="fbom-note">Last decision: <strong>${esc(latest.result)}</strong> · ${esc(latest.actor)} · ${esc(stamp(latest.at))}${latest.reference?' · '+esc(latest.reference):''}</p>`:''}${!a.can_proceed&&arr(a.blockers).length?`<ul class="fbom-blockers">${a.blockers.map(message=>`<li>${esc(typeof message==='string'?message:message.message||message.detail||'Arrival approval is outstanding.')}</li>`).join('')}</ul>`:''}</section>`;
  }
  function traceField(piece,key,label,max){
    const id='fbom-'+piece.piece_key+'-'+key,value=text(piece[key]),common=`id="${esc(id)}" data-fbom-piece="${esc(piece.piece_key)}" data-fbom-field="${key}" maxlength="${max}"`;
    if(key==='heat_number')label=heatFieldLabel();
    if(key==='mtr_reference')label='MTR reference (required for arrival)';
    return `<div class="fbom-field${key==='notes'||key==='mtr_url'?' fbom-wide':''}"><label for="${esc(id)}">${esc(label)}</label>${key==='notes'?`<textarea ${common} rows="2">${esc(value)}</textarea>`:`<input ${common} type="${key==='mtr_url'?'url':'text'}" value="${esc(value)}"${key==='mtr_reference'?' list="fbomMtrReferences"':''} autocomplete="off">`}</div>`;
  }
  function coverage(){const values=state.draft||[],heat=values.filter(p=>p.heat_number.trim()).length,mtr=values.filter(p=>p.mtr_reference.trim()).length;return heat+' of '+values.length+' heat numbers entered · '+mtr+' of '+values.length+' MTR references entered'+(mtr<values.length?' · MTR references are still required for arrival.':heat<values.length?(heatDeferred()?' · Heat numbers are deferred until '+esc(heatDueLabel())+'.':' · Heat numbers are still required for arrival.'):' · Material traceability is complete.');}
  function pieceRecord(key){return arr(state.data?.traceability?.materials).find(row=>row.piece_key===key);}
  function pieceEdited(key){const saved=pieceRecord(key),draft=state.draft?.find(row=>row.piece_key===key);return !!(saved&&draft&&materialFields.some(([field])=>text(draft[field]).trim()!==text(saved[field]).trim()));}
  function newPieceQaDraft(row){const qa=row.qa001;return {expected_version:qa?.version??0,basis_sha256:qa?.basis_sha256||'',result:qa?.status==='passed'?'Pass':qa?.status==='failed'?'Fail':'',reference:'',notes:'',editing:false,stale:false,error:''};}
  function piecePassNeeds(row){
    const values=state.draft?.find(value=>value.piece_key===row.piece_key)||row,result=[];
    if(!heatDeferred()&&!text(values.heat_number).trim())result.push({field:'heat_number',message:'Enter this piece’s heat number.'});
    if(!text(values.mtr_reference).trim())result.push({field:'mtr_reference',message:'Enter this piece’s MTR reference.'});
    if(text(values.mtr_url).trim()&&!documentUrl(values.mtr_url.trim()))result.push({field:'mtr_url',message:'Use a full HTTPS MTR link, or leave it blank.'});
    if(state.data.source_status.changed)result.push({message:'Review and adopt the current BOM before Pass.'});
    if(pieceEdited(row.piece_key)&&!state.data.traceability.editable)result.push({message:'A permitted employee must save these material changes first.'});
    return result;
  }
  function piecePassNeedsView(row,f){return f?.editing&&f.result==='Pass'?`<ul class="fbom-piece-pass-blockers">${piecePassNeeds(row).map(issue=>`<li>${esc(issue.message)}${issue.field?button('qa-focus','Go to field',`data-fbom-piece="${esc(row.piece_key)}" data-fbom-focus="${issue.field}"`):''}</li>`).join('')}</ul>`:'';}
  function focusPieceMaterial(key,field='heat_number'){
    if(state.panel!=='materials'){state.panel='materials';state.formError='';render();}
    const row=pieceRecord(key),input=field==='qa001'?(row?.qa001?.permissions?.can_inspect&&!state.stale&&!state.qaDrafts[key]?.stale?node('fbom-qa-'+key+'-pass'):null):node('fbom-'+key+'-'+field);
    const target=input||node('fbom-qa-help-'+key)||node('fbom-piece-title-'+key);
    target?.closest?.('details')?.setAttribute('open','');if(!input)target?.setAttribute('tabindex','-1');target?.focus();
  }
  function bulkQaSignature(){const d=state.data;return d?.traceability?JSON.stringify({version:d.traceability.version,source:d.source_status.expected_bom_sha256,pieces:arr(d.traceability.materials).map(row=>[row.piece_key,row.qa001?.version,row.qa001?.basis_sha256])}):'';}
  function bulkQaBlockers(){return orderedPieces(arr(state.data?.traceability?.materials)).flatMap(row=>{const hasServerBlockers=Array.isArray(row.qa001?.pass_blockers),reasons=arr(row.qa001?.pass_blockers).slice();if(!hasServerBlockers){if(!row.persisted)reasons.push('Save this physical material record first.');if(!heatDeferred()&&!row.heat_number.trim())reasons.push('Save a heat number.');if(!row.mtr_reference.trim())reasons.push('Save an MTR reference.');if(state.data.source_status.changed)reasons.push('Adopt and review the current BOM.');}if(pieceEdited(row.piece_key))reasons.push('Save this piece’s unsaved material changes first.');if(state.stale||state.qaDrafts[row.piece_key]?.stale)reasons.push('Reload this record’s current evidence.');return reasons.length?[{row,reasons:[...new Set(reasons)]}]:[];});}
  function bulkQaView(){
    const rows=arr(state.data?.traceability?.materials);if(!rows.length)return '';const f=state.bulkQa,allowed=rows.every(row=>row.qa001?.permissions?.can_inspect),blockers=bulkQaBlockers(),pending=rows.filter(row=>!row.qa001?.can_proceed).length;
    return `<section class="fbom-bulk-qa"><div class="fbom-section-heading"><div><h3>QA-001 · All pieces</h3><p>${pending} of ${rows.length} pieces need a current Pass on <strong>${spoolText(state.data,physicalName())}</strong>.</p></div>${button('qa-pass-all','PASS ALL','',true,busy()||!allowed)}</div>${f.open?`<div id="fbomPassAll"><p>Record separate passing decisions for the outstanding pieces of this physical spool. Current Pass decisions stay unchanged; overall arrival approval remains separate.</p>${blockers.length?`<div class="fbom-bulk-blockers"><strong>Complete these material records first:</strong><ul>${blockers.map(({row,reasons})=>`<li><strong>${esc(pieceName(row))}</strong>: ${esc(reasons.join(' '))} ${button('qa-focus','Go to piece',`data-fbom-piece="${esc(row.piece_key)}"`)}</li>`).join('')}</ul></div>`:''}${f.error?`<p class="fbom-error" role="alert">${esc(f.error)}</p>`:''}<p class="fbom-note">${esc(inspectionHelp('Pass'))}</p>${input('fbomPassAllReference','Inspection reference for all pieces (optional)',f.reference)}${input('fbomPassAllNotes','Inspection notes for all pieces (optional)',f.notes,{textarea:true})}<div class="actions">${button('qa-confirm-pass-all','Confirm PASS ALL','',true,busy()||!allowed||!!blockers.length||f.stale||!pending)}${button('qa-cancel-pass-all','Cancel','',false,busy())}${f.stale?button('qa-reload-pass-all','Reload and review current pieces','',false,busy()):''}</div>${!pending?'<p class="fbom-save-notice">Every piece already has a current Pass.</p>':''}</div>`:''}</section>`;
  }
  function syncPieceQaDrafts(){
    for(const [key,f] of Object.entries(state.qaDrafts)){const qa=pieceRecord(key)?.qa001;if(!qa)continue;if(f.expected_version!==qa.version||f.basis_sha256!==qa.basis_sha256){f.expected_version=qa.version;f.basis_sha256=qa.basis_sha256;f.result='';f.stale=false;if(f.editing)f.error='The saved piece or its QA decision changed. Review the current evidence and select Pass or Fail again. Your reference and findings are retained.';}}
  }
  function pieceQaHistoryView(key){
    if(!state.qaHistoryOpen[key])return '';
    const history=state.qaHistory[key];
    return `<div class="fbom-piece-qa-history">${state.qaHistoryPending===key?'<p role="status">Loading QA-001 history…</p>':state.qaHistoryError[key]?`<p class="fbom-error" role="alert">${esc(state.qaHistoryError[key])}</p>`:history?history.length?history.map(entry=>`<article><strong>${esc(entry.result)} · ${esc(entry.actor)}</strong><p>${esc(stamp(entry.at))}${entry.reference?' · '+esc(entry.reference):''}</p>${entry.notes?`<p>${esc(entry.notes)}</p>`:''}</article>`).join(''):'<p>No QA-001 decisions recorded for this piece.</p>':''}</div>`;
  }
  function pieceQaView(piece){
    const row=pieceRecord(piece.piece_key),qa=row?.qa001;
    if(!qa)return '<p class="fbom-note">QA-001 will be available when the individual material record is saved.</p>';
    const key=piece.piece_key,f=state.qaDrafts[key]||(state.qaDrafts[key]=newPieceQaDraft(row)),allowed=qa.permissions?.can_inspect===true,persisted=row.persisted===true,edited=pieceEdited(key),locked=busy()||state.stale||f.stale||!allowed||!persisted;
    const legend='fbom-qa-legend-'+key,status='fbom-qa-status-'+key,labels={pending:'Awaiting QA-001',passed:'Pass',failed:'Fail',needs_reinspection:'Needs reinspection'},latest=qa.latest;
    return `<section class="fbom-piece-qa" data-fbom-qa-card="${esc(key)}"><div class="fbom-piece-qa-heading"><strong id="${esc(status)}" class="fbom-piece-qa-status fbom-piece-qa-${esc(qa.status)}">${labels[qa.status]||'Awaiting QA-001'}</strong>${latest?`<span>Saved by ${esc(latest.actor)} · ${esc(stamp(latest.at))}</span>`:''}</div><fieldset class="fbom-piece-qa-choice"${locked?' disabled':''}><legend id="${esc(legend)}">QA-001</legend><div class="fbom-piece-qa-radios" role="radiogroup" aria-labelledby="${esc(legend)} fbom-piece-title-${esc(key)}" aria-describedby="${esc(status)}">${['Pass','Fail'].map(result=>`<label><input type="radio" id="fbom-qa-${esc(key)}-${result.toLowerCase()}" name="fbom-qa-${esc(key)}" value="${result}" data-fbom-qa-result="${esc(key)}"${f.result===result?' checked':''}><span>${result}</span></label>`).join('')}</div></fieldset><p id="fbom-qa-help-${esc(key)}" class="fbom-note">${!persisted?'Save the material details to create this individual record before QA-001.':!allowed?'QA/QC or an administrator records this decision.':decisionHelp(f)}</p><div data-fbom-pass-needs>${piecePassNeedsView(row,f)}</div>${f.error?`<div class="fbom-error" role="alert"><p>${esc(f.error)}</p>${f.stale?button('qa-reload','Reload this QA record',`data-fbom-piece="${esc(key)}"`,false,busy()):''}</div>`:''}${allowed&&f.editing?`<div class="fbom-piece-qa-form"><p class="fbom-note">${esc(inspectionHelp(f.result))}</p><div class="fbom-field"><label for="fbom-qa-${esc(key)}-reference">${esc(inspectionReferenceLabel(f.result))}</label><input id="fbom-qa-${esc(key)}-reference" data-fbom-qa-field="reference" data-fbom-piece="${esc(key)}" value="${esc(f.reference)}" maxlength="300" autocomplete="off"${f.result==='Fail'?' required':''}${busy()?' disabled':''}></div><div class="fbom-field"><label for="fbom-qa-${esc(key)}-notes">${esc(inspectionNotesLabel(f.result))}</label><textarea id="fbom-qa-${esc(key)}-notes" data-fbom-qa-field="notes" data-fbom-piece="${esc(key)}" maxlength="3000" rows="2"${f.result==='Fail'?' required':''}${busy()?' disabled':''}>${esc(f.notes)}</textarea></div><div class="actions">${button('qa-save',state.savingQa===key?'Saving QA-001…':f.result==='Pass'&&edited?'Save material details & Pass':'Save QA-001',`data-fbom-piece="${esc(key)}"`,true,locked||!f.result)}${button('qa-cancel','Cancel decision',`data-fbom-piece="${esc(key)}"`,false,busy())}</div></div>`:allowed&&latest?button('qa-edit','Record another decision',`data-fbom-piece="${esc(key)}"`,false,locked):''}${latest?`<div class="fbom-piece-qa-last"><span>Last decision: ${esc(latest.result)}${latest.reference?' · '+esc(latest.reference):''}</span>${button('qa-history',state.qaHistoryOpen[key]?'Hide QA-001 history':'View QA-001 history',`data-fbom-piece="${esc(key)}"`,false,busy()||state.qaHistoryPending===key)}</div>`:''}${pieceQaHistoryView(key)}</section>`;
  }
  function updatePieceQaControls(key){
    const row=pieceRecord(key),card=dialog.querySelector?.('[data-fbom-qa-card="'+CSS.escape(key)+'"]');if(!row||!card)return;
    // Update guidance without replacing the material input that currently has focus.
    const choice=card.querySelector('fieldset'),f=state.qaDrafts[key],edited=pieceEdited(key),locked=busy()||state.stale||!!f?.stale||row.qa001?.permissions?.can_inspect!==true||!row.persisted;
    if(f&&!f.editing){f.result=edited?'':row.qa001.status==='passed'?'Pass':row.qa001.status==='failed'?'Fail':'';for(const radio of card.querySelectorAll('[data-fbom-qa-result]'))radio.checked=radio.value===f.result;}
    if(choice)choice.disabled=locked;
    const save=card.querySelector('[data-fbom-action="qa-save"]');if(save){save.disabled=locked||!f?.result;save.textContent=f?.result==='Pass'&&edited?'Save material details & Pass':'Save QA-001';}
    const help=node('fbom-qa-help-'+key);if(help)help.textContent=!row.persisted?'Save the material details to create this individual record before QA-001.':row.qa001?.permissions?.can_inspect!==true?'QA/QC or an administrator records this decision.':decisionHelp(f);
    const needs=card.querySelector('[data-fbom-pass-needs]');if(needs)needs.innerHTML=piecePassNeedsView(row,f);
    const bulk=dialog.querySelector('.fbom-bulk-qa');if(bulk){bulk.outerHTML=bulkQaView();wire();}
  }
  function applySelectedMaterial(data,key){
    const local=clone(state.draft)||[],previous=materialDraft(state.data),reason=state.reason;
    applyData(data);
    for(const draft of local){if(draft.piece_key===key)continue;const before=previous.find(row=>row.piece_key===draft.piece_key),saved=state.draft.find(row=>row.piece_key===draft.piece_key);if(!before||!saved||!materialFields.some(([field])=>text(draft[field]).trim()!==text(before[field]).trim()))continue;if(materialFields.some(([field])=>text(saved[field]).trim()!==text(before[field]).trim())){state.stale=true;state.formError='Another material record changed. Your remaining drafts are retained; reload saved values before saving them.';}Object.assign(saved,draft);}
    state.dirty=state.draft.some(row=>pieceEdited(row.piece_key));if(state.dirty)state.reason=reason;
  }
  async function savePieceQa(key){
    const row=pieceRecord(key),qa=row?.qa001,f=state.qaDrafts[key];if(busy()||state.stale||!f||f.stale||!f.editing||!row.persisted||!qa?.permissions?.can_inspect)return;
    if(f.expected_version!==qa.version||f.basis_sha256!==qa.basis_sha256){syncPieceQaDrafts();render();return;}
    const validation=inspectionError(f.result,f.reference,f.notes);if(validation){f.error=validation;render();return;}
    const edited=pieceEdited(key),needs=f.result==='Pass'?piecePassNeeds(row):[];
    if(needs.length){f.error='Complete this piece’s material evidence before Pass.';render();if(needs[0].field)focusPieceMaterial(key,needs[0].field);return;}
    if(edited&&f.result!=='Pass'){f.error='Save this piece’s material edits before recording a Fail.';render();return;}
    const draft=state.draft.find(value=>value.piece_key===key);
    if(edited)for(const [field,label,max] of materialFields){if(text(draft[field]).trim().length>max){f.error=label+' must be '+max+' characters or fewer.';render();focusPieceMaterial(key,field);return;}}
    const sequence=state.sequence,intent={...f,reference:f.reference.trim(),notes:f.notes.trim()},result=intent.result,traceVersion=state.traceVersion,source=state.traceBasis;let version=intent.expected_version,basis=intent.basis_sha256,materialSaved=false;
    state.saving=true;state.savingQa=key;f.error='';state.notice='';render();
    try{
      if(edited){
        const materials=materialDraft(state.data).map(value=>value.piece_key===key?{piece_key:key,...Object.fromEntries(materialFields.map(([field])=>[field,text(draft[field]).trim()]))}:value);
        const data=await api(state.descriptor.api_url+'/traceability',{method:'PUT',body:JSON.stringify({expected_version:traceVersion,expected_bom_sha256:source,reason:state.reason.trim().length>=4?state.reason.trim():'Material details confirmed for QA-001 Pass',materials,qa001_guard:{piece_key:key,expected_version:version,basis_sha256:basis}})});
        if(sequence!==state.sequence||!dialog.open)return;
        if(!valid(data,state.descriptor)||data.traceability.version!==traceVersion+1)throw Error('The material save could not be verified. Reload this record before another decision.');
        materialSaved=true;applySelectedMaterial(data,key);const saved=pieceRecord(key),current=saved?.qa001;
        if(!saved||!current?.permissions?.can_inspect||data.source_status.changed||(!heatDeferred()&&!saved.heat_number.trim())||!saved.mtr_reference.trim())throw Error('Review the current material evidence before confirming QA-001.');
        version=current.version;basis=current.basis_sha256;Object.assign(f,intent,{expected_version:version,basis_sha256:basis,editing:true,stale:false,error:''});state.qaDrafts[key]=f;
        document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:data.context.item_id,action:'piece-materials',data}}));
      }
      const data=await api(state.descriptor.api_url+'/materials/'+encodeURIComponent(key)+'/qa-001',{method:'POST',body:JSON.stringify({expected_version:version,basis_sha256:basis,result,reference:intent.reference,notes:intent.notes})});
      if(sequence!==state.sequence||!dialog.open)return;if(!valid(data,state.descriptor))throw Error('The saved QA decision did not match this physical spool.');const saved=arr(data.traceability.materials).find(entry=>entry.piece_key===key);if(saved?.qa001?.version!==version+1||saved.qa001.latest?.result!==result)throw Error('The piece QA revision could not be verified.');
      applyData(data,true);state.qaDrafts[key]=newPieceQaDraft(saved);delete state.qaHistory[key];state.qaHistoryOpen[key]=false;state.notice=(materialSaved?'Material details and ':'')+'QA-001 '+result+' saved for '+pieceName(saved)+' on '+physicalName()+'.';document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:data.context.item_id,action:'piece-qa-001',data}}));
    }
    catch(error){if(sequence===state.sequence){f.error=(materialSaved?'Material details saved. QA-001 was not confirmed. ':'')+errorText(error);f.stale=error.status===409||!error.status||error.status>=500;state.qaDrafts[key]=f;if(f.stale)f.error+=' Your decision draft is retained. Reload this QA record before saving another decision.';}}
    finally{if(sequence===state.sequence){state.saving=false;state.savingQa='';render();}}
  }
  async function saveBulkQa(){
    const f=state.bulkQa,rows=arr(state.data?.traceability?.materials);if(busy()||!f.open||f.stale||!rows.length||!rows.every(row=>row.qa001?.permissions?.can_inspect))return;
    if(f.signature!==bulkQaSignature()){f.stale=true;f.error='The evidence or QA decisions changed. Reload and review the current pieces; your written findings are retained.';render();return;}
    if(bulkQaBlockers().length){f.error='Complete and save each listed material record before PASS ALL.';render();return;}
    const validation=inspectionError('Pass',f.reference,f.notes);if(validation){f.error=validation;render();return;}
    const sequence=state.sequence,id=state.data.context.item_id,pieces=rows.map(row=>({piece_key:row.piece_key,expected_version:row.qa001.version,basis_sha256:row.qa001.basis_sha256})),payload={expected_trace_version:state.data.traceability.version,expected_bom_sha256:state.data.source_status.expected_bom_sha256,reference:f.reference.trim(),notes:f.notes.trim(),pieces};
    state.saving=true;f.error='';state.notice='';render();
    try{const data=await api(state.descriptor.api_url+'/materials/qa-001/pass-all',{method:'POST',body:JSON.stringify(payload)});if(sequence!==state.sequence||!dialog.open)return;const result=data.qa001_bulk_result;if(!valid(data,state.descriptor)||result?.spool_id!==id||result.passed_count+result.already_passed_count!==pieces.length||data.traceability.materials.length!==pieces.length||!pieces.every(piece=>data.traceability.materials.some(row=>row.piece_key===piece.piece_key&&row.qa001?.can_proceed)))throw Error('The saved batch decisions could not be verified. Reload this spool before another decision.');applyData(data,true);state.qaDrafts={};state.qaHistory={};state.qaHistoryOpen={};state.bulkQa=freshBulk();state.notice='PASS ALL saved '+result.passed_count+' individual decisions for '+physicalName()+'. '+result.already_passed_count+' existing current Pass decisions retained. Overall arrival QA/QC remains separate.';document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:id,action:'pieces-pass-all',data}}));}
    catch(error){if(sequence===state.sequence){f.error=errorText(error);f.stale=error.status===409||!error.status||error.status>=500;if(f.stale)f.error+=' Your reference and findings are retained. Reload and review the current pieces before trying again.';}}
    finally{if(sequence===state.sequence){state.saving=false;render();}}
  }
  async function reloadBulkQa(){
    if(busy()||!state.descriptor)return;const sequence=state.sequence;state.loading=true;state.controller=new AbortController();render();
    try{const data=await api(state.descriptor.api_url,{signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(!valid(data,state.descriptor))throw Error('The current material records did not match this physical spool.');applyData(data,true);Object.assign(state.bulkQa,{open:true,signature:bulkQaSignature(),stale:false,error:'Current pieces loaded. Review their saved evidence, then confirm PASS ALL. Your reference and findings are retained.'});}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError')state.bulkQa.error=errorText(error);}
    finally{if(sequence===state.sequence){state.loading=false;state.controller=null;render();}}
  }
  async function reloadPieceQa(key){
    if(busy()||!state.descriptor)return;const sequence=state.sequence;state.loading=true;state.controller=new AbortController();render();
    try{const data=await api(state.descriptor.api_url,{signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(!valid(data,state.descriptor))throw Error('The QA records did not match this physical spool.');applyData(data,true);const f=state.qaDrafts[key];if(f){f.result='';f.editing=true;f.stale=false;f.error='The current QA record has been loaded. Review the piece and select Pass or Fail again; your written findings are retained.';}}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError'&&state.qaDrafts[key])state.qaDrafts[key].error=errorText(error);}
    finally{if(sequence===state.sequence){state.loading=false;state.controller=null;render();}}
  }
  async function loadPieceQaHistory(key){
    const row=pieceRecord(key),url=row?.qa001?.history_url;if(busy()||state.qaHistoryPending!==null||!url)return;
    if(state.qaHistoryOpen[key]){state.qaHistoryOpen[key]=false;render();return;}
    const expected=state.descriptor.api_url+'/materials/'+encodeURIComponent(key)+'/qa-001';if(url!==expected)return;
    state.qaHistoryOpen[key]=true;if(state.qaHistory[key]){render();return;}
    const sequence=state.sequence;state.qaHistoryPending=key;state.qaHistoryError[key]='';render();
    try{const data=await api(url);if(sequence!==state.sequence||!dialog.open)return;if(data.spool_id!==state.data.context.item_id||data.piece_key!==key||data.code!=='QA-001'||!Array.isArray(data.history))throw Error('The piece QA history could not be verified.');state.qaHistory[key]=data.history;}
    catch(error){if(sequence===state.sequence)state.qaHistoryError[key]=errorText(error);}
    finally{if(sequence===state.sequence){state.qaHistoryPending=null;render();}}
  }
  function traceabilityView(){
    const d=state.data,t=d.traceability;if(!t)return '';
    const values=state.draft||[],rows=orderedPieces(state.draftRows),editable=t.editable,disabled=busy(),docs=[...arr(d.mtr_documents?.current)].sort((a,b)=>compare(a.reference,b.reference)),initial=initialMaterialValues(d);
    if(!rows.length)return `<section class="fbom-trace"><h3>Heat numbers & MTRs</h3><p class="fbom-note">${d.bom_available?'This BOM does not yet have usable physical material rows.':'Add a structured BOM to create the material rows for this spool.'}</p>${t.locked_reason?`<p class="fbom-locked">${esc(t.locked_reason)}</p>`:''}</section>`;
    return `<section id="spoolBomTraceability" class="fbom-trace"><div class="fbom-trace-head"><div><h3>Heat numbers & MTRs</h3><p>Material records for <strong>${spoolText(state.data,physicalName())}</strong></p></div><span class="fbom-badge">${t.configured?'Saved revision '+t.version:'Not saved yet'}</span></div><p class="fbom-note">Each piece can have its own heat and MTR. Saving these entries does not approve arrival QA/QC.</p><p class="fbom-note fbom-heat-policy">${esc(heatPolicyText())}</p><p id="spoolBomCoverage" class="fbom-coverage">${coverage()}</p>${!editable?`<p class="fbom-locked">${esc(t.locked_reason||'Your role can view these records. A permitted employee can update them.')}</p>`:''}${state.formError?formErrorView():''}${window.FabFlowStatus?.legend()||''}${bulkQaView()}<datalist id="fbomMtrReferences">${docs.map(doc=>`<option value="${esc(doc.reference)}">${esc(doc.filename)}</option>`).join('')}</datalist><form id="spoolBomTraceForm" novalidate><fieldset${disabled?' disabled':''}>${rows.map(piece=>{const p=values.find(row=>row.piece_key===piece.piece_key)||{piece_key:piece.piece_key,...Object.fromEntries(materialFields.map(([key])=>[key,'']))},mtr=docs.find(doc=>doc.reference===p.mtr_reference);return `<section class="fbom-piece" data-fbom-record="${esc(piece.piece_key)}"><h4 id="fbom-piece-title-${esc(piece.piece_key)}">${esc(pieceName(piece))}</h4><p class="fbom-piece-identity">Spool ${spoolText(state.data,physicalName())}</p>${piece.piece_identifier?`<details class="fbom-piece-record-ref"><summary>Individual record reference</summary><code>${esc(piece.piece_identifier)}</code></details>`:''}<p class="fbom-piece-description">${esc(piece.description)}</p><p class="fbom-note">${esc(piece.part_number||piece.tas_ln_number||'Part number not entered')} · ${esc(piece.material||'')}${piece.length_display?' · '+esc(piece.length_display):''}</p>${editable?`<div class="fbom-piece-fields">${materialFields.filter(([key])=>['heat_number','mtr_reference'].includes(key)).map(([key,label,max])=>traceField(p,key,label,max)).join('')}</div><details class="fbom-piece-options"><summary>Supplier, document link and notes</summary><div class="fbom-piece-fields">${materialFields.filter(([key])=>!['heat_number','mtr_reference'].includes(key)).map(([key,label,max])=>traceField(p,key,label,max)).join('')}</div></details>`:`<dl class="fbom-read-fields">${materialFields.map(([key,label])=>`<div><dt>${esc(label)}</dt><dd>${key==='mtr_url'&&documentUrl(p[key])?`<a href="${esc(documentUrl(p[key]))}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Open MTR document</a>`:esc(p[key]||'Not entered')}</dd></div>`).join('')}</dl>`}<div class="actions">${mtr&&localDocumentUrl(mtr.view_url)?`<a href="${esc(localDocumentUrl(mtr.view_url))}" target="_blank" rel="noopener noreferrer">View MTR ${esc(mtr.reference)}</a>`:documentUrl(p.mtr_url)?`<a href="${esc(documentUrl(p.mtr_url))}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">View linked MTR</a>`:''}${editable&&d.mtr_documents?.can_upload?button('mtr-panel','Upload MTR for this piece',`data-fbom-piece="${esc(piece.piece_key)}"`,false,disabled):''}</div>${piece.updated_by?`<p class="fbom-note">Last saved by ${esc(piece.updated_by)}${piece.updated_at?' · '+esc(stamp(piece.updated_at)):''}</p>`:''}${pieceQaView(piece)}</section>`;}).join('')}${editable?`${!initial?'':'<details class="fbom-piece-options"><summary>Save note</summary>'}<div class="fbom-field fbom-reason"><label for="spoolBomReason">${!initial?'Reason for this update':'Save note'}</label><textarea id="spoolBomReason" maxlength="3000" rows="2">${esc(state.reason)}</textarea></div>${!initial?'':'</details>'}<div class="fbom-save-actions"><p class="fbom-note">Partial entries can be saved. Every piece needs its MTR reference and current QA-001 Pass before the spool arrival Pass. ${esc(heatPolicyText())}</p><button type="submit" id="spoolBomSave" class="primary"${state.stale?' disabled':''}>${state.saving?'Saving…':'Save material details'}</button></div>`:''}</fieldset></form></section>`;
  }
  function formErrorView(){return `<div class="fbom-error" role="alert"><p>${esc(state.formError)}</p>${state.stale?`<p>Your draft is retained. Reloading replaces it with the latest saved values.</p>${button('reload','Reload saved values','',false,busy())}`:''}</div>`;}
  function archivedMaterialsView(entry){
    const key=String(entry.version),detail=state.historyDetail[key],change=arr(detail?.changes).find(row=>row.type==='bom_adopted');
    if(change)return `<details class="fbom-archive" open><summary>Previous material register · ${arr(change.before_materials).length} pieces</summary><p class="fbom-note">Retained from the previous BOM. These entries are historical and do not approve the current material register.</p>${arr(change.before_materials).map(row=>`<section><strong>${esc(pieceName(row))} · ${esc(row.description||'')}</strong><dl>${materialFields.map(([field,label])=>`<div><dt>${esc(label)}</dt><dd>${field==='mtr_url'&&documentUrl(row[field])?`<a href="${esc(documentUrl(row[field]))}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">View recorded MTR link</a>`:esc(row[field]||'Not entered')}</dd></div>`).join('')}</dl></section>`).join('')}</details>`;
    return button('history-detail',state.historyPending===key?'Loading previous register…':'View previous material register',`data-fbom-version="${esc(key)}"`,false,busy()||state.historyPending===key)+(state.historyError&&state.historyPending===null?`<p class="fbom-error" role="alert">${esc(state.historyError)}</p>`:'');
  }
  function arrivalHistoryChecks(entry){
    const legacy={identity:'The arriving physical spool and assembly identity match this record',bom:'The delivered materials match the current spool BOM',heat_numbers:'The recorded heat numbers match the material markings',mtrs:'The MTRs have been checked against the materials and heat numbers',condition:'The arriving materials are in acceptable condition'};
    const catalog=Array.isArray(entry.checks_catalog)?entry.checks_catalog:Object.keys(entry.checks||{}).map(key=>({key,label:legacy[key]||key}));
    return catalog.filter(check=>Object.hasOwn(entry.checks||{},check.key)).map(check=>`<li>${esc(check.label)}: ${entry.checks[check.key]?'Confirmed':'Not confirmed'}</li>`).join('')+(arr(entry.deferred_checks).includes('heat_numbers')?'<li>Heat-number verification was deferred until QA/QC-003.</li>':'');
  }
  function historyView(){
    const t=state.data.traceability,a=state.data.arrival,events=arr(t?.history),inspections=arr(a?.history),mtrs=arr(state.data.mtr_documents?.history);
    if(!events.length&&!inspections.length&&!mtrs.length)return '<p class="fbom-note">Saved material changes and inspection decisions will appear in History.</p>';
    return `<details class="fbom-history"${state.historyPending!==null||Object.keys(state.historyDetail).length||state.historyError?' open':''}><summary>History · material records, MTRs and arrival QA/QC</summary>${inspections.length?`<h4>Arrival inspections</h4>${inspections.map(entry=>`<article><strong>${esc(entry.result)} · ${esc(entry.actor)}</strong><p>${esc(stamp(entry.at))}${entry.reference?' · '+esc(entry.reference):''}</p>${entry.notes?`<p>${esc(entry.notes)}</p>`:''}<ul>${arrivalHistoryChecks(entry)}</ul></article>`).join('')}`:''}${events.length?`<h4>Material revisions</h4>${events.map(entry=>`<article><strong>Revision ${esc(entry.version)} · ${esc(entry.actor)}</strong><p>${esc(stamp(entry.at))} · ${esc(entry.reason||'')}</p>${arr(entry.changes).map(change=>{if(change.type==='pieces_initialized')return `<p>${Number(change.piece_count)||0} individual material records created. Heat numbers, MTR references and QA-001 decisions are recorded separately.</p>`;if(change.type==='bom_adopted')return `<p>A new BOM was adopted. ${Number(change.previous_material_count)||0} prior material pieces were retained in this historical register.</p>${archivedMaterialsView(entry)}`;const piece=state.draftRows.find(row=>row.piece_key===change.piece_key);return `<section><strong>${esc(piece?pieceName(piece):change.piece_key||'BOM basis')}</strong><dl>${materialFields.filter(([key])=>(change.before||{})[key]!== (change.after||{})[key]).map(([key,label])=>`<div><dt>${esc(label)}</dt><dd><span>Before: ${esc(change.before?.[key]||'Not entered')}</span><span>Saved: ${esc(change.after?.[key]||'Not entered')}</span></dd></div>`).join('')}</dl></section>`;}).join('')}</article>`).join('')}`:''}${mtrs.length?`<h4>MTR document versions</h4>${mtrs.map(doc=>mtrCard(doc)).join('')}`:''}</details>`;
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
  function input(id,label,value,options={}){return `<div class="fbom-field${options.wide?' fbom-wide':''}"><label for="${id}">${esc(label)}</label>${options.textarea?`<textarea id="${id}" maxlength="${options.max||3000}" rows="3"${options.required?' required':''}${busy()?' disabled':''}>${esc(value)}</textarea>`:`<input id="${id}" value="${esc(value)}" maxlength="${options.max||300}"${options.required?' required':''}${busy()?' disabled':''}>`}</div>`;}
  function arrivalPassBlockers(){
    const d=state.data,t=d.traceability,s=d.source_status,rows=arr(t.materials),hasServerBlockers=Array.isArray(d.arrival.pass_blockers),blockers=hasServerBlockers?d.arrival.pass_blockers.slice():[];
    // Previous arrival results are not prerequisites for recording a new decision.
    if(!hasServerBlockers){
      if(!d.bom_available)blockers.push('Add a structured BOM for this physical spool.');
      if(s.changed)blockers.push('Review and adopt the current BOM for this spool.');
      if(s.blocked_reason)blockers.push(s.blocked_reason);
      if(!t.configured||rows.some(row=>row.persisted===false))blockers.push('Save the material register for this individual spool.');
      if(!rows.length)blockers.push('A physical material-piece register is required for arrival approval.');
      else{
        if(rows.some(row=>(!heatDeferred()&&!row.heat_number.trim())||!row.mtr_reference.trim()))blockers.push(heatDeferred()?'Save an MTR reference for every material piece.':'Save a heat number and MTR reference for every material piece.');
        else if(heatDeferred()?t.receiving_complete!==true:!t.complete)blockers.push('Complete and save the current material register.');
        if(rows.some(row=>row.qa001?.can_proceed!==true))blockers.push('Record a current QA-001 Pass for every material piece.');
      }
    }
    if(state.dirty)blockers.push('Save your edited material details before recording an arrival Pass.');
    if(state.stale)blockers.push('Reload the saved evidence and review the inspection again.');
    return [...new Set(blockers.filter(message=>typeof message==='string'&&message.trim()))];
  }
  function arrivalPassReadinessView(blockers){
    if(!blockers.length)return '<p id="spoolArrivalPassHelp" class="fbom-note">The material prerequisites are complete for arrival. Confirm every displayed arrival check and save to record your decision.</p>';
    const d=state.data,t=d.traceability,s=d.source_status,pieces=orderedPieces(arr(t.materials)).map(row=>{
      const needs=[],key=row.piece_key,extra=`data-fbom-piece="${esc(key)}"`;
      if(!heatDeferred()&&!row.heat_number.trim())needs.push(button('qa-focus','Enter or review heat number',extra+' data-fbom-focus="heat_number"',false,busy()));
      if(!row.mtr_reference.trim())needs.push(button('qa-focus','Enter or review MTR reference',extra+' data-fbom-focus="mtr_reference"',false,busy()));
      if(pieceEdited(key)){const draft=state.draft.find(value=>value.piece_key===key),field=materialFields.find(([name])=>text(draft[name]).trim()!==text(row[name]).trim())?.[0]||'heat_number';needs.push(button('qa-focus','Review unsaved changes',extra+` data-fbom-focus="${field}"`,false,busy()));}
      if(row.qa001?.can_proceed!==true)needs.push(button('qa-focus','Review QA-001',extra+' data-fbom-focus="qa001"',false,busy()));
      return needs.length?`<li><strong>${esc(pieceName(row))}</strong><div class="actions">${needs.join('')}</div></li>`:'';
    }).filter(Boolean);
    const messages=blockers.map(message=>message.startsWith('Heat number and MTR reference are required for every material piece:')?'Save a heat number and MTR reference for the material pieces below.':message.startsWith('An MTR reference is required for every material piece:')?'Save an MTR reference for the material pieces below.':message.startsWith('A current QA-001 Pass is required for every physical material piece:')?'Record a current QA-001 Pass for the material pieces below.':message);
    return `<div id="spoolArrivalPassHelp" class="fbom-warning" tabindex="-1"><strong>${state.inspection.result==='Pass'?'Pass selected. Complete these items before saving:':'Before saving an arrival Pass:'}</strong><ul class="fbom-blockers">${messages.map(message=>`<li>${esc(message)}</li>`).join('')}</ul>${pieces.length?`<details${pieces.length<=3?' open':''}><summary>Material pieces to review · ${pieces.length}</summary><ul class="fbom-blockers">${pieces.join('')}</ul></details>`:''}<div class="actions">${!d.bom_available||s.changed||s.blocked_reason?button('arrival-materials','Review BOM','data-fbom-focus="source"',false,busy()):''}${state.dirty||!t.configured||arr(t.materials).some(row=>row.persisted===false)?button('arrival-materials','Review and save material details','data-fbom-focus="save"',false,busy()):''}${state.stale?button('reload','Reload saved values','',false,busy()):''}</div><p>Choosing Pass does not save an inspection. Your reference, notes and checked items stay here while you complete the missing details. Changed saved evidence must be reviewed again.</p></div>`;
  }
  function inspectionView(){
    const a=state.data.arrival,f=state.inspection,allowed=a.permissions?.can_inspect===true;
    return `<section class="fbom-inspection"><h3>Record arrival QA/QC</h3><p>Check the actual spool and its material records. Every saved decision is retained with your identity and time.</p>${arrivalView(true)}${state.formError?formErrorView():''}${allowed?`<form id="spoolArrivalForm" novalidate><fieldset${busy()?' disabled':''}><div class="fbom-field"><label for="spoolArrivalResult">Arrival inspection result</label><select id="spoolArrivalResult" aria-describedby="spoolArrivalPassHelp"><option value="">Choose Pass or Fail</option><option value="Pass"${f.result==='Pass'?' selected':''}>Pass</option><option value="Fail"${f.result==='Fail'?' selected':''}>Fail</option></select></div>${arrivalPassReadinessView(arrivalPassBlockers())}${heatDeferred()&&!a.checks_catalog.some(check=>check.key==='heat_numbers')?'<p class="fbom-note fbom-heat-deferred">Heat-number verification is deferred until '+esc(heatDueLabel())+'. No heat verification is recorded by this arrival decision.</p>':''}<div class="fbom-arrival-checks">${a.checks_catalog.map(check=>`<label><input type="checkbox" data-fbom-check="${esc(check.key)}"${f.checks[check.key]?' checked':''}><span>${esc(check.label)}</span></label>`).join('')}</div><p class="fbom-note">A Pass requires every displayed check, current MTR records and a current QA-001 Pass for every material piece. A Fail can identify missing documents or an unacceptable condition.</p><p class="fbom-note">${esc(inspectionHelp(f.result))}</p>${input('spoolArrivalReference',inspectionReferenceLabel(f.result),f.reference,{max:300,required:f.result==='Fail'})}${input('spoolArrivalNotes',inspectionNotesLabel(f.result),f.notes,{textarea:true,required:f.result==='Fail'})}<div class="actions"><button type="submit" id="spoolArrivalSave" class="primary">${state.saving?'Saving…':'Record arrival decision'}</button>${button('back','Back to materials','',false,state.saving)}</div></fieldset></form>`:'<p class="fbom-locked">Only QA/QC and administrators can record an arrival inspection.</p>'}</section>`;
  }
  function adoptView(){const s=state.data.source_status;return `<section class="fbom-adopt"><h3>Review replacement BOM</h3><p>Current material basis: <strong>${esc(s.pinned?.filename||'Previous BOM')}</strong></p><p>Replacement: <strong>${esc(s.current?.filename||'New BOM')}</strong>${s.current?.revision?' · Revision '+esc(s.current.revision):''}</p><div class="fbom-warning"><strong>Material entries will start blank for the new BOM.</strong><p>The previous BOM, heat numbers, MTR references and their history are retained. Re-enter and confirm the material details for this spool, then obtain a new arrival Pass. ${esc(heatPolicyText())}</p>${state.dirty?'<p>Unsaved material edits will also be replaced when you adopt the new BOM.</p>':''}</div>${state.formError?formErrorView():''}${input('spoolBomAdoptReason','Reason for adopting this BOM',state.adoptReason,{textarea:true})}<div class="actions">${button('adopt','Adopt BOM and reset material entries','',true,busy()||!s.can_adopt||state.stale)}${button('back','Back to materials','',false,state.saving)}</div></section>`;}
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
    node('spoolBomSubtitle').textContent=state.data?(physical?'Physical spool '+physicalName()+' · '+state.data.spool_number:'Spool '+state.data.spool_number):state.descriptor?.spool_number||'';
    window.FabFlowStatus?.decorateSpool(node('spoolBomSubtitle'),spoolRecord(state.data),node('spoolBomSubtitle').textContent);
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
    const map=[['spoolBomReason',()=>state,'reason'],['fbomPassAllReference',()=>state.bulkQa,'reference'],['fbomPassAllNotes',()=>state.bulkQa,'notes'],['spoolBomAdoptReason',()=>state,'adoptReason'],['spoolArrivalReference',()=>state.inspection,'reference'],['spoolArrivalNotes',()=>state.inspection,'notes'],['spoolMtrReference',()=>state.mtr,'reference'],['spoolMtrRevision',()=>state.mtr,'revision'],['spoolMtrReason',()=>state.mtr,'reason']];
    for(const [id,target,key] of map){const input=node(id);if(input)input.oninput=()=>{target()[key]=input.value;if(id==='spoolMtrReason')state.mtr.automaticReason=false;};}
    const reference=node('spoolMtrReference');if(reference)reference.onchange=()=>render();
    const result=node('spoolArrivalResult');if(result)result.onchange=()=>{state.inspection.result=result.value;state.formError='';render();node('spoolArrivalResult')?.focus({preventScroll:true});};
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
    if(busy()||!state.data?.arrival?.permissions?.can_inspect)return;
    if(state.stale){state.formError='Reload the saved evidence and review the inspection again before recording a decision.';render();return;}
    if(bindInspectionContext()){render();return;}const f=state.inspection,a=state.data.arrival;
    if(!['Pass','Fail'].includes(f.result)){state.formError='Choose Pass or Fail for this arrival inspection.';render();return;}
    const validation=inspectionError(f.result,f.reference,f.notes);if(validation){state.formError=validation;render();return;}
    if(f.result==='Pass'&&arrivalPassBlockers().length){state.formError='Arrival Pass has not been saved. Complete the items listed below the result, then save again. Your inspection entries are retained.';render();node('spoolArrivalPassHelp')?.focus();return;}
    if(f.result==='Pass'&&!a.checks_catalog.every(check=>f.checks[check.key]===true)){state.formError='Confirm every arrival check before recording a Pass.';render();return;}
    return mutate('/arrival-inspections',{expected_version:f.expected_version,basis_sha256:f.basis_sha256,result:f.result,reference:f.reference.trim(),notes:f.notes.trim(),checks:Object.fromEntries(a.checks_catalog.map(check=>[check.key,f.checks[check.key]===true]))},data=>{applyData(data,true);state.inspection=inspection();state.panel='materials';state.notice='Arrival '+f.result+' recorded for '+data.context.item_id+'.';});
  }
  async function adopt(){
    if(busy()||state.stale||!state.data.source_status.can_adopt)return;
    if(state.adoptReason.trim().length<4){state.formError='Enter a reason for adopting the new BOM.';render();return;}
    return mutate('/adopt-bom',{expected_version:state.data.traceability.version,expected_bom_sha256:state.data.source_status.expected_bom_sha256,reason:state.adoptReason.trim()},data=>{applyData(data);state.panel='materials';state.adoptReason='';state.inspection=inspection();state.qaDrafts={};state.qaHistory={};state.qaHistoryOpen={};state.bulkQa=freshBulk();state.notice='New BOM adopted. Enter and confirm the MTR references for this spool, then record a new arrival inspection. '+heatPolicyText();});
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
    window.FabSpoolDocuments?.cancelPending?.();invalidate();state.descriptor={...d};state.data=null;state.draft=null;state.draftRows=[];state.traceVersion=0;state.traceBasis='';state.dirty=false;state.reason='';state.panel='materials';state.inspection=inspection();state.adoptReason='';state.mtr=mtrDraft();state.historyDetail={};state.historyPending=null;state.historyError='';state.qaDrafts={};state.qaHistory={};state.qaHistoryOpen={};state.qaHistoryPending=null;state.qaHistoryError={};state.savingQa='';state.bulkQa=freshBulk();state.resume=null;state.trigger=trigger;state.error='';state.formError='';state.notice='';state.stale=false;node('spoolBomDownloadError').textContent='';
    if(!dialog.open)dialog.showModal();node('spoolBomClose').focus();await load();
  }
  function navigationState(){
    if(!me?.badge)return null;if(!dialog.open||!state.descriptor)return state.resume?.badge===me.badge?state.resume:null;
    return {format:1,badge:me.badge,open:true,descriptor:{...state.descriptor},data:clone(state.data),draft:clone(state.draft),draftRows:clone(state.draftRows),traceVersion:state.traceVersion,traceBasis:state.traceBasis,dirty:state.dirty,reason:state.reason,panel:state.panel,inspection:clone(state.inspection),adoptReason:state.adoptReason,qaDrafts:clone(state.qaDrafts),bulkQa:clone(state.bulkQa),mtr:{...state.mtr,files:[...state.mtr.files],preview:clone(state.mtr.preview)},stale:state.stale,formError:state.formError,notice:state.notice,pendingSave:state.saving};
  }
  async function restoreNavigation(snapshot){
    if(!snapshot||snapshot.format!==1||snapshot.badge!==me?.badge||state.saving||!descriptor(snapshot.descriptor))return false;
    if(!snapshot.open){state.resume=snapshot;return true;}
    await open({...snapshot.descriptor,fresh:true});if(!state.data||state.descriptor?.api_url!==snapshot.descriptor.api_url)return false;
    if(!snapshot.data||!snapshot.draft)return true;
    const changed=snapshot.pendingSave||snapshot.traceVersion!==state.data.traceability?.version||snapshot.traceBasis!==state.data.source_status?.expected_bom_sha256;
    if(!changed)state.reason=snapshot.reason;
    if(snapshot.dirty){state.draft=clone(snapshot.draft);state.draftRows=clone(snapshot.draftRows)||[];state.traceVersion=snapshot.traceVersion;state.traceBasis=snapshot.traceBasis;state.dirty=true;state.reason=snapshot.reason;}
    state.panel=snapshot.panel;state.inspection=clone(snapshot.inspection);state.adoptReason=snapshot.adoptReason;state.mtr={...snapshot.mtr,files:[...snapshot.mtr.files],preview:clone(snapshot.mtr.preview)};state.stale=!!snapshot.pendingSave||!!snapshot.dirty&&(snapshot.stale||changed);state.formError=state.stale?'Saved materials or the BOM changed while you were away. Your draft is retained; reload saved values before applying a new revision.':snapshot.formError;state.notice=snapshot.notice||'';state.resume=null;state.qaDrafts=clone(snapshot.qaDrafts)||{};state.bulkQa=clone(snapshot.bulkQa)||freshBulk();syncPieceQaDrafts();
    if(state.bulkQa.open&&(snapshot.pendingSave||state.bulkQa.signature!==bulkQaSignature())){state.bulkQa.stale=true;state.bulkQa.error='Saved evidence or QA decisions changed while you were away. Reload and review the current pieces; your written findings are retained.';}
    if(state.mtr.attachPiece&&!state.draftRows.some(row=>row.piece_key===state.mtr.attachPiece))state.mtr.attachPiece='';
    if(state.panel==='inspection')bindInspectionContext();
    if(snapshot.pendingSave){for(const f of Object.values(state.qaDrafts)){f.stale=true;f.error='A previous save could not be confirmed. Reload this piece’s QA record before another decision.';}state.mtr.stale=true;state.mtr.error='A previous save could not be confirmed. Reload the saved MTR versions before saving another file.';}
    render();return true;
  }
  function close(restore=true,preserve=true){
    if(state.saving&&restore)return;const trigger=state.trigger,snapshot=preserve?navigationState():null;invalidate();state.descriptor=null;state.data=null;state.draft=null;state.draftRows=[];state.reason='';state.dirty=false;state.saving=false;state.stale=false;state.formError='';state.notice='';state.error='';state.trigger=null;state.panel='materials';state.mtr=mtrDraft();state.historyDetail={};state.historyPending=null;state.historyError='';state.qaDrafts={};state.qaHistory={};state.qaHistoryOpen={};state.qaHistoryPending=null;state.qaHistoryError={};state.savingQa='';state.bulkQa=freshBulk();state.resume=snapshot?{...snapshot,open:false}:null;
    if(dialog.open)dialog.close();render();if(restore&&trigger?.isConnected)trigger.focus();
  }
  function back(){
    if(!dialog.open)return false;if(state.saving)return true;
    if(state.working||state.scanTimer){invalidate();state.panel='mtr';render();return true;}
    if(state.panel!=='materials'){state.panel='materials';state.formError='';render();return true;}
    if(state.bulkQa.open){state.bulkQa.open=false;render();return true;}
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
    const qaInput=event.target.closest?.('[data-fbom-qa-field]');if(qaInput&&!busy()){const f=state.qaDrafts[qaInput.dataset.fbomPiece],field=qaInput.dataset.fbomQaField;if(f&&['reference','notes'].includes(field)){f[field]=qaInput.value;f.editing=true;}return;}
    const input=event.target.closest?.('[data-fbom-field]');if(!input||busy()||!state.data?.traceability?.editable)return;const row=state.draft?.find(row=>row.piece_key===input.dataset.fbomPiece),field=input.dataset.fbomField;if(row&&materialFields.some(([key])=>key===field)){row[field]=input.value;state.dirty=state.draft.some(value=>pieceEdited(value.piece_key));const coverageNode=node('spoolBomCoverage');if(coverageNode)coverageNode.textContent=coverage();updatePieceQaControls(row.piece_key);}
  });
  function selectPieceQa(key,result){const row=pieceRecord(key);if(busy()||state.stale||!row?.qa001?.permissions?.can_inspect||!row.persisted)return;const f=state.qaDrafts[key]||(state.qaDrafts[key]=newPieceQaDraft(row));if(f.stale||!['Pass','Fail'].includes(result))return;f.result=result;f.editing=true;f.error='';render();const missing=result==='Pass'?piecePassNeeds(row).find(issue=>issue.field):null;if(missing)focusPieceMaterial(key,missing.field);else node('fbom-qa-'+key+'-reference')?.focus({preventScroll:true});}
  dialog.addEventListener('change',event=>{const radio=event.target.closest?.('[data-fbom-qa-result]');if(radio)return selectPieceQa(radio.dataset.fbomQaResult,radio.value);const input=event.target.closest?.('[data-fbom-check]');if(input&&!busy())state.inspection.checks[input.dataset.fbomCheck]=!!input.checked;});
  dialog.addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.closest?.('input[data-fbom-qa-field]')){event.preventDefault();savePieceQa(event.target.dataset.fbomPiece);}});
  dialog.addEventListener('click',async event=>{
    const radio=event.target.closest?.('[data-fbom-qa-result]');if(radio&&!radio.disabled){const f=state.qaDrafts[radio.dataset.fbomQaResult];if(f&&!f.editing&&f.result===radio.value)return selectPieceQa(radio.dataset.fbomQaResult,radio.value);}
    const target=event.target.closest?.('[data-fbom-action]');if(!target||target.disabled)return;const action=target.dataset.fbomAction;
    if(action==='back')return back();if(busy())return;
    if(action==='reload')return load();
    if(action==='qa-save')return savePieceQa(target.dataset.fbomPiece);
    if(action==='qa-reload')return reloadPieceQa(target.dataset.fbomPiece);
    if(action==='qa-history')return loadPieceQaHistory(target.dataset.fbomPiece);
    if(action==='qa-focus')return focusPieceMaterial(target.dataset.fbomPiece,target.dataset.fbomFocus||'heat_number');
    if(action==='arrival-materials'){state.panel='materials';state.formError='';render();const saving=target.dataset.fbomFocus==='save',focus=saving?node('spoolBomSave'):dialog.querySelector?.('.fbom-source-card');if(!saving)focus?.setAttribute('tabindex','-1');focus?.focus();if(!focus)dialog.scrollTop=0;return;}
    if(action==='qa-pass-all'){if(!arr(state.data?.traceability?.materials).length||!state.data.traceability.materials.every(row=>row.qa001?.permissions?.can_inspect))return;Object.assign(state.bulkQa,{open:true,signature:bulkQaSignature(),error:'',stale:false});render();node('fbomPassAll')?.scrollIntoView({block:'center'});return;}
    if(action==='qa-confirm-pass-all')return saveBulkQa();
    if(action==='qa-reload-pass-all')return reloadBulkQa();
    if(action==='qa-cancel-pass-all'){state.bulkQa.open=false;render();return;}
    if(action==='qa-edit'||action==='qa-cancel'){const row=pieceRecord(target.dataset.fbomPiece);if(!row?.qa001)return;state.qaDrafts[row.piece_key]=newPieceQaDraft(row);if(action==='qa-edit'){state.qaDrafts[row.piece_key].editing=true;state.qaDrafts[row.piece_key].result='';}render();return;}
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

