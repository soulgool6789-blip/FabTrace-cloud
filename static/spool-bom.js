/* Approved drawing BOMs and per-physical-spool material traceability. */
(() => {
  'use strict';
  const node=id=>document.getElementById(id),dialog=node('spoolBomDialog');
  if(!dialog)return;
  const state={sequence:0,descriptor:null,data:null,draft:null,reason:'',loading:false,downloading:false,saving:false,error:'',formError:'',notice:'',stale:false,trigger:null,controller:null,downloadController:null};
  const materialFields=[['supplier','Supplier',160],['supplier_piece_id','Supplier piece / lot ID',160],['heat_number','Heat number',160],['mtr_reference','MTR reference',300],['mtr_url','MTR document link (optional HTTPS)',2000],['notes','Notes',3000]];
  const documentUrl=value=>{try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:'';}catch(_){return '';}};
  const apiPath=value=>typeof value==='string'?value.match(/^\/api\/spool-boms\/(requirements|spools)\/([A-Za-z0-9_-]{1,80})$/):null;
  const workbookPath=value=>typeof value==='string'&&/^\/api\/spool-boms\/workbooks\/[A-Za-z0-9][A-Za-z0-9._-]*\.xlsx$/.test(value);
  const count=value=>Number.isSafeInteger(value)&&value>=0;
  function descriptor(value){
    return value&&apiPath(value.api_url)&&typeof value.spool_number==='string'&&value.spool_number.length>0&&typeof value.revision==='string'&&value.revision.length>0&&count(value.line_count)?value:null;
  }
  function link(value){
    const d=descriptor(value);if(!d)return '';
    return `<button type="button" class="fbom-link" data-spool-bom-url="${esc(d.api_url)}" data-spool-bom-number="${esc(d.spool_number)}" data-spool-bom-revision="${esc(d.revision)}" data-spool-bom-lines="${d.line_count}" aria-haspopup="dialog" aria-controls="spoolBomDialog" aria-label="Bill of materials for spool ${esc(d.spool_number)}">Bill of materials</button>`;
  }
  function valid(data,d){
    const path=apiPath(d.api_url),context=data?.context,book=data?.source_workbook;
    if(!path||!context||context.kind!==(path[1]==='spools'?'spool':'requirement')||(path[1]==='spools'?context.item_id:context.requirement_id)!==path[2])return false;
    if(data.spool_number!==d.spool_number||data.revision!==d.revision||data.quantity_basis!=='one_spool'||data.line_count!==d.line_count||!Array.isArray(data.lines)||data.lines.length!==data.line_count)return false;
    if(typeof data.drawing_number!=='string'||typeof data.source_document!=='string'||typeof data.quantity_basis_label!=='string'||typeof data.revision_date!=='string'||!Number.isInteger(data.source_sheet)||!Number.isInteger(data.source_page_count)||data.source_sheet<1||data.source_sheet>data.source_page_count)return false;
    if(!book||typeof book.filename!=='string'||!book.filename.toLowerCase().endsWith('.xlsx')||/[\\/\x00-\x1f\x7f]/.test(book.filename)||!workbookPath(book.download_url)||typeof book.sha256!=='string'||!/^[a-fA-F0-9]{64}$/.test(book.sha256))return false;
    if(!data.lines.every(row=>Number.isInteger(row.item)&&row.item>0&&Number.isInteger(row.quantity)&&row.quantity>0&&typeof row.tas_ln_number==='string'&&typeof row.description==='string'&&typeof row.material==='string'&&typeof row.length_display==='string'&&(row.length_inches===null||typeof row.length_inches==='number'&&Number.isFinite(row.length_inches)&&row.length_inches>=0)))return false;
    if(!count(data.total_pieces)||data.total_pieces!==data.lines.reduce((n,row)=>n+row.quantity,0))return false;
    if(context.kind==='spool'){
      const t=data.traceability;if(!t||!count(t.version)||typeof t.configured!=='boolean'||typeof t.complete!=='boolean'||typeof t.editable!=='boolean'||typeof t.locked_reason!=='string'||!Array.isArray(t.materials)||t.materials.length!==data.total_pieces||!Array.isArray(t.history))return false;
      const expected=new Set(data.lines.flatMap(row=>Array.from({length:row.quantity},(_,i)=>row.item+'-'+(i+1))));
      if(!t.materials.every(row=>{const line=data.lines.find(line=>line.item===row.item);return expected.delete(row.piece_key)&&line&&row.piece_key===row.item+'-'+row.piece_number&&row.pieces_on_line===line.quantity&&row.piece_number>=1&&row.piece_number<=line.quantity&&['tas_ln_number','description','material','length_display',...materialFields.map(field=>field[0])].every(key=>typeof row[key]==='string');})||expected.size)return false;
      if(!t.history.every(row=>count(row.version)&&typeof row.actor==='string'&&typeof row.at==='string'&&typeof row.reason==='string'&&Array.isArray(row.changes)&&row.changes.every(change=>typeof change.piece_key==='string'&&change.before&&change.after)))return false;
    }
    return true;
  }
  function errorText(error){
    if(error?.status===401)return 'Your session has expired. Sign in again, then reopen this bill of materials.';
    if(error?.status===403)return 'Your account does not have permission for this action.';
    if(error?.status===404)return 'An approved bill of materials is no longer available for this spool. Refresh the spool record and try again.';
    return String(error?.message||'The bill of materials could not be loaded. Please try again.');
  }
  function contextField(label,value){return value?`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`:'';}
  function materialDraft(data){return data.context.kind==='spool'?data.traceability.materials.map(row=>({piece_key:row.piece_key,...Object.fromEntries(materialFields.map(([key])=>[key,row[key]]))})):null;}
  function pieceName(row){return 'Item '+row.item+' · Piece '+row.piece_number+' of '+row.pieces_on_line;}
  function traceField(piece,key,label,max){
    const id='fbom-'+piece.piece_key+'-'+key,value=piece[key],common=`id="${id}" data-fbom-piece="${piece.piece_key}" data-fbom-field="${key}" maxlength="${max}"`;
    return `<div class="fbom-field${key==='notes'||key==='mtr_url'?' fbom-wide':''}"><label for="${id}">${esc(label)}</label>${key==='notes'?`<textarea ${common} rows="2">${esc(value)}</textarea>`:`<input ${common} type="${key==='mtr_url'?'url':'text'}" value="${esc(value)}" autocomplete="off">`}</div>`;
  }
  function historyView(t){
    if(!t.history.length)return '<p class="fbom-note">No material traceability changes have been saved.</p>';
    return `<details class="fbom-history"><summary>Material change history (${t.history.length})</summary>${t.history.map(entry=>`<article><h4>Revision ${entry.version} · ${esc(entry.actor)}</h4><p>${esc(entry.at)} · ${esc(entry.reason)}</p>${entry.changes.map(change=>{const piece=t.materials.find(row=>row.piece_key===change.piece_key);return `<section><strong>${esc(piece?pieceName(piece):change.piece_key)}</strong><dl>${materialFields.filter(([key])=>change.before[key]!==change.after[key]).map(([key,label])=>`<div><dt>${esc(label)}</dt><dd><span>Before: ${esc(change.before[key]||'Not entered')}</span><span>Saved: ${esc(change.after[key]||'Not entered')}</span></dd></div>`).join('')}</dl></section>`;}).join('')}</article>`).join('')}</details>`;
  }
  function traceabilityView(d){
    if(d.context.kind!=='spool')return '<p class="fbom-note">Heat numbers and MTR references are recorded on each individual physical spool after its spool record is created.</p>';
    const t=d.traceability,values=state.draft||materialDraft(d),heat=values.filter(p=>p.heat_number.trim()).length,mtr=values.filter(p=>p.mtr_reference.trim()).length,editable=t.editable,disabled=state.loading||state.saving;
    return `<section id="spoolBomTraceability" class="fbom-trace"><div class="fbom-trace-head"><div><h3>Material traceability</h3><p>These material records belong to physical spool <strong>${esc(d.context.item_id)}</strong>.</p></div><span class="fbom-badge">${t.configured?'Saved revision '+t.version:'No material details saved'}</span></div><p class="fbom-note">Record the actual supplier, heat number and MTR reference for each piece. Separate pieces can have different heats or MTRs. Saving material details retains their history; QA approval is recorded separately.</p><p id="spoolBomCoverage" class="fbom-coverage">${heat} of ${values.length} heat numbers entered · ${mtr} of ${values.length} MTR references entered${heat<values.length||mtr<values.length?' · Missing details remain incomplete.':'.'}</p>${!editable?`<p class="fbom-locked">${esc(t.locked_reason||'Your role can view these material records. A permitted employee can update them.')}</p>`:''}${state.notice?`<p class="fbom-save-notice" role="status">${esc(state.notice)}</p>`:''}${state.formError?`<div class="fbom-error" role="alert"><p>${esc(state.formError)}</p>${state.stale?'<p>Your draft remains below. Reloading replaces it with the latest saved values.</p><button type="button" id="spoolBomReload">Reload saved values</button>':''}</div>`:''}<form id="spoolBomTraceForm" novalidate><fieldset${disabled?' disabled':''}>${t.materials.map((piece,index)=>{const p=values[index];return `<section class="fbom-piece"><h4>${esc(pieceName(piece))}</h4><p class="fbom-piece-description">${esc(piece.description)}</p><p class="fbom-note">TAS/LN ${esc(piece.tas_ln_number)} · ${esc(piece.material)}${piece.length_display?' · '+esc(piece.length_display):''}</p>${editable?`<div class="fbom-piece-fields">${materialFields.map(([key,label,max])=>traceField(p,key,label,max)).join('')}</div>`:`<dl class="fbom-read-fields">${materialFields.map(([key,label])=>`<div><dt>${esc(label)}</dt><dd>${key==='mtr_url'&&documentUrl(p[key])?`<a href="${esc(documentUrl(p[key]))}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Open MTR document</a>`:esc(p[key]||'Not entered')}</dd></div>`).join('')}</dl>`}${piece.updated_by?`<p class="fbom-note">Last saved by ${esc(piece.updated_by)}${piece.updated_at?' · '+esc(piece.updated_at):''}</p>`:''}</section>`;}).join('')}${editable?`<div class="fbom-field fbom-reason"><label for="spoolBomReason">Reason for this update</label><textarea id="spoolBomReason" maxlength="3000" rows="2" placeholder="For example: Enter supplier receiving records">${esc(state.reason)}</textarea></div><div class="fbom-save-actions"><p class="fbom-note">Partial entries can be saved. Each piece needs a heat number and MTR reference for complete material details.</p><button type="submit" id="spoolBomSave" class="primary"${state.stale?' disabled':''}>${state.saving?'Saving material records…':'Save material traceability'}</button></div>`:''}</fieldset></form>${historyView(t)}</section>`;
  }
  function wireTrace(){
    const form=node('spoolBomTraceForm');if(form){form.onsubmit=event=>{event.preventDefault();return saveTraceability();};form.addEventListener('input',event=>{const target=event.target;if(!state.data?.traceability?.editable||state.saving||state.loading)return;if(target.id==='spoolBomReason'){state.reason=target.value;return;}const p=state.draft?.find(p=>p.piece_key===target.dataset.fbomPiece),key=target.dataset.fbomField;if(p&&materialFields.some(field=>field[0]===key))p[key]=target.value;const heat=state.draft.filter(p=>p.heat_number.trim()).length,mtr=state.draft.filter(p=>p.mtr_reference.trim()).length;node('spoolBomCoverage').textContent=heat+' of '+state.draft.length+' heat numbers entered · '+mtr+' of '+state.draft.length+' MTR references entered'+(heat<state.draft.length||mtr<state.draft.length?' · Missing details remain incomplete.':'.');});}
    const reload=node('spoolBomReload');if(reload)reload.onclick=()=>load();
  }
  async function saveTraceability(){
    if(!dialog.open||state.loading||state.saving||state.stale||!state.data?.traceability?.editable)return;
    const materials=state.draft.map(row=>({piece_key:row.piece_key,...Object.fromEntries(materialFields.map(([key])=>[key,row[key].trim()]))})),reason=state.reason.trim();
    if(reason.length<4||reason.length>3000){state.formError='Enter a reason for this update (4–3,000 characters).';render();return;}
    for(const row of materials)for(const [key,label,max] of materialFields){if(row[key].length>max){state.formError=label+' must be '+max+' characters or fewer.';render();return;}if(key==='mtr_url'&&row[key]&&!documentUrl(row[key])){state.formError='Use a full HTTPS document link for the MTR, or leave the optional link blank.';render();return;}}
    const sequence=state.sequence,d=state.descriptor,expectedVersion=state.data.traceability.version;state.saving=true;state.formError='';state.notice='';node('spoolBomDownloadError').textContent='';render();
    try{
      const data=await api(d.api_url+'/traceability',{method:'PUT',body:JSON.stringify({expected_version:expectedVersion,reason,materials})});
      if(sequence!==state.sequence||!dialog.open)return;
      if(!valid(data,d)||data.traceability.version!==expectedVersion+1)throw Error('The saved response could not be verified. Reload the latest saved values before saving again.');
      state.data=data;state.draft=materialDraft(data);state.reason='';state.notice='Material traceability saved for spool '+data.context.item_id+'.';
    }catch(error){if(sequence===state.sequence&&dialog.open){state.formError=errorText(error);state.stale=error.status===409||!error.status;if(state.stale)state.formError+=' Reload the saved record before making another change.';}}
    finally{if(sequence===state.sequence&&dialog.open){state.saving=false;render();}}
  }
  function render(){
    node('spoolBomSubtitle').textContent=state.descriptor?'Spool '+state.descriptor.spool_number+' · Drawing revision '+state.descriptor.revision:'';
    const body=node('spoolBomContent');body.setAttribute('aria-busy',String(state.loading));
    if(state.loading&&!state.data)body.innerHTML='<p class="fbom-state" role="status">Loading the approved bill of materials…</p>';
    else if(state.error&&!state.data)body.innerHTML=`<div class="fbom-error" role="alert"><strong>The bill of materials could not be opened.</strong><p>${esc(state.error)}</p><button type="button" id="spoolBomRetry">Try again</button></div>`;
    else if(state.data){
      const d=state.data,c=d.context;
      body.innerHTML=`${state.loading?'<p class="fbom-note" role="status">Loading the latest saved values…</p>':''}${state.error?`<div class="fbom-error" role="alert"><p>${esc(state.error)}</p><button type="button" id="spoolBomRetry">Try again</button></div>`:''}<div class="fbom-source"><span class="fbom-badge">Approved drawing BOM</span><p>Drawing <strong>${esc(d.drawing_number)}</strong> · Revision <strong>${esc(d.revision)}</strong> · ${esc(d.revision_date)}</p><p>${esc(d.source_document)} · Sheet ${d.source_sheet} of ${d.source_page_count}</p></div><dl class="fbom-context">${contextField('P.O.',c.purchase_order)}${contextField('GPN / Assembly',c.assembly_number)}${contextField('Assembly ID',c.assembly_id)}${contextField('Spool ID',c.item_id)}</dl><div class="fbom-basis"><strong>${esc(d.quantity_basis_label)}</strong><span>${d.line_count} material line${d.line_count===1?'':'s'} · ${d.total_pieces} total piece${d.total_pieces===1?'':'s'}</span></div><div class="fbom-table-wrap" role="region" aria-label="Material list for spool ${esc(d.spool_number)}" tabindex="0"><table><caption>Bill of materials · ${esc(d.spool_number)}</caption><thead><tr><th scope="col">Item</th><th scope="col">Qty</th><th scope="col">TAS/LN number</th><th scope="col">Description</th><th scope="col">Length</th><th scope="col">Material</th></tr></thead><tbody>${d.lines.map(row=>`<tr><td>${row.item}</td><td>${row.quantity}</td><td>${esc(row.tas_ln_number)}</td><td>${esc(row.description)}</td><td>${esc(row.length_display||'—')}</td><td>${esc(row.material)}</td></tr>`).join('')}</tbody></table></div>${traceabilityView(d)}`;
    }else body.innerHTML='';
    const download=node('spoolBomDownload');download.disabled=state.loading||state.downloading||state.saving||!state.data;download.textContent=state.downloading?'Downloading Excel…':'Download approved Excel';download.setAttribute('aria-busy',String(state.downloading));
    node('spoolBomDownloadNote').textContent=state.data?'The approved workbook includes both spool bills of materials.':'';
    node('spoolBomClose').disabled=state.saving;node('spoolBomDone').disabled=state.saving;
    const retry=node('spoolBomRetry');if(retry)retry.onclick=()=>load();wireTrace();
  }
  function invalidate(){state.sequence++;state.controller?.abort();state.downloadController?.abort();state.controller=null;state.downloadController=null;state.loading=false;state.downloading=false;}
  function close(restore=true){
    if(state.saving&&restore)return;
    const trigger=state.trigger;invalidate();state.data=null;state.draft=null;state.reason='';state.saving=false;state.stale=false;state.formError='';state.notice='';state.descriptor=null;state.error='';state.trigger=null;render();
    if(dialog.open)dialog.close();
    if(restore&&trigger?.isConnected&&typeof trigger.focus==='function')trigger.focus();
  }
  async function load(){
    if(!dialog.open||!state.descriptor||state.saving)return;
    state.controller?.abort();state.downloadController?.abort();state.controller=new AbortController();state.downloading=false;
    const sequence=++state.sequence,d=state.descriptor,controller=state.controller;state.loading=true;state.error='';node('spoolBomDownloadError').textContent='';render();
    try{
      const data=await api(d.api_url,{signal:controller.signal});
      if(sequence!==state.sequence||!dialog.open)return;
      if(!valid(data,d))throw Error('The returned bill of materials does not match this spool and approved revision. Refresh the spool record before trying again.');
      state.data=data;state.draft=materialDraft(data);state.reason='';state.formError='';state.notice='';state.stale=false;
    }catch(error){if(sequence===state.sequence&&dialog.open&&error.name!=='AbortError')state.error=errorText(error);}
    finally{if(sequence===state.sequence&&dialog.open){state.loading=false;state.controller=null;render();}}
  }
  async function open(value,trigger=document.activeElement){
    if(!me||state.saving)return;const d=descriptor(value);if(!d)return;
    invalidate();state.descriptor={...d};state.trigger=trigger;state.data=null;state.draft=null;state.reason='';state.formError='';state.notice='';state.stale=false;state.error='';node('spoolBomDownloadError').textContent='';
    if(!dialog.open)dialog.showModal();
    node('spoolBomClose').focus();return load();
  }
  async function download(){
    if(state.downloading||state.loading||state.saving||!state.data||!dialog.open)return;
    const sequence=state.sequence,book=state.data.source_workbook;if(!workbookPath(book.download_url))return;
    state.downloading=true;state.downloadController=new AbortController();node('spoolBomDownloadError').textContent='';render();
    let objectUrl=null,anchor=null;
    try{
      const response=await fetch(book.download_url,{credentials:'same-origin',redirect:'error',signal:state.downloadController.signal,headers:{Accept:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}});
      if(!response.ok){const error=Error('The approved Excel workbook could not be downloaded. Please try again.');error.status=response.status;throw error;}
      if(!(response.headers.get('content-type')||'').toLowerCase().includes('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))throw Error('The server did not return the approved Excel workbook. Refresh this record and try again.');
      const blob=await response.blob();if(sequence!==state.sequence||!dialog.open)return;if(!blob.size)throw Error('The approved workbook was empty. Please try again.');
      objectUrl=URL.createObjectURL(blob);anchor=document.createElement('a');anchor.href=objectUrl;anchor.download=book.filename;anchor.style.display='none';document.body.appendChild(anchor);anchor.click();
      node('spoolBomDownloadError').textContent='Approved Excel workbook downloaded.';
    }catch(error){if(sequence===state.sequence&&dialog.open&&error.name!=='AbortError')node('spoolBomDownloadError').textContent=errorText(error);}
    finally{anchor?.remove();if(objectUrl)setTimeout(()=>URL.revokeObjectURL(objectUrl),30000);if(sequence===state.sequence&&dialog.open){state.downloading=false;state.downloadController=null;render();}}
  }
  node('spoolBomClose').onclick=()=>close();node('spoolBomDone').onclick=()=>close();node('spoolBomDownload').onclick=()=>download();
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  dialog.addEventListener('close',()=>{if(!dialog.open&&state.descriptor)close();});
  document.addEventListener('click',event=>{
    const target=event.target.closest?.('[data-spool-bom-url]');if(!target||target.disabled)return;
    event.preventDefault();return open({api_url:target.dataset.spoolBomUrl,spool_number:target.dataset.spoolBomNumber,revision:target.dataset.spoolBomRevision,line_count:Number(target.dataset.spoolBomLines)},target);
  });
  window.FabSpoolBom={link,open,cancelPending:()=>close(false)};
})();
