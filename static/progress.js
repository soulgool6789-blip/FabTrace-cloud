/* Read-only project and physical-item progress. No completion is inferred from missing history. */
(() => {
  'use strict';
  const itemNumberText=(row,label,tag='span')=>row.kind==='spool'&&window.FabFlowStatus?.spoolText?window.FabFlowStatus.spoolText(row,label,tag):`<${tag}>${esc(label)}</${tag}>`;
  const ROOT='/api/progress',node=id=>document.getElementById(id),encode=encodeURIComponent;
  const arr=v=>Array.isArray(v)?v:[],text=v=>String(v??''),num=v=>Number.isFinite(Number(v))?Number(v):0;
  const state={active:false,sequence:0,project:'',projects:[],detail:null,status:'all',subproject:'',kind:'all',query:'',sort:'status',projectQuery:''};
  const names={wip:'WIP',finished:'Finished',shipped:'Shipped',delivered:'Delivered',component:'Component',spool:'Spool',assembly:'Assembly',unplanned:'Needs plan'};
  const button=(action,label,id='',cls='')=>`<button type="button" class="${esc(cls)}" data-progress-action="${esc(action)}" data-progress-id="${esc(id)}">${esc(label)}</button>`;
  const option=(value,label,current)=>`<option value="${esc(value)}"${text(value)===text(current)?' selected':''}>${esc(label)}</option>`;
  const tag=(key,label)=>`<span class="fp-tag ${esc(text(key).replace(/[^a-z_-]/gi,''))}">${esc(label||names[key]||key)}</span>`;
  const pct=v=>Math.max(0,Math.min(100,num(v)));
  const meter=(value,label,detail='',finished=false)=>`<div class="fp-meter${finished?' fp-finished':''}"><div class="fp-meter-label"><span>${esc(label)}</span><strong>${pct(value).toFixed(pct(value)%1?1:0)}%</strong></div><progress max="100" value="${pct(value)}" aria-label="${esc(label)}">${pct(value)}%</progress>${detail?`<small>${esc(detail)}</small>`:''}</div>`;
  function errorText(error){try{const value=JSON.parse(error.message);if(value.message)return value.message;}catch(_){}return error.message||'The progress view could not be loaded.';}
  function url(){const q=new URLSearchParams({progress:'1'});if(state.project)q.set('project',state.project);history.replaceState(null,'','/?'+q.toString());}
  function head(title,description,controls=''){return `<div class="fp-head"><div><div class="fp-eyebrow">CLM · Registered production scope</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div><div class="actions">${controls}${button('refresh','Refresh')}</div></div>`;}
  function metrics(counts){return `<div class="fp-metrics">${[['Registered parts',counts.total_parts,'Known physical items in this project'],['WIP',counts.wip,'Fabrication still open'],['Fabrication finished',counts.finished,'Includes shipped and delivered items'],['Blocked',counts.blocked,'Review current quality or scope blockers']].map(([label,value,help])=>`<div class="fp-metric"><span>${label}</span><strong>${num(value)}</strong><small>${help}</small></div>`).join('')}</div>`;}
  function note(){return '<p class="fp-note">Progress is calculated from registered physical records. Missing BOM items are not assumed complete. Fabrication finish, Job Packet approval, shipment, and packet handover are separate milestones.</p>';}
  function home(){
    const query=state.projectQuery.trim().toLowerCase(),rows=state.projects.filter(row=>!query||[row.id,row.name,row.client].some(v=>text(v).toLowerCase().includes(query)));
    let html=head('Project progress','Follow each project from WIP to finished fabrication, then inspect its Job Packet and handover records.');
    html+=`<div class="fp-filters"><div class="field fp-search"><label for="progressProjectSearch">Find a project</label><input id="progressProjectSearch" type="search" value="${esc(state.projectQuery)}" placeholder="Project ID, name or customer"></div></div>`;
    if(!rows.length)return html+`<div class="fp-empty"><strong>No projects match this view</strong><p>Create the structured project in Projects &amp; welds, or clear the search.</p>${button('tracking','Open Projects & welds')}</div>`;
    html+='<div class="fp-cards">'+rows.map(row=>`<section class="fp-card"><span class="fp-eyebrow">${esc(row.id)}</span><h2>${button('project',row.name,row.id,'fp-link')}</h2><p>${esc(row.client||'Customer not specified')}</p>${meter(row.finished_percent,'Registered parts finished',`${num(row.finished)} of ${num(row.total_parts)} registered physical items`,true)}<div class="fp-tags">${tag('wip',`${num(row.wip)} WIP`)}${tag('finished',`${num(row.finished)} finished`)}${tag('shipped',`${num(row.shipped)} shipped`)}${tag('delivered',`${num(row.delivered)} delivered`)}</div>${num(row.blocked)?`<p>${num(row.blocked)} item(s) currently blocked.</p>`:''}${num(row.planning_needed)?`<p>${num(row.planning_needed)} item(s) need a structured plan or route.</p>`:''}<div class="actions">${button('project','View parts',row.id,'primary')}${button('dossier-project','Job Packets',row.id)}</div></section>`).join('')+'</div>';
    return html+note();
  }
  function filters(){return `<div class="fp-filters"><div class="field"><label for="progressStatus">Production status</label><select id="progressStatus">${[['all','All parts'],['wip','WIP'],['finished','Finished · includes dispatched'],['shipped','Shipped'],['delivered','Delivered']].map(([v,l])=>option(v,l,state.status)).join('')}</select></div><div class="field"><label for="progressSubproject">Work package</label><select id="progressSubproject">${option('','All work packages',state.subproject)}${arr(state.detail.subprojects).map(row=>option(row.id,row.name||row.id,state.subproject)).join('')}</select></div><div class="field"><label for="progressKind">Record type</label><select id="progressKind">${[['all','All types'],['component','Components'],['spool','Spools'],['assembly','Assemblies'],['unplanned','Needs plan']].map(([v,l])=>option(v,l,state.kind)).join('')}</select></div><div class="field"><label for="progressSort">Sort parts</label><select id="progressSort">${[['status','WIP to finished'],['progress_asc','Lowest progress first'],['progress_desc','Highest progress first'],['id','Tracking ID']].map(([v,l])=>option(v,l,state.sort)).join('')}</select></div><div class="field fp-search"><label for="progressSearch">Find a part</label><input id="progressSearch" type="search" value="${esc(state.query)}" placeholder="Tracking ID or part number"></div>${button('search','Search')}</div>`;}
  function rowMeter(row){
    if(row.progress_basis==='recorded_steps')return meter(row.progress_percent,'Recorded route steps',`${num(row.completed_steps)} of ${num(row.total_steps)} steps recorded${num(row.not_recorded_steps)?`; ${num(row.not_recorded_steps)} earlier step(s) not recorded`:''}`);
    if(row.progress_basis==='weld_completion')return meter(row.progress_percent,'Recorded weld completion',`${num(row.completed_welds)} of ${num(row.planned_welds)} planned joints complete; ${num(row.qa_accepted)} QA accepted`);
    if(row.progress_basis==='qa_release')return meter(row.progress_percent,'QA release',row.released?'Current quality release recorded':'Quality release remains open',Boolean(row.released));
    return meter(0,'No production progress recorded','Set up the actual plan or route.');
  }
  function partsMeter(row){const p=row.parts,t=p?.totals;if(!p?.configured)return '';const required=num(t?.required_qty),prepared=num(t?.prepared_qty);return required>0?meter(prepared/required*100,'Required pieces prepared',`${prepared} of ${required} required pieces; ${num(t.assigned_qty)} assigned; ${num(t.short_qty)} still to assign`):'<small>Required parts quantities need verification.</small>';}
  function board(){
    const d=state.detail,c=d.counts||{},project=d.project;
    let html=head(project.name,`${project.id}${project.client?' · '+project.client:''}`,button('home','All projects')+button('dossier-project','Project Job Packets',project.id)+button('guide-project','Guide & setup',project.id));
    html+=metrics(c)+`<section class="fp-card">${meter(c.finished_percent,'Registered parts finished',`${num(c.finished)} of ${num(c.total_parts)} known physical items`,true)}<div class="fp-tags">${tag('shipped',`${num(c.shipped)} shipped`)}${tag('delivered',`${num(c.delivered)} delivered`)}${num(c.planning_needed)?tag('pending',`${num(c.planning_needed)} need planning`):''}</div>${note()}</section>`+filters();
    const rows=arr(d.items);
    html+=`<p class="fp-note">${rows.length} matching part${rows.length===1?'':'s'}${d.as_of?' · Calculated '+esc(new Date(d.as_of).toLocaleString()):''}. Finished includes items subsequently shipped or delivered. Route history can remain below 100% when earlier work was adopted with a documented baseline.</p>`;
    if(!rows.length)return html+'<div class="fp-empty"><strong>No parts match these filters</strong><p>Clear a status, type, work-package or search filter. Items must be assigned to this project.</p></div>';
    html+='<div class="fp-card tablewrap"><table class="fp-table"><thead><tr><th>Physical item</th><th>Status</th><th>Recorded progress</th><th>Current work / quality</th><th>Open record</th></tr></thead><tbody>'+rows.map(row=>`<tr><td>${itemNumberText(row,row.kind==='spool'?(window.FabFlowStatus?.spoolNumber(row)||row.display_code||row.google_part_number||row.id):row.id,'strong')}<small>${esc(names[row.kind]||row.item_kind||row.kind)}${row.google_part_number?' · '+itemNumberText(row,row.google_part_number):''}</small>${row.parent_id?`<small>Parent: ${esc(row.parent_id)}</small>`:''}</td><td>${tag(row.status)}${row.blocked?`<div class="fp-tags">${tag('blocked','Blocked')}</div>`:''}${row.scope_source==='item_project_id'?'<small>Legacy project field; review planning scope.</small>':''}</td><td>${rowMeter(row)}${partsMeter(row)}</td><td>${row.current_title?`<strong>${row.current_step?esc(row.current_step)+' · ':''}${esc(row.current_title)}</strong>`:'<span>No active numbered step</span>'}<small>${esc(row.location||'Location not recorded')} · ${esc(row.handler||'Handler not recorded')}</small>${row.administrative_release?'<small class="fa-release-tag">Administrative release</small>':row.released?'<small>'+esc(row.release_label||'QA release recorded')+'</small>':''}${arr(row.blockers).length?`<small>${esc(row.blockers[0])}</small><details><summary>${row.blockers.length} blocker${row.blockers.length===1?'':'s'}</summary><ul>${row.blockers.map(v=>`<li>${esc(v)}</li>`).join('')}</ul></details>`:''}</td><td><div class="actions">${button('item','Item & QR',row.id)}${button('flow','Process flow',row.id)}${['spool','assembly'].includes(row.kind)?button('weld','Weld records',row.id):''}${row.kind==='spool'?button('spool-parts','Spool parts',row.id):''}${['spool','assembly'].includes(row.kind)?button('dossier-item','Job Packet',row.id):''}</div></td></tr>`).join('')+'</tbody></table></div>';
    return html;
  }
  function render(){if(!state.active)return;node('progressContent').innerHTML=state.detail?board():home();node('progressContent').setAttribute('aria-busy','false');wire();}
  function wire(){
    const homeSearch=node('progressProjectSearch');if(homeSearch)homeSearch.oninput=()=>{state.projectQuery=homeSearch.value;const start=homeSearch.selectionStart;render();node('progressProjectSearch').focus();node('progressProjectSearch').setSelectionRange(start,start);};
    for(const [id,key] of [['progressStatus','status'],['progressSubproject','subproject'],['progressKind','kind'],['progressSort','sort']]){const el=node(id);if(el)el.onchange=()=>{state[key]=el.value;return load();};}
    const search=node('progressSearch');if(search)search.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();state.query=search.value;return load();}};
  }
  async function load(){
    const sequence=++state.sequence;node('progressContent').innerHTML='<div class="fp-state" role="status">Loading registered project progress…</div>';node('progressContent').setAttribute('aria-busy','true');
    try{let result;
      if(state.project){const query=new URLSearchParams({status:state.status,subproject_id:state.subproject,kind:state.kind,search:state.query,sort:state.sort});result=await api(ROOT+'/projects/'+encode(state.project)+'?'+query.toString());}
      else result=await api(ROOT+'/projects');
      if(!state.active||sequence!==state.sequence)return;
      if(state.project)state.detail=result;else{state.detail=null;state.projects=arr(result.projects);}render();url();
    }catch(error){if(!state.active||sequence!==state.sequence)return;node('progressContent').innerHTML=`<div class="fp-state fp-error" role="alert"><strong>Project progress could not be loaded.</strong><p>${esc(errorText(error))}</p><div class="actions">${button('refresh','Try again')}${button('home','All projects')}</div></div>`;}
    finally{if(sequence===state.sequence)node('progressContent').setAttribute('aria-busy','false');}
  }
  async function open(options={}){if(!me)return;show('progressPage');if(typeof stopCloudCamera==='function')stopCloudCamera();current=null;state.active=true;state.project=text(options.project||'');state.detail=null;state.status='all';state.subproject='';state.kind='all';state.query='';state.sort='status';await load();}
  async function act(action,id){
    if(action==='refresh')return load();if(action==='home')return open();if(action==='project')return open({project:id});
    if(action==='search'){state.query=node('progressSearch')?.value||'';return load();}
    if(action==='dossier-project')return window.FabDossier.open({project:id});
    if(action==='guide-project')return window.FabGuide.open({project:id});
    if(action==='spool-parts')return window.FabParts.open({spool:id,project:state.project});
    if(action==='dossier-item')return window.FabDossier.open({project:state.project,item:id});
    if(action==='item')return openItem(id);if(action==='flow')return window.FabFlow.open({item:id,project:state.project});
    if(action==='weld')return window.FabTracking.open({spool:id});if(action==='tracking')return window.FabTracking.open();
  }
  node('progressContent').addEventListener('click',async event=>{const target=event.target.closest('[data-progress-action]');if(!target||target.disabled)return;try{await act(target.dataset.progressAction,target.dataset.progressId||'');}catch(error){notify(errorText(error));}});
  node('navProgress').onclick=()=>open();
  window.FabProgress={open,refresh:load,cancelPending(){state.active=false;state.sequence++;}};
})();
