/* Individual physical material rows in the active saved BOM document view. */
(() => {
  'use strict';
  const ROOT='/api/spool-documents',arr=v=>Array.isArray(v)?v:[],str=v=>String(v??''),enc=encodeURIComponent;
  const escape=v=>str(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));
  const fields=['supplier','supplier_piece_id','heat_number','mtr_reference','mtr_url','notes'];
  const statuses={pending:'Awaiting QA-001',passed:'Pass',failed:'Fail',needs_reinspection:'Needs reinspection'};
  const natural=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'}),compare=(a,b)=>natural.compare(str(a),str(b));
  const orderedPieces=values=>[...values].sort((a,b)=>compare(a.item,b.item)||(Number(a.line_number)||0)-(Number(b.line_number)||0)||(Number(a.piece_number)||0)-(Number(b.piece_number)||0)||compare(a.piece_key,b.piece_key));
  const freshBulk=()=>({open:false,reference:'',notes:'',signature:'',error:'',stale:false});
  const validId=v=>typeof v==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(v);
  const state={key:'',target:null,doc:null,context:null,host:null,notify:null,reloadDocuments:null,hostBusy:false,sequence:0,controller:null,loading:false,saving:false,wrapper:null,selected:'',drafts:{},history:{},historyOpen:{},historyError:{},historyPending:'',adoptOpen:false,adoptReason:'',adoptError:'',adoptStale:false,error:'',notice:'',needsRefresh:true,restore:null,bulk:freshBulk()};
  const keyFor=(target,doc)=>target.kind+'/'+target.id+'/'+doc.id;
  const busy=()=>state.loading||state.saving||state.hostBusy;
  const record=()=>state.wrapper?.record;
  const match=()=>state.wrapper?.document_id===state.doc?.id&&state.wrapper?.record_matches_document===true&&record()?.context?.item_id===state.selected;
  const physicalName=()=>record()?.context?.display_code||record()?.context?.qr_alias||arr(state.wrapper?.spools).find(row=>row.item_id===state.selected)?.display_code||state.selected;
  const pieceName=row=>row.piece_label||'Item '+str(row.item)+' · Piece '+str(row.piece_number).padStart(3,'0')+' of '+str(row.pieces_on_line).padStart(3,'0');
  const materialValue=row=>Object.fromEntries(fields.map(key=>[key,str(row[key])]));
  const fingerprint=row=>JSON.stringify(materialValue(row));
  const rows=()=>arr(record()?.traceability?.materials);
  const rowFor=key=>rows().find(row=>row.piece_key===key);
  const draftMap=()=>state.drafts[state.selected]||(state.drafts[state.selected]={});
  const date=value=>value?new Date(value).toLocaleString():'';
  const button=(action,label,key='',disabled=false)=>`<button type="button" data-dpqa-action="${action}"${key?` data-dpqa-key="${escape(key)}"`:''}${disabled?' disabled':''}>${escape(label)}</button>`;
  function localMtr(url){return typeof url==='string'&&/^\/api\/spool-boms\/mtr-files\/[A-Za-z0-9_-]+(?:\?download=1)?$/.test(url)?url:'';}
  function externalMtr(url){try{const u=new URL(url);return u.protocol==='https:'&&!u.username&&!u.password?u.href:'';}catch(_){return '';}}
  function errorText(error){
    if(error?.status===401)return 'Your session expired. Sign in again before inspecting this spool.';
    if(error?.status===403)return 'Your account cannot record this action. Your entries are retained.';
    return str(error?.message||'The material record could not be verified. Please reload and try again.');
  }
  async function request(url,options={}){
    const response=await fetch(url,{credentials:'same-origin',redirect:'error',...options});let value;
    try{value=await response.json();}catch(_){throw Object.assign(Error('The server response could not be verified. Reload this record before saving again.'),{status:response.status});}
    if(!response.ok){const detail=value.detail,extra=arr(detail?.blockers||detail?.receiving_blockers),pieces=arr(detail?.piece_blockers).map(row=>str(row.piece_label||row.piece_identifier||row.piece_key)+': '+arr(row.blockers).join(' '));throw Object.assign(Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map(row=>row.msg||str(row)).join('; '):[detail?.message,...extra,...pieces].filter(Boolean).join('; ')||'This request could not be completed.'),{status:response.status});}
    return value;
  }
  function validRecord(data,id){
    const t=data?.traceability;
    return data?.context?.kind==='spool'&&data.context.item_id===id&&t&&Number.isSafeInteger(t.version)&&t.version>=0&&typeof t.editable==='boolean'&&Array.isArray(t.materials)&&t.materials.length<=500&&new Set(t.materials.map(row=>row.piece_key)).size===t.materials.length&&t.materials.every(row=>typeof row.piece_key==='string'&&row.piece_key&&fields.every(key=>typeof row[key]==='string')&&row.qa001?.code==='QA-001'&&Number.isSafeInteger(row.qa001.version)&&Object.hasOwn(statuses,row.qa001.status)&&typeof row.qa001.basis_sha256==='string')&&data.source_status;
  }
  function validWrapper(value,selection){
    const c=value?.context,t=state.target;
    return c?.kind===(t.kind==='spools'?'spool':'requirement')&&(t.kind==='spools'?c.item_id:c.requirement_id)===t.id&&Array.isArray(value.spools)&&value.spools.every(row=>validId(row.item_id)&&typeof row.display_code==='string')&&typeof value.selection_required==='boolean'&&typeof value.record_matches_document==='boolean'&&(!selection||value.selected_spool_id===selection)&&(!value.selected_spool_id||value.spools.some(row=>row.item_id===value.selected_spool_id))&&(!value.record||validRecord(value.record,value.selected_spool_id))&&(t.kind!=='spools'||value.selected_spool_id===t.id);
  }
  function newDraft(row){return {material:materialValue(row),material_base:fingerprint(row),material_dirty:false,material_stale:false,material_reason:'Record heat and MTR for '+pieceName(row),material_error:'',qa:{version:row.qa001.version,basis:row.qa001.basis_sha256,result:row.qa001.status==='passed'?'Pass':row.qa001.status==='failed'?'Fail':'',reference:'',notes:'',editing:false,stale:false,error:''}};}
  function syncDrafts(savedMaterial='',savedQa=''){
    if(!state.selected||!record())return;
    if(state.bulk.open&&state.bulk.signature&&state.bulk.signature!==bulkSignature()){state.bulk.stale=true;state.bulk.error='The material evidence or a QA decision changed. Reload and review the current pieces before PASS ALL. Your reference and findings are retained.';}
    const drafts=draftMap();
    for(const row of rows()){
      let f=drafts[row.piece_key];if(!f){drafts[row.piece_key]=newDraft(row);continue;}
      const current=fingerprint(row);
      if(row.piece_key===savedMaterial){f.material=materialValue(row);f.material_base=current;f.material_dirty=false;f.material_stale=false;f.material_error='';}
      else if(!f.material_dirty){f.material=materialValue(row);f.material_base=current;}
      else if(f.material_base!==current){f.material_stale=true;f.material_error='This piece’s saved material details changed. Your entries are retained. Reload this record before saving.';}
      if(row.piece_key===savedQa){f.qa=newDraft(row).qa;delete state.history[row.piece_key];state.historyOpen[row.piece_key]=false;}
      else if(f.qa.version!==row.qa001.version||f.qa.basis!==row.qa001.basis_sha256){
        const editing=f.qa.editing;Object.assign(f.qa,{version:row.qa001.version,basis:row.qa001.basis_sha256,result:editing?'':row.qa001.status==='passed'?'Pass':row.qa001.status==='failed'?'Fail':'',stale:false});
        if(editing)f.qa.error='This piece’s evidence changed. Review it and choose Pass or Fail again. Your reference and findings are retained.';
      }
    }
  }
  function expandedLines(){
    const lines=arr(state.doc?.bom?.lines),result=[];let total=0;
    const canExpand=lines.every(line=>{const q=Number(line.quantity);total+=q;return Number.isSafeInteger(q)&&q>0&&q<=500&&['ea','each','pc','pcs','piece','pieces','no','nos'].includes(str(line.unit||'EA').trim().toLowerCase());})&&total<=500;
    for(const [index,line] of lines.entries())for(let n=1;n<=(canExpand?Number(line.quantity):1);n++)result.push({...line,source_notes:line.notes,piece_key:'template-'+index+'-'+n,piece_number:n,pieces_on_line:canExpand?Number(line.quantity):1,piece_label:canExpand?'Item '+str(line.item)+' · Piece '+str(n).padStart(3,'0')+' of '+str(line.quantity).padStart(3,'0'):'Item '+str(line.item),quantity:canExpand?1:line.quantity,unbound:true,invalid_quantity:!canExpand});
    return result;
  }
  function editable(row){return match()&&record()?.traceability?.editable===true&&!busy()&&!row.unbound;}
  function qaLocked(row,f){return !match()||busy()||!row.persisted||!row.qa001?.permissions?.can_inspect||f?.material_stale||f?.qa?.stale;}
  function passBlocked(row){return !str(row.heat_number).trim()||!str(row.mtr_reference).trim()||record()?.source_status?.changed;}
  function passNeeds(row,f){
    const values=f?.material||row,result=[];
    if(!str(values.heat_number).trim())result.push({field:'heat_number',message:'Enter this piece’s heat number.'});
    if(!str(values.mtr_reference).trim())result.push({field:'mtr_reference',message:'Enter this piece’s MTR reference.'});
    if(str(values.mtr_url).trim()&&!externalMtr(values.mtr_url.trim()))result.push({field:'mtr_url',message:'Use a full HTTPS MTR link, or leave it blank.'});
    if(record()?.source_status?.changed)result.push({message:'Adopt and review the current BOM before Pass.'});
    if(f?.material_dirty&&record()?.traceability?.editable!==true)result.push({message:'A permitted employee must save these material changes before Pass.'});
    return result;
  }
  function passNeedsView(row,f){return f?.qa.editing&&f.qa.result==='Pass'?`<ul class="dpqa-pass-blockers">${passNeeds(row,f).map(issue=>`<li${issue.field?` data-dpqa-missing="${issue.field}"`:''}>${escape(issue.message)}${issue.field?` <button type="button" data-dpqa-action="focus-material" data-dpqa-key="${escape(row.piece_key)}" data-dpqa-field-name="${issue.field}">Go to field</button>`:''}</li>`).join('')}</ul>`:'';}
  function qaSaveLabel(f){return state.saving?'Saving…':f?.qa.result==='Pass'&&f.material_dirty?'Save heat / MTR & Pass':'Save QA-001';}
  function bulkSignature(){return record()?JSON.stringify({version:record().traceability.version,source:record().source_status.expected_bom_sha256,pieces:rows().map(row=>[row.piece_key,row.qa001.version,row.qa001.basis_sha256])}):'';}
  function bulkBlockers(){
    const drafts=state.selected?draftMap():{};
    return orderedPieces(rows()).flatMap(row=>{const f=drafts[row.piece_key],hasServerBlockers=Array.isArray(row.qa001.pass_blockers),reasons=arr(row.qa001.pass_blockers).slice();
      if(!hasServerBlockers){if(!row.persisted)reasons.push('Save this physical material record first.');if(!row.heat_number.trim())reasons.push('Save a heat number.');if(!row.mtr_reference.trim())reasons.push('Save an MTR reference.');}
      if(f?.material_dirty)reasons.push('Save this piece’s unsaved heat / MTR changes first.');
      if(f?.material_stale||f?.qa.stale)reasons.push('Reload this piece’s current evidence before approval.');
      return reasons.length?[{row,reasons:[...new Set(reasons)]}]:[];});
  }
  function bulkView(){
    if(!state.selected||!match()||!rows().length)return '';
    const bulk=state.bulk,allowed=rows().every(row=>row.qa001.permissions?.can_inspect===true),blockers=bulkBlockers(),pending=rows().filter(row=>!row.qa001.can_proceed).length;
    return `<section class="dpqa-bulk"><div class="dpqa-bulk-heading"><div><h4>QA-001 · All pieces</h4><p>${pending} of ${rows().length} pieces need a current Pass on <strong>${escape(physicalName())}</strong>.</p></div>${button('pass-all','PASS ALL','',busy()||!allowed)}</div>${!allowed?'<p class="dpqa-help">QA/QC or an administrator can approve saved physical material records.</p>':''}${bulk.open?`<div id="dpqaPassAll"><p>This records a separate Pass for every outstanding piece on this physical spool. Existing current Pass decisions stay unchanged. Individual decision drafts are replaced after a successful save; overall arrival approval remains separate.</p>${blockers.length?`<div class="dpqa-bulk-blockers" role="status"><strong>Complete these material records first:</strong><ul>${blockers.map(({row,reasons})=>`<li data-dpqa-blocked-piece="${escape(row.piece_key)}"><strong>${escape(pieceName(row))}</strong>: ${escape(reasons.join(' '))} ${button('focus-row','Go to piece',row.piece_key,busy())}</li>`).join('')}</ul></div>`:''}${bulk.error?`<p class="dpqa-error" role="alert">${escape(bulk.error)}</p>`:''}<label for="dpqaPassAllReference">Inspection reference for all pieces</label><input id="dpqaPassAllReference" value="${escape(bulk.reference)}" maxlength="300"${busy()?' disabled':''}><label for="dpqaPassAllNotes">Findings for all pieces</label><textarea id="dpqaPassAllNotes" rows="2" maxlength="3000"${busy()?' disabled':''}>${escape(bulk.notes)}</textarea><div class="dpqa-qa-actions">${button('confirm-pass-all',state.saving?'Saving all decisions…':'Confirm PASS ALL','',busy()||!allowed||!!blockers.length||bulk.stale||!pending)}${button('cancel-pass-all','Cancel','',busy())}${bulk.stale?button('reload-pass-all','Reload and review current pieces','',busy()):''}</div>${!pending?'<p class="dpqa-notice">Every piece already has a current Pass.</p>':''}</div>`:''}</section>`;
  }
  function input(key,field,label,value,max=160,disabled=false,textarea=false){const id='dpqa-'+key+'-'+field;return `<label for="${escape(id)}">${escape(label)}</label>${textarea?`<textarea id="${escape(id)}" data-dpqa-field="${field}" data-dpqa-key="${escape(key)}" rows="2" maxlength="${max}"${disabled?' disabled':''}>${escape(value)}</textarea>`:`<input id="${escape(id)}" data-dpqa-${['heat_number','mtr_reference','mtr_url'].includes(field)?'material':'field'}="${field}" data-dpqa-key="${escape(key)}" value="${escape(value)}" maxlength="${max}" autocomplete="off"${field==='mtr_reference'?' list="dpqaMtrReferences"':''}${disabled?' disabled':''}>`}`;}
  function materialCell(row,f){
    if(row.unbound)return '<p class="dpqa-help">Select a physical spool to record its heat number and MTR.</p>';
    const disabled=!editable(row)||f.material_stale,doc=arr(record()?.mtr_documents?.current).find(doc=>doc.reference===f.material.mtr_reference),url=localMtr(doc?.view_url)||externalMtr(f.material.mtr_url),canEdit=record()?.traceability?.editable===true;
    return `<div class="dpqa-material">${canEdit?`${input(row.piece_key,'heat_number','Heat number',f.material.heat_number,160,disabled)}${input(row.piece_key,'mtr_reference','MTR reference',f.material.mtr_reference,300,disabled)}<details class="dpqa-material-options"><summary>Document link & save note</summary>${input(row.piece_key,'mtr_url','MTR link (optional HTTPS)',f.material.mtr_url,2000,disabled)}${input(row.piece_key,'material_reason','Save note',f.material_reason,3000,disabled,true)}</details>${button('save-material','Save heat / MTR',row.piece_key,disabled||!f.material_dirty&&row.persisted)}`:`<dl><dt>Heat number</dt><dd>${escape(row.heat_number||'Not entered')}</dd><dt>MTR reference</dt><dd>${escape(row.mtr_reference||'Not entered')}</dd></dl>`}${url?`<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">View MTR</a>`:''}${f.material_error?`<p class="dpqa-error" role="alert">${escape(f.material_error)}</p>`:''}${f.material_stale?button('reload','Reload this record',row.piece_key,busy()):''}<p class="dpqa-help" data-dpqa-material-note>${f.material_dirty?'Unsaved changes for this piece.':'Heat and MTR values belong only to this physical piece.'}</p></div>`;
  }
  function historyView(row){
    const key=row.piece_key;if(!state.historyOpen[key])return '';
    return `<div class="dpqa-history">${state.historyPending===key?'<p role="status">Loading QA history…</p>':state.historyError[key]?`<p class="dpqa-error" role="alert">${escape(state.historyError[key])}</p>`:arr(state.history[key]).map(event=>`<article><strong>${escape(event.result)} · ${escape(event.actor)}</strong><p>${escape(date(event.at))}</p><p>${escape(event.reference)}</p><p>${escape(event.notes)}</p></article>`).join('')||'<p>No decisions recorded.</p>'}</div>`;
  }
  function canAdopt(){return state.wrapper?.source_match?.reason_code==='pinned_revision'&&state.wrapper.document_id===state.doc?.id&&record()?.source_status?.current?.document_id===state.doc.id&&record().source_status.can_adopt===true;}
  function adoptionView(){
    if(!canAdopt())return button('review-basis','Review material basis','',busy());
    if(!state.adoptOpen)return button('adopt-panel','Use this BOM for this spool','',busy());
    return `<section class="dpqa-adoption"><h4>Use this BOM for ${escape(physicalName())}?</h4><p>New individual material records will start with blank heat / MTR entries and pending QA-001 decisions. The previous BOM, material entries and QA history stay retained. Other physical spools keep their own records.</p><label for="dpqaAdoptReason">Reason for using this BOM</label><textarea id="dpqaAdoptReason" rows="2" maxlength="3000"${busy()?' disabled':''}>${escape(state.adoptReason)}</textarea>${state.adoptError?`<p class="dpqa-error" role="alert">${escape(state.adoptError)}</p>`:''}<div class="dpqa-qa-actions">${button('adopt-bom',state.saving?'Saving…':'Adopt BOM and start new material records','',busy()||state.adoptStale)}${button('cancel-adopt','Cancel','',busy())}${state.adoptStale?button('reload','Reload material records','',busy()):''}</div></section>`;
  }
  function qaCell(row,f){
    const q=row.qa001,key=row.piece_key,locked=row.unbound||qaLocked(row,f),status=q?.status||'pending',latest=q?.latest,legend='dpqa-'+key+'-legend';
    const help=row.unbound?(state.selected?'This BOM does not match the physical material record.':'Choose the physical spool above before recording QA-001.'):!q.permissions?.can_inspect?'QA/QC or an administrator records this decision.':!row.persisted?'Save heat / MTR to bind this individual material record.':f.qa.editing?'This choice is not saved yet. Complete the fields below, then save.':'Choose Pass or Fail to enter the inspection reference and findings.';
    return `<div class="dpqa-qa"><fieldset class="dpqa-choice"${locked?' disabled':''}><legend id="${escape(legend)}">QA-001</legend><div class="dpqa-radios" role="radiogroup" aria-labelledby="${escape(legend)} dpqa-name-${escape(key)}">${['Pass','Fail'].map(value=>`<label><input type="radio" name="dpqa-result-${escape(key)}" data-dpqa-result="${escape(key)}" value="${value}"${f?.qa.result===value?' checked':''}><span>${value}</span></label>`).join('')}</div></fieldset><span class="dpqa-status dpqa-status-${status}" data-dpqa-status="${status}">${row.unbound?'Not selected':statuses[status]}</span><p class="dpqa-help" data-dpqa-qa-note>${escape(help)}</p><div data-dpqa-pass-needs>${passNeedsView(row,f)}</div>${latest?`<p class="dpqa-last">${escape(latest.actor)} · ${escape(date(latest.at))}<br>${escape(latest.reference)}</p>`:''}${f?.qa.error?`<p class="dpqa-error" role="alert">${escape(f.qa.error)}</p>`:''}${f?.qa.stale?button('reload','Reload this record',key,busy()):''}${f?.qa.editing&&q.permissions?.can_inspect?`<div class="dpqa-decision">${input(key,'reference','Inspection reference',f.qa.reference,300,busy())}${input(key,'notes','Findings / failure reason',f.qa.notes,3000,busy(),true)}</div>`:''}<div class="dpqa-qa-actions">${button('save-qa',qaSaveLabel(f),key,locked||!f?.qa.editing||!f.qa.result)}${!row.unbound&&latest?button('history',state.historyOpen[key]?'Hide history':'History',key,busy()||!!state.historyPending):''}${!row.unbound&&latest&&q.permissions?.can_inspect&&!f.qa.editing?button('new-decision','Record another decision',key,locked):''}</div>${row.unbound?'':historyView(row)}</div>`;
  }
  function render(){
    const host=state.host;if(!host)return;
    const w=state.wrapper,active=match(),physical=state.target.kind==='spools',displayRows=active?orderedPieces(rows()).map(row=>{const source=arr(state.doc?.bom?.lines)[Number(row.line_number)-1]||{};return {...source,...row,source_notes:source.notes,quantity:1};}):orderedPieces(expandedLines());
    const sourceIssue=w&&!active&&(w.selected_spool_id||w.document_id!==state.doc.id),drafts=state.selected?draftMap():{};
    host.innerHTML=`<section id="documentPieceQa" data-state="${state.loading?'loading':state.error?'error':'ready'}" aria-busy="${busy()}"><div class="dpqa-heading"><div><h4>Individual material pieces</h4><p>${displayRows.length} ${active?'physical pieces':'individual rows'} · Each whole-piece row has quantity 1</p></div>${w?.selected_spool_id?`<div class="dpqa-physical"><span>Physical spool</span><strong id="dpqaPhysicalName">${escape(physicalName())}</strong></div>`:''}</div>${!physical&&arr(w?.spools).length>1?`<div class="dpqa-selection"><label for="dpqaSpoolSelect">Choose the physical spool to inspect</label><select id="dpqaSpoolSelect"${busy()?' disabled':''}><option value="">Select a physical spool</option>${[...w.spools].sort((a,b)=>compare(a.display_code,b.display_code)||compare(a.item_id,b.item_id)).map(row=>`<option value="${escape(row.item_id)}"${state.selected===row.item_id?' selected':''}>${escape(row.display_code)}</option>`).join('')}</select><p>Approvals and heat numbers apply only to the selected copy.</p></div>`:''}${!state.loading&&w&&!w.spools.length?'<p class="dpqa-source-warning">No physical spools have been registered for this BOM yet. Generate the spool records before inspecting individual pieces.</p>':''}${state.loading?'<p class="dpqa-loading" role="status">Loading this spool’s individual material records…</p>':''}${state.error?`<div class="dpqa-error" role="alert"><p>${escape(state.error)}</p>${button('reload','Reload material records','',state.saving)}</div>`:''}${state.notice?`<p class="dpqa-notice" role="status">${escape(state.notice)}</p>`:''}${sourceIssue?`<div class="dpqa-source-warning"><strong>This BOM is not the current physical material basis.</strong><p>${escape(w.document_id!==state.doc.id?'The saved BOM changed. Reload the saved documents before inspecting it.':w.source_match?.reason||'This physical spool uses a different BOM revision. Review that basis before recording QA-001.')}</p>${w.document_id!==state.doc.id?button('reload-documents','Reload saved documents','',busy()):w.source_match?.reason_code==='individual_override'?button('open-physical','View this physical spool’s BOM','',busy()):adoptionView()}</div>`:''}${!state.loading&&!state.selected&&w?.selection_required?'<p class="dpqa-source-warning">Select a physical spool above. A shared BOM has no shared QA approval.</p>':''}${active&&record().source_status?.changed?'<p class="dpqa-source-warning">A new BOM revision needs adoption before a new Pass can be recorded.</p>':''}${bulkView()}<datalist id="dpqaMtrReferences">${[...arr(record()?.mtr_documents?.current)].sort((a,b)=>compare(a.reference,b.reference)).map(doc=>`<option value="${escape(doc.reference)}">${escape(doc.filename)}</option>`).join('')}</datalist><div class="dpqa-table-wrap"><table class="dpqa-table"><caption>Bill of material · Individual pieces${state.selected?' · '+escape(physicalName()):''}</caption><thead><tr><th scope="col">Item / piece</th><th scope="col">Qty</th><th scope="col">Part / TAS number</th><th scope="col">Description & material</th><th scope="col">Heat / MTR</th><th scope="col">QA-001</th></tr></thead><tbody>${displayRows.map(row=>{const f=!row.unbound?drafts[row.piece_key]:null;return `<tr ${row.unbound?'data-dpqa-unbound="true"':`data-dpqa-piece="${escape(row.piece_key)}"`}><td class="dpqa-identity" data-label="Item / piece"><strong class="dpqa-piece-name" id="dpqa-name-${escape(row.piece_key)}">${escape(pieceName(row))}</strong>${!row.unbound&&row.piece_identifier?`<details><summary>Record reference</summary><code>${escape(row.piece_identifier)}</code></details>`:''}</td><td class="dpqa-count" data-label="Qty"><strong class="dpqa-quantity">${escape(row.quantity)}</strong><small>${escape(row.unit||'EA')}</small></td><td class="dpqa-part-number" data-label="Part / TAS number">${escape(row.part_number||row.tas_ln_number||'—')}</td><td class="dpqa-description" data-label="Description & material"><strong>${escape(row.description)}</strong>${[['Material',row.material],['Size',row.size],['Length',row.length_display||row.length],['Notes',row.source_notes],['Drawing page',row.source_page]].filter(([,value])=>value!==undefined&&value!==null&&str(value)!=='').map(([name,value])=>`<p><span>${name}:</span> ${escape(value)}</p>`).join('')}${row.invalid_quantity?'<p class="dpqa-error">Confirm whole-piece quantities and units before material inspection.</p>':''}</td><td class="dpqa-trace" data-label="Heat / MTR">${materialCell(row,f)}</td><td class="dpqa-inspection" data-label="QA-001">${qaCell(row,f)}</td></tr>`;}).join('')}</tbody></table></div>${active&&!displayRows.length?`<p class="dpqa-source-warning">${escape(arr(record().trace_blockers).join(' ')||'This BOM needs valid whole-piece quantities before individual material records can be created.')}</p>`:''}<p class="dpqa-footnote">QA-001 decisions belong to individual pieces. The spool’s arrival QA/QC remains a separate approval.</p></section>`;
    host.onclick=click;host.oninput=inputEvent;host.onchange=change;host.onkeydown=event=>{if(event.key==='Enter'&&event.target.matches('input[data-dpqa-field]')){event.preventDefault();if(event.target.dataset.dpqaField==='reference')saveQa(event.target.dataset.dpqaKey);}};
  }
  async function load(selection=state.selected){
    if(state.saving||!state.target)return;
    state.controller?.abort();const sequence=++state.sequence;state.controller=new AbortController();state.loading=true;state.historyPending='';state.error='';state.needsRefresh=false;render();
    try{const value=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/material-records'+(selection?'?spool_id='+enc(selection):''),{signal:state.controller.signal});if(sequence!==state.sequence)return;if(!validWrapper(value,selection))throw Error('The material records did not match this BOM and physical spool.');state.wrapper=value;state.selected=value.selected_spool_id||'';if(state.adoptStale){state.adoptStale=false;state.adoptError='Current material basis loaded. Review the BOM and this physical spool again before adopting.';}syncDrafts();}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError'){state.wrapper=null;state.error=errorText(error);}}
    finally{if(sequence===state.sequence){state.loading=false;state.controller=null;render();}}
  }
  function updateRecord(data,savedMaterial='',savedQa=''){
    if(!validRecord(data,state.selected))throw Error('The saved material response did not match this physical spool.');
    state.wrapper.record=data;const current=data.source_status.current,source=data.traceability.configured?data.source_status.pinned:current;
    state.wrapper.record_matches_document=state.wrapper.document_id===state.doc.id&&current?.document_id===state.doc.id&&source?.document_id===state.doc.id;
    if(!state.wrapper.record_matches_document)state.wrapper.source_match={reason_code:'pinned_revision',reason:'This physical spool now uses a different material basis. Reload the records before inspecting this BOM.'};
    syncDrafts(savedMaterial,savedQa);
  }
  function saving(value){state.saving=value;state.notify?.();render();}
  async function saveMaterial(key){
    const row=rowFor(key),f=draftMap()[key];if(!row||!f||!editable(row)||f.material_stale||!f.material_dirty&&row.persisted)return;
    if(f.material.mtr_url.trim()&&!externalMtr(f.material.mtr_url.trim())){f.material_error='Enter a full HTTPS MTR link, or leave the link blank.';render();return;}
    if(f.material_reason.trim().length<4){f.material_error='Enter a save note with at least 4 characters.';render();return;}
    if(f.material_base!==fingerprint(row)){f.material_stale=true;f.material_error='The saved piece changed. Reload this record before saving.';render();return;}
    const sequence=state.sequence,version=record().traceability.version,id=state.selected;
    const materials=rows().map(saved=>({piece_key:saved.piece_key,...materialValue(saved),...(saved.piece_key===key?Object.fromEntries(['heat_number','mtr_reference','mtr_url'].map(field=>[field,f.material[field].trim()])):{})}));
    f.material_error='';state.notice='';saving(true);
    try{const data=await request('/api/spool-boms/spools/'+enc(id)+'/traceability',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:version,expected_bom_sha256:record().source_status.expected_bom_sha256,reason:f.material_reason.trim(),materials})});if(sequence!==state.sequence)return;if(data.traceability?.version!==version+1)throw Error('The saved material revision could not be verified.');updateRecord(data,key);state.notice='Heat / MTR saved for '+pieceName(row)+' on '+physicalName()+'.';document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:id,action:'document-piece-material',data}}));}
    catch(error){if(sequence===state.sequence){f.material_error=errorText(error);f.material_stale=error.status===409||!error.status||error.status>=500;if(f.material_stale)f.material_error+=' Your entries are retained; reload this record before retrying.';}}
    finally{if(sequence===state.sequence)saving(false);}
  }
  async function saveQa(key){
    const row=rowFor(key),f=draftMap()[key];if(!row||!f||qaLocked(row,f)||!f.qa.editing)return;
    if(!['Pass','Fail'].includes(f.qa.result)||f.qa.reference.trim().length<2||f.qa.notes.trim().length<4){f.qa.error='Choose Pass or Fail, enter an inspection reference, and describe the findings (at least 4 characters).';render();return;}
    const needs=f.qa.result==='Pass'?passNeeds(row,f):[];
    if(needs.length){f.qa.error=needs.map(issue=>issue.message).join(' ');render();focusMaterial(key,needs[0].field);return;}
    if(f.material_dirty&&f.qa.result!=='Pass'){f.qa.error='Save this piece’s heat / MTR changes first, then record its Fail decision.';render();return;}
    if(f.material_dirty&&(f.material_reason.trim().length<4||f.material_base!==fingerprint(row))){f.qa.error='Review the material save note and reload any changed material evidence before Pass.';render();return;}
    const sequence=state.sequence,id=state.selected,intent={...f.qa},result=f.qa.result;let materialSaved=false,materialAttempted=false;f.qa.error='';state.notice='';saving(true);
    try{
      if(f.material_dirty){
        materialAttempted=true;const traceVersion=record().traceability.version,materials=rows().map(saved=>({piece_key:saved.piece_key,...materialValue(saved),...(saved.piece_key===key?Object.fromEntries(['heat_number','mtr_reference','mtr_url'].map(field=>[field,f.material[field].trim()])):{})}));
        const material=await request('/api/spool-boms/spools/'+enc(id)+'/traceability',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:traceVersion,expected_bom_sha256:record().source_status.expected_bom_sha256,reason:f.material_reason.trim(),materials,qa001_guard:{piece_key:key,expected_version:intent.version,basis_sha256:intent.basis}})});
        if(sequence!==state.sequence)return;if(material.traceability?.version!==traceVersion+1)throw Error('The saved material revision could not be verified.');updateRecord(material,key);materialSaved=true;
        const current=rowFor(key);if(!match()||!current?.qa001.permissions?.can_inspect||passBlocked(current))throw Error('The current material evidence needs review before QA-001 Pass.');
        Object.assign(f.qa,{...intent,version:current.qa001.version,basis:current.qa001.basis_sha256,error:'',stale:false});
        document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:id,action:'document-piece-material',data:material}}));
      }
      const version=f.qa.version,data=await request('/api/spool-boms/spools/'+enc(id)+'/materials/'+enc(key)+'/qa-001',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:version,basis_sha256:f.qa.basis,result,reference:intent.reference.trim(),notes:intent.notes.trim()})});if(sequence!==state.sequence)return;const saved=arr(data.traceability?.materials).find(row=>row.piece_key===key);if(saved?.qa001?.version!==version+1||saved.qa001.latest?.result!==result)throw Error('The QA-001 decision could not be verified.');updateRecord(data,'',key);state.notice=(materialSaved?'Heat / MTR and ':'')+'QA-001 '+result+' saved for '+pieceName(row)+' on '+physicalName()+'.';document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:id,action:'document-piece-qa-001',data}}));
    }
    catch(error){if(sequence===state.sequence){f.qa.error=(materialSaved?'Heat / MTR saved. QA-001 was not confirmed. ':'')+errorText(error);f.qa.stale=error.status===409||!error.status||error.status>=500;if(f.qa.stale){f.qa.error+=' Your findings are retained; reload this record and review it again.';if(materialAttempted&&!materialSaved)f.material_stale=true;}}}
    finally{if(sequence===state.sequence)saving(false);}
  }
  async function passAll(){
    const bulk=state.bulk;if(busy()||!bulk.open||bulk.stale||!match()||!rows().length||!rows().every(row=>row.qa001.permissions?.can_inspect))return;
    if(bulk.signature!==bulkSignature()){bulk.stale=true;bulk.error='The material records changed. Reload and review all current pieces before PASS ALL.';render();return;}
    if(bulkBlockers().length){bulk.error='Save the listed material records before PASS ALL.';render();return;}
    if(bulk.reference.trim().length<2||bulk.notes.trim().length<4){bulk.error='Enter one inspection reference and findings covering every piece (at least 4 characters).';render();return;}
    const sequence=state.sequence,id=state.selected,pieces=rows().map(row=>({piece_key:row.piece_key,expected_version:row.qa001.version,basis_sha256:row.qa001.basis_sha256}));
    const payload={expected_trace_version:record().traceability.version,expected_bom_sha256:record().source_status.expected_bom_sha256,reference:bulk.reference.trim(),notes:bulk.notes.trim(),pieces};bulk.error='';state.notice='';saving(true);
    try{const data=await request('/api/spool-boms/spools/'+enc(id)+'/materials/qa-001/pass-all',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(sequence!==state.sequence)return;const result=data.qa001_bulk_result;if(!validRecord(data,id)||result?.spool_id!==id||result.passed_count+result.already_passed_count!==pieces.length||data.traceability.materials.length!==pieces.length||!data.traceability.materials.every(row=>pieces.some(piece=>piece.piece_key===row.piece_key)&&row.qa001.can_proceed))throw Error('The PASS ALL result could not be verified. Reload all pieces before another approval.');bulk.open=false;updateRecord(data);for(const row of rows())draftMap()[row.piece_key].qa=newDraft(row).qa;state.history={};state.historyOpen={};state.notice='PASS ALL saved '+result.passed_count+' individual decisions for '+physicalName()+'. '+result.already_passed_count+' existing current Pass decisions retained. Overall arrival QA/QC remains separate.';document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:id,action:'document-pieces-pass-all',data}}));}
    catch(error){if(sequence===state.sequence){bulk.error=errorText(error);bulk.stale=error.status===409||!error.status||error.status>=500;if(bulk.stale)bulk.error+=' Your reference and findings are retained. Reload and review the current pieces; no successful approval has been confirmed here.';}}
    finally{if(sequence===state.sequence)saving(false);}
  }
  async function reloadBulk(){if(busy())return;await load(state.selected);if(record()&&match()){state.bulk.signature=bulkSignature();state.bulk.stale=false;state.bulk.error='Current pieces loaded. Review their evidence and confirm PASS ALL again.';render();}}
  function focusMaterial(key,field='heat_number'){const row=state.host?.querySelector(`[data-dpqa-piece="${key}"]`),input=row?.querySelector(`[data-dpqa-material="${field}"]`);if(input){input.closest('details')?.setAttribute('open','');input.focus();}else row?.scrollIntoView({block:'center'});}
  async function adoptBom(){
    if(busy()||!state.adoptOpen||state.adoptStale||!canAdopt())return;
    const reason=state.adoptReason.trim();if(reason.length<4){state.adoptError='Enter a reason for adopting this BOM (at least 4 characters).';render();return;}
    const sequence=state.sequence,id=state.selected,version=record().traceability.version,sourceHash=record().source_status.expected_bom_sha256;state.adoptError='';state.notice='';saving(true);
    try{const data=await request('/api/spool-boms/spools/'+enc(id)+'/adopt-bom',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:version,expected_bom_sha256:sourceHash,reason})});if(sequence!==state.sequence)return;if(!validRecord(data,id)||data.traceability.version!==version+1||data.source_status.current?.document_id!==state.doc.id||data.source_status.pinned?.document_id!==state.doc.id)throw Error('The adopted BOM could not be verified for this physical spool.');state.drafts[id]={};state.bulk=freshBulk();state.history={};state.historyOpen={};state.historyError={};updateRecord(data);state.adoptOpen=false;state.adoptReason='';state.adoptError='';state.adoptStale=false;state.notice='This BOM is now the material basis for '+physicalName()+'. Enter each piece’s heat / MTR and record its QA-001 decision. Prior records remain in History.';document.dispatchEvent(new CustomEvent('fabtrace:spool-materials-saved',{detail:{item_id:id,action:'document-bom-adopt',data}}));}
    catch(error){if(sequence===state.sequence){state.adoptError=errorText(error);state.adoptStale=error.status===409||!error.status||error.status>=500;if(state.adoptStale)state.adoptError+=' Your reason is retained. Reload the current material basis before trying again.';}}
    finally{if(sequence===state.sequence)saving(false);}
  }
  async function reload(key){
    if(busy())return;await load(state.selected);if(!record()||!key)return;const row=rowFor(key),f=draftMap()[key];if(!row||!f)return;
    f.material_base=fingerprint(row);f.material_stale=false;f.material_error=f.material_dirty?'Current values loaded. Your unsaved heat / MTR entries are retained for review before saving.':'';
    Object.assign(f.qa,{version:row.qa001.version,basis:row.qa001.basis_sha256,result:'',stale:false,error:'Current evidence loaded. Review this piece and choose Pass or Fail again; your findings are retained.'});render();
  }
  async function history(key){
    const row=rowFor(key),url='/api/spool-boms/spools/'+enc(state.selected)+'/materials/'+enc(key)+'/qa-001';if(busy()||!row||state.historyPending||row.qa001.history_url!==url)return;
    state.historyOpen[key]=!state.historyOpen[key];if(!state.historyOpen[key]||state.history[key]){render();return;}const sequence=state.sequence,id=state.selected;state.historyPending=key;state.historyError[key]='';render();
    try{const data=await request(url);if(sequence!==state.sequence)return;if(data.spool_id!==id||data.piece_key!==key||data.code!=='QA-001'||!Array.isArray(data.history))throw Error('The QA history did not match this physical piece.');state.history[key]=data.history;}
    catch(error){if(sequence===state.sequence)state.historyError[key]=errorText(error);}
    finally{if(sequence===state.sequence){state.historyPending='';render();}}
  }
  function inputEvent(event){
    if(busy())return;const input=event.target;if(input.id==='dpqaAdoptReason'){state.adoptReason=input.value;return;}if(input.id==='dpqaPassAllReference'||input.id==='dpqaPassAllNotes'){state.bulk[input.id==='dpqaPassAllReference'?'reference':'notes']=input.value;return;}const key=input.dataset.dpqaKey,field=input.dataset.dpqaMaterial||input.dataset.dpqaField,f=draftMap()[key];if(!f)return;
    if(['heat_number','mtr_reference','mtr_url'].includes(field)){f.material[field]=input.value;const row=rowFor(key);f.material_dirty=fields.some(field=>str(f.material[field]).trim()!==str(row?.[field]).trim());if(!f.qa.editing)f.qa.result=f.material_dirty?'':row.qa001.status==='passed'?'Pass':row.qa001.status==='failed'?'Fail':'';const tr=input.closest('[data-dpqa-piece]'),choice=tr?.querySelector('.dpqa-choice');if(choice)choice.disabled=qaLocked(row,f);for(const radio of tr?.querySelectorAll('[data-dpqa-result]')||[])radio.checked=radio.value===f.qa.result;const save=tr?.querySelector('[data-dpqa-action="save-material"]');if(save)save.disabled=!editable(row)||f.material_stale||!f.material_dirty&&row.persisted;const qaSave=tr?.querySelector('[data-dpqa-action="save-qa"]');if(qaSave){qaSave.disabled=qaLocked(row,f)||!f.qa.editing||!f.qa.result;qaSave.textContent=qaSaveLabel(f);}const note=tr?.querySelector('[data-dpqa-material-note]');if(note)note.textContent=f.material_dirty?'Unsaved changes for this piece.':'Heat and MTR values belong only to this physical piece.';const help=tr?.querySelector('[data-dpqa-qa-note]');if(help)help.textContent=f.qa.editing?'This choice is not saved yet. Complete the fields below, then save.':'Choose Pass or Fail to enter the inspection reference and findings.';const needs=tr?.querySelector('[data-dpqa-pass-needs]');if(needs)needs.innerHTML=passNeedsView(row,f);const bulk=state.host?.querySelector('.dpqa-bulk');if(bulk)bulk.outerHTML=bulkView();}
    else if(field==='material_reason')f.material_reason=input.value;
    else if(['reference','notes'].includes(field)){f.qa[field]=input.value;f.qa.editing=true;}
  }
  function change(event){
    if(busy())return;const input=event.target;
    if(input.id==='dpqaSpoolSelect'){state.selected=input.value;state.wrapper=null;state.history={};state.historyOpen={};state.historyError={};state.adoptOpen=false;state.adoptReason='';state.adoptError='';state.adoptStale=false;state.bulk=freshBulk();state.notice='';load(input.value);return;}
    const key=input.dataset.dpqaResult,row=rowFor(key),f=draftMap()[key];if(!row||!f||qaLocked(row,f))return;
    Object.assign(f.qa,{result:input.value,editing:true,error:''});render();const missing=input.value==='Pass'?passNeeds(row,f)[0]?.field:null;if(missing)focusMaterial(key,missing);else state.host?.querySelector(`[data-dpqa-piece="${key}"] [data-dpqa-field="reference"]`)?.focus({preventScroll:true});
  }
  async function click(event){
    const radio=event.target.closest('[data-dpqa-result]');if(radio){const f=draftMap()[radio.dataset.dpqaResult];if(f&&!f.qa.editing&&f.qa.result===radio.value)return change({target:radio});}
    const target=event.target.closest('[data-dpqa-action]');if(!target||target.disabled)return;event.preventDefault();const key=target.dataset.dpqaKey,action=target.dataset.dpqaAction;
    if(action==='save-material')return saveMaterial(key);if(action==='save-qa')return saveQa(key);if(action==='reload')return reload(key);if(action==='history')return history(key);if(action==='adopt-bom')return adoptBom();if(action==='confirm-pass-all')return passAll();if(action==='reload-pass-all')return reloadBulk();if(busy())return;
    if(action==='focus-material')return focusMaterial(key,target.dataset.dpqaFieldName);
    if(action==='focus-row')return focusMaterial(key);
    if(action==='pass-all'&&match()&&rows().length&&rows().every(row=>row.qa001.permissions?.can_inspect)){Object.assign(state.bulk,{open:true,signature:bulkSignature(),error:'',stale:false});render();state.host?.querySelector('#dpqaPassAll')?.scrollIntoView({block:'center'});return;}
    if(action==='cancel-pass-all'){state.bulk.open=false;render();return;}
    if(action==='adopt-panel'&&canAdopt()){state.adoptOpen=true;state.adoptError='';render();state.host?.querySelector('#dpqaAdoptReason')?.focus();return;}
    if(action==='cancel-adopt'){state.adoptOpen=false;state.adoptError='';render();return;}
    if(action==='new-decision'){const f=draftMap()[key];if(f){Object.assign(f.qa,{result:'',editing:true,error:''});render();}}
    if(action==='reload-documents')return state.reloadDocuments?.();
    if(action==='open-physical')return window.FabSpoolDocuments?.open({kind:'spools',id:state.selected,tab:'bom',fresh:true});
    if(action==='review-basis')return window.FabSpoolBom?.open({api_url:'/api/spool-boms/spools/'+state.selected,item_id:state.selected,spool_number:record()?.spool_number,revision:'',line_count:0});
  }
  function mount(options){
    const key=keyFor(options.target,options.document),changed=key!==state.key;
    if(changed){const saved=state.restore;reset();state.key=key;state.target={...options.target};state.doc=clone(options.document);state.context=clone(options.context);if(saved&&saved.key===key){state.selected=saved.selected||'';state.drafts=clone(saved.drafts)||{};state.notice=saved.notice||'';state.bulk=clone(saved.bulk)||freshBulk();if(saved.pendingSave&&state.bulk.open)state.bulk.stale=true;state.adoptOpen=!!saved.adoptOpen;state.adoptReason=saved.adoptReason||'';state.adoptStale=!!saved.pendingSave&&state.adoptOpen;if(saved.pendingSave)for(const pieces of Object.values(state.drafts))for(const f of Object.values(pieces)){f.material_stale=true;f.qa.stale=true;f.qa.result='';f.qa.error='A previous save may have completed. Reload this record before recording another decision.';}}}
    state.host=options.host;state.notify=options.onBusyChange;state.reloadDocuments=options.reloadDocuments;state.hostBusy=!!options.busy;
    if(state.needsRefresh&&!state.loading&&!state.saving)load(state.selected);else render();
  }
  function unmount(){if(state.host){state.host=null;if(!state.saving){state.controller?.abort();state.sequence++;state.loading=false;state.controller=null;state.historyPending='';}state.needsRefresh=true;}}
  function snapshot(){return state.key?{format:1,key:state.key,selected:state.selected,drafts:clone(state.drafts),notice:state.notice,pendingSave:state.saving,adoptOpen:state.adoptOpen,adoptReason:state.adoptReason,bulk:clone(state.bulk)}:clone(state.restore);}
  function restore(value){reset();state.restore=value?.format===1?clone(value):null;}
  function reset(){state.controller?.abort();state.sequence++;Object.assign(state,{key:'',target:null,doc:null,context:null,host:null,notify:null,reloadDocuments:null,hostBusy:false,controller:null,loading:false,saving:false,wrapper:null,selected:'',drafts:{},history:{},historyOpen:{},historyError:{},historyPending:'',adoptOpen:false,adoptReason:'',adoptError:'',adoptStale:false,error:'',notice:'',needsRefresh:true,restore:null,bulk:freshBulk()});}
  document.addEventListener('fabtrace:spool-materials-saved',event=>{if(state.saving||!state.wrapper||event.detail?.item_id!==state.selected)return;try{updateRecord(event.detail.data);state.history={};render();}catch(_){state.needsRefresh=true;if(state.host)load(state.selected);}});
  window.FabDocumentPieceQa={mount,unmount,snapshot,restore,reset,refresh:()=>load(state.selected),isSaving:()=>state.saving,canNavigateAway:()=>!state.saving};
})();
