/* Spool-scoped BOM files and complete isometric drawing sets. */
(() => {
  'use strict';
  const ROOT='/api/spool-documents',node=id=>document.getElementById(id),arr=value=>Array.isArray(value)?value:[],enc=encodeURIComponent;
  const state={target:null,sequence:0,data:null,tab:'bom',uploadKind:'bom',view:'upload',step:'files',sourceMode:'auto',path:[],resume:null,scanTimer:null,loading:false,working:false,saving:false,error:'',notice:'',trigger:null,controller:null,drafts:null,viewer:null,package:null};
  const fresh=()=>({files:[],sheet:'',revision:'',reason:'',reasonAutomatic:false,requiresReason:false,preview:null,error:'',stale:false,expanded:false});
  const idOK=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(value);
  const fileUrl=value=>typeof value==='string'&&/^\/api\/spool-documents\/files\/[A-Za-z0-9_-]{1,100}(?:\/bom\.xlsx|\?download=1)?$/.test(value)?value:'';
  const BOM_FIELDS=[['item','Item'],['quantity','Qty'],['unit','Unit'],['part_number','Part / TAS number'],['description','Description'],['size','Size'],['material','Material'],['length','Length'],['notes','Notes']];
  const UPLOAD_ACCEPT='.pdf,.jpg,.jpeg,.png,.xlsx,.csv,.tsv,application/pdf,image/jpeg,image/png,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv';
  const MAX_REVIEW_BYTES=900*1024;
  const documentKind=review=>['bom','isometric'].includes(review?.data.source.document_kind)?review.data.source.document_kind:null;
  const pieceSaving=()=>window.FabDocumentPieceQa?.isSaving()===true;
  const busy=()=>state.loading||state.working||state.saving||pieceSaving();
  const bytes=value=>value>=1048576?(value/1048576).toFixed(1)+' MB':Math.max(1,Math.ceil(value/1024))+' KB';
  const label=kind=>kind==='bom'?'Bill of material':'Isometric drawings';
  const spoolText=(value,number)=>window.FabFlowStatus?.spoolText(value,number)||esc(number);
  const spoolRecord=data=>({...data?.context,flow_stage:data?.flow_stage});
  function spoolCopies(){const rows=arr(state.data?.physical_spools);return rows.length>1?`<details class="sdoc-copy-status"><summary>${rows.length} physical spools${state.data.flow_stage_state==='mixed'?' · Mixed flow stages':''}</summary>${rows.map(row=>`<p>${spoolText(row,window.FabFlowStatus?.spoolNumber(row)||row.display_code||row.item_id)} · ${esc(row.flow_stage?.label||'Status unavailable')}</p>`).join('')}</details>`:'';}
  const button=(action,caption,extra='',primary=false,disabled=false)=>`<button type="button" data-sdoc-action="${action}" ${extra}${disabled?' disabled':''}${primary?' class="primary"':''}>${esc(caption)}</button>`;
  const dialog=document.createElement('dialog');dialog.id='spoolDocumentsDialog';dialog.setAttribute('aria-labelledby','spoolDocumentsTitle');dialog.setAttribute('aria-describedby','spoolDocumentsSubtitle');
  dialog.innerHTML='<div class="sdoc-head"><div class="sdoc-heading"><button id="spoolDocumentsBack" type="button">← Back</button><div><span class="sdoc-eyebrow">Spool documents</span><h2 id="spoolDocumentsTitle">BOM &amp; drawings</h2><p id="spoolDocumentsSubtitle"></p></div></div><button id="spoolDocumentsClose" type="button" aria-label="Close spool documents">×</button></div><div id="spoolDocumentsContent"></div><div class="sdoc-footer"><p>Files stay with their selected spool records.</p><button id="spoolDocumentsDone" type="button">Return to spool</button></div>';
  document.body.appendChild(dialog);

  function link(kind,id,spoolNumber='',caption='BOM & drawings',tab='upload'){
    if(!['requirements','spools'].includes(kind)||!idOK(id))return '';
    return `<button type="button" class="sdoc-link" data-sdoc-kind="${kind}" data-sdoc-id="${esc(id)}" data-sdoc-number="${esc(spoolNumber)}" data-sdoc-tab="${['bom','isometric','history'].includes(tab)?tab:'upload'}" aria-haspopup="dialog" aria-controls="spoolDocumentsDialog">${esc(caption)}</button>`;
  }
  async function request(path,options={}){
    const response=await fetch(path,{credentials:'same-origin',redirect:'error',...options});
    let result;try{result=await response.json();}catch(_){const error=Error('The server returned an unreadable response. Refresh and try again.');error.status=response.status;throw error;}
    if(!response.ok){let detail=result.detail;const message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map(row=>row.msg||String(row)).join('; '):detail?.message||result.message||'This document request could not be completed.';const error=Error(message);error.status=response.status;throw error;}
    return result;
  }
  function errorText(error){
    if(error.status===401)return 'Your session has expired. Sign in again, then reopen the spool.';
    if(error.status===403)return 'Your position does not have permission to upload documents for this spool.';
    return String(error.message||'The document could not be loaded. Please try again.');
  }
  function valid(data){
    const c=data?.context,t=state.target;
    return c&&t&&c.kind===(t.kind==='spools'?'spool':'requirement')&&(t.kind==='spools'?c.item_id:c.requirement_id)===t.id&&Number.isInteger(data.version)&&data.version>=0&&typeof data.editable==='boolean'&&data.active&&Array.isArray(data.history);
  }
  function clearDraft(draft){for(const entry of draft?.files||[])if(entry.url)URL.revokeObjectURL(entry.url);}
  function clearDrafts(){if(state.drafts)for(const draft of Object.values(state.drafts))clearDraft(draft);state.drafts={bom:fresh(),isometric:fresh()};}
  function invalidatePreview(draft){draft.preview=null;draft.error='';draft.stale=false;if(draft===state.drafts?.isometric)state.package=null;}
  function contextView(){
    const c=state.data.context,identity=state.data.assembly_identity,physical=c.kind==='spool';
    return `<dl class="sdoc-context">${[['P.O.',c.purchase_order||c.project_id],['GPN',identity?.gpn??c.assembly_number],['Assembly Number',identity?.assembly_number||'Not entered'],['Spool number',c.spool_number],...(physical?[['Physical spool',c.display_code||c.qr_alias||c.item_id],...(c.display_code&&c.display_code!==c.item_id?[['Internal record ID',c.item_id]]:[])]:[])].filter(row=>row[1]).map(([name,value])=>`<div><dt>${esc(name)}</dt><dd>${['Spool number','Physical spool'].includes(name)?spoolText(spoolRecord(state.data),value):esc(value)}</dd></div>`).join('')}</dl>${spoolCopies()}<p class="sdoc-scope">${physical?'These files belong to this physical spool. Use assembly setup when a drawing covers several corresponding spools.':'Files are matched to spools in this P.O. and assembly.'}</p>${physical&&!state.package&&!state.working&&(state.tab==='isometric'||state.view==='upload'&&!state.drafts.bom.files.length)&&state.data.permissions?.can_upload!==false&&idOK(c.requirement_id)?`<div class="sdoc-share"><div><strong>Does this isometric cover several spools?</strong><p>Use assembly setup to share the full drawing and create a separate Excel BOM for every matching spool. Your selected files will carry over.</p></div>${button('use-assembly','Use for all assembly spools','',false,busy())}</div>`:''}`;
  }
  function table(bom,caption='Bill of material'){
    if(!bom||!Array.isArray(bom.lines))return '';
    const columns=[...BOM_FIELDS,['source_page','Drawing page']];
    const shown=columns.filter(([key])=>['item','quantity','description'].includes(key)||bom.lines.some(row=>row[key]!==undefined&&row[key]!==null&&String(row[key]).length));
    return `<p class="sdoc-meta">${bom.lines.length} material line${bom.lines.length===1?'':'s'} · Quantities for one spool${bom.sheet?' · Worksheet: '+esc(bom.sheet):''}</p>${arr(bom.warnings).map(w=>`<p class="sdoc-warning">${esc(w)}</p>`).join('')}<div class="sdoc-table" tabindex="0" role="region" aria-label="${esc(caption)}"><table><caption>${esc(caption)}</caption><thead><tr>${shown.map(([,name])=>`<th scope="col">${esc(name)}</th>`).join('')}</tr></thead><tbody>${bom.lines.map(row=>`<tr>${shown.map(([key])=>`<td>${esc(row[key]??'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function documentActions(doc){
    const view=fileUrl(doc.view_url),download=fileUrl(doc.download_url),excel=fileUrl(doc.excel_url),source=fileUrl(doc.source_view_url),pdf=doc.media_type==='application/pdf';
    return `<div class="sdoc-actions">${Array.isArray(doc.bom?.lines)?button('view-grid','View BOM',`data-sdoc-document="${esc(doc.id)}"`,true):pdf&&view?`<a class="sdoc-primary-link" href="${esc(view)}" target="_blank" rel="noopener noreferrer">${doc.kind==='isometric'?'View full isometric':'View BOM'}</a>`:''}${pdf&&view?button('preview-saved','Preview all pages',`data-sdoc-document="${esc(doc.id)}"`):''}${pdf&&state.data.editable?button('create-boms','Create spool BOMs',`data-sdoc-document="${esc(doc.id)}" data-sdoc-source-kind="${esc(doc.kind)}"`,false,busy()):''}${excel?`<a href="${esc(excel)}" download>Download Excel BOM</a>`:''}${source?`<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">View uploaded BOM image / PDF</a>`:''}${download&&(!excel||!doc.bom?.provenance)?`<a href="${esc(download)}" download>Download ${doc.kind==='isometric'?'drawing file':excel?'uploaded BOM':'BOM file'}</a>`:''}</div>`;
  }
  function savedDocument(){
    const doc=state.data.active[state.tab];
    if(!doc)return `<section class="sdoc-empty"><h3>No ${state.tab==='bom'?'bill of material':'isometric drawing'} uploaded yet</h3><p>${state.tab==='bom'?'Choose an Excel workbook, CSV, or a scanned PDF bill of material.':'Upload the complete drawing PDF, or scan and add every page below.'}</p></section>`;
    const viewer=state.viewer===doc.id&&fileUrl(doc.view_url)&&doc.media_type==='application/pdf';
    return `<section class="sdoc-saved"><div class="sdoc-saved-title"><div><span class="sdoc-eyebrow">${doc.inherited?'From assembly / spool setup':'Saved for this spool'}</span><h3>${esc(doc.filename)}</h3></div><span class="sdoc-badge">${doc.revision?'Revision '+esc(doc.revision):'Version '+doc.version}</span></div><p class="sdoc-meta">${doc.page_count?`${doc.page_count} page${doc.page_count===1?'':'s'} · `:''}${bytes(doc.size_bytes||0)} · Uploaded by ${esc(doc.uploaded_by||'—')}${doc.uploaded_at?' · '+esc(new Date(doc.uploaded_at).toLocaleString()):''}</p>${documentActions(doc)}${doc.bom?'<div id="sdocSavedGrid"><p class="sdoc-loading" role="status">Loading individual material pieces…</p></div>':''}${viewer?`<div class="sdoc-viewer"><iframe src="${esc(fileUrl(doc.view_url))}" title="Complete ${esc(label(doc.kind).toLowerCase())} · ${doc.page_count||''} pages"></iframe><p class="sdoc-meta">Use the viewer controls to move through all pages. You can also open the full file using the link above.</p></div>`:''}</section>`;
  }
  function filesView(draft){
    if(!draft.files.length)return '';
    return `<ol class="sdoc-files" aria-label="Selected files in page order">${draft.files.map((entry,index)=>`<li><span class="sdoc-file-order">${index+1}</span>${entry.file.type.startsWith('image/')&&entry.url?`<img src="${esc(entry.url)}" alt="Selected scan ${index+1}" loading="lazy">`:'<span class="sdoc-file-icon" aria-hidden="true">PDF<br>/ file</span>'}<div class="sdoc-file-name"><strong>${esc(entry.file.name)}</strong><span>${bytes(entry.file.size)}</span></div><div class="sdoc-file-actions">${state.tab==='isometric'?button('move-up','↑',`data-sdoc-index="${index}" aria-label="Move ${esc(entry.file.name)} earlier"`,false,busy()||index===0)+button('move-down','↓',`data-sdoc-index="${index}" aria-label="Move ${esc(entry.file.name)} later"`,false,busy()||index===draft.files.length-1):''}${button('remove-file','Remove',`data-sdoc-index="${index}"`,false,busy())}</div></li>`).join('')}</ol>`;
  }
  function previewView(draft){
    const p=draft.preview;if(!p)return '';
    const sheets=arr(p.sheets),requiresSheet=p.sheet_required===true;
    return `<section class="sdoc-preview"><h4>${requiresSheet?'Choose a worksheet':'Ready to review'}</h4>${requiresSheet?'<p>Select the worksheet for this spool, then preview again.</p>':`<p>${p.page_count?`<strong>${p.page_count} page${p.page_count===1?'':'s'}</strong> in the complete file. `:''}${p.bom?'Review the materials below before saving.':p.kind==='isometric'?'All pages will be saved as one viewable drawing file.':'This PDF will be saved as a viewable bill of material.'}</p>`}${sheets.length?`<div class="field"><label for="sdocSheetChoice">BOM worksheet</label><select id="sdocSheetChoice"><option value="">Select worksheet</option>${sheets.map(sheet=>{const name=typeof sheet==='string'?sheet:sheet.name;return `<option value="${esc(name)}"${name===draft.sheet?' selected':''}>${esc(name)}</option>`;}).join('')}</select></div>`:''}${p.bom?table(p.bom,'Preview · '+state.data.context.spool_number):''}</section>`;
  }
  const packageTargetId=target=>target.spool_id||target.requirement_id||'';
  const packageTarget=(review,candidate)=>review.data.targets.find(target=>packageTargetId(target)===candidate.target_id);
  const selectedCandidates=review=>review.candidates.filter(candidate=>candidate.selected);
  function reviewFields(draft){
    return `<div class="sdoc-upload-fields"><div class="field"><label for="sdocRevision">Revision (optional)</label><input id="sdocRevision" maxlength="80" value="${esc(draft.revision)}" placeholder="For example: 2 or A"${busy()?' disabled':''}></div><div class="field"><label for="sdocReason">${draft.requiresReason?'Reason for this change':'Save note'}</label><input id="sdocReason" maxlength="3000" value="${esc(draft.reason)}" placeholder="${draft.requiresReason?'What changed in this revision?':'Initial reference file'}"${busy()?' disabled':''}></div></div>`;
  }
  function saveNotes(draft){return draft.requiresReason?reviewFields(draft):`<details class="sdoc-save-options"><summary>Revision and save notes (optional)</summary>${reviewFields(draft)}</details>`;}
  function configurePackageReason(){
    const review=state.package;if(!review)return;
    const draft=state.drafts.isometric,kind=review.sourceOnlyKind||documentKind(review),replacement=review.sourceOnlyKind?!!state.data.active[kind]:selectedCandidates(review).some(candidate=>{const target=packageTarget(review,candidate);return target&&(target.has_bom||kind==='isometric'&&review.data.source.kind==='upload'&&target.has_isometric);});
    draft.requiresReason=!!replacement;
    if(replacement&&draft.reasonAutomatic){draft.reason='';draft.reasonAutomatic=false;}
    if(!replacement&&(draft.reasonAutomatic||!draft.reason.trim())){draft.reason=kind==='bom'?'Initial BOM from uploaded material list':review.data.source.kind==='saved'?'Initial BOM from saved reference file':'Initial reference files from uploaded drawing';draft.reasonAutomatic=true;}
  }
  function uploadFilesView(){
    const draft=state.drafts[state.tab==='isometric'?'isometric':'bom'],editable=state.data.editable;
    if(!editable)return `<p class="sdoc-locked">${esc(state.data.locked_reason||'Your position can view the saved files below. An employee with upload permission can add new files.')}</p>`;
    const resume=!!state.package||!!draft.preview;
    return `<section class="sdoc-upload-start"><span class="sdoc-eyebrow">Upload files</span><h3>Choose your drawing, scan, or BOM</h3><p>PDFs and photos are read automatically. FabTrace keeps the full source and creates a separate Excel BOM for each corresponding spool after you review it.</p><div class="sdoc-actions"><label class="sdoc-file-button sdoc-choose-primary" for="sdocFileInput">${draft.files.length?'Add / choose files':'Choose files'}<input id="sdocFileInput" type="file" accept="${UPLOAD_ACCEPT}" multiple${busy()?' disabled':''}></label><label class="sdoc-file-button" for="sdocCameraInput">Scan a page<input id="sdocCameraInput" type="file" accept="image/jpeg,image/png" capture="environment"${busy()?' disabled':''}></label></div><p class="sdoc-meta">PDF, JPG, PNG, Excel or CSV. Choose all drawing pages together, or add scans one page at a time.</p><details class="sdoc-file-options"><summary>File options</summary><div class="field"><label for="sdocSourceMode">What is in this PDF or image?</label><select id="sdocSourceMode"><option value="auto"${state.sourceMode==='auto'?' selected':''}>Detect automatically</option><option value="isometric"${state.sourceMode==='isometric'?' selected':''}>Isometric / drawing</option><option value="bom"${state.sourceMode==='bom'?' selected':''}>Bill of material only</option></select></div>${button('template','Download blank BOM template')}</details>${filesView(draft)}${draft.error?`<p class="sdoc-error" role="alert">${esc(draft.error)}</p>`:''}${state.scanTimer?'<p class="sdoc-loading" role="status">Preparing to read the selected pages…</p>':''}${draft.files.some(entry=>/\.xlsx$/i.test(entry.file.name))?`<div class="field"><label for="sdocSheet">Worksheet name (optional)</label><input id="sdocSheet" value="${esc(draft.sheet)}" placeholder="Preview lists available worksheets"></div>`:''}${draft.files.length?`<div class="sdoc-actions">${resume?button('continue-review','Continue to review','',true,busy()):button('preview',state.tab==='isometric'?'Read files again':'Review BOM','',true,busy()||!!state.scanTimer)}${button('clear-files','Choose different files','',false,busy())}</div>`:''}</section>`;
  }
  function processingView(){
    const draft=state.drafts[state.tab==='isometric'?'isometric':'bom'],scans=draft.files.some(entry=>/\.(png|jpe?g)$/i.test(entry.file.name));
    return `<section class="sdoc-processing" role="status" aria-live="polite"><span class="sdoc-spinner" aria-hidden="true"></span><h3>${state.tab==='bom'?'Reading your BOM…':scans?'Scanning your uploaded pages…':'Reading your drawing…'}</h3><p>${state.tab==='bom'?'Checking the worksheet and material rows.':'Finding material tables and matching spool numbers. Larger scans can take a little longer.'}</p><p class="sdoc-meta">${esc(draft.files.map(entry=>entry.file.name).join(' · ')||'Saved source document')}</p><p class="sdoc-meta">You can go Back while this is being read. Nothing is saved until you choose Save.</p></section>`;
  }
  function uploadReviewView(){
    if(state.package)return packageView();
    const draft=state.drafts.bom;if(!draft.preview)return uploadFilesView();
    return `<section class="sdoc-bom-review"><h3>Review your BOM</h3>${previewView(draft)}${draft.error?`<p class="sdoc-error" role="alert">${esc(draft.error)}</p>`:''}${saveNotes(draft)}<div class="sdoc-actions">${button('save',state.saving?'Saving…':'Save BOM','',true,busy()||draft.preview.sheet_required||draft.stale)}${button('back','Back to files','',false,state.saving)}</div></section>`;
  }
  function uploadedView(){
    const bom=state.data.active.bom,drawing=state.data.active.isometric,excel=fileUrl(bom?.excel_url);
    return `<section class="sdoc-uploaded"><h3>Your files are ready</h3><p>Open the saved files for this spool, or return to setup to continue.</p><div class="sdoc-actions">${bom?button('show-bom','View BOM','',true):''}${drawing?button('show-isometric','View isometric drawings'):''}${excel?`<a href="${esc(excel)}" download>Download Excel BOM</a>`:''}${button('upload-more','Upload more files')}</div></section>`;
  }
  function uploadView(){
    if(state.working)return processingView();
    if(state.step==='saved')return uploadedView();
    if(state.step==='review')return uploadReviewView();
    return uploadFilesView();
  }
  function editableRows(candidate,index){
    if(!candidate.expanded)return '';
    return `<div class="sdoc-table sdoc-edit-table" tabindex="0" role="region" aria-label="Materials for ${esc(candidate.spool_number||'unidentified spool')}"><table><caption>Quantities for one spool · Check the drawing table before saving</caption><thead><tr>${BOM_FIELDS.map(([,name])=>`<th scope="col">${esc(name)}</th>`).join('')}<th scope="col">Drawing page</th><th scope="col">Edit</th></tr></thead><tbody>${candidate.lines.map((line,row)=>`<tr>${BOM_FIELDS.map(([key,name])=>`<td class="sdoc-cell-${key}"><input type="text"${key==='quantity'?' inputmode="decimal"':''} value="${esc(line[key]??'')}" aria-label="${esc(name)} · line ${row+1} · ${esc(candidate.spool_number||'spool')}" data-sdoc-candidate="${index}" data-sdoc-row="${row}" data-sdoc-field="${key}" maxlength="${key==='notes'?2000:1000}"${busy()?' disabled':''}></td>`).join('')}<td>${esc(line.source_page??candidate.source_pages.join(', '))}</td><td>${button('remove-material','Remove',`data-sdoc-candidate="${index}" data-sdoc-row="${row}"`,false,busy())}</td></tr>`).join('')}</tbody></table></div><div class="sdoc-actions">${button('add-material','Add material line',`data-sdoc-candidate="${index}"`,false,busy()||candidate.lines.length>=(state.data.limits?.max_bom_lines||500))}</div>`;
  }
  function materialSummary(candidate){
    if(candidate.expanded)return '';
    return `<ul class="sdoc-material-preview">${candidate.lines.slice(0,3).map(row=>`<li><strong>${esc(row.quantity??'—')} ${esc(row.unit||'')}</strong><span>${esc(row.description||'Description needs review')}${row.part_number?`<small>Part ${esc(row.part_number)}</small>`:''}</span></li>`).join('')}</ul>${candidate.lines.length>3?`<p class="sdoc-meta">${candidate.lines.length-3} more material rows are available in Review / edit.</p>`:''}`;
  }
  function packageView(){
    const review=state.package;if(!review||state.tab!=='isometric')return '';
    if(!state.data.editable)return `<p class="sdoc-locked">${esc(state.data.locked_reason||'You can view these files. Your position cannot save revisions.')}</p>`;
    configurePackageReason();
    const p=review.data,draft=state.drafts.isometric,selected=selectedCandidates(review),physical=state.target.kind==='spools',sourceView=fileUrl(p.source.view_url),sourceKind=documentKind(review),bomOnly=sourceKind==='bom';
    return `<section class="sdoc-package" aria-labelledby="sdocPackageTitle"><span class="sdoc-eyebrow">${p.source.kind==='saved'?'From saved file':'Files read successfully'}</span><h3 id="sdocPackageTitle">Review detected files</h3><p><strong>${esc(p.source.filename)}</strong> · ${Number(p.source.page_count)||0} pages</p><p class="sdoc-detected"><strong>${sourceKind?(bomOnly?'BOM scan / PDF detected':'Isometric drawing detected'):'File type needs your choice'}</strong> · ${review.candidates.length} spool BOM${review.candidates.length===1?'':'s'} found</p><p>${physical?'These files apply to this unique physical spool. Other spool tables remain unselected until you choose assembly sharing.':(bomOnly?'The BOM source and a separate Excel BOM will be saved for each selected spool.':'The full drawing and a separate Excel BOM will be saved for each selected spool.')+' Copies with their own document revisions keep their individual versions.'}</p>${bomOnly?'<p class="sdoc-meta">An existing isometric drawing stays available. This upload updates the BOM.</p>':''}${!sourceKind&&review.candidates.length?`<p class="sdoc-warning">Check whether the source contains a drawing or only a bill of material.</p><div class="sdoc-actions">${button('classify-source','This is a drawing','data-sdoc-source-kind="isometric"',false,busy())}${button('classify-source','This is a BOM only','data-sdoc-source-kind="bom"',false,busy())}</div>`:''}${physical&&idOK(state.data.context.requirement_id)?`<div class="sdoc-share"><div><strong>Use these files for all corresponding spools</strong><p>Select the other matching spools in assembly setup. Your files and material edits carry over.</p></div>${button('use-assembly','Use for all assembly spools','',false,busy())}</div>`:''}${arr(p.warnings).map(w=>`<p class="sdoc-warning">${esc(w)}</p>`).join('')}${arr(p.unreadable_pages).length?`<p class="sdoc-warning">Check drawing pages ${esc(p.unreadable_pages.map(page=>typeof page==='object'?(page.page||page.page_number||'?'):page).join(', '))}: some material tables could not be read completely.</p>`:''}${arr(p.excluded_pages).length?`<p class="sdoc-meta">Pages without a usable spool BOM: ${esc(p.excluded_pages.map(page=>typeof page==='object'?(page.page||page.page_number||'?'):page).join(', '))}. Every uploaded page stays in the saved source PDF.</p>`:''}${!review.candidates.length?'<p class="sdoc-warning">No usable spool BOM was found. You can keep the uploaded pages as a drawing or BOM source. No Excel BOM will be created from unreadable rows.</p>':''}<div class="sdoc-candidates">${review.candidates.map((candidate,index)=>{
      const target=packageTarget(review,candidate),pages=candidate.source_pages,matched=candidate.assignment_basis!=='selected_scope'&&(candidate.matched_spool_id||candidate.matched_requirement_id||'')===candidate.target_id&&!!candidate.target_id,locked=target&&target.editable===false;
      return `<article class="sdoc-candidate${candidate.selected?' sdoc-candidate-selected':''}" data-sdoc-card="${index}"><div class="sdoc-candidate-heading"><label class="sdoc-check"><input type="checkbox" data-sdoc-select="${index}"${candidate.selected?' checked':''}${busy()||!target||locked?' disabled':''}><span>${esc(candidate.spool_number||'Spool number needs review')}</span></label><span class="sdoc-badge">${locked?'Locked':matched?'Spool found':candidate.target_id?'Assigned for review':'Needs assignment'}</span></div><p class="sdoc-meta">${candidate.lines.length} material line${candidate.lines.length===1?'':'s'} · Drawing page${pages.length===1?'':'s'} ${pages.map(page=>sourceView?`<a href="${esc(sourceView)}#page=${page}" target="_blank" rel="noopener noreferrer">${page}</a>`:String(page)).join(', ')||'not identified'}${candidate.drawing?' · '+esc(candidate.drawing):''}</p><div class="field"><label for="sdocTarget-${index}">${physical?'Unique spool receiving this BOM':bomOnly?'Spool receiving this BOM':'Spool receiving this BOM and full drawing'}</label><select id="sdocTarget-${index}" data-sdoc-target="${index}"${busy()?' disabled':''}><option value="">Choose a matching spool</option>${p.targets.map(item=>`<option value="${esc(packageTargetId(item))}"${candidate.target_id===packageTargetId(item)?' selected':''}${item.editable===false?' disabled':''}>${esc(item.spool_number)}${physical?' · '+esc(item.spool_id):''}${item.editable===false?' · locked':''}</option>`).join('')}</select></div>${!matched&&!candidate.target_id?'<p class="sdoc-warning">No exact match was found in this scope. Assign this table to the correct spool, or leave it unselected.</p>':''}${locked?`<p class="sdoc-locked">${esc(target.locked_reason||'This spool cannot be revised.')}</p>`:''}${target?.has_bom?'<p class="sdoc-meta">Saving creates a new BOM revision. The earlier BOM stays in History.</p>':''}${candidate.warnings.map(w=>`<p class="sdoc-warning">${esc(w)}</p>`).join('')}${materialSummary(candidate)}${button('toggle-materials',candidate.expanded?'Hide material rows':'Review / edit material rows',`data-sdoc-candidate="${index}" aria-expanded="${candidate.expanded}"`,false,busy())}${editableRows(candidate,index)}${candidate.review_required?`<label class="sdoc-check sdoc-review-check"><input type="checkbox" data-sdoc-reviewed="${index}"${candidate.reviewed?' checked':''}${busy()?' disabled':''}><span>I checked this spool assignment and material table against the drawing.</span></label>`:''}</article>`;
    }).join('')}</div>${review.error?`<p class="sdoc-error" role="alert">${esc(review.error)}</p>`:''}${review.stale?`<div class="sdoc-actions">${button('refresh-package','Refresh drawing review','',false,busy())}</div>`:''}${saveNotes(draft)}<p class="sdoc-package-count" role="status">${selected.length} spool${selected.length===1?'':'s'} selected · ${selected.length} separate Excel BOM${selected.length===1?'':'s'}</p><div class="sdoc-actions">${button('save-package',state.saving?'Saving…':`Save ${selected.length} spool${selected.length===1?'':'s'}`,'',true,busy()||review.stale||!selected.length||!sourceKind)}${p.source.kind==='upload'&&sourceKind!=='bom'?button('save-source-isometric',sourceKind?'Save drawing only':'Save as drawing','',false,busy()||draft.stale):''}${p.source.kind==='upload'&&sourceKind!=='isometric'?button('save-source-bom',sourceKind?'Save BOM reference only':'Save as BOM reference','',false,busy()||draft.stale):''}${button('back','Back to files','',false,state.saving)}</div><p class="sdoc-meta">Saving keeps previous document versions in History. Unselected tables are not turned into BOMs.</p></section>`;
  }
  function packageResultView(){
    const result=state.data?.package_result;if(!result||!result.count)return '';
    const records=[...arr(result.requirements).map(row=>({...row,scope:'requirements',identity:row.requirement_id})),...arr(result.spools).map(row=>({...row,scope:'spools',identity:row.spool_id}))];
    return `<section class="sdoc-package-result"><h3>Files saved by spool</h3>${arr(result.warnings).map(w=>`<p class="sdoc-warning">${esc(w)}</p>`).join('')}<ul>${records.map(row=>{const excel=fileUrl(row.bom_document?.excel_url)||fileUrl(row.bom_document?.download_url);return `<li><strong>${esc(row.spool_number)}</strong><div class="sdoc-actions">${excel?`<a href="${esc(excel)}" download>Download Excel BOM</a>`:''}${link(row.scope,row.identity,row.spool_number,'View spool documents','bom')}</div></li>`;}).join('')}</ul></section>`;
  }
  function uploadForm(){
    const d=state.data,draft=state.drafts[state.tab],drawing=state.tab==='isometric',saved=d.active[state.tab],limits=d.limits||{},editable=d.editable&&d.permissions?.can_upload!==false;
    if(!editable)return `<p class="sdoc-locked">${esc(d.locked_reason||'Your position can view these documents. An employee with upload permission can add or revise them.')}</p>`;
    const open=!saved||draft.expanded||draft.files.length>0,hasPackage=drawing&&!!state.package;
    return `<details class="sdoc-upload"${open?' open':''}><summary>${saved?'Upload a new '+(drawing?'drawing revision':'BOM revision'):'Upload '+(drawing?'isometric drawings':'bill of material')}</summary><div class="sdoc-upload-inner"><p>${drawing?'Choose the full PDF from your computer or scanner. FabTrace reads the spool material tables so you can review and save separate Excel BOMs. On a phone, add each page with the camera, then arrange the files in drawing-page order.':'Choose an image, PDF, Excel or CSV. Images and PDFs are read automatically so drawings and BOMs can be saved separately.'}</p><div class="sdoc-actions"><label class="sdoc-file-button" for="sdocFileInput">Choose drawing, scan or BOM<input id="sdocFileInput" type="file" accept="${UPLOAD_ACCEPT}" multiple${busy()?' disabled':''}></label>${drawing?`<label class="sdoc-file-button" for="sdocCameraInput">Scan a page with camera<input id="sdocCameraInput" type="file" accept="image/jpeg,image/png" capture="environment"${busy()?' disabled':''}></label>`:button('template','Download BOM template','',false,busy())}</div><p class="sdoc-meta">${limits.max_total_bytes?'Up to '+bytes(limits.max_total_bytes)+' per upload. ':''}${drawing?'Add every drawing page; more pages can be added before saving.':'BOM quantities must be for one spool. Files are linked only to the selected spool scope.'}</p>${filesView(draft)}${!drawing&&draft.files.some(entry=>/\.xlsx$/i.test(entry.file.name))?`<div class="field"><label for="sdocSheet">Worksheet name (if the workbook has multiple sheets)</label><input id="sdocSheet" value="${esc(draft.sheet)}" maxlength="100" autocomplete="off" placeholder="Preview to see available worksheets"${busy()?' disabled':''}></div>`:''}${draft.error?`<div class="sdoc-error" role="alert"><p>${esc(draft.error)}</p>${draft.stale?button('reload','Reload saved documents','',false,busy()):''}</div>`:''}${!hasPackage?previewView(draft)+reviewFields(draft):''}<div class="sdoc-actions">${button('preview',state.working?(drawing?'Reading drawing tables…':'Checking files…'):drawing?'Find spool BOMs / preview':'Preview selected files','',false,busy()||!draft.files.length)}${!hasPackage?button('save',state.saving?'Saving…':'Save '+(drawing?'isometric drawings':'BOM'),'',true,busy()||!draft.preview||draft.preview.sheet_required||draft.stale):''}</div><p class="sdoc-meta">Previewing does not save a file. Saving keeps prior versions available in History.</p></div></details>`;
  }
  function historyView(){
    if(!state.data.history.length)return '<section class="sdoc-empty"><h3>No upload history yet</h3><p>Saved files and prior revisions will appear here.</p></section>';
    return `<div class="sdoc-history">${state.data.history.map(doc=>`<article><div class="sdoc-saved-title"><div><span class="sdoc-eyebrow">${esc(label(doc.kind))}${doc.inherited?' · From assembly setup':''}</span><h3>${esc(doc.filename)}</h3></div><span class="sdoc-badge">${doc.revision?'Revision '+esc(doc.revision):'Version '+doc.version}</span></div><p class="sdoc-meta">${esc(doc.uploaded_by||'—')} · ${esc(doc.uploaded_at?new Date(doc.uploaded_at).toLocaleString():'')}${doc.page_count?' · '+doc.page_count+' pages':''}</p><p>${esc(doc.reason||'')}</p>${documentActions(doc)}${state.viewer===doc.id&&doc.bom?table(doc.bom,'Historical BOM'):state.viewer===doc.id&&fileUrl(doc.view_url)&&doc.media_type==='application/pdf'?`<div class="sdoc-viewer"><iframe src="${esc(fileUrl(doc.view_url))}" title="Previous ${esc(label(doc.kind).toLowerCase())}"></iframe></div>`:''}</article>`).join('')}</div>`;
  }
  function render(){
    node('spoolDocumentsSubtitle').textContent=state.data?'Spool '+state.data.context.spool_number:state.target?.spool_number?'Spool '+state.target.spool_number:'';
    window.FabFlowStatus?.decorateSpool(node('spoolDocumentsSubtitle'),spoolRecord(state.data),node('spoolDocumentsSubtitle').textContent);
    node('spoolDocumentsClose').disabled=state.saving||pieceSaving();node('spoolDocumentsDone').disabled=state.saving||pieceSaving();node('spoolDocumentsBack').disabled=state.saving||pieceSaving();
    node('spoolDocumentsDone').textContent=state.target?.kind==='requirements'?'Return to setup':'Return to spool';
    const content=node('spoolDocumentsContent');content.setAttribute('aria-busy',String(busy()));
    if(state.loading&&!state.data){window.FabDocumentPieceQa?.unmount();content.innerHTML='<p class="sdoc-loading" role="status">Loading spool documents…</p>';return;}
    if(state.error&&!state.data){window.FabDocumentPieceQa?.unmount();content.innerHTML=`<div class="sdoc-error" role="alert"><p>${esc(state.error)}</p>${button('reload','Try again')}</div>`;return;}
    if(!state.data){window.FabDocumentPieceQa?.unmount();content.innerHTML='';return;}
    const saved=state.data.active.bom||state.data.active.isometric,showTabs=saved||state.view==='saved',active=state.view==='upload'?'upload':state.tab;
    const tabs=[...(state.data.permissions?.can_upload!==false?[['upload','Upload files']]:[]),['bom','BOM'],['isometric','Drawings']];
    const tabbar=showTabs?`<div class="sdoc-file-nav"><div class="sdoc-tabs" role="tablist" aria-label="Spool files">${tabs.map(([kind,caption])=>`<button id="sdoc-tab-${kind}" type="button" role="tab" aria-selected="${active===kind}" aria-controls="sdocPanel" tabindex="${active===kind?0:-1}" data-sdoc-tab-choice="${kind}"${busy()?' disabled':''}>${esc(caption)}</button>`).join('')}</div>${state.data.history.length?`<button id="sdoc-tab-history" class="sdoc-history-link" type="button" data-sdoc-tab-choice="history"${busy()?' disabled':''}>History</button>`:''}</div>`:'';
    const panel=state.view==='upload'?uploadView():state.tab==='history'?historyView():savedDocument()+uploadForm();
    content.innerHTML=contextView()+tabbar+`${state.notice?`<p class="sdoc-notice" role="status">${esc(state.notice)}</p>`:''}${state.error?`<p class="sdoc-error" role="alert">${esc(state.error)}</p>`:''}${state.view==='upload'&&state.step==='saved'?packageResultView():''}<div id="sdocPanel"${showTabs?' role="tabpanel" aria-labelledby="sdoc-tab-'+active+'"':' aria-label="Upload files"'}>${panel}</div>`;
    const files=node('sdocFileInput');if(files)files.onchange=()=>addFiles([...files.files]);
    const camera=node('sdocCameraInput');if(camera)camera.onchange=()=>addFiles([...camera.files]);
    for(const [id,key] of [['sdocRevision','revision'],['sdocReason','reason'],['sdocSheet','sheet']]){const input=node(id);if(input)input.oninput=()=>{const draft=state.drafts[state.tab==='isometric'?'isometric':'bom'];draft[key]=input.value;if(key==='reason')draft.reasonAutomatic=false;if(key==='sheet'){invalidatePreview(draft);const save=content.querySelector('[data-sdoc-action="save"]');if(save)save.disabled=true;}};}
    const sheet=node('sdocSheetChoice');if(sheet)sheet.onchange=()=>{const draft=state.drafts.bom;draft.sheet=sheet.value;invalidatePreview(draft);if(draft.sheet)preview();else render();};
    const mode=node('sdocSourceMode');if(mode)mode.onchange=()=>{state.sourceMode=mode.value;invalidatePreview(state.drafts.isometric);if(state.tab==='isometric'&&state.drafts.isometric.files.length)scheduleAnalysis();else render();};
    const grid=node('sdocSavedGrid'),doc=state.data.active.bom;
    if(grid&&state.view==='saved'&&state.tab==='bom'&&doc?.bom){
      if(window.FabDocumentPieceQa)window.FabDocumentPieceQa.mount({host:grid,target:state.target,document:doc,context:state.data.context,busy:state.loading||state.working||state.saving,onBusyChange:()=>{if(dialog.open)render();},reloadDocuments:load});
      else grid.innerHTML='<p class="sdoc-warning">Individual material records could not be loaded. Reload this page to view the BOM pieces and QA-001 controls.</p>';
    }else window.FabDocumentPieceQa?.unmount();
  }
  function cancelScheduledAnalysis(){if(state.scanTimer){clearTimeout(state.scanTimer);state.scanTimer=null;}}
  function scheduleAnalysis(previous=null,kind='isometric'){
    cancelScheduledAnalysis();if(!state.drafts[kind].files.length)return;
    const sequence=state.sequence;state.scanTimer=setTimeout(()=>{state.scanTimer=null;if(sequence===state.sequence&&dialog.open&&state.tab===kind&&!busy()){if(kind==='isometric')previewDrawing('',previous);else preview();}},350);render();
  }
  function addFiles(files,options={}){
    if(busy()||!state.data?.editable||!files.length)return;
    cancelScheduledAnalysis();
    const drawing=files.every(file=>/\.(pdf|jpe?g|png)$/i.test(file.name)),spreadsheet=files.length===1&&/\.(xlsx|csv|tsv)$/i.test(files[0].name);
    if(!drawing&&!spreadsheet){state.error='Choose drawing PDFs and photos together, or one Excel / CSV BOM.';render();return;}
    const kind=drawing?'isometric':'bom',draft=state.drafts[kind],limits=state.data.limits||{},sameKind=state.tab===kind;
    let chosen=drawing&&sameKind?[...draft.files]:[];
    for(const file of files){
      if(!file.size){state.error='Empty files cannot be uploaded.';render();return;}
      if(limits.max_file_bytes&&file.size>limits.max_file_bytes){state.error=file.name+' exceeds the '+bytes(limits.max_file_bytes)+' file limit.';render();return;}
      if(!chosen.some(entry=>entry.file.name===file.name&&entry.file.size===file.size&&entry.file.lastModified===file.lastModified))chosen.push({file,url:null});
    }
    if((limits.max_files&&chosen.length>limits.max_files)||(limits.max_total_bytes&&chosen.reduce((n,entry)=>n+entry.file.size,0)>limits.max_total_bytes)){state.error='The selected files exceed the upload limit. Use fewer or smaller files.';render();return;}
    if(!drawing||!sameKind)clearDraft(draft);
    if(!sameKind){const other=kind==='bom'?'isometric':'bom';clearDraft(state.drafts[other]);state.drafts[other]=fresh();state.package=null;}
    for(const entry of chosen)if(!entry.url&&/\.(jpe?g|png)$/i.test(entry.file.name))entry.url=URL.createObjectURL(entry.file);
    draft.files=chosen;draft.sheet='';draft.expanded=true;invalidatePreview(draft);if(!drawing){draft.requiresReason=!!state.data.active.bom;if(!draft.requiresReason&&!draft.reason){draft.reason='Initial BOM from uploaded material list';draft.reasonAutomatic=true;}}
    state.tab=kind;state.uploadKind=kind;state.view='upload';state.step='files';state.error='';state.notice='';state.viewer=null;render();
    if(options.analyze!==false)scheduleAnalysis(options.previous||null,kind);
  }
  function multipart(kind,draft,save=false){
    const form=new FormData();form.append('kind',kind);for(const entry of draft.files)form.append('files',entry.file,entry.file.name);if(draft.sheet.trim())form.append('sheet',draft.sheet.trim());
    if(save){form.append('expected_version',String(state.data.version));form.append('expected_sha256',draft.preview.selection_sha256);form.append('revision',draft.revision.trim());form.append('reason',draft.reason.trim());}return form;
  }
  function acceptPackage(data,previous=null){
    const c=data?.context,t=state.target;
    if(!c||!t||c.kind!==(t.kind==='spools'?'spool':'requirement')||(t.kind==='spools'?c.item_id:c.requirement_id)!==t.id||!data.source||!['upload','saved'].includes(data.source.kind)||typeof data.preview_token!=='string'||!data.preview_token||!Array.isArray(data.targets)||!Array.isArray(data.candidates))throw Error('The drawing review did not match this spool. Reopen the spool and try again.');
    if(data.source.kind==='upload'&&!/^[a-f0-9]{64}$/i.test(data.source.selection_sha256||''))throw Error('The selected drawing files could not be verified. Choose them again.');
    if(data.targets.some(target=>!idOK(packageTargetId(target))||!Number.isInteger(target.version)||target.version<0||typeof target.editable!=='boolean'))throw Error('The drawing destinations could not be verified. Refresh the review.');
    const candidates=data.candidates.map((candidate,index)=>{
      if(typeof candidate.candidate_id!=='string'||!Array.isArray(candidate.lines))throw Error('A drawing material table could not be verified. Preview the file again.');
      const targetId=candidate.matched_spool_id||candidate.matched_requirement_id||'',target=data.targets.find(row=>packageTargetId(row)===targetId),old=previous?.data.source.sha256===data.source.sha256?previous.candidates.find(row=>row.candidate_id===candidate.candidate_id):null;
      const retained=old&&data.targets.find(row=>packageTargetId(row)===old.target_id);
      return {...candidate,source_pages:arr(candidate.source_pages).map(Number).filter(page=>Number.isInteger(page)&&page>0),warnings:[...new Set([...arr(candidate.warnings),...arr(candidate.validation_errors)].map(warning=>typeof warning==='string'?warning:warning.message||warning.detail||'Review the unreadable material fields against the drawing.'))],lines:old?.edited?old.lines.map(line=>({...line})):candidate.lines.map(line=>({...line})),target_id:retained?old.target_id:targetId,selected:retained?old.selected&&retained.editable:!!candidate.selected&&!!target?.editable,reviewed:old?.reviewed??!candidate.review_required,review_required:old?.review_required||!!candidate.review_required,expanded:old?.expanded??arr(candidate.validation_errors).length>0,edited:!!old?.edited};
    });
    state.package={data,candidates,error:'',stale:false};
    const draft=state.drafts.isometric;
    if(data.source.kind==='upload'){
      draft.preview={kind:'isometric',selection_sha256:data.source.selection_sha256,page_count:data.source.page_count};
    }
    draft.stale=false;
  }
  async function previewDrawing(documentId='',previous=null){
    if(busy()||!state.data?.editable)return;
    cancelScheduledAnalysis();
    const draft=state.drafts.isometric;if(!documentId&&!draft.files.length)return;
    if(documentId&&!idOK(documentId))return;
    state.tab='isometric';state.uploadKind='isometric';state.view='upload';state.step='reading';state.working=true;state.notice='';draft.error='';state.error='';const sequence=state.sequence;
    state.controller=new AbortController();render();
    const form=new FormData();form.append('source_mode',state.sourceMode);if(documentId)form.append('document_id',documentId);else for(const entry of draft.files)form.append('files',entry.file,entry.file.name);
    try{
      const data=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/isometric-preview',{method:'POST',body:form,signal:state.controller.signal});
      if(sequence!==state.sequence||!dialog.open)return;
      acceptPackage(data,previous);
      state.step='review';
      configurePackageReason();
      if(!draft.revision.trim())draft.revision=data.candidates.find(candidate=>candidate.revision)?.revision||'';
      if(previous?.candidates.some(candidate=>candidate.edited))state.notice='Drawing review refreshed. Edited material rows have been kept.';
    }catch(error){if(sequence===state.sequence&&error.name!=='AbortError'){state.step=state.package?'review':'files';if(state.package)state.package.error=errorText(error);else draft.error=errorText(error);}}
    finally{if(sequence===state.sequence){state.working=false;state.controller=null;render();if(state.package)node('sdocPackageTitle')?.scrollIntoView({block:'start'});}}
  }
  async function useAssembly(){
    const c=state.data?.context;if(busy()||state.target?.kind!=='spools'||!idOK(c?.requirement_id))return;
    const previous=state.package,draft=state.drafts.isometric,source=previous?.data.source,files=source?.kind==='saved'?[]:draft.files.map(entry=>entry.file),savedId=source?.kind==='saved'?source.document_id:state.view==='saved'&&state.tab==='isometric'?state.data.active.isometric?.id:null;
    const carried={revision:draft.revision,reason:draft.reason,reasonAutomatic:draft.reasonAutomatic,requiresReason:draft.requiresReason},mode=source?.source_mode||state.sourceMode,trigger=state.trigger;
    await open({kind:'requirements',id:c.requirement_id,spool_number:c.spool_number,tab:'upload',fresh:true},trigger);
    if(!state.data||state.target?.id!==c.requirement_id)return;
    Object.assign(state.drafts.isometric,carried);
    state.sourceMode=mode;
    if(files.length){addFiles(files,{analyze:false});await previewDrawing('',previous);}
    else if(savedId)await previewDrawing(savedId,previous);
  }
  async function savePackage(){
    const review=state.package;if(busy()||!state.data?.editable||!review||review.stale)return;
    review.sourceOnlyKind=null;configurePackageReason();
    const draft=state.drafts.isometric,selected=selectedCandidates(review);review.error='';
    const fail=message=>{review.error=message;render();};
    if(!selected.length)return fail('Select at least one spool to receive its drawing and Excel BOM.');
    if(!documentKind(review))return fail('Choose whether the source is a drawing or a BOM before saving.');
    if(draft.reason.trim().length<4)return fail('Enter a reason for saving these drawing and BOM revisions (at least 4 characters).');
    const used=new Set(),mappings=[];
    for(const candidate of selected){
      const target=packageTarget(review,candidate),number=candidate.spool_number||'This material table';
      if(!target||!target.editable)return fail(number+': choose an editable spool in this scope.');
      if(used.has(candidate.target_id))return fail('More than one table is assigned to '+target.spool_number+'. Select one reviewed BOM for each spool.');
      used.add(candidate.target_id);
      if(candidate.review_required&&!candidate.reviewed)return fail(number+': check the drawing and confirm the material table before saving.');
      if(!candidate.lines.length)return fail(number+': add at least one material line.');
      const itemNumbers=new Set();
      for(let index=0;index<candidate.lines.length;index++){
        const row=candidate.lines[index],quantity=Number(row.quantity);
        const item=String(row.item??'').trim();
        if(!item||!String(row.description||'').trim()||!Number.isFinite(quantity)||quantity<=0||quantity>100000000)return fail(number+', line '+(index+1)+': enter the item number, description and a positive numeric quantity.');
        if(itemNumbers.has(item))return fail(number+': item number '+item+' appears more than once. Check each material row against the drawing.');
        itemNumbers.add(item);
      }
      mappings.push({candidate_id:candidate.candidate_id,...(target.spool_id?{spool_id:target.spool_id}:{requirement_id:target.requirement_id}),expected_version:target.version,lines:candidate.lines.map(row=>({...row,quantity:Number(row.quantity)}))});
    }
    const reviewJson=JSON.stringify({preview_token:review.data.preview_token,reviewed:true,revision:draft.revision.trim(),reason:draft.reason.trim(),mappings});
    if(new Blob([reviewJson]).size>MAX_REVIEW_BYTES)return fail('This review is too large. Select fewer spools or upload a smaller drawing set.');
    const form=new FormData();form.append('review',reviewJson);
    if(review.data.source.kind==='upload')for(const entry of draft.files)form.append('files',entry.file,entry.file.name);
    const sequence=state.sequence;state.saving=true;state.notice='';render();
    try{
      const result=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/isometric-import',{method:'POST',body:form});
      if(sequence!==state.sequence||!dialog.open)return;
      if(!valid(result)||!Number.isInteger(result.package_result?.count)||result.package_result.count<1)throw Error('The saved drawing package could not be verified. Reload the spool documents before saving again.');
      const sourceKind=documentKind(review);
      state.data=result;state.package=null;clearDraft(draft);state.drafts.isometric=fresh();state.view='upload';state.step='saved';state.path=[];state.sourceMode='auto';state.notice=(sourceKind==='bom'?'BOM source':'Full drawing')+' and '+result.package_result.count+' separate Excel BOM'+(result.package_result.count===1?'':'s')+' saved.';
      for(const [scope,rows] of [['requirements',result.package_result.requirements],['spools',result.package_result.spools]])for(const row of arr(rows))for(const kind of arr(row.saved_kinds).filter(kind=>['bom','isometric'].includes(kind)))document.dispatchEvent(new CustomEvent('fabtrace:spool-documents-saved',{detail:{kind:scope,id:scope==='requirements'?row.requirement_id:row.spool_id,document_kind:kind,data:result}}));
    }catch(error){if(sequence===state.sequence){review.error=errorText(error);review.stale=error.status===409||!error.status;draft.stale=review.stale;if(review.stale)review.error+=' Refresh the drawing review before trying again; the previous request may already have been saved.';}}
    finally{if(sequence===state.sequence){state.saving=false;render();}}
  }
  async function preview(){
    if(busy()||!state.data?.editable||state.tab==='history')return;
    if(state.tab==='isometric')return previewDrawing();
    const kind=state.tab,draft=state.drafts[kind];if(!draft.files.length)return;
    const sequence=state.sequence;state.view='upload';state.step='reading';state.working=true;draft.error='';draft.preview=null;state.notice='';state.controller=new AbortController();render();
    try{const p=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/preview',{method:'POST',body:multipart(kind,draft),signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(p.kind!==kind||(!p.sheet_required&&!/^[a-f0-9]{64}$/i.test(p.selection_sha256||'')))throw Error('The file preview could not be verified. Select the file again.');draft.preview=p;draft.stale=false;state.step='review';}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError'){draft.error=errorText(error);state.step='files';}}
    finally{if(sequence===state.sequence){state.working=false;state.controller=null;render();}}
  }
  async function save(){
    if(busy()||!state.data?.editable||state.tab==='history')return;
    const kind=state.tab,draft=state.drafts[kind];if(!draft.preview||draft.preview.sheet_required||draft.stale)return;
    if(draft.reason.trim().length<4){draft.error='Enter a reason for this upload (at least 4 characters).';render();node('sdocReason')?.focus();return;}
    const sequence=state.sequence;state.saving=true;state.error='';state.notice='';draft.error='';render();
    try{const result=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/upload',{method:'POST',body:multipart(kind,draft,true)});if(sequence!==state.sequence||!dialog.open)return;if(!valid(result))throw Error('The saved response did not match this spool. Reload saved documents before continuing.');state.data=result;if(kind==='isometric')state.package=null;clearDraft(draft);state.drafts[kind]=fresh();state.view='upload';state.step='saved';state.path=[];state.sourceMode='auto';state.notice=label(kind)+' saved for '+result.context.spool_number+'.'+(kind==='isometric'?' No Excel BOM was created.':'');document.dispatchEvent(new CustomEvent('fabtrace:spool-documents-saved',{detail:{kind:state.target.kind,id:state.target.id,document_kind:kind,data:result}}));}
    catch(error){if(sequence===state.sequence){draft.error=errorText(error);draft.stale=error.status===409||!error.status;if(draft.stale)draft.error+=' Reload saved documents before trying another upload; the previous request may have been saved.';}}
    finally{if(sequence===state.sequence){state.saving=false;render();}}
  }
  async function saveSource(kind){
    const review=state.package,draft=state.drafts.isometric;
    if(busy()||!state.data?.editable||!review||review.data.source.kind!=='upload'||!draft.files.length||!['bom','isometric'].includes(kind))return;
    review.sourceOnlyKind=kind;configurePackageReason();
    if(draft.reason.trim().length<4){review.error='Enter a save note of at least 4 characters.';render();node('sdocReason')?.closest('details')?.setAttribute('open','');return;}
    const sequence=state.sequence,version=state.data.version;state.saving=true;review.error='';render();
    try{
      const checked=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/preview',{method:'POST',body:multipart(kind,draft)});
      if(sequence!==state.sequence||!dialog.open)return;
      if(checked.kind!==kind||!/^[a-f0-9]{64}$/i.test(checked.selection_sha256||''))throw Error('The source file could not be verified. Read the files again.');
      const form=multipart(kind,draft);form.append('expected_version',String(version));form.append('expected_sha256',checked.selection_sha256);form.append('revision',draft.revision.trim());form.append('reason',draft.reason.trim());
      const result=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/upload',{method:'POST',body:form});
      if(sequence!==state.sequence||!dialog.open)return;
      if(!valid(result))throw Error('The saved source did not match this spool. Reload saved files before trying again.');
      state.data=result;state.package=null;clearDraft(draft);state.drafts.isometric=fresh();state.tab=kind;state.view='upload';state.step='saved';state.path=[];state.sourceMode='auto';state.notice=(kind==='bom'?'BOM source':'Drawing')+' saved. No Excel BOM was created.';
      document.dispatchEvent(new CustomEvent('fabtrace:spool-documents-saved',{detail:{kind:state.target.kind,id:state.target.id,document_kind:kind,data:result}}));
    }catch(error){if(sequence===state.sequence){review.error=errorText(error);review.stale=error.status===409||!error.status;draft.stale=review.stale;}}
    finally{if(sequence===state.sequence){state.saving=false;render();}}
  }
  async function load(){
    if(!state.target||state.saving||pieceSaving())return;window.FabDocumentPieceQa?.unmount();state.controller?.abort();const sequence=++state.sequence;state.controller=new AbortController();state.loading=true;state.error='';state.working=false;render();
    try{const d=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id),{signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(!valid(d))throw Error('The documents returned do not match this spool. Reopen the spool and try again.');state.data=d;state.package=null;if(d.permissions?.can_upload===false&&state.view==='upload'){state.view='saved';state.tab=d.active.bom?'bom':d.active.isometric?'isometric':'bom';}for(const draft of Object.values(state.drafts)){draft.stale=false;draft.preview=null;draft.error='';}}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError')state.error=errorText(error);}
    finally{if(sequence===state.sequence){state.loading=false;state.controller=null;render();}}
  }
  async function open(target,trigger=document.activeElement){
    if(!me||state.saving||pieceSaving()||!target||!['spools','requirements'].includes(target.kind)||!idOK(target.id))return;
    if(!target.fresh&&state.resume?.badge===me.badge&&state.resume.target.kind===target.kind&&state.resume.target.id===target.id){
      const snapshot={...state.resume,open:true};
      if(['bom','isometric','history'].includes(target.tab))Object.assign(snapshot,{view:'saved',tab:target.tab,viewer:null,path:[]});
      return restoreNavigation(snapshot);
    }
    window.FabDocumentPieceQa?.reset();cancelScheduledAnalysis();state.controller?.abort();state.sequence++;clearDrafts();state.package=null;state.resume=null;state.path=[];state.sourceMode='auto';state.uploadKind='bom';state.step='files';state.target={kind:target.kind,id:target.id,spool_number:target.spool_number||''};state.view=['bom','isometric','history'].includes(target.tab)?'saved':'upload';state.tab=['bom','isometric','history'].includes(target.tab)?target.tab:'bom';state.data=null;state.error='';state.notice='';state.viewer=null;state.trigger=trigger;state.working=false;
    if(!dialog.open)dialog.showModal();node('spoolDocumentsClose').focus();await load();
  }
  function close(force=false,preserve=false){
    if((state.saving||pieceSaving())&&!force)return;const trigger=state.trigger,snapshot=preserve?navigationState():null;window.FabDocumentPieceQa?.reset();cancelScheduledAnalysis();state.sequence++;state.controller?.abort();state.controller=null;state.loading=false;state.working=false;state.saving=false;clearDrafts();state.package=null;state.target=null;state.data=null;state.viewer=null;state.error='';state.notice='';state.trigger=null;state.path=[];state.resume=snapshot?{...snapshot,open:false}:null;
    if(dialog.open)dialog.close();if(!force&&trigger?.isConnected)trigger.focus();
  }
  function navigate(tab,remember=true){
    if(busy()||!['upload','bom','isometric','history'].includes(tab))return;
    cancelScheduledAnalysis();
    if(remember)state.path.push({view:state.view,tab:state.tab,step:state.step,viewer:state.viewer});
    state.viewer=null;
    if(tab==='upload'){state.view='upload';state.tab=state.package?'isometric':state.uploadKind;state.step=state.package||state.drafts[state.tab]?.preview?'review':'files';}
    else{state.view='saved';state.tab=tab;}
    render();node('sdoc-tab-'+tab)?.focus();
  }
  function back(){
    if(!dialog.open)return false;
    if(state.saving||pieceSaving())return true;
    if(state.working||state.scanTimer){cancelScheduledAnalysis();state.controller?.abort();state.sequence++;state.controller=null;state.working=false;state.view='upload';state.step='files';render();return true;}
    if(state.viewer){state.viewer=null;render();return true;}
    if(state.view==='upload'&&['reading','review','saved'].includes(state.step)){state.tab=state.uploadKind;state.step='files';render();return true;}
    const previous=state.path.pop();if(previous){Object.assign(state,previous);render();return true;}
    if(state.view==='saved'&&state.data?.permissions?.can_upload!==false){state.view='upload';state.tab=state.package?'isometric':state.uploadKind;state.step='files';render();return true;}
    close(false,true);return true;
  }
  const clonePlain=value=>value==null?value:JSON.parse(JSON.stringify(value));
  function cloneDraft(draft){return {...draft,preview:clonePlain(draft.preview),files:draft.files.map(entry=>({file:entry.file,url:null}))};}
  function navigationState(){
    if(!me?.badge)return null;
    if(!dialog.open||!state.target)return state.resume?.badge===me.badge?state.resume:null;
    return {format:1,badge:me.badge,open:true,target:{...state.target},view:state.view,tab:state.tab,uploadKind:state.uploadKind,step:state.step,sourceMode:state.sourceMode,path:clonePlain(state.path),data:clonePlain(state.data),drafts:{bom:cloneDraft(state.drafts.bom),isometric:cloneDraft(state.drafts.isometric)},package:clonePlain(state.package),viewer:state.viewer,notice:state.notice,error:state.error,pendingSave:state.saving,pieceQa:window.FabDocumentPieceQa?.snapshot()||null};
  }
  async function restoreNavigation(snapshot){
    if(!snapshot||snapshot.format!==1||snapshot.badge!==me?.badge||state.saving||pieceSaving()||!idOK(snapshot.target?.id)||!['requirements','spools'].includes(snapshot.target.kind))return false;
    if(!snapshot.open){state.resume=snapshot;return true;}
    await open({...snapshot.target,tab:'upload',fresh:true});
    if(!state.data||state.target?.id!==snapshot.target.id||state.target?.kind!==snapshot.target.kind){state.resume=snapshot;return false;}
    const changed=snapshot.pendingSave||snapshot.data?.version!==state.data.version;
    clearDrafts();state.drafts={bom:cloneDraft(snapshot.drafts.bom),isometric:cloneDraft(snapshot.drafts.isometric)};
    for(const draft of Object.values(state.drafts))for(const entry of draft.files)if(/\.(jpe?g|png)$/i.test(entry.file.name))entry.url=URL.createObjectURL(entry.file);
    state.package=clonePlain(snapshot.package);state.view=snapshot.view;state.tab=snapshot.tab;state.uploadKind=snapshot.uploadKind||'bom';state.step=snapshot.step==='reading'?'files':snapshot.step;state.sourceMode=snapshot.sourceMode||'auto';state.path=clonePlain(snapshot.path)||[];state.viewer=snapshot.viewer;state.notice=snapshot.notice||'';state.error=snapshot.error||'';
    if(changed){for(const draft of Object.values(state.drafts)){draft.stale=true;draft.error='Saved files changed while you were away. Review your selected files again before saving.';}if(state.package){state.package.stale=true;state.package.error='Saved files changed while you were away. Refresh this review before saving; your material edits are retained.';}}
    if(!state.data.editable&&state.view==='upload'){state.view='saved';state.tab=state.data.active.bom?'bom':'isometric';}
    window.FabDocumentPieceQa?.restore(snapshot.pieceQa);state.resume=null;render();return true;
  }
  function template(){
    const content='spool_number,item,quantity,unit,part_number,description,size,material,length,notes,drawing,revision,source_page\r\n';
    const url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'})),anchor=document.createElement('a');anchor.href=url;anchor.download='FabTrace_Spool_BOM_Template.csv';document.body.appendChild(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
  }
  dialog.addEventListener('click',event=>{
    const tab=event.target.closest('[data-sdoc-tab-choice]');if(tab&&!busy())return navigate(tab.dataset.sdocTabChoice);
    const target=event.target.closest('[data-sdoc-action]');if(!target||target.disabled||pieceSaving())return;const action=target.dataset.sdocAction;
    if(action==='reload')return load();if(action==='template')return template();if(action==='preview')return preview();if(action==='save')return save();
    if(action==='back')return back();
    if(action==='show-bom')return navigate('bom');
    if(action==='show-isometric')return navigate('isometric');
    if(action==='upload-more'){state.view='upload';state.tab=state.uploadKind;state.step='files';state.notice='';render();return;}
    if(action==='continue-review'){state.view='upload';state.tab=state.package?'isometric':state.uploadKind;state.step='review';render();return;}
    if(action==='clear-files'){if(!busy()){cancelScheduledAnalysis();clearDrafts();state.package=null;state.sourceMode='auto';state.tab='bom';state.uploadKind='bom';state.step='files';state.error='';render();}return;}
    if(action==='save-source-bom')return saveSource('bom');
    if(action==='save-source-isometric')return saveSource('isometric');
    if(action==='classify-source'){const review=state.package;if(review){state.sourceMode=target.dataset.sdocSourceKind;return previewDrawing(review.data.source.kind==='saved'?review.data.source.document_id:'',review);}return;}
    if(action==='use-assembly')return useAssembly();
    if(action==='create-boms'){state.sourceMode=target.dataset.sdocSourceKind==='bom'?'bom':'auto';return previewDrawing(target.dataset.sdocDocument);}
    if(action==='save-package')return savePackage();
    if(action==='refresh-package'){const review=state.package;if(review)return previewDrawing(review.data.source.kind==='saved'?review.data.source.document_id:'',review);return;}
    if(action==='cancel-package')return back();
    if(['toggle-materials','add-material','remove-material'].includes(action)){
      if(busy()||!state.package)return;const index=Number(target.dataset.sdocCandidate),candidate=state.package.candidates[index];if(!candidate)return;
      if(action==='toggle-materials')candidate.expanded=!candidate.expanded;
      if(action==='add-material'&&candidate.lines.length<(state.data.limits?.max_bom_lines||500)){candidate.lines.push({item:'',quantity:'',unit:'EA',description:'',source_page:candidate.source_pages[0]||''});candidate.edited=true;candidate.reviewed=false;}
      if(action==='remove-material'){const row=Number(target.dataset.sdocRow);if(Number.isInteger(row)&&row>=0&&row<candidate.lines.length){candidate.lines.splice(row,1);candidate.edited=true;candidate.reviewed=false;}}
      state.package.error='';render();return;
    }
    if(action==='preview-saved'||action==='view-grid'){state.viewer=target.dataset.sdocDocument;render();if(state.tab!=='history'&&action==='view-grid')node('sdocSavedGrid')?.scrollIntoView({block:'nearest'});return;}
    if(busy()||state.tab==='history')return;const draft=state.drafts[state.tab],index=Number(target.dataset.sdocIndex);if(!Number.isInteger(index)||index<0||index>=draft.files.length)return;
    if(action==='remove-file'){const [entry]=draft.files.splice(index,1);if(entry.url)URL.revokeObjectURL(entry.url);}
    if(action==='move-up'&&index>0)[draft.files[index-1],draft.files[index]]=[draft.files[index],draft.files[index-1]];
    if(action==='move-down'&&index<draft.files.length-1)[draft.files[index+1],draft.files[index]]=[draft.files[index],draft.files[index+1]];
    invalidatePreview(draft);state.view='upload';state.step='files';render();if(state.tab==='isometric'&&draft.files.length)scheduleAnalysis();
  });
  dialog.addEventListener('input',event=>{
    const input=event.target.closest('[data-sdoc-field]');if(!input||busy()||!state.package)return;
    const candidate=state.package.candidates[Number(input.dataset.sdocCandidate)],row=candidate?.lines[Number(input.dataset.sdocRow)],field=input.dataset.sdocField;
    if(!row||!BOM_FIELDS.some(([key])=>key===field))return;
    row[field]=input.value;candidate.edited=true;
    if(candidate.review_required){candidate.reviewed=false;const check=dialog.querySelector('[data-sdoc-reviewed="'+input.dataset.sdocCandidate+'"]');if(check)check.checked=false;}
  });
  dialog.addEventListener('change',event=>{
    if(busy()||!state.package)return;const input=event.target,review=state.package;
    if(input.matches('[data-sdoc-select]')){const candidate=review.candidates[Number(input.dataset.sdocSelect)],target=candidate&&packageTarget(review,candidate);if(candidate)candidate.selected=!!input.checked&&!!target?.editable;}
    else if(input.matches('[data-sdoc-target]')){const candidate=review.candidates[Number(input.dataset.sdocTarget)],target=review.data.targets.find(row=>packageTargetId(row)===input.value);if(candidate){candidate.target_id=target?packageTargetId(target):'';candidate.selected=!!target?.editable;if(candidate.target_id!==(candidate.matched_spool_id||candidate.matched_requirement_id||'')){candidate.review_required=true;candidate.reviewed=false;}}}
    else if(input.matches('[data-sdoc-reviewed]')){const candidate=review.candidates[Number(input.dataset.sdocReviewed)];if(candidate)candidate.reviewed=!!input.checked;}
    else return;
    review.error='';render();
  });
  dialog.addEventListener('keydown',event=>{if(!event.target.matches('[role="tab"]')||busy()||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const tabs=[...dialog.querySelectorAll('[role="tab"]')].map(tab=>tab.dataset.sdocTabChoice),current=tabs.indexOf(state.view==='upload'?'upload':state.tab),next=event.key==='Home'?tabs[0]:event.key==='End'?tabs.at(-1):tabs[(current+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length];navigate(next);});
  dialog.addEventListener('cancel',event=>{event.preventDefault();close(false,true);});dialog.addEventListener('close',()=>{if(!dialog.open&&state.target)close(true,true);});node('spoolDocumentsClose').onclick=()=>close(false,true);node('spoolDocumentsDone').onclick=()=>close(false,true);node('spoolDocumentsBack').onclick=()=>back();
  document.addEventListener('click',event=>{const target=event.target.closest?.('[data-sdoc-kind]');if(!target||target.disabled)return;event.preventDefault();open({kind:target.dataset.sdocKind,id:target.dataset.sdocId,spool_number:target.dataset.sdocNumber,tab:target.dataset.sdocTab},target);});
  window.FabSpoolDocuments={link,open,navigationState,restoreNavigation,back,canNavigateAway:()=>!state.saving&&!pieceSaving(),cancelPending:()=>close(true,true)};
})();
