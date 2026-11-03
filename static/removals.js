/* Reversible administrator removal with a current, confirmed scope preview. */
(() => {
  'use strict';
  const ROOT='/api/removals',node=id=>document.getElementById(id),enc=encodeURIComponent,arr=v=>Array.isArray(v)?v:[],text=v=>String(v??'');
  const state={active:false,sequence:0,loading:false,records:[],query:'',error:'',modal:null,modalSequence:0,saving:false};
  const admin=()=>me?.role==='admin',labels={order:'P.O',gpn_record:'GPN record',gpn:'Assembly record',spool_line:'Spool entry',item:'Physical item'};
  const button=(action,label,kind='',id='',cls='',disabled=false)=>`<button type="button" class="${esc(cls)}" data-removal-action="${esc(action)}" data-removal-kind="${esc(kind)}" data-removal-id="${esc(id)}"${disabled?' disabled':''}>${esc(label)}</button>`;
  function errorText(error){try{const d=JSON.parse(error.message);if(d.message)return d.message;if(d.blockers)return arr(d.blockers).join(' ');if(Array.isArray(d))return d.map(x=>x.msg||'Check the entered value.').join(' ');}catch(_){}return text(error.message||'The current record could not be checked.');}
  const date=v=>v?new Date(v).toLocaleString():'—';
  function countView(counts={}){return `<div class="fr-counts">${[['orders','P.O.s'],['gpn_records','GPN records'],['gpns','Assembly records'],['spool_lines','Spool entries'],['items','Physical items']].filter(([key])=>!['gpn_records','spool_lines'].includes(key)||Object.hasOwn(counts,key)).map(([key,label])=>`<div><strong>${Number.isInteger(counts[key])?counts[key]:'—'}</strong><span>${label}</span></div>`).join('')}</div>`;}
  function renderList(){
    if(!state.active)return;const q=state.query.trim().toLowerCase(),rows=state.records.filter(r=>!q||[r.title,r.record_id,r.reason].some(v=>text(v).toLowerCase().includes(q)));
    let html=`<div class="fr-head"><div><span class="fr-eyebrow">Administrator controls</span><h1>Removed records</h1><p>P.O.s, GPNs, assemblies, spool entries and physical copies removed from working lists. Restore an entry to return its records with their original IDs and history.</p></div><div class="actions">${button('orders','Purchase orders')}${button('items','Items')}${button('refresh-list','Refresh','','','',state.loading)}</div></div>`;
    if(state.error)html+=`<div class="fr-error" role="alert"><strong>Removed records could not be verified.</strong><p>${esc(state.error)}</p></div>`;
    else if(state.loading)html+='<div class="card" role="status">Loading removed records…</div>';
    else {html+=`<div class="field fr-search"><label for="removedSearch">Find a removed record</label><input id="removedSearch" type="search" placeholder="P.O, GPN, assembly, spool or removal reason" value="${esc(state.query)}"></div>`;
      if(!rows.length)html+=`<section class="card"><h2>${state.records.length?'No matching removed records':'No removed records'}</h2><p>${state.records.length?'Clear the search to see the other records.':'Removed P.O.s, GPNs, assembly records, spool entries and physical copies will appear here.'}</p></section>`;
      else html+=`<div class="fr-records">${rows.map(r=>`<section class="card fr-record"><div class="fr-head"><div><span class="fr-kind">${esc(labels[r.kind]||r.kind)}</span><h2>${esc(r.title)}</h2><small>${esc(r.record_id)}</small></div><div class="actions">${r.kind==='item'||r.kind==='order'?button('view','View retained records',r.kind,r.record_id):''}${button('restore','Restore',r.kind,r.record_id,'primary')}</div></div>${countView(r.counts)}<p><strong>Reason:</strong> ${esc(r.reason)}</p><p class="fr-note">Removed ${esc(date(r.at))} · ${esc(r.actor||'')}</p></section>`).join('')}</div>`;
    }
    node('removalsContent').innerHTML=html;node('removalsContent').setAttribute('aria-busy',String(state.loading));
    const search=node('removedSearch');if(search)search.oninput=()=>{state.query=search.value;const caret=search.selectionStart;renderList();node('removedSearch')?.focus();node('removedSearch')?.setSelectionRange(caret,caret);};
  }
  async function loadList(){
    if(!admin()||!state.active||state.loading)return;const sequence=++state.sequence;state.loading=true;state.error='';renderList();
    try{const result=await api(ROOT);if(sequence!==state.sequence||!state.active)return;if(!Array.isArray(result?.records)||result.permissions?.can_remove!==true||!result.records.every(r=>labels[r.kind]&&typeof r.record_id==='string'))throw Error('The removed-record list could not be verified. Refresh before restoring a record.');state.records=result.records;}
    catch(error){if(sequence===state.sequence&&state.active){state.records=[];state.error=errorText(error);}}
    finally{if(sequence===state.sequence&&state.active){state.loading=false;renderList();}}
  }
  async function openList(){if(!admin())return;show('removalsPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;state.active=true;state.loading=false;state.query='';history.replaceState(null,'','/?removed-records=1');await loadList();}
  function preserve(){const m=state.modal;if(!m)return;m.confirmation=node('removalConfirmation')?.value??m.confirmation;m.reason=node('removalReason')?.value??m.reason;}
  function renderDialog(){
    const m=state.modal;if(!m)return;const restore=m.action==='restore',verb=restore?'Restore':'Remove',p=m.preview;
    node('removalDialogTitle').textContent=verb+' '+(p?.title||'record');
    let html='';
    if(m.error)html+=`<div class="fr-error" role="alert">${esc(m.error)}${m.stale?'<p>Review the current records before submitting another decision.</p>':''}</div>`;
    if(m.loading)html+='<p role="status">Checking the current record and everything linked to it…</p>';
    else if(p){
      html+=`<p>${restore?'The records below will return to their working lists. Original QR IDs, links and history are retained.':'This removes the records below from working lists. Their QR IDs, production records and quality history are retained. An administrator can restore them later.'}</p>${countView(p.counts)}`;
      if(p.affected.length)html+=`<details class="fr-scope"><summary>View ${p.affected.length} affected record${p.affected.length===1?'':'s'}</summary><ul>${p.affected.map(r=>`<li><strong>${esc(r.title)}</strong><small>${esc(r.record_id)}</small></li>`).join('')}</ul></details>`;
      if(p.blockers.length)html+=`<div class="fr-blockers" role="alert"><h3>${restore?'Before restoring':'Before removing'}</h3><ul>${p.blockers.map(v=>`<li>${esc(v)}</li>`).join('')}</ul><p>Complete these steps, then review the current records again.</p></div>`;
      if(p.can_proceed&&!p.blockers.length&&!m.stale)html+=`<div class="field"><label for="removalReason">Reason for ${restore?'restoring':'removing'} *</label><textarea id="removalReason" name="reason" required minlength="4" maxlength="3000"${state.saving?' disabled':''}>${esc(m.reason)}</textarea></div><div class="field"><label for="removalConfirmation">Type <strong>${esc(p.confirmation)}</strong> to confirm *</label><input id="removalConfirmation" name="confirmation" required autocomplete="off" spellcheck="false" value="${esc(m.confirmation)}"${state.saving?' disabled':''}></div>`;
    }
    html+=`<div class="actions fr-dialog-actions">${!m.loading&&(!p||m.stale||p.blockers.length)?button('review','Review current records','','','',state.saving):''}${p&&p.can_proceed&&!p.blockers.length&&!m.stale?`<button id="removalSubmit" type="submit" class="${restore?'primary':'fr-danger'}"${state.saving?' disabled':''}>${state.saving?(restore?'Restoring…':'Removing…'):verb}</button>`:''}${button('cancel','Cancel','','','',state.saving)}</div>`;
    node('removalDialogBody').innerHTML=html;
  }
  function validPreview(p,m){return p&&p.kind===m.kind&&p.record_id===m.id&&p.action===m.action&&typeof p.title==='string'&&typeof p.confirmation==='string'&&p.confirmation.length>0&&Number.isInteger(p.expected_version)&&p.expected_version>=0&&/^[a-f0-9]{64}$/.test(p.preview_token)&&Array.isArray(p.affected)&&p.affected.every(r=>labels[r.kind]&&typeof r.title==='string'&&typeof r.record_id==='string')&&Array.isArray(p.blockers)&&p.blockers.every(v=>typeof v==='string')&&typeof p.can_proceed==='boolean';}
  async function loadPreview(){
    const m=state.modal;if(!m||!admin()||state.saving)return;preserve();const sequence=++state.modalSequence;m.loading=true;m.error='';m.stale=false;m.preview=null;m.confirmation='';renderDialog();
    try{const result=await api(ROOT+'/'+enc(m.kind)+'/'+enc(m.id)+'?action='+m.action);if(sequence!==state.modalSequence||state.modal!==m)return;if(!validPreview(result,m))throw Error('The affected records could not be verified. Review the current records before continuing.');m.preview=result;}
    catch(error){if(sequence===state.modalSequence&&state.modal===m)m.error=errorText(error);}
    finally{if(sequence===state.modalSequence&&state.modal===m){m.loading=false;renderDialog();node('removalReason')?.focus();}}
  }
  async function open(options={}){
    if(!admin()||!labels[options.kind]||!options.id||state.saving)return;
    state.modalSequence++;state.modal={kind:options.kind,id:text(options.id),action:options.action==='restore'?'restore':'remove',onDone:options.onDone,preview:null,loading:true,error:'',stale:false,confirmation:'',reason:''};renderDialog();
    const dialog=node('recordRemovalDialog');if(!dialog.open)dialog.showModal();await loadPreview();
  }
  function close(force=false){if(state.saving&&!force)return;state.modalSequence++;state.modal=null;state.saving=false;node('recordRemovalDialog')?.close();}
  async function submit(event){
    event.preventDefault();const m=state.modal,p=m?.preview;if(!admin()||!m||!p||state.saving||m.stale||m.loading||!p.can_proceed||p.blockers.length)return;preserve();
    if(m.reason.trim().length<4){m.error='Enter a reason of at least four characters.';renderDialog();node('removalReason')?.focus();return;}
    if(m.confirmation.trim()!==p.confirmation){m.error='Type the displayed identifier exactly to confirm.';renderDialog();node('removalConfirmation')?.focus();return;}
    const sequence=state.modalSequence;state.saving=true;m.error='';renderDialog();
    try{const result=await api(ROOT+'/'+enc(m.kind)+'/'+enc(m.id)+'/'+m.action,{method:'POST',body:JSON.stringify({expected_version:p.expected_version,preview_token:p.preview_token,confirmation:m.confirmation.trim(),reason:m.reason.trim()})});
      if(sequence!==state.modalSequence||state.modal!==m)return;
      if(result?.kind!==m.kind||result.record_id!==m.id||result.removed!==(m.action==='remove'))throw Error('The saved result could not be verified. Review the current records before continuing.');
      close(true);notify(m.action==='remove'?'Removed from working lists. Records and history are retained.':'Records restored with their original IDs and history.');
      if(typeof m.onDone==='function')await m.onDone(result);else if(state.active)await loadList();
    }catch(error){if(sequence===state.modalSequence&&state.modal===m){m.error=errorText(error);m.stale=error.status===409||!error.status||error.status>=500;state.saving=false;renderDialog();}else notify(errorText(error));}
    finally{if(sequence===state.modalSequence&&state.modal===m){state.saving=false;renderDialog();}}
  }
  async function act(action,kind,id){
    if(action==='cancel')return close();if(action==='review')return loadPreview();if(action==='refresh-list')return loadList();
    if(action==='orders')return window.FabOrders.open();if(action==='items')return listItems();
    if(action==='restore')return open({kind,id,action:'restore',onDone:loadList});
    if(action==='view')return kind==='order'?window.FabOrders.open({po:id}):openItem(id);
  }
  function decorateItem(item){
    const removal=item?.removal,removed=removal?.removed===true,banner=node('itemRemovalNotice'),remove=node('removeItemBtn'),restore=node('restoreItemBtn');
    if(banner){banner.classList.toggle('hidden',!removed);banner.innerHTML=removed?`<strong>Removed record · History only</strong><p>This item is removed from working lists. Production changes and handoffs are unavailable until its removed group is restored.</p>${removal.reason?`<p><strong>Reason:</strong> ${esc(removal.reason)}</p>`:''}`:'';}
    if(remove){remove.classList.toggle('hidden',!admin()||removed);remove.onclick=()=>open({kind:'item',id:item.id,onDone:async()=>{offset=0;await listItems();}});}
    if(restore){restore.classList.toggle('hidden',!admin()||!removed);restore.onclick=()=>open({kind:removal?.root_kind||'item',id:removal?.root_id||item.id,action:'restore',onDone:()=>openItem(item.id)});}
    if(!removed){for(const id of ['itemAdminBtn','reopenBtn']){if(node(id))node(id).disabled=false;}if(node('adminReleaseBtn'))node('adminReleaseBtn').disabled=Boolean(item.released);}
    if(removed){for(const id of ['editGooglePart','transferBtn','phoneHandoffBtn','weldBtn','inspectBtn','reworkBtn','releaseBtn','adminReleaseBtn','itemAdminBtn','reopenBtn']){const el=node(id);if(el){el.disabled=true;el.classList.add('hidden');}}node('reworkRecords')?.querySelectorAll('.close-rw').forEach(el=>{el.disabled=true;el.classList.add('hidden');});}
  }
  for(const id of ['removalsContent','removalDialogBody'])node(id).addEventListener('click',event=>{const c=event.target.closest('[data-removal-action]');if(!c||c.disabled)return;return act(c.dataset.removalAction,c.dataset.removalKind,c.dataset.removalId);});
  node('recordRemovalForm').onsubmit=submit;node('recordRemovalDialog').addEventListener('cancel',event=>{event.preventDefault();close();});
  node('navRemoved').onclick=openList;
  window.FabRemovals={open,openList,decorateItem,cancelPending(){state.active=false;state.sequence++;state.loading=false;close(true);}};
})();

