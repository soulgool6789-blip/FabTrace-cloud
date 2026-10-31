/* Spool-scoped BOM files and complete isometric drawing sets. */
(() => {
  'use strict';
  const ROOT='/api/spool-documents',node=id=>document.getElementById(id),arr=value=>Array.isArray(value)?value:[],enc=encodeURIComponent;
  const state={target:null,sequence:0,data:null,tab:'bom',loading:false,working:false,saving:false,error:'',notice:'',trigger:null,controller:null,drafts:null,viewer:null,package:null};
  const fresh=()=>({files:[],sheet:'',revision:'',reason:'',preview:null,error:'',stale:false,expanded:false});
  const idOK=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(value);
  const fileUrl=value=>typeof value==='string'&&/^\/api\/spool-documents\/files\/[A-Za-z0-9_-]{1,100}(?:\/bom\.xlsx|\?download=1)?$/.test(value)?value:'';
  const BOM_FIELDS=[['item','Item'],['quantity','Qty'],['unit','Unit'],['part_number','Part / TAS number'],['description','Description'],['size','Size'],['material','Material'],['length','Length'],['notes','Notes']];
  const busy=()=>state.loading||state.working||state.saving;
  const bytes=value=>value>=1048576?(value/1048576).toFixed(1)+' MB':Math.max(1,Math.ceil(value/1024))+' KB';
  const label=kind=>kind==='bom'?'Bill of material':'Isometric drawings';
  const button=(action,caption,extra='',primary=false,disabled=false)=>`<button type="button" data-sdoc-action="${action}" ${extra}${disabled?' disabled':''}${primary?' class="primary"':''}>${esc(caption)}</button>`;
  const dialog=document.createElement('dialog');dialog.id='spoolDocumentsDialog';dialog.setAttribute('aria-labelledby','spoolDocumentsTitle');dialog.setAttribute('aria-describedby','spoolDocumentsSubtitle');
  dialog.innerHTML='<div class="sdoc-head"><div><span class="sdoc-eyebrow">Spool documents</span><h2 id="spoolDocumentsTitle">BOM &amp; drawings</h2><p id="spoolDocumentsSubtitle"></p></div><button id="spoolDocumentsClose" type="button" aria-label="Close spool documents">×</button></div><div id="spoolDocumentsContent"></div><div class="sdoc-footer"><p>Files remain linked to the selected spool record.</p><button id="spoolDocumentsDone" type="button">Close</button></div>';
  document.body.appendChild(dialog);

  function link(kind,id,spoolNumber='',caption='BOM & drawings',tab='bom'){
    if(!['requirements','spools'].includes(kind)||!idOK(id))return '';
    return `<button type="button" class="sdoc-link" data-sdoc-kind="${kind}" data-sdoc-id="${esc(id)}" data-sdoc-number="${esc(spoolNumber)}" data-sdoc-tab="${tab==='isometric'?'isometric':'bom'}" aria-haspopup="dialog" aria-controls="spoolDocumentsDialog">${esc(caption)}</button>`;
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
    const c=state.data.context,physical=c.kind==='spool';
    return `<dl class="sdoc-context">${[['P.O.',c.purchase_order||c.project_id],['Assembly',c.assembly_number||c.assembly_id],['Spool number',c.spool_number],...(physical?[['Unique spool ID',c.item_id]]:[])].filter(row=>row[1]).map(([name,value])=>`<div><dt>${esc(name)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl><p class="sdoc-scope">${physical?'Files and generated Excel BOMs here apply to this unique physical spool. Assembly setup documents are inherited until this copy has its own revision.':'Upload a full isometric to find its spool BOM tables. Review the matching spools in this P.O. and assembly, then save the full drawing and a separate Excel BOM for each selected spool. Physical copies inherit these setup files. A copy with its own document revision keeps that individual revision.'}</p>${physical&&state.tab==='isometric'&&state.data.permissions?.can_upload!==false&&idOK(c.requirement_id)?`<div class="sdoc-share"><div><strong>Does this isometric cover several spools?</strong><p>Use assembly setup to share the full drawing and create a separate Excel BOM for every matching spool. Your selected files will carry over.</p></div>${button('use-assembly','Use for all assembly spools','',false,busy())}</div>`:''}`;
  }
  function table(bom,caption='Bill of material'){
    if(!bom||!Array.isArray(bom.lines))return '';
    const columns=[...BOM_FIELDS,['source_page','Drawing page']];
    const shown=columns.filter(([key])=>['item','quantity','description'].includes(key)||bom.lines.some(row=>row[key]!==undefined&&row[key]!==null&&String(row[key]).length));
    return `<p class="sdoc-meta">${bom.lines.length} material line${bom.lines.length===1?'':'s'} · Quantities for one spool${bom.sheet?' · Worksheet: '+esc(bom.sheet):''}</p>${arr(bom.warnings).map(w=>`<p class="sdoc-warning">${esc(w)}</p>`).join('')}<div class="sdoc-table" tabindex="0" role="region" aria-label="${esc(caption)}"><table><caption>${esc(caption)}</caption><thead><tr>${shown.map(([,name])=>`<th scope="col">${esc(name)}</th>`).join('')}</tr></thead><tbody>${bom.lines.map(row=>`<tr>${shown.map(([key])=>`<td>${esc(row[key]??'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function documentActions(doc){
    const view=fileUrl(doc.view_url),download=fileUrl(doc.download_url),excel=fileUrl(doc.excel_url),pdf=doc.media_type==='application/pdf';
    return `<div class="sdoc-actions">${Array.isArray(doc.bom?.lines)?button('view-grid','View BOM',`data-sdoc-document="${esc(doc.id)}"`,true):pdf&&view?`<a class="sdoc-primary-link" href="${esc(view)}" target="_blank" rel="noopener noreferrer">${doc.kind==='isometric'?'View full isometric':'View BOM'}</a>`:''}${pdf&&view?button('preview-saved','Preview all pages',`data-sdoc-document="${esc(doc.id)}"`):''}${doc.kind==='isometric'&&pdf&&state.data.editable?button('create-boms','Create spool BOMs',`data-sdoc-document="${esc(doc.id)}"`,false,busy()):''}${excel?`<a href="${esc(excel)}" download>Download Excel BOM</a>`:''}${download&&(!excel||!doc.bom?.provenance)?`<a href="${esc(download)}" download>Download ${doc.kind==='isometric'?'drawing file':excel?'uploaded BOM':'BOM file'}</a>`:''}</div>`;
  }
  function savedDocument(){
    const doc=state.data.active[state.tab];
    if(!doc)return `<section class="sdoc-empty"><h3>No ${state.tab==='bom'?'bill of material':'isometric drawing'} uploaded yet</h3><p>${state.tab==='bom'?'Choose an Excel workbook, CSV, or a scanned PDF bill of material.':'Upload the complete drawing PDF, or scan and add every page below.'}</p></section>`;
    const viewer=state.viewer===doc.id&&fileUrl(doc.view_url)&&doc.media_type==='application/pdf';
    return `<section class="sdoc-saved"><div class="sdoc-saved-title"><div><span class="sdoc-eyebrow">${doc.inherited?'From assembly / spool setup':'Saved for this spool'}</span><h3>${esc(doc.filename)}</h3></div><span class="sdoc-badge">${doc.revision?'Revision '+esc(doc.revision):'Version '+doc.version}</span></div><p class="sdoc-meta">${doc.page_count?`${doc.page_count} page${doc.page_count===1?'':'s'} · `:''}${bytes(doc.size_bytes||0)} · Uploaded by ${esc(doc.uploaded_by||'—')}${doc.uploaded_at?' · '+esc(new Date(doc.uploaded_at).toLocaleString()):''}</p>${documentActions(doc)}${doc.bom?`<div id="sdocSavedGrid">${table(doc.bom,'BOM · '+state.data.context.spool_number)}</div>`:''}${viewer?`<div class="sdoc-viewer"><iframe src="${esc(fileUrl(doc.view_url))}" title="Complete ${esc(label(doc.kind).toLowerCase())} · ${doc.page_count||''} pages"></iframe><p class="sdoc-meta">Use the viewer controls to move through all pages. You can also open the full file using the link above.</p></div>`:''}</section>`;
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
    return `<div class="sdoc-upload-fields"><div class="field"><label for="sdocRevision">Drawing / BOM revision (optional)</label><input id="sdocRevision" maxlength="80" value="${esc(draft.revision)}" placeholder="For example: 2 or A"${busy()?' disabled':''}></div><div class="field"><label for="sdocReason">Reason for upload</label><input id="sdocReason" maxlength="3000" value="${esc(draft.reason)}" placeholder="For example: Initial spool drawing and BOMs"${busy()?' disabled':''}></div></div>`;
  }
  function editableRows(candidate,index){
    if(!candidate.expanded)return '';
    return `<div class="sdoc-table sdoc-edit-table" tabindex="0" role="region" aria-label="Materials for ${esc(candidate.spool_number||'unidentified spool')}"><table><caption>Quantities for one spool · Check the drawing table before saving</caption><thead><tr>${BOM_FIELDS.map(([,name])=>`<th scope="col">${esc(name)}</th>`).join('')}<th scope="col">Drawing page</th><th scope="col">Edit</th></tr></thead><tbody>${candidate.lines.map((line,row)=>`<tr>${BOM_FIELDS.map(([key,name])=>`<td class="sdoc-cell-${key}"><input type="text"${key==='quantity'?' inputmode="decimal"':''} value="${esc(line[key]??'')}" aria-label="${esc(name)} · line ${row+1} · ${esc(candidate.spool_number||'spool')}" data-sdoc-candidate="${index}" data-sdoc-row="${row}" data-sdoc-field="${key}" maxlength="${key==='notes'?2000:1000}"${busy()?' disabled':''}></td>`).join('')}<td>${esc(line.source_page??candidate.source_pages.join(', '))}</td><td>${button('remove-material','Remove',`data-sdoc-candidate="${index}" data-sdoc-row="${row}"`,false,busy())}</td></tr>`).join('')}</tbody></table></div><div class="sdoc-actions">${button('add-material','Add material line',`data-sdoc-candidate="${index}"`,false,busy()||candidate.lines.length>=(state.data.limits?.max_bom_lines||500))}</div>`;
  }
  function packageView(){
    const review=state.package;if(!review||state.tab!=='isometric')return '';
    const p=review.data,draft=state.drafts.isometric,selected=selectedCandidates(review),physical=state.target.kind==='spools',sourceView=fileUrl(p.source.view_url);
    return `<section class="sdoc-package" aria-labelledby="sdocPackageTitle"><span class="sdoc-eyebrow">${p.source.kind==='saved'?'From saved isometric':'From selected isometric'}</span><h3 id="sdocPackageTitle">Review spool BOMs</h3><p><strong>${esc(p.source.filename)}</strong> · ${Number(p.source.page_count)||0} pages</p><p>${physical?'Saving here applies the drawing and Excel BOM to this unique physical spool. Other spool tables remain unselected until you choose assembly sharing.':'The full drawing will be available from every selected spool below, with a separate Excel BOM for each. Physical copies inherit these setup documents. Copies with their own document revisions keep their individual versions.'}</p>${physical&&idOK(state.data.context.requirement_id)?`<div class="sdoc-share"><div><strong>Apply this full drawing to all corresponding spools</strong><p>Switch to assembly setup to select the other matching spool tables and create their separate Excel BOMs. Your files and saved drawing carry over.</p></div>${button('use-assembly','Use for all assembly spools','',false,busy())}</div>`:''}${arr(p.warnings).map(w=>`<p class="sdoc-warning">${esc(w)}</p>`).join('')}${arr(p.unreadable_pages).length?`<p class="sdoc-warning">Check drawing pages ${esc(p.unreadable_pages.map(page=>typeof page==='object'?(page.page||page.page_number||'?'):page).join(', '))}: some material tables could not be read completely.</p>`:''}${arr(p.excluded_pages).length?`<p class="sdoc-meta">Pages without a usable spool BOM: ${esc(p.excluded_pages.map(page=>typeof page==='object'?(page.page||page.page_number||'?'):page).join(', '))}. All drawing pages remain in the saved PDF.</p>`:''}${!review.candidates.length?'<p class="sdoc-warning">No spool BOM tables were found. You can save the full drawing, then upload a separate BOM for the spool.</p>':''}<div class="sdoc-candidates">${review.candidates.map((candidate,index)=>{
      const target=packageTarget(review,candidate),pages=candidate.source_pages,matched=(candidate.matched_spool_id||candidate.matched_requirement_id||'')===candidate.target_id&&!!candidate.target_id,locked=target&&target.editable===false;
      return `<article class="sdoc-candidate${candidate.selected?' sdoc-candidate-selected':''}" data-sdoc-card="${index}"><div class="sdoc-candidate-heading"><label class="sdoc-check"><input type="checkbox" data-sdoc-select="${index}"${candidate.selected?' checked':''}${busy()||!target||locked?' disabled':''}><span>${esc(candidate.spool_number||'Spool number needs review')}</span></label><span class="sdoc-badge">${locked?'Locked':matched?'Spool found':candidate.target_id?'Assigned for review':'Needs assignment'}</span></div><p class="sdoc-meta">${candidate.lines.length} material line${candidate.lines.length===1?'':'s'} · Drawing page${pages.length===1?'':'s'} ${pages.map(page=>sourceView?`<a href="${esc(sourceView)}#page=${page}" target="_blank" rel="noopener noreferrer">${page}</a>`:String(page)).join(', ')||'not identified'}${candidate.drawing?' · '+esc(candidate.drawing):''}</p><div class="field"><label for="sdocTarget-${index}">${physical?'Unique spool receiving this BOM':'Spool receiving this BOM and full drawing'}</label><select id="sdocTarget-${index}" data-sdoc-target="${index}"${busy()?' disabled':''}><option value="">Choose a matching spool</option>${p.targets.map(item=>`<option value="${esc(packageTargetId(item))}"${candidate.target_id===packageTargetId(item)?' selected':''}${item.editable===false?' disabled':''}>${esc(item.spool_number)}${physical?' · '+esc(item.spool_id):''}${item.editable===false?' · locked':''}</option>`).join('')}</select></div>${!matched&&!candidate.target_id?'<p class="sdoc-warning">No exact match was found in this scope. Assign this table to the correct spool, or leave it unselected.</p>':''}${locked?`<p class="sdoc-locked">${esc(target.locked_reason||'This spool cannot be revised.')}</p>`:''}${target?.has_bom?'<p class="sdoc-meta">Saving creates a new BOM revision. The earlier BOM stays in History.</p>':''}${candidate.warnings.map(w=>`<p class="sdoc-warning">${esc(w)}</p>`).join('')}${button('toggle-materials',candidate.expanded?'Hide material rows':'Review / edit material rows',`data-sdoc-candidate="${index}" aria-expanded="${candidate.expanded}"`,false,busy())}${editableRows(candidate,index)}${candidate.review_required?`<label class="sdoc-check sdoc-review-check"><input type="checkbox" data-sdoc-reviewed="${index}"${candidate.reviewed?' checked':''}${busy()?' disabled':''}><span>I checked this spool assignment and material table against the drawing.</span></label>`:''}</article>`;
    }).join('')}</div>${review.error?`<p class="sdoc-error" role="alert">${esc(review.error)}</p>`:''}${review.stale?`<div class="sdoc-actions">${button('refresh-package','Refresh drawing review','',false,busy())}</div>`:''}${reviewFields(draft)}<p class="sdoc-package-count" role="status">${selected.length} spool${selected.length===1?'':'s'} selected · ${selected.length} separate Excel BOM${selected.length===1?'':'s'}</p><div class="sdoc-actions">${button('save-package',state.saving?'Saving…':`Save drawing + ${selected.length||''} Excel BOM${selected.length===1?'':'s'}`,'',true,busy()||review.stale||!selected.length)}${p.source.kind==='upload'?button('save','Save drawing only for this spool','',false,busy()||draft.stale||!draft.preview):''}${button('cancel-package','Close review','',false,busy())}</div><p class="sdoc-meta">Saving keeps previous document versions in History. Unselected tables are not turned into BOMs.</p></section>`;
  }
  function packageResultView(){
    const result=state.data?.package_result;if(!result||!result.count)return '';
    const records=[...arr(result.requirements).map(row=>({...row,scope:'requirements',identity:row.requirement_id})),...arr(result.spools).map(row=>({...row,scope:'spools',identity:row.spool_id}))];
    return `<section class="sdoc-package-result"><h3>Drawing and Excel BOMs saved</h3>${arr(result.warnings).map(w=>`<p class="sdoc-warning">${esc(w)}</p>`).join('')}<ul>${records.map(row=>{const excel=fileUrl(row.bom_document?.excel_url)||fileUrl(row.bom_document?.download_url);return `<li><strong>${esc(row.spool_number)}</strong><div class="sdoc-actions">${excel?`<a href="${esc(excel)}" download>Download Excel BOM</a>`:''}${link(row.scope,row.identity,row.spool_number,'View spool documents','bom')}</div></li>`;}).join('')}</ul></section>`;
  }
  function uploadForm(){
    const d=state.data,draft=state.drafts[state.tab],drawing=state.tab==='isometric',saved=d.active[state.tab],limits=d.limits||{},editable=d.editable&&d.permissions?.can_upload!==false;
    if(!editable)return `<p class="sdoc-locked">${esc(d.locked_reason||'Your position can view these documents. An employee with upload permission can add or revise them.')}</p>`;
    const open=!saved||draft.expanded||draft.files.length>0,hasPackage=drawing&&!!state.package;
    return `<details class="sdoc-upload"${open?' open':''}><summary>${saved?'Upload a new '+(drawing?'drawing revision':'BOM revision'):'Upload '+(drawing?'isometric drawings':'bill of material')}</summary><div class="sdoc-upload-inner"><p>${drawing?'Choose the full PDF from your computer or scanner. FabTrace reads the spool material tables so you can review and save separate Excel BOMs. On a phone, add each page with the camera, then arrange the files in drawing-page order.':'Upload the BOM for this spool as .xlsx, .csv, or a scanned .pdf. For Excel files with multiple worksheets, select the spool worksheet.'}</p><div class="sdoc-actions"><label class="sdoc-file-button" for="sdocFileInput">${drawing?'Choose PDF / scanned pages':'Choose BOM file'}<input id="sdocFileInput" type="file" accept="${drawing?'.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png':'.xlsx,.csv,.pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv,application/pdf'}"${drawing?' multiple':''}${busy()?' disabled':''}></label>${drawing?`<label class="sdoc-file-button" for="sdocCameraInput">Scan a page with camera<input id="sdocCameraInput" type="file" accept="image/jpeg,image/png" capture="environment"${busy()?' disabled':''}></label>`:button('template','Download BOM template','',false,busy())}</div><p class="sdoc-meta">${limits.max_total_bytes?'Up to '+bytes(limits.max_total_bytes)+' per upload. ':''}${drawing?'Add every drawing page; more pages can be added before saving.':'BOM quantities must be for one spool. Files are linked only to the selected spool scope.'}</p>${filesView(draft)}${!drawing&&draft.files.some(entry=>/\.xlsx$/i.test(entry.file.name))?`<div class="field"><label for="sdocSheet">Worksheet name (if the workbook has multiple sheets)</label><input id="sdocSheet" value="${esc(draft.sheet)}" maxlength="100" autocomplete="off" placeholder="Preview to see available worksheets"${busy()?' disabled':''}></div>`:''}${draft.error?`<div class="sdoc-error" role="alert"><p>${esc(draft.error)}</p>${draft.stale?button('reload','Reload saved documents','',false,busy()):''}</div>`:''}${!hasPackage?previewView(draft)+reviewFields(draft):''}<div class="sdoc-actions">${button('preview',state.working?(drawing?'Reading drawing tables…':'Checking files…'):drawing?'Find spool BOMs / preview':'Preview selected files','',false,busy()||!draft.files.length)}${!hasPackage?button('save',state.saving?'Saving…':'Save '+(drawing?'isometric drawings':'BOM'),'',true,busy()||!draft.preview||draft.preview.sheet_required||draft.stale):''}</div><p class="sdoc-meta">Previewing does not save a file. Saving keeps prior versions available in History.</p></div></details>`;
  }
  function historyView(){
    if(!state.data.history.length)return '<section class="sdoc-empty"><h3>No upload history yet</h3><p>Saved files and prior revisions will appear here.</p></section>';
    return `<div class="sdoc-history">${state.data.history.map(doc=>`<article><div class="sdoc-saved-title"><div><span class="sdoc-eyebrow">${esc(label(doc.kind))}${doc.inherited?' · From assembly setup':''}</span><h3>${esc(doc.filename)}</h3></div><span class="sdoc-badge">${doc.revision?'Revision '+esc(doc.revision):'Version '+doc.version}</span></div><p class="sdoc-meta">${esc(doc.uploaded_by||'—')} · ${esc(doc.uploaded_at?new Date(doc.uploaded_at).toLocaleString():'')}${doc.page_count?' · '+doc.page_count+' pages':''}</p><p>${esc(doc.reason||'')}</p>${documentActions(doc)}${state.viewer===doc.id&&doc.bom?table(doc.bom,'Historical BOM'):state.viewer===doc.id&&fileUrl(doc.view_url)&&doc.media_type==='application/pdf'?`<div class="sdoc-viewer"><iframe src="${esc(fileUrl(doc.view_url))}" title="Previous ${esc(label(doc.kind).toLowerCase())}"></iframe></div>`:''}</article>`).join('')}</div>`;
  }
  function render(){
    node('spoolDocumentsSubtitle').textContent=state.data?'Spool '+state.data.context.spool_number:state.target?.spool_number?'Spool '+state.target.spool_number:'';
    node('spoolDocumentsClose').disabled=state.saving;node('spoolDocumentsDone').disabled=state.saving;
    const content=node('spoolDocumentsContent');content.setAttribute('aria-busy',String(busy()));
    if(state.loading&&!state.data){content.innerHTML='<p class="sdoc-loading" role="status">Loading spool documents…</p>';return;}
    if(state.error&&!state.data){content.innerHTML=`<div class="sdoc-error" role="alert"><p>${esc(state.error)}</p>${button('reload','Try again')}</div>`;return;}
    if(!state.data){content.innerHTML='';return;}
    content.innerHTML=contextView()+`<div class="sdoc-tabs" role="tablist" aria-label="Spool documents">${[['bom','Bill of material'],['isometric','Isometric drawings'],['history','History']].map(([kind,caption])=>`<button id="sdoc-tab-${kind}" type="button" role="tab" aria-selected="${state.tab===kind}" aria-controls="sdocPanel" tabindex="${state.tab===kind?0:-1}" data-sdoc-tab-choice="${kind}"${busy()?' disabled':''}>${caption}</button>`).join('')}</div>${state.notice?`<p class="sdoc-notice" role="status">${esc(state.notice)}</p>`:''}${state.error?`<p class="sdoc-error" role="alert">${esc(state.error)}</p>`:''}${packageResultView()}<div id="sdocPanel" role="tabpanel" aria-labelledby="sdoc-tab-${state.tab}">${state.tab==='history'?historyView():savedDocument()+packageView()+uploadForm()}</div>`;
    const files=node('sdocFileInput');if(files)files.onchange=()=>addFiles([...files.files]);
    const camera=node('sdocCameraInput');if(camera)camera.onchange=()=>addFiles([...camera.files]);
    for(const [id,key] of [['sdocRevision','revision'],['sdocReason','reason'],['sdocSheet','sheet']]){const input=node(id);if(input)input.oninput=()=>{const draft=state.drafts[state.tab];draft[key]=input.value;if(key==='sheet'){invalidatePreview(draft);const save=content.querySelector('[data-sdoc-action="save"]');if(save)save.disabled=true;}};}
    const sheet=node('sdocSheetChoice');if(sheet)sheet.onchange=()=>{const draft=state.drafts[state.tab];draft.sheet=sheet.value;invalidatePreview(draft);render();};
  }
  function addFiles(files){
    if(busy()||!state.data?.editable||state.tab==='history'||!files.length)return;
    const draft=state.drafts[state.tab],limits=state.data.limits||{},drawing=state.tab==='isometric';
    let chosen=drawing?[...draft.files]:[];
    for(const file of files){
      if(!file.size){draft.error='Empty files cannot be uploaded.';render();return;}
      if(limits.max_file_bytes&&file.size>limits.max_file_bytes){draft.error=file.name+' exceeds the '+bytes(limits.max_file_bytes)+' file limit.';render();return;}
      if(!(drawing?/\.(pdf|jpe?g|png)$/i:/\.(xlsx|csv|pdf)$/i).test(file.name)){draft.error=drawing?'Use PDF, JPG, or PNG files for drawing pages.':'Use an XLSX, CSV, or PDF bill of material.';render();return;}
      if(!chosen.some(entry=>entry.file.name===file.name&&entry.file.size===file.size&&entry.file.lastModified===file.lastModified))chosen.push({file,url:null});
    }
    if((limits.max_files&&chosen.length>limits.max_files)||(limits.max_total_bytes&&chosen.reduce((n,entry)=>n+entry.file.size,0)>limits.max_total_bytes)){draft.error='The selected files exceed the upload limit. Use fewer or smaller files.';render();return;}
    if(!drawing)clearDraft(draft);
    for(const entry of chosen)if(!entry.url&&entry.file.type.startsWith('image/'))entry.url=URL.createObjectURL(entry.file);
    draft.files=chosen;draft.sheet='';draft.expanded=true;invalidatePreview(draft);if(!draft.reason&&!state.data.active[state.tab])draft.reason='Initial spool '+(drawing?'isometric drawing set':'bill of material');render();
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
      return {...candidate,source_pages:arr(candidate.source_pages).map(Number).filter(page=>Number.isInteger(page)&&page>0),warnings:[...new Set([...arr(candidate.warnings),...arr(candidate.validation_errors)].map(warning=>typeof warning==='string'?warning:warning.message||warning.detail||'Review the unreadable material fields against the drawing.'))],lines:old?.edited?old.lines.map(line=>({...line})):candidate.lines.map(line=>({...line})),target_id:retained?old.target_id:targetId,selected:retained?old.selected&&retained.editable:!!candidate.selected&&!!target?.editable,reviewed:old?.reviewed??!candidate.review_required,review_required:old?.review_required||!!candidate.review_required,expanded:old?.expanded??(index<2||!!candidate.review_required),edited:!!old?.edited};
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
    const draft=state.drafts.isometric;if(!documentId&&!draft.files.length)return;
    if(documentId&&!idOK(documentId))return;
    state.tab='isometric';state.working=true;state.notice='';draft.error='';state.error='';const sequence=state.sequence;
    state.controller=new AbortController();render();
    const form=new FormData();if(documentId)form.append('document_id',documentId);else for(const entry of draft.files)form.append('files',entry.file,entry.file.name);
    try{
      const data=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/isometric-preview',{method:'POST',body:form,signal:state.controller.signal});
      if(sequence!==state.sequence||!dialog.open)return;
      acceptPackage(data,previous);
      if(!draft.reason.trim())draft.reason=documentId?'Create spool BOMs from saved isometric':'Initial spool drawing and Excel BOMs';
      if(!draft.revision.trim())draft.revision=data.candidates.find(candidate=>candidate.revision)?.revision||'';
      if(previous?.candidates.some(candidate=>candidate.edited))state.notice='Drawing review refreshed. Edited material rows have been kept.';
    }catch(error){if(sequence===state.sequence&&error.name!=='AbortError'){if(state.package)state.package.error=errorText(error);else draft.error=errorText(error);}}
    finally{if(sequence===state.sequence){state.working=false;state.controller=null;render();if(state.package)node('sdocPackageTitle')?.scrollIntoView({block:'start'});}}
  }
  async function useAssembly(){
    const c=state.data?.context;if(busy()||state.target?.kind!=='spools'||!idOK(c?.requirement_id))return;
    const previous=state.package,draft=state.drafts.isometric,source=previous?.data.source,files=source?.kind==='saved'?[]:draft.files.map(entry=>entry.file),savedId=source?.kind==='saved'?source.document_id:state.data.active.isometric?.id;
    const carried={revision:draft.revision,reason:draft.reason},trigger=state.trigger;
    await open({kind:'requirements',id:c.requirement_id,spool_number:c.spool_number,tab:'isometric'},trigger);
    if(!state.data||state.target?.id!==c.requirement_id)return;
    Object.assign(state.drafts.isometric,carried);
    if(files.length){addFiles(files);await previewDrawing('',previous);}
    else if(savedId)await previewDrawing(savedId,previous);
  }
  async function savePackage(){
    const review=state.package;if(busy()||!state.data?.editable||!review||review.stale)return;
    const draft=state.drafts.isometric,selected=selectedCandidates(review);review.error='';
    const fail=message=>{review.error=message;render();};
    if(!selected.length)return fail('Select at least one spool to receive its drawing and Excel BOM.');
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
    const form=new FormData();form.append('review',JSON.stringify({preview_token:review.data.preview_token,reviewed:true,revision:draft.revision.trim(),reason:draft.reason.trim(),mappings}));
    if(review.data.source.kind==='upload')for(const entry of draft.files)form.append('files',entry.file,entry.file.name);
    const sequence=state.sequence;state.saving=true;state.notice='';render();
    try{
      const result=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/isometric-import',{method:'POST',body:form});
      if(sequence!==state.sequence||!dialog.open)return;
      if(!valid(result)||!Number.isInteger(result.package_result?.count)||result.package_result.count<1)throw Error('The saved drawing package could not be verified. Reload the spool documents before saving again.');
      state.data=result;state.package=null;clearDraft(draft);state.drafts.isometric=fresh();state.notice='Full drawing and '+result.package_result.count+' separate Excel BOM'+(result.package_result.count===1?'':'s')+' saved.';
      for(const row of arr(result.package_result.requirements))for(const kind of ['bom','isometric'])document.dispatchEvent(new CustomEvent('fabtrace:spool-documents-saved',{detail:{kind:'requirements',id:row.requirement_id,document_kind:kind,data:result}}));
      for(const row of arr(result.package_result.spools))for(const kind of ['bom','isometric'])document.dispatchEvent(new CustomEvent('fabtrace:spool-documents-saved',{detail:{kind:'spools',id:row.spool_id,document_kind:kind,data:result}}));
    }catch(error){if(sequence===state.sequence){review.error=errorText(error);review.stale=error.status===409||!error.status;draft.stale=review.stale;if(review.stale)review.error+=' Refresh the drawing review before trying again; the previous request may already have been saved.';}}
    finally{if(sequence===state.sequence){state.saving=false;render();}}
  }
  async function preview(){
    if(busy()||!state.data?.editable||state.tab==='history')return;
    if(state.tab==='isometric')return previewDrawing();
    const kind=state.tab,draft=state.drafts[kind];if(!draft.files.length)return;
    const sequence=state.sequence;state.working=true;draft.error='';draft.preview=null;state.notice='';state.controller=new AbortController();render();
    try{const p=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/preview',{method:'POST',body:multipart(kind,draft),signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(p.kind!==kind||(!p.sheet_required&&!/^[a-f0-9]{64}$/i.test(p.selection_sha256||'')))throw Error('The file preview could not be verified. Select the file again.');draft.preview=p;draft.stale=false;}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError')draft.error=errorText(error);}
    finally{if(sequence===state.sequence){state.working=false;state.controller=null;render();}}
  }
  async function save(){
    if(busy()||!state.data?.editable||state.tab==='history')return;
    const kind=state.tab,draft=state.drafts[kind];if(!draft.preview||draft.preview.sheet_required||draft.stale)return;
    if(draft.reason.trim().length<4){draft.error='Enter a reason for this upload (at least 4 characters).';render();node('sdocReason')?.focus();return;}
    const sequence=state.sequence;state.saving=true;state.error='';state.notice='';draft.error='';render();
    try{const result=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/upload',{method:'POST',body:multipart(kind,draft,true)});if(sequence!==state.sequence||!dialog.open)return;if(!valid(result))throw Error('The saved response did not match this spool. Reload saved documents before continuing.');state.data=result;if(kind==='isometric')state.package=null;clearDraft(draft);state.drafts[kind]=fresh();state.notice=label(kind)+' saved for '+result.context.spool_number+'.'+(kind==='isometric'?' No Excel BOM was created.':'');document.dispatchEvent(new CustomEvent('fabtrace:spool-documents-saved',{detail:{kind:state.target.kind,id:state.target.id,document_kind:kind,data:result}}));}
    catch(error){if(sequence===state.sequence){draft.error=errorText(error);draft.stale=error.status===409||!error.status;if(draft.stale)draft.error+=' Reload saved documents before trying another upload; the previous request may have been saved.';}}
    finally{if(sequence===state.sequence){state.saving=false;render();}}
  }
  async function load(){
    if(!state.target||state.saving)return;state.controller?.abort();const sequence=++state.sequence;state.controller=new AbortController();state.loading=true;state.error='';state.working=false;render();
    try{const d=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id),{signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(!valid(d))throw Error('The documents returned do not match this spool. Reopen the spool and try again.');state.data=d;state.package=null;for(const draft of Object.values(state.drafts)){draft.stale=false;draft.preview=null;draft.error='';}}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError')state.error=errorText(error);}
    finally{if(sequence===state.sequence){state.loading=false;state.controller=null;render();}}
  }
  async function open(target,trigger=document.activeElement){
    if(!me||state.saving||!target||!['spools','requirements'].includes(target.kind)||!idOK(target.id))return;
    state.controller?.abort();state.sequence++;clearDrafts();state.package=null;state.target={kind:target.kind,id:target.id,spool_number:target.spool_number||''};state.tab=target.tab==='isometric'?'isometric':'bom';state.data=null;state.error='';state.notice='';state.viewer=null;state.trigger=trigger;state.working=false;
    if(!dialog.open)dialog.showModal();node('spoolDocumentsClose').focus();await load();
  }
  function close(force=false){
    if(state.saving&&!force)return;const trigger=state.trigger;state.sequence++;state.controller?.abort();state.controller=null;state.loading=false;state.working=false;state.saving=false;clearDrafts();state.package=null;state.target=null;state.data=null;state.viewer=null;state.error='';state.notice='';state.trigger=null;
    if(dialog.open)dialog.close();if(!force&&trigger?.isConnected)trigger.focus();
  }
  function template(){
    const content='spool_number,item,quantity,unit,part_number,description,size,material,length,notes,drawing,revision,source_page\r\n';
    const url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'})),anchor=document.createElement('a');anchor.href=url;anchor.download='FabTrace_Spool_BOM_Template.csv';document.body.appendChild(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
  }
  dialog.addEventListener('click',event=>{
    const tab=event.target.closest('[data-sdoc-tab-choice]');if(tab&&!busy()){state.tab=tab.dataset.sdocTabChoice;state.viewer=null;render();node('sdoc-tab-'+state.tab)?.focus();return;}
    const target=event.target.closest('[data-sdoc-action]');if(!target||target.disabled)return;const action=target.dataset.sdocAction;
    if(action==='reload')return load();if(action==='template')return template();if(action==='preview')return preview();if(action==='save')return save();
    if(action==='use-assembly')return useAssembly();
    if(action==='create-boms')return previewDrawing(target.dataset.sdocDocument);
    if(action==='save-package')return savePackage();
    if(action==='refresh-package'){const review=state.package;if(review)return previewDrawing(review.data.source.kind==='saved'?review.data.source.document_id:'',review);return;}
    if(action==='cancel-package'){if(!busy()){state.package=null;render();}return;}
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
    invalidatePreview(draft);render();
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
  dialog.addEventListener('keydown',event=>{if(!event.target.matches('[role="tab"]')||busy()||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const tabs=['bom','isometric','history'],current=tabs.indexOf(state.tab);state.tab=event.key==='Home'?tabs[0]:event.key==='End'?tabs[2]:tabs[(current+(event.key==='ArrowRight'?1:2))%3];render();node('sdoc-tab-'+state.tab).focus();});
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.addEventListener('close',()=>{if(state.target)close(true);});node('spoolDocumentsClose').onclick=()=>close();node('spoolDocumentsDone').onclick=()=>close();
  document.addEventListener('click',event=>{const target=event.target.closest?.('[data-sdoc-kind]');if(!target||target.disabled)return;event.preventDefault();open({kind:target.dataset.sdocKind,id:target.dataset.sdocId,spool_number:target.dataset.sdocNumber,tab:target.dataset.sdocTab},target);});
  window.FabSpoolDocuments={link,open,cancelPending:()=>close(true)};
})();
