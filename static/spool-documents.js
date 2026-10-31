/* Spool-scoped BOM files and complete isometric drawing sets. */
(() => {
  'use strict';
  const ROOT='/api/spool-documents',node=id=>document.getElementById(id),arr=value=>Array.isArray(value)?value:[],enc=encodeURIComponent;
  const state={target:null,sequence:0,data:null,tab:'bom',loading:false,working:false,saving:false,error:'',notice:'',trigger:null,controller:null,drafts:null,viewer:null};
  const fresh=()=>({files:[],sheet:'',revision:'',reason:'',preview:null,error:'',stale:false,expanded:false});
  const idOK=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(value);
  const fileUrl=value=>typeof value==='string'&&/^\/api\/spool-documents\/files\/[A-Za-z0-9_-]{1,100}(?:\?download=1)?$/.test(value)?value:'';
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
  function invalidatePreview(draft){draft.preview=null;draft.error='';draft.stale=false;}
  function contextView(){
    const c=state.data.context,physical=c.kind==='spool';
    return `<dl class="sdoc-context">${[['P.O.',c.purchase_order||c.project_id],['Assembly',c.assembly_number||c.assembly_id],['Spool number',c.spool_number],...(physical?[['Unique spool ID',c.item_id]]:[])].filter(row=>row[1]).map(([name,value])=>`<div><dt>${esc(name)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl><p class="sdoc-scope">${physical?'Uploads here apply to this unique physical spool. A drawing or BOM from its assembly setup is shown until a file is uploaded for this individual spool.':'Uploads here apply to this spool number within the P.O. and assembly shown above. Each physical copy created from this setup can view these files. You can also upload a separate version on an individual spool.'}</p>`;
  }
  function table(bom,caption='Bill of material'){
    if(!bom||!Array.isArray(bom.lines))return '';
    const columns=[['item','Item'],['quantity','Qty'],['unit','Unit'],['part_number','Part / TAS number'],['description','Description'],['size','Size'],['material','Material'],['length','Length'],['notes','Notes']];
    const shown=columns.filter(([key])=>['item','quantity','description'].includes(key)||bom.lines.some(row=>row[key]!==undefined&&row[key]!==null&&String(row[key]).length));
    return `<p class="sdoc-meta">${bom.lines.length} material line${bom.lines.length===1?'':'s'} · Quantities for one spool${bom.sheet?' · Worksheet: '+esc(bom.sheet):''}</p>${arr(bom.warnings).map(w=>`<p class="sdoc-warning">${esc(w)}</p>`).join('')}<div class="sdoc-table" tabindex="0" role="region" aria-label="${esc(caption)}"><table><caption>${esc(caption)}</caption><thead><tr>${shown.map(([,name])=>`<th scope="col">${esc(name)}</th>`).join('')}</tr></thead><tbody>${bom.lines.map(row=>`<tr>${shown.map(([key])=>`<td>${esc(row[key]??'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function documentActions(doc){
    const view=fileUrl(doc.view_url),download=fileUrl(doc.download_url),pdf=doc.media_type==='application/pdf';
    return `<div class="sdoc-actions">${Array.isArray(doc.bom?.lines)?button('view-grid','View BOM',`data-sdoc-document="${esc(doc.id)}"`,true):pdf&&view?`<a class="sdoc-primary-link" href="${esc(view)}" target="_blank" rel="noopener noreferrer">${doc.kind==='isometric'?'View full isometric':'View BOM'}</a>`:''}${pdf&&view?button('preview-saved','Preview all pages',`data-sdoc-document="${esc(doc.id)}"`):''}${download?`<a href="${esc(download)}" download>Download ${doc.kind==='isometric'?'drawing file':'BOM file'}</a>`:''}</div>`;
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
  function uploadForm(){
    const d=state.data,draft=state.drafts[state.tab],drawing=state.tab==='isometric',saved=d.active[state.tab],limits=d.limits||{},editable=d.editable&&d.permissions?.can_upload!==false;
    if(!editable)return `<p class="sdoc-locked">${esc(d.locked_reason||'Your position can view these documents. An employee with upload permission can add or revise them.')}</p>`;
    const open=!saved||draft.expanded||draft.files.length>0;
    return `<details class="sdoc-upload"${open?' open':''}><summary>${saved?'Upload a new '+(drawing?'drawing revision':'BOM revision'):'Upload '+(drawing?'isometric drawings':'bill of material')}</summary><div class="sdoc-upload-inner"><p>${drawing?'Choose the full PDF from your computer or scanner. On a phone, use the camera to add each page. Arrange the files in drawing-page order before previewing.':'Upload the BOM for this spool as .xlsx, .csv, or a scanned .pdf. For Excel files with multiple worksheets, select the spool worksheet.'}</p><div class="sdoc-actions"><label class="sdoc-file-button" for="sdocFileInput">${drawing?'Choose PDF / scanned pages':'Choose BOM file'}<input id="sdocFileInput" type="file" accept="${drawing?'.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png':'.xlsx,.csv,.pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv,application/pdf'}"${drawing?' multiple':''}${busy()?' disabled':''}></label>${drawing?`<label class="sdoc-file-button" for="sdocCameraInput">Scan a page with camera<input id="sdocCameraInput" type="file" accept="image/jpeg,image/png" capture="environment"${busy()?' disabled':''}></label>`:button('template','Download BOM template','',false,busy())}</div><p class="sdoc-meta">${limits.max_total_bytes?'Up to '+bytes(limits.max_total_bytes)+' per upload. ':''}${drawing?'Add every drawing page; more pages can be added before saving.':'BOM quantities must be for one spool. Files are linked only to the selected spool scope.'}</p>${filesView(draft)}${!drawing&&draft.files.some(entry=>/\.xlsx$/i.test(entry.file.name))?`<div class="field"><label for="sdocSheet">Worksheet name (if the workbook has multiple sheets)</label><input id="sdocSheet" value="${esc(draft.sheet)}" maxlength="100" autocomplete="off" placeholder="Preview to see available worksheets"${busy()?' disabled':''}></div>`:''}${draft.error?`<div class="sdoc-error" role="alert"><p>${esc(draft.error)}</p>${draft.stale?button('reload','Reload saved documents','',false,busy()):''}</div>`:''}${previewView(draft)}<div class="sdoc-upload-fields"><div class="field"><label for="sdocRevision">Drawing / BOM revision (optional)</label><input id="sdocRevision" maxlength="80" value="${esc(draft.revision)}" placeholder="For example: 2 or A"${busy()?' disabled':''}></div><div class="field"><label for="sdocReason">Reason for upload</label><input id="sdocReason" maxlength="3000" value="${esc(draft.reason)}" placeholder="For example: Initial spool drawing set"${busy()?' disabled':''}></div></div><div class="sdoc-actions">${button('preview',state.working?'Checking files…':'Preview selected files','',false,busy()||!draft.files.length)}${button('save',state.saving?'Saving…':'Save '+(drawing?'isometric drawings':'BOM'),'',true,busy()||!draft.preview||draft.preview.sheet_required||draft.stale)}</div><p class="sdoc-meta">Previewing does not save a file. Saving keeps prior versions available in History.</p></div></details>`;
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
    content.innerHTML=contextView()+`<div class="sdoc-tabs" role="tablist" aria-label="Spool documents">${[['bom','Bill of material'],['isometric','Isometric drawings'],['history','History']].map(([kind,caption])=>`<button id="sdoc-tab-${kind}" type="button" role="tab" aria-selected="${state.tab===kind}" aria-controls="sdocPanel" tabindex="${state.tab===kind?0:-1}" data-sdoc-tab-choice="${kind}"${busy()?' disabled':''}>${caption}</button>`).join('')}</div>${state.notice?`<p class="sdoc-notice" role="status">${esc(state.notice)}</p>`:''}${state.error?`<p class="sdoc-error" role="alert">${esc(state.error)}</p>`:''}<div id="sdocPanel" role="tabpanel" aria-labelledby="sdoc-tab-${state.tab}">${state.tab==='history'?historyView():savedDocument()+uploadForm()}</div>`;
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
  async function preview(){
    if(busy()||!state.data?.editable||state.tab==='history')return;
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
    try{const result=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id)+'/upload',{method:'POST',body:multipart(kind,draft,true)});if(sequence!==state.sequence||!dialog.open)return;if(!valid(result))throw Error('The saved response did not match this spool. Reload saved documents before continuing.');state.data=result;clearDraft(draft);state.drafts[kind]=fresh();state.notice=label(kind)+' saved for '+result.context.spool_number+'.';document.dispatchEvent(new CustomEvent('fabtrace:spool-documents-saved',{detail:{kind:state.target.kind,id:state.target.id,document_kind:kind,data:result}}));}
    catch(error){if(sequence===state.sequence){draft.error=errorText(error);draft.stale=error.status===409||!error.status;if(draft.stale)draft.error+=' Reload saved documents before trying another upload; the previous request may have been saved.';}}
    finally{if(sequence===state.sequence){state.saving=false;render();}}
  }
  async function load(){
    if(!state.target||state.saving)return;state.controller?.abort();const sequence=++state.sequence;state.controller=new AbortController();state.loading=true;state.error='';state.working=false;render();
    try{const d=await request(ROOT+'/'+state.target.kind+'/'+enc(state.target.id),{signal:state.controller.signal});if(sequence!==state.sequence||!dialog.open)return;if(!valid(d))throw Error('The documents returned do not match this spool. Reopen the spool and try again.');state.data=d;for(const draft of Object.values(state.drafts)){draft.stale=false;draft.preview=null;draft.error='';}}
    catch(error){if(sequence===state.sequence&&error.name!=='AbortError')state.error=errorText(error);}
    finally{if(sequence===state.sequence){state.loading=false;state.controller=null;render();}}
  }
  async function open(target,trigger=document.activeElement){
    if(!me||state.saving||!target||!['spools','requirements'].includes(target.kind)||!idOK(target.id))return;
    state.controller?.abort();state.sequence++;clearDrafts();state.target={kind:target.kind,id:target.id,spool_number:target.spool_number||''};state.tab=target.tab==='isometric'?'isometric':'bom';state.data=null;state.error='';state.notice='';state.viewer=null;state.trigger=trigger;state.working=false;
    if(!dialog.open)dialog.showModal();node('spoolDocumentsClose').focus();await load();
  }
  function close(force=false){
    if(state.saving&&!force)return;const trigger=state.trigger;state.sequence++;state.controller?.abort();state.controller=null;state.loading=false;state.working=false;state.saving=false;clearDrafts();state.target=null;state.data=null;state.viewer=null;state.error='';state.notice='';state.trigger=null;
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
    if(action==='preview-saved'||action==='view-grid'){state.viewer=target.dataset.sdocDocument;render();if(state.tab!=='history'&&action==='view-grid')node('sdocSavedGrid')?.scrollIntoView({block:'nearest'});return;}
    if(busy()||state.tab==='history')return;const draft=state.drafts[state.tab],index=Number(target.dataset.sdocIndex);if(!Number.isInteger(index)||index<0||index>=draft.files.length)return;
    if(action==='remove-file'){const [entry]=draft.files.splice(index,1);if(entry.url)URL.revokeObjectURL(entry.url);}
    if(action==='move-up'&&index>0)[draft.files[index-1],draft.files[index]]=[draft.files[index],draft.files[index-1]];
    if(action==='move-down'&&index<draft.files.length-1)[draft.files[index+1],draft.files[index]]=[draft.files[index],draft.files[index+1]];
    invalidatePreview(draft);render();
  });
  dialog.addEventListener('keydown',event=>{if(!event.target.matches('[role="tab"]')||busy()||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const tabs=['bom','isometric','history'],current=tabs.indexOf(state.tab);state.tab=event.key==='Home'?tabs[0]:event.key==='End'?tabs[2]:tabs[(current+(event.key==='ArrowRight'?1:2))%3];render();node('sdoc-tab-'+state.tab).focus();});
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.addEventListener('close',()=>{if(state.target)close(true);});node('spoolDocumentsClose').onclick=()=>close();node('spoolDocumentsDone').onclick=()=>close();
  document.addEventListener('click',event=>{const target=event.target.closest?.('[data-sdoc-kind]');if(!target||target.disabled)return;event.preventDefault();open({kind:target.dataset.sdocKind,id:target.dataset.sdocId,spool_number:target.dataset.sdocNumber,tab:target.dataset.sdocTab},target);});
  window.FabSpoolDocuments={link,open,cancelPending:()=>close(true)};
})();
