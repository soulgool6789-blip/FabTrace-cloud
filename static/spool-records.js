/* Read-only selection and download of CLM's seven-sheet spool records. */
(()=>{
  'use strict';
  const ROOT='/api/spool-records';
  const state={rows:[],selected:new Set(),query:'',project:'',max:100,sequence:0,busy:false,returnFocus:null};
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const node=id=>document.getElementById(id);
  let dialog;
  function ensure(){
    if(dialog)return;
    dialog=document.createElement('dialog');dialog.id='spoolRecordsDialog';dialog.className='sr-dialog';
    dialog.setAttribute('aria-labelledby','srTitle');
    dialog.innerHTML=`<div class="sr-head"><div><h2 id="srTitle">Export spool records</h2><p>One spreadsheet per spool, in the CLM Spool Record format.</p></div><button type="button" data-sr-action="close" aria-label="Close spool record selection">Close</button></div><div class="sr-fields"><label for="srSearch">Find a spool, GPN, assembly or purchase order<input id="srSearch" type="search" placeholder="Spool number, GPN, assembly or P.O."></label><button type="button" data-sr-action="all-orders">Show all purchase orders</button></div><div class="sr-tools"><button type="button" data-sr-action="select">Select matching spools</button><button type="button" data-sr-action="clear">Clear selection</button><span id="srCount" aria-live="polite"></span></div><div id="srStatus" role="status" aria-live="polite"></div><div id="srRows" class="sr-rows"></div><div class="sr-footer"><p>Select one spool for Excel or several for a ZIP containing separate workbooks. Each export includes the recorded material, station, weld, inspection and rework history.</p><button type="button" class="primary" id="srDownload" data-sr-action="download" disabled>Download records</button></div>`;
    document.body.appendChild(dialog);
    dialog.addEventListener('click',async event=>{
      const button=event.target.closest('[data-sr-action]');if(!button||button.disabled)return;
      const action=button.dataset.srAction;
      if(action==='close'){dialog.close();return;}
      if(action==='all-orders'){state.project='';await load();return;}
      if(action==='clear'){state.selected.clear();render();return;}
      if(action==='select'){
        const visible=matching(),combined=new Set([...state.selected,...visible.map(row=>row.item_id)]);
        if(combined.size>state.max){status(`Select up to ${state.max} spools per download. Narrow the search or choose individual spools.`,true);return;}
        state.selected=combined;render();return;
      }
      if(action==='download')await download();
    });
    dialog.addEventListener('change',event=>{
      if(!event.target.matches('[data-sr-select]'))return;
      const id=event.target.dataset.srSelect;
      if(event.target.checked&&state.selected.size>=state.max){event.target.checked=false;status(`Select up to ${state.max} spools per download.`,true);return;}
      if(event.target.checked)state.selected.add(id);else state.selected.delete(id);
      counts();
    });
    node('srSearch').addEventListener('input',event=>{state.query=event.target.value;render();});
    dialog.addEventListener('close',()=>{state.sequence++;state.returnFocus?.focus?.();});
  }
  function matching(){const q=state.query.trim().toLocaleLowerCase();return state.rows.filter(row=>!q||[row.display_code,row.item_id,row.purchase_order,row.gpn,row.assembly_number].some(v=>String(v||'').toLocaleLowerCase().includes(q)));}
  function status(message,error=false){node('srStatus').textContent=message;node('srStatus').classList.toggle('sr-error',error);}
  function counts(){node('srCount').textContent=`${state.selected.size} selected · ${matching().length} matching`;node('srDownload').disabled=state.busy||!state.selected.size;node('srDownload').textContent=state.busy?'Preparing download…':state.selected.size===1?'Download Excel':'Download records';}
  function render(){
    const rows=matching();
    node('srRows').innerHTML=rows.length?`<table><thead><tr><th scope="col">Select</th><th scope="col">Spool</th><th scope="col">P.O.</th><th scope="col">GPN</th><th scope="col">Assembly</th></tr></thead><tbody>${rows.map(row=>`<tr><td><input type="checkbox" data-sr-select="${esc(row.item_id)}" aria-label="Select ${esc(row.display_code)}"${state.selected.has(row.item_id)?' checked':''}></td><td><strong>${esc(row.display_code)}</strong><small>${esc(row.item_id)}</small></td><td>${esc(row.purchase_order||'Not linked')}</td><td>${esc(row.gpn||'Not recorded')}</td><td>${esc(row.assembly_number||'Not recorded')}</td></tr>`).join('')}</tbody></table>`:'<p class="sr-empty">No physical spools match this selection.</p>';
    counts();
  }
  async function errorText(response){let data;try{data=await response.json();}catch(_){return response.status===401?'Sign in again to export spool records.':`The export request failed (${response.status}).`;}return typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data);}
  async function load(){
    const sequence=++state.sequence;status('Loading spools…');state.busy=true;counts();
    try{
      const response=await fetch(ROOT+'/spools'+(state.project?'?project_id='+encodeURIComponent(state.project):''),{credentials:'same-origin'});
      if(!response.ok)throw Error(await errorText(response));const result=await response.json();
      if(sequence!==state.sequence||!dialog.open)return;
      if(!Array.isArray(result.spools))throw Error('Spool selection could not be verified.');
      state.rows=result.spools;state.max=result.max_selection||100;
      const permitted=new Set(state.rows.map(row=>row.item_id));state.selected=new Set([...state.selected].filter(id=>permitted.has(id)));
      status(state.project?'Showing the selected purchase order.':'Showing all active physical spools.');render();
    }catch(error){if(sequence===state.sequence){state.rows=[];state.selected.clear();status(error.message,true);render();}}
    finally{if(sequence===state.sequence){state.busy=false;counts();}}
  }
  async function download(){
    if(state.busy||!state.selected.size)return;
    state.busy=true;counts();status('Preparing the selected production records…');
    try{
      const response=await fetch(ROOT+'/export',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_ids:[...state.selected]})});
      if(!response.ok)throw Error(await errorText(response));
      const type=response.headers.get('content-type')||'';
      if(!type.includes('spreadsheetml')&&!type.includes('application/zip'))throw Error('The server did not return an Excel workbook or ZIP.');
      const blob=await response.blob();const disposition=response.headers.get('content-disposition')||'';
      const filename=/filename="([^"]+)"/.exec(disposition)?.[1]||('fabtrace-spool-records'+(type.includes('zip')?'.zip':'.xlsx'));
      const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
      status('Your download is ready. The records reflect the export timestamp.');
    }catch(error){status(error.message,true);}
    finally{state.busy=false;counts();}
  }
  async function open(options={}){
    ensure();state.returnFocus=document.activeElement;state.project=options.project||'';state.query='';state.rows=[];state.selected=new Set(options.item?[options.item]:[]);node('srSearch').value='';
    if(!dialog.open)dialog.showModal();render();await load();node('srSearch').focus();
  }
  function attach(){
    const content=node('productionProgressContent');if(!content)return;
    const actions=content.querySelector('.pp-head .actions');
    if(actions&&!actions.querySelector('[data-sr-open]')){
      const button=document.createElement('button');button.type='button';button.dataset.srOpen='';button.textContent='Export spool records';
      button.addEventListener('click',()=>open({project:node('ppPo')?.value||''}));actions.appendChild(button);
    }
  }
  const content=node('productionProgressContent');
  if(content&&typeof MutationObserver!=='undefined'){new MutationObserver(attach).observe(content,{childList:true,subtree:true});attach();}
  window.FabSpoolRecords={open};
})();
